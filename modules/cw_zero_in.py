"""Explicit native CW zero-in, with model commands kept in radio data."""
import json
import logging
import time
from modules import mic_gain, split_control

LOG = logging.getLogger('yac')

class Unsupported(Exception):
    pass

def prepare(yac, root, radio):
    path = root / radio.radio_id_path / 'cw-zero-in.json'
    if not path.is_file():
        raise Unsupported
    spec = json.loads(path.read_text(encoding='utf-8'))
    rig = split_control.Radio(yac, root, radio).prepare()
    rig.check_context()
    if rig.rxmode not in {'3', '7'}:
        raise ValueError('CW mode required')
    if mic_gain.tx_state(yac, radio, {'family': spec['family']}) is not False:
        raise ValueError('Receive state not confirmed')
    raw = int(rig.cat(spec['pitch_read'], spec['pitch_pattern']))
    if not spec['pitch_min'] <= raw <= spec['pitch_max']:
        raise ValueError('Invalid CW pitch')
    pitch = spec['pitch_base_hz'] + raw * spec['pitch_step_hz']
    return rig, spec, pitch

def apply(yac, radio, prepared):
    rig, spec, pitch = prepared
    if rig.cat('VS;', r'VS([01]);') != str(rig.side):
        raise ValueError('Receive side changed')
    rig.check_context()
    if rig.read('rxmode') not in {'3', '7'} or mic_gain.tx_state(yac, radio, {'family': spec['family']}) is not False:
        raise ValueError('CW receive state changed')
    side = rig.side if spec['side'] == 'selected' else spec['side']
    answer = yac._cat_exchange(radio, spec['start'].format(side=side))
    if '?;' in answer:
        raise ValueError('Zero In rejected')
    # ZI has no completion/status reply. Announce frequency readback, not lock.
    time.sleep(spec['readback_delay_seconds'])
    if rig.cat('VS;', r'VS([01]);') != str(rig.side):
        raise ValueError('Receive side changed')
    frequency = rig.frequency('rx')
    LOG.info('CW Zero In requested model=%s side=%s pitch_hz=%s frequency_hz=%s',
             radio.model_id, rig.side, pitch, frequency)
    return frequency
