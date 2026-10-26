"""Read active repeater signalling for Where am I; never change settings."""
import re


def report(yac, root, radio, language, *, side=None, mode=None):
    label = lambda token: yac._read_label(root, language, token, '')
    mode = yac._current_mode(radio) if mode is None else mode
    if mode is None:
        return yac._radio_error(root, radio, language)
    if not mode.startswith('FM'):
        return ''
    kind = yac._tone_radio_kind(radio)
    if kind is None:
        return ''

    def cat(command, pattern):
        match = re.search(pattern, yac._cat_exchange(radio, command))
        return match.group(1) if match else None

    def civ(command, sub):
        return yac._civ_response_data(yac._civ_exchange(radio, command, sub),
                                      radio.civ_address, command, sub)

    def ctcss(value, target):
        return f'CTCSS {value} Hz {label(target)}'

    def dcs(value, tx, rx=None):
        if rx is None:
            return f'DCS {"I" if tx else "N"} {value} {label("l102")}'
        if tx == rx:
            return f'DCS {"I" if tx else "N"} {value} {label("l103")}'
        return (f'DCS {value} {label("l102")} {"I" if tx else "N"}, '
                f'{label("l248")} {"I" if rx else "N"}')

    if kind in {'ftx1', 'ftdx10'}:
        side = (yac._yaesu_vfo_side if side is None else side) if kind == 'ftx1' else 0
        state = cat(f'CT{side};', rf'CT{side}([0-9]);')
        if state == '0':
            return ''
        tx, both = ('1', '2') if kind == 'ftx1' else ('2', '1')
        if state in {tx, both}:
            index = cat(f'CN{side}0;', rf'CN{side}0(\d{{3}});')
            if index is None or int(index) >= len(yac.CTCSS_TONES):
                return yac._radio_error(root, radio, language)
            return ctcss(yac.CTCSS_TONES[int(index)], 'l102' if state == tx else 'l103')
        if kind == 'ftx1' and state == '3':
            index = cat(f'CN{side}1;', rf'CN{side}1(\d{{3}});')
            rx = cat('EX010323;', r'EX010323([01]);')
            tx = cat('EX010324;', r'EX010324([01]);')
            codes = sorted(yac.ICOM_DCS_CODES)
            if index is None or int(index) >= len(codes) or rx is None or tx is None:
                return yac._radio_error(root, radio, language)
            return dcs(f'{codes[int(index)]:03d}', tx == '1', rx == '1')
        return yac._radio_error(root, radio, language)

    if kind in {'ts590', 'ts480'}:
        rx = cat('CT;', r'CT([01]);')
        tx = cat('TO;', r'TO([01]);')
        if rx is None or tx is None:
            return yac._radio_error(root, radio, language)
        if rx == tx == '0':
            return ''
        query = 'CN' if rx == '1' else 'TN'
        index = cat(query + ';', query + r'(\d{2});')
        if index is None or int(index) >= len(yac.TS590_CTCSS):
            return yac._radio_error(root, radio, language)
        return ctcss(yac.TS590_CTCSS[int(index)], 'l103' if rx == '1' else 'l102')

    state = civ(0x16, 0x5D)
    if state == b'\x00':
        return ''
    if state in {b'\x01', b'\x02'}:
        data = civ(0x1B, 0x00)
        if data is None or len(data) != 3 or data[0] != 0 or any(b >> 4 > 9 or b & 15 > 9 for b in data[1:]):
            return yac._radio_error(root, radio, language)
        value = f'{int(data[1:].hex()) / 10:.1f}'
        if value not in yac.CTCSS_TONES:
            return yac._radio_error(root, radio, language)
        if state == b'\x02':
            rx = civ(0x1B, 0x01)
            if rx != data:
                if rx is None or len(rx) != 3 or rx[0] != 0 or any(b >> 4 > 9 or b & 15 > 9 for b in rx[1:]):
                    return yac._radio_error(root, radio, language)
                receive_value = f'{int(rx[1:].hex()) / 10:.1f}'
                if receive_value not in yac.CTCSS_TONES:
                    return yac._radio_error(root, radio, language)
                return ctcss(value, 'l102') + f', CTCSS {receive_value} Hz {label("l248")}'
        return ctcss(value, 'l102' if state == b'\x01' else 'l103')
    if state in {b'\x03', b'\x06'}:
        data = civ(0x1B, 0x02)
        if data is None or len(data) != 3 or data[0] not in {0, 1, 16, 17} or any(b >> 4 > 9 or b & 15 > 9 for b in data[1:]):
            return yac._radio_error(root, radio, language)
        code = int(data[1:].hex())
        if code not in yac.ICOM_DCS_CODES:
            return yac._radio_error(root, radio, language)
        return dcs(f'{code:03d}', bool(data[0] & 16), bool(data[0] & 1) if state == b'\x03' else None)
    return yac._radio_error(root, radio, language)
