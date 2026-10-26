"""INI failures are brief, non-destructive and occur before radio discovery."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import ini_settings, lang_sel, name_call_sel

ROOT=Path(__file__).resolve().parents[1]


class IniTests(unittest.TestCase):
    def test_missing_file_and_optional_values_are_normal(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'yac.ini'
            self.assertEqual(yac._read_settings(path),{})
            path.write_text('[yac]\nlang=\ncall=\n')
            self.assertEqual(yac._read_settings(path),{'lang':'','call':''})

    def test_invalid_files_exit_without_changes_or_discovery(self):
        cases=[b'broken',b'[yac]\nlang=en\nlang=de\n',b'[other]\ncall=Gena\n',
               b'[yac]\nlang=zz\n',b'[yac]\nlang=en\ncall=12345678901\n',
               b'[yac]\nplatform=garbage\n',b'[yac]\nlang=en\ncall=\xff\n']
        for data in cases:
            with self.subTest(data=data),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);path=root/'yac.ini';path.write_bytes(data)
                with patch.object(yac,'project_root',return_value=root),patch.object(yac,'find_radios') as discover,redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(yac.main([]),1)
                self.assertEqual(output.getvalue(),'INI Error\n')
                self.assertEqual(path.read_bytes(),data)
                discover.assert_not_called()

    def test_error_uses_valid_saved_language(self):
        for language in ('en','de','es','pl'):
            with self.subTest(language=language),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);path=root/'yac.ini'
                path.write_text(f'[yac]\nlang={language}\ncall=12345678901\n')
                labels=root/'lang'/language/'labels';labels.mkdir(parents=True)
                text=(ROOT/'lang'/language/'labels/l025').read_text(encoding='utf-8')
                (labels/'l025').write_text(text,encoding='utf-8')
                with patch.object(yac,'project_root',return_value=root),redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(yac.main([]),1)
                self.assertEqual(output.getvalue().strip(),text.strip())

    def test_save_failures_are_ini_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'yac.ini';original='[yac]\nlang=es\ncall=Gena\n'
            path.write_text(original)
            for module,writer,operation in [
                (yac,'_write_yac_value',lambda:yac._set_yac_value(path,'platform','linux')),
                (lang_sel,'_write_language',lambda:lang_sel.set_language(path,'en')),
                (name_call_sel,'_write_call',lambda:name_call_sel._save_call(path,'M0EBP')),
            ]:
                with self.subTest(writer=writer),patch.object(module,writer,side_effect=PermissionError('test')):
                    with self.assertRaises(ini_settings.IniError) as error:operation()
                    self.assertEqual(error.exception.language,'es')
                    self.assertEqual(path.read_text(),original)

    def test_platform_migration_remains_normal_and_silent(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'yac.ini'
            path.write_text('[yac]\nplatform=windows\nlang=en\ncall=Gena\n')
            with patch.object(yac,'detect_platform',return_value='linux'),patch.object(yac,'find_radios',return_value=[]),redirect_stdout(io.StringIO()) as output:
                radio=yac.connect_radio(path)
            self.assertTrue(radio.is_dummy)
            self.assertEqual(yac._read_settings(path)['platform'],'linux')
            self.assertNotIn('INI Error',output.getvalue())
            self.assertNotIn('Correct',output.getvalue())
