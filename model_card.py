"""Presentación de fichas Markdown/HTML sin contenido activo."""
import re
from html import escape
from urllib.parse import urljoin, urlparse
import bleach
import markdown


def render_card(source, repo_url, dark=False, heading=''):
    # Los metadatos YAML se muestran por separado en la ficha.
    source = re.sub(r'\A\ufeff?---\s*\n.*?\n---\s*(?:\n|$)', '', source, count=1, flags=re.S)
    tags = set(bleach.sanitizer.ALLOWED_TAGS) | {
        'p', 'div', 'span', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'pre', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'del',
        'details', 'summary', 'sup', 'sub', 'small'}
    content = bleach.clean(markdown.markdown(source, extensions=['tables', 'fenced_code', 'sane_lists']),
        tags=tags, attributes={'a': ['href', 'title'], 'img': ['src', 'alt', 'title'],
                              'th': ['colspan', 'rowspan'], 'td': ['colspan', 'rowspan']},
        protocols=['https', 'http'], strip=True)
    # Las imágenes relativas de Hugging Face necesitan la ruta resolve.
    def image_url(match):
        value = match.group(1)
        if not urlparse(value).scheme and not value.startswith('//'):
            value = urljoin(repo_url.rstrip('/') + '/resolve/main/', value)
        value = value.replace('/blob/main/', '/resolve/main/')
        return 'src="' + escape(value, quote=True) + '"'
    content = re.sub(r'src="([^"]*)"', image_url, content)
    bg, fg, muted, link = ('#242424', '#eeeeec', '#454545', '#78aeed') if dark else ('#fafafa', '#242424', '#dddddd', '#1c71d8')
    return f'''<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: http:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<style>
body {{background:{bg};color:{fg};font:16px sans-serif;line-height:1.5;margin:24px;overflow-wrap:anywhere}}
a {{color:{link}}} img {{max-width:100%;height:auto}} pre {{white-space:pre-wrap;padding:12px;background:{muted};border-radius:8px}}
table {{border-collapse:collapse;display:block;overflow-x:auto}} td,th {{border:1px solid {muted};padding:8px}}
blockquote {{border-left:3px solid {muted};margin-left:0;padding-left:16px}} hr {{border:0;border-top:1px solid {muted}}}
</style></head><body>{heading}<hr>{content}</body></html>'''


def card_view(source, repo_url, heading=''):
    import gi
    gi.require_version('WebKit', '6.0')
    from gi.repository import WebKit, Adw, Gio, Gdk
    view = WebKit.WebView(network_session=WebKit.NetworkSession.new_ephemeral(), vexpand=True)
    settings = view.get_settings()
    settings.set_enable_javascript(False)
    settings.set_enable_html5_local_storage(False)
    manager = Adw.StyleManager.get_default()
    def render(*_):
        color = Gdk.RGBA(); color.parse('#242424' if manager.get_dark() else '#fafafa')
        view.set_background_color(color)
        view.load_html(render_card(source, repo_url, manager.get_dark(), heading), repo_url.rstrip('/') + '/blob/main/README.md')
    def policy(_view, decision, kind):
        if kind in (WebKit.PolicyDecisionType.NAVIGATION_ACTION, WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
            action = decision.get_navigation_action()
            if action.get_navigation_type() == WebKit.NavigationType.LINK_CLICKED:
                uri = action.get_request().get_uri()
                if urlparse(uri).scheme in ('https', 'http'):
                    Gio.AppInfo.launch_default_for_uri_async(uri, None, None, None, None)
                decision.ignore()
                return True
        return False
    view.connect('decide-policy', policy)
    handler = manager.connect('notify::dark', render)
    view.connect('unrealize', lambda *_: manager.disconnect(handler) if manager.handler_is_connected(handler) else None)
    render()
    return view
