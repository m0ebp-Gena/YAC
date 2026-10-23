import io
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import yac
import update_yac
from modules import lang_sel, update_control
from modules.dummy_radio import create_dummy_radio

ROOT = Path(__file__).resolve().parents[1]


class UpdateControlTests(unittest.TestCase):
    def test_normal_startup_never_checks_the_internet(self):
        radio = create_dummy_radio()
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call': 'TEST', 'lang': 'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=iter(['q', 'y']).__next__), \
             patch.object(update_yac, 'fetch') as fetch, redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]), 0)
            fetch.assert_not_called()

    def test_confirm_and_cancel_do_not_start_the_updater(self):
        for keys, expected in [(['x', ' '], True), (['q'], False)]:
            with patch.object(update_control, 'supported', return_value=True), \
                 patch.object(update_control, 'run') as run, redirect_stdout(io.StringIO()):
                self.assertEqual(update_control.confirm(ROOT, 'en', iter(keys).__next__), expected)
                run.assert_not_called()

    def test_unsupported_tree_does_not_consume_a_key(self):
        with patch.object(update_control, 'supported', return_value=False), redirect_stdout(io.StringIO()):
            self.assertFalse(update_control.confirm(ROOT, 'en', lambda: self.fail('read a key')))

    def test_installed_locations_on_linux_and_mac(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            for platform, subfolder in [('linux', '.local'), ('darwin', 'Applications')]:
                root = home / subfolder / 'yac'
                root.mkdir(parents=True)
                (root / 'update_yac.py').touch()
                with patch.object(update_control.Path, 'home', return_value=home), \
                     patch.object(update_control.sys, 'platform', platform):
                    self.assertTrue(update_control.supported(root))
                    self.assertFalse(update_control.supported(home))

    def test_settings_handover_closes_radio_and_releases_lock_first(self):
        radio = create_dummy_radio()
        held = []
        @contextmanager
        def lock(root):
            held.append(True)
            try:
                yield
            finally:
                held.pop()
        def update(root):
            self.assertFalse(held)
            self.assertFalse(radio.serial.is_open)
            return 0
        keys = iter(['s', 'u', ' '])
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call': 'TEST', 'lang': 'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=keys.__next__), \
             patch.object(update_control, 'supported', return_value=True), \
             patch.object(update_control, 'run', side_effect=update) as run, \
             patch('modules.update_lock.application_lock', side_effect=lock), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]), 0)
            run.assert_called_once()

    def test_cancel_in_settings_keeps_controller_running(self):
        radio = create_dummy_radio()
        keys = iter(['s', 'u', 'q', 'q', 'w', 'q', 'y'])
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call': 'TEST', 'lang': 'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=keys.__next__), \
             patch.object(update_control, 'supported', return_value=True), \
             patch.object(update_control, 'run') as run, redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]), 0)
            run.assert_not_called()

    def test_source_updater_uses_current_python_then_restarts_fresh(self):
        with patch.object(update_control.sys, 'platform', 'linux'), \
             patch.object(update_control.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
             patch.object(update_control.os, 'execv') as restart:
            self.assertEqual(update_control.run(ROOT), 0)
            self.assertEqual(run.call_args.args[0], [update_control.sys.executable, str(ROOT / 'update_yac.py')])
            restart.assert_called_once()

    def test_failed_source_update_can_return_to_yac_after_user_reads_error(self):
        with patch.object(update_control.sys, 'platform', 'darwin'), \
             patch.object(update_control.subprocess, 'run', return_value=SimpleNamespace(returncode=1)), \
             patch.object(update_control.os, 'execv') as restart, \
             patch('builtins.input', return_value=''):
            self.assertEqual(update_control.run(ROOT), 0)
            restart.assert_called_once()


if __name__ == '__main__':
    unittest.main()
