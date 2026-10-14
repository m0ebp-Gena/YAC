"""Auto/Manual Notch and TS-480 Beat Cancel with live readback."""
from modules import verify_settings as settings


def operate(yac, root, radio, language, key, *, toggle=False, direction=0, width=False):
    label = lambda token, **values: settings._label(yac, root, language, token, **values)
    feature = settings.catalog(root, radio, yac).get('notch')
    if feature is None or key not in feature:
        return label('l129')
    spec = feature[key]
    mode = yac._current_mode_code(radio)
    beat = spec.get('beat_cancel', False)
    unknown = 'l188' if beat else 'l181'
    failed = 'l189' if beat else 'l184'
    if mode is None:
        return label(unknown)
    if str(mode).upper() not in spec['modes']:
        return label('l129')
    side = str(yac._yaesu_vfo_side) if radio.model_id == '0840' else '0'
    expand = lambda value: {k: v.replace('{side}', side) if isinstance(v, str) else v
                            for k, v in value.items()}
    state_spec = expand(spec['state'])
    current = settings.read(yac, radio, state_spec)
    if current is None:
        return label(unknown)
    current = str(current)
    shared = spec.get('shared', False)
    if shared:
        if current not in {'00', '10', '20', '21'}:
            return label(unknown)
        enabled = current.startswith('1' if key == 'a' else '2')
    else:
        if current not in state_spec['on_values'] + [state_spec['off']]:
            return label(unknown)
        enabled = current != state_spec['off']
    if not hasattr(radio, '_notch_memory'):
        radio._notch_memory = {}
    memory = radio._notch_memory
    memory_key = (radio.radio_id_path, side)
    if shared and current.startswith('2'):
        memory[(memory_key, 'width')] = current[1]
    if beat and enabled:
        memory[(memory_key, 'beat')] = current
    off_label = 'l187' if beat else 'l172' if key == 'a' else 'l174'

    def description(state):
        if beat:
            return label({'0':'l187', '1':'l185', '2':'l186'}[state])
        return label('l171' if key == 'a' else 'l173')

    def write_verified(write_spec, target):
        return (settings._write(yac, radio, write_spec, target)
                and str(settings.read(yac, radio, write_spec)) == target)

    if toggle:
        if shared:
            target = '00' if enabled else '10' if key == 'a' else '2' + memory.get((memory_key, 'width'), '0')
        else:
            target = (state_spec['off'] if enabled else memory.get((memory_key, 'beat'),
                      state_spec['on_values'][0]) if beat else state_spec['on_values'][0])
        other_available = str(mode).upper() in spec.get('other_modes', [str(mode).upper()])
        other_spec = expand(spec['other']) if spec.get('other') and not enabled and other_available else None
        original_other = None
        if other_spec:
            original_other = settings.read(yac, radio, other_spec)
            if original_other not in {'00', '01'}:
                return label(unknown)
            if original_other == '01' and not write_verified(other_spec, '00'):
                return label(failed)
        if not write_verified(state_spec, target):
            if original_other == '01':
                write_verified(other_spec, '01')
            return label(failed)
        if other_spec and settings.read(yac, radio, other_spec) != '00':
            return label(failed)
        if enabled:
            return label(off_label)
        response = description(target)
        if shared and key == 'n':
            memory[(memory_key, 'width')] = target[1]
            response += ', ' + label('l180' if target[1] == '0' else 'l178')
        return response
    if not enabled:
        return label(off_label)
    if key == 'a':
        return description(current)  # Automatic filters have no manual position.
    if width:
        width_spec = expand(spec['width'])
        current_width = current[1] if shared else settings.read(yac, radio, width_spec)
        choices = width_spec['choices']
        if current_width not in choices:
            return label('l183')
        target = choices[(choices.index(current_width) + 1) % len(choices)]
        if shared:
            if not write_verified(state_spec, '2' + target):
                return label(failed)
            memory[(memory_key, 'width')] = target
        elif not write_verified(width_spec, target):
            return label(failed)
        return label(width_spec['labels'][target])
    position_spec = expand(spec['position'])
    value = settings.read(yac, radio, position_spec)
    if value is None:
        return label('l182')
    value = int(value)
    if not position_spec['minimum'] <= value <= position_spec['maximum']:
        return label('l182')
    target = max(position_spec['minimum'], min(position_spec['maximum'],
                 value + direction * position_spec['step']))
    if target != value:
        digits = 4 if position_spec.get('encoding') == 'bcd' else position_spec['digits']
        payload = f'{target:0{digits}d}'
        if not settings._write(yac, radio, position_spec, payload):
            return label(failed)
        actual = settings.read(yac, radio, position_spec)
        if actual is None or int(actual) != target:
            return label(failed)
        value = int(actual)
    return label('l175' if position_spec.get('hertz_multiplier') else 'l176',
                 value=value * position_spec.get('hertz_multiplier', 1))
