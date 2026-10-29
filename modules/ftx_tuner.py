"""FTX-1 tuner routing, corrected against hardware-tested CAT errata.

EX030104 is OPTION/ATAS, not INT/FAST/EXT/ATAS. On the SPA-1 the
four tuner types belong to EX030701/2. AC100 is an idle cycle reply,
not evidence that the configured tuner is Off. Never send AC001/AC003.
"""
from dataclasses import dataclass
import logging
import re
import time

LOG = logging.getLogger('yac')
LABELS = {'0': 'l122', '1': 'l137', '2': 'l123', '3': 'l124'}


class Unknown(ValueError):
    pass


def send(yac, radio, command):
    try:
        return yac._cat_exchange(radio, command)
    except (OSError, ValueError) as error:
        raise Unknown from error


def query(yac, radio, command, pattern):
    answer = send(yac, radio, command)
    match = re.search(pattern, answer)
    if not match:
        LOG.warning('FTX tuner query failed command=%s answer=%r', command, answer)
        raise Unknown
    return match.group(1)


def menu(yac, radio, number):
    return query(yac, radio, f'EX{number};', rf'EX{number}([0-3]);')


def status(yac, radio):
    return query(yac, radio, 'AC;', r'AC([01][02][0-3]);')


def busy(ac):
    # Conventional ATU: 1 is ON, 3 is tuning. ATAS 1/2 are motor moves.
    return ac[-1] != '0' if ac[1] == '2' else ac[-1] == '3'


def write_menu(yac, radio, number, value):
    answer = send(yac, radio, f'EX{number}{value};')
    if '?;' in answer:
        return False
    for attempt in range(3):
        if menu(yac, radio, number) == value:
            return True
        if attempt < 2:
            time.sleep(0.05)
    return False


@dataclass(frozen=True)
class Context:
    power: str
    route: str
    antenna: str | None
    operation: str | None
    setting: str | None
    selected: str


def context(yac, radio):
    power = query(yac, radio, 'PC;', r'PC([12])\d{3};')
    route = menu(yac, radio, '030104')
    if route not in ('0', '1'):
        raise Unknown
    if power == '1':
        # Standalone head: OPTION is its external tuner, never an internal ATU.
        return Context(power, route, None, None, None, '3' if route == '1' else '2')
    antenna = menu(yac, radio, '030704')
    operation = menu(yac, radio, '030703')
    if antenna not in ('0', '1') or operation not in ('0', '1', '2'):
        raise Unknown
    # Separate RX input still transmits on ANT1.
    setting = '030702' if antenna == '1' and operation == '0' else '030701'
    selected = menu(yac, radio, setting)
    return Context(power, route, antenna, operation, setting,
                   '3' if route == '1' else selected)


def label(yac, root, language, token):
    return yac._read_label(root, language, token, '')


def describe(yac, root, radio, language):
    try:
        value = context(yac, radio)
        ac = status(yac, radio)
        token = 'l130' if busy(ac) else LABELS[value.selected]
        return label(yac, root, language, token)
    except Unknown:
        return label(yac, root, language, 'l128')


def cycle(yac, root, radio, language):
    try:
        ac = status(yac, radio)
        if busy(ac):
            return label(yac, root, language, 'l130')
        before = context(yac, radio)
        frequency = yac._current_frequency(root, radio)
        if frequency is None:
            raise Unknown
        if not 0.03 <= float(frequency) <= 54:
            return label(yac, root, language, 'l129')
        choices = ('0', '1', '2', '3') if before.power == '2' else ('2', '3')
        target = choices[(choices.index(before.selected) + 1) % len(choices)]
        saved_type = menu(yac, radio, before.setting) if before.setting else None
        changed = []
        try:
            updates = ([(before.setting, saved_type, target)] if before.setting else [])
            updates.append(('030104', before.route, '1' if target == '3' else '0'))
            for number, old, new in updates:
                if old == new:
                    continue
                # A rejected/lost write may still have changed the radio.
                changed.append((number, old))
                if not write_menu(yac, radio, number, new):
                    raise Unknown
            after = context(yac, radio)
            if (after.power, after.antenna, after.operation, after.setting) != (
                    before.power, before.antenna, before.operation, before.setting):
                raise Unknown
            if after.selected != target:
                raise Unknown
        except Unknown:
            restored = True
            for number, old in reversed(changed):
                try:
                    restored = write_menu(yac, radio, number, old) and restored
                except Unknown:
                    restored = False
            return yac._radio_error(root, radio, language) if restored else label(yac, root, language, 'l003')
        return label(yac, root, language, LABELS[target])
    except (Unknown, ValueError):
        return label(yac, root, language, 'l128')


def tune(yac, root, radio, language, *, polls=120, interval=0.5):
    from modules import region_plan
    text = lambda token: label(yac, root, language, token)
    try:
        before = context(yac, radio)
        if busy(status(yac, radio)):
            return text('l130')
        frequency = yac._current_frequency(root, radio)
        if frequency is None:
            raise Unknown
        if not 0.03 <= float(frequency) <= 54:
            return text('l129')
        if not region_plan.permits_transmission(yac, root, radio):
            return text('l356')
        # Hardware erratum: P1=1 also controls the Optima internal tuner.
        start = 'AC123;' if before.selected == '3' else 'AC103;'
        stop = 'AC120;' if before.selected == '3' else 'AC000;'
        if '?;' in send(yac, radio, start):
            return text('l267')
    except (Unknown, ValueError):
        return text('l128')
    print(text('l265'), flush=True)
    seen_busy = False
    deadline = time.monotonic() + 60
    for count in range(polls):
        if time.monotonic() >= deadline:
            break
        time.sleep(interval)
        try:
            ac = status(yac, radio)
        except Unknown:
            break
        if busy(ac):
            seen_busy = True
        elif seen_busy:
            return text('l266')
        elif count >= 5:
            return text('l268')
    try:
        send(yac, radio, stop)
        stopped = not busy(status(yac, radio))
    except Unknown:
        stopped = False
    return text('l269' if stopped else 'l270')
