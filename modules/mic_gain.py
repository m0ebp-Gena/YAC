"""User-operated microphone gain and sampled peak ALC; never keys TX."""
import re
from time import monotonic
import logging

from modules import chat_int, help_int, verify_settings as settings, ts480_control

LOG = logging.getLogger('yac')


def profile(yac, radio):
    if radio.protocol == 'CI-V' and radio.model_id.casefold() in {
            'ic-705', 'ic-7300', 'ic-7300mk2', 'ic-7600', 'ic-9700'}:
        return {'protocol': 'civ', 'read': '14 0B', 'set': '14 0B',
                'encoding': 'bcd', 'maximum': 255, 'step': 3, 'family': 'icom'}
    if radio.protocol == 'CAT' and radio.manufacturer_key == 'yaesu' and radio.model_id in {'0761', '0800', '0840'}:
        return {'protocol': 'cat', 'read': 'MG;', 'set': 'MG{value};',
                'pattern': r'MG(\d{3});', 'minimum': 0, 'maximum': 100,
                'step': 1, 'family': 'yaesu'}
    if radio.protocol == 'CAT' and radio.manufacturer_key == 'kenwood':
        if radio.model_id == '023' or (radio.model_id == '020' and ts480_control.variant(yac, radio) is not None):
            return {'protocol': 'cat', 'read': 'MG;', 'set': 'MG{value};',
                    'pattern': r'MG(\d{3});', 'minimum': 0, 'maximum': 100,
                    'step': 1, 'family': 'kenwood'}
    return None


def tx_state(yac, radio, spec):
    if spec['family'] == 'icom':
        response = yac._civ_exchange(radio, 0x1c, 0)
        data = yac._civ_response_data(response, radio.civ_address, 0x1c, 0)
        return data == b'\x01' if data in (b'\x00', b'\x01') else None
    if spec['family'] == 'yaesu':
        match = re.search(r'TX([012]);', yac._cat_exchange(radio, 'TX;'))
        return match[1] != '0' if match else None
    response = yac._cat_exchange(radio, 'IF;')
    match = re.search(r'IF([^;]+);', response)
    body = match[1] if match else ''
    return body[26] == '1' if len(body) == 35 and body[26] in '01' else None


def alc(yac, radio, spec):
    if spec['family'] == 'icom':
        return settings.read(yac, radio, {'protocol': 'civ', 'read': '15 13', 'encoding': 'bcd'})
    if spec['family'] == 'yaesu':
        match = re.search(r'RM4(\d{3})000;', yac._cat_exchange(radio, 'RM4;'))
        value = int(match[1]) if match else None
        return value if value is not None and value <= 255 else None
    # RM; only reads. In particular, do not send RM3; to select a meter.
    match = re.search(r'RM3(\d{4});', yac._cat_exchange(radio, 'RM;'))
    value = int(match[1]) if match else None
    maximum = 10 if radio.model_id == '020' else 30
    return value if value is not None and value <= maximum else None


def adjust(yac, radio, spec, direction):
    current = settings.read(yac, radio, spec)
    if current is None:
        return None
    current = int(current)
    target = max(0, min(spec['maximum'], current + direction * spec['step']))
    payload = f'{target:04d}' if spec.get('encoding') == 'bcd' else f'{target:03d}'
    if target != current and not settings._write(yac, radio, spec, payload):
        return None
    actual = settings.read(yac, radio, spec)
    LOG.debug('Mic gain requested=%s readback=%s', target, actual)
    return target if actual is not None and int(actual) == target else None


class Peak:
    """Collect sampled peaks, retaining a valid zero and rejecting partial reads."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.transmitting = False
        self.value = None
        self.failed = False

    def sample(self, transmitting, value):
        if transmitting is None:
            self.failed = True
            return None
        if transmitting:
            if not self.transmitting:
                self.value = None
                self.failed = False
            self.transmitting = True
            if value is None:
                self.failed = True
            else:
                self.value = max(self.value if self.value is not None else 0, value)
        elif self.transmitting:
            self.transmitting = False
            return 'unknown' if self.failed or self.value is None else self.value
        return None


def control(yac, root, radio, language, read_key, watch):
    def say(token, **values):
        chat_int.show_response(settings._label(yac, root, language, token, **values))

    def choice(token):
        say(token)
        while True:
            key = read_key().casefold()
            if watch.lost or key in {'q', '\x03', '\x04'}:
                return False
            if key == ' ':
                return True
            if key == 'h':
                chat_int.show_response(help_int.get_help(root, language, 'h008'))
                say(token)

    spec = profile(yac, radio)
    if spec is None:
        say('l129')
        return
    started = False
    try:
        if not choice('l209'):
            return
        mode = yac._current_mode(radio)
        if mode not in {'LSB', 'USB', 'AM'} or (spec['family'] == 'kenwood' and mode == 'AM'):
            say('l216')
            return
        current = settings.read(yac, radio, spec)
        if current is None or tx_state(yac, radio, spec) is not False:
            say('l217')
            return
        say('l211', value=round(int(current) * 100 / spec['maximum']))
        say('l212')
        started = True
        peak = Peak()
        next_sample = 0
        changed_mode = False
        def tick():
            nonlocal next_sample, changed_mode
            if watch.lost or changed_mode or monotonic() < next_sample:
                return
            next_sample = monotonic() + 0.3
            if yac._current_mode(radio) != mode:
                changed_mode = True
                say('l216')
                return
            transmitting = tx_state(yac, radio, spec)
            result = peak.sample(transmitting, alc(yac, radio, spec) if transmitting else None)
            if result == 'unknown':
                say('l214')
            elif result is not None:
                LOG.debug('Mic gain sampled peak ALC=%s model=%s mode=%s', result, radio.model_id, mode)
                say('l213', value=result)

        while not watch.lost:
            tick()
            if changed_mode:
                break
            key = read_key(idle_callback=tick).casefold()
            if watch.lost or changed_mode:
                break
            if key in {'q', '\x03', '\x04'}:
                break
            if key == 'h':
                chat_int.show_response(help_int.get_help(root, language, 'h008'))
            elif key in {yac.UP_KEY, yac.DOWN_KEY}:
                if tx_state(yac, radio, spec) is not False:
                    say('l217')
                    continue
                if yac._current_mode(radio) != mode:
                    say('l216')
                    break
                value = adjust(yac, radio, spec, 1 if key == yac.UP_KEY else -1)
                if value is None:
                    say('l131')
                else:
                    peak.reset()
                    say('l211', value=round(value * 100 / spec['maximum']))
            elif key == 'v':
                current = settings.read(yac, radio, spec)
                if current is None:
                    say('l214')
                else:
                    say('l211', value=round(int(current) * 100 / spec['maximum']))
            elif key == ' ':
                peak.reset()
                say('l215')
    except (EOFError, KeyboardInterrupt, RuntimeError, OSError):
        if not started:
            say('l220')
    finally:
        if started:
            say('l220')
        chat_int.show_done(root, language)
