"""Context help follows live capabilities without changing the radio."""
import io
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import filter_control as filters, help_int
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection

ROOT = Path(__file__).resolve().parents[1]


class FilterHelpTests(unittest.TestCase):
    def test_each_control_and_contour_parameter_selects_its_own_topic(self):
        radio = create_dummy_radio()
        for key, parameter, topic in [(None, 'frequency', 'h007'),
                ('a', 'frequency', 'h054'), ('b', 'frequency', 'h055'),
                ('c', 'frequency', 'h056'), ('c', 'level', 'h065'),
                ('c', 'width', 'h066'), ('n', 'frequency', 'h058'),
                ('r', 'frequency', 'h059'), ('p', 'frequency', 'h031')]:
            with self.subTest(key=key, parameter=parameter), \
                 patch.object(filters.settings, '_write') as write:
                self.assertEqual(filters._help_topic(yac, ROOT, radio, key, parameter), topic)
                write.assert_not_called()

    def test_passband_edges_have_help_for_the_selected_edge(self):
        for key, expected in [('l', 'h057'), ('u', 'h060')]:
            with patch.object(filters, '_profile', return_value=({'low_read': 'SL;'}, None)):
                self.assertEqual(filters._help_topic(yac, ROOT, create_dummy_radio(), key), expected)

    def test_beat_cancel_and_time_follow_live_radio_context(self):
        radio = RadioConnection(None, 'test', 38400, 'CAT', '023', 'TS-590SG')
        for state, expected in [('1', 'h059'), ('2', 'h062'), ('0', 'h059'),
                                 (None, 'h063'), ('9', 'h063')]:
            with self.subTest(state=state), \
                 patch.object(yac, '_current_mode_code', return_value='2'), \
                 patch.object(filters.settings, 'read', return_value=state), \
                 patch.object(filters.settings, '_write') as write:
                self.assertEqual(filters._help_topic(yac, ROOT, radio, 'r'), expected)
                write.assert_not_called()
        radio._nr_memory = {(radio.radio_id_path, '0'): '2'}
        with patch.object(yac, '_current_mode_code', return_value='2'), \
             patch.object(filters.settings, 'read', return_value='0'):
            self.assertEqual(filters._help_topic(yac, ROOT, radio, 'r'), 'h062')
        feature = {'notch': {'a': {'modes': ['2'], 'beat_cancel': True}}}
        with patch.object(filters.settings, 'catalog', return_value=feature), \
             patch.object(yac, '_current_mode_code', return_value='2'):
            self.assertEqual(filters._help_topic(yac, ROOT, radio, 'a'), 'h061')

    def test_unsupported_and_unreadable_context_does_not_guess(self):
        radio = create_dummy_radio()
        with patch.object(filters.settings, 'catalog', return_value={}):
            for key in 'abcnrplu':
                self.assertEqual(filters._help_topic(yac, ROOT, radio, key), 'h064')
        with patch.object(yac, '_current_mode_code', return_value=None):
            for key in 'abcnrp':
                self.assertEqual(filters._help_topic(yac, ROOT, radio, key), 'h063')

    def test_h_returns_without_an_extra_key_or_setting_write(self):
        for language in ('en', 'de', 'es', 'pl'):
            keys = iter(['r', 'h', 'q', 'h', 'q'])
            with patch.object(filters.settings, '_write') as write, \
                 patch.object(filters.chat_int, 'show_response') as say:
                result = filters.control(yac, ROOT, create_dummy_radio(), language,
                                         'test', keys.__next__, SimpleNamespace(lost=False))
            self.assertIsNone(result)
            write.assert_not_called()
            messages = [call.args[0] for call in say.call_args_list]
            self.assertIn(help_int.get_help(ROOT, language, 'h059'), messages)
            self.assertIn(help_int.get_help(ROOT, language, 'h007'), messages)
            self.assertEqual(list(keys), [])

    def test_all_translations_are_short_complete_and_model_independent(self):
        ids = ['h031'] + [f'h{i:03d}' for i in range(54, 67)]
        for language in ('en', 'de', 'es', 'pl'):
            for topic in ids:
                with self.subTest(language=language, topic=topic):
                    text = help_int.get_help(ROOT, language, topic)
                    self.assertTrue(text.endswith('***'))
                    self.assertEqual(text.splitlines().count('***'), 2)
                    self.assertIn('q)', text)
                    self.assertLessEqual(sum(max(1, len(textwrap.wrap(line, 80)))
                                             for line in text.splitlines()), 20)
                    for model in ('Yaesu', 'Kenwood', 'Icom', 'TS-590', 'TS-480', 'FTX'):
                        self.assertNotIn(model, text)


if __name__ == '__main__':
    unittest.main()
