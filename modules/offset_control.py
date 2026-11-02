"""Receive/transmit offset selection; clearing is always explicit."""
from modules import chat_int, help_int, hints, ts480_control


def verify(yac, root, radio, language):
    if radio.protocol == 'CAT' and radio.model_id == '020':
        state = ts480_control.offset_state(yac, radio) if ts480_control.variant(yac, radio) is not None else None
    elif yac._icom_supported(radio):
        state = (yac._icom_offset_hz(radio), yac._icom_clarifier_enabled(radio, 1),
                 yac._icom_clarifier_enabled(radio, 2))
    elif yac._yaesu_clarifier(radio):
        state = yac._yaesu_offset_state(radio)
    else:
        return yac._read_label(root, language, 'l129', '')
    if state is None or any(value is None for value in state):
        return yac._radio_error(root, radio, language)
    def value(selection):
        amount = state[0] if state[selection + 1] else 0
        sign = yac._read_label(root, language, 'l079' if amount > 0 else 'l080', '') + ' ' if amount else ''
        return f'{yac._offset_label(root, language, selection)} {sign}{abs(amount)}'
    return value(0) + ', ' + value(1)


def control(yac, root, radio, language, call, read_key, watch):
    selection = 0
    chat_int.show_response(yac._offset_label(root, language, selection))
    chat_int.show_response(hints.get_hint(root, language, 'm005'))
    while True:
        try:
            key = read_key().casefold()
        except (RuntimeError, OSError, EOFError, KeyboardInterrupt):
            return None
        if watch.lost:
            return key or 'w'
        if not key:
            continue
        if key == 'q':
            chat_int.show_done(root, language)
            return None
        if key == 'o':
            selection = 1 - selection
            chat_int.show_response(yac._offset_label(root, language, selection))
        elif key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h040'))
        elif key == 'v':
            chat_int.show_response(verify(yac, root, radio, language))
        elif key in {'c', '.', ','}:
            chat_int.show_request(call, key)
            chat_int.show_response(yac._offset_action(root, radio, language,
                                                    2 if key == 'c' else selection,
                                                    -1 if key == ',' else 1))
        else:
            return key
