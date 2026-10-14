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
        self.temporary = tempfile.TemporaryDirectory(dir=test_root, ignore_cleanup_errors=True)
        assert Path(self.temporary.name).resolve().is_relative_to(test_root.resolve())
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.home = self.base / "home with spaces"
        self.home.mkdir()
        (self.source / "yac.py").write_text("# source\n")
        (self.source / "yac.ini").write_text("personal settings must not be copied")
        (self.source / "KEY-BINDINGS-English.txt").write_text("s then t: tuner\n")
        for name in ["modules", "lang", "rad_cmds"]:
            (self.source / name).mkdir()
            (self.source / name / "data.txt").write_text(name)
        cache = self.source / "modules/__pycache__"
        cache.mkdir()
        (cache / "old.pyc").write_bytes(b"old")

    def run_setup(self, answers, failure=None):
        with patch.object(install_yac.sys, "platform", "linux"), patch.object(install_yac.os, "geteuid", return_value=1000, create=True), patch.object(install_yac, "ask", side_effect=answers), patch.object(install_yac.subprocess, "run", side_effect=failure) as commands, patch.object(install_yac, "install_shortcut") as shortcut, redirect_stdout(io.StringIO()) as output:
            result = install_yac.main(self.source, self.home)
        return result, commands, shortcut, output.getvalue()

    def test_decline_creates_nothing(self):
        result, commands, shortcut, _ = self.run_setup([False])
        self.assertEqual(result, 0)
        self.assertFalse((self.home / "yac").exists())
        commands.assert_not_called()
        shortcut.assert_not_called()

    def test_existing_install_is_unchanged(self):
        destination = self.home / "yac"
        destination.mkdir()
        (destination / "yac.ini").write_text("keep")
        result, commands, _, _ = self.run_setup([])
        self.assertEqual(result, 1)
        self.assertEqual((destination / "yac.ini").read_text(), "keep")
        commands.assert_not_called()

    def test_update_preserves_settings_logs_and_environment_without_pip(self):
        destination = self.home / "yac"
        destination.mkdir()
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
        self.assertIn("skipping pip", output)
        before = (destination / "yac.py").stat().st_mtime_ns
        self.run_setup([True], [subprocess.CompletedProcess([], 0), None])
        self.assertEqual((destination / "yac.py").stat().st_mtime_ns, before)

    def test_update_installs_missing_dependency(self):
        destination = self.home / "yac"
        destination.mkdir()
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
        destination = self.home / "yac"
        self.assertEqual(result, 0)
        self.assertNotIn("personal settings", (destination / "yac.ini").read_text())
        self.assertEqual((destination / "KEY-BINDINGS-English.txt").read_bytes(),
                         (self.source / "KEY-BINDINGS-English.txt").read_bytes())
        self.assertFalse((destination / "modules/__pycache__").exists())
        self.assertEqual(commands.call_count, 3)
        self.assertEqual(commands.call_args_list[1].args[0], [str(destination / ".venv/bin/python"), "-m", "pip", "install", "pyserial>=3.5,<4"])
        shortcut.assert_called_once_with(destination / "run-yac", self.home)
        self.assertIn("has not opened any radio ports", output)

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
        self.assertFalse((self.home / "yac").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
