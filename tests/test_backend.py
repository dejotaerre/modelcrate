"""Pruebas aisladas: no usan el servidor ni los modelos personales."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from backend import Audit, OpenCode, Ollama, Cancelled, canonical, repository, variants

PARAMS = dict(num_ctx=8192, num_predict=2048, temperature=.6, top_p=.95, top_k=40, repeat_penalty=1)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config = OpenCode(root/'opencode.json', Audit(root/'audit'))
        self.initial = {'model': 'ollama/base:latest', 'instructions': ['preservar.md'], 'providers': {
            'ollama': {'models': {'base:latest': {'name': 'Base'}}},
            'otro': {'models': {'alternativo': {}}}}}
        self.config.path.write_text(json.dumps(self.initial))
        self.models = {'base:latest': {'parameters': '', 'capabilities': ['completion', 'tools'],
                                     'model_info': {'test.context_length': 32768}}}
        self.fail_delete = False
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self): self.answer({'models': [{'name': n} for n in owner.models]})
            def answer(self, data, code=200):
                self.send_response(code); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            def do_POST(self):
                p = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                name = canonical(p.get('model', 'base'))
                if self.path == '/api/show': self.answer(owner.models[name])
                elif self.path == '/api/create':
                    owner.models[name] = {**owner.models[canonical(p['from'])], 'parameters': '\n'.join(f'{k} {json.dumps(v)}' for k,v in p['parameters'].items())}
                    self.answer({'status': 'success'})
                elif self.path == '/api/pull':
                    self.send_response(200); self.end_headers()
                    events = [{'digest':'abc','total':100,'completed':20},{'digest':'abc','total':100,'completed':100},{'status':'success'}]
                    try:
                        for e in events: self.wfile.write((json.dumps(e)+'\n').encode())
                    except (BrokenPipeError, ConnectionResetError):
                        pass
            def do_DELETE(self):
                p=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if owner.fail_delete: self.answer({'error':'fallo simulado'},500)
                else:
                    owner.models.pop(canonical(p['model']))
                    self.answer({})
        self.server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.api = Ollama(f'http://127.0.0.1:{self.server.server_port}', self.config.audit, self.config)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()

    def test_configure_and_edit(self):
        self.api.configure('base', 'nuevo', PARAMS, '', True, lambda *_: None)
        cfg,_=self.config.read()
        self.assertEqual(cfg['model'],'ollama/nuevo:latest')
        self.assertEqual(cfg['instructions'],['preservar.md'])
        self.assertIn('otro',cfg['providers'])
        self.assertEqual(cfg['providers']['ollama']['models']['nuevo:latest']['limit']['context'],8192)
        self.api.configure('nuevo', 'nuevo', {**PARAMS,'num_ctx':4096}, '', False, lambda *_:None)
        self.assertIn('num_ctx 4096',self.models['nuevo:latest']['parameters'])
        self.assertTrue(list((self.config.audit.root/'BACKUPS').glob('*/opencode.json')))

    def test_default_delete_requires_replacement(self):
        with self.assertRaises(ValueError): self.api.delete('base')
        self.assertIn('base:latest',self.models)
        self.api.delete('base','otro/alternativo')
        cfg,_=self.config.read()
        self.assertEqual(cfg['model'],'otro/alternativo')
        self.assertNotIn('base:latest',cfg['providers']['ollama']['models'])
        self.assertNotIn('base:latest',self.models)

    def test_failed_delete_keeps_configuration(self):
        self.fail_delete=True
        before=self.config.path.read_bytes()
        with self.assertRaises(RuntimeError): self.api.delete('base','otro/alternativo')
        self.assertEqual(before,self.config.path.read_bytes())

    def test_concurrent_config_edit(self):
        cfg,raw=self.config.read()
        self.config.path.write_text('{}')
        with self.assertRaises(RuntimeError): self.config.save(cfg,raw)
        self.assertEqual(self.config.path.read_text(),'{}')

    def test_progress_and_cancel(self):
        updates=[]
        self.api.stream('pull',{'model':'test'},lambda f,m:updates.append(f))
        self.assertIn(.2,updates); self.assertIn(1,updates)
        self.api.cancel.set()
        with self.assertRaises(Cancelled): self.api.stream('pull',{'model':'test'},lambda *_:None)

    def test_context_and_collision(self):
        with self.assertRaises(ValueError): self.api.configure('base','nuevo',{**PARAMS,'num_ctx':65536},'',False,lambda *_:None)
        self.models['otro:latest']=self.models['base:latest']
        with self.assertRaises(ValueError): self.api.configure('base','otro',PARAMS,'',False,lambda *_:None)

    def test_repository_and_files(self):
        self.assertEqual(repository('https://huggingface.co/autor/modelo'),'autor/modelo')
        with self.assertRaises(ValueError): repository('https://otro.com/a/b')
        with self.assertRaises(ValueError): repository('https://huggingface.co/a/b/blob/main/file')
        class Response:
            links={}
            def raise_for_status(self): pass
            def json(self): return [{'path':p,'size':100} for p in ['model.Q4_K_M.gguf','mmproj.gguf','draft.gguf','model-00001-of-00002.gguf']]
        with patch('backend.requests.get',return_value=Response()):
            _,files,skipped=variants('https://huggingface.co/autor/modelo')
        self.assertEqual(len(files),1); self.assertEqual(skipped,1)
        self.assertEqual(files[0]['source'],'hf.co/autor/modelo:model.Q4_K_M.gguf')

if __name__ == '__main__': unittest.main()
