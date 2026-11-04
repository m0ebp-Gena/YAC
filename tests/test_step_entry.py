"""Rejected and cancelled step requests remain in Settings without saving."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import yac
from modules import lang_sel
from modules.dummy_radio import create_dummy_radio


class StepEntryTests(unittest.TestCase):
    def test_prompt_reads_saved_mode_step_and_updates_after_edit(self):
        for language in ('en', 'de', 'es', 'pl'):
            radio = create_dummy_radio()
            keys = iter(['s', 's', 's', 'q', 'q', 'y'])
            settings = {'call':'test', 'lang':language, 'step_ssb':'1250'}
            output = io.StringIO()
            with self.subTest(language=language), \
                 patch.object(yac, 'connect_radio', return_value=radio), \
                 patch.object(yac, '_read_settings', return_value=settings), \
                 patch.object(yac, '_current_mode', return_value='USB'), \
                 patch.object(yac.time, 'sleep'), \
                 patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), \
                 patch('builtins.input', side_effect=['1500','']), \
                 patch.object(yac, '_set_yac_value') as save, redirect_stdout(output):
                self.assertEqual(yac.main([]), 0)
            self.assertIn('SSB 1250 Hz?', output.getvalue())
            self.assertIn('SSB 1500 Hz?', output.getvalue())
            save.assert_called_once_with(yac.project_root()/'yac.ini', 'step_ssb', '1500')

    def test_cancel_and_invalid_return_to_settings_in_all_languages(self):
        for language, aborted, invalid in [
            ('en', 'Aborted', 'Invalid'), ('de', 'Abgebrochen', 'Ungültig'),
            ('es', 'Cancelado', 'Inválido'), ('pl', 'Anulowano', 'Nieprawidłowe'),
        ]:
            for value in ('', ' ', 'text', '0', '-1', '3.5'):
                with self.subTest(language=language, value=value):
                    radio = create_dummy_radio()
                    # a must still be handled by Settings after the rejected entry.
                    keys = iter(['s', 's', 'a', 'q', 'q', 'y'])
                    output = io.StringIO()
                    with patch.object(yac, 'connect_radio', return_value=radio), \
                         patch.object(yac, '_read_settings', return_value={'call': 'test', 'lang': language}), \
                         patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), \
                         patch('builtins.input', return_value=value) as entered, \
                         patch.object(yac, '_set_yac_value') as save, \
                         patch.object(yac.agc_control, 'cycle', return_value='AGC checked') as agc, \
                         redirect_stdout(output):
                        self.assertEqual(yac.main([]), 0)
                    self.assertIn(aborted if not value.strip() else invalid, output.getvalue())
                    self.assertIn('AGC checked', output.getvalue())
                    self.assertEqual(entered.call_count, 1)
                    agc.assert_called_once()
                    save.assert_not_called()

    def test_help_returns_to_entry_then_save_cancel_or_invalid_in_each_mode(self):
        from modules import step_control, help_int
        root = yac.project_root()
        for language in ('en', 'de', 'es', 'pl'):
            for mode, setting in [('USB', 'step_ssb'), ('CW', 'step_cw'),
                                  ('AM', 'step_am'), ('FM', 'step_fm'),
                                  ('C4FMDN', 'step_fm'), ('DV', 'step_fm')]:
                for value in ('250', '', 'q', 'Q', '0', 'text'):
                    with self.subTest(language=language, mode=mode, value=value):
                        settings = {setting: '1500', 'step_other': '99'}
                        radio = create_dummy_radio()
                        output = io.StringIO()
                        with patch.object(yac, '_current_mode', return_value=mode), \
                             patch.object(yac, '_set_yac_value') as save, \
                             patch.object(yac, '_cat_exchange') as cat, \
                             patch('builtins.input', side_effect=['h', ' H ', value]) as entered, \
                             redirect_stdout(output):
                            step_control.control(yac, root, radio, language, settings)
                        self.assertEqual(entered.call_count, 3)
                        self.assertEqual(output.getvalue().count(
                            help_int.get_help(root, language, 'h067')), 2)
                        cat.assert_not_called()
                        self.assertEqual(settings['step_other'], '99')
                        if value == '250':
                            save.assert_called_once_with(root/'yac.ini', setting, '250')
                            self.assertEqual(settings[setting], '250')
                        else:
                            save.assert_not_called()
                            self.assertEqual(settings[setting], '1500')

    def test_help_and_q_cancel_keep_settings_menu_active(self):
        from modules import help_int
        for language in ('en', 'de', 'es', 'pl'):
            radio = create_dummy_radio()
            keys = iter(['s', 's', 'i', 'q', 'q', 'y'])
            output = io.StringIO()
            with patch.object(yac, 'connect_radio', return_value=radio), \
                 patch.object(yac, '_read_settings', return_value={'call':'test', 'lang':language}), \
                 patch.object(yac.time, 'sleep'), \
                 patch.object(lang_sel, 'read_key', side_effect=keys.__next__), \
                 patch('builtins.input', side_effect=['h', 'q']), \
                 patch.object(yac, '_set_yac_value') as save, \
                 patch('modules.radio_info.control') as info, redirect_stdout(output):
                self.assertEqual(yac.main([]), 0)
            save.assert_not_called()
            info.assert_called_once()
            self.assertIn(help_int.get_help(yac.project_root(), language, 'h067'), output.getvalue())

    def test_help_lists_actual_defaults_in_all_languages(self):
        from modules import help_int
        for language in ('en', 'de', 'es', 'pl'):
            text = help_int.get_help(yac.project_root(), language, 'h067')
            for value in yac.STEP_SIZE_DEFAULTS.values():
                self.assertIn(f'{value} Hz', text)
            self.assertTrue(text.endswith('***'))
