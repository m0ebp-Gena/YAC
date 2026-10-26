import io
from pathlib import Path
import tempfile
import unittest
import threading
from contextlib import contextmanager, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import yac
import update_yac
from modules import lang_sel, update_control
from modules.dummy_radio import create_dummy_radio
from tests.test_update_yac import release

ROOT = Path(__file__).resolve().parents[1]


class UpdateControlTests(unittest.TestCase):
    def setUp(self):
        update_control._pending = None

    def tearDown(self):
        update_control._pending = None

    def test_help_precedes_lookup_and_notes_return_to_confirmation(self):
        for language in ('en','de','es','pl'):
            with self.subTest(language=language),patch.object(update_control,'supported',return_value=True), \
                 patch.object(update_control,'_lookup_while_cancellable',return_value=(True,release())), \
                 patch.object(update_yac,'fetch') as fetch,patch.object(update_control,'run') as run, \
                 redirect_stdout(io.StringIO()) as output:
                self.assertFalse(update_control.confirm(ROOT,language,iter(['y','r','n']).__next__))
                prompt=update_control.chat_int.label(ROOT,language,'l326')
                self.assertLessEqual(len(prompt),15)
                self.assertEqual(output.getvalue().splitlines().count(prompt),2)
                self.assertIn('Changes for testing.',output.getvalue())
                looking=update_control.chat_int.label(ROOT,language,'l357')
                self.assertTrue(output.getvalue().lstrip().startswith(update_control.help_int.get_help(ROOT,language,'h027')))
                self.assertIn(looking,output.getvalue())
                fetch.assert_not_called()
                run.assert_not_called()

    def test_normal_startup_never_checks_the_internet(self):
        radio = create_dummy_radio()
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call': 'TEST', 'lang': 'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=iter(['q', 'y']).__next__), \
             patch.object(update_yac, 'fetch') as fetch, redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]), 0)
            fetch.assert_not_called()

    def test_confirm_and_cancel_do_not_start_the_updater(self):
        for keys, expected in [(['x',' ','n','y'], True), (['q'], False), (['n','n'],False), (['y','n'],False)]:
            with patch.object(update_control, 'supported', return_value=True), \
                 patch.object(update_control,'_lookup_while_cancellable',return_value=(True,release())), \
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
        keys = iter(['s', 'u', 'n', 'y'])
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call': 'TEST', 'lang': 'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=keys.__next__), \
             patch.object(update_control, 'supported', return_value=True), \
             patch.object(update_control,'_lookup_while_cancellable',return_value=(True,release())), \
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
             patch.object(update_control,'_lookup_while_cancellable',return_value=(True,release())), \
             patch.object(update_control, 'run') as run, redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]), 0)
            run.assert_not_called()

    def test_no_update_and_no_internet_return_without_confirmation(self):
        for error,label in [(None,'l358'),(update_control.NoInternet(),'l360')]:
            with self.subTest(label=label),patch.object(update_control,'supported',return_value=True), \
                 patch.object(update_control,'_lookup_while_cancellable',return_value=(True,None),side_effect=error), \
                 redirect_stdout(io.StringIO()) as output:
                self.assertFalse(update_control.confirm(ROOT,'en',lambda:self.fail('read key')))
                self.assertTrue(output.getvalue().endswith(update_control.chat_int.label(ROOT,'en',label)))
                self.assertIsNone(update_control._pending)

    def test_lookup_outcomes_return_to_settings_with_radio_open(self):
        for error in (None,update_control.NoInternet()):
            radio=create_dummy_radio()
            keys=iter(['s','u','a','q','q','y'])
            def read_agc(*args,**kwargs):
                self.assertTrue(radio.serial.is_open)
                return 'AGC checked'
            with self.subTest(offline=bool(error)), \
                 patch.object(yac,'connect_radio',return_value=radio), \
                 patch.object(yac,'_read_settings',return_value={'call':'TEST','lang':'en'}), \
                 patch.object(lang_sel,'read_key',side_effect=keys.__next__), \
                 patch.object(update_control,'supported',return_value=True), \
                 patch.object(update_control,'_lookup_while_cancellable',return_value=(True,None),side_effect=error), \
                 patch.object(update_control,'run') as install, \
                 patch.object(yac.agc_control,'cycle',side_effect=read_agc) as agc, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(yac.main([]),0)
                agc.assert_called_once()
                install.assert_not_called()

    def test_skipping_notes_still_requires_separate_install_answer(self):
        with patch.object(update_control,'supported',return_value=True), \
             patch.object(update_control,'_lookup_while_cancellable',return_value=(True,release())), \
             patch.object(update_control.help_int,'show_paged') as notes, \
             redirect_stdout(io.StringIO()) as output:
            self.assertFalse(update_control.confirm(ROOT,'en',iter(['n','n']).__next__))
            notes.assert_not_called()
            self.assertLess(output.getvalue().index('Update Found\nRead Notes Y/N?'),output.getvalue().index('\nUpdate Y/N?'))
            self.assertIsNone(update_control._pending)

    def test_reading_notes_never_authorizes_installation(self):
        with patch.object(update_control,'supported',return_value=True), \
             patch.object(update_control,'_lookup_while_cancellable',return_value=(True,release())), \
             redirect_stdout(io.StringIO()) as output:
            self.assertFalse(update_control.confirm(ROOT,'en',iter(['y','n']).__next__))
            self.assertIn('Changes for testing.',output.getvalue())
            self.assertIsNone(update_control._pending)

    def test_lookup_cancel_returns_without_waiting_for_network(self):
        entered=threading.Event()
        release_worker=threading.Event()
        def lookup(root):
            entered.set()
            release_worker.wait(2)
            return release()
        def key(**kwargs):
            self.assertTrue(entered.wait(1))
            return 'q'
        with patch.object(update_control,'lookup',side_effect=lookup):
            try:
                self.assertEqual(update_control._lookup_while_cancellable(ROOT,key),(False,None))
            finally:
                release_worker.set()

    def test_lookup_completion_wakes_idle_key_reader(self):
        finish=threading.Event()
        def lookup(root):
            finish.wait(1)
            return release()
        def key(idle_callback=None):
            finish.set()
            # Real read_key polls this callback while no key is available.
            for _ in range(1000):
                idle_callback()
                threading.Event().wait(.001)
            self.fail('lookup did not wake the reader')
        with patch.object(update_control,'lookup',side_effect=lookup):
            completed,selected=update_control._lookup_while_cancellable(ROOT,key)
        self.assertTrue(completed)
        self.assertEqual(selected['tag_name'],'v-test')

    def test_lookup_fetches_metadata_only_and_reports_unreachable_github(self):
        import json
        with tempfile.TemporaryDirectory() as folder,patch.object(update_control.sys,'platform','linux'), \
             patch.object(update_yac,'fetch',return_value=json.dumps([release()]).encode()) as fetch:
            self.assertEqual(update_control.lookup(Path(folder)),release())
            fetch.assert_called_once_with(update_yac.API,2*1024*1024)
            (Path(folder)/'release.json').write_text(json.dumps({'tag':'v-test'}))
            self.assertIsNone(update_control.lookup(Path(folder)))
        with patch.object(update_yac,'fetch',side_effect=OSError('offline')):
            with self.assertRaises(update_control.NoInternet):
                update_control.lookup(ROOT)

    def test_selected_release_installs_without_rechecking_or_confirming(self):
        update_control._pending=(ROOT.resolve(),release(),'en')
        with patch.object(update_control.sys,'platform','linux'), \
             patch.object(update_yac,'run',return_value=0) as install, \
             patch.object(update_control.os,'execv') as restart,redirect_stdout(io.StringIO()):
            self.assertEqual(update_control.run(ROOT),0)
        install.assert_called_once_with(ROOT,selected_release=release())
        restart.assert_called_once()

    def test_notes_pager_and_short_notes(self):
        for language in ('en','de','es','pl'):
            with self.subTest(language=language),redirect_stdout(io.StringIO()) as output:
                update_control.help_int.show_paged(ROOT,language,'short notes',lambda:self.fail('short notes requested key'),page_lines=2)
                self.assertIn('short notes',output.getvalue())
            with redirect_stdout(io.StringIO()) as output:
                keys=iter([' ','q'])
                update_control.help_int.show_paged(ROOT,language,'one\ntwo\nthree\nfour\nfive\nsix',keys.__next__,page_lines=2)
                self.assertIn('four',output.getvalue())
                self.assertNotIn('five',output.getvalue())

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
