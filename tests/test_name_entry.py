"""Name/callsign help, review and Y/N confirmation without hardware."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from modules import help_int, lang_sel, name_call_sel as names

ROOT=Path(__file__).resolve().parents[1]


class NameEntryTests(unittest.TestCase):
    def test_locator_is_saved_only_after_confirming_the_revised_entry(self):
        ini = ROOT / 'yac.ini'
        save = Mock()
        keys = iter(['y', 'h', 'n', 'y'])

        def read_key():
            save.assert_not_called()
            return next(keys)

        with patch.object(names, '_edit_line', side_effect=['io83', 'io83ps']) as edit, \
             patch.object(lang_sel, 'read_key', side_effect=read_key), redirect_stdout(io.StringIO()) as output:
            names.collect_locator(ROOT, ini, 'en', '', save)

        self.assertEqual([call.args[0] for call in edit.call_args_list], ['', 'IO83'])
        self.assertIn('Locator = IO83\nContinue Y/N?', output.getvalue())
        self.assertIn('Locator = IO83PS\nContinue Y/N?', output.getvalue())
        save.assert_called_once_with(ini, 'ft_grid', 'IO83PS')

    def test_language_selection_uses_shared_confirmation_and_y(self):
        for number,language in enumerate(lang_sel.LANGUAGE_CODES,1):
            with self.subTest(language=language),patch.object(lang_sel,'read_key',side_effect=[str(number),' ','Y']),redirect_stdout(io.StringIO()) as output:
                self.assertEqual(lang_sel.show_language_menu(ROOT),language)
                self.assertIn(names._read_label(ROOT,language,'l007',''),output.getvalue())

    def test_selected_language_help_and_y_confirm(self):
        for language in ('en','de','es','pl'):
            with self.subTest(language=language),patch.object(names,'_edit_line',return_value='Gena') as edit, \
                 patch.object(lang_sel,'read_key',return_value='Y'),patch.object(names,'_save_call') as save, \
                 patch.object(names.os,'system'),redirect_stdout(io.StringIO()) as output:
                self.assertEqual(names.collect_name(ROOT,ROOT/'yac.ini',language),'Gena')
                save.assert_called_once_with(ROOT/'yac.ini','Gena')
                edit.assert_called_once_with('')
                text=output.getvalue()
                self.assertTrue(text.startswith(names._read_label(ROOT,language,'l004','') + '\n'))
                self.assertNotIn(help_int.get_help(ROOT,language,'h028'),text)
                for token in ('l004','l006','l007'):
                    label=names._read_label(ROOT,language,token,'')
                    self.assertLessEqual(len(label),15)
                    self.assertIn(label,text)
                self.assertIn(names._read_label(ROOT,language,'l006','')+' Gena',text)

    def test_n_preserves_text_and_saves_only_revised_entry(self):
        with patch.object(names,'_edit_line',side_effect=['Gena','M0EBP']) as edit, \
             patch.object(lang_sel,'read_key',side_effect=['n','y']), \
             patch.object(names,'_save_call') as save,patch.object(names.os,'system'), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(names.collect_name(ROOT,ROOT/'yac.ini','en',initial='Old'),'M0EBP')
        self.assertEqual([c.args[0] for c in edit.call_args_list],['Old','Gena'])
        save.assert_called_once_with(ROOT/'yac.ini','M0EBP')

    def test_space_and_e_do_not_confirm_or_edit_and_h_returns(self):
        with patch.object(names,'_edit_line',return_value='Gena') as edit, \
             patch.object(lang_sel,'read_key',side_effect=[' ','e','h','y']), \
             patch.object(names,'_save_call') as save,patch.object(names.os,'system'), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(names.collect_name(ROOT,ROOT/'yac.ini','en'),'Gena')
        edit.assert_called_once_with('')
        save.assert_called_once_with(ROOT/'yac.ini','Gena')
        self.assertEqual(output.getvalue().splitlines().count('Continue Y/N?'),2)
        self.assertIn(help_int.get_help(ROOT,'en','h028'),output.getvalue())
