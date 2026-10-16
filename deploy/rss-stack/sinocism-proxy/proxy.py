#!/usr/bin/env python3
"""Sinocism 付费全文中转。

公开的 https://sinocism.com/feed 对 only_paid 的文章只给前 ~1000 字预览
（正文尾部是一个「Read more」链接）。带上付费订阅者的 substack.sid，
Substack 的 post API 会返回完整 body_html —— 本脚本逐条把预览换成全文，
写出一份结构完全相同的 RSS 给 RSSBox 抓。

- 只读上游，不改任何本地状态；输出原子替换（先写 .tmp 再 mv）。
- 已经取到过全文的文章缓存在磁盘上：cookie 过期后旧文章不会退回预览。
- 环境变量：SINOCISM_COOKIE（substack.sid 的值，或整条 Cookie 头）、
  OUT（输出路径）、CACHE（缓存路径）、INTERVAL（秒，0 = 只跑一次）。
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

FEED_URL = "https://sinocism.com/feed"
API = "https://sinocism.com/api/v1/posts/{slug}"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

OUT = os.environ.get("OUT", "/srv/ext/sinocism.xml")
CACHE = os.environ.get("CACHE", "/srv/ext/.sinocism-cache.json")
INTERVAL = int(os.environ.get("INTERVAL", "900"))


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%S%z"), *a, flush=True)


def cookie_header():
    raw = (os.environ.get("SINOCISM_COOKIE") or "").strip()
    if not raw:
        return None
    # 允许直接给 substack.sid 的值，也允许给整条 Cookie 头
    return raw if "=" in raw else "substack.sid=" + raw


def get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    ck = cookie_header()
    if ck:
        req.add_header("Cookie", ck)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, CACHE)


def slug_of(link):
    return re.sub(r"[?#].*$", "", (link or "").rstrip("/")).rsplit("/", 1)[-1]


_NUMERIC_ENTITY = re.compile(r"&#(\d{2,7});")


def decode_entities(html):
    """把正文里的数字实体还原成真字符。

    Substack 把每个 CJK 字符编码成 `&#22320;` 这样的 8~9 个 ASCII 字符，
    一篇长文因此膨胀三到五成 —— 翻译按字符/token 计费，这一刀值得省。
    只还原 >= 160 的码位：`&#60;` 之类还原出来会变成真的尖括号，破坏结构。
    """
    def sub(m):
        code = int(m.group(1))
        return chr(code) if code >= 160 else m.group(0)

    return _NUMERIC_ENTITY.sub(sub, html or "")

def looks_truncated(html):
    """Substack 的预览尾巴：正文末尾一个指回原文的 Read more 链接。

    只看结尾 —— 长文正文里也会出现 Read more（引用别的 post），
    整篇搜会把已经完整的长文误判成预览。
    """
    html = html or ""
    return bool(re.search(r">\s*Read more\s*<", html[-600:])) or len(html) < 4000


def build_once():
    ET.register_namespace("content", CONTENT_NS)
    root = ET.fromstring(get(FEED_URL))
    cache = load_cache()
    stats = {"full": 0, "cached": 0, "fetched": 0, "still_short": 0}

    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        slug = slug_of(link)
        node = item.find("{%s}encoded" % CONTENT_NS)
        if node is None or not slug:
            continue
        current = decode_entities(node.text or "")
        node.text = current
        if not looks_truncated(current):
            stats["full"] += 1
            cache[slug] = current
            continue
        if slug in cache and len(cache[slug]) > len(current):
            node.text = cache[slug]
            stats["cached"] += 1
            continue
        try:
            data = json.loads(get(API.format(slug=slug)))
        except (urllib.error.URLError, ValueError, OSError) as e:
            log("api FAILED", slug, repr(e))
            continue
        body = decode_entities(data.get("body_html") or "")
        if len(body) > len(current):
            node.text = body
            cache[slug] = body
            stats["fetched"] += 1
        else:
            stats["still_short"] += 1
        time.sleep(1)

    save_cache(cache)
    tmp = OUT + ".tmp"
    ET.ElementTree(root).write(tmp, encoding="utf-8", xml_declaration=True)
    os.replace(tmp, OUT)
    log("ok", os.path.getsize(OUT), "bytes", stats,
        "auth" if cookie_header() else "NO-COOKIE")
    return stats


def main():
    while True:
        try:
            build_once()
        except Exception as e:  # 中转挂了不该拖垮容器，等下一轮
            log("cycle FAILED", repr(e))
        if INTERVAL <= 0:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
