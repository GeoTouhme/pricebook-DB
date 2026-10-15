"""Preserve website inventory and link only exact UPC matches."""
import argparse
import csv
from datetime import date
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from import_pricebook import ROOT, unwrap


def cents(value):
    if not value.strip():
        return None
    number = Decimal(value) * 100
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f'Invalid monetary amount: {value!r}')
    return int(number)


def import_inventory(source, database, snapshot_date):
    date.fromisoformat(snapshot_date)
    source = Path(source)
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig'), newline=''))
    required = {'UPC', 'Name', 'Price', 'Sale Price', 'Stock', 'Category', 'SubCategory', 'Status', 'Code', 'Image URL'}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError('Missing website inventory columns')
    rows = list(reader)
    if not rows:
        raise ValueError('No inventory rows')
    with sqlite3.connect(database) as db:
        db.executescript((ROOT / 'schema.sql').read_text())
        existing = db.execute('SELECT id FROM imports WHERE sha256=?', (digest,)).fetchone()
        if existing:
            dates = {r[0] for r in db.execute('SELECT DISTINCT snapshot_date FROM website_inventory_rows WHERE import_id=?', existing)}
            if dates != {snapshot_date}:
                raise ValueError('File already imported with another date or import type')
            return {'status': 'already_imported', 'rows': len(rows)}
        if db.execute('SELECT 1 FROM website_inventory_rows WHERE snapshot_date=? LIMIT 1', (snapshot_date,)).fetchone():
            raise ValueError('A different website snapshot already exists for this date. Choose the correct export date; replacing a snapshot is not supported.')
        batch = db.execute('INSERT INTO imports(source_name,sha256,row_count) VALUES (?,?,?)',
                           (source.name, digest, len(rows))).lastrowid
        products = {r[0] for r in db.execute('SELECT upc FROM products')}
        matched = 0
        for number, row in enumerate(rows, 2):
            upc = unwrap(row['UPC'])
            if not upc or not upc.isascii() or not upc.isdigit():
                raise ValueError(f'Invalid UPC at row {number}')
            stock = Decimal(row['Stock'])
            if not stock.is_finite():
                raise ValueError(f'Invalid stock at row {number}')
            link = upc if upc in products else None
            db.execute('INSERT INTO website_inventory_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (batch, number, upc, link, snapshot_date, row['Name'], cents(row['Price']),
                        cents(row['Sale Price']), row['Stock'], row['Category'], row['SubCategory'],
                        row['Status'], row['Code'], row['Image URL'], json.dumps(row, ensure_ascii=False)))
            if link:
                matched += 1
                db.execute('''INSERT INTO inventory_snapshots
                    (upc,source,location,observed_at,quantity,source_row_key) VALUES (?,?,?,?,?,?)''',
                    (link, 'website', 'website', snapshot_date, row['Stock'], f'{digest}:{number}'))
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Foreign key validation failed')
    return {'status': 'imported', 'rows': len(rows), 'matched': matched, 'unmatched': len(rows)-matched}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--database', default=ROOT / 'data/pricebook.sqlite3')
    parser.add_argument('--snapshot-date', required=True, help='YYYY-MM-DD; date supplied by export metadata')
    args = parser.parse_args()
    print(json.dumps(import_inventory(args.source, args.database, args.snapshot_date)))
