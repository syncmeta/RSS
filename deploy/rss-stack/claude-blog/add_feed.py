"""Run with ``python manage.py shell < add_feed.py`` inside RSSBox.

The Claude blog is an independent source from Anthropic News/Engineering.
Keep its full original text; do not start long-form translation on a 1 GiB VPS.
"""

from core.management.commands.feed_updater import update_single_feed
from core.models import Feed

SOURCE = "http://feed-proxy/ext/claude-blog.xml"
feed = Feed.objects.filter(feed_url=SOURCE).first()
if feed is None:
    feed = Feed(
        name="Claude Blog",
        feed_url=SOURCE,
        target_language="Chinese Traditional",
        update_frequency=60,
        max_posts=20,
        translate_title=False,
        translate_content=False,
        summary=False,
    )
    feed.save()
    print("claude-blog created", feed.pk)
else:
    print("claude-blog existing", feed.pk)

ok = update_single_feed(feed)
feed.refresh_from_db()
print("claude-blog fetched", bool(ok), "entries", feed.entries.count(), "id", feed.pk, "slug", feed.slug)
