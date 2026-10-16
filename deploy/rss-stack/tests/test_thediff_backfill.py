import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "thediff-proxy" / "backfill.py"
SPEC = importlib.util.spec_from_file_location("thediff_backfill", MODULE_PATH)
BACKFILL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKFILL)


class TheDiffBackfillTests(unittest.TestCase):
    def test_upgrades_only_matching_short_entries_and_preserves_other_feeds(self):
        with tempfile.TemporaryDirectory() as directory:
            rss = Path(directory) / "thediff.xml"
            body = "<p>" + ("Paid analysis with evidence. " * 30) + "</p>"
            rss.write_text(
                '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/">'
                '<channel><item><guid>paid-1</guid><content:encoded><![CDATA['
                + body
                + ']]></content:encoded></item></channel></rss>',
                encoding="utf-8",
            )
            db = Path(directory) / "db.sqlite3"
            with sqlite3.connect(db) as connection:
                connection.execute(
                    "CREATE TABLE core_entry (id INTEGER PRIMARY KEY, feed_id INTEGER, "
                    "guid TEXT, original_content TEXT, translated_content TEXT)"
                )
                connection.executemany(
                    "INSERT INTO core_entry VALUES (?, ?, ?, ?, ?)",
                    [
                        (1, 26, "paid-1", "<p>Preview</p>", "old translation"),
                        (2, 25, "paid-1", "<p>Other feed</p>", "other translation"),
                    ],
                )

            self.assertEqual(BACKFILL.backfill(db, rss, feed_id=26, apply=False), 1)
            with sqlite3.connect(db) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT original_content FROM core_entry WHERE id=1"
                    ).fetchone()[0],
                    "<p>Preview</p>",
                )

            self.assertEqual(BACKFILL.backfill(db, rss, feed_id=26, apply=True), 1)
            with sqlite3.connect(db) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT original_content, translated_content FROM core_entry WHERE id=1"
                    ).fetchone(),
                    (body, None),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT original_content, translated_content FROM core_entry WHERE id=2"
                    ).fetchone(),
                    ("<p>Other feed</p>", "other translation"),
                )
            self.assertEqual(BACKFILL.backfill(db, rss, feed_id=26, apply=True), 0)


if __name__ == "__main__":
    unittest.main()
