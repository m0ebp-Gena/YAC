"""Confirm a main-command quit without closing the controller first."""
from modules import chat_int


def confirm(root, language, read_key):
    prompt = chat_int.label(root, language, 'l352', 'Quit YAC? y/n')
    chat_int.show_response(prompt)
    while True:
        try:
            key = read_key().casefold()
        except (EOFError, KeyboardInterrupt, OSError, RuntimeError):
            key = 'n'
        if key == 'y':
            return True
        if key in {'n', 'q'}:
            chat_int.show_response(chat_int.label(root, language, 'l353', 'Quit cancelled.'))
            return False
        if key:
            chat_int.show_response(prompt)
