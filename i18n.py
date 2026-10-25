"""Español para sistemas en español; inglés como idioma de respaldo."""
import json
import os
from pathlib import Path


def detect_language(environment=None):
    env = os.environ if environment is None else environment
    override = env.get('MODELCRATE_LANGUAGE', '').strip()
    if override:
        value = override
    elif env.get('LC_ALL'):
        value = env['LC_ALL']
    else:
        value = env.get('LANGUAGE', '').split(':')[0] or env.get('LC_MESSAGES') or env.get('LANG') or 'en'
    return 'es' if value.lower().split('_')[0].split('-')[0].split('.')[0] == 'es' else 'en'


LANGUAGE = detect_language()
# También orienta las cadenas estándar de GTK; solo afecta a este proceso.
os.environ['LANGUAGE'] = LANGUAGE
CATALOG = json.loads((Path(__file__).parent / 'locales/en.json').read_text(encoding='utf-8'))


def tr(message):
    return message if LANGUAGE == 'es' else CATALOG.get(message, message)


def decimal_text(text):
    return text.replace('.', ',') if LANGUAGE == 'es' else text
