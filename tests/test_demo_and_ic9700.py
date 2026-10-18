"""Offline integration coverage for discovery fallback and IC-9700 controls."""
import io
import string
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import lang_sel, find_rad
from modules.dummy_radio import create_dummy_radio
from tests.test_icom_7300 import IcomSerial

ROOT = Path(__file__).resolve().parents[1]


class DemoTests(unittest.TestCase):
    def test_real_radio_connection_stays_under_cursor_until_first_command(self):
        radio = create_dummy_radio()
        radio.is_dummy = False
        radio.model_name = 'IC-705'
        output = io.StringIO()
        def first_command(**kwargs):
            self.assertTrue(output.getvalue().endswith('Radio Connected IC-705'))
            return 'q'
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call': 'TEST', 'lang': 'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=first_command), redirect_stdout(output):
            self.assertEqual(yac.main([]), 0)
        self.assertIn('Radio Connected IC-705\nBye TEST', output.getvalue())

    def test_simulated_label_stays_under_cursor_until_first_command(self):
        radio = create_dummy_radio()
        output = io.StringIO()
        def first_command():
            self.assertTrue(output.getvalue().endswith('Simulated Mode'))
            return 'q'
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call': 'TEST', 'lang': 'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=first_command), redirect_stdout(output):
            self.assertEqual(yac.main([]), 0)
        self.assertIn('Simulated Mode\nBye TEST', output.getvalue())

    def test_failed_discovery_enters_spanish_interface_without_saving_fake_radio(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'local_storage') as directory:
            ini = Path(directory) / 'yac.ini'
            ini.write_text(f'[yac]\nlang=es\ncall=EA3GZA\nplatform={yac.detect_platform()}\n')
            original = ini.read_bytes()
            output = io.StringIO()
            with patch.object(yac, 'find_radios', return_value=[]), redirect_stdout(output):
                radio = yac.connect_radio(ini)
            self.assertTrue(radio.is_dummy)
            self.assertEqual(ini.read_bytes(), original)
            self.assertIn('simulada FT-DX10', output.getvalue())
            keys = iter(['w', '.', ',', 'm', '.', 'q', 'b', '.', 'q',
                         'o', '.', 'o', ',', 'o', '.', 'q', 'z', 'q'])
            with patch.object(yac, 'connect_radio', return_value=radio), \
                 patch.object(yac, '_read_settings', return_value={'call':'EA3GZA','lang':'es'}), \
                 patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), redirect_stdout(output):
                self.assertEqual(yac.main([]), 0)
            self.assertIn('Modo de demostración', output.getvalue())
            self.assertIn('Hasta luego EA3GZA', output.getvalue())
            self.assertNotIn('Falló', output.getvalue())
            self.assertFalse(radio.serial.is_open)

    def test_dummy_frequency_modes_offsets_and_tones(self):
        radio = create_dummy_radio()
        self.assertIn('S 9 7.159 LSB', yac._radio_status(ROOT, radio, 'en'))
        self.assertEqual(yac._set_frequency(ROOT, radio, 'en', '29.6'), '29.6')
        self.assertTrue(yac._set_mode(radio, '4'))
        self.assertIn('88.5', yac._set_tone(ROOT, radio, 'en', '88.5', 'Both'))
        yac._offset_action(ROOT, radio, 'en', 0, 1)
        self.assertEqual(yac._yaesu_offset_state(radio), (10, True, False))
        yac._offset_action(ROOT, radio, 'en', 2, 1)
        self.assertEqual(yac._yaesu_offset_state(radio), (0, False, False))

    def test_spanish_selection_and_complete_translations(self):
        with patch.object(lang_sel, 'read_key', side_effect=['4', ' ']), redirect_stdout(io.StringIO()):
            self.assertEqual(lang_sel.show_language_menu(ROOT), 'es')
        formatter = string.Formatter()
        for group in ['labels', 'help']:
            for english in (ROOT/'lang/en'/group).iterdir():
                spanish = ROOT/'lang/es'/group/english.name
                self.assertTrue(spanish.is_file(), spanish)
                fields = lambda text: {field for _, field, _, _ in formatter.parse(text) if field}
                self.assertEqual(fields(english.read_text(encoding='utf-8-sig')),
                                 fields(spanish.read_text(encoding='utf-8-sig')))

    def test_language_reselection_keeps_confirmation_under_cursor(self):
        output = io.StringIO()
        keys = iter(['2', 'n', '1', ' '])
        expected = iter([None, 'de', None, 'en'])
        def read():
            language = next(expected)
            self.assertFalse(output.getvalue().endswith('\n'))
            if language:
                self.assertTrue(output.getvalue().endswith(
                    lang_sel.read_label(ROOT, language, 'l005')))
            return next(keys)
        with patch.object(lang_sel, 'read_key', side_effect=read), redirect_stdout(output):
            self.assertEqual(lang_sel.show_language_menu(ROOT), 'en')


class IC9700Tests(unittest.TestCase):
    def setUp(self):
        self.serial = IcomSerial(0xA2)
        self.serial.frequencies = [145500000, 433500000]
        self.serial.modes = [5, 1]
        self.radio = find_rad.RadioConnection(self.serial, 'test9700', 115200,
                                            'CI-V', 'IC-9700', 'IC-9700', civ_address=0xA2)
        yac._ICOM_BAND_SETTINGS.clear()
        yac._ICOM_VFO_SELECTION.clear()

    def test_status_frequency_ranges_and_bands(self):
        self.assertEqual(yac._radio_status(ROOT, self.radio, 'en'), 'S 9 145.5 FM')
        for value in ['7.2', '200', '500', '1301']:
            self.assertIn('outside', yac._set_frequency(ROOT, self.radio, 'en', value))
        self.assertFalse(any(packet[4] == 5 for packet in self.serial.writes))
        self.assertEqual(yac._set_frequency(ROOT, self.radio, 'en', '145.525'), '145.525')
        self.assertTrue(yac._icom_band_change(self.radio, 1))
        self.assertEqual(self.serial.frequencies[0], 433000000)
        self.assertTrue(yac._icom_band_change(self.radio, 1))
        self.assertEqual(self.serial.frequencies[0], 1296500000)
        self.assertTrue(yac._icom_band_change(self.radio, -1))
        self.assertEqual(self.serial.frequencies[0], 433000000)

    def test_rit_without_unsupported_xit_commands(self):
        self.assertIn('Receive', yac._offset_action(ROOT, self.radio, 'en', 0, 1))
        self.assertIn('not supported', yac._offset_action(ROOT, self.radio, 'en', 1, 1))
        yac._offset_action(ROOT, self.radio, 'en', 2, 1)
        self.assertEqual((self.serial.offset, self.serial.rit), (0, False))
        self.assertEqual(yac._round_frequency_to_khz(ROOT, self.radio, 'en'), '145.5')
        self.assertFalse(any(packet[4:6] == b'\x21\x02' for packet in self.serial.writes))

    def test_vfo_modes_and_dd_restriction(self):
        self.assertTrue(yac._icom_select_vfo(ROOT, self.radio, 'en').startswith('VFO A'))
        self.assertTrue(yac._icom_select_vfo(ROOT, self.radio, 'en').startswith('VFO B'))
        self.assertTrue(yac._set_mode(self.radio, 0x17))
        self.assertFalse(yac._set_mode(self.radio, 0x22))
        self.serial.frequencies[1] = 1296500000
        for flag, expected in [(b'\x00', True), (b'\x01', False), (None, False)]:
            with patch.object(yac, '_civ_exchange', return_value=b'ignored'), \
                 patch.object(yac, '_civ_response_data', return_value=flag):
                # Only the satellite-state query is mocked; frequency is supplied separately.
                with patch.object(yac, '_current_frequency', return_value='1296.5'):
                    self.assertEqual(0x22 in dict(yac._available_modes(self.radio)), expected)

    def test_fm_tones_use_ic9700_address_and_verify_readback(self):
        self.assertEqual(yac._tone_radio_kind(self.radio), 'ic9700')
        for selection, value, target in [('CTCSS', '88.5', 'TX'),
                                         ('CTCSS', '88.5', 'Both'),
                                         ('DCS N', '023', 'Both'),
                                         ('DCS I', '023', 'Both')]:
            values = {(0x16, 0x5D): b'\x00', (0x1B, 2): b'\x00\x00\x23'}
            def send(radio, command, data):
                values[(command, data[0])] = data[1:]
                return bytes.fromhex('FEFEE0A2FBFD')
            def exchange(radio, command, sub):
                return bytes([0xFE, 0xFE, 0xE0, 0xA2, command, sub]) + values.get((command, sub), b'') + b'\xfd'
            with patch.object(yac, '_civ_send', side_effect=send), \
                 patch.object(yac, '_civ_exchange', side_effect=exchange):
                self.assertTrue(yac._tone_command(self.radio, 'ic9700', selection, value, target))
        self.assertTrue(yac._tone_band_supported('ic9700', '1296.5'))
        self.assertFalse(yac._tone_band_supported('ic9700', '50.5'))


if __name__ == '__main__':
    unittest.main()
