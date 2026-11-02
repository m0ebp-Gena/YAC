"""Live radio lock selection; native commands and capabilities live in model data."""
import json
import logging
import re
from modules import chat_int, help_int, ts480_control

LOG = logging.getLogger('yac')


class Unknown(ValueError):
    pass


class Locks:
    def __init__(self, yac, root, radio):
        self.yac, self.radio = yac, radio
        path = root / radio.radio_id_path / 'lock.json'
        self.spec = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
        if self.spec:
            if self.spec['protocol'] != radio.protocol:
                raise ValueError('Lock protocol mismatch')
            if self.spec.get('identity_required') and ts480_control.variant(yac, radio) is None:
                self.spec = None

    @property
    def choices(self):
        return ('off', 'dial', 'panel') if self.spec.get('type_command') else ('off', 'on')

    def civ_read(self, command):
        command = bytes.fromhex(command)
        if len(command) == 2:
            response = self.yac._civ_exchange(self.radio, command[0], command[1])
        else:
            response = self.yac._civ_send(self.radio, command[0], command[1:])
        data = self.yac._civ_response_data(response, self.radio.civ_address, command[0])
        if data is None or data[:-1] != command[1:] or data[-1:] not in (b'\x00', b'\x01'):
            raise Unknown('Unconfirmed lock state')
        return data[-1]

    def civ_write(self, command, value):
        command = bytes.fromhex(command)
        response = self.yac._civ_send(self.radio, command[0], command[1:] + bytes([value]))
        ack = bytes([0xfe, 0xfe, 0xe0, self.radio.civ_address, 0xfb, 0xfd])
        if ack not in response:
            raise Unknown('Lock command rejected')

    def read(self):
        if self.spec['protocol'] == 'CAT':
            match = re.fullmatch(self.spec['pattern'], self.yac._cat_exchange(self.radio, self.spec['read']).strip())
            if match is None:
                raise Unknown('Unconfirmed lock state')
            return 'off' if all(c == '0' for c in match[1]) else 'on'
        enabled = self.civ_read(self.spec['command'])
        if self.spec.get('type_command'):
            scope = self.civ_read(self.spec['type_command'])
            return ('panel' if scope else 'dial') if enabled else 'off'
        return 'on' if enabled else 'off'

    def change(self, current, direction):
        choices = self.choices
        target = choices[(choices.index(current) + direction) % len(choices)]
        if self.spec['protocol'] == 'CAT':
            self.yac._cat_exchange(self.radio, self.spec['off' if target == 'off' else 'on'])
        elif target == 'off':
            self.civ_write(self.spec['command'], 0)
        else:
            if self.spec.get('type_command'):
                scope = int(target == 'panel')
                self.civ_write(self.spec['type_command'], scope)
                if self.civ_read(self.spec['type_command']) != scope:
                    raise Unknown('Lock type readback mismatch')
            if current == 'off':
                self.civ_write(self.spec['command'], 1)
        actual = self.read()
        if actual != target:
            raise Unknown('Lock readback mismatch')
        return actual


def control(yac, root, radio, language, read_key, watch):
    label = lambda token: yac._read_label(root, language, token, '')
    tokens = {'off': 'l404', 'on': 'l405', 'dial': 'l406', 'panel': 'l407'}
    def error():
        LOG.exception('Lock state or change unconfirmed')
        chat_int.show_response(yac._radio_error(root, radio, language))
    try:
        backend = Locks(yac, root, radio)
        if backend.spec is None:
            chat_int.show_response(label('l129'))
            return None
        chat_int.show_response(label(tokens[backend.read()]))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        error()
        return None
    while True:
        try:
            key = read_key().casefold()
        except (EOFError, KeyboardInterrupt):
            chat_int.show_done(root, language)
            return None
        except (RuntimeError, OSError):
            return None
        if watch.lost:
            return key or 'w'
        if key == 'q':
            chat_int.show_done(root, language)
            return None
        if key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h038'))
        elif key in ('k', '.', ','):
            try:
                state = backend.change(backend.read(), -1 if key == ',' else 1)
                chat_int.show_response(label(tokens[state]))
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                error()
        elif key:
            return key


def active_status(yac, root, radio, language):
    """Omit Off/unsupported; report an active native lock without changing it."""
    try:
        backend = Locks(yac, root, radio)
        if backend.spec is None:
            return ''
        state = backend.read()
        token = {'on': 'l405', 'dial': 'l406', 'panel': 'l407'}.get(state)
        return yac._read_label(root, language, token, '') if token else ''
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        LOG.debug('Lock status unavailable', exc_info=True)
        return yac._read_label(root, language, 'l411', '')
