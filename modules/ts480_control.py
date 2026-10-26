"""Verified TS-480 operations; ID020 alone is not a model identification."""
import json
import re


def profile(yac, radio):
    path = yac.project_root() / radio.radio_id_path / 'identity.json'
    return json.loads(path.read_text(encoding='utf-8'))


def variant(yac, radio):
    if radio.protocol != 'CAT' or radio.model_id != '020':
        return None
    if hasattr(radio, '_ts480_variant'):
        return radio._ts480_variant
    spec = profile(yac, radio)
    match = re.fullmatch(spec['type_pattern'], yac._cat_exchange(radio, spec['type_read']).strip())
    if not match:
        return None
    value = match.group(1)
    radio._ts480_variant = value
    radio.model_name = spec['names'][value]
    return value


def vfo(yac, radio):
    spec = profile(yac, radio)
    match = re.fullmatch(spec['vfo_pattern'], yac._cat_exchange(radio, spec['vfo_read']).strip())
    return match.group(1) if match else None


def select_vfo(yac, root, radio, language):
    if variant(yac, radio) is None:
        return yac._read_label(root, language, 'l129', 'Not supported')
    current = vfo(yac, radio)
    if current is None:
        return yac._radio_error(root, radio, language)
    spec = profile(yac, radio)
    target = '1' if current == '0' else '0'
    # FR selects the receive VFO. Preserve FT (transmit VFO) and split state.
    yac._cat_exchange(radio, spec['vfo_set'].format(value=target))
    if vfo(yac, radio) != target:
        return yac._radio_error(root, radio, language)
    frequency = yac._current_frequency(root, radio)
    mode = yac._current_mode(radio)
    return f'VFO {"B" if target == "1" else "A"} {frequency} {mode}'


def offset_state(yac, radio):
    spec = profile(yac, radio)
    response = yac._cat_exchange(radio, spec['offset_read']).strip()
    match = re.fullmatch(spec['offset_pattern'], response)
    if not match or match.group(4) != '0':  # Scan changes RU/RD's meaning.
        return None
    return int(match.group(1)), match.group(2) == '1', match.group(3) == '1'


def zero_offsets(yac, radio):
    if variant(yac, radio) is None or offset_state(yac, radio) is None:
        return False
    yac._cat_exchange(radio, profile(yac, radio)['offset_clear'])
    state = offset_state(yac, radio)
    return state is not None and state[0] == 0


def offset(yac, root, radio, language, selection, direction):
    label = lambda token: yac._read_label(root, language, token, '')
    if variant(yac, radio) is None:
        return label('l129')
    current = offset_state(yac, radio)
    if current is None:
        return yac._radio_error(root, radio, language)
    spec = profile(yac, radio)
    if selection == 2:
        for command in (spec['offset_clear'], spec['receive_set'].format(value=0),
                        spec['transmit_set'].format(value=0)):
            yac._cat_exchange(radio, command)
        return label('l078') if offset_state(yac, radio) == (0, False, False) else yac._radio_error(root, radio, language)
    target = current[0] + direction * 10
    if not -9990 <= target <= 9990:
        prefix = yac._offset_label(root, language, selection)
        sign = label('l079' if current[0] > 0 else 'l080')
        return f'{prefix} {sign} {abs(current[0])} {label("l081")}' 
    command = spec['offset_up' if direction > 0 else 'offset_down']
    yac._cat_exchange(radio, command.format(value=10))
    after = offset_state(yac, radio)
    if after is None or after[0] != target:
        return yac._radio_error(root, radio, language)
    yac._cat_exchange(radio, spec['receive_set' if selection == 0 else 'transmit_set'].format(value=1))
    after = offset_state(yac, radio)
    if after is None or after[0] != target or not after[1 + selection]:
        return yac._radio_error(root, radio, language)
    prefix = yac._offset_label(root, language, selection)
    sign = label('l079' if target > 0 else 'l080') if target else ''
    return f'{prefix} {sign} {abs(target)} {label("l081")}'.replace('  ', ' ')
