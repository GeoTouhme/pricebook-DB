"""Bound automatic upload backups; leave manually named backups untouched."""
from pathlib import Path

KEEP = 10


def prune_backups(database):
    folder = Path(database).parent / 'backups'
    files = [p for pattern in ('before-upload-*.sqlite3', 'before-delivery-*.sqlite3')
             for p in folder.glob(pattern) if p.is_file() and not p.is_symlink()]
    for path in sorted(files, key=lambda p: p.stat().st_mtime_ns, reverse=True)[KEEP:]:
        path.unlink(missing_ok=True)
