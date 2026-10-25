"""Catálogo público de Hugging Face para el gestor local."""
from i18n import tr
import threading
from urllib.parse import urlparse, parse_qs, quote
import requests
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk, GLib, Gio
from backend import variants, size_text

SORTS = [(tr('Tendencias'), 'trendingScore'), (tr('Más descargas'), 'downloads'), (tr('Actualizados recientemente'), 'lastModified'), (tr('Más favoritos'), 'likes')]


def search_options(value):
    value = value.strip()
    if not value.startswith(('https://', 'http://')):
        return None
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.hostname != 'huggingface.co' or parsed.path.rstrip('/') != '/models':
        raise ValueError(tr('Pega una URL de búsqueda de huggingface.co/models o escribe un nombre.'))
    query = parse_qs(parsed.query)
    sort = query.get('sort', ['trending'])[0]
    sort = {'trending': 'trendingScore', 'modified': 'lastModified'}.get(sort, sort)
    if sort not in [s[1] for s in SORTS]:
        raise ValueError(tr('Ese orden no está disponible. Usa tendencias, descargas, actualización o favoritos.'))
    return dict(search=query.get('search', [''])[0], sort=sort,
                uncensored='uncensored' in query.get('other', []) + query.get('filter', []),
                ollama='ollama' in query.get('apps', []),
                lmstudio='lmstudio' in query.get('apps', []),
                jan='jan' in query.get('apps', []))


def fetch_models(params=None, next_url=None):
    url = next_url or 'https://huggingface.co/api/models'
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'huggingface.co' or parsed.path != '/api/models':
        raise ValueError(tr('El catálogo devolvió una dirección inesperada.'))
    response = requests.get(url, params=params if not next_url else None, timeout=(10, 30))
    response.raise_for_status()
    return response.json(), response.links.get('next', {}).get('url')


class Explorer(Adw.Window):
    def __init__(self, parent):
        super().__init__(title=tr('Explorar modelos'), transient_for=parent, modal=True,
                         default_width=1040, default_height=760)
        self.parent_window = parent
        self.busy = False
        self.next_url = None
        self.count = 0
        self.connect('close-request', lambda *_: self.busy)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=tr('Explorar modelos'), subtitle='Hugging Face → Ollama → OpenCode'))
        root.append(header)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for edge in ('start','end','top','bottom'): getattr(controls,'set_margin_'+edge)(16)
        self.query = Gtk.Entry(placeholder_text=tr('Busca por nombre o pega una URL de búsqueda de Hugging Face'), hexpand=True)
        self.query.connect('activate', lambda *_: self.search())
        line = Gtk.Box(spacing=8)
        line.append(self.query)
        button = Gtk.Button(label=tr('Buscar'), css_classes=['suggested-action'])
        button.connect('clicked', lambda *_: self.search())
        line.append(button)
        self.spinner = Gtk.Spinner()
        line.append(self.spinner)
        controls.append(line)
        filters = Gtk.Box(spacing=16)
        self.application_choices = []
        for label in (tr('Todas'), 'Ollama', 'LM Studio', 'Jan'):
            radio = Gtk.CheckButton(label=label)
            if self.application_choices:
                radio.set_group(self.application_choices[0])
            radio.set_tooltip_text(tr('Filtra el catálogo de Hugging Face. La instalación sigue usando Ollama.'))
            self.application_choices.append(radio)
        self.application_choices[1].set_active(True)
        self.uncensored = Gtk.CheckButton(label=tr('Etiqueta uncensored'), active=True)
        filters.append(Gtk.Label(label=tr('Aplicación:')))
        for radio in self.application_choices:
            filters.append(radio)
        filters.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        filters.append(self.uncensored)
        filters.append(Gtk.Label(label='GGUF', css_classes=['dim-label']))
        self.sort = Gtk.DropDown.new_from_strings([x[0] for x in SORTS])
        filters.append(self.sort)
        controls.append(filters)
        self.controls = controls
        root.append(controls)
        self.status = Gtk.Label(label=tr('Busca modelos y compara sus archivos antes de descargar.'), xalign=0, wrap=True, margin_start=16, margin_end=16, margin_bottom=12)
        root.append(self.status)
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=16, margin_end=16, margin_bottom=16)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.results); root.append(scroll)
        self.more = Gtk.Button(label=tr('Cargar más resultados'), visible=False, margin_start=16, margin_end=16, margin_bottom=16)
        self.more.connect('clicked', lambda *_: self.search(more=True)); root.append(self.more)
        self.set_content(root)
        self.search()

    def run(self, work, done):
        if self.busy: return
        self.busy=True; self.spinner.start()
        self.controls.set_sensitive(False); self.results.set_sensitive(False); self.more.set_sensitive(False)
        def worker():
            try: result,error=work(),None
            except Exception as e: result,error=None,e
            GLib.idle_add(finish,result,error)
        def finish(result,error):
            self.busy=False; self.spinner.stop()
            self.controls.set_sensitive(True); self.results.set_sensitive(True); self.more.set_sensitive(True)
            if error: self.status.set_text(tr('No pudimos completar la consulta: {0}').format(error))
            else:
                try: done(result)
                except Exception as e: self.status.set_text(tr('No pudimos mostrar el resultado: {0}').format(e))
            return False
        threading.Thread(target=worker,daemon=True).start()

    def search(self, more=False):
        if self.busy: return
        try:
            imported = search_options(self.query.get_text()) if not more else None
            if imported:
                self.query.set_text(imported['search'])
                self.application_choices[3 if imported['jan'] else (2 if imported['lmstudio'] else (1 if imported['ollama'] else 0))].set_active(True)
                self.uncensored.set_active(imported['uncensored'])
                self.sort.set_selected([s[1] for s in SORTS].index(imported['sort']))
            params={'filter':'gguf' + (',uncensored' if self.uncensored.get_active() else ''),
                    'sort':SORTS[self.sort.get_selected()][1], 'direction':-1, 'limit':20, 'full':'true'}
            if self.query.get_text().strip(): params['search']=self.query.get_text().strip()
            application = next(value for value, radio in zip(('', 'ollama', 'lmstudio', 'jan'), self.application_choices) if radio.get_active())
            if application: params['apps'] = application
        except ValueError as e:
            self.status.set_text(str(e)); return
        url=self.next_url if more else None
        if more and not url:return
        self.status.set_text(tr('Buscando modelos en Hugging Face…'))
        def done(data):
            models,self.next_url=data
            if not more:
                child=self.results.get_first_child()
                while child:
                    self.results.remove(child); child=self.results.get_first_child()
                self.count=0
            for model in models:self.add_result(model)
            self.count+=len(models)
            self.more.set_visible(bool(self.next_url))
            self.status.set_text(tr('{0} resultados. Las etiquetas las publica cada autor; no garantizan compatibilidad ni calidad.').format(self.count) if self.count else tr('No encontramos modelos con esos filtros. Prueba otro nombre o desmarca una etiqueta.'))
        self.run(lambda:fetch_models(params,url),done)

    def add_result(self, model):
        name=model['id']
        group=Adw.PreferencesGroup(title=name, description=tr('Autor: {0} · {1:,} descargas · ♥ {2:,} · Actualizado: {3}').format(model.get('author') or name.split('/')[0], model.get('downloads', 0), model.get('likes', 0), model.get('lastModified', tr('Sin confirmar'))[:10]))
        row=Adw.ActionRow(title=tr('Ver detalles y archivos'), subtitle=tr('Tarea: {0} · Contexto y herramientas: sin confirmar').format(model.get('pipeline_tag', tr('Sin confirmar'))), activatable=True)
        row.set_subtitle_lines(2)
        row.add_prefix(Gtk.Image.new_from_icon_name('application-x-addon-symbolic'))
        row.add_suffix(Gtk.Image.new_from_icon_name('go-next-symbolic'))
        row.connect('activated',lambda *_:self.details(model))
        group.add(row);self.results.append(group)

    def details(self, model):
        self.status.set_text(tr('Leyendo la ficha y los archivos del modelo…'))
        name=model['id']; url='https://huggingface.co/'+name
        def work():
            response=requests.get('https://huggingface.co/api/models/'+quote(name,safe='/'),timeout=(10,30));response.raise_for_status()
            info=response.json()
            try: _,files,skipped=variants(url); error=None
            except Exception as e: files=[];skipped=0;error=str(e)
            readme=requests.get(url+'/raw/main/README.md',timeout=(10,30))
            text=readme.text[:12000] if readme.ok else tr('El autor no publicó una descripción accesible.')
            return info,files,skipped,error,text
        def done(data):
            info,files,skipped,error,text=data
            dialog=Adw.Window(title=name,transient_for=self,modal=True,default_width=820,default_height=680)
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
            box.append(Adw.HeaderBar())
            scroll=Gtk.ScrolledWindow(vexpand=True,hscrollbar_policy=Gtk.PolicyType.NEVER)
            body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14,margin_start=20,margin_end=20,margin_bottom=20)
            card=info.get('cardData') or {}
            details=tr('{0}\nLicencia publicada: {1}\nContexto y llamadas a herramientas: sin confirmar.\nLa compatibilidad final se comprueba con Ollama después de descargar.').format(name, card.get('license', tr('Sin confirmar')))
            body.append(Gtk.Label(label=details,xalign=0,wrap=True,selectable=True))
            body.append(Gtk.Label(label=tr('Archivos disponibles'),xalign=0,css_classes=['heading']))
            listing='\n'.join(f"{f['file']} — {size_text(f['size'])}" for f in files)
            body.append(Gtk.Label(label=listing or error or tr('Sin archivos compatibles.'),xalign=0,wrap=True,selectable=True))
            if skipped:body.append(Gtk.Label(label=tr('{0} fragmentos omitidos: este gestor usa GGUF de un solo archivo.').format(skipped),wrap=True,xalign=0))
            body.append(Gtk.Label(label=tr('Descripción del autor (Markdown)'),xalign=0,css_classes=['heading']))
            body.append(Gtk.Label(label=text,xalign=0,wrap=True,selectable=True))
            scroll.set_child(body);box.append(scroll)
            actions=Gtk.Box(spacing=10,margin_start=20,margin_end=20,margin_bottom=16)
            link=Gtk.LinkButton.new_with_label(url,tr('Abrir en Hugging Face'));actions.append(link)
            choose=Gtk.Button(label=tr('Elegir este modelo'),sensitive=bool(files),css_classes=['suggested-action'])
            def select(*_):
                parent=self.parent_window
                parent.new_model();parent.url.set_text(url);parent.inspect()
                dialog.close();self.close()
            choose.connect('clicked',select);actions.append(choose);box.append(actions)
            dialog.set_content(box);dialog.present()
            self.status.set_text(tr('Ficha cargada. Puedes revisar los tamaños antes de elegir.'))
        self.run(work,done)
