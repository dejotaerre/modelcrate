"""Conversión de fichas mixtas y eliminación de contenido activo."""
import unittest
from model_card import render_card

class CardTests(unittest.TestCase):
    def test_mixed_card(self):
        doc=render_card('---\nlicense: mit\n---\n# Title\n\n<b>Bold</b>\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n![plot](images/plot.png)', 'https://huggingface.co/owner/model')
        self.assertNotIn('license: mit',doc)
        self.assertIn('<h1>Title</h1>',doc)
        self.assertIn('<table>',doc)
        self.assertIn('https://huggingface.co/owner/model/resolve/main/images/plot.png',doc)
    def test_active_content_removed(self):
        doc=render_card('<script>alert(1)</script><iframe src="https://example.com"></iframe><a href="javascript:alert(1)" onclick="bad()">link</a><p style="color:red">text</p>', 'https://huggingface.co/a/b')
        for fragment in ('<script','<iframe','onclick=','javascript:','style="color:red"'):
            self.assertNotIn(fragment,doc)
    def test_theme(self):
        self.assertIn('background:#242424',render_card('text','https://huggingface.co/a/b',True))
        self.assertIn('background:#fafafa',render_card('text','https://huggingface.co/a/b',False))
