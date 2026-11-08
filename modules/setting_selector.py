"""Read a setting before accepting an explicit selection change."""
from modules import chat_int, help_int


def control(root, language, read_current, change, read_key, watch, repeat_key,
            help_id='h041', *, forward_command=False):
    chat_int.show_response(read_current())
    while True:
        try:
            key = read_key().casefold()
        except (EOFError, KeyboardInterrupt, RuntimeError, OSError):
            return
        if watch.lost:
            return
        if key == 'q':
            chat_int.show_done(root, language)
            return
        if key == 'h':
            chat_int.show_response(help_int.get_help(root, language, help_id))
        elif key in {'.', ',', repeat_key}:
            chat_int.show_response(change(-1 if key == ',' else 1))
        elif key and forward_command:
            return key


def vfo(yac, root, radio, language, read_key, watch):
    def current():
        if radio.protocol == 'CAT' and radio.model_id == '020':
            if yac.ts480_control.variant(yac, radio) is None:
                return yac._read_label(root, language, 'l129', '')
            selected = yac.ts480_control.vfo(yac, radio)
            if selected is None:
                return yac._radio_error(root, radio, language)
            return 'VFO ' + ('B' if selected == '1' else 'A')
        if yac._ftx1(radio):
            return 'Sub' if yac._yaesu_vfo_side else 'Main'
        # The existing Icom profiles have no selected-VFO read command.
        # Do not select A just to establish a starting point.
        return yac._read_label(root, language, 'l409', '')

    def change(direction):
        if radio.protocol == 'CAT' and radio.model_id == '020':
            return yac.ts480_control.select_vfo(yac, root, radio, language)
        if yac._icom_supported(radio):
            return yac._icom_select_vfo(root, radio, language)
        yac._yaesu_vfo_side = 1 - yac._yaesu_vfo_side
        return current()

    if not (yac._icom_supported(radio) or yac._ftx1(radio)
            or radio.protocol == 'CAT' and radio.model_id == '020'):
        chat_int.show_response(yac._read_label(root, language, 'l129', ''))
        return
    control(root, language, current, change, read_key, watch, 'v', help_id='h068')
