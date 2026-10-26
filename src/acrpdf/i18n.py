import gettext
import locale
import os

DOMAIN = "acrpdf"
LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")

_translation = gettext.NullTranslations()
_language = "en"


def setup(language=None):
    global _translation, _language
    languages = [language] if language else None
    _translation = gettext.translation(DOMAIN, LOCALE_DIR, languages=languages, fallback=True)
    _language = language or _system_language()


def _system_language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return value.split(":")[0].split(".")[0].split("_")[0] or "en"
    try:
        return (locale.getlocale()[0] or "en").split("_")[0]
    except ValueError:
        return "en"


def language():
    return _language


def _(message):
    return _translation.gettext(message)


def ngettext(singular, plural, n):
    return _translation.ngettext(singular, plural, n)


def N_(message):
    return message


LANGUAGES = {"": N_("System default"), "en": "English", "es": "Español", "fr": "Français", "pt": "Português"}
