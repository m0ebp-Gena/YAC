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
        expected = 'ATT off, preamp off, Power 20 W, tuner internal, tuner off'
        self.assertEqual(controls.verify(yac, ROOT, radio, 'en'), expected)
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'preamp 1')
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'preamp 2')
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'preamp off')
        for expected in ('ATT 6 dB', 'ATT 12 dB', 'ATT 18 dB', 'ATT off'):
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'attenuator'), expected)
        for expected in ('tuner internal, tuner on','tuner external, tuner on','tuner ATAS, tuner on','tuner internal, tuner off'):
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), expected)
        radio.serial.preamp = '2'  # A change made outside YAC is immediately visible.
        self.assertIn('preamp 2', controls.verify(yac, ROOT, radio, 'en'))

    def test_keyboard_routes_top_level_and_settings_keys(self):
        radio = create_dummy_radio()
        keys = iter(['v','p','p','u','s','t','.','.','q','q','v','q', 'y'])
        output = io.StringIO()
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call':'test','lang':'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), redirect_stdout(output):
            self.assertEqual(yac.main([]), 0)
        self.assertIn('ATT 6 dB, preamp 2, Power 20 W, tuner external', output.getvalue())

    def test_tuner_q_returns_to_settings_before_power_and_top_level(self):
        radio = create_dummy_radio()
        keys = iter(['s','t','q','p','q','q','y'])
        output = io.StringIO()
        def power_edit(*args):
            self.assertIn('Done', output.getvalue())
            self.assertNotIn('Top Level', output.getvalue())
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call':'test','lang':'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), \
             patch.object(yac.power_control, 'edit', side_effect=power_edit) as edit, \
             redirect_stdout(output):
            self.assertEqual(yac.main([]), 0)
        edit.assert_called_once()
        self.assertEqual(radio.serial.tuner, '000')  # Entry and q do not change it.

    def test_icom_frames_readback_and_rejected_change(self):
        serial = SettingsSerial(0x94)
        radio = RadioConnection(serial, 'test', 115200, 'CI-V', 'IC-7300', 'IC-7300', civ_address=0x94)
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'attenuator'), 'ATT on')
        self.assertEqual(serial.settings[b'\x11'], b'\x20')
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'preamp 1')
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), 'tuner on')
        self.assertIn('power 20%', controls.verify(yac, ROOT, radio, 'en'))
        serial.reject_setting = True
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'Radio Error')
        self.assertEqual(serial.settings[b'\x16\x02'], b'\x01')

    def test_no_tuner_means_no_tuner_command_or_report(self):
        serial = SettingsSerial(0xA2)
        radio = RadioConnection(serial, 'test', 115200, 'CI-V', 'IC-9700', 'IC-9700', civ_address=0xA2)
        self.assertNotIn('tuner', controls.verify(yac, ROOT, radio, 'en'))
        count = len(serial.writes)
        self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), 'Not Supported')
        self.assertEqual(len(serial.writes), count)
        serial.settings[b'\x16\x02'] = b'\x02'
        self.assertIn('preamp external', controls.verify(yac, ROOT, radio, 'en'))

    def test_failed_read_does_not_become_off_or_cause_write(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_cat_exchange', return_value='?;') as exchange:
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'preamp unknown')
            self.assertTrue(all(call.args[1] == 'PA0;' for call in exchange.call_args_list))
            report = controls.verify(yac, ROOT, radio, 'en')
            self.assertEqual(report, 'Radio Error, preamp unknown, power unknown, tuner unknown')

    def test_cat_readback_mismatch_is_failure(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_cat_exchange', return_value='PA00;') as exchange:
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'Radio Error')
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

    def test_dx10_can_leave_atas_even_when_bypass_is_ignored(self):
        radio = create_dummy_radio()
        radio.serial.tuner_selection = '2'
        radio.serial.tuner = '001'
        original_exchange = yac._cat_exchange
        commands = []
        def exchange(radio, command):
            commands.append(command)
            if command == 'AC000;' and radio.serial.tuner_selection == '2':
                return ''  # Hardware log: ATAS remains enabled.
            return original_exchange(radio, command)
        with patch.object(yac, '_cat_exchange', side_effect=exchange):
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'),
                             'tuner internal, tuner off')
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'),
                             'tuner internal, tuner on')
        self.assertLess(commands.index('EX0301050;'), commands.index('AC000;'))
        self.assertEqual(radio.serial.tuner_selection, '0')
        self.assertEqual(radio.serial.tuner, '001')

    def test_dx10_selects_atas_without_enabling_or_starting_rf(self):
        radio = create_dummy_radio()
        radio.serial.tuner_selection = '1'
        radio.serial.tuner = '001'
        original_exchange = yac._cat_exchange
        commands = []
        def exchange(radio, command):
            commands.append(command)
            return original_exchange(radio, command)
        with patch.object(yac, '_cat_exchange', side_effect=exchange):
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), 'tuner ATAS, tuner on')
        self.assertIn('EX0301052;', commands)
        self.assertFalse(any(c.startswith('TX') or c in ('AC000;', 'AC001;', 'AC002;') for c in commands))

    def test_dx10_failed_menu_change_restores_original_selection(self):
        radio = create_dummy_radio()
        radio.serial.tuner_selection = '0'
        radio.serial.tuner = '001'
        original_exchange = yac._cat_exchange
        commands = []
        def exchange(radio, command):
            commands.append(command)
            if command == 'EX0301051;':
                return ''  # Radio ignored the menu change.
            return original_exchange(radio, command)
        with patch.object(yac, '_cat_exchange', side_effect=exchange):
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'tuner'), 'Radio Error')
        self.assertEqual(radio.serial.tuner_selection, '0')
        self.assertEqual(radio.serial.tuner, '001')
        self.assertNotIn('AC000;', commands)

    def test_ftx_band_specific_preamp_and_power_format(self):
        radio = create_dummy_radio()
        radio.model_id = '0840'
        replies = {'PA1;':'PA11;', 'PA10;':'', 'PC;':'PC2005;'}
        with patch.object(yac, '_current_frequency', return_value='145.5'), \
             patch.object(yac, '_cat_exchange', side_effect=lambda r,c: replies.get(c, 'PA10;')) as exchange:
            self.assertEqual(controls.cycle(yac, ROOT, radio, 'en', 'preamp'), 'Radio Error')
            self.assertNotIn('PA12;', [call.args[1] for call in exchange.call_args_list])
            spec = controls.catalog(ROOT, radio)['power']
            self.assertEqual(controls.describe(yac, ROOT, radio, 'en', 'power', spec), 'Power 5 W')

    def test_all_catalog_labels_exist_and_translate_placeholders(self):
        formatter = string.Formatter()
        for number in (number for number in range(111, 140) if number not in (125, 131)):
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
