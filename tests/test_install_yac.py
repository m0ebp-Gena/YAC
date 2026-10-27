"""Installer safety/flow tests with dependency installs and shortcuts mocked."""
import io
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import install_yac


class Installer(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / "builds/.work/test-installs"
        test_root.mkdir(exist_ok=True)
        # Dropbox may briefly hold directories open after a file operation.
        self.temporary = tempfile.TemporaryDirectory(dir=test_root)
        assert Path(self.temporary.name).resolve().is_relative_to(test_root.resolve())
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.home = self.base / "home with spaces"
        self.home.mkdir()
        (self.source / "yac.py").write_text("# source\n")
        (self.source / "yac.ini").write_text("personal settings must not be copied")
        (self.source / "yac.ini.example").write_text("[yac]\nlang=\ncall=\n")
        (self.source / "error-codes.txt").write_text("INI Error recovery\n")
        (self.source / "KEY-BINDINGS-English.txt").write_text("s then t: tuner\n")
        for name in ["modules", "lang", "rad_cmds"]:
            (self.source / name).mkdir()
            (self.source / name / "data.txt").write_text(name)
        cache = self.source / "modules/__pycache__"
        cache.mkdir()
        (cache / "old.pyc").write_bytes(b"old")

    def run_setup(self, answers, failure=None, platform="linux"):
        with patch.object(install_yac.sys, "platform", platform), patch.object(install_yac.os, "geteuid", return_value=1000, create=True), patch.object(install_yac, "ask", side_effect=answers), patch.object(install_yac.subprocess, "run", side_effect=failure) as commands, patch.object(install_yac, "install_shortcut") as shortcut, redirect_stdout(io.StringIO()) as output:
            result = install_yac.main(self.source, self.home)
        return result, commands, shortcut, output.getvalue()

    def test_enter_accepts_yes_and_eof_cancels(self):
        with patch('builtins.input', return_value='') as entered:
            self.assertTrue(install_yac.ask('Install YAC?'))
            entered.assert_called_once_with('Install YAC? [Y/n] ')
        with patch('builtins.input', side_effect=EOFError), redirect_stdout(io.StringIO()):
            self.assertFalse(install_yac.ask('Install YAC?'))

    def test_pi_decline_stops_wrapper_without_installing(self):
        with patch.object(install_yac.sys, 'platform', 'linux'), patch.object(install_yac.os, 'geteuid', return_value=1000, create=True), patch.object(install_yac, 'ask', return_value=False), patch.object(install_yac.subprocess, 'run') as commands, redirect_stdout(io.StringIO()):
            self.assertEqual(install_yac.main(self.source, self.home, pi=True), 2)
        commands.assert_not_called()
        self.assertFalse((self.home / '.local/yac').exists())

    def test_dependency_commands_capture_output_and_use_private_environment(self):
        result, commands, _, output = self.run_setup([True])
        self.assertEqual(result, 0)
        self.assertIn('Installation Complete', output)
        for call in commands.call_args_list:
            self.assertTrue(call.kwargs.get('capture_output'))

    def test_launcher_asks_once_and_existing_launcher_is_silent(self):
        system = self.base / 'system-bin'
        system.mkdir()
        launcher = self.base / 'run-yac'
        launcher.write_text('#!/bin/sh\n')
        real_path = Path
        def paths(value):
            return system if value == '/usr/local/bin' else real_path(value)
        with patch.object(install_yac, 'Path', side_effect=paths), patch.object(install_yac.os, 'access', return_value=True), patch.object(install_yac, 'ask', return_value=True) as ask, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(install_yac.install_shortcut(launcher, self.home), system / 'yac')
            ask.assert_called_once_with('Create YAC launcher?')
            self.assertEqual(output.getvalue(), '')
            ask.reset_mock()
            self.assertIsNone(install_yac.install_shortcut(launcher, self.home))
            ask.assert_not_called()
            self.assertEqual((system / 'yac').read_text(), launcher.read_text())

    def test_mac_uses_applications_and_leaves_legacy_installation(self):
        legacy = self.home / "yac"
        legacy.mkdir()
        (legacy / "yac.ini").write_text("old settings")
        result, commands, shortcut, output = self.run_setup([True], platform="darwin")
        destination = self.home / "Applications/yac"
        self.assertEqual(result, 0)
        self.assertTrue((destination / "yac.py").is_file())
        self.assertTrue(any('from modules.update_certificates import context; context()' in call.args[0]
                            for call in commands.call_args_list))
        self.assertIn(str(destination / "run-yac"), output)
        self.assertIn(str(destination / ".venv/bin/python"), (destination / "run-yac").read_text())
        self.assertEqual((legacy / "yac.ini").read_text(), "old settings")
        shortcut.assert_called_once_with(destination / "run-yac", self.home)

    def test_language_documents_installed_on_both_platforms(self):
        for language in ('English', 'Deutsch', 'Espanol', 'Polski'):
            guide = self.source / 'doc' / language / 'START-HERE-mac.txt'
            guide.parent.mkdir(parents=True, exist_ok=True)
            guide.write_text('Guide: '+language, encoding='utf-8')
        for platform in ('darwin', 'linux'):
            with self.subTest(platform=platform):
                result, _, _, _ = self.run_setup([True], platform=platform)
                self.assertEqual(result, 0)
                destination = install_yac.installation_directory(self.home, platform)
                for language in ('English', 'Deutsch', 'Espanol', 'Polski'):
                    self.assertEqual((destination / 'doc' / language / 'START-HERE-mac.txt').read_text(encoding='utf-8'), 'Guide: '+language)

    def test_updater_install_preserves_settings_without_more_confirmation(self):
        (self.source / 'update_yac.py').write_text('# updater')
        (self.source / 'changelog.txt').write_text('changes')
        (self.source / 'LICENSE').write_text('licence')
        (self.source / 'release.json').write_text('{"tag":"test"}')
        with patch.object(install_yac.sys, 'platform', 'linux'), patch.object(install_yac.os, 'geteuid', return_value=1000, create=True), patch.object(install_yac, 'ask') as ask, patch.object(install_yac.subprocess, 'run'), patch.object(install_yac, 'install_shortcut') as shortcut, redirect_stdout(io.StringIO()):
            self.assertEqual(install_yac.main(self.source, self.home, update=True), 0)
        destination = self.home / '.local/yac'
        self.assertTrue((destination / 'update-yac').is_file())
        self.assertTrue((destination / 'LICENSE').is_file())
        self.assertEqual((destination / 'release.json').read_text(), '{"tag":"test"}')
        ask.assert_not_called()
        shortcut.assert_not_called()

    def test_decline_creates_nothing(self):
        result, commands, shortcut, _ = self.run_setup([False])
        self.assertEqual(result, 0)
        self.assertFalse((self.home / ".local/yac").exists())
        commands.assert_not_called()
        shortcut.assert_not_called()

    def test_dated_release_details_are_installed(self):
        documentation = self.source / 'doc'
        documentation.mkdir()
        details = documentation / 'in-this-release-2026-10-26.txt'
        details.write_text('Full explanation for this release.')
        result, _, _, _ = self.run_setup([True])
        self.assertEqual(result, 0)
        installed = self.home / '.local/yac/doc' / details.name
        self.assertEqual(installed.read_bytes(), details.read_bytes())

    def test_recovery_files_are_installed_without_replacing_personal_ini(self):
        destination=self.home/'.local/yac'
        destination.mkdir(parents=True)
        (destination/'yac.py').write_text('# old source')
        (destination/'yac.ini').write_text('keep even if damaged')
        result,_,_,_=self.run_setup([True])
        self.assertEqual(result,0)
        for name in ('yac.ini.example','error-codes.txt'):
            self.assertEqual((destination/name).read_bytes(),(self.source/name).read_bytes())
        self.assertEqual((destination/'yac.ini').read_text(),'keep even if damaged')

    def test_existing_install_is_unchanged(self):
        destination = self.home / ".local/yac"
        destination.mkdir(parents=True)
        (destination / "yac.ini").write_text("keep")
        result, commands, _, _ = self.run_setup([])
        self.assertEqual(result, 1)
        self.assertEqual((destination / "yac.ini").read_text(), "keep")
        commands.assert_not_called()

    def test_update_preserves_settings_logs_and_environment_without_pip(self):
        destination = self.home / ".local/yac"
        destination.mkdir(parents=True)
        (destination / "yac.py").write_text("# old source\n")
        (destination / "yac.ini").write_text("lang=en\ncall=Gena\n")
        (destination / "logs").mkdir()
        (destination / "logs/test.log").write_text("keep log")
        python = destination / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("existing environment")
        result, commands, _, output = self.run_setup(
            [True], [subprocess.CompletedProcess([], 0), None])
        self.assertEqual(result, 0)
        self.assertEqual((destination / "yac.py").read_bytes(), (self.source / "yac.py").read_bytes())
        self.assertEqual((destination / "yac.ini").read_text(), "lang=en\ncall=Gena\n")
        self.assertEqual((destination / "logs/test.log").read_text(), "keep log")
        self.assertEqual(python.read_text(), "existing environment")
        self.assertEqual(commands.call_count, 2)
        self.assertNotIn("Installing dependencies", output)
        before = (destination / "yac.py").stat().st_mtime_ns
        self.run_setup([True], [subprocess.CompletedProcess([], 0), None])
        self.assertEqual((destination / "yac.py").stat().st_mtime_ns, before)

    def test_update_installs_missing_dependency(self):
        destination = self.home / ".local/yac"
        destination.mkdir(parents=True)
        (destination / "yac.py").write_text("# old\n")
        python = destination / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("existing environment")
        result, commands, _, _ = self.run_setup(
            [True], [subprocess.CompletedProcess([], 1), None, None])
        self.assertEqual(result, 0)
        self.assertEqual(commands.call_args_list[1].args[0],
                         [str(python), "-m", "pip", "install", "pyserial>=3.5,<4"])

    def test_install_copies_data_and_uses_only_private_pip(self):
        result, commands, shortcut, output = self.run_setup([True])
        destination = self.home / ".local/yac"
        self.assertEqual(result, 0)
        self.assertNotIn("personal settings", (destination / "yac.ini").read_text())
        self.assertEqual((destination / "KEY-BINDINGS-English.txt").read_bytes(),
                         (self.source / "KEY-BINDINGS-English.txt").read_bytes())
        self.assertFalse((destination / "modules/__pycache__").exists())
        self.assertEqual(commands.call_count, 3)
        self.assertEqual(commands.call_args_list[1].args[0], [str(destination / ".venv/bin/python"), "-m", "pip", "install", "pyserial>=3.5,<4"])
        shortcut.assert_called_once_with(destination / "run-yac", self.home)
        self.assertIn("Your existing Python environments are unchanged.", output)

    def test_venv_failure_does_not_install_shortcut(self):
        result, commands, shortcut, output = self.run_setup([True], subprocess.CalledProcessError(1, "venv"))
        self.assertEqual(result, 1)
        self.assertEqual(commands.call_count, 1)
        shortcut.assert_not_called()
        self.assertIn("python3-venv", output)

    def test_pip_failure_reports_recovery(self):
        result, _, shortcut, output = self.run_setup([True], [None, subprocess.CalledProcessError(1, "pip")])
        self.assertEqual(result, 1)
        shortcut.assert_not_called()
        self.assertIn("To retry", output)

    def test_launcher_quotes_paths_and_forwards_arguments(self):
        destination = Path("/home/a user's directory/yac")
        text = install_yac.launcher_text(destination)
        words = shlex.split(text.splitlines()[1])
        self.assertEqual(words, ["exec", str(destination / ".venv/bin/python"), str(destination / "yac.py"), "$@"])

    def test_root_execution_is_refused_before_any_mutation(self):
        with patch.object(install_yac.sys, "platform", "linux"), patch.object(install_yac.os, "geteuid", return_value=0, create=True), patch.object(install_yac, "ask") as ask, redirect_stdout(io.StringIO()):
            self.assertEqual(install_yac.main(self.source, self.home), 1)
        ask.assert_not_called()
        self.assertFalse((self.home / ".local/yac").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
