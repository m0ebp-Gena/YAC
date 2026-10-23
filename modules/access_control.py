"""Pi-image Speakup speech settings; other platforms keep their access software."""
import json
import logging
import os
import subprocess
import sys
import configparser

from modules import chat_int, help_int

LOG = logging.getLogger('yac')
HELPER = '/usr/local/libexec/yac-speakup-settings'
DEFAULTS = {'speech-rate': '2', 'speech-volume': '5',
            'speech-pitch': '5', 'speech-punctuation': 'some'}
PUNCT_LABELS = {'none': 'l312', 'some': 'l313', 'most': 'l325', 'all': 'l314'}
FIELDS = {'r': ('speech-rate', 'l300'), 'v': ('speech-volume', 'l301'),
          'p': ('speech-pitch', 'l302'), 'u': ('speech-punctuation', 'l303')}


def image_enabled():
    return sys.platform == 'linux' and os.environ.get('YAC_PI_IMAGE') == '1'


def bridge(request):
    result = subprocess.run(['sudo', '-n', HELPER], input=json.dumps(request) + '\n',
                            capture_output=True, text=True, timeout=30)
    reply = json.loads(result.stdout)
    if result.returncode or not reply.get('ok'):
        raise RuntimeError(reply.get('error', 'Speakup helper failed'))
    return reply


def mode_file():
    from pathlib import Path
    return Path.home() / '.config/yac/pi-launcher.ini'


def load_mode():
    import configparser
    config = configparser.ConfigParser(interpolation=None)
    config.read(mode_file(), encoding='utf-8')
    mode = config.get('launcher', 'access_mode', fallback='both')
    if mode not in MODES:
        raise ValueError('Invalid launcher access mode.')
    return mode


def save_mode(mode):
    import configparser
    import tempfile
    from pathlib import Path
    path = mode_file()
    if path.is_symlink():
        raise ValueError('Refusing a linked launcher INI.')
    config = configparser.ConfigParser(interpolation=None)
    config.read(path, encoding='utf-8')
    if not config.has_section('launcher'):
        config.add_section('launcher')
    config['launcher']['access_mode'] = mode
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            config.write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


MODES = {'both': 'l348', 'braille': 'l349', 'speech': 'l350'}


def control(root, language, read_key, watch, *, modes=False):
    def say(key, **values):
        chat_int.show_response(chat_int.label(root, language, key).format(**values))
    def announce(field, *, value_only=False):
        label = next(label for name, label in FIELDS.values() if name == field)
        if not value_only:
            say(label)
            return
        value = current[field]
        if field == 'speech-punctuation':
            value = chat_int.label(root, language, PUNCT_LABELS[value])
        chat_int.show_response(value)
    def change(changes):
        nonlocal current
        if not changes:
            return True
        try:
            current = bridge({'action': 'apply', 'changes': changes})['preferences']
            return True
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            LOG.exception('Could not apply Pi Speakup settings')
            say('l319')
            return False
    def apply_mode_selection():
        nonlocal mode
        previous = mode
        try:
            save_mode(selected_mode)
            try:
                bridge({'action': 'mode', 'mode': selected_mode})
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                save_mode(previous)
                bridge({'action': 'mode', 'mode': previous})
                raise
            mode = selected_mode
            return True
        except (OSError, RuntimeError, ValueError, configparser.Error, subprocess.SubprocessError):
            say('l319')
            return False
    if not image_enabled():
        say('l296')
        return
    try:
        if modes:
            mode = load_mode()
        else:
            current = bridge({'action': 'status'})['preferences']
    except (OSError, RuntimeError, ValueError, configparser.Error, subprocess.SubprocessError):
        say('l297')
        return
    if modes:
        selected_mode = mode
        say(MODES[selected_mode])
    else:
        selected = 'speech-rate'
        announce(selected)
    while True:
        key = read_key()
        if watch.lost:
            return
        if not key:
            continue
        key = key.casefold()
        if key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h024' if modes else 'h025'))
        elif key == 'q':
            if modes and selected_mode != mode:
                apply_mode_selection()
            chat_int.show_done(root, language)
            return
        elif modes and key in {'b', '.', ','}:
            choices = list(MODES)
            direction = -1 if key == ',' else 1
            selected_mode = choices[(choices.index(selected_mode) + direction) % len(choices)]
            say(MODES[selected_mode])
        elif not modes and key == 'o':
            choices = [field for field, label in FIELDS.values()]
            selected = choices[(choices.index(selected) + 1) % len(choices)]
            announce(selected)
        elif not modes and key in FIELDS:
            selected = FIELDS[key][0]
            announce(selected)
        elif not modes and key in {'.', ','}:
            direction = 1 if key == '.' else -1
            if selected == 'speech-punctuation':
                choices = list(PUNCT_LABELS)
                value = choices[max(0, min(3, choices.index(current[selected]) + direction))]
            else:
                value = str(max(1 if selected == 'speech-volume' else 0,
                                min(9, int(current[selected]) + direction)))
            if value == current[selected] or change({selected: value}):
                announce(selected, value_only=True)
        elif not modes and key == 'd':
            if change({k: v for k, v in DEFAULTS.items() if current[k] != v}):
                say('l316')
        elif not modes and key == 't':
            say('l323')
