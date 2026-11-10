from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from modules.nexus_ft8 import NexusReceive
from modules.decoder_control import DecoderManager
from modules.ft_decode_filter import distance_settings, grid_center, message_distance
import yac


ROOT = Path(__file__).resolve().parents[1]


class FTDecodeFilterTests(unittest.TestCase):
    def test_distance_uses_the_grid_and_excludes_acknowledgements(self):
        origin = grid_center('io83ps')
        self.assertEqual(grid_center('IO83PS'), origin)
        self.assertIsNone(grid_center('IO83ZZ'))
        self.assertAlmostEqual(message_distance('CQ DX W1AW FN31', origin), 5211, delta=10)
        self.assertAlmostEqual(message_distance('CQ W1AW JJ01', grid_center('JJ00')), 111.195, places=3)
        self.assertLess(message_distance('M0AAA G4BBB R IO91', origin), 400)
        self.assertIsNone(message_distance('M0AAA W1AW RR73', origin))
        self.assertIsNone(message_distance('CQ W1AW', origin))

    def test_selector_filters_the_same_history_in_kilometres_or_miles(self):
        manager = DecoderManager(yac, ROOT, None, 'en')
        manager.ft_origin = grid_center('IO83PS')
        manager.ft_buffer.extend([
            ('CQ DX W1AW FN31', 'far CQ'),
            ('CQ G4BBB IO91', 'near CQ'),
            ('CQ G4BBB', 'CQ without locator'),
            ('M0AAA JA1ABC PM95', 'far reply'),
            ('M0AAA W1AW RR73', 'acknowledgement'),
        ])
        self.assertEqual(manager.review(kind='f')[0], 'acknowledgement')
        self.assertEqual(manager.review(0, kind='f')[0], 'far CQ 5211 km.')
        with patch.object(yac, '_read_settings', return_value={'ft_distance': '4000', 'ft_distance_unit': 'miles'}), \
             patch('modules.chat_int.show_response') as show, patch('modules.chat_int.show_done'):
            manager.ft_filter_control(iter(['.', 'q']).__next__)
            self.assertEqual(manager.ft_lines(), ['far CQ 3238 miles.', 'near CQ 172 miles.',
                                                  'CQ without locator'])
            manager.ft_filter_control(iter(['.', 'q']).__next__)
            self.assertEqual(show.call_args.args[0], 'Over 4000 miles')
            self.assertEqual(manager.ft_lines(), ['far reply 5859 miles.'])
            self.assertEqual(manager.review(kind='f')[0], 'far reply 5859 miles.')
            manager.ft_filter_control(iter(['.', 'q']).__next__)
        self.assertEqual(manager.ft_lines(), ['far CQ 3238 miles.', 'near CQ 172 miles.',
                                              'CQ without locator', 'far reply 5859 miles.',
                                              'acknowledgement'])

    def test_distance_setting_defaults_and_validation(self):
        self.assertEqual(distance_settings({}), (2000, 'km'))
        for unit in ('mi', 'miles', 'MILES'):
            self.assertEqual(distance_settings({'ft_distance_unit': unit}), (2000, 'mi'))
        for settings in ({'ft_distance': 'nan'}, {'ft_distance': '0'}, {'ft_distance_unit': 'yards'}):
            with self.assertRaises(ValueError):
                distance_settings(settings)

    def test_nexus_poll_preserves_message_for_filtering(self):
        def field(text):
            return struct.pack('>I', len(text)) + text

        packet = (bytes.fromhex('adbccbda0000000300000002') + field(b'Tempo')
                  + struct.pack('>BIidI', 1, 45_240_000, -12, .2, 1210)
                  + field(b'FT8') + field(b'CQ DX W1AW FN31') + b'\0\0')
        manager = DecoderManager(yac, ROOT, None, 'en')
        manager.ft_filter = 1
        manager.ft_origin = grid_center('IO83PS')
        receiver = NexusReceive(lambda message, line: manager.ft_buffer.append((message, line)),
                                ROOT / 'host.exe', 'radio', 'speakers', 'N0CALL', 'IO91')
        with patch.object(receiver, 'listener') as listener, patch.object(receiver, 'process') as process:
            process.poll.return_value = None
            listener.recv.side_effect = [packet, BlockingIOError()]
            receiver.poll()
        self.assertEqual(manager.ft_lines(), ['12:34:00 UTC. CQ DX W1AW FN31. Minus 12 dB. 5211 km.'])


if __name__ == '__main__':
    unittest.main()
