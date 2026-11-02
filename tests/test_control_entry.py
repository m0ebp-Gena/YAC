"""Opening settings must report live state without changing it."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yac
from modules import filter_control, setting_selector, speech_processor, split_control
from modules import audio_setup, access_control
from modules.decoder_control import DecoderManager
from modules.dummy_radio import create_dummy_radio
from tests import test_audio_setup

ROOT = Path(__file__).resolve().parents[1]


class ControlEntryTests(unittest.TestCase):
    def test_filter_entry_reentry_preserves_on_and_off_states(self):
        cases = [('a', 'auto_notch', '1'), ('b', 'noise_blanker', '1'),
                 ('n', 'manual_notch', '001'), ('r', 'noise_reduction', '1'),
                 ('c', 'contour', '0001')]
        for key, field, enabled in cases:
            for on in (False, True):
                with self.subTest(key=key, on=on):
                    radio = create_dummy_radio()
                    if key == 'c':
                        radio.serial.contour['CO00'] = enabled if on else '0000'
                    else:
                        setattr(radio.serial, field, enabled if on else ('000' if key == 'n' else '0'))
                    commands = []
                    original = yac._cat_exchange
                    def exchange(radio, command):
                        commands.append(command)
                        return original(radio, command)
                    keys = iter([key, 'q', key, 'q', 'q'])
                    with patch.object(yac, '_cat_exchange', side_effect=exchange), \
                         patch('modules.verify_settings._write') as setter, \
                         redirect_stdout(io.StringIO()) as output:
                        filter_control.control(yac, ROOT, radio, 'en', 'test',
                                               keys.__next__, SimpleNamespace(lost=False))
                    setter.assert_not_called()
                    self.assertIn('On' if on else 'Off', output.getvalue())
                    if not on:
                        self.assertFalse(set(commands) & {'NL0;', 'RL0;', 'BP01;', 'CO01;'}, commands)

    def test_preamp_and_attenuator_entry_do_not_cycle(self):
        radio = create_dummy_radio()
        keys = iter(['p', 'q', 'u', 'q', 'q', 'y'])
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call':'test','lang':'en'}), \
             patch.object(yac.lang_sel, 'read_key', side_effect=keys.__next__), \
             patch.object(yac.verify_settings, 'cycle') as cycle, redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]), 0)
        cycle.assert_not_called()

    def test_vfo_entry_is_read_only_and_reports_unknown_without_selecting(self):
        radio = SimpleNamespace(protocol='CI-V', civ_address=0x94, model_id='IC-7300')
        with patch.object(yac, '_icom_select_vfo') as select, redirect_stdout(io.StringIO()) as output:
            setting_selector.vfo(yac, ROOT, radio, 'en', iter(['q']).__next__, SimpleNamespace(lost=False))
        select.assert_not_called()
        self.assertIn('Unknown', output.getvalue())

    def test_processor_off_hidden_level_is_not_probed_on_entry(self):
        radio = create_dummy_radio()
        original = yac._cat_exchange
        def exchange(radio, command):
            return 'PL000;' if command == 'PL;' else original(radio, command)
        with patch.object(yac, '_cat_exchange', side_effect=exchange), \
             patch.object(speech_processor, 'set_status') as setter, \
             redirect_stdout(io.StringIO()) as output:
            speech_processor.control(yac, ROOT, radio, 'en', iter(['q']).__next__, SimpleNamespace(lost=False))
        setter.assert_not_called()
        self.assertTrue(output.getvalue().startswith('Processor Off'))
        # Help can explain levels; the opening status itself must omit them.
        self.assertNotIn('Strength', output.getvalue().splitlines()[0])

    def test_split_open_and_cancel_preserves_existing_split(self):
        for on in (False, True):
            with self.subTest(on=on):
                radio = create_dummy_radio()
                if on:
                    self.assertTrue(split_control.Radio(yac, ROOT, radio).prepare().enable(7164000)[0])
                before = dict(radio.serial.split_settings)
                with patch.object(split_control.Radio, 'enable') as enable, \
                     patch.object(split_control.Radio, 'off') as disable, \
                     redirect_stdout(io.StringIO()):
                    split_control.control(yac, ROOT, radio, 'en', iter(['q']).__next__)
                enable.assert_not_called()
                disable.assert_not_called()
                self.assertEqual(radio.serial.split_settings, before)

    def test_audio_browsing_keeps_capture_running(self):
        manager = DecoderManager(yac, ROOT, create_dummy_radio(), 'en')
        session = SimpleNamespace(paused=False, close=Mock())
        manager.session = session
        sd = test_audio_setup.AudioSetupTests().backend()
        with patch.dict('sys.modules', {'sounddevice':sd}), \
             patch.object(yac, '_read_settings', return_value={}), \
             redirect_stdout(io.StringIO()):
            manager.control(iter(['a', 'q', 'q']).__next__)
        self.assertIs(manager.session, session)
        session.close.assert_not_called()
        sd.RawInputStream.assert_not_called()

    def test_audio_explicit_check_prepares_input_only_on_request(self):
        sd = test_audio_setup.AudioSetupTests().backend()
        prepare = Mock()
        def read():
            prepare.assert_not_called()
            return 'q'
        with patch.dict('sys.modules', {'sounddevice':sd}), \
             patch.object(yac, '_read_settings', return_value={}), \
             redirect_stdout(io.StringIO()):
            audio_setup.control(yac, ROOT, 'en', read, prepare_input=prepare)
        prepare.assert_not_called()

    def test_speech_settings_announce_current_value_on_entry(self):
        with patch.object(access_control, 'image_enabled', return_value=True), \
             patch.object(access_control, 'bridge', return_value={'preferences': dict(access_control.DEFAULTS)}), \
             redirect_stdout(io.StringIO()) as output:
            access_control.control(ROOT, 'en', iter(['q']).__next__, SimpleNamespace(lost=False))
        self.assertIn('2', output.getvalue().splitlines())


if __name__ == '__main__':
    unittest.main()
