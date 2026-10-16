"""Read-only inventory; run inside RSSBox with its Django environment."""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from collections import Counter
import json
import re
from bs4 import BeautifulSoup
from core.models import Entry, Feed


def images(value):
    return Counter(img.get('src', '') for img in BeautifulSoup(value or '', 'lxml').find_all('img'))


def inventory():
    visible = set()
    for feed in Feed.objects.all():
        visible.update(feed.entries.order_by('-pubdate').values_list('pk', flat=True)[:feed.max_posts])
    rows = []
    for entry in Entry.objects.select_related('feed').exclude(translated_content__isnull=True).iterator():
        original, translated = entry.original_content or '', entry.translated_content or ''
        if not translated:
            continue
        reasons = []
        if images(original) != images(translated):
            reasons.append('images')
        if re.search(r'User Safety\s*:\s*(?:safe|unsafe)\b', translated, re.I) and 'User Safety:' not in original:
            reasons.append('classifier')
        if reasons:
            rows.append(dict(id=entry.pk, feed=entry.feed_id, reasons=reasons,
                             visible=entry.pk in visible, chars=len(original)))
    return rows


if __name__ == '__main__':
    rows = inventory()
    print(json.dumps(dict(total=len(rows), visible=sum(r['visible'] for r in rows),
                         chars=sum(r['chars'] for r in rows), rows=rows)))
