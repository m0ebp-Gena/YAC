"""Native SWR transport and model data, separate from the measurement control."""
import json
import re

from modules import mic_gain, power_control, split_control, ts480_control
from modules import verify_settings as settings


class Unavailable(RuntimeError):
    pass


class Invalid(Unavailable):
    pass


class Unsupported(Unavailable):
    pass


def calibration(spec, raw):
    if not 0 <= raw <= spec['raw_maximum']:
        raise Unavailable('Invalid SWR meter value')
    if spec.get('bins'):
        for low, high, value in spec['bins']:
            if low <= raw <= high:
                return value, raw >= spec.get('over_from', spec['raw_maximum'] + 1)
        raise Unavailable('No calibrated reading')
    points = spec['calibration']
    if raw >= points[-1][0]:
        return points[-1][1], True
    if raw <= points[0][0]:
        return points[0][1], False
    for (a, x), (b, y) in zip(points, points[1:]):
        if a <= raw <= b:
            return x + (raw - a) * (y - x) / (b - a), False
    raise Unavailable('No calibrated reading')


class Radio:
    def __init__(self, yac, root, radio):
        self.yac, self.root, self.radio = yac, root, radio
        path = root / radio.radio_id_path / 'swr.json'
        if not path.is_file():
            raise Unsupported('No SWR profile')
        self.spec = json.loads(path.read_text(encoding='utf-8'))
        if self.spec.get('disabled'):
            raise Unsupported('SWR profile awaiting documented calibration')
        self.family = self.spec['family']
        if self.family == 'kenwood' and radio.model_id == '020':
            if ts480_control.variant(yac, radio) is None:
                raise Unsupported('Unidentified TS-480 or QMX')
        self.power = power_control.prepare(yac, root, radio)
        if self.power is None:
            raise Unavailable('Power setting unavailable')
        self.fields = dict(self.spec.get('fields', {}))
        self.fields['power'] = self.power
        self.side = None

    def cat(self, query, pattern):
        answer = self.yac._cat_exchange(self.radio, query).strip()
        match = re.fullmatch(pattern, answer)
        if not match:
            raise Unavailable('Unreadable ' + query)
        return match[1]

    def civ(self, command, sub):
        answer = self.yac._civ_exchange(self.radio, command, sub)
        data = self.yac._civ_response_data(answer, self.radio.civ_address, command, sub)
        if data is None:
            raise Unavailable('Unreadable CI-V value')
        return data

    def read(self, field):
        if field == 'mode' and self.family == 'icom':
            value = self.civ(0x26, 0)
            if len(value) != 3 or value[1] not in (0, 1) or value[2] not in (1, 2, 3):
                raise Unavailable('Unreadable mode/data/filter')
            return value
        if field == 'frequency' and self.family == 'icom':
            data = self.civ(0x25, 0)
            if len(data) != 5 or any(x >> 4 > 9 or x & 15 > 9 for x in data):
                raise Unavailable('Unreadable frequency')
            return int(data[::-1].hex())
        value = settings.read(self.yac, self.radio, self.fields[field])
        if value is None:
            raise Unavailable('Unreadable ' + field)
        return value

    def write(self, field, value):
        if self.family == 'icom' and field in {'mode', 'frequency'}:
            command = 0x26 if field == 'mode' else 0x25
            payload = value if field == 'mode' else self.yac._civ_frequency_bytes(value)
            answer = self.yac._civ_send(self.radio, command, b'\x00' + payload)
            if bytes((254, 254, 224, self.radio.civ_address, 251, 253)) not in answer:
                raise Unavailable('CI-V setter rejected')
        else:
            if field == 'frequency':
                value = str(value).zfill(self.spec['frequency_digits'])
            elif field == 'power':
                value = f'{int(value):04d}' if self.power.get('encoding') == 'bcd' else f'{int(value):03d}'
            if not settings._write(self.yac, self.radio, self.fields[field], value):
                raise Unavailable('Setter rejected: ' + field)
        actual = self.read(field)
        if field in {'power', 'frequency'}:
            equal = int(actual) == int(value)
        else:
            equal = actual == value
        if not equal:
            raise Unavailable('Readback failed: ' + field)

    def context(self):
        """SWR uses the displayed simplex VFO; never edits split or offsets."""
        if self.family in {'icom', 'yaesu'}:
            rig = split_control.Radio(self.yac, self.root, self.radio).prepare()
            # Both VFOs must be in readable VFO mode, without RIT/XIT. Using
            # both checks also covers a split TX VFO while RX happens to be FM.
            rig.fm = False
            rig.check_context()
            if rig.on:
                raise Invalid('Split/repeater operation')
            if rig.yaesu:
                if rig.read('txside') != str(rig.side) or rig.read('shift') != '0':
                    raise Invalid('TX selection or shift')
                side = rig.side
                if self.side is not None and self.side != side:
                    raise Invalid('VFO changed')
                self.side = side
                self.fields['mode'] = {'protocol': 'cat', 'read': f'MD{side};',
                    'pattern': rf'MD{side}([0-9A-F]);', 'set': f'MD{side}{{value}};'}
                prefix = 'FA' if side == 0 else 'FB'
                self.fields['frequency'] = {'protocol': 'cat', 'read': prefix + ';',
                    'pattern': prefix + r'(\d{9});', 'set': prefix + '{value};'}
            else:
                if rig.state != b'\x00':
                    raise Invalid('Repeater operation')
            return rig.rx
        rx = self.cat('FR;', r'FR([01]);')
        tx = self.cat('FT;', r'FT([01]);')
        info = self.cat('IF;', r'IF([^;]{35});')
        if rx != tx or info[21:23] != '00' or info[26] != '0' or info[29:31] != '00':
            raise Invalid('Split, scan, offsets or TX active')
        if self.side is not None and self.side != rx:
            raise Invalid('VFO changed')
        self.side = rx
        prefix = 'FA' if rx == '0' else 'FB'
        self.fields['frequency'] = {'protocol': 'cat', 'read': prefix + ';',
            'pattern': prefix + r'(\d{11});', 'set': prefix + '{value};'}
        return int(self.read('frequency'))

    def tx_state(self):
        return mic_gain.tx_state(self.yac, self.radio, {'family': self.family})

    def tx(self, on):
        # The caller records possible TX *before* the start write: a command
        # may take effect even if its ACK/readback subsequently disappears.
        if self.family == 'icom':
            answer = self.yac._civ_send(self.radio, 0x1c, bytes((0, int(on))))
            ack = bytes((254, 254, 224, self.radio.civ_address, 251, 253))
            if ack not in answer:
                raise Unavailable('TX/RX command rejected')
        else:
            command = ('TX1;' if on else 'TX0;') if self.family == 'yaesu' else ('TX0;' if on else 'RX;')
            self.yac._cat_exchange(self.radio, command)
        if self.tx_state() is not on:
            raise Unavailable('TX/RX not confirmed')

    def watts(self, hz):
        for item in self.spec.get('band_power', []):
            if item['minimum_hz'] <= hz < item['maximum_hz']:
                return item['watts']
        if self.spec.get('selector_power'):
            return self.spec['selector_power'][str(self.power['maximum'])]
        return self.spec['watts']

    def power_value(self, watts):
        # Prepare again *after* mode selection, as AM has separate limits.
        new = power_control.prepare(self.yac, self.root, self.radio)
        if new is None or new['set'] != self.power['set'] or watts > new['maximum']:
            raise Unavailable('Measurement power unavailable')
        return round(watts * 255 / new['watts_at_full_scale']) if new.get('encoding') == 'bcd' else watts

    def measurement_mode(self):
        return bytes.fromhex(self.spec['mode']) if self.family == 'icom' else self.spec['mode']

    def sample(self):
        if self.tx_state() is not True:
            raise Unavailable('No transmitter')
        if self.family == 'kenwood':
            answer = self.yac._cat_exchange(self.radio, 'RM;')
            readings = re.findall(r'RM1(\d{4});', answer)
            if len(readings) != 1:
                raise Unavailable('No SWR reading')
            raw = int(readings[0])
            # Native SWR dots do not prove RF. SM reports the PWR scale in TX.
            power = int(self.cat('SM0;', r'SM0(\d{4});'))
        else:
            power = int(self.read('rf'))
            raw = int(self.read('swr'))
        if power <= 0 or self.tx_state() is not True:
            raise Unavailable('No valid RF sample')
        if self.spec.get('rf_calibration'):
            percent, _ = calibration({'raw_maximum': 255,
                                     'calibration': self.spec['rf_calibration']}, power)
            watts = percent * self.power['watts_at_full_scale'] / 100
            required = self.spec.get('minimum_readback_watts', self.watts(self.context_hz))
            if watts < required:
                raise Unavailable('RF reading below manufacturer measurement power')
        return calibration(self.spec, raw)
