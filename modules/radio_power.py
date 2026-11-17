"""Optional startup and confirmed-quit power control for saved radios."""

from dataclasses import dataclass
import logging
import re
import time
from typing import Any

from modules import chat_int, help_int, find_rad


LOG = logging.getLogger('yac')
OPTIONS = ('off', 'start', 'stop', 'both')
LABELS = (('l453', 'Off'), ('l450', 'Start only'),
          ('l451', 'Stop only'), ('l452', 'Start and stop'))
YAESU_USB_POWER = frozenset({'0761', '0800'})
CAT_POWER_OFF = {
    '0761': b'PS0;', '0800': b'PS0;', '0840': b'PS0;',  # Yaesu
    # TS-2000 uses PS0 to stop and PS1 to start, despite the reversed
    # parameter descriptions in the English instruction manual.
    '019': b'PS0;', '020': b'PS0;', '021': b'PS9;',
    '023': b'PS9;', '024': b'PS0;',
    'kx2': b'PS0;',
}
CAT_WAKE = {
    '0761': ((0, b'PS1;'), (1.05, b'PS1;')),
    '0800': ((0, b'PS1;'),),
    '019': ((0, b'PS1;'),),
    '020': ((0, b';;;PS1;'),),
    '021': ((0, b';'), (0.25, b'PS1;')),
    '023': ((0, b';'), (0.25, b'PS1;')),
    '024': ((0, b';'), (0.1, b'PS1;')),
}
CIV_POWER = frozenset({
    'ic-705', 'ic-7100', 'ic-7300', 'ic-7300mk2', 'ic-7600', 'ic-7610', 'ic-9700',
})
CIV_WAKE_PREAMBLE = {
    'ic-7100': {300: 2, 1200: 3, 4800: 7, 9600: 13, 19200: 25},
    'ic-7300': {4800: 7, 9600: 13, 19200: 25, 38400: 50, 57600: 75, 115200: 150},
    'ic-7300mk2': {4800: 7, 9600: 13, 19200: 25},
    'ic-7610': {4800: 7, 9600: 13, 19200: 25, 38400: 50, 57600: 75, 115200: 150},
    'ic-9700': {4800: 5, 9600: 9, 19200: 20, 38400: 40, 57600: 59, 115200: 119},
}


def setting(settings):
    value = settings.get('radio_power', 'off').casefold()
    return value if value in OPTIONS else 'off'


def control(app, root, language, read_key):
    ini = root / 'yac.ini'
    index = OPTIONS.index(setting(app._read_settings(ini)))
    while True:
        chat_int.show_response(chat_int.label(root, language, *LABELS[index]))
        while True:
            key = read_key().casefold()
            if key == 'q':
                chat_int.show_done(root, language)
                return
            if key == 'h':
                chat_int.show_response(help_int.get_help(root, language, 'h079'))
            if key in {'o', '.', ','}:
                break
        index = (index + (-1 if key == ',' else 1)) % len(OPTIONS)
        app._set_yac_value(ini, 'radio_power', OPTIONS[index])


def _civ_packet(address, on):
    return bytes((0xFE, 0xFE, address, find_rad.CONTROLLER_ADDRESS, 0x18, int(on), 0xFD))


def _wake_sequence(protocol, model_id, model_name, address, baudrate):
    if protocol == 'CAT':
        # The QMX and TS-480 share an ID. QMX only supports CAT shutdown.
        if model_id == '020' and model_name.casefold().startswith(('qrp labs qmx', 'qmx')):
            return ()
        return CAT_WAKE.get(model_id, ())
    if protocol != 'CI-V' or model_id not in CIV_POWER or address is None:
        return ()
    preamble = CIV_WAKE_PREAMBLE.get(model_id, {}).get(baudrate, 0)
    return ((0, b'\xFE' * preamble + _civ_packet(address, on=True)),)


@dataclass
class WakeCandidate:
    model_name: str
    port: str
    baudrate: int
    profile: dict[str, str]
    port_info: Any
    sequence: tuple[tuple[float, bytes], ...]


def wake_candidates(ini_path, radios):
    """Supplement discovery using visible ports from saved radio profiles."""
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
    except (ImportError, OSError):
        LOG.exception('Could not enumerate ports for radio power-on')
        return []

    occupied = {radio.port.casefold() for radio in radios}
    occupied_usb = {radio.usb_identity for radio in radios if radio.usb_identity}
    candidates = []
    for profile in find_rad._radio_profiles(ini_path):
        identity = profile.get('usb_identity', '')
        if identity in occupied_usb:
            continue
        protocol = profile.get('protocol', '').upper()
        model_id = profile.get('model_id', '').casefold()
        model_name = profile.get('model') or model_id
        try:
            baudrate = int(profile.get('baud_rate', ''))
            address = int(profile.get('civ_address', '0'), 0) if protocol == 'CI-V' else None
            if baudrate <= 0 or (address is not None and not 0 < address < 0xE0):
                continue
        except ValueError:
            continue
        sequence = _wake_sequence(protocol, model_id, model_name, address, baudrate)
        if not sequence:
            continue
        if model_id in YAESU_USB_POWER and not identity.upper().startswith('10C4:EA70:'):
            continue
        preferred = find_rad._profile_port_hint(profile).casefold()
        if identity:
            matching = [port for port in ports if find_rad._usb_identity(port) == identity]
        else:
            # Native serial interfaces have no USB identity. Use the saved port
            # and never fall back to an unrelated USB interface at that address.
            matching = [port for port in ports if port.device.casefold() == preferred
                        and getattr(port, 'vid', None) is None]
        port_info = next((port for port in matching if port.device.casefold() == preferred), None)
        if port_info is None:
            if len(matching) != 1:
                continue
            port_info = matching[0]
        port = port_info.device
        if port.casefold() in occupied:
            continue
        # The ID 020 menu label may mention QMX generically. Skip a visibly QMX
        # USB interface even when its saved label predates positive identification.
        if model_id == '020' and find_rad._cat_model_name(model_id, port_info).startswith('QRP Labs'):
            continue
        candidates.append(WakeCandidate(model_name, port, baudrate, profile, port_info, sequence))
        occupied.add(port.casefold())
        if identity:
            occupied_usb.add(identity)
    return candidates


def wake(candidate):
    import serial

    try:
        with find_rad._open_serial(candidate.port, candidate.baudrate, serial) as connection:
            LOG.info('Power-on requested model=%s port=%s', candidate.model_name, candidate.port)
            for delay, packet in candidate.sequence:
                if delay:
                    time.sleep(delay)
                connection.write(packet)
                connection.flush()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            radios = find_rad._probe_saved_profiles([candidate.profile], [candidate.port_info], serial)
            if radios:
                find_rad._identify_id020(radios[0])
                return radios[0]
            time.sleep(0.25)
    except (OSError, ValueError):
        LOG.exception('Could not power on %s on %s', candidate.model_name, candidate.port)
    LOG.warning('Radio did not respond after power-on model=%s port=%s',
                candidate.model_name, candidate.port)
    return None


def power_off(radio):
    if radio.is_dummy:
        return
    model_id = radio.model_id.casefold()
    if model_id in YAESU_USB_POWER and not radio.usb_identity.upper().startswith('10C4:EA70:'):
        return
    packet = CAT_POWER_OFF.get(model_id) if radio.protocol == 'CAT' else None
    if radio.protocol == 'CAT' and model_id == '020' and radio.model_name.startswith('QRP Labs'):
        version = re.fullmatch(r'(\d+)_(\d+)_(\d+)QMX(\+?)', getattr(radio, 'qmx_firmware', ''))
        if not version or tuple(map(int, version.groups()[:3])) < (1, 4, 0 if version[4] else 1):
            return
    if radio.protocol == 'CI-V' and model_id in CIV_POWER and radio.civ_address is not None:
        packet = _civ_packet(radio.civ_address, on=False)
    if packet is not None:
        LOG.info('Power-off requested model=%s port=%s', radio.model_name, radio.port)
        radio.serial.write(packet)
        radio.serial.flush()
