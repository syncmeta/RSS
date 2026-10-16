import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET


MODULE_PATH = Path(__file__).resolve().parents[1] / "claude-blog" / "proxy.py"
spec = importlib.util.spec_from_file_location("claude_blog_proxy", MODULE_PATH)
blog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blog)

ARTICLE = '''<script type="application/ld+json">{
  "@type": "BlogPosting", "headline": "A Claude article",
  "datePublished": "Sep 28, 2026"
}</script><div class="u-rich-text-blog w-richtext" data-readtime="content">
<p>''' + ("An original article paragraph. " * 10) + '''</p>
<p><a href="/blog/another">Related page</a></p></div>'''

NEW_ARTICLE = '''<script type="application/ld+json">{
  "@type": "BlogPosting", "headline": "Agent observability on the Claude Platform",
  "datePublished": "2026-10-14"
}</script><div class="text-rich-text text-rich-text--article w-richtext">
<p>''' + ("A new article about agent observability. " * 10) + '''</p>
<p><a href="/resources/articles/another">Related page</a></p></div>'''


class ClaudeBlogProxyTest(unittest.TestCase):
    def test_new_article_index_and_body(self):
        index = '<a href="/resources/articles/agent-observability-on-the-claude-platform">Article</a>'
        links = blog.index_links(index)
        self.assertEqual(links, ["https://claude.com/resources/articles/agent-observability-on-the-claude-platform"])
        item = blog.parse_article(NEW_ARTICLE, links[0])
        self.assertIn("A new article about agent observability", item["content"])
        self.assertIn('href="https://claude.com/resources/articles/another"', item["content"])

    def test_new_listing_keeps_cached_older_articles(self):
        with tempfile.TemporaryDirectory() as directory:
            old_out, old_cache = blog.OUT, blog.CACHE
            try:
                blog.OUT = os.path.join(directory, "claude-blog.xml")
                blog.CACHE = os.path.join(directory, "cache.json")
                old_url = "https://claude.com/blog/a-claude-article"
                Path(blog.CACHE).write_text(json.dumps({old_url: blog.parse_article(ARTICLE, old_url)}))
                new_url = "https://claude.com/resources/articles/agent-observability-on-the-claude-platform"
                index = f'<a href="{new_url}">Article</a>'
                blog.build_feed(lambda url: index if url == blog.INDEX else NEW_ARTICLE)
                links = [item.findtext("link") for item in ET.parse(blog.OUT).findall("./channel/item")]
                self.assertEqual(links, [new_url, old_url])
            finally:
                blog.OUT, blog.CACHE = old_out, old_cache

    def test_public_article_has_full_body_and_absolute_links(self):
        item = blog.parse_article(ARTICLE, "https://claude.com/blog/a-claude-article")
        self.assertIn("An original article paragraph", item["content"])
        self.assertIn('href="https://claude.com/blog/another"', item["content"])
        self.assertEqual(item["published"], "2026-09-28T00:00:00+00:00")

    def test_build_keeps_previous_feed_if_index_breaks(self):
        with tempfile.TemporaryDirectory() as directory:
            old_out, old_cache = blog.OUT, blog.CACHE
            try:
                blog.OUT = os.path.join(directory, "claude-blog.xml")
                blog.CACHE = os.path.join(directory, "cache.json")
                index = '<a href="/blog/a-claude-article">Article</a>'
                blog.build_feed(lambda url: index if url == blog.INDEX else ARTICLE)
                items = ET.parse(blog.OUT).findall("./channel/item")
                self.assertEqual(len(items), 1)
                original = Path(blog.OUT).read_bytes()
                with self.assertRaises(ValueError):
                    blog.build_feed(lambda _: "")
                self.assertEqual(Path(blog.OUT).read_bytes(), original)
            finally:
                blog.OUT, blog.CACHE = old_out, old_cache


if __name__ == "__main__":
    unittest.main()
