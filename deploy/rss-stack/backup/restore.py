#!/usr/bin/python3
"""Verify a backup by default; --prepare populates an empty replacement host.
Never starts RSS or connects a public tunnel.
"""
import argparse, hashlib, json, os, pathlib, shutil, sqlite3, subprocess, tarfile, tempfile
os.umask(0o077)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('snapshot', type=pathlib.Path, help='Timestamp directory copied from your backup storage')
parser.add_argument('--images', type=pathlib.Path, required=True, help='Matching images/<image-set>.tar.gz')
parser.add_argument('--prepare', action='store_true', help='Restore into empty /opt/rss and new Docker volumes; no service start')
args = parser.parse_args()
def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
snapshot = args.snapshot / 'snapshot.tar.gz'
assert digest(snapshot) == (args.snapshot / 'SHA256SUMS').read_text().split()[0], 'Snapshot checksum mismatch'
assert args.images.name == (args.snapshot / 'image-set').read_text().strip() + '.tar.gz', 'Wrong image set'
assert digest(args.images) == args.images.with_suffix('.sha256').read_text().strip(), 'Images checksum mismatch'
with tempfile.TemporaryDirectory(prefix='rss-restore-check-') as tmp:
    root = pathlib.Path(tmp)
    # Extract only a verified, trusted backup. Reject absolute/traversal names and links.
    with tarfile.open(snapshot) as archive:
        for entry in archive:
            name = pathlib.PurePosixPath(entry.name)
            assert not name.is_absolute() and '..' not in name.parts
            assert entry.isfile() or entry.isdir(), 'Unexpected archive entry type'
        archive.extractall(root, filter='data')
    manifest = json.loads((root / 'manifest.json').read_text())
    assert digest(root / 'db.sqlite3') == manifest['db_sha256']
    db = sqlite3.connect(f'file:{root / "db.sqlite3"}?mode=ro', uri=True)
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    db.close()
    containers = json.loads((root / 'containers.private.json').read_text())
    compose_files = next(x['Config']['Labels']['com.docker.compose.project.config_files'] for x in containers if x['Config']['Labels'].get('com.docker.compose.service') == 'rssbox').split(',')
    assert all((root / 'config' / pathlib.Path(p).name).is_file() for p in compose_files)
    assert (root / 'config/.env').is_file()
    # Check Docker config blobs against the exact IDs of the captured containers.
    image_ids = set()
    expected = {image_id[7:] for image_id in manifest['images'].values()}
    with tarfile.open(args.images, 'r|gz') as archive:
        for entry in archive:
            name = pathlib.PurePosixPath(entry.name).name.removesuffix('.json')
            if entry.isfile() and name in expected:
                blob = archive.extractfile(entry).read()
                image_ids.add('sha256:' + hashlib.sha256(blob).hexdigest())
    assert image_ids == set(manifest['images'].values()), 'Image inventory mismatch'
    print('Verified database, private configuration, Compose files and exact Docker image IDs.')
    if args.prepare:
        assert os.geteuid() == 0, 'Run --prepare as root'
        assert not pathlib.Path('/opt/rss').exists(), '/opt/rss already exists; refusing overwrite'
        volumes = ('rss_rssbox-data', 'rss_ext-feeds', 'rss_redis-data')
        existing = subprocess.check_output(['docker', 'volume', 'ls', '-q'], text=True).split()
        assert not set(volumes).intersection(existing), 'RSS volumes already exist; refusing overwrite'
        subprocess.run(['docker', 'load', '-i', str(args.images)], check=True)
        for tag, image_id in manifest['images'].items():
            if '@sha256:' not in tag and not tag.startswith('sha256:'):
                subprocess.run(['docker', 'tag', image_id, tag], check=True)
        shutil.copytree(root / 'config', '/opt/rss')
        # Pin all services to the captured image IDs; avoid mutable tags during recovery.
        services = {x['Config']['Labels']['com.docker.compose.service']: {'image': x['Image'], 'pull_policy': 'never'} for x in containers}
        pathlib.Path('/opt/rss/docker-compose.recovery.json').write_text(json.dumps({'services': services}, indent=2))
        for volume in volumes:
            subprocess.run(['docker', 'volume', 'create', volume], check=True, stdout=subprocess.DEVNULL)
        def mountpoint(volume):
            return pathlib.Path(subprocess.check_output(['docker', 'volume', 'inspect', '-f', '{{.Mountpoint}}', volume], text=True).strip())
        shutil.copy2(root / 'db.sqlite3', mountpoint('rss_rssbox-data') / 'db.sqlite3')
        shutil.copytree(root / 'ext-feeds', mountpoint('rss_ext-feeds'), dirs_exist_ok=True)
        print('Prepared /opt/rss and volumes. RSS services and tunnel remain stopped.')
    print('Compose files:', ', '.join(pathlib.Path(p).name for p in compose_files), '+ docker-compose.recovery.json (after --prepare)')
