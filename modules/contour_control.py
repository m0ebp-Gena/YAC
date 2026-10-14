"""Yaesu Contour with verified live readback."""
from modules import verify_settings as settings


def operate(yac, root, radio, language, *, toggle=False, parameter='frequency', direction=0):
    label = lambda token, **values: settings._label(yac, root, language, token, **values)
    feature = settings.catalog(root, radio).get('contour')
    if feature is None:
        return label('l129')
    mode = yac._current_mode_code(radio)
    if mode is None:
        return label('l197')
    if str(mode).upper() not in feature['modes']:
        return label('l129')
    side = str(yac._yaesu_vfo_side) if radio.model_id == '0840' else '0'
    expand = lambda spec: {k: v.replace('{side}', side) if isinstance(v, str) else v for k, v in spec.items()}
    state = expand(feature['state'])
    enabled = settings.read(yac, radio, state)
    if enabled not in {'0000', '0001'}:
        return label('l197')
    if toggle:
        target = '0000' if enabled == '0001' else '0001'
        if not settings._write(yac, radio, state, target) or settings.read(yac, radio, state) != target:
            return label('l198')
        return label('l190' if target == '0001' else 'l191')
    if enabled == '0000':
        return label('l191')
    spec = expand(feature[parameter])
    raw = settings.read(yac, radio, spec)
    if raw is None:
        return label('l197')
    value = int(raw)
    target = max(spec['minimum'], min(spec['maximum'], value + direction * spec['step']))
    if target != value:
        payload = f'{target:+03d}' if parameter == 'level' else f'{target:0{spec["digits"]}d}'
        if not settings._write(yac, radio, spec, payload):
            return label('l198')
        actual = settings.read(yac, radio, spec)
        if actual is None or int(actual) != target:
            return label('l198')
        value = int(actual)
    if parameter == 'level':
        return label('l194' if value < 0 else 'l195' if value > 0 else 'l196', value=abs(value))
    return label('l192' if parameter == 'frequency' else 'l193', value=value)
