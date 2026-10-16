import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[1] / "thediff-proxy" / "proxy.py"
SPEC = importlib.util.spec_from_file_location("thediff_proxy", MODULE_PATH)
PROXY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROXY)


class TheDiffProxyTests(unittest.TestCase):
    def test_extracts_nested_content_container(self):
        page = '''
        <div class="unrelated"><div>ignore</div></div>
        <div class="content"><h2>Title</h2><div><p>Body</p></div></div>
        <footer>after</footer>
        '''
        self.assertEqual(
            PROXY.extract_content(page),
            '<h2>Title</h2><div><p>Body</p></div>',
        )

    def test_rejects_paid_upgrade_cta(self):
        locked = (
            '<aside class="gh-post-upgrade-cta">'
            '<h2>This post is for paying subscribers only</h2></aside>'
        )
        self.assertFalse(PROXY.is_full_article(locked))

    def test_accepts_substantial_member_content(self):
        content = "<p>" + ("Financial analysis and evidence. " * 30) + "</p>"
        self.assertTrue(PROXY.is_full_article(content))

    def test_cookie_accepts_raw_value_or_header(self):
        original = PROXY.os.environ.get("THEDIFF_COOKIE")
        original_sig = PROXY.os.environ.get("THEDIFF_COOKIE_SIG")
        try:
            PROXY.os.environ.pop("THEDIFF_COOKIE_SIG", None)
            PROXY.os.environ["THEDIFF_COOKIE"] = "token-value"
            self.assertEqual(
                PROXY.cookie_header(), "ghost-members-ssr=token-value"
            )
            PROXY.os.environ["THEDIFF_COOKIE"] = "a=b; c=d"
            self.assertEqual(PROXY.cookie_header(), "a=b; c=d")
            PROXY.os.environ["THEDIFF_COOKIE"] = "token-value"
            PROXY.os.environ["THEDIFF_COOKIE_SIG"] = "signature-value"
            self.assertEqual(
                PROXY.cookie_header(),
                "ghost-members-ssr=token-value; ghost-members-ssr.sig=signature-value",
            )
        finally:
            if original is None:
                PROXY.os.environ.pop("THEDIFF_COOKIE", None)
            else:
                PROXY.os.environ["THEDIFF_COOKIE"] = original
            if original_sig is None:
                PROXY.os.environ.pop("THEDIFF_COOKIE_SIG", None)
            else:
                PROXY.os.environ["THEDIFF_COOKIE_SIG"] = original_sig


if __name__ == "__main__":
    unittest.main()
