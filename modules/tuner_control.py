"""Start the configured tuner once and observe its native tuning cycle."""
import time

from modules import verify_settings as settings


def tune(yac, root, radio, language, *, polls=120, interval=0.5):
    label = lambda token: settings._label(yac, root, language, token)
    spec = settings.catalog(root, radio, yac).get('tuner')
    if spec and spec.get('kind') == 'ftx1':
        from modules import ftx_tuner
        return ftx_tuner.tune(yac, root, radio, language, polls=polls, interval=interval)
    if not spec or not spec.get('tune'):
        return label('l129')
    config = spec['tune']
    current = settings.read(yac, radio, spec)
    if current in config['busy']:
        return label('l130')  # A second start toggles stop on some Yaesu radios.
    if current not in spec['states']:
        return label('l128')
    if spec['states'][current] == 'l121':
        return label('l121')
    if spec.get('selection') and settings._tuner_state(yac, radio, spec) is None:
        return label('l128')
    start = config.get('start', config.get('start_by_state', {}).get(current))
    if start is None:
        return label('l128')
    if not settings._write(yac, radio, spec, start):
        return label('l267')
    print(label('l265'), flush=True)
    seen_busy = False
    for count in range(polls):
        time.sleep(interval)
        state = settings.read(yac, radio, spec)
        if state in config['busy']:
            seen_busy = True
        elif state in config['idle']:
            if seen_busy:
                return label('l266')
            # Allow a delayed start, but never interpret an ignored command as success.
            if count >= 5:
                return label('l268')
        elif state in spec['states']:
            return label('l267')
        else:
            # A lost reply may leave the transmitter tuning. Request stop below.
            break
    stop = config.get('stop', config.get('stop_by_start', {}).get(start))
    settings._write(yac, radio, spec, stop)
    state = settings.read(yac, radio, spec)
    return label('l269' if state is not None and state not in config['busy'] else 'l270')
