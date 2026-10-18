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
    """KDE translations / LANGUAGE / message locale / regional fallback.

    KDE deliberately allows Chinese labels with English date/number formats.
    Reading configuration here must not change the process or backend locale.
    """
    env = os.environ if environ is None else environ
    config_home = env.get('XDG_CONFIG_HOME', '')
    root = Path(config_home) if config_home and Path(config_home).is_absolute() else (
        Path.home() if home is None else Path(home)) / '.config'
    for filename, section, option in (
            ('plasma-localerc', 'Translations', 'LANGUAGE'),
            ('kdeglobals', 'Locale', 'Language')):
        parser = configparser.ConfigParser(interpolation=None)
        try:
            with (root / filename).open(encoding='utf-8') as source:
                parser.read_string(source.read(65536))
            chosen = _supported(parser.get(section, option, fallback=''))
            if chosen:
                return chosen
        except (OSError, UnicodeError, configparser.Error):
            pass
    for variable in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        chosen = _supported(env.get(variable, ''))
        if chosen:
            return chosen
    try:
        return _supported(locale.getlocale()[0] or '') or 'en'
    except (ValueError, TypeError):
        return 'en'
