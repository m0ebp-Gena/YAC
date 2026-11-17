"""Fetch and browse a snapshot of recent DXSpider spots."""
import logging
import re
import socket
import time
from decimal import Decimal

from modules import chat_int, help_int, hints, region_plan
from modules.decoder_control import FT_DIAL_FREQUENCIES

DEBUG_LOG = logging.getLogger('yac')
HAMSERVE = ('dxc.hamserve.uk', 7300)
M0MHX = ('dxc.m0mhx.uk', 7300)
ATTEMPTS = (
    (HAMSERVE, 2, 'm017'),
    (M0MHX, 2, 'm022'),
    (HAMSERVE, 4, 'm023'),
    (M0MHX, 4, 'm024'),
)
LOGIN = re.compile(rb'(?:login|callsign):[ \t]*$', re.IGNORECASE)
PROMPT = re.compile(rb'(?:^|\n)[A-Z0-9/-]+ de [A-Z0-9/-]+ [^\r\n]*>[ \t\r\n]*$', re.IGNORECASE)
SPOT = re.compile(
    rb'^\s*(\d+(?:\.\d+)?)\s+([A-Z0-9/]+)\s+\d{1,2}-[A-Z]{3}-\d{4}\s+\d{4}Z\b(.*)',
    re.IGNORECASE,
)
MODE = re.compile(rb'\b(?:(?i:FT8|FT4|CW|LSB|USB|SSB|RTTY|PSK31|SSTV|JS8)|AM|FM)\b')
SPOTTER = re.compile(rb'\s*<[A-Z0-9/#-]+>\s*$', re.IGNORECASE)
FT_MODES_BY_DIAL = {
    Decimal(frequency): mode
    for mode, frequencies in FT_DIAL_FREQUENCIES.items()
    for frequency in frequencies
}


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('DX cluster attempt timed out')
    return remaining


def _read_until(connection, marker, deadline):
    data = bytearray()
    while len(data) < 65536:
        connection.settimeout(_remaining(deadline))
        chunk = connection.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if marker.search(data):
            return bytes(data)
    raise OSError('Incomplete DX cluster response')


def fetch(call, cluster, timeout):
    deadline = time.monotonic() + timeout
    stage = 'connecting'
    try:
        with socket.create_connection(cluster, timeout=_remaining(deadline)) as connection:
            stage = 'waiting for login prompt'
            _read_until(connection, LOGIN, deadline)
            stage = 'sending callsign'
            connection.settimeout(_remaining(deadline))
            connection.sendall(call.encode('ascii') + b'\r\n')
            stage = 'waiting for command prompt after login'
            _read_until(connection, PROMPT, deadline)
            try:
                stage = 'sending spot request'
                connection.settimeout(_remaining(deadline))
                connection.sendall(b'show/dx/10\r\n')
                stage = 'waiting for spot response'
                response = _read_until(connection, PROMPT, deadline)
            finally:
                try:
                    connection.settimeout(_remaining(deadline))
                    connection.sendall(b'bye\r\n')
                except OSError:
                    pass  # The socket is closed even if the server has disconnected.
            stage = 'closing connection'
    except OSError as error:
        DEBUG_LOG.debug('DX spots fetch failed at %s:%d while %s: %s: %s',
                        *cluster, stage, type(error).__name__, error)
        raise
    spots = []
    for line in response.splitlines():
        match = SPOT.match(line)
        if match:
            frequency, station, comment = match.groups()
            modes = {mode.upper() for mode in MODE.findall(SPOTTER.sub(b'', comment))}
            mode = next(iter(modes), b'').decode('ascii') if len(modes) <= 1 else None
            spots.append((station.decode('ascii').upper(), frequency.decode('ascii'), mode))
    return spots[:10]


def control(root, language, call, read_key, tune, region, read_status, select_mode):
    chat_int.show_response(chat_int.label(root, language, 'l449', 'Seeking spots'))
    call = call.strip().upper()
    if not re.fullmatch(r'(?=[A-Z0-9/]*[0-9])(?=[A-Z0-9/]*[A-Z])[A-Z0-9]+(?:/[A-Z0-9]+)*', call):
        chat_int.show_response(hints.get_hint(root, language, 'm016'))
        return
    def load_spots():
        for cluster, timeout, hint in ATTEMPTS:
            chat_int.show_response(hints.get_hint(root, language, hint))
            try:
                latest = fetch(call, cluster, timeout)
            except OSError:
                continue
            if not latest:
                chat_int.show_response(hints.get_hint(root, language, 'm019'))
            return latest
        chat_int.show_response(hints.get_hint(root, language, 'm018'))
        chat_int.show_response(hints.get_hint(root, language, 'm025'))
        return []

    spots = load_spots()
    if not spots:
        return

    try:
        cw_ranges = region_plan.load(root, region).get('cw_ranges_hz', ())
    except (OSError, ValueError, KeyError):
        cw_ranges = ()
    index = 0

    def selected_frequency():
        _, frequency_khz, _ = spots[index]
        frequency = format(Decimal(frequency_khz) / 1000, 'f')
        if '.' in frequency:
            frequency = frequency.rstrip('0').rstrip('.')
        return frequency

    def suggested_mode(frequency):
        mhz = Decimal(frequency)
        mode = FT_MODES_BY_DIAL.get(mhz)
        if not mode and any(low <= mhz * 1_000_000 < high for low, high in cw_ranges):
            return 'CW'
        return mode

    def announce():
        station, _, mode = spots[index]
        frequency = selected_frequency()
        if language in {'de', 'es', 'pl'}:
            frequency = frequency.replace('.', ',')
        message = f'{index + 1}/{len(spots)}. {station}, {frequency} MHz'
        if mode:
            message += ', ' + hints.get_hint(root, language, 'm020', mode=mode)
        elif mode == '':
            suggested = suggested_mode(selected_frequency())
            if suggested:
                message += ', ' + hints.get_hint(root, language, 'm021', mode=suggested)
        chat_int.show_response(message)

    announce()
    pending_key = None
    while True:
        try:
            key = (pending_key or read_key()).casefold()
            pending_key = None
        except (EOFError, KeyboardInterrupt):
            return
        if key == 'q':
            chat_int.show_done(root, language)
            return
        if key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h078'))
        elif key in ('\r', '\n'):
            frequency = selected_frequency()
            mode = spots[index][2]
            chat_int.show_response(tune(frequency, suggested_mode(frequency) if mode == '' else mode))
        elif key == 'w':
            chat_int.show_response(read_status())
        elif key == 'm':
            pending_key = select_mode()
        elif key == 'r':
            latest = load_spots()
            if latest:
                spots = latest
                index = 0
                announce()
        elif key in {'.', ','}:
            index = min(len(spots) - 1, max(0, index + (1 if key == '.' else -1)))
            announce()
