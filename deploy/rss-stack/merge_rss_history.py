#!/usr/bin/env python3
"""Merge historical RSSBox entries into an offline current database copy.

Never changes either input. Existing settings and nonempty content win;
historical versions remain in the separately retained historical database.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3


def readonly(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def check(connection):
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("Database integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Database foreign key check failed")


def insert(connection, table, row):
    allowed = {r[1] for r in connection.execute(f'PRAGMA table_info("{table}")')}
    fields = [f for f in row if f != "id" and f in allowed]
    columns = ",".join(f'"{f}"' for f in fields)
    placeholders = ",".join("?" for _ in fields)
    return connection.execute(
        f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
        [row[f] for f in fields],
    ).lastrowid


def merge(current, historical, output, translator_id, report_path):
    output = Path(output)
    temporary = output.with_name(output.name + ".part")
    if output.exists() or temporary.exists():
        raise RuntimeError("Output exists; choose a new output filename")
    source = readonly(current)
    old = readonly(historical)
    check(source)
    check(old)
    os.close(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    destination = sqlite3.connect(temporary)
    destination.row_factory = sqlite3.Row
    source.backup(destination)
    destination.execute("PRAGMA foreign_keys=ON")
    if not destination.execute("SELECT 1 FROM core_openaiagent WHERE id=?", (translator_id,)).fetchone():
        raise RuntimeError("Explicit target translator does not exist")
    report = {"feeds_added": 0, "entries_added": 0, "entries_matched": 0,
              "different_versions": [], "per_feed": [],
              "policy": "Current settings/content retained; complete historical DB retained separately"}
    current_feeds = {r["slug"]: dict(r) for r in destination.execute("SELECT * FROM core_feed")}
    with destination:
        for previous in old.execute("SELECT * FROM core_feed ORDER BY id"):
            previous = dict(previous)
            feed = current_feeds.get(previous["slug"])
            if feed is None:
                if not previous["slug"]:
                    raise RuntimeError("Historical feed has no stable slug")
                if destination.execute("SELECT 1 FROM core_feed WHERE feed_url=? AND target_language=?",
                                       (previous["feed_url"], previous["target_language"])).fetchone():
                    raise RuntimeError("Historical slug conflicts with existing feed URL/language")
                new_feed = dict(previous)
                # Foreign keys and generic translator IDs are installation-specific.
                new_feed["translator_object_id"] = translator_id
                new_feed["translator_content_type_id"] = destination.execute(
                    "SELECT id FROM django_content_type WHERE app_label='core' AND model='openaiagent'"
                ).fetchone()[0]
                new_feed["summarizer_id"] = translator_id if previous["summarizer_id"] else None
                new_feed["log"] = None
                new_feed["id"] = insert(destination, "core_feed", new_feed)
                current_feeds[previous["slug"]] = new_feed
                feed = new_feed
                report["feeds_added"] += 1
            stats = {"slug": previous["slug"], "name": previous["name"], "added": 0, "matched": 0}
            by_guid, by_link = {}, {}
            for row in destination.execute("SELECT * FROM core_entry WHERE feed_id=?", (feed["id"],)):
                row = dict(row)
                if row["guid"]:
                    by_guid.setdefault(row["guid"], []).append(row)
                if row["link"]:
                    by_link.setdefault(row["link"], []).append(row)
            for row in old.execute("SELECT * FROM core_entry WHERE feed_id=? ORDER BY id", (previous["id"],)):
                row = dict(row)
                candidates = by_guid.get(row["guid"], []) if row["guid"] else []
                if not candidates and row["link"]:
                    candidates = by_link.get(row["link"], [])
                if len(candidates) > 1:
                    raise RuntimeError("Ambiguous historical entry match; manual review required")
                if candidates:
                    existing = candidates[0]
                    stats["matched"] += 1
                    report["entries_matched"] += 1
                    fields = [f for f in ("original_title", "original_content", "original_summary",
                                           "translated_title", "translated_content", "ai_summary", "enclosures_xml")
                              if row[f] != existing[f] and row[f]]
                    if fields:
                        report["different_versions"].append({"slug": previous["slug"],
                            "historical_entry_id": row["id"], "current_entry_id": existing["id"], "fields": fields})
                    continue
                row["feed_id"] = feed["id"]
                row["id"] = insert(destination, "core_entry", row)
                if row["guid"]:
                    by_guid.setdefault(row["guid"], []).append(row)
                if row["link"]:
                    by_link.setdefault(row["link"], []).append(row)
                stats["added"] += 1
                report["entries_added"] += 1
            report["per_feed"].append(stats)
    check(destination)
    report["total_feeds"] = destination.execute("SELECT count(*) FROM core_feed").fetchone()[0]
    report["total_entries"] = destination.execute("SELECT count(*) FROM core_entry").fetchone()[0]
    destination.close()
    source.close()
    old.close()
    temporary.replace(output)
    report_path = Path(report_path)
    with os.fdopen(os.open(report_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k not in ("per_feed", "different_versions")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("current", "historical", "output", "report"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--translator-id", type=int, required=True)
    args = parser.parse_args()
    merge(args.current, args.historical, args.output, args.translator_id, args.report)
