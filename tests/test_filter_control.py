"""Protocol tables, live readback and nested keyboard behaviour."""
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import filter_control as filters, lang_sel
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
from tests.test_verify_settings import SettingsSerial

ROOT = Path(__file__).resolve().parents[1]


class FilterTests(unittest.TestCase):
    def radio(self, model):
        return RadioConnection(None, 'test', 38400, 'CAT', model, model)

    def test_demo_current_width_limits_and_live_changes(self):
        radio = create_dummy_radio()
        self.assertEqual(filters.adjust(yac, ROOT, radio, 'en'), 'Bandwidth 3000 Hz')
        self.assertEqual(radio.serial.bandwidth, '20')
        self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Bandwidth 3200 Hz')
        radio.serial.bandwidth = '23'
        self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Bandwidth 4000 Hz')
        radio.serial.bandwidth = '01'
        self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', -1), 'Bandwidth 300 Hz')
        radio.serial.mode = '3'
        self.assertEqual(filters.adjust(yac, ROOT, radio, 'en'), 'Bandwidth 50 Hz')

    def test_yaesu_sides_formats_fixed_modes_and_default(self):
        for model in ('0761', '0800', '0840'):
            radio = self.radio(model)
            side = '1' if model == '0840' else '0'
            value = ['20']
            commands = []
            def exchange(radio, command):
                commands.append(command)
                if command != f'SH{side};':
                    self.assertEqual(command, f'SH{side}021;')
                    value[0] = '21'
                return f'SH{side}0{value[0]};'
            with patch.object(yac, '_cat_exchange', side_effect=exchange), \
                 patch.object(yac, '_current_mode_code', return_value='2'), \
                 patch.object(yac, '_yaesu_vfo_side', 1):
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Bandwidth 3200 Hz')
                value[0] = '00'
                commands.clear()
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en'), 'Bandwidth default')
                self.assertIn('Default width unknown', filters.adjust(yac, ROOT, radio, 'en', 1))
                self.assertTrue(all(cmd == f'SH{side};' for cmd in commands))
            if model != '0761':
                with patch.object(yac, '_current_mode_code', return_value='4'), \
                     patch.object(yac, '_yaesu_vfo_side', 1), \
                     patch.object(yac, '_cat_exchange', return_value=f'SH{side}003;') as exchange:
                    self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', -1), 'Bandwidth 16000 Hz')
                    self.assertEqual(exchange.call_count, 1)

    def test_all_icom_wire_bcd_and_mode_ranges(self):
        for model, address in [('IC-705',0xA4), ('IC-7300',0x94), ('IC-7300MK2',0xB6),
                               ('IC-7600',0x7A), ('IC-9700',0xA2)]:
            radio = RadioConnection(SettingsSerial(address), 'test', 115200,
                                    'CI-V', model, model, civ_address=address)
            radio.serial.settings[b'\x1a\x03'] = b'\x28'
            with patch.object(yac, '_current_mode_code', return_value=1):
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en'), 'Bandwidth 2400 Hz')
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Bandwidth 2500 Hz')
                self.assertEqual(radio.serial.settings[b'\x1a\x03'], b'\x29')
                radio.serial.reject_setting = True
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Setting change failed')
                radio.serial.reject_setting = False
                radio.serial.settings[b'\x1a\x03'] = b'\x0a'
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Bandwidth unknown')
            radio.serial.settings[b'\x1a\x03'] = b'\x49'
            with patch.object(yac, '_current_mode_code', return_value=2):
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Bandwidth 10000 Hz')
            with patch.object(yac, '_current_mode_code', return_value=5):
                before = len(radio.serial.writes)
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Not supported')
                self.assertEqual(len(radio.serial.writes), before)

    def test_kenwood_edges_keep_other_edge_and_width_is_separate(self):
        for model in ('023', '020'):
            radio = self.radio(model)
            state = {'SH':'10', 'SL':'04'}
            commands = []
            def exchange(radio, command):
                commands.append(command)
                if command.startswith('MM'): return '?;'
                if command == 'EX0450000;': return 'EX04500000;'
                if command == 'DA;': return 'DA0;'
                if command == 'EX0280000;': return 'EX02800001;'
                name = command[:2]
                if len(command) > 3: state[name] = command[2:-1]
                return name + state[name] + ';'
            with patch.object(yac, '_current_mode_code', return_value='2'), \
                 patch.object(yac, '_cat_exchange', side_effect=exchange):
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Use Low Cut l or Upper Cut u')
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1, 'l'), 'Low Cut 400 Hz')
                self.assertEqual(state['SH'], '10')
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1, 'u'), 'Upper Cut 3400 Hz')
                self.assertEqual(state['SL'], '05')
                self.assertNotIn('FW;', commands)

    def test_kenwood_direct_width_layouts_and_cw(self):
        for model in ('023', '020'):
            radio = self.radio(model)
            state = ['08' if model == '023' else '03']
            def exchange(radio, command):
                if command.startswith('MM'): return '?;'
                if command == 'EX0450000;': return 'EX04500001;'
                if command == 'DA;': return 'DA1;'
                if command == 'EX0290000;': return 'EX02900002;'
                if command.startswith('SL'):
                    if command != 'SL;': state[0] = command[2:-1]
                    return 'SL'+state[0]+';'
                if command == 'FW;': return 'FW0500;'
                if command == 'FW0600;': return command
                return '?;'
            with patch.object(yac, '_cat_exchange', side_effect=exchange), \
                 patch.object(yac, '_current_mode_code', return_value='2'):
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1),
                                 'Bandwidth 600 Hz' if model == '023' else 'Bandwidth 1000 Hz')
                self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1, 'l'), 'Not supported')

    def test_qmx_uses_menu_enabled_filters_not_read_only_fw(self):
        radio = self.radio('020')
        current = ['300']
        commands = []
        def exchange(radio, command):
            commands.append(command)
            if command == 'MMCW|CW passband;': return 'MM'+current[0]+';'
            if command.startswith('MMCW|Choose filters|'):
                return 'MMDISABLED;' if command.endswith('|6;') else 'MMENABLED;'
            if command.startswith('MMCW|CW passband='):
                current[0] = command.split('=')[1][:-1]
            return '?;'
        with patch.object(yac, '_cat_exchange', side_effect=exchange), \
             patch.object(yac, '_current_mode_code', return_value='3'):
            self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Bandwidth 500 Hz')
            self.assertIn('MU;', commands)
            self.assertFalse(any(cmd.startswith(('FW', 'EX', 'SL', 'SH')) for cmd in commands))
            self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Bandwidth wide')
            self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', -1), 'Bandwidth 500 Hz')

    def test_unknown_reads_and_ambiguous_id_never_write(self):
        for model in ('0761', '020', '023'):
            with patch.object(yac, '_current_mode_code', return_value='2'), \
                 patch.object(yac, '_cat_exchange', return_value='?;') as exchange:
                self.assertEqual(filters.adjust(yac, ROOT, self.radio(model), 'en', 1), 'Bandwidth unknown')
                self.assertTrue(all(call.args[1].endswith(';') for call in exchange.call_args_list))
                self.assertFalse(any('=' in call.args[1] for call in exchange.call_args_list))

    def test_qmx_ssb_width_and_failed_readback(self):
        radio = self.radio('020')
        state = ['2700']
        def exchange(radio, command):
            if command == 'MMCW|CW passband;': return 'MM300;'
            if command == 'MMSSB|Filter RX;': return 'MM'+state[0]+';'
            if command == 'MMSSB|Filter RX=2900;': state[0] = '2900'
            return '?;'
        with patch.object(yac, '_current_mode_code', return_value='2'), \
             patch.object(yac, '_cat_exchange', side_effect=exchange):
            self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1), 'Bandwidth 2900 Hz')
            self.assertEqual(filters.adjust(yac, ROOT, radio, 'en', 1, 'u'), 'Not supported')
        with patch.object(yac, '_current_mode_code', return_value='2'), \
             patch.object(yac, '_cat_exchange', return_value='SH0020;'):
            self.assertEqual(filters.adjust(yac, ROOT, self.radio('0761'), 'en', 1),
                             'Setting change failed')

    def test_edge_endpoint_cannot_cross_other_edge(self):
        replies = {'DA;':'DA0;', 'EX0280000;':'EX02800001;',
                   'SH;':'SH00;', 'SL;':'SL10;'}
        with patch.object(yac, '_current_mode_code', return_value='2'), \
             patch.object(yac, '_cat_exchange', side_effect=lambda r,c:replies[c]) as exchange:
            self.assertEqual(filters.adjust(yac, ROOT, self.radio('023'), 'en', 1, 'l'),
                             'Low Cut 900 Hz')
            self.assertTrue(all(call.args[1] in replies for call in exchange.call_args_list))

    def test_nested_q_and_forwarded_command(self):
        radio = create_dummy_radio()
        keys = iter(['f','p','.','q','h','q','w','q', 'y'])
        output = io.StringIO()
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call':'test','lang':'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), redirect_stdout(output):
            self.assertEqual(yac.main([]), 0)
        self.assertEqual(radio.serial.bandwidth, '21')
        self.assertIn('Bandwidth 3200 Hz', output.getvalue())
        self.assertIn('Filters: p', output.getvalue())

    def test_catalog_values_are_ordered_and_labels_translated(self):
        for path in (ROOT/'rad_cmds').rglob('settings.json'):
            feature = json.loads(path.read_text()).get('bandwidth')
            if feature:
                for profile in feature['profiles'].values():
                    self.assertEqual(list(profile['values'].values()), sorted(profile['values'].values()))
        for lang in ('en','de','es','pl'):
            for number in (65,82,83,147,148,149,150,151,152):
                self.assertTrue((ROOT/f'lang/{lang}/labels/l{number:03d}').read_text().strip())


if __name__ == '__main__':
    unittest.main()
