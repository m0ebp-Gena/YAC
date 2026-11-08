"""Native CAT parameters for the Elecraft KX2."""
import re
import time


FREQUENCY_RANGE = (500_000, 32_000_000)
MODES = {
    '1': 'LSB', '2': 'USB', '3': 'CW', '4': 'FM', '5': 'AM',
    '6': 'DATA', '7': 'CW-R', '9': 'DATA-R',
}
# 80 through 10 m, including 60 m. Other logical bands can be reached
# by direct frequency entry where they fall within the receiver range.
BANDS = tuple(range(1, 10))


def read_mode(exchange, radio):
    match = re.search(r'(?:^|;)MD([12345679]);', exchange(radio, 'MD;'))
    return match[1] if match else None


def modes(exchange, radio):
    match = re.search(r'(?:^|;)RVM(\d{2})\.(\d{2});', exchange(radio, 'RVM;'))
    fm = match and (2, 89) <= (int(match[1]), int(match[2])) < (99, 99)
    return [(code, name) for code, name in MODES.items() if code != '4' or fm]


def change_band(exchange, radio, direction):
    def read():
        match = re.search(r'(?:^|;)BN(\d{2});', exchange(radio, 'BN;'))
        return int(match[1]) if match else None

    current = read()
    if current is None:
        return False
    choices = BANDS if direction > 0 else reversed(BANDS)
    target = next((band for band in choices if (band - current) * direction > 0), None)
    if target is None:
        return False
    exchange(radio, f'BN{target:02d};')
    time.sleep(0.3)
    return read() == target


def signal(exchange, radio):
    # SM has two scales depending on the radio's CAT extension mode.
    match = re.search(r'(?:^|;)SM(00(?:0\d|1\d|2[01]));', exchange(radio, 'SM;'))
    return f'S {int(match[1])}' if match else 'S ?'


def noise_reduction_state(exchange, radio):
    """Read the NR icon via the extended display reply and restore CAT format."""
    cat_format = exchange(radio, 'K3;').strip()
    if cat_format not in {'K30;', 'K31;'}:
        return None
    restore = cat_format == 'K30;'
    restored = True
    try:
        if restore:
            exchange(radio, 'K31;')
            if exchange(radio, 'K3;').strip() != 'K31;':
                return None
        display = re.search(r'(?:^|;)DS[\x30-\xff]{8}[\x80-\xff]([\x80-\xff]);',
                            exchange(radio, 'DS;'))
    finally:
        if restore:
            exchange(radio, cat_format)
            restored = exchange(radio, 'K3;').strip() == cat_format
    if not restored or not display:
        return None
    return '1' if ord(display[1]) & 0x04 else '0'
