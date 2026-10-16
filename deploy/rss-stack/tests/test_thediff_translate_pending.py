import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "thediff-proxy" / "translate_pending.py"
SPEC = importlib.util.spec_from_file_location("thediff_translate_pending", MODULE_PATH)
TRANSLATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSLATE)


class TranslatePendingTests(unittest.TestCase):
    def test_selects_only_untranslated_full_articles_from_target_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "db.sqlite3"
            with sqlite3.connect(db_path) as db:
                db.execute(
                    "CREATE TABLE core_entry (id INTEGER, feed_id INTEGER, "
                    "pubdate TEXT, original_content TEXT, translated_content TEXT)"
                )
                db.executemany(
                    "INSERT INTO core_entry VALUES (?, ?, ?, ?, ?)",
                    [
                        (1, 26, "2026-09-25", "a" * 600, None),
                        (2, 26, "2026-09-24", "a" * 600, "译文"),
                        (3, 26, "2026-09-23", "preview", None),
                        (4, 25, "2026-09-22", "a" * 600, None),
                    ],
                )
            self.assertEqual(TRANSLATE.pending_ids(db_path, feed_id=26), [1])
            self.assertEqual(TRANSLATE.pending_ids(db_path, feed_id=25), [4])
            self.assertEqual(TRANSLATE.translated_length(db_path, 2, feed_id=26), 2)
            self.assertEqual(TRANSLATE.translated_length(db_path, 2, feed_id=25), 0)


if __name__ == "__main__":
    unittest.main()
