#!/usr/bin/python3 -I
"""Narrow Pi Wi-Fi helper; secrets arrive only on stdin. GPL-3.0-only."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

PROFILES = Path('/etc/NetworkManager/system-connections')
COUNTRIES = Path('/usr/share/zoneinfo/iso3166.tab')
KEY_ECHO = Path('/sys/accessibility/speakup/key_echo')
ECHO_SAVED = Path('/run/yac-wifi-key-echo')
NMCLI = '/usr/bin/nmcli'
RASPI = '/usr/bin/raspi-config'


class WifiError(Exception):
    pass


def run(args, timeout=15, required=True):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, timeout=timeout, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
                                                          'LC_ALL': 'C'})
    if required and result.returncode:
        raise WifiError('unavailable')
    return result


def country_codes():
    return {line.split('\t', 1)[0] for line in COUNTRIES.read_text().splitlines()
            if re.match(r'^[A-Z]{2}\t', line)}


def interface(base=Path('/sys/class/net')):
    choices = sorted(path.parent.name for path in base.glob('*/wireless')
                     if re.fullmatch('[A-Za-z0-9_.-]+', path.parent.name))
    if not choices:
        raise WifiError('no-device')
    return choices[0]


def validate(request):
    if not isinstance(request, dict):
        raise WifiError('unavailable')
    action = request.get('action')
    if action in ('status', 'private-start', 'private-end') and set(request) == {'action'}:
        return action
    if action != 'connect' or set(request) != {'action', 'country', 'ssid', 'password'}:
        raise WifiError('unavailable')
    country, ssid, password = (request[key] for key in ('country', 'ssid', 'password'))
    if not isinstance(country, str) or country not in country_codes():
        raise WifiError('country')
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or not ssid.isprintable():
        raise WifiError('ssid')
    if (not isinstance(password, str) or len(password.encode()) > 64 or
            any(not c.isprintable() for c in password)):
        raise WifiError('password')
    return action


def fields(line):
    """Decode nmcli terse escaped colons and backslashes without a shell."""
    result, current, escape = [], '', False
    for char in line:
        if escape:
            current += char
            escape = False
        elif char == '\\':
            escape = True
        elif char == ':':
            result.append(current)
            current = ''
        else:
            current += char
    result.append(current)
    return result


def key_string(value):
    return value.replace('\\', '\\\\').replace(' ', '\\s')


def profile(identifier, iface, ssid, password, security):
    content = (f'[connection]\nid=YAC Wi-Fi {identifier}\nuuid={identifier}\ntype=wifi\n'
               f'interface-name={iface}\nautoconnect=true\n\n[wifi]\nmode=infrastructure\n'
               'ssid=' + ';'.join(str(b) for b in ssid.encode()) + ';\n')
    if security:
        content += f'\n[wifi-security]\nkey-mgmt={security}\npsk={key_string(password)}\npsk-flags=0\n'
    return content + '\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n'


def private_entry(start):
    if start:
        if ECHO_SAVED.exists():
            raise WifiError('privacy')
        if KEY_ECHO.exists():
            previous = KEY_ECHO.read_text().strip()
            if previous not in ('0', '1', '2'):
                raise WifiError('privacy')
            with ECHO_SAVED.open('x', encoding='ascii') as stream:
                os.chmod(ECHO_SAVED, 0o600)
                stream.write(previous)
            try:
                KEY_ECHO.write_text('0\n')
            except BaseException:
                ECHO_SAVED.unlink(missing_ok=True)
                raise
    elif ECHO_SAVED.exists():
        previous = ECHO_SAVED.read_text().strip()
        if previous not in ('0', '1', '2'):
            raise WifiError('privacy')
        if KEY_ECHO.exists() and KEY_ECHO.read_text().strip() == '0':
            KEY_ECHO.write_text(previous + '\n')
        ECHO_SAVED.unlink()


def connect(request):
    iface = interface()
    if run([RASPI, 'nonint', 'do_wifi_country', request['country']], timeout=25, required=False).returncode:
        raise WifiError('country')
    scan = run([NMCLI, '--wait', '15', '-t', '--escape', 'yes', '-f', 'SSID,SECURITY',
                'device', 'wifi', 'list', 'ifname', iface, '--rescan', 'yes'], timeout=20)
    matches = [row[1] for row in map(fields, scan.stdout.splitlines())
               if len(row) == 2 and row[0] == request['ssid']]
    if not matches:
        raise WifiError('not-found')
    capabilities = ' '.join(matches)
    if '802.1X' in capabilities or 'WEP' in capabilities or 'OWE' in capabilities:
        raise WifiError('security')
    password = request['password']
    if 'WPA3' in capabilities and 'WPA2' not in capabilities:
        security = 'sae'
        valid = 1 <= len(password.encode()) <= 63
    elif 'WPA' in capabilities:
        security = 'wpa-psk'
        valid = 8 <= len(password.encode()) <= 63 or bool(re.fullmatch('[0-9A-Fa-f]{64}', password))
    else:
        security = ''
        valid = not password
    if not valid:
        raise WifiError('password')
    active = run([NMCLI, '-t', '-f', 'UUID,DEVICE', 'connection', 'show', '--active'])
    previous = next((row[0] for row in map(fields, active.stdout.splitlines())
                     if len(row) == 2 and row[1] == iface and re.fullmatch('[0-9a-fA-F-]{36}', row[0])), None)
    if PROFILES.is_symlink():
        raise WifiError('unavailable')
    PROFILES.mkdir(parents=True, exist_ok=True)
    identifier = str(uuid.uuid4())
    path = PROFILES / f'yac-wifi-{identifier}.nmconnection'
    created = False
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(profile(identifier, iface, request['ssid'], password, security))
            stream.flush()
            os.fsync(stream.fileno())
        run([NMCLI, 'connection', 'load', str(path)])
        result = run([NMCLI, '--wait', '30', 'connection', 'up', 'uuid', identifier], timeout=35, required=False)
        if result.returncode:
            raise WifiError('connect')
    except BaseException:
        # Only this attempt's new profile is removed. Existing saved networks stay.
        if created:
            try:
                run([NMCLI, 'connection', 'delete', 'uuid', identifier], required=False)
            finally:
                path.unlink(missing_ok=True)
                if previous:
                    run([NMCLI, '--wait', '10', 'connection', 'up', 'uuid', previous], required=False)
        raise


def handle(request):
    action = validate(request)
    if action.startswith('private-'):
        private_entry(action == 'private-start')
        return {'ok': True}
    if run(['/usr/bin/systemctl', 'is-active', '--quiet', 'NetworkManager.service'], required=False).returncode:
        raise WifiError('unavailable')
    interface()
    if action == 'status':
        result = run([RASPI, 'nonint', 'get_wifi_country'], required=False)
        country = result.stdout.strip()
        return {'ok': True, 'country': country if country in country_codes() else '',
                'countries': sorted(country_codes())}
    connect(request)
    return {'ok': True}


def main():
    import fcntl
    if sys.platform != 'linux' or os.geteuid() != 0 or len(sys.argv) != 1:
        raise WifiError('unavailable')
    with open('/run/yac-pi-wifi.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(handle(json.loads(sys.stdin.read(8192)))), flush=True)


if __name__ == '__main__':
    try:
        main()
    except WifiError as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        sys.exit(1)
    except BaseException:
        # Command failures may contain private connection data: never print them.
        print(json.dumps({'ok': False, 'error': 'unavailable'}))
        sys.exit(1)
