"""Live tone readback in Where am I, with no setter commands."""
import unittest
from pathlib import Path
from unittest.mock import patch

import yac
from modules import tone_status
from modules.find_rad import RadioConnection

ROOT = Path(__file__).resolve().parents[1]


class ToneStatusTests(unittest.TestCase):
    def test_yaesu_live_off_ctcss_dcs_and_invalid(self):
        radio = RadioConnection(None, 'test', 38400, 'CAT', '0840', 'FTX-1')
        cases = [
            ({'CT1;': 'CT10;'}, ''),
            ({'CT1;': 'CT11;', 'CN10;': 'CN10008;'}, 'CTCSS 88.5 Hz TX'),
            ({'CT1;': 'CT12;', 'CN10;': 'CN10008;'}, 'CTCSS 88.5 Hz Both'),
            ({'CT1;': 'CT13;', 'CN11;': 'CN11000;', 'EX010323;': 'EX0103231;',
              'EX010324;': 'EX0103241;'}, 'DCS I 023 Both'),
            ({'CT1;': 'CT11;', 'CN10;': 'CN10999;'}, 'Tone/code unknown'),
            ({}, 'Tone/code unknown'),
        ]
        for replies, expected in cases:
            with self.subTest(expected=expected), patch.object(yac, '_yaesu_vfo_side', 1), \
                 patch.object(yac, '_current_mode', return_value='FM'), \
                 patch.object(yac, '_cat_exchange', side_effect=lambda r,c: replies[c] if c in replies else '?;') as exchange:
                self.assertEqual(tone_status.report(yac, ROOT, radio, 'en'), expected)
                self.assertTrue(all(c.args[1] in replies or c.args[1] == 'CT1;' for c in exchange.call_args_list))

    def test_non_fm_does_not_query_tones(self):
        with patch.object(yac, '_current_mode', return_value='USB'), patch.object(yac, '_cat_exchange') as cat:
            self.assertEqual(tone_status.report(yac, ROOT, None, 'en'), '')
            cat.assert_not_called()

    def test_icom_both_and_dcs_polarity(self):
        radio = RadioConnection(None, 'test', 115200, 'CI-V', 'IC-705', 'IC-705', civ_address=0xA4)
        for state, data, expected in [(2, b'\x00\x08\x85', 'CTCSS 88.5 Hz Both'),
                                       (3, b'\x10\x00\x23', 'DCS 023 TX I, RX N'),
                                       (6, b'\x10\x00\x23', 'DCS I 023 TX'),
                                       (0, b'', '')]:
            def exchange(r, command, sub):
                payload = bytes([state]) if command == 0x16 else data
                return bytes([254, 254, 224, 0xA4, command, sub]) + payload + b'\xfd'
            with self.subTest(state=state), patch.object(yac, '_current_mode', return_value='FM'), \
                 patch.object(yac, '_civ_exchange', side_effect=exchange):
                self.assertEqual(tone_status.report(yac, ROOT, radio, 'en'), expected)

    def test_kenwood_uses_current_tx_or_squelch_tone(self):
        radio = RadioConnection(None, 'test', 38400, 'CAT', '023', 'TS-590SG')
        for replies, expected in [({'CT;':'CT0;', 'TO;':'TO0;'}, ''),
                                  ({'CT;':'CT0;', 'TO;':'TO1;', 'TN;':'TN08;'}, 'CTCSS 88.5 Hz TX'),
                                  ({'CT;':'CT1;', 'TO;':'TO0;', 'CN;':'CN08;'}, 'CTCSS 88.5 Hz Both')]:
            with patch.object(yac, '_current_mode', return_value='FM'), \
                 patch.object(yac, '_cat_exchange', side_effect=lambda r,c: replies[c]):
                self.assertEqual(tone_status.report(yac, ROOT, radio, 'en'), expected)

    def test_w_appends_only_active_or_unknown_tone(self):
        for tone, expected in [('', 'S 9 145.5 FM'), ('CTCSS 88.5 Hz TX', 'S 9 145.5 FM, CTCSS 88.5 Hz TX'),
                               ('Tone/code unknown', 'S 9 145.5 FM, Tone/code unknown')]:
            with patch.object(yac, '_radio_status', return_value='S 9 145.5 FM'), \
                 patch.object(tone_status, 'report', return_value=tone):
                self.assertEqual(yac._dispatch(ROOT, None, 'en', 'w', None), expected)
