"""Resume Anthropic body translations one entry at a time.

Run inside the RSSBox container with a conservative
TRANSLATE_OUTPUT_TOKEN_CAP. Unlike the bulk task, each completed entry is
saved immediately and the public feed's translation_status is untouched.
"""

import time
import os

from core.models import Feed
from core.tasks.translate_feeds import _translate_entry_content


for feed_id in [int(value) for value in os.environ['RSS_TRANSLATE_FEED_IDS'].split(',')]:
    feed = Feed.objects.get(pk=feed_id)
    for entry in feed.entries.order_by("-pubdate")[: feed.max_posts]:
        if entry.translated_content or not entry.original_content:
            continue
        try:
            _translate_entry_content(
                entry,
                feed.target_language,
                feed.translator,
                feed.additional_prompt,
            )
            entry.save(update_fields=["translated_content"])
            print(f"translated feed={feed_id} entry={entry.pk}", flush=True)
        except Exception as exc:
            print(
                f"failed feed={feed_id} entry={entry.pk} type={type(exc).__name__}",
                flush=True,
            )
        time.sleep(2)
