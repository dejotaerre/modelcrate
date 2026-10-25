#!/usr/bin/env python3
"""Capturas reproducibles con datos de demostración y sin acceso a modelos reales."""
import argparse
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import Window, Adw, Gio, GLib, Gtk
from backend import NoOpenCode
from gi.repository import Graphene

parser=argparse.ArgumentParser()
parser.add_argument('--theme',choices=('dark','light'),required=True)
args=parser.parse_args()
models=[{'name':'qwen3:14b','size':9280000000},{'name':'qwen2.5-coder:7b','size':4680000000},{'name':'llama3.1:8b','size':4920000000}]
info={'parameters':'num_ctx 8192\nnum_predict 2048\ntemperature 0.6', 'capabilities':['completion','tools'], 'model_info':{'demo.context_length':32768}}
app=Adw.Application(application_id='io.github.modelcrate.Screenshot',flags=Gio.ApplicationFlags.NON_UNIQUE)
state={'phase':0}

def activate(a):
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK if args.theme=='dark' else Adw.ColorScheme.FORCE_LIGHT)
    window=Window(a);window.set_default_size(1160,960);window.present();state['window']=window
    GLib.timeout_add(300,capture)

def capture():
    w=state['window']
    if w.busy:return True
    if state['phase']==0:
        state['phase']=1;w.load_model('qwen3:14b');return True
    if state['phase']==1:
        state['phase']=2;return True
    snapshot=Gtk.Snapshot.new();paint=Gtk.WidgetPaintable.new(w)
    paint.snapshot(snapshot,w.get_width(),w.get_height())
    rect=Graphene.Rect();rect.init(0,0,w.get_width(),w.get_height())
    path=ROOT/'docs/screenshots'/f'modelcrate-{args.theme}.png'
    w.get_renderer().render_texture(snapshot.to_node(),rect).save_to_png(str(path))
    print(path);app.quit();return False

with patch('backend.available_opencode',return_value=NoOpenCode('Vista de demostración · Gestión local con Ollama')), patch('backend.Ollama.models',return_value=models), patch('backend.Ollama.show',return_value=info):
    app.connect('activate',activate)
    app.run([])
