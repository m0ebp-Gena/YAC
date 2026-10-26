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
    # Preparation selects ALC only when the read does not already include it.
    match = re.search(r'RM3(\d{4});', yac._cat_exchange(radio, 'RM;'))
    value = int(match[1]) if match else None
    maximum = 10 if radio.model_id == '020' else 30
    return value if value is not None and value <= maximum else None


def prepare_meter(yac, radio, spec):
    """Use ALC already returned, or select it while retaining a known meter."""
    if spec['family'] != 'kenwood':
        return None
    response = yac._cat_exchange(radio, 'RM;')
    readings = re.findall(r'RM([123])(\d{4});', response)
    maximum = 10 if radio.model_id == '020' else 30
    if any(meter == '3' and int(value) <= maximum for meter, value in readings):
        return None
    if len(readings) != 1:
        raise RuntimeError('Cannot determine meter selection')
    previous = readings[0][0]
    radio._yac_mic_meter_restore = previous
    yac._cat_exchange(radio, 'RM3;')
    if alc(yac, radio, spec) is None:
        raise RuntimeError('ALC meter selection was not confirmed')
    return previous


def restore_meter(yac, radio, spec):
    previous = getattr(radio, '_yac_mic_meter_restore', None)
    if previous is None:
        return True
    if tx_state(yac, radio, spec) is not False:
        return False
    yac._cat_exchange(radio, f'RM{previous};')
    readings = re.findall(r'RM([123])(\d{4});', yac._cat_exchange(radio, 'RM;'))
    if len(readings) != 1 or readings[0][0] != previous:
        return False
    del radio._yac_mic_meter_restore
    return True


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
            if watch.lost or key in {'n', 'q', '\x03', '\x04'}:
                return False
            if key == 'y':
                return True
            if key == 'h':
                chat_int.show_response(help_int.get_help(root, language, 'h008'))
                say(token)

    spec = profile(yac, radio)
    if spec is None:
        say('l129')
        return
    try:
        chat_int.show_response(help_int.get_help(root, language, 'h008'))
        if not choice('l007'):
            return
        mode = yac._current_mode(radio)
        if mode is None:
            chat_int.show_response(yac._radio_error(root, radio, language))
            return
        if mode not in {'LSB', 'USB', 'AM'} or (spec['family'] == 'kenwood' and mode == 'AM'):
            say('l129')
            return
        current = settings.read(yac, radio, spec)
        if current is None or tx_state(yac, radio, spec) is not False:
            say('l217')
            return
        try:
            if not restore_meter(yac, radio, spec):
                raise RuntimeError('Previous meter restoration pending')
            prepare_meter(yac, radio, spec)
        except (RuntimeError, OSError):
            chat_int.show_response(yac._radio_error(root, radio, language))
            return
        say('l211', value=round(int(current) * 100 / spec['maximum']))
        say('l212')
        peak = Peak()
        next_sample = 0
        changed_mode = False
        def tick():
            nonlocal next_sample, changed_mode
            if watch.lost or changed_mode or monotonic() < next_sample:
                return
            next_sample = monotonic() + 0.3
            actual_mode = yac._current_mode(radio)
            if actual_mode != mode:
                changed_mode = True
                if actual_mode is None:
                    chat_int.show_response(yac._radio_error(root, radio, language))
                else:
                    say('l001')
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
                actual_mode = yac._current_mode(radio)
                if actual_mode != mode:
                    if actual_mode is None:
                        chat_int.show_response(yac._radio_error(root, radio, language))
                    else:
                        say('l001')
                    break
                value = adjust(yac, radio, spec, 1 if key == yac.UP_KEY else -1)
                if value is None:
                    chat_int.show_response(yac._radio_error(root, radio, language))
                else:
                    peak.reset()
                    say('l211', value=round(value * 100 / spec['maximum']))
            elif key == 'v':
                current = settings.read(yac, radio, spec)
                if current is None:
                    chat_int.show_response(yac._radio_error(root, radio, language))
                else:
                    say('l211', value=round(int(current) * 100 / spec['maximum']))
            elif key == ' ':
                peak.reset()
                say('l215')
    except (EOFError, KeyboardInterrupt, RuntimeError, OSError):
        pass
    finally:
        if getattr(radio, '_yac_mic_meter_restore', None) is not None and not watch.lost:
            try:
                restored = restore_meter(yac, radio, spec)
            except (RuntimeError, OSError):
                restored = False
            if not restored:
                chat_int.show_response(yac._radio_error(root, radio, language))
        chat_int.show_done(root, language)
