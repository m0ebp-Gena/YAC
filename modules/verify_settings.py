"""Model-specific settings, with live readback and language-file labels.

No state is cached: controls on the radio can change these values at any time.
An absent catalog feature means unsupported; a failed read means unknown.
"""
import json
import re


def catalog(root, radio, yac=None):
    path = root / radio.radio_id_path / 'settings.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if radio.protocol == 'CAT' and radio.model_id == '020' and yac is not None:
        from modules import ts480_control
        variant = ts480_control.variant(yac, radio)
        if variant is not None:
            extra = path.with_name('ts480-settings.json')
            data.update(json.loads(extra.read_text(encoding='utf-8')))
            maximum = ts480_control.profile(yac, radio)['maximum_watts'][variant]
            data['power']['maximum'] = maximum
            data['power']['mode_fraction'] = {'5': 0.25}
            if variant == '0':
                data['power']['band_maximum'] = [{'minimum_mhz': 50, 'watts': 100}]
            if variant != '1':
                data.pop('tuner', None)
    return data


def _command(spec, name, band):
    return spec[name].replace('{band}', str(band))


def band(yac, radio):
    frequency = yac._current_frequency(yac.project_root(), radio)
    if frequency is None:
        return None
    hz = float(frequency) * 1_000_000
    return 0 if hz < 100_000_000 else 1 if hz < 300_000_000 else 2


def read(yac, radio, spec, selected_band=0):
    if spec['protocol'] == 'civ':
        command = bytes.fromhex(spec['read'])
        sub = command[1] if len(command) > 1 else None
        response = yac._civ_exchange(radio, command[0], sub)
        data = yac._civ_response_data(response, radio.civ_address, command[0], sub)
        if data is None:
            return None
        if spec.get('encoding') == 'bcd':
            if len(data) != 2 or any(b >> 4 > 9 or b & 15 > 9 for b in data):
                return None
            value = int(data.hex())
            return value if 0 <= value <= 255 else None
        return data.hex().upper() if len(data) == 1 else None
    response = yac._cat_exchange(radio, _command(spec, 'read', selected_band))
    match = re.search(_command(spec, 'pattern', selected_band), response)
    if not match:
        return None
    value = match.group(1)
    if 'minimum' in spec and not spec['minimum'] <= int(value) <= spec['maximum']:
        return None
    return value


def _write(yac, radio, spec, value, selected_band=0):
    if spec['protocol'] == 'civ':
        command = bytes.fromhex(spec['set'])
        result = yac._civ_send(radio, command[0], command[1:] + bytes.fromhex(value))
        return bytes((254, 254, 224, radio.civ_address, 251, 253)) in result
    yac._cat_exchange(radio, _command(spec, 'set', selected_band).replace('{value}', value))
    return True  # CAT setters need not reply; the caller always reads back.


def _label(yac, root, language, token, **values):
    return yac._read_label(root, language, token, '').format(**values)


def _states(spec, selected_band):
    return spec.get('band_states', {}).get(str(selected_band), spec.get('states', {}))


def _tuner_state(yac, radio, spec):
    value = read(yac, radio, spec)
    if value is None:
        return None
    if spec.get('selection'):
        selection = read(yac, radio, spec['selection'])
        if selection not in spec['selection']['states']:
            return None
        if value not in spec['states']:
            return None
        if spec['states'][value] == 'l130':
            return 'tuning'
        if selection == spec.get('atas_selection'):
            return 'atas'
        if spec['states'][value] == 'l121':
            return 'off'
        return selection
    return spec.get('aliases', {}).get(value, value) if value in spec['states'] else None


def _select_tuner(yac, radio, spec, current, target):
    """Change selection with readback; recover the previous idle state on failure."""
    raw = read(yac, radio, spec)
    selection = read(yac, radio, spec['selection'])
    if raw not in spec['states'] or selection not in spec['selection']['states']:
        return False
    if spec['states'][raw] == 'l130':
        return False  # Never restore a tuning-start command.

    def write_checked(setting, value):
        return _write(yac, radio, setting, value) and read(yac, radio, setting) == value

    def restore():
        if read(yac, radio, spec['selection']) == selection and read(yac, radio, spec) == raw:
            return
        # Stop if selection cannot be restored: enabling another tuner is unsafe.
        if write_checked(spec['selection'], selection):
            write_checked(spec, raw)

    if spec.get('selection_first'):
        # DX10 ATAS can keep reporting enabled after a bypass request.
        # Change the tuner-routing menu first; do not require the old
        # device to confirm Off before allowing the operator to leave it.
        selected = (spec['off_selection'] if target == 'off' and current == 'atas'
                    else selection if target == 'off'
                    else spec['atas_selection'] if target == 'atas' else target)
        if selected != selection and not write_checked(spec['selection'], selected):
            restore()
            return False
        if target != 'atas':
            enabled = spec['off'] if target == 'off' else spec['enable'][selected]
            if not write_checked(spec, enabled):
                restore()
                return False
        if _tuner_state(yac, radio, spec) != target:
            restore()
            return False
        return True

    off = spec['off'].replace('{selection}', raw[:2])
    if raw != off and not write_checked(spec, off):
        restore()
        return False
    selected = (spec['off_selection'] if target == 'off' and current == 'atas'
                else selection if target == 'off'
                else spec.get('atas_selection') if target == 'atas' else target)
    if selected != selection and not write_checked(spec['selection'], selected):
        restore()
        return False
    enabled = (spec['off_from_atas'] if target == 'off' and current == 'atas'
               else off if target == 'off' else spec['enable'][selected])
    if enabled != off or selected != selection:
        if not write_checked(spec, enabled):
            restore()
            return False
    if _tuner_state(yac, radio, spec) != target:
        restore()
        return False
    return True


def describe(yac, root, radio, language, name, spec):
    if name == 'tuner' and spec.get('kind') == 'ftx1':
        from modules import ftx_tuner
        return ftx_tuner.describe(yac, root, radio, language)
    if name == 'tuner' and spec.get('show_selection_and_state'):
        raw = read(yac, radio, spec)
        selected = read(yac, radio, spec['selection'])
        selection_label = spec['selection']['states'].get(selected)
        state_label = spec['states'].get(raw)
        if selection_label and state_label:
            return _label(yac, root, language, selection_label) + ', ' + _label(yac, root, language, state_label)
        return _label(yac, root, language, 'l128')
    selected_band = band(yac, radio) if spec.get('band_states') else 0
    value = (_tuner_state(yac, radio, spec) if name == 'tuner' else
             read(yac, radio, spec, selected_band) if selected_band is not None else None)
    if name == 'power' and value is not None:
        if spec.get('encoding') == 'bcd':
            return _label(yac, root, language, 'l120', value=round(value * 100 / 255))
        return _label(yac, root, language, 'l119', value=int(value))
    states = _states(spec, selected_band)
    if name == 'tuner' and spec.get('selection'):
        states = dict(spec['selection']['states'], off='l121', atas='l124', tuning='l130')
    if value in states:
        return _label(yac, root, language, states[value])
    if name == 'attenuator':
        return yac._radio_error(root, radio, language)
    return _label(yac, root, language, {'preamp':'l126',
                                     'power':'l127', 'tuner':'l128'}[name])


def verify(yac, root, radio, language):
    features = catalog(root, radio, yac)
    return ', '.join(describe(yac, root, radio, language, name, features[name])
                     for name in ('attenuator', 'preamp', 'power', 'tuner') if name in features) or _label(yac, root, language, 'l129')


def cycle(yac, root, radio, language, name, *, direction=1):
    spec = catalog(root, radio, yac).get(name)
    if spec is None:
        return _label(yac, root, language, 'l129')
    if name == 'tuner' and spec.get('kind') == 'ftx1':
        from modules import ftx_tuner
        return ftx_tuner.cycle(yac, root, radio, language, direction=direction)
    selected_band = band(yac, radio) if spec.get('band_states') else 0
    if selected_band is None:
        return describe(yac, root, radio, language, name, spec)
    current = _tuner_state(yac, radio, spec) if name == 'tuner' else read(yac, radio, spec, selected_band)
    choices = spec.get('cycle', list(_states(spec, selected_band)))
    if current not in choices:
        # Unknown or actively tuning: do not invent a starting state.
        return describe(yac, root, radio, language, name, spec)
    target = choices[(choices.index(current) + direction) % len(choices)]
    if name == 'tuner' and spec.get('selection'):
        if not _select_tuner(yac, radio, spec, current, target):
            return yac._radio_error(root, radio, language)
    elif not _write(yac, radio, spec, target, selected_band):
        return yac._radio_error(root, radio, language)
    actual = _tuner_state(yac, radio, spec) if name == 'tuner' else read(yac, radio, spec, selected_band)
    if actual != target:
        return yac._radio_error(root, radio, language)
    return describe(yac, root, radio, language, name, spec)
