"""Every filter keeps q nested after entry, changes and failed reads."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import filter_control as filters
from modules.dummy_radio import create_dummy_radio

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ('en', 'de', 'es', 'pl')


class FilterNavigationTests(unittest.TestCase):
    def check_navigation(self, radio, language, entry, actions):
        # A second filter must open after the first q, without reopening f.
        keys = iter([entry, *actions, 'q', 'r', 'q', 'q'])
        with patch.object(filters.chat_int, 'show_done') as done, \
             patch.object(filters.chat_int, 'show_back') as back, \
             patch.object(filters.chat_int, 'show_response') as say, \
             patch.object(filters.settings, '_write', wraps=filters.settings._write) as write:
            last_key = None
            writes_before_key = 0
            count = 0
            def read_key():
                nonlocal last_key, writes_before_key, count
                if count == 1:
                    self.assertEqual(write.call_count, 0, 'Entry must not change settings')
                if last_key == 'q':
                    self.assertEqual(write.call_count, writes_before_key,
                                     'q must preserve settings')
                    back.assert_not_called()
                    self.assertEqual(done.call_count, 1 if count == len(actions) + 2 else 2)
                key = next(keys)
                last_key = key
                writes_before_key = write.call_count
                count += 1
                return key
            result = filters.control(yac, ROOT, radio, language, 'test',
                                     read_key, SimpleNamespace(lost=False))
            self.assertEqual(write.call_count, writes_before_key, 'Leaving Filters must preserve settings')
            self.assertIsNone(result, 'Filter key must not be forwarded to Top Level')
            self.assertEqual(count, len(actions) + 5)
            self.assertEqual(done.call_count, 2)
            back.assert_called_once_with(ROOT, language)
            self.assertGreaterEqual(say.call_count, 3)
            self.assertEqual(list(keys), [])

    def test_all_filters_entry_toggle_adjust_help_verify_and_nested_q(self):
        cases = {
            'a': ['a', '.', ',', 'h', 'v'],
            'b': ['b', '.', ',', 'b', '.', ',', 'h', 'v'],
            'r': ['r', '.', ',', 'r', '.', ',', 'h', 'v'],
            'n': ['n', '.', ',', 'w', 'n', '.', ',', 'h', 'v'],
            'c': ['c', '.', ',', 'l', '.', ',', 'w', '.', ',', 'c', 'c', 'h', 'v'],
            'p': ['.', ',', 'p', 'h', 'v'],
            'l': ['.', ',', 'h', 'v'],
            'u': ['.', ',', 'h', 'v'],
        }
        for language in LANGUAGES:
            for entry, actions in cases.items():
                with self.subTest(language=language, filter=entry):
                    self.check_navigation(create_dummy_radio(), language, entry, actions)

    def test_active_filters_finish_with_settings_kept(self):
        for language in LANGUAGES:
            for entry, field, state in [('a', 'auto_notch', '1'),
                                        ('b', 'noise_blanker', '1'),
                                        ('r', 'noise_reduction', '1'),
                                        ('n', 'manual_notch', '001'),
                                        ('c', 'contour', '0001')]:
                with self.subTest(language=language, filter=entry):
                    radio = create_dummy_radio()
                    if entry == 'c':
                        radio.serial.contour['CO00'] = state
                    else:
                        setattr(radio.serial, field, state)
                    self.check_navigation(radio, language, entry, ['.', ',', 'h', 'v'])

    def test_bandwidth_missing_or_unreadable_profile_keeps_navigation(self):
        for language in LANGUAGES:
            for actions in ([], ['.', ',', 'p']):
                with self.subTest(language=language, actions=actions, profile='absent'), \
                     patch.object(filters.settings, 'catalog', return_value={}):
                    self.check_navigation(create_dummy_radio(), language, 'p', actions)
                with self.subTest(language=language, actions=actions, profile='unreadable'), \
                     patch.object(yac, '_current_mode_code', return_value=None):
                    self.check_navigation(create_dummy_radio(), language, 'p', actions)

    def test_separate_bandwidth_edges_keep_q_nested(self):
        for language in LANGUAGES:
            with self.subTest(language=language), \
                 patch.object(filters, '_profile', return_value=({'low_read': 'SL;'}, None)), \
                 patch.object(filters, 'adjust', return_value='edge') as adjust:
                self.check_navigation(create_dummy_radio(), language, 'p', ['p', '.', 'p', ','])
                self.assertEqual([call.kwargs.get('key', call.args[5] if len(call.args) > 5 else None)
                                  for call in adjust.call_args_list], ['l', 'u', 'u', 'l', 'l'])

    def test_all_filters_unsupported_and_unreadable_still_need_q_to_finish(self):
        for language in LANGUAGES:
            for error in ('l129', 'l050'):
                response = yac._read_label(ROOT, language, error, '')
                for entry in ('a', 'b', 'r', 'n', 'c', 'p', 'l', 'u'):
                    with self.subTest(language=language, error=error, filter=entry), \
                         patch.object(filters.noise_blanker, 'operate', return_value=response), \
                         patch.object(filters.noise_reduction, 'operate', return_value=response), \
                         patch.object(filters.notch_control, 'operate', return_value=response), \
                         patch.object(filters.contour_control, 'operate', return_value=response), \
                         patch.object(filters.settings, 'catalog', return_value={'bandwidth': {'kind': 'test'}}), \
                         patch.object(filters, '_profile', return_value=(None, error)), \
                         patch.object(filters, 'adjust', return_value=response):
                        self.check_navigation(create_dummy_radio(), language, entry, ['.', ',', 'h'])


if __name__ == '__main__':
    unittest.main()
