"""Choose UI translations independently of the user's regional formats."""
import configparser
import locale
import os
from pathlib import Path


def _supported(value):
    for token in value.split(':'):
        name = token.strip().lower().split('.', 1)[0].split('@', 1)[0].replace('-', '_')
        if name == 'zh' or name.startswith('zh_'):
            return 'zh'
        if name in ('c', 'posix', 'en') or name.startswith('en_'):
            return 'en'
    return None


def detect_language(*, environ=None, home=None):
    """LANGUAGE / KDE translations / message locale / regional fallback.

    KDE deliberately allows Chinese labels with English date/number formats.
    Reading configuration here must not change the process or backend locale.
    """
    env = os.environ if environ is None else environ
    chosen = _supported(env.get('LANGUAGE', ''))
    if chosen:
        return chosen
    config_home = env.get('XDG_CONFIG_HOME', '')
    root = Path(config_home) if config_home and Path(config_home).is_absolute() else (
        Path.home() if home is None else Path(home)) / '.config'
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with (root / 'plasma-localerc').open(encoding='utf-8') as source:
            parser.read_file(source)
        chosen = _supported(parser.get('Translations', 'LANGUAGE', fallback=''))
        if chosen:
            return chosen
    except (OSError, UnicodeError, configparser.Error):
        pass
    for variable in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        chosen = _supported(env.get(variable, ''))
        if chosen:
            return chosen
    try:
        return _supported(locale.getlocale()[0] or '') or 'en'
    except (ValueError, TypeError):
        return 'en'
