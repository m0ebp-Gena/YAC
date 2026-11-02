"""CW controls preserve entry state and verify explicit native changes."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import cw_control as cw
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection

ROOT = Path(__file__).resolve().parents[1]


class CWTests(unittest.TestCase):
    def run_adjustment(self, radio, name, keys, language='en', watch=None):
        output = io.StringIO()
        with redirect_stdout(output):
            pending = cw.adjustment(yac, ROOT, radio, language, name,
                                    iter(keys).__next__, watch or SimpleNamespace(lost=False))
        return output.getvalue(), pending

    def test_entry_and_exit_only_read_each_setting_in_every_state(self):
        for name, states in [('internal_keyer', ('0', '1')), ('break_in', ('0', '1'))]:
            for state in states:
                radio = create_dummy_radio()
                command = 'KR' if name == 'internal_keyer' else 'BI'
                radio.serial.cw[command] = state
                radio.serial.cw['EX020113'] = '1'
                before = dict(radio.serial.cw)
                with patch.object(yac, '_cat_exchange', wraps=yac._cat_exchange) as exchange:
                    output, _ = self.run_adjustment(radio, name, ['q'])
                self.assertEqual(radio.serial.cw, before)
                commands = [call.args[1] for call in exchange.call_args_list]
                expected = [command + ';']
                if name == 'break_in' and state == '1':
                    expected.append('EX020113;')
                self.assertEqual(commands, expected)
                self.assertIn('Done', output)

    def test_internal_keyer_toggle_navigation_and_reopen_all_languages(self):
        for language in ('en', 'de', 'es', 'pl'):
            radio = create_dummy_radio()
            output, _ = self.run_adjustment(radio, 'internal_keyer', ['i', 'q'], language)
            self.assertEqual(radio.serial.cw['KR'], '1')
            title = yac._read_label(ROOT, language, 'l414', '')
            self.assertIn(title.format(state=yac._read_label(ROOT, language, 'l416', '')), output)
            self.run_adjustment(radio, 'internal_keyer', ['q'], language)
            self.assertEqual(radio.serial.cw['KR'], '1')
            self.run_adjustment(radio, 'internal_keyer', ['.', ',', 'i', 'q'], language)
            self.assertEqual(radio.serial.cw['KR'], '0')

    def test_all_yaesu_break_in_models_exact_menu_and_order(self):
        for model, menu in [('0761', 'EX020113'), ('0800', 'EX020116'), ('0840', 'EX020115')]:
            state = {'BI': '0', menu: '1', 'KR': '0'}
            commands = []
            def exchange(radio, command):
                commands.append(command)
                for prefix in state:
                    if command == prefix + ';':
                        return prefix + state[prefix] + ';'
                    if command in (prefix + '0;', prefix + '1;'):
                        state[prefix] = command[-2]
                        return ''
                self.fail(command)
            radio = RadioConnection(None, 'test', 38400, 'CAT', model, model)
            with patch.object(yac, '_cat_exchange', side_effect=exchange):
                output, _ = self.run_adjustment(radio, 'break_in', ['b', '.', ',', 'q'])
            self.assertIn('Break-in Semi', output)
            self.assertIn('Break-in Full', output)
            self.assertEqual(state['BI'], '1')
            self.assertEqual(state[menu], '0')
            writes = [c for c in commands if c not in [p + ';' for p in state]]
            self.assertEqual(writes, [menu + '0;', 'BI1;', menu + '1;', menu + '0;'])

    def test_break_in_wrap_off_preserves_type_and_other_settings(self):
        radio = create_dummy_radio()
        radio.serial.cw.update(BI='1', EX020113='1', KR='1')
        self.run_adjustment(radio, 'break_in', ['b', 'q'])
        self.assertEqual(radio.serial.cw, {'BI': '0', 'KR': '1', 'EX020113': '1'})
        self.run_adjustment(radio, 'break_in', [',', 'q'])
        self.assertEqual(radio.serial.cw, {'BI': '1', 'KR': '1', 'EX020113': '1'})

    def test_keyer_rereads_front_panel_before_toggle(self):
        radio = create_dummy_radio()
        def keys():
            radio.serial.cw['KR'] = '1'
            yield 'i'
            yield 'q'
        self.run_adjustment(radio, 'internal_keyer', keys())
        self.assertEqual(radio.serial.cw['KR'], '0')

    def test_bad_entry_does_not_write_or_invent_off(self):
        radio = create_dummy_radio()
        for response in ('', '?;', 'KR2;', 'KR1;KR0;'):
            with patch.object(yac, '_cat_exchange', return_value=response) as exchange:
                output, _ = self.run_adjustment(radio, 'internal_keyer', [])
            self.assertNotIn('Int Key Off', output)
            self.assertEqual([c.args[1] for c in exchange.call_args_list], ['KR;'])

    def test_failed_change_is_not_announced_as_success(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_cat_exchange', side_effect=['KR0;', 'KR0;', '', 'KR0;']):
            output, _ = self.run_adjustment(radio, 'internal_keyer', ['i', 'q'])
        self.assertNotIn('Int Key On', output)

    def test_failed_type_change_never_enables_break_in(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_cat_exchange', side_effect=['BI0;', 'BI0;', 'EX0201131;', '', 'EX0201131;']) as exchange:
            self.run_adjustment(radio, 'break_in', ['b', 'q'])
        self.assertNotIn('BI1;', [c.args[1] for c in exchange.call_args_list])

    def test_civ_native_states_ack_and_readback(self):
        for model, address in [('IC-705', 0xa4), ('IC-7300', 0x94), ('IC-7300MK2', 0xb6),
                               ('IC-7600', 0x7a), ('IC-9700', 0xa2)]:
            radio = RadioConnection(None, 'test', 115200, 'CI-V', model, model, civ_address=address)
            state = [0]
            writes = []
            def read(radio, command, sub):
                self.assertEqual((command, sub), (0x16, 0x47))
                return bytes([254, 254, 224, address, command, sub, state[0], 253])
            def send(radio, command, data):
                self.assertEqual((command, data[0]), (0x16, 0x47))
                writes.append(data[1])
                state[0] = data[1]
                return bytes([254, 254, 224, address, 251, 253])
            with patch.object(yac, '_civ_exchange', side_effect=read), patch.object(yac, '_civ_send', side_effect=send):
                self.run_adjustment(radio, 'break_in', ['q'])
                self.assertEqual(writes, [])
                output, _ = self.run_adjustment(radio, 'break_in', ['b', '.', '.', ',', 'q'])
            self.assertEqual(writes, [1, 2, 0, 2])
            self.assertEqual(state[0], 2)
            self.assertIn('Break-in Full', output)

    def test_unsupported_keyer_sends_nothing(self):
        radio = RadioConnection(None, 'test', 115200, 'CI-V', 'IC-705', 'IC-705', civ_address=0xa4)
        with patch.object(yac, '_civ_exchange') as read, patch.object(yac, '_civ_send') as send:
            output, _ = self.run_adjustment(radio, 'internal_keyer', [])
        self.assertIn('Not Supported', output)
        read.assert_not_called()
        send.assert_not_called()

    def test_help_and_q_preserve_state_and_return_to_cw(self):
        radio = create_dummy_radio()
        keys = iter(['i', 'h', 'i', 'q', 'b', 'h', 'q', 'q'])
        with redirect_stdout(io.StringIO()) as output:
            cw.control(yac, ROOT, radio, 'en', keys.__next__, SimpleNamespace(lost=False))
        self.assertEqual(sum(line.strip() == 'Done' for line in output.getvalue().splitlines()), 2)
        self.assertIn('Top Level', output.getvalue())
        self.assertEqual(radio.serial.cw['KR'], '1')
        self.assertEqual(radio.serial.cw['BI'], '0')

    def test_disconnect_does_not_apply_queued_toggle(self):
        radio = create_dummy_radio()
        output, pending = self.run_adjustment(radio, 'internal_keyer', ['i'], watch=SimpleNamespace(lost=True))
        self.assertEqual(pending, 'i')
        self.assertEqual(radio.serial.cw['KR'], '0')

    def test_main_c_i_reaches_control_and_q_keeps_selection(self):
        radio = create_dummy_radio()
        keys = iter(['c', 'i', 'i', 'q', 'q', 'q', 'y'])
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call': 'test', 'lang': 'en'}), \
             patch.object(yac.lang_sel, 'read_key', side_effect=keys.__next__), \
             patch.object(yac.time, 'sleep'), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(yac.main([]), 0)
        self.assertIn('Int Key Off', output.getvalue())
        self.assertIn('Int Key On', output.getvalue())
        self.assertEqual(radio.serial.cw['KR'], '1')

    def test_translated_resources_generic_help_and_label_limits(self):
        for language, ending in [('en', 'End of help'), ('de', 'Ende der Hilfe'), ('es', 'Fin de la ayuda'), ('pl', 'Koniec pomocy')]:
            for number in range(412, 419):
                text = (ROOT / f'lang/{language}/labels/l{number}').read_text(encoding='utf-8').strip()
                self.assertLessEqual(len(text.replace('{state}', '')), 15)
            for number in range(42, 45):
                text = (ROOT / f'lang/{language}/help/h{number:03}').read_text(encoding='utf-8').strip()
                self.assertTrue(text.endswith('***\n' + ending + '\n***'))
                for model in ('Yaesu', 'Icom', 'Kenwood', 'FTX', 'IC-705'):
                    self.assertNotIn(model, text)


if __name__ == '__main__':
    unittest.main()
