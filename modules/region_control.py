"""Three-state Region control; r advances and persists, q finishes."""
from modules import chat_int, help_int, region_plan


def control(yac, root, language, read_key, watch=None):
    path = root / 'yac.ini'
    current = region_plan.selected(yac._read_settings(path))
    label = lambda token: yac._read_label(root, language, token, '')
    announce = lambda: chat_int.show_response(label('l368').format(value=current))
    announce()
    while True:
        try:
            key = read_key().casefold()
        except (EOFError, KeyboardInterrupt):
            chat_int.show_done(root, language)
            return
        if watch is not None and watch.lost:
            return
        if key == 'r':
            target = current % 3 + 1
            yac._set_yac_value(path, 'region', str(target))
            current = target
            announce()
        elif key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h034'))
        elif key == 'q':
            chat_int.show_done(root, language)
            return
