"""Import your configured OPML in a Django shell. Preview unless RSS_IMPORT_APPLY=1."""
import os
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from core.models import Feed

apply = os.environ.get('RSS_IMPORT_APPLY') == '1'
path = os.environ.get('RSS_IMPORT_OPML', '/tmp/feeds.opml')
for row in ET.parse(path).iter('outline'):
    url = row.get('xmlUrl')
    if not url:
        continue
    name = row.get('title') or row.get('text') or 'Untitled'
    if any(marker in url.upper() for marker in ('YOUR', 'REPLACE_', 'CHANGE_ME', '${', '<', '>')):
        print('SKIP placeholder:', name)
        continue
    if urlsplit(url).scheme not in ('http', 'https'):
        print('SKIP unsupported URL:', name)
        continue
    if not apply:
        print('PREVIEW:', name)
        continue
    feed, created = Feed.objects.get_or_create(
        feed_url=url, target_language='Chinese Simplified',
        defaults={'name': name, 'update_frequency': 60, 'max_posts': 20,
                  'translate_title': False, 'translate_content': False, 'summary': False})
    # Feed URLs may carry personal keys; only report title and outcome.
    print('CREATED:' if created else 'EXISTS:', name)
