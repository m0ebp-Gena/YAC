"""Optional Wi-Fi setup for the Raspberry Pi image. GPL-3.0-only."""
import getpass
import json
import os
import subprocess
import sys
import warnings

from modules import chat_int, help_int

HELPER = '/usr/local/libexec/yac-pi-wifi'
ERROR_LABELS = {'unavailable': 'l340', 'no-device': 'l341', 'country': 'l342',
                'not-found': 'l343', 'security': 'l129', 'connect': 'l345',
                'ssid': 'l356', 'password': 'l356', 'privacy': 'l347'}


class WifiError(RuntimeError):
    pass


def enabled():
    return sys.platform == 'linux' and os.environ.get('YAC_PI_IMAGE') == '1'


def bridge(request):
    result = subprocess.run(['sudo', '-n', HELPER], input=json.dumps(request),
                            capture_output=True, text=True, timeout=150)
    try:
        reply = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise WifiError('unavailable') from None
    if result.returncode or not reply.get('ok'):
        raise WifiError(reply.get('error', 'unavailable'))
    return reply


def field(prompt, secret=False):
    """Canonical entry: punctuation and command letters are always literal."""
    if not sys.stdin.isatty():
        raise WifiError('unavailable')
    chat_int.finish_response()
    if secret:
        # Never allow getpass to fall back to echoed password input.
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            return getpass.getpass(prompt + ' ', stream=sys.stdout)
    return input(prompt + ' ')


def control(root, language, read_key, watch, *, read_field=field):
    def label(key, **values):
        return chat_int.label(root, language, key).format(**values)
    def say(key, **values):
        chat_int.show_response(label(key, **values))
    if not enabled():
        say('l129')
        return
    try:
        state = bridge({'action': 'status'})
        country = state.get('country', '')
        countries = state['countries']
        while True:
            entered = read_field(label('l330', country=country or '--')).strip()
            if entered.casefold() == 'h':
                chat_int.show_response(help_int.get_help(root, language, 'h026'))
                continue
            entered = entered.upper()
            entered = {'UK': 'GB'}.get(entered, entered)
            country = entered or country
            if country not in countries:
                say('l356')
                return
            ssid = read_field(label('l332'))
            if not ssid:
                say('l355')
                return
            if not 1 <= len(ssid.encode('utf-8')) <= 32 or not ssid.isprintable():
                say('l356')
                return
            bridge({'action': 'private-start'})
            try:
                password = read_field(label('l333'), secret=True)
            finally:
                bridge({'action': 'private-end'})
            if len(password.encode('utf-8')) > 64 or any(not c.isprintable() for c in password):
                say('l356')
                return
            say('l007')
            while True:
                key = read_key().casefold()
                if watch.lost:
                    return
                if key in ('q', '\x03', '\x04'):
                    say('l355')
                    return
                if key in {'e', 'n'}:
                    break
                if key == 'h':
                    chat_int.show_response(help_int.get_help(root, language, 'h026'))
                if key == 'y':
                    say('l337')
                    bridge({'action': 'connect', 'country': country, 'ssid': ssid, 'password': password})
                    say('l338')
                    return
            password = ''
    except WifiError as error:
        say('l356' if str(error) in {'ssid', 'password'} else ERROR_LABELS.get(str(error), 'l340'))
    except (OSError, ValueError, subprocess.SubprocessError, getpass.GetPassWarning):
        # Do not log request data, backend output, passwords or exception objects.
        say('l340')
    except (EOFError, KeyboardInterrupt):
        say('l355')
