"""Shared ID020 needs positive identification before using QMX commands."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import find_rad


class QmxIdentityTests(unittest.TestCase):
    def radio(self):
        return SimpleNamespace(protocol='CAT', model_id='020', serial=object(),
                               model_name='CAT ID020', manufacturer_key='kenwood')

    def test_positive_identity_and_rejected_or_malformed_reply(self):
        for reply, expected in [(b'VN1_04_004QMX;', 'QRP Labs QMX'),
                                (b'VN1_04_004QMX+;', 'QRP Labs QMX Plus'),
                                (b'?;', 'CAT ID020'), (b'VNQMX;', 'CAT ID020')]:
            radio = self.radio()
            with self.subTest(reply=reply), patch.object(find_rad, '_exchange', return_value=reply) as exchange:
                find_rad._identify_id020(radio)
                self.assertEqual(radio.model_name, expected)
                self.assertEqual(hasattr(radio, 'qmx_firmware'), expected != 'CAT ID020')
                exchange.assert_called_once_with(radio.serial, b'VN;', b';')

    def test_signal_query_depends_on_confirmed_identity(self):
        for firmware, response, expected, command in [
            ('1_04_004QMX', 'SM-97;', 'S Minus 97 dB', 'SM;'),
            ('1_04_004QMX', '?;', 'S ?', 'SM;'),
            (None, 'SM00015;', 'S 15', 'SM0;'),
        ]:
            radio = self.radio()
            radio.qmx_firmware = firmware
            with self.subTest(response=response), \
                 patch.object(yac, '_current_frequency', return_value='7.03'), \
                 patch.object(yac, '_current_mode', return_value='CW'), \
                 patch.object(yac, '_cat_exchange', return_value=response) as exchange:
                text = yac._radio_status(Path(__file__).resolve().parents[1], radio, 'en')
                self.assertEqual(text, expected + ' 7.03 CW')
                exchange.assert_called_once_with(radio, command)
