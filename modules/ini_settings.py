"""INI validation and failures, separate from radio and display handling."""
import configparser

LANGUAGES = {'en', 'de', 'es', 'pl'}
MAX_CALL_LENGTH = 10


class IniError(RuntimeError):
    def __init__(self, language='en'):
        super().__init__('INI Error')
        self.language = language if language in LANGUAGES else 'en'


def read_settings(path):
    if not path.exists():
        return {}
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str.casefold
    try:
        with path.open('r', encoding='utf-8-sig') as stream:
            parser.read_file(stream)
        if not parser.has_section('yac'):
            raise IniError
        settings = {key.casefold(): value.strip() for key, value in parser.items('yac')}
    except (OSError, UnicodeError, configparser.Error) as error:
        try:
            language = parser.get('yac', 'lang', fallback='en').casefold()
        except configparser.Error:
            language = 'en'
        raise IniError(language) from error
    language = settings.get('lang', '').casefold()
    if language and language not in LANGUAGES:
        raise IniError
    if len(settings.get('call', '')) > MAX_CALL_LENGTH:
        raise IniError(language)
    if settings.get('region', '1') not in {'1', '2', '3'}:
        raise IniError(language)
    platform = settings.get('platform', '').casefold()
    if platform and platform not in {'windows', 'linux', 'macos'}:
        raise IniError(language)
    return settings


def save_error(path, error):
    try:
        language = read_settings(path).get('lang', 'en').casefold()
    except IniError as existing:
        language = existing.language
    raise IniError(language) from error
