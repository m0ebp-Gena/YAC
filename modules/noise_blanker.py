"""Read-before-toggle noise blanker and verified live level adjustment."""
from modules import verify_settings as settings


def _memory(radio):
    if not hasattr(radio, '_nb_memory'):
        radio._nb_memory = {}
    return radio._nb_memory


def operate(yac, root, radio, language, *, toggle=False, direction=0):
    label = lambda token, **values: settings._label(yac, root, language, token, **values)
    feature = settings.catalog(root, radio, yac).get('noise_blanker')
    if feature is None:
        return label('l129')
    mode = yac._current_mode_code(radio)
    if mode is None:
        return yac._radio_error(root, radio, language)
    if str(mode).upper() not in feature['modes']:
        return label('l129')
    side = str(yac._yaesu_vfo_side) if radio.model_id == '0840' else '0'
    specs = {name: {k: v.replace('{side}', side) if isinstance(v, str) else v
                    for k, v in feature[name].items()} for name in ('state', 'level')}
    state_spec, level_spec = specs['state'], specs['level']
    current = settings.read(yac, radio, state_spec)
    if current is None:
        return yac._radio_error(root, radio, language)
    state = str(current)
    combined = feature.get('combined', False)
    valid = state_spec['on_values'] + [state_spec['off']]
    if state not in valid:
        return yac._radio_error(root, radio, language)
    enabled = state != state_spec['off']
    memory = _memory(radio)
    memory_key = (radio.radio_id_path, side)
    if enabled:
        memory[memory_key] = state
    if toggle:
        target = state_spec['off'] if enabled else memory.get(memory_key, state_spec['on_values'][0])
        if not settings._write(yac, radio, state_spec, target):
            return yac._radio_error(root, radio, language)
        actual = settings.read(yac, radio, state_spec)
        if actual is None or str(actual) != target:
            return yac._radio_error(root, radio, language)
        return label('l154' if target == state_spec['off'] else 'l153')
    if not enabled:
        return label('l154')
    current_level = int(current) if combined else settings.read(yac, radio, level_spec)
    if current_level is None:
        return yac._radio_error(root, radio, language)
    value = int(current_level)
    if not level_spec['minimum'] <= value <= level_spec['maximum']:
        return yac._radio_error(root, radio, language)
    target = max(level_spec['minimum'], min(level_spec['maximum'],
                 value + direction * level_spec['step']))
    if target != value:
        payload = f'{target:04d}' if level_spec.get('encoding') == 'bcd' else f'{target:03d}'
        if not settings._write(yac, radio, level_spec, payload):
            return yac._radio_error(root, radio, language)
        actual = settings.read(yac, radio, level_spec)
        if actual is None or int(actual) != target:
            return yac._radio_error(root, radio, language)
        value = int(actual)
        if combined:
            memory[memory_key] = f'{value:03d}'
    if level_spec.get('percent'):
        return label('l159', value=round(value * 100 / level_spec['maximum']))
    return label('l155', value=value)
