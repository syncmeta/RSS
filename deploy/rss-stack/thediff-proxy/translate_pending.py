#!/usr/bin/env python3
"""Translate The Diff's pending full articles one process at a time.

Run on your RSS host with explicit feed, agent, container and database arguments.
Provider fallback is disabled for this resource-bounded pass.
"""

import argparse
from datetime import datetime, timezone
import fcntl
from pathlib import Path
import sqlite3
import subprocess
import time


CHILD_SCRIPT = """
import sys
from core.models import Entry, Feed
from core.tasks.translate_feeds import _translate_entry_content

entry = Entry.objects.get(pk={entry_id}, feed_id={feed_id})
feed = Feed.objects.get(pk={feed_id})
assert feed.translator_object_id == {agent_id}
if entry.translated_content:
    print('SKIPPED')
else:
    try:
        _translate_entry_content(
            entry, feed.target_language, feed.translator, feed.additional_prompt
        )
        entry.save(update_fields=['translated_content'])
        print('SAVED')
    except Exception as exc:
        print('FAILED', type(exc).__name__)
        sys.exit(1)
"""


def pending_ids(db_path, feed_id):
    with sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True) as db:
        return [
            row[0]
            for row in db.execute(
                "SELECT id FROM (SELECT id, pubdate, original_content, "
                "translated_content FROM core_entry WHERE feed_id=? "
                "ORDER BY pubdate DESC LIMIT 20) "
                "WHERE length(original_content)>=500 "
                "AND (translated_content IS NULL OR translated_content='') "
                "ORDER BY pubdate DESC",
                (feed_id,),
            )
        ]


def translated_length(db_path, entry_id, feed_id):
    with sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT length(translated_content) FROM core_entry "
            "WHERE feed_id=? AND id=?",
            (feed_id, entry_id),
        ).fetchone()
        return (row or [None])[0] or 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--feed-id", required=True, type=int)
    parser.add_argument("--agent-id", required=True, type=int)
    parser.add_argument("--container", required=True)
    args = parser.parse_args()

    with args.lock.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ids = pending_ids(args.db, args.feed_id)
        print("pending", len(ids), flush=True)
        for entry_id in ids:
            started = time.monotonic()
            command = [
                "docker", "exec",
                "-e", "TRANSLATION_FALLBACK_OPENAI_AGENT_ID=",
                "-e", "TRANSLATE_OUTPUT_TOKEN_CAP=4096",
                "-w", "/app", args.container,
                "python", "manage.py", "shell", "-c",
                CHILD_SCRIPT.format(entry_id=entry_id, feed_id=args.feed_id, agent_id=args.agent_id),
            ]
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=900,
                    check=False,
                )
                status = "ok" if result.returncode == 0 and translated_length(
                    args.db, entry_id, args.feed_id
                ) >= 500 else "failed"
            except subprocess.TimeoutExpired:
                status = "timeout"
            elapsed = round(time.monotonic() - started)
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(
                f"{timestamp} entry={entry_id} status={status} "
                f"elapsed_s={elapsed}",
                flush=True,
            )
            time.sleep(2)


if __name__ == "__main__":
    main()
