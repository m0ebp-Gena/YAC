"""User-operated processor settings with verified cancellation; never keys TX."""
import logging
import re
from time import monotonic

from modules import chat_int, help_int, mic_gain, verify_settings as settings

LOG = logging.getLogger('yac')


def profile(yac, radio):
    base = mic_gain.profile(yac, radio)
    if base is None:
        return None
    family = base['family']
    if family == 'icom':
        return {'family': family, 'status': {'protocol': 'civ', 'read': '16 44', 'set': '16 44'},
                'level': {'protocol': 'civ', 'read': '14 0E', 'set': '14 0E', 'encoding': 'bcd'},
                'maximum': 255, 'step': 26}
    if family == 'yaesu':
        return {'family': family,
                'status': {'protocol': 'cat', 'read': 'PR0;', 'set': 'PR0{value};', 'pattern': r'PR0([12]);'},
                'level': {'protocol': 'cat', 'read': 'PL;', 'set': 'PL{value};', 'pattern': r'PL(\d{3});', 'minimum': 0, 'maximum': 100},
                'maximum': 100, 'step': 1}
    return {'family': family, 'maximum': 100, 'step': 1,
            'status': {'protocol': 'cat', 'read': 'PR;', 'set': 'PR{value};', 'pattern': r'PR([01]);'}}


def read(yac, radio, spec):
    raw = settings.read(yac, radio, spec['status'])
    states = {'00': False, '01': True} if spec['family'] == 'icom' else (
        {'1': False, '2': True} if spec['family'] == 'yaesu' else {'0': False, '1': True})
    if raw not in states:
        return None
    if spec['family'] == 'kenwood':
        match = re.search(r'PL(\d{3})(\d{3});', yac._cat_exchange(radio, 'PL;'))
        levels = tuple(int(v) for v in match.groups()) if match else None
    else:
        value = settings.read(yac, radio, spec['level'])
        levels = (int(value),) if value is not None else None
    if levels is None or any(v > spec['maximum'] for v in levels):
        return None
    return states[raw], levels


def set_status(yac, radio, spec, enabled):
    value = ('01' if enabled else '00') if spec['family'] == 'icom' else (
        ('2' if enabled else '1') if spec['family'] == 'yaesu' else ('1' if enabled else '0'))
    return settings._write(yac, radio, spec['status'], value)


def set_levels(yac, radio, spec, levels):
    if spec['family'] == 'kenwood':
        yac._cat_exchange(radio, 'PL' + ''.join(f'{v:03d}' for v in levels) + ';')
        return True
    value = f'{levels[0]:04d}' if spec['family'] == 'icom' else f'{levels[0]:03d}'
    return settings._write(yac, radio, spec['level'], value)


def context(yac, root, radio):
    mode = yac._current_mode(radio)
    frequency = yac._current_frequency(root, radio)
    if mode is None or frequency is None:
        return None
    receiver = getattr(yac, '_yaesu_vfo_side', 0)
    if radio.protocol == 'CI-V':
        receiver = getattr(yac, '_ICOM_VFO_SELECTION', {}).get((radio.port, radio.civ_address))
    elif radio.manufacturer_key == 'kenwood':
        match = re.search(r'FR([012]);', yac._cat_exchange(radio, 'FR;'))
        if not match:
            return None
        receiver = match[1]
    return mode, frequency, receiver


def supported_mode(spec, mode):
    return mode in ({'LSB', 'USB', 'AM', 'FM'} if spec['family'] == 'kenwood' else {'LSB', 'USB'})


def restore(yac, root, radio, spec, original, entry_context):
    """Do not send setters if already unchanged, context differs or TX is active."""
    if context(yac, root, radio) != entry_context or mic_gain.tx_state(yac, radio, spec) is not False:
        return False
    current = read(yac, radio, spec)
    if current is None:
        return False
    if current == original:
        return True
    # Disable before restoring levels, then restore the original switch state.
    if current[0] and not set_status(yac, radio, spec, False):
        return False
    if current[1] != original[1] and not set_levels(yac, radio, spec, original[1]):
        return False
    if not set_status(yac, radio, spec, original[0]):
        return False
    return read(yac, radio, spec) == original


def compression(yac, radio, spec):
    if spec['family'] == 'icom':
        return settings.read(yac, radio, {'protocol': 'civ', 'read': '15 14', 'encoding': 'bcd'})
    if spec['family'] == 'yaesu':
        match = re.search(r'RM3(\d{3})000;', yac._cat_exchange(radio, 'RM3;'))
        value = int(match[1]) if match else None
        return value if value is not None and value <= 255 else None
    match = re.search(r'RM2(\d{4});', yac._cat_exchange(radio, 'RM;'))
    value = int(match[1]) if match else None
    limit = 10 if radio.model_id == '020' else 30
    return value if value is not None and value <= limit else None


def control(yac, root, radio, language, read_key, watch):
    def say(token, **values):
        chat_int.show_response(settings._label(yac, root, language, token, **values))
    spec = profile(yac, radio)
    if spec is None:
        say('l129')
        return
    entry_context = context(yac, root, radio)
    if entry_context is None or not supported_mode(spec, entry_context[0]):
        say('l240')
        return
    original = read(yac, radio, spec)
    if original is None:
        say('l239')
        return
    if mic_gain.tx_state(yac, radio, spec) is not False:
        say('l217')
        return
    # Zero while Off may conceal a retained Yaesu level, which cannot be undone.
    pending = getattr(radio, '_processor_pending', None)
    if not pending and spec['family'] == 'yaesu' and original[1] == (0,):
        say('l244')
        return
    if pending:
        if pending['context'] != entry_context:
            say('l242')
            return
        original = pending['original']
        say('l242')
    selected = 0
    peak = mic_gain.Peak()
    monitoring = False
    next_sample = 0
    changed_context = False
    def describe(state):
        enabled, levels = state
        say('l232' if enabled else 'l233')
        value = round(levels[selected] * 10 / 255, 1) if spec['family'] == 'icom' else levels[selected]
        say(('l235' if selected else 'l234') if spec['family'] == 'kenwood' else 'l236', value=value)
    def safe():
        return (not watch.lost and context(yac, root, radio) == entry_context
                and mic_gain.tx_state(yac, radio, spec) is False)
    def tick():
        nonlocal next_sample, changed_context
        if not monitoring or watch.lost or changed_context or monotonic() < next_sample:
            return
        next_sample = monotonic() + 0.3
        if context(yac, root, radio) != entry_context:
            changed_context = True
            return
        tx = mic_gain.tx_state(yac, radio, spec)
        use_alc = spec['family'] == 'kenwood' and selected == 1
        meter = (mic_gain.alc(yac, radio, spec) if use_alc else compression(yac, radio, spec)) if tx else None
        result = peak.sample(tx, meter)
        if result == 'unknown':
            say('l239')
        elif result is not None:
            say('l213' if use_alc else 'l238', value=result)
    describe(read(yac, radio, spec) or original)
    say('l237')
    try:
        while not watch.lost:
            key = read_key(idle_callback=tick).casefold() if monitoring else read_key().casefold()
            if watch.lost or changed_context:
                break
            if key in {'q', 'n', '\x03', '\x04'}:
                if key == 'q':
                    radio._processor_pending = None
                    say('l243')
                    return
                if not getattr(radio, '_processor_pending', None) or restore(yac, root, radio, spec, original, entry_context):
                    radio._processor_pending = None
                    say('l241')
                    return
                say('l242')
                continue
            if key == 'h':
                chat_int.show_response(help_int.get_help(root, language, 'h010'))
            elif key == ' ':
                say('l209')
                while True:
                    answer = read_key().casefold()
                    if watch.lost:
                        break
                    if answer == 'n':
                        if not getattr(radio, '_processor_pending', None) or restore(yac, root, radio, spec, original, entry_context):
                            radio._processor_pending = None
                            say('l241')
                            return
                        say('l242')
                        break
                    if answer == 'q':
                        break
                    if answer == 'h':
                        chat_int.show_response(help_int.get_help(root, language, 'h010'))
                    if answer == ' ':
                        monitoring = True
                        peak.reset()
                        say('l245')
                        break
            elif key in {'i', 'o'} and spec['family'] == 'kenwood':
                selected = 0 if key == 'i' else 1
                peak.reset()
                state = read(yac, radio, spec)
                if state is None:
                    say('l239')
                else:
                    describe(state)
            elif key == 'v':
                state = read(yac, radio, spec)
                say('l239') if state is None else describe(state)
            elif key == 'e' or key in {yac.UP_KEY, yac.DOWN_KEY}:
                if not safe():
                    say('l246')
                    continue
                state = read(yac, radio, spec)
                if state is None:
                    say('l239')
                    continue
                if key != 'e' and not state[0]:
                    say('l233')
                    continue
                target = state
                if key == 'e':
                    target = (not state[0], state[1])
                else:
                    levels = list(state[1])
                    minimum = 1 if spec['family'] == 'yaesu' else 0
                    levels[selected] = max(minimum, min(spec['maximum'], levels[selected] + (spec['step'] if key == yac.UP_KEY else -spec['step'])))
                    target = (state[0], tuple(levels))
                if target == state:
                    describe(state)
                    continue
                radio._processor_pending = {'original': original, 'context': entry_context}
                LOG.debug('Processor original=%s context=%s target=%s', original, entry_context, target)
                ok = set_status(yac, radio, spec, target[0]) if key == 'e' else set_levels(yac, radio, spec, target[1])
                actual = read(yac, radio, spec)
                verified = actual is not None and (actual[0] == target[0] if key == 'e' and spec['family'] == 'yaesu' else actual == target)
                if not ok or not verified:
                    say('l131')
                else:
                    peak.reset()
                    describe(actual)
    except (EOFError, KeyboardInterrupt, RuntimeError, OSError):
        pass
    finally:
        # Interrupted sessions attempt undo only if the original context is safe.
        if getattr(radio, '_processor_pending', None):
            try:
                if not watch.lost and restore(yac, root, radio, spec, original, entry_context):
                    radio._processor_pending = None
                    say('l241')
                else:
                    say('l242')
            except (OSError, RuntimeError):
                say('l242')
        chat_int.show_done(root, language)
