#!/usr/bin/python3
"""Forced-command SSH endpoint; exports backups without accepting shell commands."""
import hashlib, json, os, pathlib, shlex, sqlite3, subprocess, sys, tarfile, tempfile
os.umask(0o077)
request = shlex.split(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
def run(*args):
    return subprocess.check_output(args)
if request and request[0] == 'images' and len(request) > 1:
    ids = request[1:]
    if any(len(x) != 71 or not x.startswith('sha256:') or any(c not in '0123456789abcdef' for c in x[7:]) for x in ids):
        sys.exit('Invalid image IDs')
    save = subprocess.Popen(['docker', 'save', *ids], stdout=subprocess.PIPE)
    zip_process = subprocess.Popen(['gzip', '-1'], stdin=save.stdout, stdout=sys.stdout.buffer)
    save.stdout.close()
    zip_rc = zip_process.wait()
    sys.exit(save.wait() or zip_rc)
if request != ['snapshot']:
    sys.exit('Only snapshot and images exports are allowed')
with tempfile.TemporaryDirectory(prefix='rss-backup-') as tmp:
    root = pathlib.Path(tmp)
    source = sqlite3.connect('file:/var/lib/docker/volumes/rss_rssbox-data/_data/db.sqlite3?mode=ro', uri=True, timeout=60)
    dest = sqlite3.connect(root / 'db.sqlite3')
    source.backup(dest, pages=256, sleep=0.1)
    if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        sys.exit('Database integrity failed')
    dest.close(); source.close()
    containers = json.loads(run('docker', 'inspect', *run('docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=rss').decode().split()))
    images = {x['Config']['Image']: x['Image'] for x in containers}
    (root / 'containers.private.json').write_text(json.dumps(containers))
    manifest = {'version': 1, 'images': images, 'db_sha256': hashlib.file_digest(open(root / 'db.sqlite3', 'rb'), 'sha256').hexdigest()}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    def filter_entry(entry):
        if any(part in ('backups', '__pycache__', '.git') for part in pathlib.PurePosixPath(entry.name).parts):
            return None
        return entry
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz', compresslevel=1) as archive:
        archive.add('/opt/rss', arcname='config', filter=filter_entry)
        archive.add('/var/lib/docker/volumes/rss_ext-feeds/_data', arcname='ext-feeds')
        for name in ('db.sqlite3', 'manifest.json', 'containers.private.json'):
            archive.add(root / name, arcname=name)
