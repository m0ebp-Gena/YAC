import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from modules import wifi_control

ROOT = Path(__file__).resolve().parents[1]


class WifiControlTests(unittest.TestCase):
    def test_disabled_outside_image_never_runs_helper_or_reads_credentials(self):
        with patch.object(wifi_control, 'enabled', return_value=False), \
             patch.object(wifi_control, 'bridge') as bridge, redirect_stdout(io.StringIO()):
            wifi_control.control(ROOT, 'en', lambda: self.fail('key read'), SimpleNamespace(lost=False),
                                 read_field=lambda *a, **k: self.fail('credential read'))
            bridge.assert_not_called()

    def test_confirmation_cancel_restores_key_echo_and_changes_no_connection(self):
        calls = []
        def bridge(request):
            calls.append(request)
            return {'country': 'GB', 'countries': ['GB']}
        values = iter(['', 'Home: q.,', 'private-q.,password'])
        with patch.object(wifi_control, 'enabled', return_value=True), \
             patch.object(wifi_control, 'bridge', side_effect=bridge), redirect_stdout(io.StringIO()):
            wifi_control.control(ROOT, 'en', lambda: 'q', SimpleNamespace(lost=False),
                                 read_field=lambda *a, **k: next(values))
        self.assertEqual([r['action'] for r in calls], ['status', 'private-start', 'private-end'])

    def test_confirmed_request_preserves_literal_punctuation_and_does_not_print_password(self):
        calls = []
        def bridge(request):
            calls.append(request)
            return {'country': '', 'countries': ['GB']}
        values = iter(['UK', 'My: WiFi\\home', ' q.,;#password '])
        output = io.StringIO()
        with patch.object(wifi_control, 'enabled', return_value=True), \
             patch.object(wifi_control, 'bridge', side_effect=bridge), redirect_stdout(output):
            wifi_control.control(ROOT, 'en', lambda: ' ', SimpleNamespace(lost=False),
                                 read_field=lambda *a, **k: next(values))
        self.assertEqual(calls[-1], dict(action='connect', country='GB', ssid='My: WiFi\\home', password=' q.,;#password '))
        self.assertNotIn(' q.,;#password ', output.getvalue())

    def test_password_cancellation_always_restores_key_echo(self):
        calls = []
        def bridge(request):
            calls.append(request['action'])
            return {'country': 'GB', 'countries': ['GB']}
        def entry(prompt, secret=False):
            if secret:
                raise KeyboardInterrupt
            return '' if prompt == 'Country?' else 'Home'
        with patch.object(wifi_control, 'enabled', return_value=True), \
             patch.object(wifi_control, 'bridge', side_effect=bridge), redirect_stdout(io.StringIO()):
            wifi_control.control(ROOT, 'en', lambda: self.fail('key read'), SimpleNamespace(lost=False), read_field=entry)
        self.assertEqual(calls, ['status', 'private-start', 'private-end'])

    def test_short_prompts_and_help_preserve_literal_ssid_and_password(self):
        calls, prompts = [], []
        values = iter(['h', 'GB', 'h', 'h'])
        def bridge(request):
            calls.append(request)
            return {'country': 'GB', 'countries': ['GB']}
        def entry(prompt, secret=False):
            prompts.append((prompt, secret))
            return next(values)
        with patch.object(wifi_control, 'enabled', return_value=True), \
             patch.object(wifi_control, 'bridge', side_effect=bridge), \
             redirect_stdout(io.StringIO()) as output:
            wifi_control.control(ROOT, 'en', iter(['h', ' ']).__next__, SimpleNamespace(lost=False), read_field=entry)
        self.assertEqual(prompts, [('Country?', False), ('Country?', False), ('S S I D?', False), ('Password?', True)])
        self.assertEqual(calls[-1]['ssid'], 'h')
        self.assertEqual(calls[-1]['password'], 'h')
        self.assertIn('Ctrl+C', output.getvalue())

    def test_backend_errors_do_not_expose_raw_diagnostics(self):
        secret = 'PRIVATE-PASSWORD'
        with patch.object(wifi_control.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='bad', stderr=secret)):
            with self.assertRaises(wifi_control.WifiError) as result:
                wifi_control.bridge({'action': 'connect', 'password': secret})
        self.assertNotIn(secret, str(result.exception))


if __name__ == '__main__':
    unittest.main()
