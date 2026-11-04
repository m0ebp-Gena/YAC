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
        return None, 'l050'
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
                return None, 'l050'
            if str(mode) in {'1', '2'} and layout == '1':
                profile = dict(feature['width_profile'])
    if feature['kind'] == 'kenwood' and str(mode) in {'1', '2'}:
        data = _cat_value(yac, radio, 'DA;', r'DA([01]);')
        if data is None:
            return None, 'l050'
        menu = '029' if data == '1' else '028'
        command = f'EX{menu}0000'
        layout = _cat_value(yac, radio, command + ';', command + r'([12]);')
        if layout is None:
            return None, 'l050'
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
        return yac._radio_error(root, radio, language) if error == 'l050' else label(error)
    label_token = 'l082'
    bound = None
    if key in {'l', 'u'}:
        if not spec.get('low_read'):
            return label('l129')
        if key == 'l':
            high = settings.read(yac, radio, spec)
            if high not in spec['values']:
                return yac._radio_error(root, radio, language)
            bound = spec['values'][high]
            spec = dict(protocol='cat', read=spec['low_read'],
                        pattern=spec['low_pattern'], set='SL{value};',
                        values=spec['low_values'])
            label_token = 'l150'
        else:
            raw = _cat_value(yac, radio, spec['low_read'], spec['low_pattern'])
            if raw not in spec['low_values']:
                return yac._radio_error(root, radio, language)
            bound = spec['low_values'][raw]
            spec = {k: v for k, v in spec.items() if not k.startswith('low_')}
            label_token = 'l151'
    elif spec.get('low_read'):
        return adjust(yac, root, radio, language, direction, key='l')
    current = settings.read(yac, radio, spec)
    widths = spec['values']
    if current is not None and spec.get('apply'):
        current = next((value for value in widths
                        if value.casefold() == current.casefold()), None)
    # Default is symbolic; choose an explicit endpoint without guessing its width.
    is_default = 'default' in spec and current == spec['default']
    if is_default and not direction:
        return label('l147')
    if not is_default and current not in widths:
        return yac._radio_error(root, radio, language)
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
                return yac._radio_error(root, radio, language)
            if state == 'ENABLED':
                enabled.append(value)
        choices = enabled
    if not choices or (not is_default and current not in choices):
        return yac._radio_error(root, radio, language)
    if direction:
        if is_default:
            target = choices[0] if direction > 0 else choices[-1]
        else:
            index = choices.index(current)
            target = choices[max(0, min(len(choices) - 1, index + direction))]
        if target != current:
            if not settings._write(yac, radio, spec, target):
                return yac._radio_error(root, radio, language)
            if spec.get('apply'):
                yac._cat_exchange(radio, spec['apply'])
            actual = settings.read(yac, radio, spec)
            if actual is None or actual.casefold() != target.casefold():
                return yac._radio_error(root, radio, language)
            current = target
    if current == 'None':
        return label('l149')
    return label(label_token, value=widths[current])


def _help_topic(yac, root, radio, adjusting, contour_parameter='frequency'):
    """Select help from live capabilities without changing radio settings."""
    if adjusting is None:
        return 'h007'
    catalog = settings.catalog(root, radio, yac)
    if adjusting in {'p', 'l', 'u'}:
        feature = catalog.get('bandwidth')
        if not feature:
            return 'h064'
        profile, error = _profile(yac, radio, feature)
        if error:
            return 'h063' if error == 'l050' else 'h064'
        if adjusting in {'l', 'u'}:
            if not profile.get('low_read'):
                return 'h064'
            return 'h057' if adjusting == 'l' else 'h060'
        return 'h031'
    feature = catalog.get({'a': 'notch', 'n': 'notch', 'b': 'noise_blanker',
                           'r': 'noise_reduction', 'c': 'contour'}[adjusting])
    if adjusting in {'a', 'n'}:
        feature = (feature or {}).get(adjusting)
    if not feature:
        return 'h064'
    mode = yac._current_mode_code(radio)
    if mode is None:
        return 'h063'
    if str(mode).upper() not in feature['modes']:
        return 'h064'
    if adjusting == 'a':
        return 'h061' if feature.get('beat_cancel') else 'h054'
    if adjusting == 'r' and not feature.get('levels'):
        return 'h062' if feature.get('level', {}).get('following_time') else 'h059'
    if adjusting == 'r' and feature.get('levels'):
        side = str(yac._yaesu_vfo_side) if radio.model_id == '0840' else '0'
        spec = {k: v.replace('{side}', side) if isinstance(v, str) else v
                for k, v in feature['state'].items()}
        state = settings.read(yac, radio, spec)
        if state is None or str(state) not in spec['on_values'] + [spec['off']]:
            return 'h063'
        state = str(state)
        allowed = feature.get('on_by_mode', {}).get(str(mode).upper(), spec['on_values'])
        if state == spec['off']:
            memory_key = (radio.radio_id_path, side)
            state = getattr(radio, '_nr_memory', {}).get(memory_key, spec['on_values'][0])
            if state not in allowed:
                state = allowed[0]
        elif state not in allowed:
            return 'h064'
        level = feature['levels'].get(state, feature.get('level', {}))
        return 'h062' if level.get('following_time') else 'h059'
    if adjusting == 'c':
        return {'frequency': 'h056', 'level': 'h065', 'width': 'h066'}[contour_parameter]
    return {'b': 'h055', 'n': 'h058', 'r': 'h059'}[adjusting]


def control(yac, root, radio, language, call, read_key, watch):
    """q finishes any filter, q again leaves Filters; other commands return to top."""
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
            topic = _help_topic(yac, root, radio, adjusting, contour_parameter)
            chat_int.show_response(help_int.get_help(root, language, topic))
        elif key == 'v':
            chat_int.show_response(filter_review.next(yac, root, radio, language))
        elif key == 'b' and adjusting in {None, 'b'}:
            toggle = adjusting == 'b'
            adjusting = 'b'
            chat_int.show_response(noise_blanker.operate(yac, root, radio, language, toggle=toggle))
        elif key == 'r' and adjusting in {None, 'r'}:
            toggle = adjusting == 'r'
            adjusting = 'r'
            chat_int.show_response(noise_reduction.operate(yac, root, radio, language, toggle=toggle))
        elif key in {'a', 'n'} and adjusting in {None, key}:
            toggle = adjusting == key
            adjusting = key
            chat_int.show_response(notch_control.operate(yac, root, radio, language, key, toggle=toggle))
        elif key == 'c' and not adjusting:
            adjusting = 'c'
            contour_parameter = 'frequency'
            chat_int.show_response(contour_control.operate(yac, root, radio, language))
        elif adjusting == 'c' and key in {'c', 'l', 'w'}:
            toggle = key == 'c' and contour_parameter == 'frequency'
            contour_parameter = {'c': 'frequency', 'l': 'level', 'w': 'width'}[key]
            chat_int.show_response(contour_control.operate(yac, root, radio, language, toggle=toggle, parameter=contour_parameter))
        elif key == 'w' and adjusting == 'n':
            chat_int.show_response(notch_control.operate(yac, root, radio, language, 'n', width=True))
        elif key == 'p' and adjusting in {None, 'p', 'l', 'u'}:
            feature = settings.catalog(root, radio).get('bandwidth')
            spec, error = _profile(yac, radio, feature) if feature else (None, 'l129')
            if error:
                # Keep the same nesting as every other filter, even when
                # unsupported or unreadable. q must finish this control first.
                adjusting = adjusting or 'p'
                response = yac._radio_error(root, radio, language) if error == 'l050' else settings._label(yac, root, language, error)
            else:
                adjusting = ('u' if adjusting == 'l' else 'l') if spec and spec.get('low_read') else 'p'
                response = adjust(yac, root, radio, language, key=adjusting)
            chat_int.show_response(response)
        elif not adjusting and key in {'l', 'u'}:
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
