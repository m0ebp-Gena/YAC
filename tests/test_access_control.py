"""Speakup controls preserve platform boundaries, cancellation and recovery."""
import copy
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch
from modules import access_control as access

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('speakup_helper', ROOT / 'pi/speakup-settings.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
STATE = {'ok': True, 'preferences': dict(access.DEFAULTS)}


class AccessTests(unittest.TestCase):
    def menu(self, keys, state=None):
        state = copy.deepcopy(state or STATE)
        requests = []
        def bridge(request):
            requests.append(request)
            if request['action'] == 'apply': state['preferences'].update(request['changes'])
            return copy.deepcopy(state)
        keys = iter(keys)
        with patch.object(access, 'image_enabled', return_value=True), patch.object(access, 'bridge', side_effect=bridge), redirect_stdout(io.StringIO()) as output:
            access.control(ROOT, 'en', lambda: next(keys), SimpleNamespace(lost=False))
        return requests, output.getvalue()

    def test_normal_source_never_invokes_helper(self):
        for modes in (False, True):
            with patch.object(access, 'image_enabled', return_value=False), patch.object(access, 'bridge') as bridge, redirect_stdout(io.StringIO()):
                access.control(ROOT, 'en', lambda: 'q', SimpleNamespace(lost=False), modes=modes)
            bridge.assert_not_called()

    def test_adjustment_applies_and_saves_without_e_before_quit(self):
        requests, output = self.menu(['r', '.', 'q'])
        self.assertEqual(requests, [{'action': 'status'}, {'action':'apply', 'changes':{'speech-rate':'3'}}])
        self.assertEqual([line for line in output.splitlines() if line][:3], ['Rate', 'Rate', '3'])

    def test_each_adjustment_is_immediate(self):
        requests, output = self.menu(['r', '.', '.', 'p', ',', 't', 'q'])
        self.assertEqual([r['changes'] for r in requests[1:]], [{'speech-rate':'3'}, {'speech-rate':'4'}, {'speech-pitch':'4'}])
        self.assertIn('14.250', output)

    def test_rate_selected_on_entry_like_offset(self):
        self.assertEqual(self.menu(['.', 'q'])[0][1]['changes'], {'speech-rate':'3'})

    def test_rate_upper_endpoint_is_nine(self):
        state=copy.deepcopy(STATE); state['preferences']['speech-rate']='8'
        self.assertEqual(len(self.menu(['r', '.', '.', 'q'],state)[0]), 2)

    def test_volume_endpoint_does_not_write(self):
        state=copy.deepcopy(STATE); state['preferences']['speech-volume']='1'
        self.assertEqual(len(self.menu(['v', ',', 'q'],state)[0]), 1)

    def test_punctuation_includes_most(self):
        self.assertEqual(self.menu(['u', '.', 'q'])[0][1]['changes'], {'speech-punctuation':'most'})

    def test_defaults_apply_immediately_and_change_only_speech_fields(self):
        state=copy.deepcopy(STATE); state['preferences']['speech-rate']='8'
        self.assertEqual(self.menu(['d','q'],state)[0][1]['changes'], {'speech-rate':'2'})

    def test_failed_change_does_not_announce_unconfirmed_rate(self):
        with patch.object(access, 'image_enabled', return_value=True), \
             patch.object(access, 'bridge', side_effect=[copy.deepcopy(STATE), RuntimeError('disk full')]), \
             self.assertLogs(access.LOG, level='ERROR'), redirect_stdout(io.StringIO()) as output:
            access.control(ROOT, 'en', iter(['.', 'q']).__next__, SimpleNamespace(lost=False))
        self.assertNotIn('3', output.getvalue().splitlines())

    def test_selection_names_and_adjustment_values_without_navigation_prompts(self):
        requests, output = self.menu(['o', '.', 'o', ',', 'o', '.', 'q'])
        self.assertEqual([line for line in output.splitlines() if line][:7],
                         ['Rate', 'Volume', '6', 'Pitch', '4', 'Punctuation', 'Most'])
        self.assertNotIn('Help', output)
        self.assertNotIn('increase', output)

    def test_navigation_instructions_are_available_on_help(self):
        requests, output = self.menu(['h', 'q'])
        self.assertIn('Full stop increases', output)

    def test_modes_announce_only_current_mode_on_entry(self):
        with patch.object(access, 'load_mode', return_value='both'), \
             patch.object(access, 'image_enabled', return_value=True), \
             redirect_stdout(io.StringIO()) as output:
            access.control(ROOT, 'en', iter(['q']).__next__, SimpleNamespace(lost=False), modes=True)
        self.assertEqual(output.getvalue().strip().splitlines()[0], 'Speech/Braille')
        self.assertNotIn('Help', output.getvalue())

    def test_modes_apply_and_preserve_unrelated_launcher_values(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(access, 'mode_file', return_value=Path(directory)/'launcher.ini'), \
             patch.object(access, 'image_enabled', return_value=True), \
             patch.object(access, 'bridge', return_value=copy.deepcopy(STATE)) as bridge, redirect_stdout(io.StringIO()):
            access.mode_file().write_text('[launcher]\naudio_card=USB\nvolume=70\naccess_mode=both\n')
            for keys in (['.', 'q'], ['.', 'q'], ['.', 'q']):
                access.control(ROOT, 'en', iter(keys).__next__, SimpleNamespace(lost=False), modes=True)
            self.assertEqual([call.args[0]['mode'] for call in bridge.call_args_list], ['braille','speech','both'])
            self.assertEqual(access.load_mode(), 'both')
            self.assertIn('audio_card = USB', access.mode_file().read_text())

    def test_mode_navigation_moves_both_directions_and_only_applies_on_q(self):
        with patch.object(access, 'load_mode', return_value='speech'), \
             patch.object(access, 'save_mode') as save, \
             patch.object(access, 'image_enabled', return_value=True), \
             patch.object(access, 'bridge') as bridge, redirect_stdout(io.StringIO()) as output:
            access.control(ROOT, 'en', iter(['.', ',', ',', 'q']).__next__, SimpleNamespace(lost=False), modes=True)
        self.assertEqual([line for line in output.getvalue().splitlines() if line][:4],
                         ['Speech only', 'Speech/Braille', 'Speech only', 'Braille only'])
        save.assert_called_once_with('braille')
        bridge.assert_called_once_with({'action': 'mode', 'mode': 'braille'})

    def test_failed_mode_change_restores_previous_saved_mode(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(access, 'mode_file', return_value=Path(directory)/'launcher.ini'), \
             patch.object(access, 'image_enabled', return_value=True), \
             patch.object(access, 'bridge', side_effect=[RuntimeError('failure'), copy.deepcopy(STATE)]), redirect_stdout(io.StringIO()):
            access.control(ROOT, 'en', iter(['b','q']).__next__, SimpleNamespace(lost=False), modes=True)
            self.assertEqual(access.load_mode(), 'both')

    def test_cannot_mute_when_mode_cannot_be_saved(self):
        with patch.object(access, 'load_mode', return_value='both'), \
             patch.object(access, 'save_mode', side_effect=OSError('read only')), \
             patch.object(access, 'image_enabled', return_value=True), \
             patch.object(access, 'bridge') as bridge, redirect_stdout(io.StringIO()):
            access.control(ROOT, 'en', iter(['b','q']).__next__, SimpleNamespace(lost=False), modes=True)
            bridge.assert_not_called()

    def test_repeat_o_cycles_fields_and_punctuation_wraps_back_to_rate(self):
        requests, output = self.menu(['o', '.', 'o', ',', 'o', '.', 'o', '.', 'q'])
        self.assertEqual([r['changes'] for r in requests[1:]], [
            {'speech-volume':'6'}, {'speech-pitch':'4'},
            {'speech-punctuation':'most'}, {'speech-rate':'3'}])

    def test_focused_mode_is_applied_and_saved_on_quit(self):
        with patch.object(access, 'load_mode', return_value='both'), \
             patch.object(access, 'save_mode') as save, \
             patch.object(access, 'image_enabled', return_value=True), \
             patch.object(access, 'bridge') as bridge, redirect_stdout(io.StringIO()):
            access.control(ROOT, 'en', iter(['b','b','q']).__next__, SimpleNamespace(lost=False), modes=True)
        save.assert_called_once_with('speech')
        bridge.assert_called_once_with({'action': 'mode', 'mode': 'speech'})

    def test_braille_only_on_quit_requests_silence(self):
        with patch.object(access, 'load_mode', return_value='both'), \
             patch.object(access, 'save_mode') as save, \
             patch.object(access, 'image_enabled', return_value=True), \
             patch.object(access, 'bridge') as bridge, redirect_stdout(io.StringIO()):
            access.control(ROOT, 'en', iter(['b','q']).__next__, SimpleNamespace(lost=False), modes=True)
        save.assert_called_once_with('braille')
        bridge.assert_called_once_with({'action': 'mode', 'mode': 'braille'})


class HelperTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'builds/.work/speakup-tests'; folder.mkdir(parents=True,exist_ok=True)
        temporary=tempfile.TemporaryDirectory(dir=folder,ignore_cleanup_errors=True)
        self.addCleanup(temporary.cleanup); self.base=Path(temporary.name)
        (self.base/'soft').mkdir()
        for name,value in {'synth':'soft','soft/direct':'0','soft/rate':'2','soft/vol':'5','soft/pitch':'5','punc_level':'1','reading_punc':'2'}.items():
            (self.base/name).write_text(value+'\n')
        for name,value in [('BASE',self.base),('load_saved',lambda:{})]:
            patcher=patch.object(helper,name,value); patcher.start(); self.addCleanup(patcher.stop)

    def test_live_write_readback_and_only_managed_values_saved(self):
        with patch.object(helper,'persist') as save:
            result=helper.apply({'speech-rate':'4'})
        self.assertEqual(result['speech-rate'],'4')
        save.assert_called_once_with({'speech-rate':'4'})
        self.assertEqual((self.base/'reading_punc').read_text(),'2\n')

    def test_punctuation_mapping(self):
        with patch.object(helper,'persist'):
            self.assertEqual(helper.apply({'speech-punctuation':'most'})['speech-punctuation'],'most')
        self.assertEqual((self.base/'punc_level').read_text(),'2\n')

    def test_reject_unknown_or_out_of_range_before_writes(self):
        for changes in ({'synth':'none'},{'speech-volume':'0'},{'speech-rate':'10'},{'speech-rate':True},{'speech-punctuation':'invalid'}):
            with patch.object(helper,'write_value') as write:
                with self.assertRaises(ValueError): helper.apply(changes)
                write.assert_not_called()

    def test_nonsoft_synth_is_refused(self):
        (self.base/'synth').write_text('none\n')
        with patch.object(helper,'write_value') as write:
            with self.assertRaises(ValueError): helper.apply({'speech-rate':'4'})
            write.assert_not_called()

    def test_direct_mode_punctuation_is_refused(self):
        (self.base/'soft/direct').write_text('1\n')
        with patch.object(helper,'write_value') as write:
            with self.assertRaises(ValueError): helper.apply({'speech-punctuation':'all'})
            write.assert_not_called()

    def test_partial_failure_restores_old_values(self):
        write=helper.write_value; calls=[]
        def fail(key,value):
            calls.append((key,value))
            if len(calls)==2: raise OSError('simulated failure')
            write(key,value)
        with patch.object(helper,'write_value',side_effect=fail), patch.object(helper,'persist') as save:
            with self.assertRaises(OSError): helper.apply({'speech-rate':'4','speech-pitch':'6'})
        save.assert_not_called()
        self.assertEqual((self.base/'soft/rate').read_text(),'2\n')
        self.assertEqual((self.base/'soft/pitch').read_text(),'5\n')

    def test_persistence_failure_rolls_back(self):
        with patch.object(helper,'persist',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): helper.apply({'speech-rate':'4'})
        self.assertEqual((self.base/'soft/rate').read_text(),'2\n')

    def test_restore_does_not_save_again(self):
        with patch.object(helper,'persist') as save: helper.apply({'speech-rate':'4'},save=False)
        save.assert_not_called()

    def test_modes_mute_and_resume_without_stopping_braille_or_restarting_speech(self):
        with patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            helper.apply_mode('braille')
            self.assertEqual((self.base/'silent').read_text(), '7\n')
            run.assert_not_called()
            helper.apply_mode('speech')
            self.assertEqual((self.base/'silent').read_text(), '6\n')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/systemctl', 'is-active', '--quiet', 'espeakup.service'])
            self.assertEqual((self.base/'soft/rate').read_text(), '2\n')

    def test_failed_speech_service_never_queues_start_or_changes_mute(self):
        (self.base/'silent').write_text('7\n')
        with patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=3)) as run:
            with self.assertRaises(RuntimeError):
                helper.apply_mode('speech')
        self.assertEqual((self.base/'silent').read_text(), '7\n')
        self.assertEqual(run.call_count, 1)
        self.assertIn('is-active', run.call_args.args[0])

    def test_invalid_mode_changes_nothing(self):
        with patch.object(helper.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                helper.apply_mode('disable-braille')
            run.assert_not_called()
        self.assertFalse((self.base/'silent').exists())


if __name__=='__main__': unittest.main()
