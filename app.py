#!/usr/bin/python
"""Ventana nativa para Ollama y OpenCode."""
from i18n import tr, decimal_text
import re
import sys
import threading
from pathlib import Path
from runtime import APP_ID, VERSION

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk, Gdk
from hardware import detect, recommend, summary
from explorer import Explorer
from backend import Ollama, Cancelled, canonical, parse_parameters, size_text, variants, validate_parameters


def variant_labels(files):
    labels = []
    for f in files:
        filename = f['file'].rsplit('/', 1)[-1].removesuffix('.gguf')
        match = re.search(r'(?:^|[-_.])((?:IQ|Q)\d[A-Za-z0-9_]*|BF16|F16|F32|FP16|FP32)(?=$|[-.])', filename, re.I)
        quant = match.group(1).upper() if match else filename
        extra = ' · noMTP' if 'nomtp' in filename.lower() else ''
        labels.append(f"{quant} · {decimal_text(size_text(f['size']))}{extra}")
    # Se distinguen también archivos con igual cuantización y tamaño.
    return [tr('{0} · opción {1}').format(label, i + 1) if labels.count(label) > 1 else label
            for i, label in enumerate(labels)]


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='ModelCrate', default_width=1080, default_height=840)
        self.add_css_class('model-manager')
        css = Gtk.CssProvider()
        css.load_from_data(b"""
.model-manager .hero { background: linear-gradient(110deg, alpha(@accent_color, .20), alpha(#9069dc, .12)); border-radius: 18px; padding: 18px; }
.model-manager .hero-icon { color: #35b8ab; }
.model-manager .tone-teal { color: #2ab4a5; }
.model-manager .tone-blue { color: #629ce8; }
.model-manager .tone-purple { color: #b28be7; }
.model-manager .tone-orange { color: #df9c45; }
.model-manager .model-icon { padding: 8px; border-radius: 10px; background: alpha(currentColor, .12); }
.model-manager row.current-model { background: alpha(@accent_color, .16); box-shadow: inset 3px 0 @accent_color; }
.model-manager .new-model { background: alpha(@accent_color, .15); }
.model-manager .status-line { margin-top: 6px; margin-bottom: 8px; }
.model-manager .tools-button { background: alpha(#9069dc, .18); }
.model-manager progressbar progress { background: linear-gradient(90deg, #209cba, #35c7a5); }
        """)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.api = Ollama()
        self.busy = False
        self.selected = None
        self.files = []
        self.hardware = None
        self.recommended_index = None
        self.names = []
        self.source = None
        self.can_cancel = False
        self.connect('close-request', self.closing)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title='ModelCrate')
        header.set_title_widget(title)
        header.pack_start(Gtk.Image.new_from_file(str(Path(__file__).parent / 'assets/modelcrate.svg')))
        self.refresh = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text=tr('Actualizar modelos instalados'))
        self.refresh.connect('clicked', lambda _: self.reload())
        header.pack_end(self.refresh)
        root.append(header)
        self.status = Gtk.Label(label=tr('Conectando con Ollama…'), xalign=0, wrap=True)
        self.status.add_css_class('status-line')
        self.status.set_margin_start(24)
        self.status.set_margin_end(24)
        root.append(self.status)
        self.integration_info = Gtk.Label(label=self.api.config.reason, xalign=0, wrap=True,
                                          margin_start=24, margin_end=24)
        self.integration_info.add_css_class('dim-label')
        root.append(self.integration_info)
        self.bar = Gtk.ProgressBar(show_text=True, visible=False)
        self.bar.set_margin_start(24)
        self.bar.set_margin_end(24)
        self.bar.set_margin_top(10)
        root.append(self.bar)
        self.cancel = Gtk.Button(label=tr('Cancelar descarga'), halign=Gtk.Align.END, visible=False)
        self.cancel.set_margin_end(24)
        self.cancel.connect('clicked', self.cancel_download)
        root.append(self.cancel)
        content = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=300)
        content.set_vexpand(True)
        root.append(content)
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.sidebar.set_margin_start(16)
        self.sidebar.set_margin_end(12)
        self.sidebar.set_margin_top(16)
        self.sidebar.set_margin_bottom(16)
        self.sidebar.set_size_request(250, -1)
        label = Gtk.Label(label=tr('INSTALADOS'), xalign=0)
        label.add_css_class('heading')
        self.sidebar.append(label)
        self.new_button = Gtk.Button(label=tr('＋ Descargar otro modelo'))
        self.new_button.set_child(Adw.ButtonContent(icon_name='list-add-symbolic', label=tr('Descargar otro modelo')))
        self.new_button.add_css_class('new-model')
        self.new_button.connect('clicked', lambda _: self.new_model())
        self.sidebar.append(self.new_button)
        explore = Gtk.Button()
        explore.set_child(Adw.ButtonContent(icon_name='system-search-symbolic', label=tr('Explorar modelos')))
        explore.connect('clicked', lambda _: Explorer(self).present())
        self.sidebar.append(explore)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.add_css_class('boxed-list')
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.listbox)
        self.sidebar.append(scroll)
        content.set_start_child(self.sidebar)
        scroll2 = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(self.form, 'set_margin_' + side)(24)
        scroll2.set_child(self.form)
        content.set_end_child(scroll2)
        self.heading = Gtk.Label(label=tr('Añadir un modelo'), xalign=0)
        self.heading.add_css_class('title-1')
        hero = Gtk.Box(spacing=16)
        hero.add_css_class('hero')
        hero_icon = Gtk.Image.new_from_icon_name('application-x-addon-symbolic')
        hero_icon.set_pixel_size(36)
        hero_icon.add_css_class('hero-icon')
        hero.append(hero_icon)
        self.heading.set_wrap(True)
        hero.append(self.heading)
        self.form.append(hero)
        self.download_group = Adw.PreferencesGroup(title=tr('Desde Hugging Face'), description=tr('Pega el enlace del modelo en Hugging Face. Puedes usar modelos públicos en un único archivo GGUF.'))
        self.url = Adw.EntryRow(title=tr('Escribe o pega la URL del modelo'))
        self.url.connect('changed', self.invalidate_source)
        self.url.add_prefix(self.colored_icon('insert-link-symbolic', 'tone-blue'))
        self.download_group.add(self.url)
        self.lookup_spinner = Gtk.Spinner(visible=False, valign=Gtk.Align.CENTER,
                                          tooltip_text=tr('Buscando variantes…'))
        self.url.add_suffix(self.lookup_spinner)
        self.url_focus = Gtk.EventControllerFocus.new()
        self.url_focus.connect('leave', self.url_focus_left)
        self.url.add_controller(self.url_focus)
        self.url.connect('entry-activated', self.inspect)
        self.variant = Adw.ComboRow(title=tr('Variante y tamaño'), model=Gtk.StringList.new([tr('Escribe una URL para ver las variantes')]))
        self.variant.connect('notify::selected', self.variant_changed)
        self.variant.add_prefix(self.colored_icon('package-x-generic-symbolic', 'tone-purple'))
        self.download_group.add(self.variant)
        self.preference = Adw.ComboRow(title=tr('Prioridad'), model=Gtk.StringList.new([tr('Más velocidad'), tr('Equilibrio'), tr('Más calidad')]))
        self.preference.set_selected(1)
        self.preference.connect('notify::selected', lambda *_: self.update_recommendation())
        self.download_group.add(self.preference)
        self.hardware_info = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.hardware_info.add_css_class('dim-label')
        self.download_group.add(self.hardware_info)
        self.advice = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.download_group.add(self.advice)
        actions = Gtk.Box(spacing=8)
        self.apply_advice = Gtk.Button(label=tr('Usar recomendación'), sensitive=False)
        self.apply_advice.connect('clicked', lambda *_: self.apply_recommendation())
        actions.append(self.apply_advice)
        refresh_hardware = Gtk.Button(label=tr('Actualizar memoria'))
        refresh_hardware.connect('clicked', self.refresh_hardware)
        actions.append(refresh_hardware)
        self.download_group.add(actions)
        self.form.append(self.download_group)
        self.details = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.details.add_css_class('dim-label')
        self.form.append(self.details)
        group = Adw.PreferencesGroup(title=tr('Configuración del modelo'), description=tr('Estos ajustes se guardan en Ollama y, si está habilitada la integración, en OpenCode. Más contexto necesita más memoria.'))
        self.name = Adw.EntryRow(title=tr('Nombre local'))
        self.name.add_prefix(self.colored_icon('edit-symbolic', 'tone-teal'))
        group.add(self.name)
        self.spins = {}
        for key, label, low, high, step, value, digits in [
            ('num_ctx', tr('Contexto (tokens)'), 512, 262144, 1024, 8192, 0),
            ('num_predict', tr('Máximo de salida (tokens)'), 1, 131072, 512, 2048, 0),
            ('temperature', tr('Temperatura'), 0, 2, .1, .6, 2)]:
            group.add(self.spin_row(key, label, low, high, step, value, digits))
        self.make_default = Adw.SwitchRow(title=tr('Usar por defecto en OpenCode'))
        self.make_default.add_prefix(self.colored_icon('starred-symbolic', 'tone-orange'))
        self.make_default.set_visible(self.api.config.enabled)
        group.add(self.make_default)
        self.form.append(group)
        advanced = Adw.PreferencesGroup(title=tr('Opciones avanzadas'))
        for args in [('top_p', 'Top-p', .01, 1, .05, .95, 2),
                     ('top_k', 'Top-k', 1, 1000, 1, 40, 0),
                     ('repeat_penalty', tr('Penalización de repetición'), .1, 3, .05, 1.0, 2)]:
            advanced.add(self.spin_row(*args))
        expander = Gtk.Expander(label=tr('Muestreo e instrucciones propias'))
        advanced_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        advanced_box.append(advanced)
        advanced_box.append(Gtk.Label(label=tr('Mensaje de sistema opcional de Ollama'), xalign=0))
        self.system = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, height_request=100)
        self.system.set_top_margin(8)
        self.system.set_left_margin(8)
        sys_scroll = Gtk.ScrolledWindow(min_content_height=100)
        sys_scroll.set_child(self.system)
        advanced_box.append(sys_scroll)
        advanced_box.append(Gtk.Label(label=tr('OpenCode envía sus propias instrucciones; este mensaje no sustituye AGENTS.md ni CODEX.md.'), wrap=True, xalign=0))
        expander.set_child(advanced_box)
        self.form.append(expander)
        buttons = Gtk.Box(spacing=10)
        self.save = Gtk.Button(label=tr('Descargar y configurar'))
        self.save.set_child(Adw.ButtonContent(icon_name='folder-download-symbolic', label=tr('Descargar y configurar')))
        self.save.add_css_class('suggested-action')
        self.save.connect('clicked', self.save_clicked)
        buttons.append(self.save)
        self.test = Gtk.Button(label=tr('Probar herramientas'), visible=False)
        self.test.set_child(Adw.ButtonContent(icon_name='applications-engineering-symbolic', label=tr('Probar herramientas')))
        self.test.add_css_class('tools-button')
        self.test.connect('clicked', self.test_clicked)
        buttons.append(self.test)
        self.remove = Gtk.Button(label=tr('Desinstalar'), visible=False)
        self.remove.set_child(Adw.ButtonContent(icon_name='user-trash-symbolic', label=tr('Desinstalar')))
        self.remove.add_css_class('destructive-action')
        self.remove.connect('clicked', self.remove_clicked)
        buttons.append(self.remove)
        self.form.append(buttons)
        self.note = Gtk.Label(label=tr('Si le das otro nombre, también verás el modelo original en la lista. Ambos comparten los mismos archivos, sin duplicar la descarga.'), xalign=0, wrap=True)
        self.note.add_css_class('dim-label')
        self.form.append(self.note)
        self.set_content(root)
        self.reload()

    @staticmethod
    def colored_icon(name, tone):
        icon = Gtk.Image.new_from_icon_name(name)
        icon.add_css_class(tone)
        return icon

    def mark_selected(self):
        row = self.listbox.get_first_child()
        while row:
            if getattr(row, 'model_name', None) == self.selected:
                row.add_css_class('current-model')
            else:
                row.remove_css_class('current-model')
            row = row.get_next_sibling()

    def spin_row(self, key, label, low, high, step, value, digits):
        row = Adw.ActionRow(title=label)
        icons = {'num_ctx': ('view-grid-symbolic', 'tone-blue'), 'num_predict': ('text-x-generic-symbolic', 'tone-teal'), 'temperature': ('weather-clear-symbolic', 'tone-orange')}
        icon, tone = icons.get(key, ('preferences-system-symbolic', 'tone-purple'))
        row.add_prefix(self.colored_icon(icon, tone))
        spin = Gtk.SpinButton.new_with_range(low, high, step)
        spin.set_value(value)
        spin.set_digits(digits)
        spin.set_valign(Gtk.Align.CENTER)
        row.add_suffix(spin)
        self.spins[key] = spin
        if key == 'num_ctx':
            spin.connect('value-changed', lambda *_: self.update_recommendation())
        return row

    def closing(self, *_):
        if self.busy:
            self.status.set_text(tr('Todavía hay una tarea en marcha. Espera a que termine o cancela la descarga antes de cerrar.'))
        return self.busy

    def cancel_download(self, *_):
        if not self.can_cancel:
            return
        self.api.stop()
        self.cancel.set_sensitive(False)
        self.status.set_text(tr('Cancelando la transferencia… Los bloques parciales los gestiona Ollama.'))

    def progress(self, fraction, message):
        GLib.idle_add(self.update_progress, fraction, message)

    def update_progress(self, fraction, message):
        self.bar.set_visible(True)
        self.status.set_text(message)
        if fraction is None:
            self.bar.pulse()
            self.bar.set_text(tr('Procesando'))
        else:
            self.bar.set_fraction(max(0, min(1, fraction)))
            self.bar.set_text(tr('{0:.0%} del archivo actual').format(fraction))

    def run(self, work, done=None, cancellable=False):
        if self.busy:
            return
        self.busy = True
        self.can_cancel = cancellable
        self.api.cancel.clear()
        self.form.set_sensitive(False)
        self.sidebar.set_sensitive(False)
        self.refresh.set_sensitive(False)
        self.cancel.set_sensitive(True)
        self.cancel.set_visible(cancellable)
        self.bar.set_fraction(0)
        self.bar.set_visible(cancellable)
        self.bar.set_text(tr('Trabajando…'))
        def worker():
            try:
                result, error = work(), None
            except Exception as e:
                result, error = None, e
            GLib.idle_add(self.finished, result, error, done)
        threading.Thread(target=worker, daemon=True).start()

    def finished(self, result, error, done):
        self.lookup_spinner.stop()
        self.lookup_spinner.set_visible(False)
        self.busy = False
        self.can_cancel = False
        self.form.set_sensitive(True)
        self.sidebar.set_sensitive(True)
        self.refresh.set_sensitive(True)
        self.cancel.set_visible(False)
        self.bar.set_visible(False)
        if error:
            cancelled = isinstance(error, Cancelled) or self.api.cancel.is_set()
            self.status.set_text(tr('Cancelaste la descarga. Si la vuelves a iniciar, Ollama puede aprovechar lo que ya descargó.') if cancelled else str(error))
            self.bar.set_text(tr('Cancelado') if cancelled else tr('No completado'))
            if not cancelled:
                self.api.audit.record('ERROR', str(error))
        else:
            self.bar.set_fraction(1)
            self.bar.set_text(tr('Completado'))
            if done:
                try:
                    done(result)
                except Exception as e:
                    self.status.set_text(str(e))
                    self.bar.set_text(tr('No completado'))

    def reload(self):
        self.status.set_text(tr('Buscando tus modelos instalados…'))
        self.run(self.api.models, self.populate)

    def populate(self, models):
        child = self.listbox.get_first_child()
        while child:
            self.listbox.remove(child)
            child = self.listbox.get_first_child()
        self.names = [m['name'] for m in models]
        for m in sorted(models, key=lambda x: x['name']):
            row = Adw.ActionRow(title=m['name'], subtitle=size_text(m.get('size', 0)), activatable=True)
            row.model_name = m['name']
            cloud = m['name'].endswith(':cloud')
            tone = 'tone-purple' if cloud else ('tone-teal' if 'qwen' in m['name'].lower() else 'tone-blue')
            icon = self.colored_icon('network-server-symbolic' if cloud else 'application-x-addon-symbolic', tone)
            icon.add_css_class('model-icon')
            row.add_prefix(icon)
            row.set_title_lines(2)
            row.set_tooltip_text(m['name'])
            row.connect('activated', lambda _, n=m['name']: self.load_model(n))
            self.listbox.append(row)
        self.mark_selected()
        self.status.set_text(tr('{0} modelos en Ollama · Guardamos una copia de los ajustes antes de cambiarlos').format(len(models)))

    def new_model(self):
        self.selected = None
        self.mark_selected()
        self.heading.set_text(tr('Añadir un modelo'))
        self.download_group.set_visible(True)
        self.name.set_text('')
        self.name.set_editable(True)
        self.details.set_text('')
        self.save.set_sensitive(True)
        self.save.get_child().set_label(tr('Descargar y configurar'))
        self.save.get_child().set_icon_name('folder-download-symbolic')
        self.test.set_visible(False)
        self.remove.set_visible(False)
        for k, v in dict(num_ctx=8192, num_predict=2048, temperature=.6, top_p=.95, top_k=40, repeat_penalty=1).items():
            self.spins[k].set_value(v)
        self.system.get_buffer().set_text('')
        self.make_default.set_active(False)
        self.variant_changed()

    def invalidate_source(self, *_):
        self.files = []
        self.source = None
        self.recommended_index = None
        if hasattr(self, 'advice'):
            self.advice.set_text('')
            self.apply_advice.set_sensitive(False)
        if hasattr(self, 'variant'):
            self.variant.set_model(Gtk.StringList.new([tr('Se buscarán al salir del campo de URL')]))

    def url_focus_left(self, *_):
        GLib.idle_add(self.lookup_after_focus)

    def lookup_after_focus(self):
        if not self.busy and self.selected is None and not self.files:
            self.inspect()
        return False

    def inspect(self, *_):
        if self.busy or not self.url.get_text().strip() or self.files:
            return
        self.lookup_spinner.set_visible(True)
        self.lookup_spinner.start()
        self.status.set_text(tr('Buscando las variantes del modelo en Hugging Face…'))
        url = self.url.get_text()
        def done(result):
            (repo, self.files, skipped), self.hardware = result
            self.variant.set_model(Gtk.StringList.new(variant_labels(self.files)))
            self.update_recommendation()
            self.variant.set_selected(self.recommended_index if self.recommended_index is not None else Gtk.INVALID_LIST_POSITION)
            self.variant_changed()
            self.name.set_text(re.sub(r'[^a-z0-9._-]', '-', repo.split('/')[-1].lower().removesuffix('-gguf')))
            self.status.set_text(tr('{0} variantes disponibles. Elige la que quieras y pulsa Descargar y configurar para empezar.').format(len(self.files)))
        self.run(lambda: (variants(url), detect()), done)

    def update_recommendation(self):
        if not self.hardware or not self.files or 'num_ctx' not in self.spins:
            return
        context = int(self.spins['num_ctx'].get_value())
        self.recommended_index, reason = recommend(self.files, self.hardware, context, self.preference.get_selected())
        self.hardware_info.set_text(summary(self.hardware))
        label = variant_labels(self.files)[self.recommended_index] if self.recommended_index is not None else tr('Sin recomendación')
        self.advice.set_text(tr('Recomendación orientativa: {0}\n{1}\nPuedes cambiar la variante. Si ajustas el contexto o la prioridad, pulsa Usar recomendación para aplicarla.').format(label, reason))
        self.apply_advice.set_sensitive(self.recommended_index is not None)

    def apply_recommendation(self):
        if self.recommended_index is not None:
            self.variant.set_selected(self.recommended_index)

    def refresh_hardware(self, *_):
        def done(hardware):
            self.hardware = hardware
            self.hardware_info.set_text(summary(hardware))
            self.update_recommendation()
            self.status.set_text(tr('Memoria actualizada. Puedes aplicar la nueva recomendación si quieres.'))
        self.run(detect, done)

    def variant_changed(self, *_):
        if self.selected is None:
            self.source = None
        if self.selected is None and self.files:
            i = self.variant.get_selected()
            if i < len(self.files):
                f = self.files[i]
                self.source = f['source']
                self.variant.set_tooltip_text(f['file'])
                self.details.set_text(tr('Archivo seleccionado: {0}\nDescarga: {1}. Recuerda que el contexto también necesita memoria.').format(f['file'], decimal_text(size_text(f['size']))))

    def load_model(self, name):
        def done(info):
            self.selected = self.source = name
            self.mark_selected()
            self.heading.set_text(tr('Configurar modelo instalado'))
            self.download_group.set_visible(False)
            self.name.set_text(name)
            self.name.set_editable(False)
            self.save.get_child().set_label(tr('Guardar ajustes'))
            self.save.get_child().set_icon_name('document-save-symbolic')
            cloud = bool(info.get('remote_model')) or name.endswith(':cloud')
            self.save.set_sensitive(not cloud)
            self.test.set_visible(not cloud)
            self.remove.set_visible(True)
            params = parse_parameters(info.get('parameters', ''))
            cfg, _ = self.api.config.read()
            defaults = dict(num_ctx=8192, num_predict=2048, temperature=.6, top_p=.95, top_k=40, repeat_penalty=1)
            for key, fallback in defaults.items():
                self.spins[key].set_value(float(params.get(key, fallback)))
            self.system.get_buffer().set_text(info.get('system', ''))
            current = self.api.config.model_id(cfg)
            self.make_default.set_active(current in (f'ollama/{name}', f'ollama/{name.removesuffix(":latest")}'))
            caps = ', '.join(info.get('capabilities', [])) or tr('Sin capacidades declaradas')
            max_ctx = next((v for k, v in info.get('model_info', {}).items() if k.endswith('.context_length')), tr('No declarado'))
            self.details.set_text(tr('Según Ollama, este modelo admite: {0}\nContexto máximo que indica el modelo: {1}\nSi falta algún ajuste, te mostramos un valor inicial. Nada cambia hasta que pulses Guardar.').format(caps, max_ctx))
            self.status.set_text(tr('Este modelo funciona en la nube. Puedes quitarlo de la lista, pero no ajustar archivos locales.') if cloud else tr('Ya puedes cambiar sus ajustes. Al guardar, no tendrás que descargar el modelo otra vez.'))
        self.run(lambda: self.api.show(name), done)

    def feedback(self, title, message):
        dialog = Adw.MessageDialog(transient_for=self, heading=title, body=message)
        dialog.add_response('ok', tr('Entendido'))
        dialog.set_default_response('ok')
        dialog.set_close_response('ok')
        dialog.present()

    def save_clicked(self, *_):
        name = self.name.get_text().strip()
        if not self.source:
            if self.files:
                self.feedback(tr('Elige una variante'), tr('No hay una variante seleccionada. Revisa los archivos disponibles y elige uno antes de descargar.'))
            elif self.url.get_text().strip():
                self.inspect()
            else:
                self.feedback(tr('Falta la URL del modelo'), tr('Escribe o pega el enlace de Hugging Face para buscar los archivos disponibles.'))
                self.url.grab_focus()
            return
        if not self.selected and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]*(?::[a-zA-Z0-9._-]+)?', name):
            self.status.set_text(tr('Usa un nombre local con letras, números, guiones o puntos, y una etiqueta opcional :nombre.'))
            return
        params = {k: (int(w.get_value()) if k in ('num_ctx', 'num_predict', 'top_k') else w.get_value()) for k, w in self.spins.items()}
        try:
            validate_parameters(params)
            self.api.config.read()
            if not self.selected and canonical(name) in [canonical(n) for n in self.names]:
                raise ValueError(tr('Ese nombre ya existe. Selecciónalo en Instalados para editarlo.'))
        except Exception as e:
            self.status.set_text(str(e))
            return
        buf = self.system.get_buffer()
        system = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        source, installed, default = self.source, self.selected, self.make_default.get_active()
        self.status.set_text(tr('Iniciando descarga de {0}…').format(name) if not installed else tr('Guardando configuración de {0}…').format(name))
        def work():
            if not installed:
                self.api.audit.record('INICIO_DESCARGA', tr('Origen: {0}; nombre deseado: {1}').format(source, name))
                self.api.stream('pull', {'model': source}, self.progress)
            if self.api.cancel.is_set():
                raise Cancelled()
            self.can_cancel = False
            if self.api.cancel.is_set():
                raise Cancelled()
            GLib.idle_add(self.cancel.set_visible, False)
            self.progress(None, tr('Guardando tus ajustes…'))
            self.api.configure(source, name, params, system, default, self.progress)
            return self.api.models()
        def done(models):
            self.populate(models)
            target = tr('Ollama y OpenCode') if self.api.config.enabled else 'Ollama'
            self.status.set_text(tr('{0} ya está listo en {1}.').format(name, target))
            self.feedback(tr('Modelo listo'), tr('{0} ya está listo en {1}.').format(name, target))
        self.run(work, done, cancellable=not bool(installed))

    def test_clicked(self, *_):
        dialog = Adw.MessageDialog(transient_for=self, heading=tr('Probar llamadas a herramientas'),
            body=tr('Vamos a cargar el modelo y hacer dos consultas a Ollama. La prueba solo intercambia un código aleatorio: no ejecuta comandos ni accede a tu red.'))
        dialog.add_response('cancel', tr('Cancelar'))
        dialog.add_response('test', tr('Probar'))
        dialog.set_response_appearance('test', Adw.ResponseAppearance.SUGGESTED)
        dialog.connect('response', lambda _, response: self.run(lambda: self.api.test_tools(self.selected), self.status.set_text) if response == 'test' else None)
        dialog.present()

    def remove_clicked(self, *_):
        try:
            cfg, _ = self.api.config.read()
        except Exception as e:
            self.status.set_text(str(e))
            return
        name = self.selected
        current = self.api.config.model_id(cfg)
        affected = current in (f'ollama/{name}', f'ollama/{name.removesuffix(":latest")}')
        choices = [f'{p}/{m}' for p, v in cfg.get('providers', {}).items() for m in v.get('models', {}) if not (p == 'ollama' and canonical(m) == canonical(name))]
        if affected and not choices:
            self.status.set_text(tr('Añade otro modelo a OpenCode antes de quitar el que usas por defecto.'))
            return
        dialog = Adw.MessageDialog(transient_for=self, heading=tr('¿Desinstalar este modelo?'),
            body=tr('{0}\n\nVas a quitar este modelo de Ollama.').format(name) + (tr(' También se retirará del catálogo de OpenCode.') if self.api.config.enabled else tr(' La configuración de otras aplicaciones no se actualizará.')) + tr(' Ollama conserva los archivos que compartan otros modelos. Guardamos una copia de los ajustes, pero no de los archivos del modelo. Tus conversaciones se conservan.'))
        picker = None
        if affected:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.append(Gtk.Label(label=tr('¿Qué modelo quieres usar por defecto en OpenCode?')))
            picker = Gtk.DropDown.new_from_strings(choices)
            box.append(picker)
            dialog.set_extra_child(box)
        dialog.add_response('cancel', tr('Cancelar'))
        dialog.add_response('delete', tr('Desinstalar'))
        dialog.set_response_appearance('delete', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        def response(_, result):
            if result != 'delete':
                return
            replacement = choices[picker.get_selected()] if picker else None
            def work():
                self.api.delete(name, replacement)
                return self.api.models()
            def done(models):
                self.populate(models)
                self.new_model()
                self.status.set_text(tr('{0} desinstalado de Ollama.').format(name) + (tr(' También se retiró de OpenCode.') if self.api.config.enabled else ''))
            self.run(work, done)
        dialog.connect('response', response)
        dialog.present()


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        window = self.get_active_window() or Window(self)
        window.present()


if __name__ == '__main__':
    App().run(sys.argv)
