"""Live AF gain, RF gain and FM squelch controls using model capabilities."""
import sys

from modules import chat_int, help_int, verify_settings as settings

GAIN_STEPS = {'af_gain': 6, 'rf_gain': 5}
GAIN_HELP = {'af_gain': 'h005', 'rf_gain': 'h069', 'squelch': 'h070'}


def _feature(yac, root, radio, key):
    features = settings.catalog(root, radio, yac)
    if key != 'r':
        return 'af_gain', features
    if 'rf_gain' not in features:
        return 'rf_gain', features
    mode = yac._current_mode_code(radio)
    if mode is None:
        return None, features
    name = ('squelch' if str(mode).upper() in
            features['rf_gain'].get('squelch_modes', []) else 'rf_gain')
    return name, features


def _step_value(value):
    if len(value) <= 3 and value.isascii() and value.isdecimal():
        number = int(value)
        if 1 <= number <= 100:
            return number
    return None


def adjust(yac, root, radio, language, key, direction=0, gain_steps=None):
    name, features = _feature(yac, root, radio, key)
    if name is None:
        return settings._label(yac, root, language, 'l143')
    original = features.get(name)
    if original is None:
        return settings._label(yac, root, language, 'l129')
    spec = {k: v.replace('{side}', str(yac._yaesu_vfo_side))
            if isinstance(v, str) else v for k, v in original.items()}
    current = settings.read(yac, radio, spec)
    if current is None:
        return settings._label(yac, root, language, 'l143')
    current = int(current)
    if direction:
        step = spec['step']
        if gain_steps is not None and name in gain_steps:
            span = spec['maximum'] - spec['minimum']
            step = max(1, round(span * gain_steps[name] / 100))
        target = max(spec['minimum'], min(spec['maximum'], current + direction * step))
        if target != current:
            value = f'{target:04d}' if spec.get('encoding') == 'bcd' else f'{target:03d}'
            if not settings._write(yac, radio, spec, value):
                return yac._radio_error(root, radio, language)
            actual = settings.read(yac, radio, spec)
            if actual is None or int(actual) != target:
                return yac._radio_error(root, radio, language)
            current = target
    percent = round((current - spec['minimum']) * 100 / (spec['maximum'] - spec['minimum']))
    return settings._label(yac, root, language, spec['label'], value=percent)


def _edit_step(yac, root, radio, language, key, gain_steps, watch):
    name, features = _feature(yac, root, radio, key)
    if name is None:
        chat_int.show_response(settings._label(yac, root, language, 'l143'))
        return
    if name not in gain_steps or name not in features:
        chat_int.show_response(settings._label(yac, root, language, 'l129'))
        return
    prompt = chat_int.label(root, language, 'l432', 'Step {value}?')
    chat_int.finish_response()
    try:
        entered = input(prompt.format(value=gain_steps[name]) + ' ').strip()
    except (EOFError, KeyboardInterrupt):
        print()
        entered = ''
    if watch.lost:
        return
    if not entered or entered.casefold() == 'q':
        chat_int.show_response(settings._label(yac, root, language, 'l355'))
        return
    value = _step_value(entered)
    if value is None:
        chat_int.show_response(settings._label(yac, root, language, 'l356'))
        return
    yac._set_yac_value(root / 'yac.ini', f'{name}_step', str(value))
    gain_steps[name] = value
    result = chat_int.label(root, language, 'l433', 'Step {value}')
    chat_int.show_response(result.format(value=value))


def control(yac, root, radio, language, key, call, read_key, watch):
    chat_int.show_response(adjust(yac, root, radio, language, key))
    config = yac._read_settings(root / 'yac.ini')
    gain_steps = {name: _step_value(config.get(f'{name}_step', '')) or default
                  for name, default in GAIN_STEPS.items()}
    while True:
        try:
            pressed = read_key()
        except (RuntimeError, OSError) as error:
            print(f'\n{error}', file=sys.stderr)
            return None
        if watch.lost:
            return pressed or 'w'
        pressed = pressed.casefold()
        if not pressed:
            continue
        if pressed in {yac.UP_KEY, yac.DOWN_KEY}:
            chat_int.show_request(call, pressed)
            chat_int.show_response(adjust(yac, root, radio, language, key,
                                         1 if pressed == yac.UP_KEY else -1, gain_steps))
        elif pressed == 's':
            chat_int.show_request(call, pressed)
            _edit_step(yac, root, radio, language, key, gain_steps, watch)
        elif pressed == 'h':
            chat_int.show_request(call, pressed)
            name, features = _feature(yac, root, radio, key)
            if name is None:
                chat_int.show_response(settings._label(yac, root, language, 'l143'))
            elif name not in features:
                chat_int.show_response(settings._label(yac, root, language, 'l129'))
            else:
                chat_int.show_response(help_int.get_help(root, language, GAIN_HELP[name]))
        elif pressed == 'q':
            chat_int.show_done(root, language)
            chat_int.show_request(call, pressed)
            return None
        else:
            return pressed
