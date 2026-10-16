"""An existing public feed must stay visible while its next item translates."""

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).parents[1] / "rssbox-patches" / "translate_feeds.py"


class TranslationVisibilityTests(unittest.TestCase):
    def test_existing_feed_stays_visible_during_translation(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        method = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "handle_feeds_translation"
        )
        observed = []
        env = {
            "timezone": SimpleNamespace(now=lambda: "now"),
            "logger": logging.getLogger("test"),
            "Feed": SimpleNamespace(
                objects=SimpleNamespace(bulk_update=lambda *args, **kwargs: None)
            ),
            "translate_feed": lambda feed, target_field: observed.append(
                feed.translation_status
            ),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), "exec"), env)
        feed = SimpleNamespace(
            entries=SimpleNamespace(exists=lambda: True),
            translation_status=True,
            target_language="Chinese Traditional",
            feed_url="test-feed",
            log="",
            total_tokens=0,
            total_characters=0,
            last_translate=None,
            save=lambda: None,
        )
        env["handle_feeds_translation"]([feed], target_field="content")
        self.assertEqual(observed, [True])
        self.assertTrue(feed.translation_status)


if __name__ == "__main__":
    unittest.main()
