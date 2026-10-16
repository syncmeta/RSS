#!/usr/bin/env python3
"""Build an authenticated full-text RSS feed for The Diff.

The public Ghost RSS feed contains metadata but no article body.  A paid
member session makes the full article available in the server-rendered page.
This proxy fetches those pages with the member cookie, extracts the article
body, caches successful full text, and atomically publishes an RSS feed for
RSSBox.

THEDIFF_COOKIE accepts either a complete Cookie header or only the value of
Ghost's ``ghost-members-ssr`` cookie. THEDIFF_COOKIE_SIG holds the matching
``ghost-members-ssr.sig`` value when the first variable is only a value.
Never log either secret.
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


FEED_URL = "https://www.thediff.co/archive/rss/"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

OUT = os.environ.get("OUT", "/srv/ext/thediff.xml")
CACHE = os.environ.get("CACHE", "/srv/ext/.thediff-cache.json")
INTERVAL = int(os.environ.get("INTERVAL", "900"))


def log(*parts):
    print(time.strftime("%Y-%m-%dT%H:%M:%S%z"), *parts, flush=True)


def cookie_header():
    raw = (os.environ.get("THEDIFF_COOKIE") or "").strip()
    if not raw:
        return None
    if raw.startswith("ghost-members-ssr=") or ";" in raw:
        header = raw
    else:
        header = "ghost-members-ssr=" + raw
    signature = (os.environ.get("THEDIFF_COOKIE_SIG") or "").strip()
    if signature and "ghost-members-ssr.sig=" not in header:
        header += "; ghost-members-ssr.sig=" + signature
    return header


def get(url, timeout=60):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/rss+xml;q=0.9,*/*;q=0.8",
        },
    )
    cookie = cookie_header()
    if cookie:
        request.add_header("Cookie", cookie)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(cache):
    temporary = CACHE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(cache, stream)
    os.replace(temporary, CACHE)


def _tag_end(source, start):
    quote = None
    for index in range(start, len(source)):
        char = source[index]
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == ">":
            return index + 1
    raise ValueError("unterminated HTML tag")


def extract_content(page):
    """Return the inner HTML of the theme's outer ``div.content``."""
    opening = re.search(
        r"<div\b[^>]*\bclass\s*=\s*([\"'])[^\"']*\bcontent\b[^\"']*\1[^>]*>",
        page,
        re.I,
    )
    if not opening:
        raise ValueError("The Diff content container was not found")

    start = opening.end()
    depth = 1
    for token in re.finditer(r"<div\b|</div\s*>", page[start:], re.I):
        absolute = start + token.start()
        if token.group(0).lower().startswith("</"):
            depth -= 1
            if depth == 0:
                return page[start:absolute].strip()
        else:
            _tag_end(page, absolute)
            depth += 1
    raise ValueError("The Diff content container was not closed")


def is_full_article(content):
    plain = re.sub(r"<[^>]+>", " ", content)
    plain = html.unescape(re.sub(r"\s+", " ", plain)).strip()
    return (
        len(plain) >= 500
        and "This post is for paying subscribers only" not in plain
        and "This post is for members only" not in plain
    )


def content_node(item):
    node = item.find("{%s}encoded" % CONTENT_NS)
    if node is None:
        node = ET.SubElement(item, "{%s}encoded" % CONTENT_NS)
    return node


def build_once():
    ET.register_namespace("content", CONTENT_NS)
    root = ET.fromstring(get(FEED_URL))
    cache = load_cache()
    stats = {"fetched": 0, "cached": 0, "locked": 0, "failed": 0}

    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        if not link:
            continue
        body = None
        try:
            page = get(link).decode("utf-8", "replace")
            candidate = extract_content(page)
            if is_full_article(candidate):
                body = candidate
                cache[link] = candidate
                stats["fetched"] += 1
            else:
                stats["locked"] += 1
        except (urllib.error.URLError, OSError, ValueError) as error:
            log("article FAILED", link, type(error).__name__)
            stats["failed"] += 1

        if body is None and is_full_article(cache.get(link, "")):
            body = cache[link]
            stats["cached"] += 1
        if body is not None:
            content_node(item).text = body
        time.sleep(0.4)

    save_cache(cache)
    temporary = OUT + ".tmp"
    ET.ElementTree(root).write(temporary, encoding="utf-8", xml_declaration=True)
    os.replace(temporary, OUT)
    log(
        "ok",
        os.path.getsize(OUT),
        "bytes",
        stats,
        "auth" if cookie_header() else "NO-COOKIE",
    )
    return stats


def main():
    while True:
        try:
            build_once()
        except Exception as error:
            log("cycle FAILED", type(error).__name__, str(error))
        if INTERVAL <= 0:
            return 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
