"""Rutas del usuario y ajustes locales fuera del repositorio."""
import json
import os
from pathlib import Path

VERSION = '0.1.0'
APP_ID = 'io.github.modelcrate.ModelCrate'


def config_home():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')


def state_home():
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')


def audit_root():
    # La ruta opcional permite respetar una política local de respaldos.
    settings = config_home() / 'modelcrate/settings.json'
    if settings.exists():
        data = json.loads(settings.read_text())
        if data.get('audit_dir'):
            return Path(data['audit_dir']).expanduser()
    return state_home() / 'modelcrate'
