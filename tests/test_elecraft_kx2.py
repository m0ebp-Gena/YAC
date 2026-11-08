from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yac
from modules import filter_control, find_rad, gain_control, noise_reduction, radio_info, verify_settings
from modules.cw_control import Settings
from modules.lock_control import Locks


ROOT = Path(__file__).resolve().parents[1]


class KX2Tests(unittest.TestCase):
    def setUp(self):
        self.radio = find_rad.RadioConnection(None, 'test', 38400, 'CAT', 'kx2', 'Elecraft KX2')
        self.values = {
            'FA': '00007030000', 'BN': '03', 'MD': '3', 'RVM': '03.02',
            'SM': '0006', 'AG': '128', 'RG': '250', 'SQ': '000',
            'PA': '0', 'RA': '00', 'PC': '005', 'LK': '0', 'KS': '020',
        }
        self.commands = []
        exchange = patch.object(yac, '_cat_exchange', side_effect=self.exchange)
        exchange.start()
        self.addCleanup(exchange.stop)

    def exchange(self, radio, command):
        self.assertIs(radio, self.radio)
        self.commands.append(command)
        name = 'RVM' if command == 'RVM;' else command[:2]
        value = command[len(name):-1]
        if not value:
            return name + self.values[name] + ';'
        self.values[name] = value
        if name == 'BN':
            self.values['FA'] = '00010106000'
        return ''

    def test_shared_id_requires_kx2_option_reply(self):
        for options, expected in [
            (b'OM A---------01;', 'kx2'), (b'OM A-F-------02;', '017'),
            (b'OM ----------;', '017'), (b'?;', '017'), (b'', '017'),
        ]:
            with self.subTest(options=options), patch.object(
                find_rad, '_exchange', side_effect=[b'FA00007030000;', b'ID017;', options]
            ) as exchange:
                self.assertEqual(find_rad._probe_cat(SimpleNamespace(), [38400]),
                                 (38400, expected, '00007030000'))
                self.assertEqual([c.args[1] for c in exchange.call_args_list],
                                 [b'FA;', b'ID;', b'OM;'])

    def test_frequency_step_and_range(self):
        self.assertEqual(yac._current_frequency(ROOT, self.radio), '7.03')
        yac._set_frequency(ROOT, self.radio, 'en', '7.031')
        self.assertIn('FA00007031000;', self.commands)
        yac._step_frequency(ROOT, self.radio, 'en', {'step_cw': '100'}, -1)
        self.assertEqual(self.values['FA'], '00007030900')
        self.commands.clear()
        self.assertEqual(yac._set_frequency(ROOT, self.radio, 'en', '50.1'), 'Invalid')
        self.assertEqual(self.commands, [])

    def test_band_mode_status_and_information(self):
        with patch.object(yac.elecraft_kx2.time, 'sleep') as settle:
            self.assertIn('10.106', yac._band_change(ROOT, self.radio, 'en', 1))
        settle.assert_called_once_with(0.3)
        self.assertTrue(yac._set_mode(self.radio, '4'))
        self.assertEqual(yac._radio_status(ROOT, self.radio, 'en'), 'S 6 10.106 FM')
        self.values.update(RVM='02.88', MD='3')
        self.commands.clear()
        self.assertFalse(yac._set_mode(self.radio, '4'))
        self.assertNotIn('MD4;', self.commands)
        info = radio_info.report(yac, ROOT, self.radio, 'en')
        self.assertIn('Manufacturer: Elecraft', info)
        self.assertIn('Model: KX2', info)
        self.assertIn('Firmware: 02.88', info)

    def test_live_controls_use_native_ranges_and_readback(self):
        self.assertEqual(gain_control.adjust(yac, ROOT, self.radio, 'en', 'a'), 'AF Gain 50%')
        self.assertEqual(self.commands, ['AG;'])
        self.assertEqual(gain_control.adjust(yac, ROOT, self.radio, 'en', 'r', -1,
                                            {'rf_gain': 5}), 'RF Gain 95%')
        self.values['MD'] = '4'
        self.assertEqual(gain_control.adjust(yac, ROOT, self.radio, 'en', 'r', 1,
                                            {'rf_gain': 5}), 'Squelch 3%')
        self.assertEqual(verify_settings.cycle(yac, ROOT, self.radio, 'en', 'preamp'), 'preamp on')
        self.assertEqual(verify_settings.cycle(yac, ROOT, self.radio, 'en', 'attenuator'), 'ATT on')
        lock = Locks(yac, ROOT, self.radio)
        self.assertEqual(lock.change(lock.read(), 1), 'on')
        speed = Settings(yac, ROOT, self.radio, 'speed')
        self.assertEqual(speed.read(), '20')
        speed.write_value(speed.spec, '025')
        self.assertEqual(speed.read(), '25')

    def test_noise_reduction_entry_and_verified_toggle(self):
        enabled = False
        cat_format = 'K30;'
        commands = []

        def exchange(radio, command):
            nonlocal enabled, cat_format
            commands.append(command)
            if command == 'MD;':
                return 'MD3;'
            if command == 'K3;':
                return cat_format
            if command in ('K30;', 'K31;'):
                cat_format = command
                return ''
            if command == 'DS;':
                self.assertEqual(cat_format, 'K31;')
                return 'DS12345678\x80' + ('\x84' if enabled else '\x80') + ';'
            if command == 'MN;':
                return 'MN255;'
            if command == 'SWH19;':
                enabled = not enabled
                return ''
            self.fail(command)

        keys = iter(['r', 'h', 'r', 'r', 'q', 'q'])
        with patch.object(yac, '_cat_exchange', side_effect=exchange), \
             patch.object(filter_control.chat_int, 'show_response') as response:
            filter_control.control(yac, ROOT, self.radio, 'en', 'Test',
                                   keys.__next__, SimpleNamespace(lost=False))
        output = [call.args[0] for call in response.call_args_list]
        self.assertEqual(output[1], 'NR Off')
        self.assertIn('Noise reduction help', output[2])
        self.assertEqual(output[3:5], ['NR On', 'NR Off'])
        self.assertEqual(commands.count('SWH19;'), 2)
        self.assertEqual(commands[:7], ['MD;', 'K3;', 'K31;', 'K3;', 'DS;', 'K30;', 'K3;'])
        self.assertEqual(cat_format, 'K30;')

    def test_noise_reduction_unreadable_state_does_not_toggle(self):
        replies = ['MD3;', 'K31;', '?;']
        with patch.object(yac, '_cat_exchange', side_effect=replies) as exchange:
            self.assertEqual(noise_reduction.operate(yac, ROOT, self.radio, 'en',
                                                     toggle=True), 'Radio Error')
        self.assertEqual([c.args[1] for c in exchange.call_args_list], ['MD;', 'K3;', 'DS;'])
