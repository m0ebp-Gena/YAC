"""Offset selection and verification never implicitly clear the radio."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import offset_control
from modules.dummy_radio import create_dummy_radio
from tests import test_icom_7300, test_ts480

ROOT = Path(__file__).resolve().parents[1]


class OffsetControlTests(unittest.TestCase):
    def run_control(self, radio, keys, language='en'):
        with redirect_stdout(io.StringIO()) as output:
            offset_control.control(yac, ROOT, radio, language, 'test',
                                   iter(keys).__next__, SimpleNamespace(lost=False))
        return output.getvalue()

    def test_open_select_and_quit_preserve_value_and_enable_states(self):
        radio = create_dummy_radio()
        radio.serial.offset = 120
        radio.serial.receive = True
        radio.serial.transmit = False
        with patch.object(yac, '_cat_exchange', wraps=yac._cat_exchange) as exchange:
            output = self.run_control(radio, ['o', 'o', 'q'])
        exchange.assert_not_called()
        self.assertEqual((radio.serial.offset, radio.serial.receive, radio.serial.transmit), (120, True, False))
        lines = [line for line in output.splitlines() if line]
        self.assertEqual(lines[:2], ['Receive', 'v Verify, c Clear Offset, h Help'])
        self.assertEqual(lines.count('Receive'), 2)
        self.assertEqual(lines.count('Transmit'), 1)
        self.assertNotIn('Clear', lines)

    def test_live_verify_reports_effective_offsets_and_changes_nothing(self):
        radio = create_dummy_radio()
        radio.serial.offset = -40
        radio.serial.receive = True
        radio.serial.transmit = False
        output = self.run_control(radio, ['v', 'q'])
        self.assertIn('Receive Minus 40, Transmit 0', output)
        self.assertEqual((radio.serial.offset, radio.serial.receive, radio.serial.transmit), (-40, True, False))
        radio.serial.receive = False
        self.assertEqual(offset_control.verify(yac, ROOT, radio, 'en'), 'Receive 0, Transmit 0')
        self.assertEqual(radio.serial.offset, -40)

    def test_adjustments_start_at_retained_value_and_q_keeps_them(self):
        radio = create_dummy_radio()
        radio.serial.offset = 40
        output = self.run_control(radio, ['.', 'v', 'o', '.', 'v', 'q'])
        self.assertIn('Receive Plus 50, Transmit 0', output)
        self.assertIn('Receive Plus 60, Transmit Plus 60', output)
        self.assertEqual((radio.serial.offset, radio.serial.receive, radio.serial.transmit), (60, True, True))

    def test_c_clears_both_without_switching_selected_side(self):
        radio = create_dummy_radio()
        radio.serial.offset = 90
        radio.serial.receive = radio.serial.transmit = True
        output = self.run_control(radio, ['o', 'c', 'v', 'q'])
        self.assertIn('Clear', output.splitlines())
        self.assertIn('Receive 0, Transmit 0', output)
        self.assertEqual((radio.serial.offset, radio.serial.receive, radio.serial.transmit), (0, False, False))
        self.assertEqual(output.splitlines().count('Receive'), 1)
        self.assertEqual(output.splitlines().count('Transmit'), 1)

    def test_icom_verify_preserves_native_state_then_explicit_clear(self):
        for radio, serial in test_icom_7300.Icom7300Tests().radios():
            self.assertEqual(offset_control.verify(yac, ROOT, radio, 'en'), 'Receive Plus 40, Transmit Plus 40')
            self.assertEqual((serial.offset, serial.rit, serial.xit), (40, True, True))
            self.run_control(radio, ['c', 'v', 'q'])
            self.assertEqual((serial.offset, serial.rit, serial.xit), (0, False, False))

    def test_ts480_verify_and_clear(self):
        rig = test_ts480.TS480()
        radio = test_ts480.TS480Tests().radio()
        rig.offset, rig.rit, rig.xit = -30, '0', '1'
        with patch.object(yac, '_cat_exchange', side_effect=rig.exchange):
            self.assertEqual(offset_control.verify(yac, ROOT, radio, 'en'), 'Receive 0, Transmit Minus 30')
            self.assertTrue(all(command in {'TY;', 'IF;'} for command in rig.commands))
            self.run_control(radio, ['c', 'v', 'q'])
        self.assertEqual((rig.offset, rig.rit, rig.xit), (0, '0', '0'))

    def test_unknown_state_does_not_clear_or_adjust(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_yaesu_offset_state', return_value=None), \
             patch.object(yac, '_set_yaesu_offset') as setter:
            output = self.run_control(radio, ['v', 'c', '.', 'q'])
        setter.assert_not_called()
        self.assertEqual(output.count('Radio Error'), 3)

    def test_hint_and_help_are_aligned_in_all_languages(self):
        for language in ('en', 'de', 'es', 'pl'):
            hint = (ROOT/f'lang/{language}/hints/m005').read_text(encoding='utf-8').strip()
            self.assertLessEqual(len(hint), 50)
            for key in ('v ', 'c ', 'h '):
                self.assertIn(key, hint)
            output = self.run_control(create_dummy_radio(), ['h', 'q'], language)
            self.assertIn((ROOT/f'lang/{language}/help/h040').read_text(encoding='utf-8').strip(), output)


if __name__ == '__main__':
    unittest.main()
