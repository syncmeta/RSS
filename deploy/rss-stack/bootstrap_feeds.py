import json
import os

from config import settings
from core.management.commands.feed_updater import update_single_feed
from core.models import Feed


rsshub_access_key = os.environ["RSSHUB_ACCESS_KEY"]

feed_specs = [
    (
        "即刻 - AI探索站",
        "http://rsshub:1200/jike/topic/63579abb6724cc583b9bba9a"
        f"?key={rsshub_access_key}",
    ),
    (
        "Founder Park",
        "https://wechat2rss.bestblogs.dev/feed/"
        "f940695505f2be1399d23cc98182297cadf6f90d.xml",
    ),
    ("Latent Space", "https://www.latent.space/feed"),
    ("Ben's Bites", "https://www.bensbites.com/feed"),
]

results = []
for name, feed_url in feed_specs:
    feed, created = Feed.objects.get_or_create(
        feed_url=feed_url,
        target_language="Chinese Simplified",
        defaults={
            "name": name,
            "update_frequency": 60,
            "max_posts": 20,
            "translate_title": False,
            "translate_content": False,
            "summary": False,
        },
    )
    if feed.name != name:
        feed.name = name
        feed.save(update_fields=["name"])

    updated = update_single_feed(feed)
    feed.refresh_from_db()
    results.append(
        {
            "name": feed.name,
            "id": feed.id,
            "slug": feed.slug,
            "created": created,
            "updated": updated,
            "fetch_status": feed.fetch_status,
            "entries": feed.entries.count(),
            "url": f"{settings.SITE_URL.rstrip('/')}/rss/{feed.slug}",
        }
    )

print(json.dumps(results, ensure_ascii=False))
