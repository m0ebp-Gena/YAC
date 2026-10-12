"""Live AF gain, RF gain and FM squelch controls using model capabilities."""
import sys

from modules import chat_int, help_int, verify_settings as settings


def adjust(yac, root, radio, language, key, direction=0):
    features = settings.catalog(root, radio)
    name = 'af_gain'
    if key == 'r':
        mode = yac._current_mode_code(radio)
        if mode is None:
            return settings._label(yac, root, language, 'l143')
        name = ('squelch' if str(mode).upper() in
                features.get('rf_gain', {}).get('squelch_modes', []) else 'rf_gain')
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
        target = max(spec['minimum'], min(spec['maximum'], current + direction * spec['step']))
        if target != current:
            value = f'{target:04d}' if spec.get('encoding') == 'bcd' else f'{target:03d}'
            if not settings._write(yac, radio, spec, value):
                return settings._label(yac, root, language, 'l131')
            actual = settings.read(yac, radio, spec)
            if actual is None or int(actual) != target:
                return settings._label(yac, root, language, 'l131')
            current = target
    percent = round((current - spec['minimum']) * 100 / (spec['maximum'] - spec['minimum']))
    return settings._label(yac, root, language, spec['label'], value=percent)


def control(yac, root, radio, language, key, call, read_key, watch):
    chat_int.show_response(adjust(yac, root, radio, language, key))
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
                                         1 if pressed == yac.UP_KEY else -1))
        elif pressed == 'h':
            chat_int.show_request(call, pressed)
            chat_int.show_response(help_int.get_help(root, language, 'h005'))
        elif pressed == 'q':
            chat_int.show_request(call, pressed)
            return None
        else:
            return pressed
