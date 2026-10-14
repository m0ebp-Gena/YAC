"""Settings readback, model capabilities and keyboard integration checks."""
import io
import json
import string
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import lang_sel, verify_settings as controls
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
from tests.test_icom_7300 import IcomSerial

ROOT = Path(__file__).resolve().parents[1]


class SettingsSerial(IcomSerial):
    def __init__(self, address):
        super().__init__(address)
        self.settings = {b'\x11': b'\x00', b'\x16\x02': b'\x00',
                         b'\x14\x0a': b'\x00\x51', b'\x1c\x01': b'\x00'}
        self.reject_setting = False

    def write(self, packet):
        key = packet[4:5] if packet[4] == 0x11 else packet[4:6]
        if key not in self.settings:
            return super().write(packet)
        self.writes.append(packet)
        self.buffer.extend(packet)  # Ignore echoed commands when decoding.
        prefix = bytes((254, 254, 224, self.address))
        value = packet[4 + len(key):-1]
        if value:
            if self.reject_setting:
                reply = b'\xfa'
            else:
                self.settings[key] = value
                reply = b'\xfb'
        else:
            reply = key + self.settings[key]
        self.buffer.extend(prefix + reply + b'\xfd')
        return len(packet)


class VerifySettingsTests(unittest.TestCase):
    def test_demo_reports_live_values_and_cycles_all_settings(self):
        radio = create_dummy_radio()
        expected = 'Attenuator off, preamp off, power 20 watts, tuner off'
        self.assertEqual(controls.verify(yac, ROOT, radio, 'en'), expected)
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'preamp 1')
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'preamp 2')
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'preamp off')
        for expected in ('Attenuator 6 dB', 'Attenuator 12 dB', 'Attenuator 18 dB', 'Attenuator off'):
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'attenuator'), expected)
        for expected in ('tuner internal','tuner external 1','tuner external 2','tuner external 3','tuner off'):
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), expected)
        radio.serial.preamp = '2'  # A change made outside YAC is immediately visible.
        self.assertIn('preamp 2', controls.verify(yac, ROOT, radio, 'en'))

    def test_keyboard_routes_top_level_and_settings_keys(self):
        radio = create_dummy_radio()
        keys = iter(['v','p','p','u','s','t','t','q','v','q'])
        output = io.StringIO()
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call':'test','lang':'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), redirect_stdout(output):
            self.assertEqual(yac.main([]), 0)
        self.assertIn('Attenuator 6 dB, preamp 2, power 20 watts, tuner external 1', output.getvalue())

    def test_icom_frames_readback_and_rejected_change(self):
        serial = SettingsSerial(0x94)
        radio = RadioConnection(serial, 'test', 115200, 'CI-V', 'IC-7300', 'IC-7300', civ_address=0x94)
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'attenuator'), 'Attenuator on')
        self.assertEqual(serial.settings[b'\x11'], b'\x20')
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'preamp 1')
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), 'tuner on')
        self.assertIn('power 20%', controls.verify(yac, ROOT, radio, 'en'))
        serial.reject_setting = True
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'Setting change failed')
        self.assertEqual(serial.settings[b'\x16\x02'], b'\x01')

    def test_no_tuner_means_no_tuner_command_or_report(self):
        serial = SettingsSerial(0xA2)
        radio = RadioConnection(serial, 'test', 115200, 'CI-V', 'IC-9700', 'IC-9700', civ_address=0xA2)
        self.assertNotIn('tuner', controls.verify(yac, ROOT, radio, 'en'))
        count = len(serial.writes)
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), 'Not supported')
        self.assertEqual(len(serial.writes), count)
        serial.settings[b'\x16\x02'] = b'\x02'
        self.assertIn('preamp external', controls.verify(yac, ROOT, radio, 'en'))

    def test_failed_read_does_not_become_off_or_cause_write(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_cat_exchange', return_value='?;') as exchange:
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'preamp unknown')
            self.assertTrue(all(call.args[1] == 'PA0;' for call in exchange.call_args_list))
            report = controls.verify(yac, ROOT, radio, 'en')
            self.assertEqual(report, 'Attenuator unknown, preamp unknown, power unknown, tuner unknown')

    def test_cat_readback_mismatch_is_failure(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_cat_exchange', return_value='PA00;') as exchange:
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'Setting change failed')
            self.assertIn('PA01;', [call.args[1] for call in exchange.call_args_list])

    def test_invalid_power_data_is_unknown(self):
        serial = SettingsSerial(0x94)
        radio = RadioConnection(serial, 'test', 115200, 'CI-V', 'IC-7300', 'IC-7300', civ_address=0x94)
        spec = controls.catalog(ROOT, radio)['power']
        for value in (b'\x02\x56', b'\xfa\x00', b'\x01'):
            serial.settings[b'\x14\x0a'] = value
            self.assertEqual(controls.describe(yac, ROOT, radio, 'en', 'power', spec), 'power unknown')
        radio = create_dummy_radio()
        radio.serial.power = '999'
        spec = controls.catalog(ROOT, radio)['power']
        self.assertEqual(controls.describe(yac, ROOT, radio, 'en', 'power', spec), 'power unknown')

    def test_failed_tuner_disable_does_not_change_selection_or_enable(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_cat_exchange', side_effect=lambda r,c: 'AC001;' if c=='AC;' else 'EX0301050;') as exchange:
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), 'Setting change failed')
        commands = [call.args[1] for call in exchange.call_args_list]
        self.assertIn('AC000;', commands)
        self.assertNotIn('EX0301051;', commands)
        self.assertNotIn('AC001;', commands)

    def test_ftx_band_specific_preamp_and_power_format(self):
        radio = create_dummy_radio()
        radio.model_id = '0840'
        replies = {'PA1;':'PA11;', 'PA10;':'', 'PC;':'PC2005;'}
        with patch.object(yac, '_current_frequency', return_value='145.5'), \
             patch.object(yac, '_cat_exchange', side_effect=lambda r,c: replies.get(c, 'PA10;')) as exchange:
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'Setting change failed')
            self.assertNotIn('PA12;', [call.args[1] for call in exchange.call_args_list])
            spec = controls.catalog(ROOT, radio)['power']
            self.assertEqual(controls.describe(yac, ROOT, radio, 'en', 'power', spec), 'power 5 watts')

    def test_ftx_tuner_external_off_and_atas(self):
        radio = create_dummy_radio()
        radio.model_id = '0840'
        state = {'ac':'101', 'selection':'2'}
        commands = []
        def exchange(radio, command):
            commands.append(command)
            if command == 'AC;': return 'AC'+state['ac']+';'
            if command == 'EX030104;': return 'EX030104'+state['selection']+';'
            if command.startswith('EX030104'): state['selection'] = command[-2]
            elif command.startswith('AC'): state['ac'] = command[2:-1]
            return ''
        with patch.object(yac, '_cat_exchange', side_effect=exchange):
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), 'tuner ATAS')
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), 'tuner off')
        self.assertNotIn('AC123;', commands)  # Selection never initiates tuning.
        self.assertEqual(state['selection'], '0')  # ATAS stop is not tuner bypass.

    def test_all_catalog_labels_exist_and_translate_placeholders(self):
        formatter = string.Formatter()
        for number in range(111, 140):
            english = (ROOT/'lang/en/labels'/f'l{number:03}').read_text(encoding='utf-8')
            fields = lambda text: {field for _,field,_,_ in formatter.parse(text) if field}
            for language in ('de','pl','es'):
                text = (ROOT/'lang'/language/'labels'/f'l{number:03}').read_text(encoding='utf-8')
                self.assertEqual(fields(english), fields(text))
        for path in (ROOT/'rad_cmds').rglob('settings.json'):
            config = json.loads(path.read_text())
            # A model may support filters without exposing gain/tuner settings
            # (notably CAT ID020, shared by the TS-480 and QMX).
            self.assertTrue(config)
            self.assertTrue(set(config) <= {'preamp', 'attenuator', 'power', 'tuner',
                                           'af_gain', 'rf_gain', 'squelch', 'bandwidth',
                                           'noise_blanker', 'noise_reduction', 'notch', 'contour'})
            if path.parent.name != '020':
                self.assertIn('preamp', config)
                self.assertIn('attenuator', config)


if __name__ == '__main__':
    unittest.main()
