"""Regression check for the NYT Visual Investigations full-text seed."""

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
EXPECTED_SOURCE = (
    "'visual-investigations': { title: 'Visual Investigations', source: 'rss', "
    "url: 'https://www.nytimes.com/svc/collections/v1/publish/"
    "https://www.nytimes.com/spotlight/visual-investigations/rss.xml'"
)


class VisualInvestigationsSourceTest(unittest.TestCase):
    def test_fulltext_route_uses_official_rss_seed(self):
        for relative in (
            "deploy/rsshub-custom-routes/nytimes/fulltext.ts",
        ):
            with self.subTest(relative=relative):
                source = (ROOT / relative).read_text()
                self.assertTrue(EXPECTED_SOURCE in source, f"{relative}: wrong seed")
                self.assertTrue("link: section.link ||" in source, f"{relative}: lost human link")


if __name__ == "__main__":
    unittest.main()
