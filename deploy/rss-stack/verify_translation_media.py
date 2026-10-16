"""Read-only DB/public-Atom/image-HTTP acceptance probes inside RSSBox."""
import argparse
import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from bs4 import BeautifulSoup
from core.models import Entry

UA = 'Mozilla/5.0 RSS media verification'


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=45)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ids', required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--probe-images', action='store_true')
    args = parser.parse_args()
    feeds = {}
    for entry in Entry.objects.select_related('feed').filter(pk__in=[int(v) for v in args.ids.split(',')]):
        if entry.feed_id not in feeds:
            with fetch(f'{args.base_url.rstrip(chr(47))}/rss/{entry.feed.slug}') as response:
                feeds[entry.feed_id] = ET.fromstring(response.read())
        node = next((item for item in feeds[entry.feed_id].findall('{*}entry')
                     if any(link.attrib.get('href') == entry.link for link in item.findall('{*}link'))), None)
        if node is None:
            print(json.dumps(dict(id=entry.pk, public='not in current feed')), flush=True)
            continue
        content = node.find('{*}content')
        public_html = content.text or ''
        imgs = BeautifulSoup(public_html, 'lxml').find_all('img')
        originals = BeautifulSoup(entry.original_content or '', 'lxml').find_all('img')
        translated = BeautifulSoup(entry.translated_content or '', 'lxml').find_all('img')
        inventory = lambda tags: Counter(i.get('src', '') for i in tags)
        row = dict(id=entry.pk, feed=entry.feed_id, original_images=len(originals),
                   translated_images=len(translated), inventory_equal=inventory(originals) == inventory(translated),
                   public_images=len(imgs), public_type=content.attrib.get('type'),
                   internal_images=sum('feed-proxy' in i.get('src', '') for i in imgs),
                   nonabsolute_images=sum(not urllib.parse.urlsplit(i.get('src', '')).scheme for i in imgs),
                   classifier='User Safety:' in public_html, marker='[[RSSBOX_MEDIA_' in public_html)
        if args.probe_images:
            row['http_images'] = []
            urls = list(dict.fromkeys(i.get('src', '') for i in imgs if i.get('src', '').startswith('https://')))
            for url in urls[:2]:
                try:
                    with fetch(url) as response:
                        response.read(32)
                        row['http_images'].append(dict(host=urllib.parse.urlsplit(url).hostname,
                                                       status=response.status, type=response.headers.get('Content-Type')))
                except Exception as error:
                    row['http_images'].append(dict(host=urllib.parse.urlsplit(url).hostname, error=type(error).__name__))
        print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
