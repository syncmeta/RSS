#!/usr/bin/env python3
"""Run RSSBox feeds serially with a lock held until every feed ends.

The stock command starts five translation threads and releases its lock after
30 minutes even while worker threads keep running. That combination can
overlap hourly runs and exhaust a 1 GiB VPS. This wrapper uses RSSBox's normal
single-feed update function but never runs two feeds concurrently.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import os
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only-feed", type=int)
    parser.add_argument("--frequency", type=int, default=60,
                        choices=[5, 15, 30, 60, 1440, 10080])
    parser.add_argument("--exclude-feed", type=int, action="append", default=[])
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    # Acquire before loading Django so another cron frequency cannot consume
    # a second application's memory while the active pass is still running.
    lock = open("/tmp/rss_serial_updates.lock", "a+")
    if not args.list:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            print("already_running", flush=True)
            return 0

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ["TRANSLATE_OUTPUT_TOKEN_CAP"] = "4096"
    import django

    django.setup()
    from core.cache import cache_rss, cache_tag
    from core.management.commands.feed_updater import update_single_feed
    from core.models import Feed, Tag

    feeds = Feed.objects.all().order_by("id")
    if args.only_feed is not None:
        feeds = feeds.filter(pk=args.only_feed)
    else:
        feeds = feeds.filter(update_frequency=args.frequency)
    if args.exclude_feed:
        feeds = feeds.exclude(pk__in=args.exclude_feed)
    feeds = list(feeds)

    if args.list:
        print("feed_ids", " ".join(str(feed.pk) for feed in feeds))
        return 0

    with lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("already_running", flush=True)
            return 0

        print("started", datetime.now(timezone.utc).isoformat(), len(feeds), flush=True)
        failures = 0
        for feed in feeds:
            start = time.monotonic()
            previous_fallback = os.environ.get("TRANSLATION_FALLBACK_OPENAI_AGENT_ID")
            try:
                result = update_single_feed(feed)
                feed.refresh_from_db()
                okay = result and feed.fetch_status is True
                failures += not okay
                print(
                    "feed", feed.pk, "ok" if okay else "failed",
                    "seconds", round(time.monotonic() - start),
                    flush=True,
                )
                for feed_type, format in (
                    ("o", "xml"), ("o", "json"), ("t", "xml"), ("t", "json")
                ):
                    try:
                        cache_rss(feed.slug, feed_type=feed_type, format=format)
                    except Exception as exc:
                        print("feed_cache_failed", feed.pk, type(exc).__name__, flush=True)
            finally:
                if previous_fallback is None:
                    os.environ.pop("TRANSLATION_FALLBACK_OPENAI_AGENT_ID", None)
                else:
                    os.environ["TRANSLATION_FALLBACK_OPENAI_AGENT_ID"] = previous_fallback
        tag_ids = set()
        for feed in feeds:
            tag_ids.update(feed.tags.values_list("id", flat=True))
        for tag in Tag.objects.filter(pk__in=tag_ids):
            for feed_type, format in (("o", "xml"), ("t", "xml"), ("t", "json")):
                try:
                    cache_tag(tag.slug, feed_type=feed_type, format=format)
                except Exception as exc:
                    print("tag_cache_failed", tag.pk, type(exc).__name__, flush=True)
        print("finished", datetime.now(timezone.utc).isoformat(), "failed", failures, flush=True)
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
