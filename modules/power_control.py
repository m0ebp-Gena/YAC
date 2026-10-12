"""Editable output power, using each model's native command and units."""
import re
import sys

from modules import chat_int, help_int, verify_settings as settings


def prepare(yac, root, radio):
    original = settings.catalog(root, radio).get('power')
    if not original or 'set' not in original:
        return None
    spec = dict(original)
    if spec.get('encoding') == 'bcd':
        scale = spec['watts_at_full_scale']
        if spec.get('band_watts'):
            frequency = yac._current_frequency(root, radio)
            if frequency is None:
                return None
            mhz = float(frequency)
            scale = next((item['watts'] for item in spec['band_watts']
                          if item['minimum_mhz'] <= mhz <= item['maximum_mhz']), None)
            if scale is None:
                return None
        spec['watts_at_full_scale'] = scale
        spec['maximum'] = scale
        if spec.get('supply_read'):
            supply = settings.read(yac, radio, spec['supply_read'])
            if supply not in spec['supply_maximum']:
                return None
            spec['maximum'] = spec['supply_maximum'][supply]
        mode = yac._current_mode_code(radio)
        if mode is None:
            return None
        if str(mode) == spec.get('am_mode'):
            spec['maximum'] = min(spec['maximum'], scale * spec['am_fraction'])
    if spec.get('selector_pattern'):
        response = yac._cat_exchange(radio, spec['read'])
        match = re.search(spec['selector_pattern'], response)
        if not match:
            return None
        selector = match.group(1)
        spec['set'] = spec['set'].replace('{selector}', selector)
        spec['maximum'] = spec['selector_maximum'][selector]
    if settings.read(yac, radio, spec) is None:
        return None
    return spec


def set_value(yac, radio, spec, entered):
    """Return a label for an error, or None on a verified successful change."""
    entered = entered.strip()
    if not entered:
        return None  # An empty edit cancels without writing.
    if not entered.isascii() or not entered.isdecimal():
        return 'l146'
    value = int(entered)
    if not spec['input_minimum'] <= value <= spec['maximum']:
        return 'l146'
    native = round(value * 255 / spec['watts_at_full_scale']) if spec.get('encoding') == 'bcd' else value
    payload = f'{native:04d}' if spec.get('encoding') == 'bcd' else f'{native:03d}'
    if not settings._write(yac, radio, spec, payload):
        return 'l131'
    actual = settings.read(yac, radio, spec)
    return None if actual is not None and int(actual) == native else 'l131'


def edit(yac, root, radio, language):
    spec = prepare(yac, root, radio)
    if spec is None:
        chat_int.show_response(settings._label(yac, root, language, 'l127'))
        return
    while True:
        prompt = settings._label(yac, root, language, 'l144',
                                 minimum=spec['input_minimum'], maximum=spec['maximum'])
        chat_int.finish_response()
        sys.stdout.write(prompt + ' ')
        sys.stdout.flush()
        try:
            entered = input()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if entered.strip().casefold() == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h006'))
            # Re-read limits after help: supply, band or mode may have changed.
            spec = prepare(yac, root, radio)
            if spec is None:
                chat_int.show_response(settings._label(yac, root, language, 'l127'))
                return
            continue
        # Check live limits again before sending a value entered during a change.
        if entered.strip():
            spec = prepare(yac, root, radio)
            if spec is None:
                chat_int.show_response(settings._label(yac, root, language, 'l127'))
                return
        error = set_value(yac, radio, spec, entered)
        if not error:
            return
        chat_int.show_response(settings._label(yac, root, language, error))
