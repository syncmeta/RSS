#!/usr/bin/env python3
"""Build a small full-original RSS feed for the public Claude product blog."""

from __future__ import annotations

import email.utils
import html
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

ROOT = "https://claude.com"
INDEX = ROOT + "/resources/articles"
OUT = os.environ.get("CLAUDE_BLOG_OUT", "/srv/ext/claude-blog.xml")
CACHE = os.environ.get("CLAUDE_BLOG_CACHE", "/srv/ext/.claude-blog-cache.json")
LIMIT = 20
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ET.register_namespace("content", CONTENT_NS)


def get_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; RSSFeed/1.0)", "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(2_000_000).decode("utf-8", errors="replace")


def index_links(page: str) -> list[str]:
    links = []
    for slug in re.findall(r'href=["\']((?:https://claude\.com)?/(?:blog|resources/articles)/[^"\'?#]+)', page, re.I):
        if slug.startswith("/blog/category/") or slug.startswith("/blog/tag/"):
            continue
        url = urljoin(ROOT, slug)
        if url not in links:
            links.append(url)
    if not links:
        raise ValueError("Claude blog index has no article links")
    return links[:40]


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def body_html(page: str) -> str:
    marker = re.search(r'<div\b(?=[^>]*data-readtime="content")(?=[^>]*\bu-rich-text-blog\b)[^>]*>', page, re.I)
    if not marker:
        marker = re.search(r'<div\b(?=[^>]*\btext-rich-text--article\b)(?=[^>]*\bw-richtext\b)[^>]*>', page, re.I)
    if not marker:
        raise ValueError("Claude article body not found")
    depth = 1
    end = None
    for match in re.finditer(r"<div\b[^>]*>|</div\s*>", page[marker.end():], re.I):
        depth += -1 if match.group().lower().startswith("</") else 1
        if depth == 0:
            end = marker.end() + match.start()
            break
    if end is None:
        raise ValueError("Claude article body not closed")
    content = page[marker.end():end]
    content = re.sub(r"\s(?:href|src)=[\"'](?!https?:|mailto:|#)([^\"']+)[\"']", lambda m: m.group().replace(m.group(1), urljoin(ROOT, html.unescape(m.group(1)))), content, flags=re.I)
    plain = PlainText()
    plain.feed(content)
    if len(" ".join(plain.parts).strip()) < 150:
        raise ValueError("Claude article body too short")
    return content


def parse_article(page: str, url: str) -> dict:
    for script in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I | re.S):
        try:
            metadata = json.loads(script)
        except ValueError:
            continue
        if metadata.get("@type") != "BlogPosting":
            continue
        title = metadata.get("headline")
        date = metadata.get("datePublished")
        if title and date:
            try:
                published = datetime.fromisoformat(date.replace("Z", "+00:00"))
            except ValueError:
                try:
                    published = datetime.strptime(date, "%b %d, %Y")
                except ValueError:
                    published = datetime.strptime(date, "%B %d, %Y")
            published = published.replace(tzinfo=published.tzinfo or timezone.utc)
            return {"link": url, "title": title, "published": published.isoformat(), "content": body_html(page)}
    raise ValueError("Claude BlogPosting metadata missing")


def build_feed(fetch=get_text):
    links = index_links(fetch(INDEX))
    try:
        with open(CACHE, encoding="utf-8") as source:
            cache = json.load(source)
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    results = []
    for link in links:
        item = cache.get(link)
        if not isinstance(item, dict) or not all(item.get(key) for key in ("title", "published", "content")):
            try:
                item = parse_article(fetch(link), link)
                cache[link] = item
                time.sleep(0.2)
            except Exception as error:
                print("claude-blog article skipped", type(error).__name__, flush=True)
                continue
        results.append(item)
        if len(results) >= LIMIT:
            break
    if not results:
        raise ValueError("Claude blog has no complete articles; previous feed retained")
    seen = {item["link"] for item in results}
    for link, item in cache.items():
        if link not in seen and isinstance(item, dict) and all(item.get(key) for key in ("link", "title", "published", "content")):
            results.append(item)
            seen.add(link)
    results.sort(key=lambda item: item["published"], reverse=True)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    for tag, value in (("title", "Claude Blog"), ("link", INDEX), ("description", "Official Claude product blog; full original articles")):
        ET.SubElement(channel, tag).text = value
    for entry in results[:LIMIT]:
        item = ET.SubElement(channel, "item")
        for tag, value in (("title", entry["title"]), ("link", entry["link"]), ("guid", entry["link"])):
            ET.SubElement(item, tag).text = value
        ET.SubElement(item, "pubDate").text = email.utils.format_datetime(datetime.fromisoformat(entry["published"]))
        ET.SubElement(item, "{%s}encoded" % CONTENT_NS).text = entry["content"]
    data = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cache_tmp, out_tmp = CACHE + ".tmp", OUT + ".tmp"
    with open(cache_tmp, "w", encoding="utf-8") as target:
        json.dump(cache, target, ensure_ascii=False)
    with open(out_tmp, "wb") as target:
        target.write(data)
    os.replace(cache_tmp, CACHE)
    os.replace(out_tmp, OUT)
    print("claude-blog ok", len(results[:LIMIT]), "items", flush=True)


if __name__ == "__main__":
    build_feed()
