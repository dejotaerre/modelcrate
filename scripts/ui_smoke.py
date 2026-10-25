#!/usr/bin/env python3
"""Prueba visual bilingüe sin red ni cambios en modelos."""
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Window, Adw, Gio, GLib
from explorer import Explorer
from backend import NoOpenCode
from i18n import LANGUAGE

expected=sys.argv[1]
assert LANGUAGE==expected,(LANGUAGE,expected)
app=Adw.Application(application_id='io.github.modelcrate.LanguageTest',flags=Gio.ApplicationFlags.NON_UNIQUE)
state={}

def activate(a):
    w=Window(a);w.present();state['window']=w
    GLib.timeout_add(150,check)

def check():
    w=state['window']
    if w.busy:return True
    if 'explorer' not in state:
        assert w.heading.get_text()==('Añadir un modelo' if expected=='es' else 'Add a model')
        assert w.save.get_child().get_label()==('Descargar y configurar' if expected=='es' else 'Download and configure')
        e=Explorer(w);e.present();state['explorer']=e;return True
    e=state['explorer']
    if e.busy:return True
    assert e.get_title()==('Explorar modelos' if expected=='es' else 'Explore models')
    assert e.application_choices[0].get_label()==('Todas' if expected=='es' else 'All')
    assert e.count==1
    print(f'GUI verified: {expected}',flush=True)
    app.quit();return False

with patch('backend.available_opencode',return_value=NoOpenCode('Demo')), patch('backend.Ollama.models',return_value=[]), patch('explorer.fetch_models',return_value=([{'id':'demo/model','downloads':10,'likes':2}],None)):
    app.connect('activate',activate);app.run([])
