"""Preparation gates, manual TX, protocol frames and peak reporting."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import mic_gain as mic, lang_sel
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
from tests.test_verify_settings import SettingsSerial

ROOT = Path(__file__).resolve().parents[1]


class MicGainTests(unittest.TestCase):
    def run_control(self, keys, radio=None):
        radio = radio or create_dummy_radio()
        sequence = iter(keys)
        output = io.StringIO()
        with redirect_stdout(output):
            mic.control(yac, ROOT, radio, 'en',
                        lambda **kwargs: next(sequence), SimpleNamespace(lost=False))
        return radio, output.getvalue()

    def test_cancel_at_either_preparation_prompt_writes_nothing(self):
        for keys in [['q']]:
            with patch.object(yac, '_cat_exchange') as exchange:
                _, output = self.run_control(keys)
                exchange.assert_not_called()
            self.assertIn('Done', output)

    def test_preparation_help_does_not_acknowledge_readiness(self):
        with patch.object(yac, '_cat_exchange') as exchange:
            _, output = self.run_control(['h', 'q'])
            exchange.assert_not_called()
        self.assertIn('Lower power does not make an unsuitable load safe', output)

    def test_demo_changes_only_mic_gain_and_keeps_value_on_exit(self):
        radio = create_dummy_radio()
        commands = []
        original = yac._cat_exchange
        def exchange(radio, command):
            commands.append(command)
            return original(radio, command)
        with patch.object(yac, '_cat_exchange', side_effect=exchange):
            _, output = self.run_control([' ', '.', 'v', 'q'], radio)
        self.assertEqual(radio.serial.mic_gain, 51)
        self.assertEqual(radio.serial.power, '020')
        self.assertEqual(radio.serial.frequency, 7159000)
        self.assertEqual(radio.serial.mode, '1')
        self.assertIn('Mic Gain 51%', output)
        self.assertTrue(all(c in {'MG;', 'TX;', 'MD0;'} or c.startswith('MG0') for c in commands), commands)

    def test_icom_bcd_step_and_rejection(self):
        serial = SettingsSerial(0xa4)
        serial.settings[b'\x14\x0b'] = bytes.fromhex('01 28')
        radio = RadioConnection(serial, 'test', 115200, 'CI-V', 'IC-705', 'IC-705', civ_address=0xa4)
        spec = mic.profile(yac, radio)
        self.assertEqual(mic.adjust(yac, radio, spec, 1), 131)
        self.assertEqual(serial.settings[b'\x14\x0b'], bytes.fromhex('01 31'))
        serial.reject_setting = True
        self.assertIsNone(mic.adjust(yac, radio, spec, -1))

    def test_native_endpoints_and_readback_mismatch(self):
        radio = create_dummy_radio()
        spec = mic.profile(yac, radio)
        radio.serial.mic_gain = 100
        self.assertEqual(mic.adjust(yac, radio, spec, 1), 100)
        with patch.object(mic.settings, '_write', return_value=True):
            self.assertIsNone(mic.adjust(yac, radio, spec, -1))

    def test_peak_zero_missing_and_repeated_transmissions(self):
        peak = mic.Peak()
        self.assertIsNone(peak.sample(True, 0))
        self.assertEqual(peak.sample(False, None), 0)
        peak.sample(True, 40)
        peak.sample(True, 70)
        self.assertEqual(peak.sample(False, None), 70)
        peak.sample(True, None)
        peak.sample(True, 25)
        self.assertEqual(peak.sample(False, None), 'unknown')

    def test_meter_parsing_and_no_meter_selection_write(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_cat_exchange', return_value='RM4123000;'):
            self.assertEqual(mic.alc(yac, radio, mic.profile(yac, radio)), 123)
        radio = RadioConnection(None, 'test', 9600, 'CAT', '023', 'TS-590SG')
        with patch.object(yac, '_cat_exchange', return_value='RM10001;RM20002;RM30013;') as exchange:
            self.assertEqual(mic.alc(yac, radio, mic.profile(yac, radio)), 13)
            exchange.assert_called_once_with(radio, 'RM;')
        with patch.object(yac, '_cat_exchange', return_value='RM10001;'):
            self.assertIsNone(mic.alc(yac, radio, mic.profile(yac, radio)))

    def test_ts480_identity_does_not_enable_qmx(self):
        radio = RadioConnection(None, 'test', 9600, 'CAT', '020', 'unknown')
        with patch.object(mic.ts480_control, 'variant', return_value=None):
            self.assertIsNone(mic.profile(yac, radio))
        with patch.object(mic.ts480_control, 'variant', return_value='1'):
            spec = mic.profile(yac, radio)
            with patch.object(yac, '_cat_exchange', return_value='RM30011;'):
                self.assertIsNone(mic.alc(yac, radio, spec))

    def test_initial_tx_blocks_adjustment(self):
        with patch.object(mic, 'tx_state', return_value=True), patch.object(mic, 'adjust') as adjust:
            _, output = self.run_control([' '])
            adjust.assert_not_called()
        self.assertIn('Release PTT', output)

    def test_mode_change_blocks_writes(self):
        with patch.object(yac, '_current_mode', side_effect=['LSB', 'CW']), patch.object(mic, 'adjust') as adjust:
            _, output = self.run_control([' ', '.'])
            adjust.assert_not_called()
        self.assertIn('Select SSB', output)

    def test_settings_route_returns_to_settings(self):
        radio = create_dummy_radio()
        keys = iter(['s', 'm', ' ', '.', 'q', 'q', 'q', 'y'])
        with patch.object(yac, 'connect_radio', return_value=radio), patch.object(yac, '_read_settings', return_value={'call':'test','lang':'en'}), patch.object(lang_sel, 'read_key', side_effect=lambda **kwargs: next(keys)), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(yac.main([]), 0)
        self.assertEqual(output.getvalue().count('Done'), 1)
        self.assertEqual(output.getvalue().count('Back'), 1)
        self.assertIn('Bye test', output.getvalue())

    def test_idle_polling_reports_peak_after_ptt_release(self):
        radio = create_dummy_radio()
        keys = iter([' ', 'q', 'y'])
        def read_key(idle_callback=None):
            if idle_callback:
                idle_callback()
                idle_callback()
                idle_callback()
            return next(keys)
        with patch.object(mic, 'tx_state', side_effect=[False, False, True, True, False]), patch.object(mic, 'alc', side_effect=[42, 77]), patch.object(mic, 'monotonic', side_effect=range(100)), redirect_stdout(io.StringIO()) as output:
            mic.control(yac, ROOT, radio, 'en', read_key, SimpleNamespace(lost=False))
        self.assertIn('Peak ALC 77 raw', output.getvalue())

    def test_kenwood_if_status_position(self):
        radio = RadioConnection(None, 'test', 9600, 'CAT', '023', 'TS-590SG')
        spec = mic.profile(yac, radio)
        body = '00014175000' + ' ' * 5 + '+0000' + '00' + '000' + '1' + '20000000'
        self.assertEqual(len(body), 35)
        with patch.object(yac, '_cat_exchange', return_value='IF' + body + ';'):
            self.assertTrue(mic.tx_state(yac, radio, spec))

    def test_icom_read_only_status_and_alc_frames(self):
        radio = RadioConnection(None, 'test', 115200, 'CI-V', 'IC-705', 'IC-705', civ_address=0xa4)
        spec = mic.profile(yac, radio)
        with patch.object(yac, '_civ_exchange', return_value=b'ignored') as exchange, patch.object(yac, '_civ_response_data', return_value=b'\x01'):
            self.assertTrue(mic.tx_state(yac, radio, spec))
            exchange.assert_called_once_with(radio, 0x1c, 0)
        with patch.object(yac, '_civ_exchange', return_value=b'ignored') as exchange, patch.object(yac, '_civ_response_data', return_value=bytes.fromhex('00 72')):
            self.assertEqual(mic.alc(yac, radio, spec), 72)
            exchange.assert_called_once_with(radio, 0x15, 0x13)


if __name__ == '__main__':
    unittest.main()
