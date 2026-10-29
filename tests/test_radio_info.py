"""Read-only identity report and its accessible line order."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import radio_info
from modules.find_rad import RadioConnection

ROOT = Path(__file__).resolve().parents[1]


class RadioInfoTests(unittest.TestCase):
    def radio(self, model='023', maker='kenwood', protocol='CAT'):
        return RadioConnection(SimpleNamespace(baudrate=38400), 'COM4', 9600,
                               protocol, model, 'Kenwood TS-590SG',
                               port_details={'description': 'Enhanced COM Port',
                                             'vid': '10C4', 'pid': 'EA70',
                                             'serial_number': 'USB123'})

    def report(self, radio, replies):
        commands = []
        def exchange(radio, command):
            commands.append(command)
            value = replies.get(command, '?;')
            if isinstance(value, Exception):
                raise value
            return value
        with patch.object(yac, '_cat_exchange', side_effect=exchange), \
             patch.object(yac, '_read_settings', return_value={'region': '2'}):
            output = radio_info.report(yac, ROOT, radio, 'en')
        return output, commands

    def test_live_baud_line_order_and_firmware(self):
        output, commands = self.report(self.radio(), {'FV;': 'FV1.05;'})
        self.assertEqual(commands, ['FV;'])
        self.assertIn('Baud rate: 38400', output)
        self.assertNotIn('9600', output)
        self.assertIn('YAC region: 2', output)
        lines = output.splitlines()
        self.assertTrue(lines[0].startswith('USB description:'))
        self.assertEqual(lines[-1], 'Firmware: 1.05')
        self.assertLess(output.index('USB serial:'), output.index('Model:'))
        self.assertTrue(all(': ' in line for line in lines))

    def test_qmx_identification_never_uses_ts480_type_query(self):
        output, commands = self.report(self.radio('020'),
            {'VN;': 'VN1_04_009QMX;', 'UI;': 'UI393731390651333152005000;'})
        self.assertEqual(commands, ['VN;', 'UI;'])
        self.assertIn('Manufacturer: QRP Labs', output)
        self.assertIn('Processor ID: 393731390651333152005000', output)
        self.assertNotIn('Kenwood', output)

    def test_ts480_variants_and_unknown_compatible_id(self):
        for code, variant in [('0', 'TS-480HX'), ('1', 'TS-480SAT'), ('2', 'Japan 50 W'), ('3', 'Japan 20 W')]:
            output, commands = self.report(self.radio('020'), {'TY;': f'TY00{code};'})
            self.assertIn(variant, output)
            self.assertEqual(commands, ['VN;', 'TY;'])
        output, commands = self.report(self.radio('020'), {})
        self.assertIn('Model: Model unknown', output)
        self.assertIn('CAT ID: 020', output)
        self.assertNotIn('Manufacturer: Kenwood', output)

    def test_query_failure_is_optional_and_does_not_change_connection(self):
        radio = self.radio()
        output, commands = self.report(radio, {'FV;': OSError('timeout')})
        self.assertNotIn('Firmware:', output)
        self.assertEqual(radio.baudrate, 9600)
        self.assertEqual(radio.serial.baudrate, 38400)

    def test_civ_address_is_not_yac_region_and_no_cat_queries(self):
        radio = self.radio('ic-705', protocol='CI-V')
        radio.civ_address = 0xA5
        output, commands = self.report(radio, {})
        self.assertEqual(commands, [])
        self.assertIn('CI-V address: A5', output)
        self.assertIn('Model: IC-705', output)
        self.assertIn('YAC region: 2', output)

    def test_device_text_cannot_add_terminal_control_or_extra_lines(self):
        radio = self.radio()
        radio.port_details['description'] = 'USB\nforged\x1b[2J'
        output, _ = self.report(radio, {})
        self.assertNotIn('\x1b', output)
        self.assertTrue(output.splitlines()[0].startswith('USB description: USBforged'))

    def test_control_refresh_help_and_exit(self):
        keys = iter(['i', 'h', 'q'])
        with patch.object(radio_info, 'report', return_value='Model: test') as report, \
             patch.object(radio_info.help_int, 'get_help', return_value='Info help'), \
             redirect_stdout(io.StringIO()) as output:
            radio_info.control(yac, ROOT, self.radio(), 'en', lambda: next(keys))
        self.assertEqual(report.call_count, 2)
        self.assertIn('Info help', output.getvalue())
        self.assertIn('Done', output.getvalue())

    def test_languages_and_settings_route(self):
        for language in ('en', 'de', 'es', 'pl'):
            for number in range(378, 397):
                value = (ROOT / f'lang/{language}/labels/l{number}').read_text(encoding='utf-8').strip()
                self.assertTrue(value)
                self.assertLessEqual(len(value), 15)
            help_text = (ROOT / f'lang/{language}/help/h036').read_text(encoding='utf-8')
            self.assertTrue(help_text.endswith('***\n'))
        source = (ROOT / 'yac.py').read_text(encoding='utf-8-sig')
        self.assertIn('if settings_key == "i":', source)

    def test_demo_is_explicitly_simulated_without_real_radio_queries(self):
        from modules.dummy_radio import create_dummy_radio
        output, commands = self.report(create_dummy_radio(), {})
        self.assertEqual(commands, [])
        self.assertIn('Manufacturer: YAC Demo', output)
        self.assertIn('Radio serial: DEMO-RADIO-0001', output)
        self.assertIn('Model: FT-DX10 simulation', output)
        self.assertNotIn('Baud rate: 0', output)

    def test_settings_i_returns_to_settings_then_top_level(self):
        from modules import lang_sel
        from modules.dummy_radio import create_dummy_radio
        keys = iter(['s', 'i', 'h', 'i', 'q', 'a', 'q', 'q', 'y'])
        with patch.object(yac, 'connect_radio', return_value=create_dummy_radio()), \
             patch.object(yac, '_read_settings', return_value={'call': 'Test', 'lang': 'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), \
             patch.object(yac.agc_control, 'cycle', return_value='AGC checked') as agc, \
             patch.object(yac, '_set_yac_value') as save, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(yac.main([]), 0)
        self.assertEqual(output.getvalue().count('Model: FT-DX10 simulation'), 2)
        self.assertIn('Radio information help', output.getvalue())
        agc.assert_called_once()
        save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
