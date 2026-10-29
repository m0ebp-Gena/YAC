"""Short carrier measurement, always followed by RX and verified restoration."""
import logging
import statistics
import time

from modules import chat_int, help_int, region_plan, split_control, swr_radio

LOG = logging.getLogger('yac')
ERRORS = (OSError, RuntimeError, ValueError, KeyError, TypeError,
          split_control.Unavailable, split_control.CommandFileError)


class Measurement:
    def __init__(self, backend):
        self.backend = backend
        self.journal = []
        self.possible_tx = False
        self.original = {}
        self.changed = False

    def change(self, field, value):
        before = self.backend.read(field)
        if before != value:
            self.changed = True
            self.journal.append((field, before))
            self.backend.write(field, value)

    def restore(self):
        b = self.backend
        # Never restore a user's potentially high power while TX is uncertain.
        if self.possible_tx:
            for attempt in range(2):
                try:
                    b.tx(False)
                    self.possible_tx = False
                    break
                except (KeyboardInterrupt, *ERRORS):
                    LOG.exception('SWR receive request failed')
            if self.possible_tx:
                return 'l374'
        elif self.journal and b.tx_state() is not False:
            return 'l374'
        if not self.changed:
            return None
        # Leave the journal intact until everything is verified. A rejected
        # restoration remains retryable through g, including after reconnect.
        while self.journal:
            field, value = self.journal[-1]
            try:
                if b.tx_state() is not False:
                    return 'l374'
                b.write(field, value)
            except (KeyboardInterrupt, *ERRORS):
                LOG.exception('SWR restoration failed field=%s', field)
                return 'l373'
            self.journal.pop()
        for field, value in self.original.items():
            try:
                if b.tx_state() is not False:
                    return 'l374'
                if b.read(field) != value:
                    b.write(field, value)
            except (KeyboardInterrupt, *ERRORS):
                LOG.exception('SWR original setting not restored field=%s', field)
                return 'l373'
        self.changed = False
        return None


def recover(radio):
    pending = getattr(radio, '_swr_pending', None)
    if pending is None:
        return None
    try:
        error = pending.restore()
    except (KeyboardInterrupt, *ERRORS):
        LOG.exception('SWR recovery failed')
        error = 'l373'
    if error is None:
        radio._swr_pending = None
    return error


def measure(yac, root, radio, language, *, clock=time.monotonic, sleep=time.sleep):
    label = lambda token, **values: yac._read_label(root, language, token, '').format(**values)
    pending_error = recover(radio)
    if pending_error:
        return label(pending_error)
    try:
        b = swr_radio.Radio(yac, root, radio)
    except swr_radio.Unsupported:
        return label('l129')
    except ERRORS:
        return label('l372')
    try:
        hz = b.context()
        b.context_hz = hz
        region = region_plan.selected(yac._read_settings(root / 'yac.ini'))
        margin = b.spec.get('frequency_margin_hz', 0)
        if not all(region_plan.contains(root, region, frequency)
                   for frequency in (hz - margin, hz, hz + margin)):
            return label('l356')
        if not any(low <= hz - margin and hz + margin < high
                   for low, high in b.spec['transmit_ranges_hz']):
            return label('l356')
        if b.tx_state() is not False:
            return label('l372')
        original = {name: b.read(name) for name in ('mode', 'frequency', 'power')}
    except (swr_radio.Invalid, split_control.Unavailable):
        return label('l356')
    except ERRORS:
        return label('l372')

    transaction = Measurement(b)
    transaction.original = original
    radio._swr_pending = transaction
    result = label('l372')
    try:
        # Journal extra originals before changing mode. Mode-specific slots
        # are captured again by change() after selecting the carrier mode.
        for field in b.spec.get('prepare', {}):
            allowed_modes = b.spec.get('mode_snapshot_fields', {}).get(field)
            if allowed_modes is None or original['mode'] in allowed_modes:
                transaction.original[field] = b.read(field)
        if 'vox' in b.spec.get('prepare', {}):
            transaction.change('vox', b.spec['prepare']['vox'])
        for field in b.spec.get('mode_snapshot_fields', {}):
            if field in transaction.original:
                # Restore a mode's independent DATA flag only after restoring
                # that mode. AM's own flag is journalled separately below.
                transaction.journal.append((field, transaction.original[field]))
                transaction.changed = True
        # Frequency is restored after the mode, but before re-enabling VOX.
        transaction.journal.append(('frequency', original['frequency']))
        transaction.changed = True
        transaction.change('mode', b.measurement_mode())
        # Mode changes can shift a displayed frequency on some radios.
        if int(b.read('frequency')) != hz:
            b.write('frequency', original['frequency'])
        for field, value in b.spec.get('prepare', {}).items():
            if field != 'vox':
                transaction.change(field, value)
        target = b.power_value(b.watts(hz))
        transaction.change('power', target)
        # Fresh readback, not a frequency saved before an operator changed VFO.
        if b.context() != hz or b.read('mode') != b.measurement_mode() or int(b.read('power')) != target:
            raise swr_radio.Invalid('Measurement context changed')
        chat_int.show_response(label('l377'))
        transaction.possible_tx = True
        start = clock()
        b.tx(True)
        sleep(max(0, min(b.spec.get('settle_seconds', 0.2), 1.0 - (clock() - start))))
        samples = []
        # Nominal one second, never extended to chase an absent reading.
        # A serial timeout can delay a stop; the finally path always requests RX.
        while clock() - start < 1.0 and len(samples) < 3:
            sleep(min(0.15, max(0, 1.0 - (clock() - start))))
            if clock() - start >= 1.0:
                break
            if int(b.read('frequency')) != hz:
                raise swr_radio.Invalid('Frequency changed during measurement')
            samples.append(b.sample())
        if len(samples) >= 2:
            value = statistics.median(item[0] for item in samples)
            over = sum(item[1] for item in samples) >= 2
            if max(item[0] for item in samples) - min(item[0] for item in samples) <= max(0.2, value * 0.1):
                result = label('l376' if over else 'l375', value=f'{value:.1f}')
        LOG.debug('SWR model=%s frequency=%s native_power=%s samples=%s',
                  radio.model_id, hz, target, samples)
    except KeyboardInterrupt:
        result = label('l355')
    except swr_radio.Invalid:
        result = label('l356')
    except ERRORS:
        LOG.exception('SWR measurement failed')
    finally:
        error = recover(radio)
        if error:
            result = label(error)
    return result


def control(yac, root, radio, language, read_key, watch=None):
    say = lambda token: chat_int.show_response(yac._read_label(root, language, token, ''))
    say('l370')
    say('l371')
    while True:
        try:
            key = read_key().casefold()
        except (EOFError, KeyboardInterrupt):
            error = recover(radio)
            if error:
                say(error)
            chat_int.show_done(root, language)
            return
        if watch is not None and watch.lost:
            return
        if key == 'g':
            chat_int.show_response(measure(yac, root, radio, language))
        elif key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h035'))
        elif key == 'q':
            error = recover(radio)
            if error:
                say(error)
            chat_int.show_done(root, language)
            return
