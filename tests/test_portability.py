"""Comprueba integración opcional y rutas aisladas del equipo personal."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend import Audit, OpenCode, NoOpenCode, available_opencode, Ollama
from runtime import audit_root

class PortabilityTests(unittest.TestCase):
    def test_missing_opencode_does_not_create_config(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_CONFIG_HOME': tmp, 'XDG_STATE_HOME': tmp}):
            config=available_opencode(Audit())
            self.assertFalse(config.enabled)
            config.register('test',{},[])
            self.assertFalse((Path(tmp)/'opencode').exists())
            self.assertEqual(audit_root(),Path(tmp)/'modelcrate')

    def test_unsupported_config_is_preserved(self):
        for content in ('{"provider":{}}','{}','[]','invalid','{"providers": []}'):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp}):
                p=Path(tmp)/'opencode/opencode.json';p.parent.mkdir();p.write_text(content)
                config=available_opencode(Audit(Path(tmp)/'audit'))
                self.assertFalse(config.enabled)
                self.assertEqual(p.read_text(),content)

    def test_supported_format_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp}):
            p=Path(tmp)/'opencode/opencode.json';p.parent.mkdir();p.write_text('{"providers": {}}')
            self.assertTrue(available_opencode(Audit(Path(tmp)/'audit')).enabled)

    def test_missing_ollama_explains_how_to_continue(self):
        import requests
        with tempfile.TemporaryDirectory() as tmp:
            api=Ollama(audit=Audit(Path(tmp)),config=NoOpenCode('No disponible'))
            with patch('backend.requests.request',side_effect=requests.ConnectionError()):
                with self.assertRaisesRegex(RuntimeError,'Puedes explorar el catálogo'):
                    api.models()

    def test_standalone_delete_skips_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            api=Ollama(audit=Audit(Path(tmp)),config=NoOpenCode('No disponible'))
            with patch.object(api,'show',return_value={}), patch.object(api,'request',return_value={}) as request, patch.object(api,'models',return_value=[]):
                api.delete('test')
                request.assert_called_once_with('delete',{'model':'test'},method='DELETE')

if __name__=='__main__':unittest.main()
