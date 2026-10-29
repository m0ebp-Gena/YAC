"""Complete RF transaction and rollback tests using native CAT/CI-V replies."""
import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import swr_control as swr, swr_radio, region_plan
from tests.test_split_control import ROOT, Cat, Civ
from tests.test_ts480 import TS480
from modules.find_rad import RadioConnection


class Clock:
    def __init__(self):
        self.now = 0.0
    def time(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class CarrierCat(Cat):
    def __init__(self, model='0761', side=0):
        super().__init__(model, side)
        self.state.update({'TX': '0', 'VX': '1', 'MG': '057',
                           'PC': '2020' if model == '0840' else '020',
                           'EX010213': '3' if model == '0840' else '1',
                           'EX010214': '1000' if model == '0761' else '3'})
        self.raw = '065' if model == '0840' else '052'
        self.rf = '027'
        self.interrupt = False
        self.lose_swr = False
        self.stop_fail = False
        self.restore_fail = False
        self.tx_seen = False
        self.apply_but_reject_start = False

    def exchange(self, radio, command):
        if command == 'TX1;':
            self.tx_seen = True
            self.state['TX'] = '1'
            if self.apply_but_reject_start:
                self.reject = 'TX;'
        if command == 'TX0;' and self.stop_fail:
            self.commands.append(command)
            return '?;'
        if self.tx_seen and self.restore_fail and command.startswith('MD') and len(command) > 4:
            self.commands.append(command)
            return '?;'
        if command == 'RM6;':
            self.commands.append(command)
            if self.interrupt:
                raise KeyboardInterrupt
            return '?;' if self.lose_swr else 'RM6' + self.raw + '000;'
        if command == 'RM5;':
            self.commands.append(command)
            return 'RM5' + self.rf + '000;'
        return super().exchange(radio, command)


class CarrierCiv(Civ):
    def __init__(self, model='IC-7300'):
        super().__init__()
        self.radio.model_id = model
        self.state.update({(0x14, 0x0a): b'\x00\x51', (0x16, 0x46): b'\x01',
                           (0x1c, 0): b'\x00', (0x15, 0x11): b'\x01\x70',
                           (0x15, 0x12): b'\x00\x48', (0x1a, 0x0b): b'\x00'})
        self.state[(0x26, 0)] = b'\x01\x01\x03'  # USB, data On, filter 3
        if model == 'IC-9700':
            self.state[(0x25, 0)] = yac._civ_frequency_bytes(145500000)
        self.tx_history = []

    def exchange(self, radio, command, sub=None):
        if command in {0x03, 0x04}:
            data = self.state[(0x25, 0)] if command == 0x03 else self.state[(0x26, 0)][::2]
            return bytes((254, 254, 224, 164, command)) + data + b'\xfd'
        return super().exchange(radio, command, sub)

    def send(self, radio, command, payload):
        self.sent.append((command, payload))
        if (command, payload) == self.reject:
            return bytes.fromhex('FEFEE0A4FAFD')
        sub = payload[0] if command in {0x25, 0x26, 0x14, 0x16, 0x1c} else None
        data = payload[1:] if sub is not None else payload
        self.state[(command, sub)] = data
        if command == 0x1c:
            self.tx_history.append(data)
        return bytes.fromhex('FEFEE0A4FBFD')


class CarrierKenwood(TS480):
    def __init__(self):
        super().__init__()
        self.radio = RadioConnection(None, 'test', 38400, 'CAT', '023', 'TS-590SG')
        self.values.update({'MG': '057', 'VX': '1', 'DA': '1'})
        self.mode = '2'
        self.powers = {'2': '020', '5': '015'}
        self.mics = {'2': '057', '5': '025'}
        self.data_modes = {'2': '1', '5': '1'}
        self.tx = False

    def exchange(self, radio, command):
        if command in ('TX0;', 'RX;'):
            self.commands.append(command)
            self.tx = command == 'TX0;'
            return ''
        if command == 'FT;': return 'FT0;'
        if command == 'RM;':
            self.commands.append(command)
            return 'RM10008;RM20000;RM30000;'
        if command == 'IF;':
            result = super().exchange(radio, command)
            return result[:28] + ('1' if self.tx else '0') + result[29:]
        if command.startswith('MD') and command != 'MD;':
            self.powers[self.mode] = self.values['PC']
            self.mics[self.mode] = self.values['MG']
            self.data_modes[self.mode] = self.values['DA']
            result = super().exchange(radio, command)
            self.values['PC'] = self.powers[self.mode]
            self.values['MG'] = self.mics[self.mode]
            self.values['DA'] = self.data_modes[self.mode]
            return result
        return super().exchange(radio, command)


class SWRTests(unittest.TestCase):
    def setUp(self):
        config = patch.object(yac, '_read_settings', return_value={'region': '1'})
        config.start(); self.addCleanup(config.stop)
        side = patch.object(yac, '_yaesu_vfo_side', 0)
        side.start(); self.addCleanup(side.stop)

    def measure_cat(self, rig, **options):
        clock = Clock()
        with patch.object(yac, '_cat_exchange', side_effect=rig.exchange), redirect_stdout(io.StringIO()):
            result = swr.measure(yac, ROOT, rig.radio, 'en', clock=clock.time, sleep=clock.sleep, **options)
        return result

    def test_each_yaesu_restores_usb_lsb_power_mic_vox_and_source(self):
        for model in ('0761', '0800', '0840'):
            for mode in ('1', '2'):
                rig = CarrierCat(model)
                rig.state['MD0'] = mode
                before = dict(rig.state)
                self.assertEqual(self.measure_cat(rig), 'SWR approx 1.5')
                self.assertEqual(rig.state, before)
                self.assertIsNone(rig.radio._swr_pending)
                commands = rig.commands
                start, stop = commands.index('TX1;'), commands.index('TX0;')
                self.assertLess(commands.index('MD05;'), start)
                self.assertLess(start, stop)
                self.assertGreater(commands.index('MD0' + mode + ';'), stop)
                self.assertGreater(commands.index('VX1;'), stop)
                self.assertFalse(any(c.startswith('AC') for c in commands))

    def test_ftx_sub_preserves_main_and_selects_low_power_head(self):
        rig = CarrierCat('0840', side=1)
        rig.state['PC'] = '1006'
        before = dict(rig.state)
        with patch.object(yac, '_yaesu_vfo_side', 1):
            self.assertEqual(self.measure_cat(rig), 'SWR approx 1.5')
        self.assertEqual(rig.state, before)
        self.assertIn('PC1001;', rig.commands)
        self.assertNotIn('MD05;', rig.commands)

    def test_icom_models_use_rtty_and_restore_full_mode_data_filter(self):
        for model, watts in [('IC-7300', 35), ('IC-7300MK2', 35), ('IC-7600', 35),
                              ('IC-705', 6), ('IC-9700', 30)]:
            rig = CarrierCiv(model)
            before = dict(rig.state)
            clock = Clock()
            with patch.object(yac, '_civ_exchange', side_effect=rig.exchange), \
                 patch.object(yac, '_civ_send', side_effect=rig.send), redirect_stdout(io.StringIO()):
                self.assertEqual(swr.measure(yac, ROOT, rig.radio, 'en', clock=clock.time, sleep=clock.sleep),
                                 'SWR approx 1.5')
            self.assertEqual(rig.state, before)
            self.assertEqual(rig.tx_history, [b'\x01', b'\x00'])
            self.assertIn((0x26, b'\x00\x04\x00\x02'), rig.sent)
            scale = 10 if model == 'IC-705' else 100
            power = bytes.fromhex(f'{round(watts * 255 / scale):04d}')
            self.assertIn((0x14, b'\x0a' + power), rig.sent)
            self.assertNotIn((0x1c, b'\x01\x02'), rig.sent)

    def test_705_battery_does_not_silently_substitute_lower_power(self):
        rig = CarrierCiv('IC-705')
        rig.state[(0x1a, 0x0b)] = b'\x01'
        before = dict(rig.state)
        clock = Clock()
        with patch.object(yac, '_civ_exchange', side_effect=rig.exchange), \
             patch.object(yac, '_civ_send', side_effect=rig.send), redirect_stdout(io.StringIO()), \
             self.assertLogs('yac', level='ERROR'):
            self.assertEqual(swr.measure(yac, ROOT, rig.radio, 'en', clock=clock.time, sleep=clock.sleep),
                             'SWR unavailable')
        self.assertEqual(rig.state, before)
        self.assertEqual(rig.tx_history, [])

    def test_receive_only_frequencies_and_edges_never_write(self):
        for hz in (121500000, 156800000, 2182000, 7200000, 54000000):
            rig = CarrierCat()
            rig.state['FA'] = f'{hz:09d}'
            before = dict(rig.state)
            self.assertEqual(self.measure_cat(rig), 'Invalid')
            self.assertEqual(rig.state, before)
            self.assertNotIn('TX1;', rig.commands)
            self.assertFalse(any(c.startswith('MD') and len(c) > 4 for c in rig.commands))

    def test_590_preserves_both_mode_power_and_mic_slots(self):
        rig = CarrierKenwood()
        before = dict(rig.values)
        self.assertEqual(self.measure_cat(rig), 'SWR approx 2.0')
        self.assertEqual(rig.values, before)
        self.assertEqual(rig.powers['5'], '015')
        self.assertEqual(rig.mics['5'], '025')
        self.assertEqual(rig.data_modes['5'], '1')
        self.assertEqual(rig.values['DA'], '1')
        self.assertFalse(rig.tx)
        self.assertLess(rig.commands.index('RX;'), rig.commands.index('MD2;'))

    def test_qmx_and_unverified_480_do_not_issue_transmit_or_setters(self):
        from tests.test_ts480 import TS480Tests
        for variant in ('0', '1'):
            rig = TS480(variant)
            rig.radio = TS480Tests().radio()
            self.assertEqual(self.measure_cat(rig), 'Not Supported')
            self.assertEqual(rig.commands, [])

    def test_missing_rf_or_swr_does_not_announce_one_to_one(self):
        for failure in ('rf', 'swr'):
            rig = CarrierCat()
            if failure == 'rf': rig.rf = '000'
            else: rig.lose_swr = True
            before = dict(rig.state)
            with self.assertLogs('yac', level='ERROR'):
                self.assertEqual(self.measure_cat(rig), 'SWR unavailable')
            self.assertEqual(rig.state, before)

    def test_icom_insufficient_live_rf_is_not_a_valid_swr_result(self):
        rig = CarrierCiv()
        rig.state[(0x15, 0x11)] = b'\x00\x95'  # About 25 W, below manual requirement.
        before = dict(rig.state)
        clock = Clock()
        with patch.object(yac, '_civ_exchange', side_effect=rig.exchange), \
             patch.object(yac, '_civ_send', side_effect=rig.send), redirect_stdout(io.StringIO()), \
             self.assertLogs('yac', level='ERROR'):
            self.assertEqual(swr.measure(yac, ROOT, rig.radio, 'en', clock=clock.time, sleep=clock.sleep),
                             'SWR unavailable')
        self.assertEqual(rig.state, before)

    def test_language_resources_have_short_labels_and_complete_help(self):
        for language, ending in [('en', 'End of help'), ('de', 'Ende der Hilfe'),
                                  ('es', 'Fin de la ayuda'), ('pl', 'Koniec pomocy')]:
            for token in range(370, 378):
                text = yac._read_label(ROOT, language, f'l{token}', '')
                self.assertTrue(text)
                self.assertLessEqual(len(text.replace('{value}', '').strip()), 15)
            help_text = (ROOT/'lang'/language/'help/h035').read_text(encoding='utf-8')
            self.assertTrue(help_text.rstrip().endswith('***\n' + ending + '\n***'))

    def test_interrupt_restores_and_stops_before_speaking(self):
        rig = CarrierCat()
        rig.interrupt = True
        before = dict(rig.state)
        self.assertEqual(self.measure_cat(rig), 'Aborted')
        self.assertEqual(rig.state, before)
        self.assertIn('TX0;', rig.commands)

    def test_rx_failure_does_not_restore_high_power_and_remains_retryable(self):
        rig = CarrierCat()
        rig.stop_fail = True
        before = dict(rig.state)
        with self.assertLogs('yac', level='ERROR'):
            self.assertEqual(self.measure_cat(rig), 'RX unconfirmed')
        self.assertEqual(rig.state['PC'], '005')
        self.assertIsNotNone(rig.radio._swr_pending)
        rig.stop_fail = False
        with patch.object(yac, '_cat_exchange', side_effect=rig.exchange):
            self.assertIsNone(swr.recover(rig.radio))
        self.assertEqual(rig.state, before)

    def test_failed_mode_restoration_remains_pending_and_can_be_retried(self):
        rig = CarrierCat()
        rig.restore_fail = True
        before = dict(rig.state)
        with self.assertLogs('yac', level='ERROR'):
            self.assertEqual(self.measure_cat(rig), 'Restore failed')
        self.assertEqual(rig.state['TX'], '0')
        self.assertIsNotNone(rig.radio._swr_pending)
        rig.restore_fail = False
        with patch.object(yac, '_cat_exchange', side_effect=rig.exchange):
            self.assertIsNone(swr.recover(rig.radio))
        self.assertEqual(rig.state, before)

    def test_failed_tx_readback_still_requests_rx(self):
        rig = CarrierCat()
        rig.apply_but_reject_start = True
        with self.assertLogs('yac', level='ERROR'):
            self.assertEqual(self.measure_cat(rig), 'RX unconfirmed')
        self.assertEqual(rig.commands.count('TX0;'), 2)
        self.assertEqual(rig.state['TX'], '0')
        # No confirmed RX means no restoration to a higher configured power.
        self.assertEqual(rig.state['PC'], '005')

    def test_rejected_preparation_never_keys_and_restores_previous_changes(self):
        rig = CarrierCat()
        rig.reject = 'PC005;'
        before = dict(rig.state)
        with self.assertLogs('yac', level='ERROR'):
            self.assertEqual(self.measure_cat(rig), 'SWR unavailable')
        self.assertEqual(rig.state, before)
        self.assertNotIn('TX1;', rig.commands)

    def test_deadline_does_not_extend_rf_to_chase_more_samples(self):
        rig = CarrierCat()
        before = dict(rig.state)
        clock = Clock()
        sample = swr_radio.Radio.sample
        def slow_sample(backend):
            value = sample(backend)
            clock.now += 1.0
            return value
        with patch.object(yac, '_cat_exchange', side_effect=rig.exchange), \
             patch.object(swr_radio.Radio, 'sample', slow_sample), redirect_stdout(io.StringIO()):
            self.assertEqual(swr.measure(yac, ROOT, rig.radio, 'en', clock=clock.time, sleep=clock.sleep),
                             'SWR unavailable')
        self.assertEqual(rig.commands.count('RM6;'), 1)
        self.assertEqual(rig.state, before)

    def test_keyboard_routes_g_help_and_q_back_without_transmitting(self):
        from modules import lang_sel
        from modules.dummy_radio import create_dummy_radio
        radio = create_dummy_radio()
        keys = iter(['g', 'h', 'q', 'q', 'y'])
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call': 'Test', 'lang': 'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), \
             patch.object(swr, 'measure') as measure, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(yac.main([]), 0)
        self.assertIn('Get SWR', out.getvalue())
        self.assertIn('Connect an antenna', out.getvalue())
        measure.assert_not_called()

    def test_entry_help_and_q_do_not_transmit(self):
        rig = CarrierCat()
        keys = iter(['h', 'q'])
        with patch.object(yac, '_cat_exchange', side_effect=rig.exchange), redirect_stdout(io.StringIO()) as out:
            swr.control(yac, ROOT, rig.radio, 'en', lambda: next(keys))
        self.assertEqual(rig.commands, [])
        self.assertIn('Connect an antenna', out.getvalue())

    def test_conversion_endpoints_and_manufacturer_590_bins(self):
        import json
        curve = json.loads((ROOT/'rad_cmds/yaesu/CAT/models/0761/swr.json').read_text())
        self.assertEqual(swr_radio.calibration(curve, 52), (1.5, False))
        self.assertEqual(swr_radio.calibration(curve, 255), (25, True))
        bins = json.loads((ROOT/'rad_cmds/kenwood/CAT/models/023/swr.json').read_text())
        for raw, value, over in [(1,1,False), (2,1.5,False), (7,2,False), (12,3,False),
                                  (17,5,False), (24,5,False), (25,5,True)]:
            self.assertEqual(swr_radio.calibration(bins, raw), (value, over))
