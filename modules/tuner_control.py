"""Start the configured tuner once and observe its native tuning cycle."""
import time
import re

from modules import verify_settings as settings, region_plan


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
    if not region_plan.permits_transmission(yac, root, radio):
        return label('l356')
    immediate = config.get('immediate_query', False)
    if immediate:
        # Yaesu setters do not reply. Query in the same exchange to observe
        # a short tuning cycle without spending a timeout on the setter.
        command = spec['set'].replace('{value}', start) + spec['read']
        answer = yac._cat_exchange(radio, command)
        match = re.fullmatch(spec['pattern'], answer.strip())
        first_state = match[1] if match else None
    elif not settings._write(yac, radio, spec, start):
        return label('l267')
    print(label('l265'), flush=True)
    seen_busy = False
    for count in range(polls):
        if immediate and count == 0:
            state = first_state
        else:
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


def control(yac, root, radio, language, read_key, watch=None):
    """Read on entry; stay in tuner selection until q returns to Settings."""
    from modules import chat_int, help_int
    spec = settings.catalog(root, radio, yac).get('tuner')
    if spec is None:
        chat_int.show_response(settings._label(yac, root, language, 'l129'))
        return
    chat_int.show_response(settings.describe(yac, root, radio, language, 'tuner', spec))
    while True:
        try:
            key = read_key().casefold()
        except (EOFError, KeyboardInterrupt):
            chat_int.show_done(root, language)
            return
        if watch is not None and watch.lost:
            return
        if key in ('.', ','):
            chat_int.show_response(settings.cycle(yac, root, radio, language, 'tuner',
                                                 direction=-1 if key == ',' else 1))
        elif key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h037'))
        elif key == 'q':
            chat_int.show_done(root, language)
            return
