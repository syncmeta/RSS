import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rssbox-patches"))
from translation_integrity import protect_media, restore_media, translation_error

spec = importlib.util.spec_from_file_location("public_proxy", ROOT / "public-proxies/proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class IntegrityTests(unittest.TestCase):
    def test_media_roundtrip_is_exact(self):
        original = '<p>Hello</p><picture><source srcset="https://a/x 2x"><img src="https://a/a?x=1&amp;y=2" alt="a > b"></picture><img src="same">'
        masked, media = protect_media(original)
        self.assertNotIn('<img', masked)
        self.assertNotIn('<source', masked)
        self.assertEqual(restore_media(masked.replace('Hello', '你好'), media), original.replace('Hello', '你好'))

    def test_missing_duplicate_reordered_or_changed_media_rejected(self):
        masked, media = protect_media('<img src="a"><p>Hi</p><img src="b">')
        a, b = list(media)
        for output in [masked.replace(a, ''), masked + a, masked.replace(a, 'TEMP').replace(b, a).replace('TEMP', b), masked + '<img src="evil">', '<!--' + masked + '-->']:
            self.assertIsNotNone(translation_error(masked, output))
            with self.assertRaises(ValueError):
                restore_media(output, media)

    def test_classifier_is_not_a_translation(self):
        self.assertIsNotNone(translation_error('An article', 'User Safety: safe'))
        self.assertIsNotNone(translation_error('An article', 'User Safety: unsafe\nSafety Categories: Political/Misinformation/Conspiracy, Needs Caution'))
        self.assertIsNone(translation_error('User Safety: is a field name', 'User Safety: 是一个字段名'))
        self.assertIsNotNone(translation_error('Hello', ''))

    def test_anthropic_cached_internal_and_relative_urls(self):
        source = '<a href="/research/post">x</a><img src="http://feed-proxy/_next/image?url=https%3A%2F%2Fwww-cdn.anthropic.com%2Fimages%2Fa.png&amp;w=3840&amp;q=75" srcset="/_next/image?url=https%3A%2F%2Fwww-cdn.anthropic.com%2Fimages%2Fa.png&amp;w=640 640w, /images/b.png 1280w">'
        fixed = proxy.normalize_anthropic_html(source)
        self.assertNotIn('feed-proxy', fixed)
        self.assertNotIn('/_next/image', fixed)
        self.assertIn('src="https://www-cdn.anthropic.com/images/a.png"', fixed)
        self.assertIn('https://www.anthropic.com/images/b.png 1280w', fixed)
        self.assertIn('href="https://www.anthropic.com/research/post"', fixed)
        self.assertEqual(proxy.normalize_anthropic_html(fixed), fixed)


if __name__ == '__main__':
    unittest.main()
