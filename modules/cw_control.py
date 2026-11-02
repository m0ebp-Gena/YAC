"""CW menu and live, verified settings driven by model capability files."""
import json
import logging
import re
import sys

from modules import chat_int, help_int

LOG = logging.getLogger('yac')


class Unavailable(ValueError):
    """A shared radio control is not available in the current mode."""


class Settings:
    def __init__(self, yac, root, radio, name):
        self.yac, self.radio, self.name = yac, radio, name
        path = root / radio.radio_id_path / 'cw.json'
        self.spec = json.loads(path.read_text(encoding='utf-8')).get(name) if path.is_file() else None

    def check_mode(self, spec):
        if spec.get('allowed_modes'):
            mode = self.yac._current_mode_code(self.radio)
            if mode is None:
                raise ValueError('CW control mode unreadable')
            if str(mode) not in spec['allowed_modes']:
                raise Unavailable('CW control unavailable in this mode')

    def read_value(self, spec):
        self.check_mode(spec)
        if self.radio.protocol == 'CAT':
            response = self.yac._cat_exchange(self.radio, spec['read']).strip()
            match = re.fullmatch(spec['pattern'], response)
            if match is None or match[1] not in spec['values']:
                raise ValueError('CW state unreadable')
            return match[1]
        command = bytes.fromhex(spec['command'])
        if len(command) == 2:
            response = self.yac._civ_exchange(self.radio, command[0], command[1])
            data = self.yac._civ_response_data(response, self.radio.civ_address, command[0], command[1])
        else:
            response = self.yac._civ_send(self.radio, command[0], command[1:])
            data = self.yac._civ_response_data(response, self.radio.civ_address, command[0])
            if data is None or not data.startswith(command[1:]):
                raise ValueError('CW menu response mismatch')
            data = data[len(command) - 1:]
        if data is None or data.hex().upper() not in spec['values']:
            raise ValueError('CW state unreadable')
        return data.hex().upper()

    def write_value(self, spec, value):
        self.check_mode(spec)
        if self.radio.protocol == 'CAT':
            self.yac._cat_exchange(self.radio, spec['set'].format(value=value))
        else:
            command = bytes.fromhex(spec['command'])
            response = self.yac._civ_send(self.radio, command[0], command[1:] + bytes.fromhex(value))
            ack = bytes([0xfe, 0xfe, 0xe0, self.radio.civ_address, 0xfb, 0xfd])
            if ack not in response:
                raise ValueError('CW change rejected')
        if self.read_value(spec) != value:
            raise ValueError('CW change readback mismatch')

    def read(self):
        value = self.read_value(self.spec)
        if self.spec.get('type') and value != '0':
            return self.spec['type']['values'][self.read_value(self.spec['type'])]
        return self.spec['values'][value]

    def change(self, direction):
        current = self.read()  # Reflect front-panel changes before selecting.
        choices = self.spec['choices']
        target = choices[(choices.index(current) + direction) % len(choices)]
        if self.spec.get('type'):
            if target == 'off':
                self.write_value(self.spec, '0')
            else:
                kind = self.spec['type']
                value = next(v for v, state in kind['values'].items() if state == target)
                # Read and confirm the type before enabling Break-in.
                if self.read_value(kind) != value:
                    self.write_value(kind, value)
                if current == 'off':
                    self.write_value(self.spec, '1')
        else:
            value = next(v for v, state in self.spec['values'].items() if state == target)
            self.write_value(self.spec, value)
        actual = self.read()
        if actual != target:
            raise ValueError('CW combined-state readback mismatch')
        return actual


class Delay(Settings):
    """Ordered numeric adjustment with clamped endpoints and no defaults."""
    def change(self, direction):
        if self.spec.get('presets'):
            current = self.read_value(self.spec)
            presets = self.spec['presets']
            candidates = [value for value in presets
                          if (int(value) - int(current)) * direction > 0]
            target = (candidates[0] if direction > 0 else candidates[-1]) if candidates else current
            if target != current:
                self.write_value(self.spec, target)
            return self.spec['values'][target]
        current = self.read()
        choices = self.spec['choices']
        index = max(0, min(len(choices) - 1, choices.index(current) + direction))
        target = choices[index]
        if target != current:
            value = (self.spec['write_values'][target] if self.spec.get('write_values') else
                     next(v for v, setting in self.spec['values'].items() if setting == target))
            self.write_value(self.spec, value)
            if self.read() != target:
                raise ValueError('CW delay readback mismatch')
        return target


def adjustment(yac, root, radio, language, name, read_key, watch):
    key_letter = {'break_in': 'b', 'internal_keyer': 'i', 'delay': 'd', 'pitch': 'p', 'volume': 'v'}[name]
    title = {'break_in': 'l413', 'internal_keyer': 'l414', 'delay': 'l419', 'pitch': 'l424', 'volume': 'l425'}[name]
    state_tokens = {'off': 'l415', 'on': 'l416', 'semi': 'l417', 'full': 'l418'}
    label = lambda token: yac._read_label(root, language, token, '')
    def announce(state):
        if name in ('pitch', 'volume'):
            chat_int.show_response(label(title).format(value=state))
        elif name == 'delay':
            if backend.spec.get('presets'):
                chat_int.show_response(label(backend.spec['label']).format(value=state))
            else:
                chat_int.show_response(label(title).format(value=state, unit=label(backend.spec['unit'])))
        else:
            chat_int.show_response(label(title).format(state=label(state_tokens[state])))
    def error():
        LOG.debug('CW setting or change unconfirmed', exc_info=True)
        chat_int.show_response(yac._radio_error(root, radio, language))
    try:
        backend = (Delay if name in ('delay', 'pitch', 'volume') else Settings)(yac, root, radio, name)
        if backend.spec is None:
            chat_int.show_response(label('l129'))
            return None
        if backend.spec.get('entry_mode'):
            current_mode = yac._current_mode_code(radio)
            if current_mode is None:
                raise ValueError('CW volume entry mode unreadable')
            if watch.lost:
                return 'w'
            if str(current_mode) not in backend.spec['allowed_modes']:
                target_mode = backend.spec['entry_mode']
                if not yac._set_mode(radio, target_mode):
                    raise ValueError('CW volume entry mode change unconfirmed')
                chat_int.show_response(yac._mode_name(radio, target_mode))
        announce(backend.read())
    except Unavailable:
        chat_int.show_response(label('l129'))
        return None
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
            topic = {'break_in': 'h043', 'internal_keyer': 'h044', 'delay': 'h045', 'pitch': 'h047', 'volume': 'h048'}[name]
            chat_int.show_response(help_int.get_help(root, language, topic))
        elif key in (key_letter, '.', ','):
            try:
                announce(backend.read() if name in ('delay', 'pitch', 'volume') and key == key_letter
                         else backend.change(-1 if key == ',' else 1))
            except Unavailable:
                chat_int.show_response(label('l129'))
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                error()
        elif key:
            return key


def speed_entry(yac, root, radio, language, read_key, watch):
    """Two ASCII digits; h/q are immediate commands, never entry data."""
    from modules import name_call_sel
    label = lambda token: yac._read_label(root, language, token, '')
    def announce(value):
        chat_int.show_response(label('l422').format(value=value))
    def error():
        LOG.debug('CW speed read/change unconfirmed', exc_info=True)
        chat_int.show_response(yac._radio_error(root, radio, language))
    try:
        backend = Settings(yac, root, radio, 'speed')
        if backend.spec is None:
            chat_int.show_response(label('l129'))
            return None
        announce(backend.read())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        error()
        return None
    chat_int.show_response(label('l423'))
    chat_int.finish_response()
    buffer = []
    drawn = 0
    while True:
        try:
            key = read_key().casefold()
        except (EOFError, KeyboardInterrupt):
            print()
            chat_int.show_done(root, language)
            return None
        except (OSError, RuntimeError):
            print()
            return None
        if watch.lost:
            print()
            return key or 'w'
        if key in ('q', '\x03', '\x04'):
            print()
            chat_int.show_done(root, language)
            return None
        if key == 'h':
            print()
            chat_int.show_response(help_int.get_help(root, language, 'h046'))
            chat_int.finish_response()
            drawn = 0
        elif key in ('\r', '\n', 'enter'):
            print()
            if not buffer:
                chat_int.show_response(label('l355'))
                return None
            value = str(int(''.join(buffer)))
            native = backend.spec['write_values'].get(value)
            if native is None:
                chat_int.show_response(label('l356'))
                return None
            try:
                backend.write_value(backend.spec, native)
                announce(backend.read())
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                error()
            return None
        elif key in ('\b', '\x7f', 'backspace', 'delete'):
            if buffer:
                buffer.pop()
        elif len(key) == 1 and key in '0123456789' and len(buffer) < 2:
            buffer.append(key)
        elif key:
            print()
            chat_int.show_response(label('l356'))
            return None
        drawn = name_call_sel._draw_input(buffer, len(buffer), drawn)


def control(yac, root, radio, language, read_key, watch):
    chat_int.show_response(yac._read_label(root, language, 'l412', 'CW'))
    pending = None
    while True:
        try:
            key = pending if pending is not None else read_key().casefold()
            pending = None
        except (EOFError, KeyboardInterrupt):
            chat_int.show_back(root, language)
            return None
        except (RuntimeError, OSError):
            return None
        if watch.lost:
            return key or 'w'
        if key == 'q':
            chat_int.show_back(root, language)
            return None
        if key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h042'))
        elif key == 'k':
            pending = speed_entry(yac, root, radio, language, read_key, watch)
        elif key in ('b', 'd', 'i', 'p', 'v'):
            pending = adjustment(yac, root, radio, language,
                                 {'b': 'break_in', 'd': 'delay', 'i': 'internal_keyer', 'p': 'pitch', 'v': 'volume'}[key], read_key, watch)
        elif key:
            chat_int.show_response(yac._read_label(root, language, 'l129', 'Not Supported'))
