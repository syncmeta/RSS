#!/usr/bin/env python3
"""Build local RSS files for public sources whose RSSHub routes are broken.

The generated files are served by feed-proxy from the shared ext-feeds volume.
Only Python's standard library is used so this can run in the existing small
sinocism-proxy container without adding another resident service.
"""

from __future__ import annotations

import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.request
from urllib.parse import parse_qs, urljoin, urlsplit
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ANTHROPIC_INDEX = "https://www.anthropic.com/research"
ANTHROPIC_OUT = os.environ.get("ANTHROPIC_OUT", "/srv/ext/anthropic-research.xml")
ANTHROPIC_CACHE = os.environ.get("ANTHROPIC_CACHE", "/srv/ext/.anthropic-cache.json")
LAURA_URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/laurashin"
LAURA_OUT = os.environ.get("LAURA_OUT", "/srv/ext/laurashin.xml")
LAURA_CACHE = os.environ.get("LAURA_CACHE", "/srv/ext/.laurashin-timeline.html")
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"


def log(*parts):
    print(time.strftime("%Y-%m-%dT%H:%M:%S%z"), *parts, flush=True)


def get_text(url, timeout=60):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as output:
        output.write(data)
    os.replace(tmp, path)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as source:
            value = json.load(source)
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False).encode())


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_anthropic_index(page):
    """Extract Research posts from Next.js flight data.

    RSSHub's route only inspects ``item.page.sections``. Anthropic now nests the
    same Publications object more deeply, so that route returns an empty feed.
    Walking the decoded flight records makes the extraction insensitive to that
    wrapper layout.
    """
    chunks = []
    for script in re.findall(r"<script[^>]*>(.*?)</script>", page, re.I | re.S):
        match = re.search(r"self\.__next_f\.push\((.+)\)\s*;?\s*$", script, re.S)
        if not match:
            continue
        try:
            payload = json.loads(html.unescape(match.group(1)))
        except ValueError:
            continue
        if isinstance(payload, list) and len(payload) == 2 and payload[0] == 1:
            chunks.append(payload[1])

    records = []
    part = re.compile(r"^([0-9a-z]+):([0-9a-z]+)?(\[.*)$", re.I)
    for line in "".join(chunks).splitlines():
        match = part.match(line)
        if not match:
            continue
        try:
            records.append(json.loads(match.group(3)))
        except ValueError:
            continue

    sections = [
        obj
        for record in records
        for obj in walk_json(record)
        if obj.get("title") == "Publications" and isinstance(obj.get("posts"), list)
    ]
    if not sections:
        raise RuntimeError("Anthropic Publications section was not found")

    posts = []
    seen = set()
    for post in max(sections, key=lambda item: len(item["posts"]))["posts"]:
        if not isinstance(post, dict):
            continue
        slug_value = post.get("slug")
        slug = slug_value.get("current") if isinstance(slug_value, dict) else slug_value
        title = post.get("title")
        published = post.get("publishedOn")
        if not (slug and title and published) or slug in seen:
            continue
        seen.add(slug)
        posts.append({"slug": slug, "title": title, "published": published})
        if len(posts) == 20:
            break
    return posts


def extract_outer_article(page):
    main = re.search(r"<main\b[^>]*\bid=[\"']main-content[\"'][^>]*>", page, re.I)
    start_at = main.end() if main else 0
    start = re.search(r"<article\b[^>]*>", page[start_at:], re.I)
    if not start:
        raise RuntimeError("article element was not found")
    begin = start_at + start.start()
    depth = 0
    for token in re.finditer(r"<article\b[^>]*>|</article\s*>", page[begin:], re.I):
        if token.group(0).lower().startswith("</"):
            depth -= 1
            if depth == 0:
                return page[begin : begin + token.end()]
        else:
            depth += 1
    raise RuntimeError("article element was not closed")


def rfc2822(iso_date):
    parsed = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    return email.utils.format_datetime(parsed.astimezone(timezone.utc))


def normalize_anthropic_html(content):
    """Fix cached as well as fresh HTML before an internal proxy becomes its base."""
    def public_url(value):
        value = html.unescape(value)
        parsed = urlsplit(value)
        if parsed.path == '/_next/image' and parsed.hostname in (
            None, 'feed-proxy', 'www.anthropic.com', 'anthropic.com'
        ):
            target = parse_qs(parsed.query).get('url', [''])[0]
            if target and urlsplit(target).scheme in ('', 'http', 'https'):
                value = target
        elif parsed.hostname == 'feed-proxy':
            value = parsed.path + ('?' + parsed.query if parsed.query else '')
        return urljoin('https://www.anthropic.com/', value)

    def attribute(match):
        name, quote, value = match.groups()
        if name.lower() == 'srcset':
            if 'data:' in value:
                return match.group()
            candidates = []
            for candidate in html.unescape(value).split(','):
                parts = candidate.strip().split()
                if parts:
                    candidates.append(' '.join([public_url(parts[0])] + parts[1:]))
            value = ', '.join(candidates)
        else:
            value = public_url(value)
        return f'{name}={quote}{html.escape(value, quote=True)}{quote}'

    class Rewriter(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.edits = []
            self.offsets = [0] + [m.end() for m in re.finditer('\n', content)]

        def handle_starttag(self, tag, attrs):
            raw = self.get_starttag_text()
            fixed = re.sub(r'\b(src|srcset|href|poster)\s*=\s*([\"\'])(.*?)\2', attribute, raw, flags=re.I | re.S)
            if fixed != raw:
                line, col = self.getpos()
                self.edits.append((self.offsets[line - 1] + col, raw, fixed))

        handle_startendtag = handle_starttag

    parser = Rewriter()
    parser.feed(content)
    for offset, raw, fixed in reversed(parser.edits):
        content = content[:offset] + fixed + content[offset + len(raw):]
    return content


def new_channel(title, link, description):
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = link
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "lastBuildDate").text = email.utils.format_datetime(
        datetime.now(timezone.utc)
    )
    return root, channel


def build_anthropic():
    posts = parse_anthropic_index(get_text(ANTHROPIC_INDEX))
    cache = load_json(ANTHROPIC_CACHE)
    root, channel = new_channel(
        "Anthropic Research", ANTHROPIC_INDEX, "Latest research from Anthropic"
    )
    fetched = 0
    for post in posts:
        slug = post["slug"]
        link = f"https://www.anthropic.com/research/{slug}"
        content = cache.get(slug)
        if not content:
            try:
                content = extract_outer_article(get_text(link))
                cache[slug] = content
                fetched += 1
                time.sleep(0.3)
            except Exception as error:
                log("anthropic article FAILED", slug, repr(error))
                content = f'<p><a href="{html.escape(link)}">Read on Anthropic</a></p>'
        content = normalize_anthropic_html(content)
        cache[slug] = content
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = post["title"]
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = link
        ET.SubElement(item, "pubDate").text = rfc2822(post["published"])
        ET.SubElement(item, f"{{{CONTENT_NS}}}encoded").text = content

    save_json(ANTHROPIC_CACHE, cache)
    ET.register_namespace("content", CONTENT_NS)
    atomic_write(ANTHROPIC_OUT, ET.tostring(root, encoding="utf-8", xml_declaration=True))
    log("anthropic ok", len(posts), "items", fetched, "articles fetched")


def parse_laura(page):
    match = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page,
        re.I | re.S,
    )
    if not match:
        raise RuntimeError("X __NEXT_DATA__ was not found")
    data = json.loads(html.unescape(match.group(1)))
    entries = data["props"]["pageProps"]["timeline"]["entries"]
    tweets = []
    seen = set()
    for entry in entries:
        tweet = ((entry or {}).get("content") or {}).get("tweet") or {}
        tweet_id = tweet.get("id_str")
        if not tweet_id or tweet_id in seen:
            continue
        seen.add(tweet_id)
        tweets.append(tweet)
    return tweets


def build_laura():
    try:
        with open(LAURA_CACHE, encoding="utf-8") as source:
            page = source.read()
    except OSError:
        # The Alpine curl sidecar normally refreshes this file because X treats
        # Python's TLS client differently. This fallback keeps local tests and
        # first-run deployments usable when urllib happens to be accepted.
        page = get_text(LAURA_URL)
        atomic_write(LAURA_CACHE, page.encode())
    tweets = parse_laura(page)
    root, channel = new_channel(
        "X / Laura Shin", "https://x.com/laurashin", "Laura Shin posts from X"
    )
    for tweet in tweets:
        tweet_id = tweet["id_str"]
        link = f"https://x.com/laurashin/status/{tweet_id}"
        text = tweet.get("full_text") or tweet.get("text") or ""
        content = "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"
        media = (tweet.get("entities") or {}).get("media") or []
        for asset in media:
            src = asset.get("media_url_https") or asset.get("media_url")
            if src:
                content += f'<p><img src="{html.escape(src)}"></p>'
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = re.sub(r"\s+", " ", text).strip()[:180]
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = link
        ET.SubElement(item, "pubDate").text = tweet.get("created_at")
        ET.SubElement(item, f"{{{CONTENT_NS}}}encoded").text = content

    ET.register_namespace("content", CONTENT_NS)
    atomic_write(LAURA_OUT, ET.tostring(root, encoding="utf-8", xml_declaration=True))
    log("laurashin ok", len(tweets), "items")


def main():
    failures = 0
    for name, build in (("anthropic", build_anthropic), ("laurashin", build_laura)):
        try:
            build()
        except Exception as error:
            failures += 1
            log(name, "FAILED", repr(error))
    return failures


if __name__ == "__main__":
    sys.exit(main())
