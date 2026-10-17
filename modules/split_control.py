"""Split and FM repeater setup with native readback and rollback.

No cached VFO identity is used. This module never starts transmission.
"""
import json
import re
import sys
from decimal import Decimal, InvalidOperation

from modules import chat_int, help_int


class Unavailable(Exception):
    pass


def band(hz):
    for name, low, high in [('10m', 28000000, 29700000), ('6m', 50000000, 54000000),
                             ('2m', 144000000, 148000000), ('70cm', 420000000, 450000000),
                             ('23cm', 1240000000, 1300000000)]:
        if low <= hz <= high:
            return name
    return None


def mhz(hz):
    return format(Decimal(hz) / 1000000, 'f').rstrip('0').rstrip('.') if hz % 1000000 else str(hz // 1000000)


def parse(entered, fm):
    pattern = r'[+-]?\d+' if fm else r'\d+(?:\.\d{1,6})?'
    if not re.fullmatch(pattern, entered.strip(), re.ASCII):
        raise ValueError
    try:
        value = int(Decimal(entered.strip()) * (1 if fm else 1000000))
    except (InvalidOperation, ValueError):
        raise ValueError from None
    if not value:
        raise ValueError
    return value


class Radio:
    def __init__(self, yac, root, radio):
        self.yac, self.radio = yac, radio
        path = root / radio.radio_id_path / 'split.json'
        if not path.exists():
            raise Unavailable
        self.spec = json.loads(path.read_text(encoding='utf-8'))
        self.yaesu = self.spec['protocol'] == 'cat'

    def cat(self, command, pattern):
        answer = self.yac._cat_exchange(self.radio, command)
        match = re.fullmatch(pattern, answer.strip())
        if not match:
            raise Unavailable
        return match.group(1)

    def civ(self, command, sub=None):
        answer = self.yac._civ_exchange(self.radio, command, sub)
        data = self.yac._civ_response_data(answer, self.radio.civ_address, command, sub)
        if data is None:
            raise Unavailable
        return data

    def read(self, field):
        if self.yaesu:
            query, pattern, _ = self.fields[field]
            return self.cat(query, pattern)
        command, sub = self.fields[field]
        return self.civ(command, sub)

    def write(self, field, value):
        if self.yaesu:
            _, _, setter = self.fields[field]
            if field == 'txside':
                value_set = self.spec['tx_set'][int(value)]
            else:
                value_set = value
            self.yac._cat_exchange(self.radio, setter.format(value=value_set))
        else:
            command, sub = self.fields[field]
            # Offset uses separate read/write commands; all other fields share one.
            command = 0x0D if field == 'offset' else command
            payload = (bytes([sub]) if sub is not None else b'') + value
            answer = self.yac._civ_send(self.radio, command, payload)
            ack = bytes([254, 254, 224, self.radio.civ_address, 251, 253])
            if ack not in answer:
                return False
        return self.read(field) == value

    def frequency(self, field):
        value = self.read(field)
        if self.yaesu:
            return int(value)
        if len(value) != 5 or any(b >> 4 > 9 or b & 15 > 9 for b in value):
            raise Unavailable
        return int(value[::-1].hex())

    def encode_frequency(self, hz):
        return f'{hz:09d}' if self.yaesu else bytes.fromhex(f'{hz:010d}')[::-1]

    def prepare(self, *, reporting=False):
        if self.yaesu:
            side = int(self.cat('VS;', r'VS([01]);'))
            # FTX-1's local control target must match the radio's RX selection.
            if not reporting and self.spec.get('main_sub') and side != self.yac._yaesu_vfo_side:
                raise Unavailable
            other = 1 - side
            self.fields = {
                'split': ('ST;', r'ST([01]);', 'ST{value};'),
                'txside': ('FT;', r'FT([01]);', 'FT{value};'),
                'rx': (f'F{"AB"[side]};', rf'F{"AB"[side]}(\d{{9}});', f'F{"AB"[side]}{{value}};'),
                'tx': (f'F{"AB"[other]};', rf'F{"AB"[other]}(\d{{9}});', f'F{"AB"[other]}{{value}};'),
                'rxmode': (f'MD{side};', rf'MD{side}([0-9A-F]);', f'MD{side}{{value}};'),
                'txmode': (f'MD{other};', rf'MD{other}([0-9A-F]);', f'MD{other}{{value}};'),
                'shift': (f'OS{side};', rf'OS{side}([0-3]);', f'OS{side}{{value}};'),
            }
            self.side, self.other = side, other
        else:
            self.fields = {'split': (15, None), 'rx': (37, 0), 'tx': (37, 1),
                           'rxmode': (38, 0), 'txmode': (38, 1), 'offset': (12, None)}
        self.rx = self.frequency('rx')
        self.rxmode = self.read('rxmode')
        if self.yaesu:
            self.fm = self.rxmode in {'4', 'B'}
        else:
            if len(self.rxmode) != 3:
                raise Unavailable
            self.fm = self.rxmode[0] == 5
        self.state = self.read('split')
        valid = {'0', '1'} if self.yaesu else {b'\x00', b'\x01', b'\x11', b'\x12'}
        if self.state not in valid:
            raise Unavailable
        self.on = self.state in {'1', b'\x01', b'\x11', b'\x12'}
        if self.fm and self.yaesu:
            self.shift = self.read('shift')
            # Explicit l also lets a user leave automatic repeater shift.
            self.on = self.on or self.shift != '0'
        return self

    def check_context(self):
        if self.yaesu:
            if self.cat('VS;', r'VS([01]);') != str(self.side):
                raise Unavailable
            # IF/OI expose memory mode and RX/TX clarifiers. Refuse rather
            # than announce base frequencies while a clarifier offsets RF.
            for side in ([self.side] if self.fm else [self.side, self.other]):
                prefix = 'IF' if side == 0 else 'OI'
                digits = 5 if self.spec.get('main_sub') else 3
                response = self.yac._cat_exchange(self.radio, prefix + ';').strip()
                match = re.fullmatch(prefix + rf'.{{{digits}}}\d{{9}}[+-]\d{{4}}([01])([01])[0-9A-FHI]([0-5])[0-5]\d{{2}}[0-3];', response)
                if not match or match.groups() != ('0', '0', '0'):
                    raise Unavailable
        else:
            # Access to the unselected VFO rejects restricted memory/DR and
            # IC-9700 satellite contexts, including during repeater setup.
            self.frequency('tx')
            if len(self.read('txmode')) != 3:
                raise Unavailable
            for sub in (1, 2):
                if self.yac._icom_clarifier_enabled(self.radio, sub) is not False:
                    raise Unavailable

    def off(self):
        changes = [('split', '0' if self.yaesu else b'\x00')]
        if self.fm and self.yaesu:
            changes.append(('shift', '0'))
        return self.apply(changes)

    def apply(self, changes, verify=None):
        old = {key: self.read(key) for key, _ in changes}
        attempted = []
        try:
            for key, value in changes:
                attempted.append(key)
                if not self.write(key, value):
                    raise Unavailable
            if verify is not None and not verify():
                raise Unavailable
            return True
        except (Unavailable, OSError, RuntimeError):
            # Disable before recovering frequencies/routing. Never restore On
            # unless every changed field was recovered and verified.
            restored = False
            try:
                stopped = self.write('split', '0' if self.yaesu else b'\x00')
                if self.fm and self.yaesu:
                    stopped = self.write('shift', '0') and stopped
                if stopped:
                    restored = True
                    for key in reversed(attempted):
                        if key != 'split':
                            restored = self.write(key, old[key]) and restored
                    if restored and 'split' in old:
                        restored = self.write('split', old['split'])
            except (Unavailable, OSError, RuntimeError):
                restored = False
            self.restored = restored
            return False

    def enable(self, target):
        tx = self.rx + target if self.fm else target
        if not self.spec['minimum_hz'] <= tx <= self.spec['maximum_hz'] or tx == self.rx:
            raise ValueError
        if self.frequency('rx') != self.rx or self.read('rxmode') != self.rxmode or self.read('split') != self.state:
            raise Unavailable
        self.check_context()
        if self.fm:
            if band(tx) != band(self.rx) or band(self.rx) is None:
                raise ValueError
            if self.yaesu:
                if self.read('shift') != self.shift:
                    raise Unavailable
                menu = self.spec['offsets'].get(band(self.rx))
                if not menu:
                    raise Unavailable
                prefix, unit, step, maximum = menu
                magnitude = abs(target)
                if magnitude % step or magnitude // unit > maximum:
                    raise ValueError
                self.fields['offset'] = (prefix + ';', prefix + r'(\d{4});', prefix + '{value};')
                changes = [('offset', f'{magnitude // unit:04d}'),
                           ('shift', '1' if target > 0 else '2')]
            else:
                if abs(target) % 100 or abs(target) // 100 > 999999:
                    raise ValueError
                offset = bytes.fromhex(f'{abs(target) // 100:06d}')[::-1]
                changes = [('offset', offset), ('split', b'\x12' if target > 0 else b'\x11')]
        else:
            # Probe the other VFO before any write; restricted contexts reject it.
            self.frequency('tx')
            other_mode = self.read('txmode')
            if not self.yaesu and len(other_mode) != 3:
                raise Unavailable
            changes = [('tx', self.encode_frequency(tx)), ('txmode', self.rxmode)]
            if self.yaesu:
                changes.append(('txside', str(self.other)))
            changes.append(('split', '1' if self.yaesu else b'\x01'))
        def verify():
            return (self.frequency('rx') == self.rx and self.read('rxmode') == self.rxmode
                    and (not self.yaesu or self.cat('VS;', r'VS([01]);') == str(self.side)))
        success = self.apply(changes, verify)
        return success, tx


def report(yac, root, radio, language):
    """Read split routing and native repeater shift without sending setters."""
    label = lambda token, **values: yac._read_label(root, language, token, '').format(**values)
    try:
        backend = Radio(yac, root, radio).prepare(reporting=True)
        if not backend.on:
            return label('l258')
        backend.check_context()
        repeater = False
        if backend.yaesu:
            if backend.state == '1':
                tx = backend.rx if backend.read('txside') == str(backend.side) else backend.frequency('tx')
                if backend.fm and backend.shift != '0':
                    raise Unavailable
            else:
                if backend.shift not in {'1', '2'}:
                    raise Unavailable  # ARS cannot be inferred from a saved default.
                menu = backend.spec['offsets'].get(band(backend.rx))
                if not menu:
                    raise Unavailable
                prefix, unit, step, maximum = menu
                raw = backend.cat(prefix + ';', prefix + r'(\d{4});')
                if int(raw) > maximum or int(raw) * unit % step:
                    raise Unavailable
                tx = backend.rx + int(raw) * unit * (1 if backend.shift == '1' else -1)
                repeater = True
        elif backend.state == b'\x01':
            tx = backend.frequency('tx')
        elif backend.state in {b'\x11', b'\x12'}:
            raw = backend.read('offset')
            if len(raw) != 3 or any(b >> 4 > 9 or b & 15 > 9 for b in raw):
                raise Unavailable
            tx = backend.rx + int(raw[::-1].hex()) * 100 * (1 if backend.state == b'\x12' else -1)
            repeater = True
        else:
            raise Unavailable
        if not backend.spec['minimum_hz'] <= tx <= backend.spec['maximum_hz']:
            raise Unavailable
        from modules import tone_status
        tone = tone_status.report(yac, root, radio, language,
                                  side=getattr(backend, 'side', None), mode='FM' if backend.fm else 'USB')
        if backend.fm and not repeater:
            # External two-VFO FM split may have different tone settings on
            # each VFO; selected-VFO tone is not authoritative for TX.
            tone = label('l247')
        result = label('l254' if repeater else 'l250', rx=mhz(backend.rx), tx=mhz(tx))
        return result + (', ' + tone if tone else '')
    except (Unavailable, OSError, RuntimeError, ValueError):
        return label('l259')


def control(yac, root, radio, language):
    label = lambda token, **values: yac._read_label(root, language, token, '').format(**values)
    def show(token, **values):
        chat_int.show_response(label(token, **values))
    try:
        backend = Radio(yac, root, radio).prepare()
        if backend.on:
            if backend.off():
                show('l251', rx=mhz(backend.rx), tx=mhz(backend.rx))
            else:
                show('l256' if getattr(backend, 'restored', False) else 'l257')
            return
        entered = None
        if backend.fm:
            values = yac._read_settings(root / 'yac.ini')
            entered = values.get('repeater_offset_' + (band(backend.rx) or '') + '_hz', '').strip()
        while not entered:
            chat_int.finish_response()
            sys.stdout.write(label('l253' if backend.fm else 'l252') + ' ')
            sys.stdout.flush()
            try:
                entered = input().strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not entered or entered.casefold() == 'q':
                chat_int.show_back(root, language)
                return
            if entered.casefold() == 'h':
                chat_int.show_response(help_int.get_help(root, language, 'h011'))
                entered = None
        value = parse(entered, backend.fm)
        ok, tx = backend.enable(value)
        if ok:
            show('l250' if not backend.fm else 'l254', rx=mhz(backend.rx), tx=mhz(tx))
        else:
            show('l256' if getattr(backend, 'restored', False) else 'l257')
    except ValueError:
        show('l255')
    except (Unavailable, OSError, RuntimeError):
        show('l249')
