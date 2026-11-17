from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import yac
from modules import radio_power


ROOT = Path(__file__).resolve().parents[1]


class RadioPowerTests(unittest.TestCase):
    def test_wake_sequences_follow_model_and_baud(self):
        cases = (
            ('CAT', '0761', 'FT-DX10', None, 38400, ((0, b'PS1;'), (1.05, b'PS1;'))),
            ('CAT', '0800', 'FT-710', None, 38400, ((0, b'PS1;'),)),
            ('CAT', '019', 'TS-2000', None, 9600, ((0, b'PS1;'),)),
            ('CAT', '020', 'TS-480 SAT', None, 9600, ((0, b';;;PS1;'),)),
            ('CAT', '021', 'TS-590S', None, 9600, ((0, b';'), (0.25, b'PS1;'))),
            ('CAT', '023', 'TS-590SG', None, 9600, ((0, b';'), (0.25, b'PS1;'))),
            ('CAT', '024', 'TS-890S', None, 9600, ((0, b';'), (0.1, b'PS1;'))),
            ('CAT', '020', 'QRP Labs QMX Plus', None, 9600, ()),
            ('CAT', '0840', 'FTX-1', None, 38400, ()),
            ('CAT', 'kx2', 'Elecraft KX2', None, 38400, ()),
        )
        for protocol, model, name, address, rate, expected in cases:
            with self.subTest(model=name):
                self.assertEqual(
                    radio_power._wake_sequence(protocol, model, name, address, rate), expected,
                )
        for model, address, count in (('ic-7100', 0x88, 25), ('ic-7300', 0x94, 25),
                                      ('ic-7300mk2', 0xB6, 25),
                                      ('ic-9700', 0xA2, 20), ('ic-7610', 0x98, 25),
                                      ('ic-7600', 0x7A, 0), ('ic-705', 0xA4, 0)):
            with self.subTest(model=model):
                packet = bytes([0xFE] * (count + 2) + [address, 0xE0, 0x18, 0x01, 0xFD])
                self.assertEqual(
                    radio_power._wake_sequence('CI-V', model, model, address, 19200),
                    ((0, packet),),
                )

    def test_quit_sends_model_specific_shutdown(self):
        for protocol, model, address, packet in (
            ('CI-V', 'IC-7300', 0x94, bytes.fromhex('FE FE 94 E0 18 00 FD')),
            ('CAT', '0840', None, b'PS0;'),
            ('CAT', 'kx2', None, b'PS0;'),
            ('CAT', '020', None, b'PS0;'),
            ('CAT', '023', None, b'PS9;'),
            ('CAT', '019', None, b'PS0;'),
            ('CAT', 'unknown', None, None),
        ):
            with self.subTest(model=model):
                radio = SimpleNamespace(
                    is_dummy=False, protocol=protocol, model_id=model, civ_address=address,
                    model_name=model, port='COM9', usb_identity='', serial=MagicMock(),
                )
                radio_power.power_off(radio)
                if packet:
                    radio.serial.write.assert_called_once_with(packet)
                else:
                    radio.serial.write.assert_not_called()

    def test_qmx_shutdown_requires_firmware_with_ps_support(self):
        for firmware, supported in (('1_03_002QMX', False), ('1_04_001QMX', True),
                                    ('1_04_000QMX+', True)):
            with self.subTest(firmware=firmware):
                radio = SimpleNamespace(
                    is_dummy=False, protocol='CAT', model_id='020', civ_address=None,
                    model_name='QRP Labs QMX', port='COM9', usb_identity='',
                    serial=MagicMock(), qmx_firmware=firmware,
                )
                radio_power.power_off(radio)
                self.assertEqual(radio.serial.write.call_count, int(supported))

    def test_numbered_selection_can_include_awake_and_sleeping_radios(self):
        profiles = [
            {'model_id': 'IC-7300', 'protocol': 'CI-V', 'civ_address': '0x94',
             'usb_identity': '10C4:EA60:7300', 'baud_rate': '19200', 'model': 'IC-7300'},
            {'model_id': '020', 'protocol': 'CAT', 'port_hint': 'COM1',
             'baud_rate': '9600', 'model': 'TS-480'},
            {'model_id': '0840', 'protocol': 'CAT', 'port_hint': 'COM4',
             'baud_rate': '38400', 'model': 'FTX-1'},
        ]
        ports = [
            SimpleNamespace(device='COM9', vid=0x10C4, pid=0xEA60, serial_number='7300'),
            SimpleNamespace(device='COM1', vid=None),
            SimpleNamespace(device='COM4', vid=None),
        ]
        running = MagicMock(port='COM10', usb_identity='10C4:EA60:705',
                            model_name='IC-705', baudrate=19200)
        with patch('serial.tools.list_ports.comports', return_value=ports), \
             patch.object(radio_power.find_rad, '_radio_profiles', return_value=profiles):
            candidates = radio_power.wake_candidates(ROOT / 'yac.ini', [running])
        self.assertEqual([candidate.port for candidate in candidates], ['COM9', 'COM1'])
        with patch.object(yac.lang_sel, 'read_key', return_value='2'), redirect_stdout(StringIO()):
            chosen = yac._choose_radio([running, *candidates], ROOT, 'en')
        self.assertIs(chosen, candidates[0])
        running.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
