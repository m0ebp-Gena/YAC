"""Noise Reduction toggle and mode-specific level/time adjustment."""
from modules import verify_settings as settings


def operate(yac, root, radio, language, *, toggle=False, direction=0):
    label = lambda token, **values: settings._label(yac, root, language, token, **values)
    feature = settings.catalog(root, radio, yac).get('noise_reduction')
    if feature is None:
        return label('l129')
    mode = yac._current_mode_code(radio)
    if mode is None:
        return yac._radio_error(root, radio, language)
    if str(mode).upper() not in feature['modes']:
        return label('l129')
    side = str(yac._yaesu_vfo_side) if radio.model_id == '0840' else '0'
    expand = lambda spec: {k: v.replace('{side}', side) if isinstance(v, str) else v
                           for k, v in spec.items()}
    state_spec = expand(feature['state'])
    current = settings.read(yac, radio, state_spec)
    state = str(current) if current is not None else None
    if state not in state_spec['on_values'] + [state_spec['off']]:
        return yac._radio_error(root, radio, language)
    if not hasattr(radio, '_nr_memory'):
        radio._nr_memory = {}
    memory = radio._nr_memory
    memory_key = (radio.radio_id_path, side)
    enabled = state != state_spec['off']
    allowed_on = feature.get('on_by_mode', {}).get(str(mode).upper(), state_spec['on_values'])
    if enabled and state not in allowed_on:
        return label('l129')
    if enabled:
        memory[memory_key] = state
    if toggle:
        target = state_spec['off'] if enabled else memory.get(memory_key, state_spec['on_values'][0])
        if not enabled and target not in allowed_on:
            target = allowed_on[0]
        if not settings._write(yac, radio, state_spec, target):
            return yac._radio_error(root, radio, language)
        actual = settings.read(yac, radio, state_spec)
        if actual is None or str(actual) != target:
            return yac._radio_error(root, radio, language)
        token = 'l161' if target == state_spec['off'] else feature.get('on_labels', {}).get(target, 'l160')
        return label(token)
    if not enabled:
        return label('l161')
    level_spec = feature.get('levels', {}).get(state, feature.get('level'))
    if level_spec is None:
        return label('l053')
    level_spec = expand(level_spec)
    combined = feature.get('combined', False)
    current_level = int(current) if combined else settings.read(yac, radio, level_spec)
    if current_level is None:
        return yac._radio_error(root, radio, language)
    value = int(current_level)
    if not level_spec['minimum'] <= value <= level_spec['maximum']:
        return yac._radio_error(root, radio, language)
    target = max(level_spec['minimum'], min(level_spec['maximum'],
                 value + direction * level_spec['step']))
    if target != value:
        digits = 4 if level_spec.get('encoding') == 'bcd' else level_spec.get('digits', 2)
        payload = f'{target:0{digits}d}'
        if not settings._write(yac, radio, level_spec, payload):
            return yac._radio_error(root, radio, language)
        actual = settings.read(yac, radio, level_spec)
        if actual is None or int(actual) != target:
            return yac._radio_error(root, radio, language)
        value = int(actual)
        if combined:
            memory[memory_key] = f'{value:0{digits}d}'
    if level_spec.get('following_time'):
        return label('l170', value=(value + 1) * 2)
    if value == level_spec.get('auto'):
        return label('l169')
    if level_spec.get('percent'):
        return label('l166', value=round(value * 100 / level_spec['maximum']))
    return label('l162', value=value)
