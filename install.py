#!/usr/bin/env python3
"""Instala el lanzador del usuario sin sudo ni cambios en paquetes."""
from i18n import tr
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from backend import Audit

ID = 'io.github.modelcrate.ModelCrate'
ROOT = Path(__file__).resolve().parent


def paths():
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    return (Path.home() / '.local/bin/modelcrate', data / f'applications/{ID}.desktop',
            data / f'icons/hicolor/scalable/apps/{ID}.svg')


def install(uninstall=False):
    if sys.platform != 'linux':
        raise RuntimeError(tr('Esta versión se instala en Linux; Windows y macOS no están soportados.'))
    audit = Audit()
    command, desktop, icon = paths()
    if uninstall:
        for path in (command, desktop, icon):
            if path.exists():
                audit.backup(path, 'DESINSTALAR_APP')
                path.unlink()
        audit.record('DESINSTALAR_APP', tr('Retirados lanzador, acceso del menú e ícono. Modelos, ajustes y fuentes conservados.'))
        print(tr('ModelCrate desinstalado del menú. Tus modelos, ajustes y fuentes se conservan.'))
    else:
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        gi.require_version('WebKit', '6.0')
        import markdown
        import bleach
        from gi.repository import Gtk, Adw
        if (Adw.get_major_version(), Adw.get_minor_version()) < (1, 4):
            raise RuntimeError(tr('Necesitas libadwaita 1.4 o posterior.'))
        for path in (command, desktop, icon):
            audit.backup(path, 'INSTALAR_APP')
            path.parent.mkdir(parents=True, exist_ok=True)
        command.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(ROOT / 'app.py')) + ' "$@"\n')
        command.chmod(0o755)
        # Exec usa su propio formato de escape, no el del shell.
        escaped = str(command).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
        desktop.write_text(f'''[Desktop Entry]
Type=Application
Name=ModelCrate
Comment=Browse, download and manage local AI models
Comment[es]=Explora, descarga y organiza tus modelos de IA locales
Exec="{escaped}"
Icon={ID}
Terminal=false
Categories=Development;
Keywords=AI;Ollama;GGUF;Hugging Face;Models;
StartupNotify=true
StartupWMClass={ID}
''')
        shutil.copy2(ROOT / 'assets/modelcrate.svg', icon)
        audit.record('INSTALAR_APP', tr('Fuentes: {0}\nLanzador: {1}\nMenú: {2}\nÍcono: {3}').format(ROOT, command, desktop, icon))
        print(tr('ModelCrate instalado. Ábrelo desde el menú de aplicaciones. Mantén el repositorio en esta ruta.'))
    for executable, args in [('update-desktop-database', [str(desktop.parent)]),
                             ('gtk-update-icon-cache', ['-f', '-t', str(icon.parents[2])])]:
        if shutil.which(executable):
            subprocess.run([executable, *args], check=False, capture_output=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=tr('Instala ModelCrate para el usuario actual, sin sudo.'))
    parser.add_argument('--uninstall', action='store_true', help=tr('Retira el lanzador; conserva fuentes, modelos y ajustes.'))
    args = parser.parse_args()
    try:
        install(args.uninstall)
    except Exception as error:
        print(tr('No se pudo completar la instalación: {0}').format(error), file=sys.stderr)
        sys.exit(1)
