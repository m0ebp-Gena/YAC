"""Model-specific AGC cycling, mode guards and verified readback."""
import io
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
import yac
from modules import agc_control as agc, lang_sel
from modules.find_rad import RadioConnection
from modules.dummy_radio import create_dummy_radio
from tests.test_verify_settings import SettingsSerial

ROOT = Path(__file__).resolve().parents[1]


class AgcTests(unittest.TestCase):
    def test_demo_cycle_including_auto_readback(self):
        radio = create_dummy_radio()
        results = [agc.cycle(yac, ROOT, radio, 'en') for _ in range(5)]
        self.assertEqual(results, ['AGC Off', 'AGC Fast', 'AGC Mid', 'AGC Slow', 'AGC Auto Slow'])
        self.assertEqual(radio.serial.mic_gain, 50)
        self.assertEqual(radio.serial.power, '020')

    def test_ftx_selected_sub_and_auto_codes(self):
        radio = RadioConnection(None, 'test', 38400, 'CAT', '0840', 'FTX-1')
        for current in '456':
            with patch.object(yac, '_yaesu_vfo_side', 1), patch.object(yac, '_current_mode', return_value='USB'), patch.object(yac, '_cat_exchange', side_effect=[f'GT1{current};', '', 'GT10;']) as commands:
                self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'Sub AGC Off')
                self.assertEqual([c.args[1] for c in commands.call_args_list], ['GT1;', 'GT10;', 'GT1;'])

    def test_icom_bcd_selection_and_rejection(self):
        serial = SettingsSerial(0xa4)
        serial.settings[b'\x16\x12'] = b'\x01'
        radio = RadioConnection(serial, 'test', 115200, 'CI-V', 'IC-705', 'IC-705', civ_address=0xa4)
        with patch.object(yac, '_current_mode', return_value='USB'):
            self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'AGC Mid')
            self.assertEqual(serial.settings[b'\x16\x12'], b'\x02')
            serial.reject_setting = True
            self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'Setting change failed')

    def test_fixed_icom_modes_send_no_agc_commands(self):
        radio = RadioConnection(None, 'test', 115200, 'CI-V', 'IC-9700', 'IC-9700', civ_address=0xa2)
        for mode in ['FM', 'FM-N', 'WFM', 'DV', 'DD']:
            with patch.object(yac, '_current_mode', return_value=mode), patch.object(yac, '_civ_exchange') as commands:
                self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'AGC Fast fixed in this mode; no change')
                commands.assert_not_called()

    def test_kenwood_590_uses_gc_not_custom_gt(self):
        radio = RadioConnection(None, 'test', 9600, 'CAT', '023', 'TS-590SG')
        with patch.object(yac, '_current_mode', return_value='USB'), patch.object(yac, '_cat_exchange', side_effect=['GC1;', '', 'GC0;']) as commands:
            self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'AGC Off')
            self.assertEqual([c.args[1] for c in commands.call_args_list], ['GC;', 'GC0;', 'GC;'])

    def test_ts480_identity_and_three_digit_commands(self):
        radio = RadioConnection(None, 'test', 9600, 'CAT', '020', 'TS-480')
        with patch.object(agc.ts480_control, 'variant', return_value='1'), patch.object(yac, '_current_mode', return_value='CW'), patch.object(yac, '_cat_exchange', side_effect=['GT000;', '', 'GT001;']) as commands:
            self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'AGC Fast')
            self.assertEqual([c.args[1] for c in commands.call_args_list], ['GT;', 'GT001;', 'GT;'])
        with patch.object(agc.ts480_control, 'variant', return_value=None), patch.object(yac, '_cat_exchange') as commands:
            self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'Not supported')
            commands.assert_not_called()

    def test_kenwood_fm_does_not_query_or_write_agc(self):
        radio = RadioConnection(None, 'test', 9600, 'CAT', '023', 'TS-590SG')
        with patch.object(yac, '_current_mode', return_value='FM'), patch.object(yac, '_cat_exchange') as commands:
            self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'AGC unavailable in FM; no change')
            commands.assert_not_called()

    def test_unknown_reading_and_mismatch(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_current_mode', return_value='USB'), patch.object(yac, '_cat_exchange', return_value='GT09;') as commands:
            self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'AGC unknown; no change')
            commands.assert_called_once_with(radio, 'GT0;')
        with patch.object(yac, '_current_mode', return_value='USB'), patch.object(yac, '_cat_exchange', side_effect=['GT01;', '', 'GT01;']):
            self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'Setting change failed')

    def test_mode_change_prevents_write(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_current_mode', side_effect=['USB', 'FM']), patch.object(agc.settings, '_write') as write:
            self.assertEqual(agc.cycle(yac, ROOT, radio, 'en'), 'AGC unknown; no change')
            write.assert_not_called()

    def test_keyboard_stays_in_settings_and_help(self):
        radio = create_dummy_radio()
        keys = iter(['s', 'a', 'a', 'h', 'q', 'q'])
        with patch.object(yac, 'connect_radio', return_value=radio), patch.object(yac, '_read_settings', return_value={'call':'test','lang':'en'}), patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(yac.main([]), 0)
        self.assertIn('AGC Off', output.getvalue())
        self.assertIn('AGC Fast', output.getvalue())
        self.assertIn('AGC controls receiver recovery', output.getvalue())
        self.assertIn('Back', output.getvalue())
        self.assertIn('Bye test', output.getvalue())
