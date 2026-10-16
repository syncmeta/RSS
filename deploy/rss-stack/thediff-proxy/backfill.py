#!/usr/bin/env python3
"""Upgrade existing The Diff previews from the authenticated RSS snapshot.

New RSSBox entries get full text on their first fetch, but its normal updater
never refreshes the body of an existing GUID. Run with --apply only after a
verified SQLite backup; dry-run is the default. No article text is printed.
"""

import argparse
import html
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET


CONTENT_TAG = "{http://purl.org/rss/1.0/modules/content/}encoded"
LOCKED_MARKERS = (
    "This post is for paying subscribers only",
    "This post is for members only",
)


def full_bodies(rss_path):
    root = ET.parse(rss_path).getroot()
    if root.tag != "rss":
        raise ValueError("expected an RSS document")

    bodies = {}
    for item in root.iter("item"):
        guid = (item.findtext("guid") or item.findtext("link") or "").strip()
        body = item.findtext(CONTENT_TAG) or ""
        plain = html.unescape(re.sub(r"<[^>]+>", " ", body))
        plain = re.sub(r"\s+", " ", plain).strip()
        if guid and len(plain) >= 500 and not any(
            marker in plain for marker in LOCKED_MARKERS
        ):
            bodies[guid] = body
    return bodies


def backfill(db_path, rss_path, feed_id, apply=False):
    bodies = full_bodies(rss_path)
    if not bodies:
        raise ValueError("authenticated RSS contains no full articles")

    upgrades = []
    with sqlite3.connect(str(db_path), timeout=10) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("database integrity check failed")
        for guid, body in bodies.items():
            rows = connection.execute(
                "SELECT id, length(original_content) FROM core_entry "
                "WHERE feed_id = ? AND guid = ?",
                (feed_id, guid),
            ).fetchall()
            for entry_id, old_length in rows:
                if len(body) > (old_length or 0):
                    upgrades.append((body, entry_id, feed_id))

        if apply and upgrades:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "UPDATE core_entry SET original_content = ?, "
                "translated_content = NULL WHERE id = ? AND feed_id = ?",
                upgrades,
            )

    return len(upgrades)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--rss", required=True, type=Path)
    parser.add_argument("--feed-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    count = backfill(args.db, args.rss, args.feed_id, args.apply)
    print("upgraded" if args.apply else "would_upgrade", count)


if __name__ == "__main__":
    main()
