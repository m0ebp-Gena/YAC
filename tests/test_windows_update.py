import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import update_yac as updater
from modules import windows_update

POWERSHELL = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


def archive(extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as package:
        for name in ('YAC-001-beta.exe', 'yac.ini', 'LICENSE', '_internal/runtime.dll', 'lang/en/labels/l000'):
            package.writestr('YAC-test/' + name, 'new')
        if extra:
            package.writestr(*extra)
    return stream.getvalue()


def release():
    name = 'YAC-001-beta-2026-10-22.zip'
    prefix = 'https://github.com/m0ebp-Gena/YAC/releases/download/v-test/'
    return dict(tag_name='v-test', published_at='2026-10-22T12:00:00Z', draft=False,
                body='Test changes', assets=[dict(name=n, browser_download_url=prefix+n)
                                            for n in (name, name[:-4]+'.sha256')])


class WindowsUpdateTests(unittest.TestCase):
    def test_asset_pair_uses_windows_package_and_existing_checksum_name(self):
        pair = updater.asset_pair(release(), windows=True)
        self.assertEqual(pair[0]['name'], 'YAC-001-beta-2026-10-22.zip')
        self.assertEqual(pair[1]['name'], 'YAC-001-beta-2026-10-22.sha256')
        with self.assertRaises(ValueError):
            updater.asset_pair(release())

    def test_archive_validation_rejects_windows_aliases_and_personal_paths(self):
        for name in ('YAC-test/../outside', 'YAC-test/CON.txt', 'YAC-test/doc/file.',
                     'YAC-test/doc/file ', 'YAC-test/LANG/en/labels/l000', 'YAC-test/logs/private'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    windows_update.extract(archive((name, 'bad')), Path(folder))

    def test_valid_archive_extracts_one_program(self):
        with tempfile.TemporaryDirectory() as folder:
            source, program = windows_update.extract(archive(), Path(folder))
            self.assertEqual(program, 'YAC-001-beta.exe')
            self.assertTrue((source / 'lang/en/labels/l000').is_file())

    def test_windows_byte_lock_is_released_even_on_error(self):
        from modules import update_lock
        from types import SimpleNamespace
        calls = []
        fake = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=lambda fd, action, length: calls.append(action))
        with tempfile.TemporaryDirectory() as folder, patch.object(update_lock.sys, 'platform', 'win32'), \
             patch.dict('sys.modules', {'msvcrt': fake}):
            with self.assertRaises(ValueError):
                with update_lock.application_lock(Path(folder)):
                    raise ValueError('test')
        self.assertEqual(calls, [1, 2])

    def test_checksum_failure_never_launches_installer(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(windows_update.sys, 'platform', 'win32'), \
             patch.object(windows_update.sys, 'frozen', True, create=True), \
             patch.object(windows_update.sys.stdin, 'isatty', return_value=True), \
             patch.object(updater, 'read_key', return_value=' '), \
             patch.object(updater, 'fetch', side_effect=[json.dumps([release()]).encode(), archive(),
                         b'0'*64 + b'  YAC-001-beta-2026-10-22.zip']), \
             patch.object(windows_update.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(ValueError, 'checksum failed'):
                windows_update.run(Path(folder))
            launch.assert_not_called()

    @unittest.skipUnless(POWERSHELL.is_file(), 'Windows PowerShell required')
    def test_real_powershell_install_preserves_settings_and_removes_old_program(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / 'portable'
            root.mkdir()
            (root / 'yac.ini').write_text('personal settings')
            (root / 'personal.log').write_text('personal log')
            (root / 'YAC-old.exe').write_text('old executable')
            stage = base / 'stage'
            stage.mkdir()
            source, program = windows_update.extract(archive(), stage)
            script = ('function Read-Host { return "" }; function Start-Process { };\n' +
                      windows_update.installer_script(root, source, stage, program, 'YAC-old.exe', 2147483000))
            result = subprocess.run([str(POWERSHELL), '-NoProfile', '-EncodedCommand',
                                     base64.b64encode(script.encode('utf-16le')).decode()],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('YAC update installed', result.stdout)
            self.assertEqual((root / 'yac.ini').read_text(), 'personal settings')
            self.assertEqual((root / 'personal.log').read_text(), 'personal log')
            self.assertFalse((root / 'YAC-old.exe').exists())
            self.assertEqual((root / program).read_text(), 'new')

    @unittest.skipUnless(POWERSHELL.is_file(), 'Windows PowerShell required')
    def test_real_powershell_failed_copy_rolls_back_original_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / 'portable'
            root.mkdir()
            (root / 'LICENSE').write_text('old licence')
            (root / 'YAC-001-beta.exe').write_text('old executable')
            stage = base / 'stage'
            stage.mkdir()
            source, program = windows_update.extract(archive(), stage)
            hooks = r'''
function Read-Host { return "" }
function Copy-Item {
    param($LiteralPath, $Destination, [switch]$Recurse)
    if ([IO.Path]::GetFileName($LiteralPath) -eq 'YAC-001-beta.exe') { throw 'Simulated copy failure' }
    Microsoft.PowerShell.Management\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Recurse
}
'''
            script = hooks + windows_update.installer_script(root, source, stage, program, program, 2147483000)
            result = subprocess.run([str(POWERSHELL), '-NoProfile', '-EncodedCommand',
                                     base64.b64encode(script.encode('utf-16le')).decode()],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Simulated copy failure', result.stdout)
            self.assertEqual((root / 'LICENSE').read_text(), 'old licence')
            self.assertEqual((root / program).read_text(), 'old executable')
            self.assertTrue(stage.exists())


if __name__ == '__main__':
    unittest.main()
