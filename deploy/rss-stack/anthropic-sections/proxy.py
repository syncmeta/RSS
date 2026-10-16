#!/usr/bin/env python3
"""Publish Anthropic News and Engineering as full-text local RSS feeds."""

import email.utils
import html
import importlib.util
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin


SPEC = importlib.util.spec_from_file_location("public_proxies", "/app/public-proxies.py")
PUBLIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLIC)

ROOT = "https://www.anthropic.com"
OUT_DIR = os.environ.get("OUT_DIR", "/srv/ext")
INTERVAL = int(os.environ.get("INTERVAL", "900"))
CONTENT_TAG = "{%s}encoded" % PUBLIC.CONTENT_NS
ET.register_namespace("content", PUBLIC.CONTENT_NS)


def news_posts(page):
    """Read the complete publication list embedded in Next.js flight data."""
    chunks = []
    for script in re.findall(r"<script[^>]*>(.*?)</script>", page, re.I | re.S):
        match = re.search(r"self\.__next_f\.push\((.+)\)\s*;?\s*$", script, re.S)
        if not match:
            continue
        try:
            packet = json.loads(html.unescape(match.group(1)))
        except ValueError:
            continue
        if isinstance(packet, list) and len(packet) == 2 and packet[0] == 1:
            chunks.append(packet[1])
    payload = "".join(chunks)
    lists = []
    for match in re.finditer(r'"posts"\s*:\s*\[', payload):
        try:
            candidates, _ = json.JSONDecoder().raw_decode(payload[match.end() - 1 :])
        except ValueError:
            continue
        if isinstance(candidates, list):
            lists.append(candidates)
    if not lists:
        raise ValueError("Anthropic News posts were not found")

    posts = []
    seen = set()
    for candidate in max(lists, key=len):
        if not isinstance(candidate, dict):
            continue
        slug = candidate.get("slug")
        slug = slug.get("current") if isinstance(slug, dict) else slug
        title = (candidate.get("title") or "").strip()
        published = candidate.get("publishedOn")
        if slug and title and published and slug not in seen:
            seen.add(slug)
            posts.append({"slug": slug, "title": title, "published": published})
    return sorted(posts, key=lambda item: item["published"], reverse=True)[:20]


def engineering_links(page):
    links = []
    seen = set()
    for slug in re.findall(r'href=["\'](/engineering/[^"\'?#]+)', page, re.I):
        if slug not in seen:
            seen.add(slug)
            links.append(urljoin(ROOT, slug))
    if not links:
        raise ValueError("Anthropic Engineering links were not found")
    return links


def engineering_metadata(page):
    title_match = re.search(r"<title>(.*?)</title>", page, re.I | re.S)
    date_match = re.search(r"Published\s*(?:<!--.*?-->\s*)?([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", page, re.S)
    if not title_match or not date_match:
        raise ValueError("Anthropic Engineering title or publication date missing")
    title = html.unescape(title_match.group(1)).split("\\ Anthropic")[0].strip()
    date_text = date_match.group(1)
    try:
        published = datetime.strptime(date_text, "%B %d, %Y")
    except ValueError:
        published = datetime.strptime(date_text, "%b %d, %Y")
    published = published.replace(tzinfo=timezone.utc)
    return title, published.isoformat()


def build_section(section):
    index = f"{ROOT}/{section}"
    page = PUBLIC.get_text(index)
    cache_path = f"{OUT_DIR}/.anthropic-{section}-cache.json"
    cache = PUBLIC.load_json(cache_path)
    if section == "news":
        posts = [dict(item, link=f"{index}/{item['slug']}") for item in news_posts(page)]
    else:
        posts = []
        for link in engineering_links(page):
            saved = cache.get(link) or {}
            if saved.get("title") and saved.get("published") and saved.get("content"):
                posts.append(dict(saved, link=link))
                continue
            try:
                article = PUBLIC.get_text(link)
                title, published = engineering_metadata(article)
                content = PUBLIC.normalize_anthropic_html(PUBLIC.extract_outer_article(article))
                posts.append({"link": link, "title": title, "published": published, "content": content})
                time.sleep(0.3)
            except Exception as error:
                PUBLIC.log("anthropic", section, "article FAILED", link, type(error).__name__)
        posts.sort(key=lambda item: item["published"], reverse=True)
        posts = posts[:20]

    if not posts:
        raise ValueError(f"Anthropic {section} has no posts")
    root, channel = PUBLIC.new_channel(
        "Anthropic " + section.title(), index, f"Latest {section} from Anthropic"
    )
    fetched = 0
    for post in posts:
        link = post["link"]
        saved = cache.get(link) or {}
        content = post.get("content") or saved.get("content")
        if not content:
            try:
                content = PUBLIC.normalize_anthropic_html(
                    PUBLIC.extract_outer_article(PUBLIC.get_text(link))
                )
                fetched += 1
                time.sleep(0.3)
            except Exception as error:
                PUBLIC.log("anthropic", section, "article FAILED", link, type(error).__name__)
                continue
        content = PUBLIC.normalize_anthropic_html(content)
        cache[link] = {"title": post["title"], "published": post["published"], "content": content}
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = post["title"]
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = link
        ET.SubElement(item, "pubDate").text = PUBLIC.rfc2822(post["published"])
        ET.SubElement(item, CONTENT_TAG).text = content
    if not len(channel.findall("item")):
        raise ValueError(f"Anthropic {section} has no complete articles")
    PUBLIC.save_json(cache_path, cache)
    output = f"{OUT_DIR}/anthropic-{section}.xml"
    PUBLIC.atomic_write(output, ET.tostring(root, encoding="utf-8", xml_declaration=True))
    PUBLIC.log("anthropic", section, "ok", len(channel.findall("item")), "items", fetched, "fetched")


def main():
    while True:
        for section in ("news", "engineering"):
            try:
                build_section(section)
            except Exception as error:
                PUBLIC.log("anthropic", section, "FAILED", type(error).__name__, str(error))
        if INTERVAL <= 0:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
