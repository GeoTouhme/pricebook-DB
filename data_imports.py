"""Validate uploads against a database copy before applying existing importers."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

from import_pricebook import import_pricebook
from import_website_inventory import import_inventory

MAX_BYTES = 20 * 1024 * 1024


def copy_database(source, destination):
    with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(destination)) as target:
            src.backup(target)


def run_import(payload, filename, kind, database, snapshot_date=None):
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError('Choose a nonempty CSV file smaller than 20 MB.')
    if kind not in ('pricebook', 'website'):
        raise ValueError('Unknown import type.')
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / Path(filename.replace('\\', '/')).name
        source.write_bytes(payload)
        if kind == 'pricebook':
            return import_pricebook(source, database)
        return import_inventory(source, database, snapshot_date)


def preview_import(payload, filename, kind, database, snapshot_date=None):
    with tempfile.TemporaryDirectory() as directory:
        staged = Path(directory) / 'preview.sqlite3'
        copy_database(database, staged)
        with closing(sqlite3.connect(staged)) as db:
            before = {r[0]: r[1:] for r in db.execute('SELECT * FROM product_catalog')}
        result = run_import(payload, filename, kind, staged, snapshot_date)
        if kind == 'pricebook':
            with closing(sqlite3.connect(staged)) as db:
                after = {r[0]: r[1:] for r in db.execute('SELECT * FROM product_catalog')}
                # Ignore import provenance when comparing product values.
                changed = [upc for upc in before if before[upc][:14] != after[upc][:14]]
                added = sorted(after.keys() - before.keys())
                result.update(new_products=len(added), updated_products=len(changed))
                affected = added + changed
                result['sample'] = [dict(zip(('UPC', 'Name', 'Price cents', 'Price quantity'),
                    db.execute('SELECT upc,name,price_cents,price_qty FROM products WHERE upc=?', (upc,)).fetchone()))
                    for upc in affected[:50]]
        else:
            with closing(sqlite3.connect(staged)) as db:
                batch = db.execute('SELECT max(id) FROM imports').fetchone()[0]
                result['sample'] = [dict(zip(('UPC', 'Name', 'Stock', 'Catalog UPC'), r)) for r in db.execute(
                    'SELECT website_upc,name,stock,matched_upc FROM website_inventory_rows WHERE import_id=? LIMIT 50', (batch,))]
        return result


def save_import(payload, filename, kind, database, snapshot_date=None):
    # Revalidate against current data; never replace the live database with the preview copy.
    preview = preview_import(payload, filename, kind, database, snapshot_date)
    if preview['status'] == 'already_imported':
        return preview
    folder = Path(database).parent / 'backups'
    folder.mkdir(exist_ok=True)
    backup = folder / f'before-upload-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.sqlite3'
    copy_database(database, backup)
    result = run_import(payload, filename, kind, database, snapshot_date)
    return dict(result, backup=str(backup))
