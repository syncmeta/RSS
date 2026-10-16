#!/usr/bin/python3
"""Pull consistent snapshots and Docker images to local private storage."""
import argparse, datetime, fcntl, hashlib, json, os, pathlib, shlex, sqlite3, subprocess, tarfile, tempfile
os.umask(0o077)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[3] / 'backups/rss')
parser.add_argument('--host', required=True, help='SSH destination, e.g. root@rss.example.com')
parser.add_argument('--identity', type=pathlib.Path)
parser.add_argument('--known-hosts', type=pathlib.Path)
parser.add_argument('--restricted', action='store_true', help='Use the old forced-command standby key')
args = parser.parse_args()
ROOT = args.root.expanduser().resolve()
ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
lock = open(ROOT / '.lock', 'w')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3']
if args.identity:
    SSH += ['-i', str(args.identity.expanduser())]
if args.known_hosts:
    SSH += ['-o', 'UserKnownHostsFile=' + str(args.known_hosts.expanduser())]
SSH.append(args.host)
def download(command, target):
    partial = target.with_suffix(target.suffix + '.partial')
    try:
        with open(partial, 'wb') as output:
            remote = command if args.restricted else '/usr/bin/ionice -c3 /usr/bin/nice -n 15 /usr/bin/env SSH_ORIGINAL_COMMAND=' + shlex.quote(command) + ' /usr/bin/python3 /usr/local/sbin/rss-backup-export'
            subprocess.run(SSH + [remote], stdout=output, check=True, timeout=2400)
        partial.rename(target)
    finally:
        partial.unlink(missing_ok=True)
def checksum(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
def checked_image(path):
    # Fully consume each member to verify gzip CRC and tar readability.
    with tarfile.open(path, 'r|gz') as archive:
        for member in archive:
            if member.isfile():
                stream = archive.extractfile(member)
                while stream.read(1024 * 1024):
                    pass
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
staging = ROOT / ('.staging-' + stamp)
staging.mkdir(mode=0o700)
try:
    snapshot = staging / 'snapshot.tar.gz'
    download('snapshot', snapshot)
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        with tarfile.open(snapshot) as archive:
            manifest = json.load(archive.extractfile('manifest.json'))
            db = pathlib.Path(tmp) / 'db.sqlite3'
            with open(db, 'wb') as out:
                import shutil
                shutil.copyfileobj(archive.extractfile('db.sqlite3'), out)
        assert checksum(db) == manifest['db_sha256'], 'Database checksum mismatch'
        connection = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        connection.close()
    ids = sorted(set(manifest['images'].values()))
    image_key = hashlib.sha256('\n'.join(ids).encode()).hexdigest()
    image_dir = ROOT / 'images'; image_dir.mkdir(exist_ok=True)
    image_file = image_dir / (image_key + '.tar.gz')
    if not image_file.exists():
        download('images ' + ' '.join(ids), image_file)
        try:
            checked_image(image_file)
        except Exception:
            image_file.unlink(missing_ok=True)
            raise
        image_file.with_suffix('.sha256').write_text(checksum(image_file) + '\n')
    else:
        assert checksum(image_file) == image_file.with_suffix('.sha256').read_text().strip(), 'Image checksum mismatch'
    (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    (staging / 'image-set').write_text(image_key + '\n')
    (staging / 'SHA256SUMS').write_text(checksum(snapshot) + '  snapshot.tar.gz\n')
    staging.rename(ROOT / stamp)
    # Keep 12 recent snapshots plus one snapshot per backup date for seven dates.
    snapshots = sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name.startswith('20'))
    keep = set(snapshots[-12:]); days = {}
    for path in snapshots:
        days[path.name[:8]] = path
    keep.update(list(days.values())[-7:])
    import shutil
    for path in snapshots:
        if path not in keep:
            shutil.rmtree(path)
    used = {(p / 'image-set').read_text().strip() for p in keep}
    for path in image_dir.glob('*.tar.gz'):
        if path.name[:-7] not in used:
            path.unlink(); path.with_suffix('.sha256').unlink(missing_ok=True)
    (ROOT / 'last-success.json').write_text(json.dumps({'utc': stamp, 'snapshots': len(keep), 'snapshot_bytes': (ROOT / stamp / 'snapshot.tar.gz').stat().st_size}))
    print('Backup verified:', ROOT / stamp, 'retained:', len(keep))
finally:
    if staging.exists():
        import shutil
        shutil.rmtree(staging)
