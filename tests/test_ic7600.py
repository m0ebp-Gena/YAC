"""IC-7600 frames, discovery and control integration without serial hardware."""
import unittest
from pathlib import Path
import yac
from modules import find_rad
from tests.test_icom_7300 import IcomSerial

ROOT = Path(__file__).resolve().parents[1]


class IC7600Serial(IcomSerial):
    def write(self, packet):
        if packet[4] == 7:
            self.writes.append(packet)
            assert packet[5:-1] in (b'\xd0', b'\xd1'), packet.hex()
            self.vfo = packet[5] - 0xD0
            self.buffer.extend(bytes([0xFE, 0xFE, 0xE0, self.address, 0xFB, 0xFD]))
            return len(packet)
        return super().write(packet)


class IC7600Tests(unittest.TestCase):
    def setUp(self):
        self.serial = IC7600Serial(0x7A)
        self.radio = find_rad.RadioConnection(self.serial, 'mock7600', 19200,
                                            'CI-V', 'IC-7600', 'IC-7600', civ_address=0x7A)
        yac._ICOM_BAND_SETTINGS.clear()
        yac._ICOM_VFO_SELECTION.clear()

    def test_discovery_default_and_custom_address(self):
        self.assertIn(0x7A, find_rad.CIV_ADDRESSES)
        for address in [0x7A, 0x80]:
            serial = IC7600Serial(address)
            serial.identity = 0x7A
            result = find_rad._probe_civ(serial, [19200], [address])
            self.assertEqual(result[1], address)
            self.assertEqual(find_rad.CI_V_MODELS[result[3]], 'IC-7600')

    def test_frequency_modes_status_and_limits(self):
        self.assertEqual(yac._radio_status(ROOT, self.radio, 'en'), 'S 9 7.159123 LSB')
        for value in ['0.029999', '60.000001', '70.2', '145.5']:
            self.serial.writes.clear()
            self.assertIn('outside', yac._set_frequency(ROOT, self.radio, 'en', value))
            self.assertEqual(self.serial.writes, [])
        self.assertEqual(yac._set_frequency(ROOT, self.radio, 'en', '14.185001'), '14.185001')
        for code, label in yac._available_modes(self.radio):
            self.assertTrue(yac._set_mode(self.radio, code))
            self.assertEqual(yac._current_mode_code(self.radio), code)
        self.assertEqual(dict(yac._available_modes(self.radio))[0x13], 'PSK-R')

    def test_main_sub_and_band_navigation(self):
        self.assertTrue(yac._icom_select_vfo(ROOT, self.radio, 'en').startswith('Main '))
        self.assertTrue(yac._icom_select_vfo(ROOT, self.radio, 'en').startswith('Sub '))
        self.assertEqual(yac._set_frequency(ROOT, self.radio, 'en', '18.118'), '18.118')
        self.assertEqual(self.serial.frequencies, [7159123, 18118000])
        self.serial.frequencies[1] = 52000000
        self.assertFalse(yac._icom_band_change(self.radio, 1))
        self.assertTrue(yac._icom_band_change(self.radio, -1))
        self.assertEqual(self.serial.frequencies[1], 28850000)

    def test_firmware_two_offsets_and_rounding(self):
        yac._offset_action(ROOT, self.radio, 'en', 0, 1)
        self.assertEqual(self.serial.offset, 50)
        yac._offset_action(ROOT, self.radio, 'en', 1, -1)
        self.assertEqual(self.serial.offset, 40)
        self.assertEqual(yac._round_frequency_to_khz(ROOT, self.radio, 'en'), '7.159')
        self.assertEqual((self.serial.offset, self.serial.rit, self.serial.xit), (40, True, True))

    def test_rejected_setting_restores_frequency(self):
        self.serial.mismatch = True
        self.assertIn('restored', yac._set_frequency(ROOT, self.radio, 'en', '14.185'))
        self.assertEqual(self.serial.frequencies[0], 7159123)


if __name__ == '__main__':
    unittest.main()
