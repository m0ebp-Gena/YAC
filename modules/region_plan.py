"""Regional frequency envelopes for YAC-initiated RF, not receive tuning limits.

National permissions and the radio's firmware remain independent restrictions.
Plan files are deliberately separate from model definitions and UI resources.
"""
import json
import re


def selected(settings):
    value = settings.get('region', '1')
    if value not in {'1', '2', '3'}:
        raise ValueError('Invalid region')
    return int(value)


def load(root, region):
    if region not in (1, 2, 3):
        raise ValueError('Invalid region')
    data = json.loads((root / 'rad_cmds' / 'regions' / f'{region}.json').read_text(encoding='utf-8'))
    if data['region'] != region or not data['sources']:
        raise ValueError('Invalid regional plan')
    previous = 0
    for low, high in data['transmit_ranges_hz']:
        if type(low) is not int or type(high) is not int or not previous <= low < high:
            raise ValueError('Invalid regional ranges')
        previous = high
    return data


def contains(root, region, hz):
    # Upper edges are excluded: a carrier on the boundary has no band margin.
    return any(low <= hz < high for low, high in load(root, region)['transmit_ranges_hz'])


def transmit_frequency(yac, root, radio):
    """Read TX VFO frequency. Refuse contexts whose effective RF is uncertain.

    No setters, VFO swaps or cached receive frequencies are used here.
    """
    from modules import split_control
    if radio.protocol == 'CI-V' or radio.manufacturer_key == 'yaesu':
        rig = split_control.Radio(yac, root, radio).prepare()
        rig.fm = False  # Check both VFOs even when receive happens to be FM.
        rig.check_context()  # Reject memory/satellite contexts and active offsets.
        if rig.yaesu:
            if rig.read('shift') != '0':
                return None
            side = rig.read('txside')
            if side not in {'0', '1'}:
                return None
            return rig.frequency('rx' if int(side) == rig.side else 'tx')
        # CI-V split readback also encodes FM repeater shift. Do not treat
        # a shifted frequency as the displayed base frequency.
        if rig.state not in {b'\x00', b'\x01'}:
            return None
        return rig.frequency('tx' if rig.on else 'rx')
    if radio.manufacturer_key == 'kenwood':
        # Native tuner profiles exist only for these identified Kenwoods.
        if radio.model_id not in {'023', '020'}:
            return None
        if radio.model_id == '020':
            from modules import ts480_control
            if ts480_control.variant(yac, radio) is None:
                return None
        tx = re.fullmatch(r'FT([01]);', yac._cat_exchange(radio, 'FT;').strip())
        rx = re.fullmatch(r'FR([01]);', yac._cat_exchange(radio, 'FR;').strip())
        info = re.fullmatch(r'IF([^;]{35});', yac._cat_exchange(radio, 'IF;').strip())
        if not tx or not rx or not info:
            return None
        body = info[1]
        # IF: XIT, TX, scan and split flags; malformed/active states block RF.
        if body[22] != '0' or body[26] != '0' or body[29] != '0':
            return None
        prefix = 'FA' if tx[1] == '0' else 'FB'
        match = re.fullmatch(prefix + r'(\d{11});', yac._cat_exchange(radio, prefix + ';').strip())
        return int(match[1]) if match else None
    return None


def permits_transmission(yac, root, radio):
    """Fail closed before a native tuning/carrier start; stopping stays possible."""
    from modules import split_control
    try:
        region = selected(yac._read_settings(root / 'yac.ini'))
        hz = transmit_frequency(yac, root, radio)
        return hz is not None and contains(root, region, hz)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError,
            IndexError, ArithmeticError, split_control.Unavailable,
            split_control.CommandFileError):
        return False
