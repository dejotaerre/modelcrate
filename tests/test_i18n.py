"""Idioma automático, respaldo inglés e integridad de las traducciones."""
import ast
from pathlib import Path
from string import Formatter
import unittest
from unittest.mock import patch
import i18n

ROOT = Path(__file__).resolve().parents[1]

class LanguageTests(unittest.TestCase):
    def test_spanish_variants(self):
        for locale in ('es','es_UY.UTF-8','es_ES.UTF-8','es-MX'):
            self.assertEqual(i18n.detect_language({'LANG':locale}),'es')

    def test_other_languages_fall_back_to_english(self):
        for locale in ('en_US.UTF-8','de_DE.UTF-8','fr_FR.UTF-8','pt_BR.UTF-8','C','C.UTF-8','ja_JP.UTF-8'):
            self.assertEqual(i18n.detect_language({'LANG':locale}),'en')
        self.assertEqual(i18n.detect_language({}),'en')

    def test_precedence_and_override(self):
        self.assertEqual(i18n.detect_language({'LC_ALL':'C','LANGUAGE':'es','LANG':'es_UY.UTF-8'}),'en')
        self.assertEqual(i18n.detect_language({'LANGUAGE':'es:en','LANG':'en_US.UTF-8'}),'es')
        self.assertEqual(i18n.detect_language({'LC_MESSAGES':'es_ES.UTF-8','LANG':'en_US.UTF-8'}),'es')
        self.assertEqual(i18n.detect_language({'MODELCRATE_LANGUAGE':'en','LANG':'es_UY.UTF-8'}),'en')
        self.assertEqual(i18n.detect_language({'LANGUAGE':'fr:es','LANG':'es_UY.UTF-8'}),'en')

    def test_catalog_preserves_placeholders(self):
        def placeholders(text):
            return sorted((field,spec,conv or '') for _,field,spec,conv in Formatter().parse(text) if field is not None)
        for source,target in i18n.CATALOG.items():
            with self.subTest(source=source):
                self.assertEqual(placeholders(source),placeholders(target))
                self.assertTrue(target.strip())

    def test_every_translation_call_has_a_catalog_entry(self):
        for path in [*ROOT.glob('*.py'),ROOT/'scripts/screenshots.py']:
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='tr':
                    self.assertIsInstance(node.args[0],ast.Constant)
                    self.assertIn(node.args[0].value,i18n.CATALOG,str(path))

    def test_both_languages(self):
        with patch.object(i18n,'LANGUAGE','es'):
            self.assertEqual(i18n.tr('Descargar y configurar'),'Descargar y configurar')
            self.assertEqual(i18n.decimal_text('16.81 GB'),'16,81 GB')
        with patch.object(i18n,'LANGUAGE','en'):
            self.assertEqual(i18n.tr('Descargar y configurar'),'Download and configure')
            self.assertEqual(i18n.decimal_text('16.81 GB'),'16.81 GB')

if __name__=='__main__':unittest.main()
