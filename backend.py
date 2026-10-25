"""Gestión local de modelos y configuración de OpenCode."""
from i18n import tr
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from urllib.parse import urlparse

import requests
from runtime import audit_root, config_home


class Cancelled(Exception):
    pass


def canonical(name):
    return name if ':' in name.rsplit('/', 1)[-1] else name + ':latest'


def size_text(n):
    return f'{n / 1e9:.2f} GB' if n >= 1e9 else f'{n / 1e6:.1f} MB'


def repository(url):
    url = url.strip()
    if not url.startswith(('https://', 'http://')):
        url = 'https://' + url
    p = urlparse(url)
    if p.scheme != 'https' or p.hostname not in ('huggingface.co', 'hf.co'):
        raise ValueError(tr('Pega una URL HTTPS de huggingface.co o hf.co.'))
    parts = p.path.strip('/').split('/')
    if len(parts) < 2 or not all(re.fullmatch(r'[\w.-]+', x) for x in parts[:2]):
        raise ValueError(tr('La URL debe contener el autor y el repositorio.'))
    if len(parts) > 2:
        raise ValueError(tr('Usa la URL principal del repositorio, sin /tree/ ni /blob/.'))
    return '/'.join(parts)


def variants(url):
    repo = repository(url)
    endpoint = f'https://huggingface.co/api/models/{repo}/tree/main?recursive=true&limit=1000'
    files = []
    skipped = 0
    while endpoint:
        response = requests.get(endpoint, timeout=(10, 30))
        response.raise_for_status()
        for f in response.json():
            name = f.get('path', '')
            if not name.lower().endswith('.gguf'):
                continue
            if re.search(r'mmproj|(?:^|[-_/])draft(?:[-_.]|$)', name, re.I):
                continue
            if re.search(r'-\d{5}-of-\d{5}\.gguf$', name):
                skipped += 1
                continue
            files.append({'file': name, 'size': f.get('size', 0),
                          'source': f'hf.co/{repo}:{name}'})
        endpoint = response.links.get('next', {}).get('url')
        if endpoint and urlparse(endpoint).hostname != 'huggingface.co':
            raise ValueError(tr('Hugging Face devolvió una paginación inesperada.'))
    files.sort(key=lambda f: (f['size'], f['file']))
    if not files:
        raise ValueError(tr('No hay GGUF completos compatibles en la rama main. No se importan fragmentos ni proyectores solos.'))
    return repo, files, skipped


def parse_parameters(text):
    result = {}
    for line in text.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2:
            key, value = fields
            try:
                value = json.loads(value)
            except ValueError:
                pass
            if key == 'stop':
                result.setdefault(key, []).append(value)
            else:
                result[key] = value
    return result


def validate_parameters(p):
    if not 512 <= p['num_ctx'] <= 262144:
        raise ValueError(tr('El contexto debe estar entre 512 y 262144 tokens.'))
    if not 1 <= p['num_predict'] < p['num_ctx']:
        raise ValueError(tr('La salida máxima debe ser menor que el contexto.'))
    if not 0 <= p['temperature'] <= 2 or not 0 < p['top_p'] <= 1:
        raise ValueError(tr('Temperatura o top-p fuera de rango.'))
    if not 1 <= p['top_k'] <= 1000 or not 0.1 <= p['repeat_penalty'] <= 3:
        raise ValueError(tr('Top-k o penalización fuera de rango.'))


class Audit:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else audit_root()

    def backup(self, path, label):
        stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        folder = self.root / 'BACKUPS' / f'{stamp}_MODELOS_{label}'
        folder.mkdir(parents=True, mode=0o700)
        if path.exists():
            shutil.copy2(path, folder / path.name)
        return folder

    def record(self, label, text):
        folder = self.root / 'CAMBIOS'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + f'_MODELOS_{label}.md')
        path.write_text(tr('# Gestor de modelos: {0}\n\n{1}\n').format(label, text))
        return path


class OpenCode:
    enabled = True
    reason = tr('OpenCode: integración activa (formato providers).')

    def __init__(self, path=None, audit=None):
        self.path = Path(path) if path is not None else config_home() / 'opencode/opencode.json'
        self.audit = audit or Audit()

    def read(self):
        data = self.path.read_bytes() if self.path.exists() else b'{}'
        try:
            config = json.loads(data)
        except ValueError as e:
            raise ValueError(tr('opencode.json no es JSON estricto. No se modificó; revisa sus comentarios o sintaxis.')) from e
        other = self.path.with_suffix('.jsonc')
        if other.exists():
            text = other.read_text()
            if re.search(r'"(?:providers|provider|model|agents)"\s*:', text):
                raise ValueError(tr('Hay ajustes de modelos en opencode.jsonc; unifica esos ajustes antes de usar este gestor.'))
        if not isinstance(config, dict) or 'provider' in config or not isinstance(config.get('providers'), dict):
            raise ValueError(tr('Formato de OpenCode no compatible: esta versión admite providers, no provider ni configuraciones vacías.'))
        if not all(isinstance(v, dict) and isinstance(v.get('models', {}), dict)
                   and isinstance(v.get('settings', {}), dict) for v in config['providers'].values()):
            raise ValueError(tr('La configuración de proveedores de OpenCode no tiene el formato esperado.'))
        if not isinstance(config.get('agents', {}), dict):
            raise ValueError(tr('El formato de agentes de OpenCode no es compatible.'))
        return config, data

    def save(self, config, before):
        current = self.path.read_bytes() if self.path.exists() else b'{}'
        if current != before:
            raise RuntimeError(tr('OpenCode cambió durante la operación. Actualiza la lista y vuelve a registrar el modelo.'))
        backup = self.audit.backup(self.path, 'OPENCODE')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix='.modelos-')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            if self.path.exists():
                os.chmod(temp, self.path.stat().st_mode & 0o777)
            if (self.path.read_bytes() if self.path.exists() else b'{}') != before:
                raise RuntimeError(tr('La configuración cambió; no se sobrescribió.'))
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.audit.record('OPENCODE', tr('Configuración: {0}\n\nRespaldo: {1}').format(self.path, backup))

    @staticmethod
    def model_id(config):
        m = config.get('model', '')
        if isinstance(m, dict):
            return f"{m.get('providerID')}/{m.get('model')}"
        return m

    def register(self, name, params, caps, default=False, base='http://127.0.0.1:11434'):
        cfg, raw = self.read()
        provider = cfg.setdefault('providers', {}).setdefault('ollama', {'name': 'Ollama'})
        existing_url = provider.get('settings', {}).get('baseURL')
        if existing_url and existing_url.rstrip('/') != base.rstrip('/') + '/v1':
            raise ValueError(tr('El proveedor ollama de OpenCode apunta a otro servidor. No se modificó.'))
        provider.setdefault('settings', {})['baseURL'] = base.rstrip('/') + '/v1'
        provider.setdefault('package', '@opencode/ai/providers/openai-compatible')
        models = provider.setdefault('models', {})
        key = next((k for k in models if canonical(k) == canonical(name)), name)
        entry = models.setdefault(key, {})
        entry.setdefault('name', name)
        entry.setdefault('limit', {}).update(context=params['num_ctx'], output=params['num_predict'])
        entry.setdefault('body', {}).update(temperature=params['temperature'], top_p=params['top_p'])
        entry.setdefault('capabilities', {}).update(tools='tools' in caps,
            input=['text', 'image'] if 'vision' in caps else ['text'], output=['text'])
        if default:
            cfg['model'] = f'ollama/{key}'
        self.save(cfg, raw)

    def deletion_plan(self, name, replacement=None):
        cfg, raw = self.read()
        models = cfg.get('providers', {}).get('ollama', {}).get('models', {})
        keys = [k for k in models if canonical(k) == canonical(name)]
        ids = {f'ollama/{k}' for k in keys} | {f'ollama/{name}'}
        selected = self.model_id(cfg)
        affected = selected in ids or selected in {f'ollama/{canonical(name)}'}
        if affected and not replacement:
            raise ValueError(tr('Elige otro modelo predeterminado antes de desinstalar este.'))
        if replacement in ids:
            raise ValueError(tr('El reemplazo no puede ser el modelo eliminado.'))
        for agent in cfg.get('agents', {}).values():
            if isinstance(agent, dict) and self.model_id(agent) in ids:
                raise ValueError(tr('Un agente de OpenCode usa este modelo explícitamente. Cambia su modelo antes de eliminarlo.'))
        if affected:
            valid = [f'{p}/{m}' for p, v in cfg.get('providers', {}).items() for m in v.get('models', {})]
            if replacement not in valid:
                raise ValueError(tr('El reemplazo debe estar registrado en OpenCode.'))
            cfg['model'] = replacement
        for k in keys:
            del models[k]
        return cfg, raw


class NoOpenCode:
    enabled = False
    model_id = staticmethod(OpenCode.model_id)

    def __init__(self, reason):
        self.reason = reason

    def read(self):
        return {}, b'{}'

    def register(self, *args, **kwargs):
        pass

    def deletion_plan(self, *args, **kwargs):
        return {}, b'{}'

    def save(self, *args, **kwargs):
        pass


def available_opencode(audit):
    config = OpenCode(audit=audit)
    if not config.path.exists():
        return NoOpenCode(tr('OpenCode no configurado: puedes gestionar modelos en Ollama sin él.'))
    try:
        config.read()
    except (ValueError, OSError) as error:
        return NoOpenCode(tr('Integración de OpenCode desactivada: {0} Puedes usar Ollama; su catálogo de OpenCode no se actualizará.').format(error))
    return config


class Ollama:
    def __init__(self, base='http://127.0.0.1:11434', audit=None, config=None):
        self.base = base.rstrip('/')
        self.audit = audit or Audit()
        self.config = config if config is not None else available_opencode(self.audit)
        self.cancel = threading.Event()
        self.response = None

    def request(self, path, payload=None, method=None):
        try:
            response = requests.request(method or ('POST' if payload is not None else 'GET'),
                self.base + '/api/' + path, json=payload, timeout=(10, 120))
        except requests.ConnectionError as error:
            raise RuntimeError(tr('No pudimos conectar con Ollama en {0}. Inícialo y pulsa Actualizar. Puedes explorar el catálogo mientras tanto.').format(self.base)) from error
        except requests.Timeout as error:
            raise RuntimeError(tr('Ollama tardó demasiado en responder. Comprueba su estado y vuelve a intentarlo.')) from error
        if not response.ok:
            raise RuntimeError(f'Ollama: {response.status_code} — {response.text[:500]}')
        return response.json() if response.content else {}

    def stop(self):
        self.cancel.set()
        response = self.response
        if response:
            threading.Thread(target=response.close, daemon=True).start()

    def stream(self, path, payload, progress):
        success = False
        baselines = {}
        with requests.post(self.base + '/api/' + path, json={**payload, 'stream': True},
                           stream=True, timeout=(10, 60)) as response:
            self.response = response
            response.raise_for_status()
            for line in response.iter_lines(chunk_size=1):
                if self.cancel.is_set():
                    raise Cancelled()
                if not line:
                    continue
                event = json.loads(line)
                if 'error' in event:
                    raise RuntimeError(event['error'])
                digest = event.get('digest')
                if digest and event.get('total'):
                    done, total = event.get('completed', 0), event['total']
                    if digest not in baselines:
                        baselines[digest] = (done, time.monotonic())
                    initial, began = baselines[digest]
                    rate = max(0, done - initial) / max(time.monotonic() - began, .001)
                    eta = (total - done) / rate if rate else None
                    progress(done / total, f'{size_text(done)} / {size_text(total)} · '
                        + (tr('{0}/s · ~{1} s restantes').format(size_text(rate), int(eta)) if eta is not None else tr('Calculando velocidad…')))
                else:
                    labels = {'pulling manifest': tr('Consultando manifiesto…'), 'verifying sha256 digest': tr('Verificando integridad…'),
                        'writing manifest': tr('Guardando modelo…'), 'success': tr('Operación completada')}
                    progress(None, labels.get(event.get('status'), event.get('status', tr('Procesando…'))))
                success = event.get('status') == 'success'
        self.response = None
        if self.cancel.is_set():
            raise Cancelled()
        if not success:
            raise RuntimeError(tr('Ollama cerró la conexión sin confirmar que terminó. Actualiza la lista antes de repetir.'))

    def models(self):
        return self.request('tags').get('models', [])

    def show(self, name):
        return self.request('show', {'model': name})

    def configure(self, source, name, params, system, default, progress):
        validate_parameters(params)
        cfg, _ = self.config.read()
        target = cfg.get('providers', {}).get('ollama', {}).get('settings', {}).get('baseURL')
        if target and target.rstrip('/') != self.base + '/v1':
            raise ValueError(tr('El proveedor ollama de OpenCode apunta a otro servidor.'))
        before = self.show(source)
        if before.get('remote_model'):
            raise ValueError(tr('Este es un modelo remoto de Ollama; el gestor configura modelos locales.'))
        max_ctx = next((v for k, v in before.get('model_info', {}).items() if k.endswith('.context_length')), None)
        if max_ctx and params['num_ctx'] > max_ctx:
            raise ValueError(tr('El modelo declara un máximo de {0} tokens; reduce el contexto.').format(max_ctx))
        all_names = [canonical(m['name']) for m in self.models()]
        if canonical(name) != canonical(source) and canonical(name) in all_names:
            raise ValueError(tr('Ese nombre ya existe. Elígelo desde Instalados para editarlo.'))
        if canonical(name) == canonical(source):
            folder = self.audit.backup(Path('/nonexistent'), 'PARAMETROS')
            path = folder / 'modelo-anterior.json'
            path.write_text(json.dumps(before, indent=2, ensure_ascii=False))
            path.chmod(0o600)
        self.audit.record('INICIO_CONFIGURACION', tr('Modelo: {0}\nOrigen: {1}\nParámetros: {2}').format(name, source, params))
        self.stream('create', {'model': name, 'from': source, 'parameters': params, 'system': system}, progress)
        result = self.show(name)
        actual = parse_parameters(result.get('parameters', ''))
        for key in ('num_ctx', 'num_predict'):
            if actual.get(key) != params[key]:
                raise RuntimeError(tr('Ollama no confirmó {0}. El modelo existe pero no fue registrado en OpenCode.').format(key))
        try:
            self.config.register(canonical(name), params, result.get('capabilities', []), default, self.base)
        except Exception as e:
            self.audit.record('REGISTRO_PENDIENTE', tr('Modelo {0} configurado en Ollama; fallo de OpenCode: {1}').format(name, e))
            raise RuntimeError(tr('El modelo quedó configurado en Ollama, pero falta registrarlo en OpenCode: {0}').format(e)) from e
        self.audit.record('CONFIGURADO', tr('Modelo {0}; origen {1}; parámetros {2}; integración OpenCode: {3}.').format(name, source, params, self.config.enabled))

    def delete(self, name, replacement=None):
        config, raw = self.config.deletion_plan(name, replacement)
        original = self.show(name)
        backup = self.audit.backup(self.config.path if self.config.enabled else Path('/nonexistent'), 'DESINSTALAR')
        p = backup / 'modelo.json'
        p.write_text(json.dumps(original, indent=2, ensure_ascii=False))
        p.chmod(0o600)
        self.audit.record('INICIO_DESINSTALAR', tr('Modelo: {0}\nRespaldo de metadatos: {1}\nLos pesos no se respaldan.').format(name, backup))
        self.request('delete', {'model': name}, method='DELETE')
        if any(canonical(x['name']) == canonical(name) for x in self.models()):
            raise RuntimeError(tr('Ollama todavía lista el modelo. No se modificó OpenCode.'))
        try:
            self.config.save(config, raw)
        except Exception as e:
            self.audit.record('LIMPIEZA_PENDIENTE', tr('Ollama eliminó {0}; falta limpiar OpenCode: {1}').format(name, e))
            raise RuntimeError(tr('Eliminado de Ollama, pero no de OpenCode: {0}').format(e)) from e
        self.audit.record('DESINSTALADO', tr('Modelo: {0}. Eliminado mediante API de Ollama; integración OpenCode: {1}.').format(name, self.config.enabled))

    def test_tools(self, name):
        nonce = os.urandom(8).hex()
        tool = {'type': 'function', 'function': {'name': 'obtener_codigo',
            'description': tr('Devuelve el código de prueba actual. Solo se conoce invocando esta herramienta.'),
            'parameters': {'type': 'object', 'properties': {}}}}
        messages = [{'role': 'user', 'content': tr('Llama a obtener_codigo y responde únicamente con el código recibido.')}]
        payload = {'model': name, 'messages': messages, 'tools': [tool], 'stream': False,
                   'options': {'num_ctx': 4096, 'num_predict': 512, 'temperature': 0}, 'keep_alive': '2m'}
        response = self.request('chat', payload)
        msg = response.get('message', {})
        calls = msg.get('tool_calls', [])
        if len(calls) != 1 or calls[0].get('function', {}).get('name') != 'obtener_codigo':
            return tr('No pasó: el modelo no emitió la llamada nativa esperada. No se ejecutó ningún comando.')
        messages.extend([msg, {'role': 'tool', 'tool_name': 'obtener_codigo', 'content': nonce}])
        result = self.request('chat', {**payload, 'messages': messages})
        if nonce not in result.get('message', {}).get('content', ''):
            return tr('Parcial: llamó a la herramienta, pero no devolvió correctamente su resultado.')
        return tr('Prueba aprobada: llamada nativa y resultado correcto en Ollama. Es una prueba básica; no garantiza tareas completas en OpenCode.')
