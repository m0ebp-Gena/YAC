"""Read-only summary of switchable filters applicable to the receive mode."""
from modules import verify_settings as settings


def _reports(yac, root, radio, language, features=None):
    label = lambda token, **values: settings._label(yac, root, language, token, **values)
    features = settings.catalog(root, radio, yac) if features is None else features
    entries = []
    for name, on, unknown in [('noise_blanker', 'l153', 'l156'),
                               ('noise_reduction', 'l160', 'l163')]:
        if name in features:
            entries.append((name, features[name], on, unknown))
    for key, on in [('a', 'l171'), ('n', 'l173')]:
        spec = features.get('notch', {}).get(key)
        if spec:
            entries.append((key, spec, on, 'l188' if spec.get('beat_cancel') else 'l181'))
    if 'contour' in features:
        entries.append(('contour', features['contour'], 'l190', 'l197'))
    if not entries:
        return label('l201'), [], None
    mode = yac._current_mode_code(radio)
    if mode is None:
        return label('l204'), [], None
    mode = str(mode).upper()
    side = str(yac._yaesu_vfo_side) if radio.model_id == '0840' else '0'
    active, unknowns, items, names = [], [], [], []
    reads = {}
    for name, spec, on, unknown in entries:
        if mode not in spec['modes']:
            continue
        names.append(name)
        state = {k: v.replace('{side}', side) if isinstance(v, str) else v
                 for k, v in spec['state'].items()}
        cache_key = (state['protocol'], state['read'], state.get('pattern'))
        if cache_key not in reads:
            reads[cache_key] = settings.read(yac, radio, state)
        raw = reads[cache_key]
        value = str(raw) if raw is not None else None
        if spec.get('shared'):
            valid = value in {'00', '10', '20', '21'}
            enabled = valid and value.startswith('1' if name == 'a' else '2')
        else:
            off = '0000' if name == 'contour' else state['off']
            on_values = ['0001'] if name == 'contour' else state['on_values']
            valid = value in on_values + [off]
            enabled = valid and value != off
        if not valid:
            item = label(unknown)
            unknowns.append(item)
        elif enabled:
            token = spec.get('on_labels', {}).get(value, on)
            if spec.get('beat_cancel'):
                token = {'1': 'l185', '2': 'l186'}[value]
            elif name == 'noise_blanker' and radio.model_id == '023':
                token = {'1': 'l205', '2': 'l206'}[value]
            item = label(token)
            active.append(item)
        else:
            token = {'noise_blanker': 'l154', 'noise_reduction': 'l161',
                     'a': 'l187' if spec.get('beat_cancel') else 'l172',
                     'n': 'l174', 'contour': 'l191'}[name]
            item = label(token)
        items.append(item)
    result = []
    if active:
        result.append(label('l199', filters=', '.join(active)))
    elif not unknowns:
        result.append(label('l200' if names else 'l201'))
    result.extend(dict.fromkeys(unknowns))
    summary = ', '.join(result)
    if radio.model_id == '0840':
        summary = label('l202' if side == '0' else 'l203', filters=summary)
        items = [label('l202' if side == '0' else 'l203', filters=item) for item in items]
    return summary, items, (mode, side, tuple(names))


def verify(yac, root, radio, language, features=None):
    return _reports(yac, root, radio, language, features)[0]


class Review:
    """Consecutive v presses: summary, each live status, then summary again."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.context = None
        self.index = 0

    def next(self, yac, root, radio, language):
        summary, items, context = _reports(yac, root, radio, language)
        if context != self.context:
            self.index = 0
        self.context = context
        reports = [summary] + items
        response = reports[self.index % len(reports)]
        self.index = (self.index + 1) % len(reports)
        return response
