"""CI-V integration checks against simulated IC-7300 and IC-7300MK2 radios."""
import unittest
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock
import yac
from modules import find_rad, lang_sel
from modules.icom_profile import load_profile

ROOT = Path(__file__).resolve().parent
MODELS = [('IC-7300', 0x94), ('IC-7300MK2', 0xB6)]


class IcomSerial:
    """Use real YAC frame encoders/decoders, with echoes and fragmented replies."""
    def __init__(self, address):
        self.address = address
        self.identity = address
        self.timeout = .12
        self.baudrate = 115200
        self.buffer = bytearray()
        self.writes = []
        self.vfo = 0
        self.frequencies = [7159123, 14185000]
        self.modes = [0, 1]
        self.filters = [2, 1]
        self.offset = 40
        self.rit = True
        self.xit = True
        self.reject = None
        self.mismatch = False

    @property
    def in_waiting(self):
        return len(self.buffer)

    def reset_input_buffer(self):
        self.buffer.clear()

    def flush(self):
        pass

    def close(self):
        pass

    def read(self, count):
        result = bytes(self.buffer[:min(count, 3)])
        del self.buffer[:len(result)]
        return result

    def write(self, packet):
        self.writes.append(packet)
        command = packet[4]
        data = packet[5:-1]
        prefix = bytes([0xFE, 0xFE, 0xE0, self.address])
        self.buffer.extend(packet)  # Local interface echo.
        if packet[2] != self.address:
            return
        if self.reject == command:
            self.reject = None
            self.buffer.extend(prefix + b'\xfa\xfd')
            return
        if command == 3:
            reply = b'\x03' + yac._civ_frequency_bytes(self.frequencies[self.vfo])
        elif command == 4:
            reply = bytes([4, self.modes[self.vfo], self.filters[self.vfo]])
        elif command == 0x15:
            reply = bytes.fromhex('15020120')
        elif command == 0x19:
            reply = bytes([0x19, 0, self.identity])
        elif command == 0x21 and len(data) == 1:
            sub = data[0]
            if sub == 0:
                digits = f'{abs(self.offset):04d}'
                reply = bytes([0x21, 0, int(digits[2:], 16), int(digits[:2], 16), int(self.offset < 0)])
            else:
                reply = bytes([0x21, sub, int(self.rit if sub == 1 else self.xit)])
        else:
            if command == 5:
                self.frequencies[self.vfo] = round(float(yac._civ_bcd_frequency(data))*1e6)
                if self.mismatch:
                    self.frequencies[self.vfo] += 1
                    self.mismatch = False
            elif command == 6:
                self.modes[self.vfo] = data[0]
                self.filters[self.vfo] = data[1] if len(data) > 1 else 1
            elif command == 7:
                self.vfo = data[0]
            elif command == 0x21:
                if data[0] == 0:
                    magnitude = int(f'{data[2]:02X}{data[1]:02X}')
                    self.offset = -magnitude if data[3] else magnitude
                elif data[0] == 1:
                    self.rit = bool(data[1])
                else:
                    self.xit = bool(data[1])
            else:
                raise AssertionError(f'Unexpected command {packet.hex()}')
            reply = b'\xfb'
        self.buffer.extend(prefix + reply + b'\xfd')


class Icom7300Tests(unittest.TestCase):
    def setUp(self):
        yac._ICOM_BAND_SETTINGS.clear()
        yac._ICOM_VFO_SELECTION.clear()

    def radios(self):
        for model, address in MODELS:
            serial = IcomSerial(address)
            yield find_rad.RadioConnection(serial, 'mock-' + model, 115200, 'CI-V', model, model, civ_address=address), serial

    def test_status_and_one_hz_frequency_entry(self):
        for radio, serial in self.radios():
            with self.subTest(model=radio.model_id):
                self.assertTrue(yac._radio_status(ROOT, radio, 'en').endswith('7.159123 LSB'))
                self.assertEqual(yac._set_frequency(ROOT, radio, 'en', '14.185001'), '14.185001')
                self.assertEqual(serial.frequencies[0], 14185001)
                self.assertIn(bytes([0xFE, 0xFE, radio.civ_address, 0xE0, 5]) + bytes.fromhex('0150181400') + b'\xfd', serial.writes)

    def test_frequency_limits_and_invalid_input_do_not_write(self):
        for radio, serial in self.radios():
            for value in ['nan', 'inf', '-1', '0', '0.029999', '74.800001', '145', 'garbage']:
                with self.subTest(model=radio.model_id, value=value):
                    serial.writes.clear()
                    yac._set_frequency(ROOT, radio, 'en', value)
                    self.assertFalse(serial.writes)
            self.assertEqual(yac._set_frequency(ROOT, radio, 'en', '.030'), '0.03')
            self.assertEqual(yac._set_frequency(ROOT, radio, 'en', '74.8'), '74.8')

    def test_rejection_and_one_hz_mismatch_restore_previous_frequency(self):
        for radio, serial in self.radios():
            for failure in ['reject', 'mismatch']:
                with self.subTest(model=radio.model_id, failure=failure):
                    if failure == 'reject': serial.reject = 5
                    else: serial.mismatch = True
                    self.assertIn('restored', yac._set_frequency(ROOT, radio, 'en', '14.185'))
                    self.assertEqual(serial.frequencies[0], 7159123)

    def test_missing_frequency_prevents_change(self):
        for radio, serial in self.radios():
            serial.reject = 3
            self.assertIn('cancelled', yac._set_frequency(ROOT, radio, 'en', '14.185'))
            self.assertFalse(any(packet[4] == 5 for packet in serial.writes))

    def test_supported_modes_and_steps(self):
        for radio, serial in self.radios():
            for code, name in yac._available_modes(radio):
                self.assertTrue(yac._set_mode(radio, code))
                self.assertEqual(yac._current_mode_code(radio), code)
            self.assertFalse(yac._set_mode(radio, 0x17))
            self.assertNotIn(6, dict(yac._available_modes(radio)))
            for code, step in [(0,1000),(3,500),(2,2500),(5,12500)]:
                serial.modes[0] = code
                serial.frequencies[0] = 7159123
                yac._step_frequency(ROOT, radio, 'en', {}, 1)
                self.assertEqual(serial.frequencies[0], 7159123 + step)
                yac._step_frequency(ROOT, radio, 'en', {}, -1)
                self.assertEqual(serial.frequencies[0], 7159123)
            yac._step_frequency(ROOT, radio, 'en', {'step_fm':'125'}, 1)
            self.assertEqual(serial.frequencies[0], 7159248)

    def test_band_navigation_remembers_frequency_mode_and_filter(self):
        for radio, serial in self.radios():
            with self.subTest(model=radio.model_id):
                self.assertTrue(yac._icom_band_change(radio, 1))
                self.assertEqual(serial.frequencies[0], 10125000)
                self.assertTrue(yac._icom_band_change(radio, -1))
                self.assertEqual((serial.frequencies[0], serial.modes[0], serial.filters[0]), (7159123, 0, 2))
                serial.frequencies[0] = 52000000
                self.assertTrue(yac._icom_band_change(radio, 1))
                self.assertEqual(serial.frequencies[0], 70200000)
                self.assertFalse(yac._icom_band_change(radio, 1))
                self.assertLess(max(load_profile(ROOT, radio.model_id)['bands_hz']), 75000000)

    def test_rejected_band_mode_restores_previous_settings(self):
        for radio, serial in self.radios():
            serial.reject = 6
            self.assertFalse(yac._icom_band_change(radio, 1))
            self.assertEqual((serial.frequencies[0], serial.modes[0], serial.filters[0]), (7159123, 0, 2))

    def test_rounding_preserves_offsets_and_enable_states(self):
        for radio, serial in self.radios():
            for hz, expected in [(7159123,7159000),(7159500,7160000)]:
                serial.frequencies[0] = hz
                self.assertEqual(round(float(yac._round_frequency_to_khz(ROOT, radio, 'en'))*1e6), expected)
                self.assertEqual((serial.offset,serial.rit,serial.xit),(40,True,True))

    def test_offsets_receive_transmit_and_clear(self):
        for radio, serial in self.radios():
            self.assertTrue(yac._zero_offsets(radio))
            yac._offset_action(ROOT,radio,'en',0,-1)
            self.assertEqual(serial.offset,-10)
            yac._offset_action(ROOT,radio,'en',1,1)
            self.assertEqual(serial.offset,0)
            yac._offset_action(ROOT,radio,'en',2,1)
            self.assertEqual((serial.offset,serial.rit,serial.xit),(0,False,False))
            self.assertIsNone(yac._tone_radio_kind(radio))

    def test_vfo_selection_and_rejection(self):
        for radio, serial in self.radios():
            self.assertTrue(yac._icom_select_vfo(ROOT,radio,'en').startswith('VFO A'))
            self.assertTrue(yac._icom_select_vfo(ROOT,radio,'en').startswith('VFO B'))
            self.assertEqual(yac._set_frequency(ROOT,radio,'en','18.118'), '18.118')
            self.assertEqual(serial.frequencies,[7159123,18118000])
            serial.reject=7
            self.assertNotIn('VFO A',yac._icom_select_vfo(ROOT,radio,'en'))
            self.assertEqual(serial.vfo,1)

    def test_discovery_identity_at_changed_address(self):
        for model, identity in MODELS:
            serial=IcomSerial(0x80)
            serial.identity=identity
            result=find_rad._probe_civ(serial,[115200],[0x80])
            self.assertEqual(result[1],0x80)
            self.assertEqual(find_rad.CI_V_MODELS[result[3]],model)
        self.assertIn(0xB6,find_rad.CIV_ADDRESSES)

    def test_bcd_and_wrong_address_responses(self):
        self.assertIsNone(yac._civ_bcd_frequency(bytes.fromhex('FA00000000')))
        self.assertIsNone(yac._civ_bcd_frequency(b'\0'*4))
        self.assertIsNone(yac._civ_response_data(bytes.fromhex('FEFEE094030015070000FD'),0xB6,3))

    def test_keyboard_loop_uses_new_radio_controls(self):
        for radio, serial in self.radios():
            keys = iter(['w', 'e', '.', ',', 'm', '.', 'q', 'b', '.', 'q',
                         'o', '.', 'o', ',', 'o', '.', 'q', 'z', 's', 's', 'v', 'v', 'q', 'q'])
            output = io.StringIO()
            with patch.object(yac, 'connect_radio', return_value=radio), \
                 patch.object(yac, '_read_settings', return_value={'call':'test','lang':'en'}), \
                 patch.object(yac, '_set_yac_value') as save, \
                 patch.object(lang_sel, 'read_key', side_effect=lambda:next(keys)), \
                 patch('builtins.input', side_effect=['14.185001','250']), redirect_stdout(output):
                self.assertEqual(yac.main([]), 0)
            self.assertIn('VFO A',output.getvalue())
            self.assertIn('VFO B',output.getvalue())
            self.assertIn('Bye test',output.getvalue())
            save.assert_called_once()
            self.assertEqual(serial.vfo,1)

    def test_radio_list_has_no_selection_before_number(self):
        radios = [radio for radio, serial in self.radios()]
        for radio in radios:
            radio.serial.close = MagicMock()
        output = io.StringIO()
        keys = iter([' ', 'h', '9', '2', ' '])
        calls = []
        def read_key():
            calls.append(output.getvalue())
            return next(keys)
        with patch('modules.lang_sel.read_key',side_effect=read_key), redirect_stdout(output):
            chosen = yac._choose_radio(radios,ROOT,'en')
        self.assertIs(chosen,radios[1])
        self.assertNotIn('Selected:',output.getvalue())
        self.assertEqual(calls[0].count('IC-7300 ('),1)
        self.assertNotIn('2. IC-7300MK2\n',calls[0])
        self.assertIn('2. IC-7300MK2\n',calls[-1])
        radios[0].serial.close.assert_called_once()
        radios[1].serial.close.assert_not_called()

    def test_space_before_number_does_not_choose_radio(self):
        radios = [radio for radio,serial in self.radios()]
        with patch('modules.lang_sel.read_key',side_effect=[' ','q']), redirect_stdout(io.StringIO()):
            self.assertIsNone(yac._choose_radio(radios,ROOT,'en'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
