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
    @unittest.skipUnless(POWERSHELL.is_file(), 'Windows PowerShell required')
    def test_access_denied_rename_retries_then_succeeds_or_stops(self):
        for failures in (2, 99):
            with self.subTest(failures=failures), tempfile.TemporaryDirectory() as folder:
                base = Path(folder).resolve()
                source, target = base / 'original', base / 'renamed'
                source.mkdir()
                (source / 'keep.txt').write_text('original contents')
                script = windows_update.installer_script(base, base, base, 'YAC.exe', 'YAC.exe', 2147483000)
                definitions = script.split("try {\n    Write-Host 'Waiting", 1)[0]
                hooks = r'''
$script:Attempts = 0
$script:Sleeps = 0
function Start-Sleep { param($Milliseconds) $script:Sleeps++ }
function Rename-ApplicationFile($From, $To) {
    $script:Attempts++
    if ($script:Attempts -le FAILURES) {
        throw [IO.IOException]::new('Injected access denial', -2147024891)
    }
    [IO.Directory]::Move($From, $To)
}
'''.replace('FAILURES', str(failures))
                script = definitions + hooks + '\ntry { Move-ApplicationFile ' + windows_update.literal(source) + ' ' + windows_update.literal(target) + r'''
    Write-Output 'Renamed'
} catch { Write-Output $_.Exception.Message }
Write-Output ('Attempts=' + $script:Attempts + ';Sleeps=' + $script:Sleeps)
'''
                result = subprocess.run([str(POWERSHELL), '-NoProfile', '-EncodedCommand',
                    base64.b64encode(script.encode('utf-16le')).decode()], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                if failures == 2:
                    self.assertIn('Attempts=3;Sleeps=2', result.stdout)
                    self.assertEqual((target / 'keep.txt').read_text(), 'original contents')
                    self.assertFalse(source.exists())
                else:
                    self.assertIn('Windows error 5; attempts 12', result.stdout)
                    self.assertIn(str(source), result.stdout)
                    self.assertIn(str(target), result.stdout)
                    self.assertIn('Attempts=12;Sleeps=11', result.stdout)
                    self.assertEqual((source / 'keep.txt').read_text(), 'original contents')
                    self.assertFalse(target.exists())

    @unittest.skipUnless(POWERSHELL.is_file(), 'Windows PowerShell required')
    def test_real_dropbox_cloud_file_is_accepted_without_modification(self):
        cloud = Path(__file__).resolve().parents[1] / 'COPYING'
        before = cloud.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            script = windows_update.installer_script(base, base, base, 'YAC.exe', 'YAC.exe', 2147483000)
            definitions = script.split("try {\n    Write-Host 'Waiting", 1)[0]
            check = definitions + '\nAssert-ApplicationFile ' + windows_update.literal(cloud) + "\nWrite-Output 'Cloud file accepted'"
            result = subprocess.run([str(POWERSHELL), '-NoProfile', '-EncodedCommand',
                base64.b64encode(check.encode('utf-16le')).decode()], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Cloud file accepted', result.stdout)
        self.assertEqual(cloud.read_bytes(), before)

    @unittest.skipUnless(POWERSHELL.is_file(), 'Windows PowerShell required')
    def test_real_directory_junction_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            outside = base / 'outside'
            outside.mkdir()
            (outside / 'keep.txt').write_text('untouched')
            junction = base / 'linked'
            script = windows_update.installer_script(base, base, base, 'YAC.exe', 'YAC.exe', 2147483000)
            definitions = script.split("try {\n    Write-Host 'Waiting", 1)[0]
            check = definitions + "\n$ErrorActionPreference = 'Stop'\ntry {\n    try {\n        New-Item -ItemType Junction -Path " + windows_update.literal(junction) + ' -Target ' + windows_update.literal(outside) + r''' | Out-Null
    } catch {
        if (($_.Exception -is [ComponentModel.Win32Exception] -and $_.Exception.NativeErrorCode -eq 5) -or
            $_.Exception -is [UnauthorizedAccessException]) {
            Write-Output 'ENVIRONMENT BLOCKED: Windows denied creation of the test junction; YAC protection was not tested.'
            exit 77
        }
        throw
    }
    Assert-ApplicationFile ''' + windows_update.literal(junction) + r'''
} finally {
    if (Test-Path -LiteralPath ''' + windows_update.literal(junction) + r''') {
        [IO.Directory]::Delete(''' + windows_update.literal(junction) + r''')
    }
}
'''
            result = subprocess.run([str(POWERSHELL), '-NoProfile', '-EncodedCommand',
                base64.b64encode(check.encode('utf-16le')).decode()], capture_output=True, text=True, timeout=30)
            self.assertEqual((outside / 'keep.txt').read_text(), 'untouched')
            self.assertFalse(os.path.lexists(junction), 'Test junction cleanup failed: ' + str(junction))
            if result.returncode == 77 and 'ENVIRONMENT BLOCKED:' in result.stdout:
                self.skipTest(result.stdout.strip())
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Refusing to replace a linked application file', result.stderr)

    def test_junction_environment_block_is_not_a_yac_failure_or_pass(self):
        result = unittest.TestResult()
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], 77, 'ENVIRONMENT BLOCKED: Windows denied creation of the test junction.', '')):
            self.__class__('test_real_directory_junction_is_still_rejected').run(result)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])

    def test_junction_unexpected_setup_error_is_not_hidden_as_environment_block(self):
        result = unittest.TestResult()
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], 1, '', 'Unexpected setup error')):
            self.__class__('test_real_directory_junction_is_still_rejected').run(result)
        self.assertEqual(result.skipped, [])
        self.assertEqual(len(result.failures), 1)

    def test_junction_accepted_by_updater_is_still_a_failure(self):
        result = unittest.TestResult()
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            self.__class__('test_real_directory_junction_is_still_rejected').run(result)
        self.assertEqual(result.skipped, [])
        self.assertEqual(len(result.failures), 1)

    def test_flat_archive_extracts_without_an_extra_user_folder(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(archive())) as old, zipfile.ZipFile(stream, 'w') as flat:
            for name in old.namelist():
                flat.writestr(name.split('/', 1)[1], old.read(name))
        with tempfile.TemporaryDirectory() as folder:
            source, program = windows_update.extract(stream.getvalue(), Path(folder))
            self.assertEqual(source, Path(folder) / 'package')
            self.assertTrue((source / program).is_file())
            self.assertTrue((source / 'lang/en/labels/l000').is_file())

    def test_preselected_release_skips_lookup_and_second_confirmation(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(windows_update.sys,'platform','win32'), \
             patch.object(windows_update.sys,'frozen',True,create=True), \
             patch.object(windows_update.sys.stdin,'isatty',return_value=True), \
             patch.object(updater,'read_key',side_effect=AssertionError('second confirmation')), \
             patch.object(updater,'fetch',side_effect=[archive(),b'0'*64+b'  YAC-001-beta-2026-10-22.zip']) as fetch, \
             patch.object(windows_update.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(ValueError,'checksum failed'):
                windows_update.run(Path(folder),selected_release=release())
            self.assertEqual(fetch.call_count,2)
            self.assertNotIn(updater.API,[call.args[0] for call in fetch.call_args_list])
            launch.assert_not_called()

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


    def test_stage_is_inside_installation_even_with_other_default_temp(self):
        data=archive()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()/'portable';root.mkdir()
            other=Path(folder).resolve()/'system-temp';other.mkdir()
            selected=release()
            expected=hashlib.sha256(data).hexdigest().encode()+b'  '+selected['assets'][0]['name'].encode()
            mkdtemp=tempfile.mkdtemp
            with patch.object(windows_update.sys,'platform','win32'), \
                 patch.object(windows_update.sys,'frozen',True,create=True), \
                 patch.object(windows_update.sys,'executable',str(root/'YAC-old.exe')), \
                 patch.object(windows_update.sys.stdin,'isatty',return_value=True), \
                 patch.object(updater,'fetch',side_effect=[data,expected]), \
                 patch.object(tempfile,'tempdir',str(other)), \
                 patch.object(tempfile,'mkdtemp',wraps=mkdtemp) as create, \
                 patch.object(windows_update.subprocess,'Popen',side_effect=OSError('launch failed')):
                with self.assertRaisesRegex(OSError,'launch failed'):
                    windows_update.run(root,selected_release=selected)
            self.assertEqual(Path(create.call_args.kwargs['dir']),root)
            self.assertEqual(list(root.iterdir()),[root/'.update.lock'])
            self.assertEqual(list(other.iterdir()),[])

    @unittest.skipUnless(POWERSHELL.is_file(),'Windows PowerShell required')
    def test_nested_same_volume_stage_installs_and_is_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()/'portable';root.mkdir()
            (root/'yac.ini').write_text('preserve settings')
            (root/'YAC-old.exe').write_text('old program')
            (root/'_internal').mkdir();(root/'_internal/old.dll').write_text('old library')
            stage=Path(tempfile.mkdtemp(prefix='.yac-windows-update-',dir=root))
            source,program=windows_update.extract(archive(),stage)
            script='function Read-Host { return "" }; function Start-Process { };\n'+windows_update.installer_script(root,source,stage,program,'YAC-old.exe',2147483000)
            result=subprocess.run([str(POWERSHELL),'-NoProfile','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode()],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('YAC update installed',result.stdout)
            self.assertFalse(stage.exists())
            self.assertEqual((root/'yac.ini').read_text(),'preserve settings')
            self.assertEqual((root/'_internal/runtime.dll').read_text(),'new')
            self.assertFalse((root/'_internal/old.dll').exists())
            self.assertFalse((root/'YAC-old.exe').exists())


if __name__ == '__main__':
    unittest.main()
