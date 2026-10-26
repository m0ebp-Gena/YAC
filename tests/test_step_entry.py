"""Rejected and cancelled step requests remain in Settings without saving."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import yac
from modules import lang_sel
from modules.dummy_radio import create_dummy_radio


class StepEntryTests(unittest.TestCase):
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
