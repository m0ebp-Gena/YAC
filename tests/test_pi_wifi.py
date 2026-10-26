import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pi_wifi_settings', ROOT / 'pi/wifi-settings.py')
wifi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wifi)
spec = importlib.util.spec_from_file_location('pi_wifi_cleanup', ROOT / 'pi/clear-image-wifi.py')
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class PiWifiTests(unittest.TestCase):
    def request(self, **overrides):
        return dict(dict(action='connect', country='GB', ssid='Home', password='q.,;#pass\\ word'), **overrides)

    def test_validation_rejects_extra_paths_invalid_country_and_control_characters(self):
        with patch.object(wifi, 'country_codes', return_value={'GB'}):
            self.assertEqual(wifi.validate(self.request()), 'connect')
            for request in (self.request(path='/etc/anything'), self.request(country='GB;cmd'),
                            self.request(ssid='x\nprofile'), self.request(password='x\npsk'), self.request(ssid='é'*17)):
                with self.subTest(request=list(request)), self.assertRaises(wifi.WifiError):
                    wifi.validate(request)

    def test_nmcli_escaping_is_decoded_and_profile_preserves_secret_without_argv(self):
        self.assertEqual(wifi.fields(r'Home\: WiFi\\new:WPA2'), ['Home: WiFi\\new', 'WPA2'])
        text = wifi.profile('uuid', 'wlan0', 'A:é', ' a;#\\password ', 'wpa-psk')
        self.assertIn('ssid=65;58;195;169;', text)
        self.assertIn('psk=\\sa;#\\\\password\\s\n', text)

    def test_private_entry_restores_original_speakup_setting(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(wifi, 'KEY_ECHO', Path(folder) / 'key_echo'), \
             patch.object(wifi, 'ECHO_SAVED', Path(folder) / 'saved'):
            wifi.KEY_ECHO.write_text('2\n')
            wifi.private_entry(True)
            self.assertEqual(wifi.KEY_ECHO.read_text(), '0\n')
            wifi.private_entry(False)
            self.assertEqual(wifi.KEY_ECHO.read_text(), '2\n')
            self.assertFalse(wifi.ECHO_SAVED.exists())

    def test_connection_failure_removes_only_new_profile_and_restores_previous(self):
        old_uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            if 'SSID,SECURITY' in command:
                return subprocess.CompletedProcess(command, 0, 'Home:WPA2\n')
            if '--active' in command:
                return subprocess.CompletedProcess(command, 0, old_uuid + ':wlan0\n')
            status = 1 if 'up' in command and old_uuid not in command else 0
            return subprocess.CompletedProcess(command, status, '')
        with tempfile.TemporaryDirectory() as folder, patch.object(wifi, 'PROFILES', Path(folder)), \
             patch.object(wifi, 'interface', return_value='wlan0'), patch.object(wifi, 'run', side_effect=run):
            personal = Path(folder) / 'existing.nmconnection'
            personal.write_text('personal network')
            with self.assertRaisesRegex(wifi.WifiError, 'connect'):
                wifi.connect(self.request())
            self.assertEqual(personal.read_text(), 'personal network')
            self.assertEqual(list(Path(folder).iterdir()), [personal])
        self.assertEqual(commands[-1][-1], old_uuid)
        self.assertTrue(any('delete' in command for command in commands))
        self.assertFalse(any(self.request()['password'] in part for command in commands for part in command))

    def test_wpa3_personal_selects_sae_and_saves_profile(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, 'Home:WPA3\n' if 'SSID,SECURITY' in command else '')
        with tempfile.TemporaryDirectory() as folder, patch.object(wifi, 'PROFILES', Path(folder)), \
             patch.object(wifi, 'interface', return_value='wlan0'), patch.object(wifi, 'run', side_effect=run):
            wifi.connect(self.request())
            files = list(Path(folder).glob('yac-wifi-*.nmconnection'))
            self.assertEqual(len(files), 1)
            self.assertIn('key-mgmt=sae', files[0].read_text())
        self.assertFalse(any(self.request()['password'] in part for command in commands for part in command))

    def test_cleanup_selects_only_wifi_profiles_not_wired_connections(self):
        first = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        second = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
        output = first + ':802-11-wireless\n' + second + ':802-3-ethernet\n'
        with patch.object(cleanup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output)):
            self.assertEqual(cleanup.profiles(), [first])


if __name__ == '__main__':
    unittest.main()
