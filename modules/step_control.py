"""Edit YAC's per-mode tuning step; never change a radio setting."""
from modules import chat_int, help_int


def control(yac, root, radio, language, settings):
    def say(token, fallback):
        chat_int.show_response(yac._read_label(root, language, token, fallback))

    while True:
        profile = yac._step_size_key(yac._current_mode(radio))
        if profile is None:
            say('l072', 'NOT Understood.')
            return
        setting_key, mode_name = profile
        chat_int.show_step_size_prompt(root, language, mode_name,
                                       yac._step_size_value(settings, setting_key))
        try:
            entered = input().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            say('l355', 'Aborted')
            return
        if entered.casefold() == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h067'))
            continue
        if not entered or entered.casefold() == 'q':
            say('l355', 'Aborted')
            return
        try:
            value = int(entered)
        except ValueError:
            value = 0
        if not entered.isascii() or not entered.isdecimal() or value <= 0:
            say('l356', 'Invalid')
            return
        yac._set_yac_value(root / 'yac.ini', setting_key, str(value))
        settings[setting_key] = str(value)
        template = yac._read_label(root, language, 'l070', 'Step size {value} Hz applied.')
        chat_int.show_response(template.format(value=value))
        return
