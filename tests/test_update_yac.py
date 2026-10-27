"""Updater tests never contact GitHub or install real packages."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import ssl
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
import zipfile
import update_yac as updater


def archive(extra=None):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for name in ['yac.py','install_yac.py','install-yac.sh','modules/__init__.py']:
            z.writestr('yac-source-test/'+name,'# test')
        if extra:z.writestr(*extra)
    return stream.getvalue()


def release():
    base='https://github.com/m0ebp-Gena/YAC/releases/download/v-test/'
    return dict(tag_name='v-test',published_at='2026-10-24T12:00:00Z',draft=False,prerelease=True,
                body='Changes for testing.',assets=[dict(name=n,browser_download_url=base+n) for n in ['yac-source.zip','yac-source.zip.sha256']])


class Updates(unittest.TestCase):
    def test_portable_windows_download_coexists_with_legacy_update_asset(self):
        base = 'https://github.com/m0ebp-Gena/YAC/releases/download/v-test/'
        names = ['yac-win-portable-2026-10-27-r7.zip', 'YAC-001-beta-r7-2026-10-27.zip']
        assets = [dict(name=n, browser_download_url=base+n)
                  for name in names for n in (name, name+'.sha256')]
        self.assertEqual(updater.asset_pair({'assets':assets}, windows=True)[0]['name'], names[0])

    def test_mac_and_windows_fetch_use_verified_context(self):
        from modules.update_certificates import context
        # Simulate Python having no preconfigured roots, as on the failing Mac.
        def empty_trust():
            return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with patch('modules.update_certificates.ssl.create_default_context', side_effect=empty_trust):
            trust = context()
        self.assertGreater(trust.cert_store_stats()['x509_ca'], 0)
        self.assertTrue(trust.check_hostname)
        self.assertEqual(trust.verify_mode, ssl.CERT_REQUIRED)
        for platform in ('darwin', 'win32'):
            with patch.object(updater.sys, 'platform', platform), patch.object(updater.urllib.request, 'urlopen') as opened:
                response = opened.return_value.__enter__.return_value
                response.geturl.return_value = 'https://github.com/test'
                response.read.return_value = b'ok'
                for url in (updater.API, 'https://github.com/test.zip.sha256', 'https://github.com/test.zip'):
                    self.assertEqual(updater.fetch(url, 100), b'ok')
                    supplied = opened.call_args.kwargs['context']
                    self.assertTrue(supplied.check_hostname)
                    self.assertEqual(supplied.verify_mode, ssl.CERT_REQUIRED)

    def test_linux_fetch_keeps_default_trust(self):
        with patch.object(updater.sys, 'platform', 'linux'), patch.object(updater.urllib.request, 'urlopen') as opened:
            response = opened.return_value.__enter__.return_value
            response.geturl.return_value = updater.API
            response.read.return_value = b'ok'
            updater.fetch(updater.API, 100)
            self.assertNotIn('context', opened.call_args.kwargs)

    def test_platform_names_preferred_over_compatibility_assets(self):
        base = 'https://github.com/m0ebp-Gena/YAC/releases/download/v-test/'
        names = ['yac-win-2026-10-26-r4.zip', 'yac-mac-linux-2026-10-26-r4.zip',
                 'YAC-001-beta-r4-2026-10-26.zip', 'yac-source.zip']
        assets = [dict(name=n, browser_download_url=base+n)
                  for name in names for n in (name, name+'.sha256')]
        for windows, expected in ((True, names[0]), (False, names[1])):
            with self.subTest(windows=windows):
                pair = updater.asset_pair({'assets': assets}, windows=windows)
                self.assertEqual(pair[0]['name'], expected)
                self.assertEqual(pair[1]['name'], expected+'.sha256')

    def test_multiple_modern_packages_rejected_instead_of_guessing(self):
        base = 'https://github.com/m0ebp-Gena/YAC/releases/download/v-test/'
        names = ['yac-mac-linux-2026-10-26-r4.zip', 'yac-mac-linux-2026-10-26-r5.zip']
        assets = [dict(name=n, browser_download_url=base+n)
                  for name in names for n in (name, name+'.sha256')]
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            updater.asset_pair({'assets': assets})

    def test_preselected_release_never_rechecks_or_prompts(self):
        data=archive()
        responses=[data,(hashlib.sha256(data).hexdigest()+'  yac-source.zip').encode()]
        with tempfile.TemporaryDirectory() as tmp,patch.object(updater,'fetch',side_effect=responses) as fetch, \
             patch.object(updater.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as install, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(updater.run(Path(tmp),lambda:self.fail('second confirmation'),selected_release=release()),0)
            self.assertEqual(fetch.call_count,2)
            self.assertNotIn(updater.API,[c.args[0] for c in fetch.call_args_list])
            self.assertTrue(install.call_args.kwargs['capture_output'])
            self.assertEqual(output.getvalue(),'')

    def test_failed_selected_installer_is_logged_without_screen_diagnostics(self):
        data = archive()
        responses = [data, (hashlib.sha256(data).hexdigest()+'  yac-source.zip').encode()]
        failure = subprocess.CompletedProcess([], 1, stdout='Dependency setup failed.', stderr='connection timed out')
        with tempfile.TemporaryDirectory() as tmp, patch.object(updater, 'fetch', side_effect=responses), patch.object(updater.subprocess, 'run', return_value=failure), self.assertLogs('yac.update', level='ERROR') as logs, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(updater.run(Path(tmp), selected_release=release()), 1)
        self.assertEqual(output.getvalue(), '')
        self.assertIn('exit=1', logs.output[0])
        self.assertIn('connection timed out', logs.output[0])
        self.assertIn('Dependency setup failed', logs.output[0])

    def test_beta_and_draft_selection(self):
        beta=release()
        draft=dict(beta,published_at='2026-10-25T00:00:00Z',draft=True)
        self.assertEqual(updater.newest_release([draft,beta])['tag_name'],'v-test')

    def test_cancel_and_read_never_download_or_install(self):
        keys=iter(['r','q'])
        with tempfile.TemporaryDirectory() as tmp, patch.object(updater,'fetch',return_value=json.dumps([release()]).encode()) as fetch, patch.object(updater.subprocess,'run') as install, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(updater.run(Path(tmp),lambda:next(keys)),0)
            self.assertEqual(fetch.call_count,1)
            install.assert_not_called()
            self.assertIn('Changes for testing.',out.getvalue())

    def test_current_version_never_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'release.json').write_text(json.dumps({'tag':'v-test'}))
            with patch.object(updater,'fetch',return_value=json.dumps([release()]).encode()),redirect_stdout(io.StringIO()) as out:
                self.assertEqual(updater.run(root,lambda:self.fail('unexpected prompt')),0)
                self.assertIn('up to date',out.getvalue())

    def test_checksum_failure_cannot_run_installer(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(updater,'fetch',side_effect=[json.dumps([release()]).encode(),archive(),b'0'*64+b'  yac-source.zip']),patch.object(updater.subprocess,'run') as install:
            with self.assertRaisesRegex(ValueError,'checksum failed'):
                updater.run(Path(tmp),lambda:' ')
            install.assert_not_called()

    def test_bad_archive_paths_and_incomplete_source(self):
        for bad in ['../escape','/absolute','x/../../escape','x\\escape']:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):updater.extract_source(archive((bad,'bad')),Path(tmp))
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:z.writestr('empty/file','x')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'Incomplete'):updater.extract_source(stream.getvalue(),Path(tmp))

    def test_verified_update_and_failure_restore(self):
        data=archive()
        for status in [0,1]:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'yac.py').write_text('old');(root/'yac.ini').write_text('my settings')
                def install(command,check):
                    self.assertEqual(command[-1],'--update')
                    self.assertTrue((Path(command[1]).parent/'release.json').is_file())
                    (root/'yac.py').write_text('new')
                    return subprocess.CompletedProcess(command,status)
                responses=[json.dumps([release()]).encode(),data,(hashlib.sha256(data).hexdigest()+'  yac-source.zip').encode()]
                with patch.object(updater,'fetch',side_effect=responses),patch.object(updater.subprocess,'run',side_effect=install):
                    self.assertEqual(updater.run(root,lambda:' '),status)
                self.assertEqual((root/'yac.py').read_text(),'old' if status else 'new')
                self.assertEqual((root/'yac.ini').read_text(),'my settings')

    def test_untrusted_asset_url_and_display_controls(self):
        r=release();r['assets'][0]['browser_download_url']='http://example.org/evil'
        with self.assertRaises(ValueError):updater.asset_pair(r)
        self.assertNotIn('\x1b',updater.clean_changes('hello\x1b[2J'))


class LockTests(unittest.TestCase):
    def test_running_yac_prevents_download(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(updater, 'fetch', return_value=json.dumps([release()]).encode()) as fetch, patch('modules.update_lock.application_lock', side_effect=RuntimeError('Close YAC')), patch.object(updater.subprocess, 'run') as install:
            with self.assertRaisesRegex(RuntimeError, 'Close YAC'):
                updater.run(Path(tmp), lambda: ' ')
            self.assertEqual(fetch.call_count, 1)
            install.assert_not_called()

    def test_posix_lock_excludes_and_releases(self):
        from types import SimpleNamespace
        from modules import update_lock
        calls=[]
        fake=SimpleNamespace(LOCK_EX=2, LOCK_SH=1, LOCK_NB=4, LOCK_UN=8,
                             flock=lambda fd,flags:calls.append(flags))
        with tempfile.TemporaryDirectory() as tmp, patch.object(update_lock.sys, 'platform', 'linux'), patch.dict('sys.modules', {'fcntl':fake}):
            with update_lock.application_lock(Path(tmp), exclusive=True):
                self.assertEqual(calls,[6])
        self.assertEqual(calls,[6,8])
