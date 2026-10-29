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
