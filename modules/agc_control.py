"""Cycle only documented AGC choices; preserve custom time constants."""
from modules import verify_settings as settings, ts480_control


def profile(yac, radio):
    if radio.protocol == 'CI-V' and yac._icom_supported(radio):
        return {'protocol': 'civ', 'read': '16 12', 'set': '16 12',
                'choices': ['01', '02', '03'], 'labels': {'01': 'l221', '02': 'l222', '03': 'l223'},
                'family': 'icom'}
    if radio.protocol == 'CAT' and radio.manufacturer_key == 'yaesu' and radio.model_id in {'0761', '0800', '0840'}:
        side = yac._yaesu_vfo_side if radio.model_id == '0840' else 0
        return {'protocol': 'cat', 'read': f'GT{side};', 'set': f'GT{side}' + '{value};',
                'pattern': rf'GT{side}([0-6]);', 'choices': ['1', '2', '3', '4', '0'],
                'labels': {'0': 'l225', '1': 'l221', '2': 'l222', '3': 'l223',
                           '4': 'l226', '5': 'l227', '6': 'l228'}, 'family': 'yaesu', 'side': side}
    if radio.protocol == 'CAT' and radio.manufacturer_key == 'kenwood':
        if radio.model_id == '023':
            return {'protocol': 'cat', 'read': 'GC;', 'set': 'GC{value};', 'pattern': r'GC([012]);',
                    'choices': ['2', '1', '0'], 'labels': {'0': 'l225', '1': 'l223', '2': 'l221'}, 'family': 'kenwood'}
        if radio.model_id == '020' and ts480_control.variant(yac, radio) is not None:
            return {'protocol': 'cat', 'read': 'GT;', 'set': 'GT{value};', 'pattern': r'GT(00[012]);',
                    'choices': ['001', '002', '000'], 'labels': {'000': 'l225', '001': 'l221', '002': 'l223'}, 'family': 'kenwood'}
    return None


def cycle(yac, root, radio, language):
    def label(token):
        return settings._label(yac, root, language, token)
    spec = profile(yac, radio)
    if spec is None:
        return label('l129')
    mode = yac._current_mode(radio)
    if mode is None:
        return label('l229')
    if spec['family'] == 'icom' and (mode.startswith('FM') or mode in {'WFM', 'DV', 'DD'}):
        return label('l230')
    if spec['family'] == 'kenwood' and mode.startswith('FM'):
        return label('l231')
    current = settings.read(yac, radio, spec)
    if current not in spec['labels']:
        return label('l229')
    # Yaesu Auto is returned as Auto-Fast/Mid/Slow, not writable value 4.
    selected = '4' if spec['family'] == 'yaesu' and current in {'4', '5', '6'} else current
    target = spec['choices'][(spec['choices'].index(selected) + 1) % len(spec['choices'])]
    if yac._current_mode(radio) != mode:
        return label('l229')
    if not settings._write(yac, radio, spec, target):
        return label('l131')
    actual = settings.read(yac, radio, spec)
    verified = actual in {'4', '5', '6'} if target == '4' and spec['family'] == 'yaesu' else actual == target
    if not verified:
        return label('l131')
    result = label(spec['labels'][actual])
    if spec['family'] == 'yaesu' and radio.model_id == '0840':
        result = ('Main' if spec['side'] == 0 else 'Sub') + ' ' + result
    return result
