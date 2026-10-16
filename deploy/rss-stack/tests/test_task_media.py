"""Run in RSSBox for the actual Django task integration; skip without its deps."""
import os
import unittest
from types import SimpleNamespace

AVAILABLE = os.path.isdir('/app/core')
if AVAILABLE:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from core.tasks.translate_feeds import _translate_entry_content
    from bs4 import BeautifulSoup


@unittest.skipUnless(AVAILABLE, 'requires deployed RSSBox runtime')
class TaskMediaTests(unittest.TestCase):
    def test_actual_task_retains_images_and_srcset(self):
        original = '<p>Hello</p><picture><source srcset="https://example.org/a.png 2x"><img src="https://example.org/a.png"></picture><img src="https://example.org/b.png">'
        entry = SimpleNamespace(pk=-1, original_content=original, translated_content=None)
        def translate(**kw):
            self.assertNotIn('<img', kw['text'])
            self.assertNotIn('example.org', kw['text'])
            return {'text': kw['text'].replace('Hello', '你好')}
        _translate_entry_content(entry, 'Chinese Simplified', SimpleNamespace(translate=translate))
        soup = BeautifulSoup(entry.translated_content, 'lxml')
        self.assertEqual(len(soup.find_all('img')), 2)
        self.assertEqual(soup.source['srcset'], 'https://example.org/a.png 2x')
        self.assertIn('你好', soup.get_text())

    def test_invalid_result_never_assigned(self):
        for output in ['User Safety: safe', '你好', None]:
            entry = SimpleNamespace(pk=-1, original_content='<p>Hello</p><img src="a">', translated_content=None)
            engine = SimpleNamespace(translate=lambda **kw: {'text': output})
            with self.assertRaises(ValueError):
                _translate_entry_content(entry, 'Chinese Simplified', engine)
            self.assertIsNone(entry.translated_content)


if __name__ == '__main__':
    unittest.main()
