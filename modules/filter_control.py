"""Live receive bandwidth with model/mode-specific wire values and readback."""
import re
import sys

from modules import chat_int, help_int, noise_blanker, noise_reduction, notch_control, contour_control, filter_verify, verify_settings as settings


def _cat_value(yac, radio, command, pattern):
    match = re.fullmatch(pattern, yac._cat_exchange(radio, command).strip())
    return match.group(1) if match else None


def _profile(yac, radio, feature):
    mode = yac._current_mode_code(radio)
    if mode is None:
        return None, 'l083'
    profile = feature['modes'].get(str(mode).upper())
    if profile is None:
        return None, 'l129'
    profile = dict(feature['profiles'][profile])
    if feature['kind'] == 'ts480_qmx':
        # Both radios answer ID020. A successful QMX-only menu read identifies
        # the variant; no TS-480 setters are sent until its menu responds.
        qmx = _cat_value(yac, radio, 'MMCW|CW passband;', r'MM([^;]+);')
        if qmx is not None:
            profile = feature['qmx_modes'].get(str(mode))
            if profile is None:
                return None, 'l129'
            profile = dict(feature['profiles'][profile])
        else:
            layout = _cat_value(yac, radio, 'EX0450000;', r'EX0450000([01]);')
            if layout is None:
                return None, 'l083'
            if str(mode) in {'1', '2'} and layout == '1':
                profile = dict(feature['width_profile'])
    if feature['kind'] == 'kenwood' and str(mode) in {'1', '2'}:
        data = _cat_value(yac, radio, 'DA;', r'DA([01]);')
        if data is None:
            return None, 'l083'
        menu = '029' if data == '1' else '028'
        command = f'EX{menu}0000'
        layout = _cat_value(yac, radio, command + ';', command + r'([12]);')
        if layout is None:
            return None, 'l083'
        if layout == '2':
            profile = dict(feature['width_profile'])
    side = str(yac._yaesu_vfo_side) if radio.model_id == '0840' else '0'
    profile = {k: v.replace('{side}', side) if isinstance(v, str) else v
               for k, v in profile.items()}
    return profile, None


def adjust(yac, root, radio, language, direction=0, key='p'):
    label = lambda token, **values: settings._label(yac, root, language, token, **values)
    feature = settings.catalog(root, radio).get('bandwidth')
    if feature is None:
        return label('l129')
    spec, error = _profile(yac, radio, feature)
    if error:
        return label(error)
    label_token = 'l082'
    bound = None
    if key in {'l', 'u'}:
        if not spec.get('low_read'):
            return label('l129')
        if key == 'l':
            high = settings.read(yac, radio, spec)
            if high not in spec['values']:
                return label('l083')
            bound = spec['values'][high]
            spec = dict(protocol='cat', read=spec['low_read'],
                        pattern=spec['low_pattern'], set='SL{value};',
                        values=spec['low_values'])
            label_token = 'l150'
        else:
            raw = _cat_value(yac, radio, spec['low_read'], spec['low_pattern'])
            if raw not in spec['low_values']:
                return label('l083')
            bound = spec['low_values'][raw]
            spec = {k: v for k, v in spec.items() if not k.startswith('low_')}
            label_token = 'l151'
    elif spec.get('low_read'):
        # Separate edge controls must not be disguised as a width adjustment.
        return label('l152')
    current = settings.read(yac, radio, spec)
    widths = spec['values']
    if current is not None and spec.get('apply'):
        current = next((value for value in widths
                        if value.casefold() == current.casefold()), None)
    # Default is a symbolic manufacturer setting, not a universal 2400 Hz.
    if 'default' in spec and current == spec['default']:
        return label('l148' if direction else 'l147')
    if current not in widths:
        return label('l083')
    choices = list(widths)
    if bound is not None:
        choices = [value for value in choices if
                   (widths[value] < bound if key == 'l' else widths[value] > bound)]
    if spec.get('enabled_read') and direction:
        enabled = []
        for index, value in enumerate(widths):
            if value == 'None':
                enabled.append(value)
                continue
            state = _cat_value(yac, radio, spec['enabled_read'].format(index=index),
                               r'MM(ENABLED|DISABLED);')
            if state is None:
                return label('l083')
            if state == 'ENABLED':
                enabled.append(value)
        choices = enabled
    if current not in choices:
        return label('l083')
    if direction:
        index = choices.index(current)
        target = choices[max(0, min(len(choices) - 1, index + direction))]
        if target != current:
            if not settings._write(yac, radio, spec, target):
                return label('l131')
            if spec.get('apply'):
                yac._cat_exchange(radio, spec['apply'])
            actual = settings.read(yac, radio, spec)
            if actual is None or actual.casefold() != target.casefold():
                return label('l131')
            current = target
    if current == 'None':
        return label('l149')
    return label(label_token, value=widths[current])


def control(yac, root, radio, language, call, read_key, watch):
    """q leaves width, q again leaves Filters; other commands return to top."""
    chat_int.show_response(settings._label(yac, root, language, 'l065'))
    adjusting = None
    contour_parameter = "frequency"
    filter_review = filter_verify.Review()
    while True:
        try:
            key = read_key()
        except (RuntimeError, OSError) as error:
            print(f'\n{error}', file=sys.stderr)
            return None
        if watch.lost:
            return key or 'w'
        key = key.casefold()
        if not key:
            continue
        if key != 'v':
            filter_review.reset()
        if key == 'q':
            if not adjusting:
                chat_int.show_back(root, language)
                return None
            chat_int.show_done(root, language)
            adjusting = None
        elif key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h007'))
        elif key == 'v':
            chat_int.show_response(filter_review.next(yac, root, radio, language))
        elif key == 'b' and adjusting in {None, 'b'}:
            adjusting = 'b'
            chat_int.show_response(noise_blanker.operate(yac, root, radio, language, toggle=True))
        elif key == 'r' and adjusting in {None, 'r'}:
            adjusting = 'r'
            chat_int.show_response(noise_reduction.operate(yac, root, radio, language, toggle=True))
        elif key in {'a', 'n'} and adjusting in {None, key}:
            adjusting = key
            chat_int.show_response(notch_control.operate(yac, root, radio, language, key, toggle=True))
        elif key == 'c' and not adjusting:
            adjusting = 'c'
            contour_parameter = 'frequency'
            chat_int.show_response(contour_control.operate(yac, root, radio, language, toggle=True))
        elif adjusting == 'c' and key in {'c', 'l', 'w'}:
            toggle = key == 'c' and contour_parameter == 'frequency'
            contour_parameter = {'c': 'frequency', 'l': 'level', 'w': 'width'}[key]
            chat_int.show_response(contour_control.operate(yac, root, radio, language, toggle=toggle, parameter=contour_parameter))
        elif key == 'w' and adjusting == 'n':
            chat_int.show_response(notch_control.operate(yac, root, radio, language, 'n', width=True))
        elif not adjusting and key in {'p', 'l', 'u'}:
            adjusting = key
            chat_int.show_response(adjust(yac, root, radio, language, key=key))
        elif adjusting and key in {yac.UP_KEY, yac.DOWN_KEY}:
            direction = 1 if key == yac.UP_KEY else -1
            if adjusting in {'b', 'r'}:
                module = noise_blanker if adjusting == 'b' else noise_reduction
                response = module.operate(yac, root, radio, language, direction=direction)
            elif adjusting == 'c':
                response = contour_control.operate(yac, root, radio, language, parameter=contour_parameter, direction=direction)
            elif adjusting in {'a', 'n'}:
                response = notch_control.operate(yac, root, radio, language, adjusting, direction=direction)
            else:
                response = adjust(yac, root, radio, language, direction, key=adjusting)
            chat_int.show_response(response)
        else:
            return key
