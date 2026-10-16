"""Keep media out of model output and reject known non-translations."""
import hashlib
import re
from html.parser import HTMLParser

MEDIA_TAGS = {"img", "source"}
MARKER = re.compile(r"\[\[RSSBOX_MEDIA_[0-9a-f]{16}_\d+\]\]")
MEDIA_INSTRUCTIONS = (
    "\nPreserve every [[RSSBOX_MEDIA_...]] token exactly once, unchanged, "
    "in its original position and order. These tokens are images, not text. "
    "Translate the complete article, not a summary or a safety assessment."
)


class MediaParser(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.offsets = [0]
        for match in re.finditer('\n', source):
            self.offsets.append(match.end())
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        if tag in MEDIA_TAGS:
            line, col = self.getpos()
            self.tags.append((self.offsets[line - 1] + col, self.get_starttag_text()))

    handle_startendtag = handle_starttag


def protect_media(source):
    salt = hashlib.sha256(source.encode()).hexdigest()[:16]
    if MARKER.search(source):
        raise ValueError("Source already contains reserved media markers")
    parts, media, start = [], {}, 0
    for index, (offset, raw) in enumerate(MediaParser(source).tags):
        token = f"[[RSSBOX_MEDIA_{salt}_{index}]]"
        media[token] = raw
        parts.extend((source[start:offset], token))
        start = offset + len(raw)
    parts.append(source[start:])
    return ''.join(parts), media


def translation_error(source, output):
    if not isinstance(output, str) or not output.strip():
        return "empty translation"
    # Avoid rejecting an article merely quoting the classifier's field names.
    if (re.search(r'User Safety\s*:\s*(?:safe|unsafe)\b', output, re.I)
            and not re.search(r'User Safety\s*:', source, re.I)):
        return "safety classification instead of translation"
    expected = MARKER.findall(source)
    if MARKER.findall(output) != expected:
        return "missing, duplicated or reordered media markers"
    if expected and MediaParser(output).tags:
        return "model introduced unprotected images"
    if expected:
        # Tokens inside comments/attributes would restore to invisible/broken images.
        probe = MARKER.sub('<img src="rssbox-marker">', output)
        if len(MediaParser(probe).tags) != len(expected):
            return "media markers are not in renderable HTML positions"
    return None


def restore_media(output, media):
    if MARKER.findall(output) != list(media):
        raise ValueError("missing, duplicated or reordered media markers")
    if media and MediaParser(output).tags:
        raise ValueError("model introduced unprotected images")
    restored = MARKER.sub(lambda match: media[match.group()], output)
    if [raw for _, raw in MediaParser(restored).tags] != list(media.values()):
        raise ValueError("restored media inventory differs from source")
    return restored
