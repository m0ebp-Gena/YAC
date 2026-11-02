"""Delay readback, monotonic limits, native units and unchanged Break-in."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import cw_control as cw
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection

ROOT = Path(__file__).resolve().parents[1]


class DelayTests(unittest.TestCase):
    def adjust(self, radio, keys, language='en', watch=None):
        with redirect_stdout(io.StringIO()) as output:
            pending = cw.adjustment(yac, ROOT, radio, language, 'delay',
                                    iter(keys).__next__, watch or SimpleNamespace(lost=False))
        return output.getvalue(), pending

    def test_every_yaesu_value_entry_repeat_help_exit_send_only_reads(self):
        for language in ('en', 'de', 'es', 'pl'):
            for value in range(34):
                radio = create_dummy_radio()
                radio.serial.cw_delay = f'{value:02}'
                before = dict(radio.serial.cw)
                with patch.object(yac, '_cat_exchange', wraps=yac._cat_exchange) as exchange:
                    output, _ = self.adjust(radio, ['d', 'h', 'q'], language)
                self.assertEqual([c.args[1] for c in exchange.call_args_list], ['SD;', 'SD;'])
                self.assertEqual(radio.serial.cw_delay, f'{value:02}')
                self.assertEqual(radio.serial.cw, before)
                self.assertIn(yac._read_label(ROOT, language, 'l420', ''), output)

    def test_all_yaesu_profiles_step_table_and_clamped_limits(self):
        expected = [30, 50, 100, 150, 200, 250] + list(range(300, 3001, 100))
        for model in ('0761', '0800', '0840'):
            radio = RadioConnection(None, 'test', 38400, 'CAT', model, model)
            value = [0]
            commands = []
            def exchange(radio, command):
                commands.append(command)
                if command == 'SD;':
                    return f'SD{value[0]:02};'
                self.assertRegex(command, r'^SD\d{2};$')
                value[0] = int(command[2:4])
                return ''
            backend = cw.Delay(yac, ROOT, radio, 'delay')
            with patch.object(yac, '_cat_exchange', side_effect=exchange):
                self.assertEqual(backend.change(-1), '30')
                self.assertEqual(commands, ['SD;'])
                for target in expected[1:]:
                    self.assertEqual(backend.change(1), str(target))
                commands.clear()
                self.assertEqual(backend.change(1), '3000')
                self.assertEqual(commands, ['SD;'])
                for target in reversed(expected[:-1]):
                    self.assertEqual(backend.change(-1), str(target))
            self.assertEqual(value[0], 0)

    def test_invalid_cat_reply_never_sets_a_default(self):
        for reply in ('', '?;', 'SD34;', 'SD-1;', 'SD6;', 'SD06;SD07;'):
            with patch.object(yac, '_cat_exchange', return_value=reply) as exchange:
                output, _ = self.adjust(create_dummy_radio(), [])
            self.assertEqual([c.args[1] for c in exchange.call_args_list], ['SD;'])
            self.assertNotIn('Delay 300', output)

    def test_failed_cat_change_does_not_announce_target(self):
        with patch.object(yac, '_cat_exchange', side_effect=['SD06;', 'SD06;', '', 'SD06;']):
            output, _ = self.adjust(create_dummy_radio(), ['.', 'q'])
        self.assertIn('Delay 300 milliseconds', output)
        self.assertNotIn('Delay 400 milliseconds', output)

    def test_reread_external_change_and_preserve_break_in_in_all_states(self):
        for enabled, kind in [('0', '0'), ('1', '0'), ('1', '1')]:
            radio = create_dummy_radio()
            radio.serial.cw.update(BI=enabled, EX020113=kind, KR='1')
            before = dict(radio.serial.cw)
            def keys():
                radio.serial.cw_delay = '06'
                yield '.'
                yield 'q'
            self.adjust(radio, keys())
            self.assertEqual(radio.serial.cw_delay, '07')
            self.assertEqual(radio.serial.cw, before)
            self.adjust(radio, ['q'])
            self.assertEqual(radio.serial.cw_delay, '07')

    def test_icom_relative_levels_all_raw_values_directions_and_languages(self):
        for model, address in [('IC-705', 0xa4), ('IC-7300', 0x94),
                               ('IC-7300MK2', 0xb6), ('IC-7600', 0x7a), ('IC-9700', 0xa2)]:
            radio = RadioConnection(None, 'test', 115200, 'CI-V', model, model, civ_address=address)
            raw = [0]
            writes = []
            def read(radio, command, sub):
                self.assertEqual((command, sub), (0x14, 0x0f))
                return bytes([254, 254, 224, address, command, sub]) + bytes.fromhex(f'{raw[0]:04}') + b'\xfd'
            def send(radio, command, data):
                self.assertEqual((command, data[0], len(data)), (0x14, 0x0f, 3))
                raw[0] = int(data[1:].hex())
                writes.append(raw[0])
                return bytes([254, 254, 224, address, 251, 253])
            backend = cw.Delay(yac, ROOT, radio, 'delay')
            with patch.object(yac, '_civ_exchange', side_effect=read), patch.object(yac, '_civ_send', side_effect=send):
                for initial in range(256):
                    raw[0] = initial
                    self.assertEqual(backend.read(), str(min(range(16), key=lambda n: abs(n*17-initial))+1))
                    for direction in (-1, 1):
                        raw[0] = initial
                        writes.clear()
                        candidates = [n for n in range(0,256,17) if (n-initial)*direction > 0]
                        target = (min(candidates) if direction > 0 else max(candidates)) if candidates else initial
                        level = backend.change(direction)
                        self.assertEqual(raw[0], target)
                        self.assertEqual(writes, [target] if target != initial else [])
                        self.assertEqual(level, str(target//17+1))
                for language in ('en','de','es','pl'):
                    raw[0] = 10
                    writes.clear()
                    output, _ = self.adjust(radio, ['d','h','q'], language)
                    self.assertEqual(raw[0], 10)
                    self.assertEqual(writes, [])
                    self.assertIn(yac._read_label(ROOT, language, 'l421', '').format(value=2), output)

    def test_icom_invalid_delay_and_negative_ack_do_not_announce_success(self):
        radio = RadioConnection(None, 'test', 115200, 'CI-V', 'IC-705', 'IC-705', civ_address=0xa4)
        prefix = b'\xfe\xfe\xe0\xa4'
        for data in (b'', b'\x00', b'\x02\x56', b'\x00\xfa', b'\x00\x00\x00'):
            with patch.object(yac, '_civ_exchange', return_value=prefix+b'\x14\x0f'+data+b'\xfd'), \
                 patch.object(yac, '_civ_send') as send:
                output, _ = self.adjust(radio, [])
            send.assert_not_called()
            self.assertNotIn('Delay Level', output)
        with patch.object(yac, '_civ_exchange', return_value=prefix+b'\x14\x0f\x00\x00\xfd'), \
             patch.object(yac, '_civ_send', return_value=prefix+b'\xfa\xfd'):
            output, _ = self.adjust(radio, ['.','q'])
        self.assertIn('Delay Level 1', output)
        self.assertNotIn('Delay Level 2', output)
        with patch.object(yac, '_civ_exchange', return_value=prefix+b'\x14\x0f\x00\x00\xfd'), \
             patch.object(yac, '_civ_send', return_value=prefix+b'\xfb\xfd'):
            output, _ = self.adjust(radio, ['.','q'])
        self.assertNotIn('Delay Level 2', output)  # Acknowledgement alone is insufficient.

    def test_unsupported_delay_no_commands_and_disconnect_no_change(self):
        radio = RadioConnection(None, 'test', 115200, 'CI-V', 'IC-7610', 'IC-7610', civ_address=0x98)
        with patch.object(yac, '_civ_exchange') as read, patch.object(yac, '_civ_send') as send:
            output, _ = self.adjust(radio, [])
        self.assertIn('Not Supported', output)
        read.assert_not_called()
        send.assert_not_called()
        radio = create_dummy_radio()
        _, pending = self.adjust(radio, ['.'], watch=SimpleNamespace(lost=True))
        self.assertEqual(pending, '.')
        self.assertEqual(radio.serial.cw_delay, '00')

    def test_menu_d_returns_to_cw_before_q_leaves_and_help_is_generic(self):
        radio = create_dummy_radio()
        keys = iter(['d', '.', 'd', 'h', 'q', 'q'])
        with redirect_stdout(io.StringIO()) as output:
            cw.control(yac, ROOT, radio, 'en', keys.__next__, SimpleNamespace(lost=False))
        self.assertIn('Delay 50 milliseconds', output.getvalue())
        self.assertLess(output.getvalue().rfind('Done'), output.getvalue().rfind('Top Level'))
        for language, end in [('en','End of help'),('de','Ende der Hilfe'),('es','Fin de la ayuda'),('pl','Koniec pomocy')]:
            text = (ROOT / f'lang/{language}/help/h045').read_text(encoding='utf-8').strip()
            self.assertTrue(text.endswith('***\n' + end + '\n***'))
            self.assertNotRegex(text, r'Icom|Yaesu|Kenwood|FTX|IC-705')
            for number in (419, 420, 421):
                label = yac._read_label(ROOT, language, f'l{number}', '')
                self.assertLessEqual(len(label.replace('{value}', '').replace('{unit}', '')), 15)


if __name__ == '__main__':
    unittest.main()
