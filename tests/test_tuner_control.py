import unittest
from unittest.mock import patch

import yac
from modules import tuner_control, verify_settings
from tests.test_verify_settings import ROOT


class TunerTests(unittest.TestCase):
    def setUp(self):
        # These tests exercise the native cycle state machine. Region and TX
        # frequency protocol checks are covered by test_region_control.
        guard = patch('modules.region_plan.permits_transmission', return_value=True)
        guard.start()
        self.addCleanup(guard.stop)

    def test_icom_real_frame_and_rejection(self):
        from tests.test_verify_settings import SettingsSerial, RadioConnection
        serial = SettingsSerial(0x94)
        serial.settings[b'\x1c\x01'] = b'\x01'
        radio = RadioConnection(serial, 'test', 115200, 'CI-V',
                                'IC-7300', 'IC-7300', civ_address=0x94)
        def advance(_):
            if advance.busy:
                serial.settings[b'\x1c\x01'] = b'\x01'
            advance.busy = True
        advance.busy = False
        with patch('modules.tuner_control.time.sleep', side_effect=advance), patch('builtins.print'):
            self.assertEqual(yac._dispatch(ROOT, radio, 'en', 't', None), 'Tune Finished')
        self.assertIn(bytes.fromhex('FEFE94E01C0102FD'), serial.writes)
        serial.reject_setting = True
        self.assertEqual(yac._dispatch(ROOT, radio, 'en', 't', None), 'Tune Failed')

    def test_ts480_sat_tunes_hx_does_not(self):
        from tests.test_ts480 import TS480, TS480Tests
        for variant in ('0', '1'):
            emulator = TS480(variant)
            emulator.values['AC'] = '110'
            def advance(_):
                if emulator.values['AC'] == '111':
                    if advance.busy:
                        emulator.values['AC'] = '110'
                    advance.busy = True
            advance.busy = False
            with patch.object(yac, '_cat_exchange', side_effect=emulator.exchange), \
                 patch('modules.tuner_control.time.sleep', side_effect=advance), patch('builtins.print'):
                result = tuner_control.tune(yac, ROOT, TS480Tests().radio(), 'en')
            self.assertEqual(result, 'Tune Finished' if variant == '1' else 'Not Supported')
            self.assertEqual('AC111;' in emulator.commands, variant == '1')

    def run_cycle(self, path, states, selection=None, **options):
        from types import SimpleNamespace
        radio = SimpleNamespace(radio_id_path=path, protocol='CAT', model_id='test')
        spec = verify_settings.catalog(ROOT, radio)['tuner']
        def immediate_exchange(radio, command):
            self.assertEqual(command, 'AC002;AC;')
            verify_settings._write(yac, radio, spec, '002')
            value = verify_settings.read(yac, radio, spec)
            return 'AC' + value + ';' if value is not None else ''
        with patch.object(yac, '_cat_exchange', side_effect=immediate_exchange), \
             patch.object(verify_settings, 'read', side_effect=states), \
             patch.object(verify_settings, '_tuner_state', return_value=selection), \
             patch.object(verify_settings, '_write', return_value=True) as write, \
             patch('modules.tuner_control.time.sleep'), patch('builtins.print'):
            result = tuner_control.tune(yac, ROOT, radio, 'en', **options)
        return result, [call.args[3] for call in write.call_args_list]

    def test_all_profiles_use_native_start_and_observe_completion(self):
        profiles = [
            ('yaesu/CAT/models/0761', '001', '002', '002', '0'),
            ('yaesu/CAT/models/0800', '001', '002', '002', None),
            ('kenwood/CAT/models/023', '110', '111', '111', None),
        ]
        for model in ('ic-705', 'ic-7300', 'ic-7300mk2', 'ic-7600'):
            profiles.append((f'icom/CI-V/models/{model}', '01', '02', '02', None))
        for path, idle, busy, start, selected in profiles:
            with self.subTest(path=path, start=start):
                result, writes = self.run_cycle('rad_cmds/'+path, [idle, busy, idle], selected)
                self.assertEqual(result, 'Tune Finished')
                self.assertEqual(writes, [start])

    def test_yaesu_observes_busy_in_start_reply_before_sleeping(self):
        from types import SimpleNamespace
        radio = SimpleNamespace(radio_id_path='rad_cmds/yaesu/CAT/models/0761', protocol='CAT', model_id='0761')
        events = []
        def exchange(radio, command):
            events.append(command)
            return 'AC002;'
        with patch.object(verify_settings, 'read', side_effect=['001', '001']), \
             patch.object(verify_settings, '_tuner_state', return_value='0'), \
             patch.object(yac, '_cat_exchange', side_effect=exchange), \
             patch('modules.tuner_control.time.sleep', side_effect=lambda _: events.append('sleep')), \
             patch('builtins.print'):
            self.assertEqual(tuner_control.tune(yac, ROOT, radio, 'en'), 'Tune Finished')
        self.assertEqual(events, ['AC002;AC;', 'sleep'])
        radio.radio_id_path = 'rad_cmds/yaesu/CAT/models/0800'
        radio.model_id = '0800'
        events.clear()
        with patch.object(verify_settings, 'read', side_effect=['001', '001']), \
             patch.object(yac, '_cat_exchange', side_effect=exchange), \
             patch('modules.tuner_control.time.sleep', side_effect=lambda _: events.append('sleep')), \
             patch('builtins.print'):
            self.assertEqual(tuner_control.tune(yac, ROOT, radio, 'en'), 'Tune Finished')
        self.assertEqual(events, ['AC002;AC;', 'sleep'])

    def test_off_unknown_and_already_tuning_never_write(self):
        for state in ('000', None, '002'):
            _, writes = self.run_cycle('rad_cmds/yaesu/CAT/models/0761', [state])
            self.assertEqual(writes, [])

    def test_ignored_start_not_reported_as_completion(self):
        result, writes = self.run_cycle('rad_cmds/yaesu/CAT/models/0800', ['001']*7)
        self.assertEqual(result, 'Tune Unverified')
        self.assertEqual(writes, ['002'])

    def test_timeout_stops_without_restarting(self):
        result, writes = self.run_cycle('rad_cmds/yaesu/CAT/models/0800',
                                        ['001', '002', '002', '000'], polls=2)
        self.assertEqual(writes, ['002', '000'])
        self.assertIn('Tune Timed Out', result)

    def test_lost_connection_requests_stop_and_reports_unconfirmed(self):
        result, writes = self.run_cycle('rad_cmds/yaesu/CAT/models/0800',
                                        ['001', None, None])
        self.assertEqual(writes, ['002', '000'])
        self.assertEqual(result, 'Stop Unverified')

    def test_selector_reads_entry_and_stays_until_q(self):
        from modules.dummy_radio import create_dummy_radio
        from contextlib import redirect_stdout
        import io
        radio = create_dummy_radio()
        before = radio.serial.tuner
        keys = iter(['h','x','t','.','.',',','q','sentinel'])
        with redirect_stdout(io.StringIO()) as out:
            tuner_control.control(yac, ROOT, radio, 'en', lambda: next(keys))
        self.assertEqual(next(keys), 'sentinel')
        self.assertEqual(before, '000')
        self.assertEqual(radio.serial.tuner_selection, '0')
        self.assertEqual(radio.serial.tuner, '001')
        self.assertIn('Done', out.getvalue())
        self.assertNotIn('Top Level', out.getvalue())
