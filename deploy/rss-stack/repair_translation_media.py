"""Resumable, compare-and-swap repair. Dry-run unless --apply is explicit.

Run inside RSSBox, with audit_translation_media.py and public_proxy.py beside it.
The state directory must be persistent and private. Original values are retained
per entry; do not restore a whole database snapshot over newer feed updates.
"""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from core.models import Entry, Feed
from core.cache import cache_rss, cache_tag, generate_atom_feed
from core.tasks.translate_feeds import _translate_entry_content, _translate_entry_title
from utils.translation_integrity import translation_error
from audit_translation_media import images

spec = importlib.util.spec_from_file_location('public_proxy', Path(__file__).with_name('public-proxies') / 'proxy.py')
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


def atomic_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False))
    tmp.replace(path)


def refresh(feed_ids):
    for feed in Feed.objects.filter(pk__in=feed_ids):
        # Do not clear unrelated cache keys or override the live scheduler state.
        for kind in ('t', 'o'):
            if feed.translation_status is not None or kind == 'o':
                cache_rss(feed.slug, kind)
            else:
                cache.set(f'cache_rss_{feed.slug}_{kind}_xml', generate_atom_feed(feed, kind),
                          feed.update_frequency or 86400)
        for tag in feed.tags.all():
            for kind in ('t', 'o'):
                cache_tag(tag.name, kind)


def problems(entry):
    reasons = []
    original, translated = entry.original_content or '', entry.translated_content or ''
    if translated and translation_error(original, translated):
        reasons.append('content_classifier')
    if translated and images(original) != images(translated):
        reasons.append('images')
    if entry.translated_title and translation_error(entry.original_title or '', entry.translated_title):
        reasons.append('title_classifier')
    return reasons


def prepare(state_dir, apply):
    visible = set()
    for feed in Feed.objects.all():
        visible.update(feed.entries.order_by('-pubdate').values_list('pk', flat=True)[:feed.max_posts])
    rows, touched = [], set()
    for entry in Entry.objects.select_related('feed').iterator():
        path = state_dir / f'{entry.pk}.json' if apply else None
        if path and path.exists():
            old_row = json.loads(path.read_text())
            rows.append({k: v for k, v in old_row.items() if k != 'before'})
            touched.add(entry.feed_id)
            continue
        before = {field: getattr(entry, field) for field in (
            'original_content', 'translated_content', 'translated_title')}
        if entry.link.startswith('https://www.anthropic.com/'):
            for field in ('original_content', 'translated_content'):
                value = getattr(entry, field)
                if value:
                    setattr(entry, field, proxy.normalize_anthropic_html(value))
        reasons = problems(entry)
        if 'content_classifier' in reasons:
            entry.translated_content = None  # Serve intact original until verified retranslation.
        if 'title_classifier' in reasons:
            entry.translated_title = None
        changed = {field: getattr(entry, field) for field in before if before[field] != getattr(entry, field)}
        if not reasons and not changed:
            continue
        row = dict(id=entry.pk, feed=entry.feed_id, visible=entry.pk in visible,
                   reasons=reasons, before=before, status='pending' if reasons else 'done')
        if apply:
            atomic_json(state_dir / f'{entry.pk}.json', row)
            if changed:
                changed['updated'] = timezone.now()
                if Entry.objects.filter(pk=entry.pk, **before).update(**changed) != 1:
                    row['status'] = 'conflict'
                    atomic_json(state_dir / f'{entry.pk}.json', row)
                else:
                    touched.add(entry.feed_id)
        rows.append({k: v for k, v in row.items() if k != 'before'})
    if apply:
        atomic_json(state_dir / 'prepared.json', dict(count=len(rows)))
        refresh(touched)
    print(json.dumps(dict(prepared=len(rows), pending=sum(r['status'] == 'pending' for r in rows),
                         visible=sum(r['visible'] and r['status'] == 'pending' for r in rows))), flush=True)


def repair(state_dir, limit, only_ids):
    rows = []
    for path in state_dir.glob('*.json'):
        if path.stem.isdigit():
            row = json.loads(path.read_text())
            if row['status'] in ('pending', 'failed') and (not only_ids or row['id'] in only_ids):
                rows.append((path, row))
    # Current articles first, newest first. Serial calls respect model RPM limits.
    rows.sort(key=lambda item: (not item[1]['visible'], -item[1]['id']))
    for path, row in rows[:limit]:
        started = time.monotonic()
        print(json.dumps(dict(start=row['id'], reasons=row['reasons'])), flush=True)
        try:
            entry = Entry.objects.select_related('feed').get(pk=row['id'])
            feed = entry.feed
            baseline = {field: getattr(entry, field) for field in ('original_content', 'translated_content', 'translated_title')}
            metrics = {'tokens': 0, 'characters': 0}
            fields = {}
            if any(reason in row['reasons'] for reason in ('images', 'content_classifier')):
                # If a concurrent scheduled translation already fixed it, retain that result.
                if not entry.translated_content or problems(entry):
                    entry.translated_content = None
                    result = _translate_entry_content(entry, feed.target_language, feed.translator, feed.additional_prompt)
                    for key in metrics:
                        metrics[key] += result.get(key, 0)
                    if images(entry.original_content) != images(entry.translated_content):
                        raise ValueError('final image inventory differs from original')
                    fields['translated_content'] = entry.translated_content
            if 'title_classifier' in row['reasons'] and not entry.translated_title:
                result = _translate_entry_title(entry, feed.target_language, feed.translator, feed.additional_prompt)
                if translation_error(entry.original_title or '', entry.translated_title):
                    raise ValueError('title translation still invalid')
                fields['translated_title'] = entry.translated_title
                for key in metrics:
                    metrics[key] += result.get(key, 0)
            if fields:
                fields['updated'] = timezone.now()
                if Entry.objects.filter(pk=entry.pk, **baseline).update(**fields) != 1:
                    raise ValueError('entry changed concurrently; not overwritten')
                Feed.objects.filter(pk=feed.pk).update(total_tokens=F('total_tokens') + metrics['tokens'],
                                                     total_characters=F('total_characters') + metrics['characters'])
                refresh({feed.pk})
            row['status'] = 'done'
            row.pop('error', None)
        except Exception as error:
            row['status'] = 'failed'
            # Do not log API error bodies/credentials into the repair manifest.
            row['error'] = type(error).__name__
            if isinstance(error, ValueError) and str(error).startswith((
                'Translation rejected for entry ', 'final image inventory',
                'title translation still invalid', 'entry changed concurrently',
                'restored media inventory', 'missing, duplicated',
                'model introduced unprotected')):
                row['error'] += ': ' + str(error)
        row['seconds'] = round(time.monotonic() - started, 1)
        atomic_json(path, row)
        print(json.dumps({k: row[k] for k in ('id', 'status', 'seconds')}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--state-dir', default='/app/data/media-repair-20260910')
    parser.add_argument('--limit', type=int, default=0, help='maximum retranslation count this invocation')
    parser.add_argument('--ids', default='')
    args = parser.parse_args()
    if not args.apply:
        prepare(None, False)
        return
    os.umask(0o077)
    state_dir = Path(args.state_dir)
    state_dir.mkdir(mode=0o700, exist_ok=True)
    with (state_dir / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not (state_dir / 'prepared.json').exists():
            prepare(state_dir, True)
        if args.limit:
            repair(state_dir, args.limit, {int(v) for v in args.ids.split(',') if v})


if __name__ == '__main__':
    main()
