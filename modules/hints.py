"""Short factual messages, separate from labels and operating help."""


def get_hint(root, language, message_id, **values):
    path = root / 'lang' / language / 'hints' / message_id
    try:
        message = path.read_text(encoding='utf-8-sig').strip()
    except OSError:
        return ''
    return message.format(**values)
