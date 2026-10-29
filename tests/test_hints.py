"""Startup factual hint is translated, brief and follows name selection."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import hints, name_call_sel

ROOT = Path(__file__).resolve().parents[1]


class HintTests(unittest.TestCase):
    def test_all_region_messages_fit_fifty_characters(self):
        for language in ('en', 'de', 'es', 'pl'):
            for region in (1, 2, 3):
                message = hints.get_hint(ROOT, language, 'm000', region=region)
                self.assertTrue(message)
                self.assertIn(str(region), message)
                self.assertNotIn('{', message)
                self.assertLessEqual(len(message), 50)
        self.assertEqual(hints.get_hint(ROOT, 'en', 'm000', region=2),
                         'Current region is set to 2.')

    def test_startup_order_existing_and_new_users_all_languages(self):
        for language in ('en', 'de', 'es', 'pl'):
            for saved_call, region in (('', None), ('Test', '2'), ('Test', '3')):
                with self.subTest(language=language, call=saved_call, region=region), \
                     tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'yac.ini'
                    content = f'[yac]\nlang={language}\ncall={saved_call}\nplatform=linux\n'
                    if region is not None:
                        content += f'region={region}\n'
                    path.write_text(content, encoding='utf-8')
                    output = io.StringIO()
                    def collect(*args):
                        print('NAME CONFIRMED')
                        name_call_sel._save_call(path, 'NewUser')
                    def discover(*args):
                        print('DISCOVERY')
                        return [object()]
                    with patch.object(yac, 'detect_platform', return_value='linux'), \
                         patch.object(yac.time, 'sleep'), \
                         patch.object(name_call_sel, 'collect_name', side_effect=collect) as prompt, \
                         patch.object(yac, 'find_radios', side_effect=discover), \
                         patch.object(yac, '_choose_radio', return_value='radio'), \
                         redirect_stdout(output):
                        self.assertEqual(yac.connect_radio(path), 'radio')
                    message = hints.get_hint(ROOT, language, 'm000', region=int(region or '1'))
                    text = output.getvalue()
                    self.assertEqual(text.count(message), 1)
                    search = yac._read_label(ROOT, language, 'l058', '')
                    self.assertLess(text.index(message), text.index(search))
                    self.assertLess(text.index(search), text.index('DISCOVERY'))
                    if not saved_call:
                        self.assertLess(text.index('NAME CONFIRMED'), text.index(message))
                    else:
                        prompt.assert_not_called()
                    self.assertEqual(yac._read_settings(path).get('region', '1'), region or '1')
                    if region is None:
                        self.assertNotIn('region', yac._read_settings(path))
