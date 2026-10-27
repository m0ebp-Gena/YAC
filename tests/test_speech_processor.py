"""Only processor writes, live paired levels, native undo and interruption."""
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import redirect_stdout
import yac
from modules import speech_processor as proc, lang_sel
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
from tests.test_verify_settings import SettingsSerial

ROOT = Path(__file__).resolve().parents[1]


class ProcessorTests(unittest.TestCase):
    def run_control(self, keys, radio=None):
        radio = radio or create_dummy_radio()
        keys = iter(keys)
        output = io.StringIO()
        with redirect_stdout(output):
            proc.control(yac, ROOT, radio, 'en', lambda **kwargs: next(keys), SimpleNamespace(lost=False))
        return radio, output.getvalue()

    def test_entry_and_cancel_are_read_only(self):
        radio = create_dummy_radio()
        original = yac._cat_exchange
        commands = []
        def exchange(radio, command):
            commands.append(command)
            return original(radio, command)
        with patch.object(yac, '_cat_exchange', side_effect=exchange):
            _, output = self.run_control(['n'], radio)
        self.assertTrue(all(c in {'MD0;', 'FA;', 'PR0;', 'PL;', 'TX;'} for c in commands), commands)
        self.assertIn('Restored', output.splitlines())
        self.assertFalse(radio.serial.processor_on)

    def test_q_keeps_only_processor_changes(self):
        radio, output = self.run_control(['e', '.', 'q'])
        self.assertTrue(radio.serial.processor_on)
        self.assertEqual(radio.serial.processor_level, 26)
        self.assertEqual(radio.serial.mic_gain, 50)
        self.assertEqual(radio.serial.power, '020')
        self.assertEqual(radio.serial.frequency, 7159000)
        self.assertEqual(radio.serial.mode, '1')
        self.assertIn('Done', output.splitlines())
        self.assertIsNone(radio._processor_pending)

    def test_n_restores_onoff_and_level(self):
        radio, output = self.run_control(['e', '.', '.', 'n'])
        self.assertFalse(radio.serial.processor_on)
        self.assertEqual(radio.serial.processor_level, 25)
        self.assertIn('Restored', output.splitlines())

    def test_navigation_while_off_changes_nothing(self):
        radio, _ = self.run_control(['.', ',', 'q'])
        self.assertFalse(radio.serial.processor_on)
        self.assertEqual(radio.serial.processor_level, 25)

    def test_hidden_off_level_is_revealed_and_restored_without_radio_controls(self):
        for model in ('0761', '0800', '0840'):
            radio = create_dummy_radio()
            radio.model_id = model
            original_exchange = yac._cat_exchange
            commands = []
            def exchange(radio, command):
                commands.append(command)
                if command == 'PL;' and not radio.serial.processor_on:
                    return 'PL000;'
                return original_exchange(radio, command)
            with patch.object(yac, '_cat_exchange', side_effect=exchange):
                _, output = self.run_control(['e', '.', 'n'], radio)
            self.assertFalse(radio.serial.processor_on)
            self.assertEqual(radio.serial.processor_level, 25)
            self.assertIn('PR02;', commands)
            self.assertIn('Restored', output.splitlines())

    def test_failed_hidden_level_probe_restores_off(self):
        radio = create_dummy_radio()
        spec = proc.profile(yac, radio)
        state = [False]
        def status(yac, radio, spec, enabled):
            state[0] = enabled
            return True
        with patch.object(proc, 'context', return_value=('USB', '14.2', 0)), patch.object(proc.mic_gain, 'tx_state', return_value=False), patch.object(proc, 'set_status', side_effect=status), patch.object(proc, 'read', side_effect=lambda *args: None if state[0] else (False, (0,))):
            self.assertIsNone(proc.reveal_level(yac, ROOT, radio, spec, (False, (0,)), ('USB', '14.2', 0)))
        self.assertFalse(state[0])
        self.assertIsNone(radio._processor_pending)

    def test_icom_undo_preserves_exact_bcd_not_rounded_display(self):
        serial = SettingsSerial(0xa4)
        serial.settings[b'\x16\x44'] = b'\x01'
        serial.settings[b'\x14\x0e'] = bytes.fromhex('01 13')
        serial.settings[b'\x1c\x00'] = b'\x00'
        radio = RadioConnection(serial, 'test', 115200, 'CI-V', 'IC-705', 'IC-705', civ_address=0xa4)
        with patch.object(yac, '_current_mode', return_value='USB'), patch.object(yac, '_current_frequency', return_value='14.200000'):
            self.run_control(['.', 'n'], radio)
        self.assertEqual(serial.settings[b'\x14\x0e'], bytes.fromhex('01 13'))
        self.assertEqual(serial.settings[b'\x16\x44'], b'\x01')

    def test_kenwood_output_preserves_live_input_and_cancel_restores_both(self):
        radio = RadioConnection(None, 'test', 9600, 'CAT', '023', 'TS-590SG')
        state = {'on': '1', 'levels': '020030'}
        writes = []
        def exchange(radio, command):
            if command == 'PR;': return 'PR' + state['on'] + ';'
            if command == 'PL;': return 'PL' + state['levels'] + ';'
            writes.append(command)
            if command.startswith('PL'): state['levels'] = command[2:-1]
            if command.startswith('PR'): state['on'] = command[2:-1]
            return ''
        with patch.object(yac, '_cat_exchange', side_effect=exchange), patch.object(proc, 'context', return_value=('USB', '14.2', 0)), patch.object(proc.mic_gain, 'tx_state', return_value=False):
            self.run_control(['o', '.', 'n'], radio)
        self.assertIn('PL020031;', writes)
        self.assertEqual(state['levels'], '020030')
        self.assertEqual(state['on'], '1')

    def test_failed_restore_retains_snapshot(self):
        radio = create_dummy_radio()
        with patch.object(proc, 'restore', return_value=False):
            keys = iter(['e', '.', 'n'])
            def read_key(**kwargs):
                try: return next(keys)
                except StopIteration: raise EOFError()
            with redirect_stdout(io.StringIO()) as output:
                proc.control(yac, ROOT, radio, 'en', read_key, SimpleNamespace(lost=False))
        self.assertIsNotNone(radio._processor_pending)
        self.assertIn('Restore Failed', output.getvalue().splitlines())

    def test_interrupt_restores(self):
        radio = create_dummy_radio()
        keys = iter(['e', '.'])
        def read_key(**kwargs):
            try: return next(keys)
            except StopIteration: raise KeyboardInterrupt()
        with redirect_stdout(io.StringIO()):
            proc.control(yac, ROOT, radio, 'en', read_key, SimpleNamespace(lost=False))
        self.assertFalse(radio.serial.processor_on)
        self.assertEqual(radio.serial.processor_level, 25)

    def test_restore_does_not_write_when_tx_or_context_differs(self):
        radio = create_dummy_radio()
        spec = proc.profile(yac, radio)
        for actual_context, tx in [(('USB', 'other', 0), False), (('USB', '14.2', 0), True)]:
            with patch.object(proc, 'context', return_value=actual_context), patch.object(proc.mic_gain, 'tx_state', return_value=tx), patch.object(proc, 'set_status') as write:
                self.assertFalse(proc.restore(yac, ROOT, radio, spec, (False, (25,)), ('USB', '14.2', 0)))
                write.assert_not_called()

    def test_qmx_and_unavailable_modes_do_not_write(self):
        radio = RadioConnection(None, 'test', 9600, 'CAT', '020', 'QMX')
        with patch.object(proc.mic_gain.ts480_control, 'variant', return_value=None):
            _, output = self.run_control([], radio)
        self.assertIn('Not Supported', output)
        radio = create_dummy_radio()
        radio.serial.mode = '4'
        _, output = self.run_control([], radio)
        self.assertIn('Not Supported', output)

    def test_kenwood_comp_meter_is_read_only(self):
        radio = RadioConnection(None, 'test', 9600, 'CAT', '023', 'TS-590SG')
        with patch.object(yac, '_cat_exchange', return_value='RM10001;RM20012;RM30015;') as exchange:
            self.assertEqual(proc.compression(yac, radio, proc.profile(yac, radio)), 12)
            exchange.assert_called_once_with(radio, 'RM;')

    def test_keyboard_routes_and_returns_to_settings(self):
        radio = create_dummy_radio()
        keys = iter(['s', 'e', 'e', '.', 'n', 'q', 'q', 'y'])
        with patch.object(yac, 'connect_radio', return_value=radio), patch.object(yac, '_read_settings', return_value={'call':'test','lang':'en'}), patch.object(lang_sel, 'read_key', side_effect=lambda **kwargs: next(keys)), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(yac.main([]), 0)
        self.assertEqual(output.getvalue().count('Done'), 1)
        self.assertEqual(output.getvalue().splitlines().count('Top Level'), 1)
        self.assertFalse(radio.serial.processor_on)

    def test_n_in_meter_preparation_cancels_control(self):
        radio, output = self.run_control(['e', '.', ' ', 'q', 'n'])
        self.assertFalse(radio.serial.processor_on)
        self.assertEqual(radio.serial.processor_level, 25)
        self.assertIn('Restored', output.splitlines())

    def test_partial_write_still_undoes_when_unconfirmed(self):
        radio = create_dummy_radio()
        original_write = proc.set_levels
        def uncertain(yac, radio, spec, levels):
            original_write(yac, radio, spec, levels)
            return False  # Acknowledgement lost, but the radio changed.
        with patch.object(proc, 'set_levels', side_effect=uncertain):
            keys = iter(['e', '.', 'n', 'q', 'y'])
            self.run_control(keys, radio)
        # Even the failed restore write is kept for retry, never claimed restored.
        self.assertEqual(radio.serial.processor_level, 25)

    def test_monitor_captures_comp_peak_with_manual_ptt(self):
        radio = create_dummy_radio()
        keys = iter([' ', 'y', 'q', 'y'])
        def read_key(idle_callback=None):
            if idle_callback:
                idle_callback()
                idle_callback()
                idle_callback()
            return next(keys)
        with patch.object(proc.mic_gain, 'tx_state', side_effect=[False, True, True, False]), patch.object(proc, 'compression', side_effect=[30, 48]), patch.object(proc, 'monotonic', side_effect=range(100)), redirect_stdout(io.StringIO()) as output:
            proc.control(yac, ROOT, radio, 'en', read_key, SimpleNamespace(lost=False))
        self.assertIn('Peak COMP 48 raw', output.getvalue())
        self.assertFalse(radio.serial.processor_on)

    def test_receive_state_blocks_toggle_without_dirty_snapshot(self):
        radio = create_dummy_radio()
        with patch.object(proc.mic_gain, 'tx_state', side_effect=[False, True]), patch.object(proc, 'set_status') as setter:
            _, output = self.run_control(['e', 'q'], radio)
        setter.assert_not_called()
        self.assertIn('Release PTT', output)
        self.assertFalse(radio.serial.processor_on)
