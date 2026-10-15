"""Import daily POS summaries without inventing transaction IDs or net revenue."""
import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from import_pricebook import ROOT, unwrap


def parse_date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return datetime.strptime(value, '%m/%d/%Y').date().isoformat()


def money(value):
    cleaned = value.strip().replace('$', '').replace(',', '')
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]
    amount = Decimal(cleaned) * 100
    if not amount.is_finite() or amount != amount.to_integral_value():
        raise ValueError(f'Invalid money: {value!r}')
    return int(amount)


def number(value):
    if not Decimal(value).is_finite():
        raise ValueError(f'Invalid number: {value!r}')
    return value


def import_sales(source, database, replace_sha256=None):
    source = Path(source)
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig'), newline=''))
    expected = ['Date', 'Department', 'UPC', 'Item', '# of Baskets', '# of Items',
                'Avg Items', 'Sales $', 'Avg Sale', 'Scan Rate', 'Scan Sales']
    if reader.fieldnames != expected:
        raise ValueError('Unexpected daily sales headers')
    rows = list(reader)
    if not rows:
        raise ValueError('No sales rows')
    with sqlite3.connect(database) as db:
        db.executescript((ROOT / 'schema.sql').read_text())
        previous = db.execute('SELECT id FROM imports WHERE sha256=?', (digest,)).fetchone()
        if previous:
            if not db.execute('SELECT 1 FROM daily_sales_rows WHERE import_id=? LIMIT 1', previous).fetchone():
                raise ValueError('File already registered under another import type')
            return {'status': 'already_imported', 'rows': len(rows)}
        if replace_sha256:
            previous_import = db.execute('SELECT id FROM imports WHERE sha256=?', (replace_sha256,)).fetchone()
            if not previous_import:
                raise ValueError('Replacement target not found')
            old_rows = [json.loads(r[0]) for r in db.execute(
                'SELECT raw_json FROM daily_sales_rows WHERE import_id=? ORDER BY row_number', previous_import)]
            def without_upc(row):
                return {k: v for k, v in row.items() if k != 'UPC'}
            if not old_rows or list(map(without_upc, old_rows)) != list(map(without_upc, rows)):
                raise ValueError('UPC correction must preserve every other field and row order')
            db.execute('DELETE FROM daily_sales_rows WHERE import_id=?', previous_import)
            db.execute('DELETE FROM imports WHERE id=?', previous_import)
        # Overlapping reports may repeat daily summaries with changed values.
        # Reject instead of silently adding them together; replacements need explicit review.
        incoming_dates = {parse_date(r['Date']) for r in rows}
        existing_dates = {r[0] for r in db.execute('SELECT DISTINCT sale_date FROM daily_sales_rows')}
        overlap = incoming_dates & existing_dates
        if overlap:
            raise ValueError(f'Report overlaps {len(overlap)} previously imported dates; review before importing')
        batch = db.execute('INSERT INTO imports(source_name,sha256,row_count) VALUES (?,?,?)',
                           (source.name, digest, len(rows))).lastrowid
        products = {r[0] for r in db.execute('SELECT upc FROM products')}
        matched = 0
        for line, row in enumerate(rows, 2):
            upc = unwrap(row['UPC'])
            linked = upc if upc in products else None
            matched += linked is not None
            db.execute('INSERT INTO daily_sales_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (batch, line, parse_date(row['Date']), upc, linked, row['Department'], row['Item'],
                 int(row['# of Baskets']), number(row['# of Items']), money(row['Sales $']),
                 money(row['Scan Sales']), number(row['Avg Items']), money(row['Avg Sale']),
                 number(row['Scan Rate']), json.dumps(row, ensure_ascii=False)))
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Foreign key validation failed')
    return {'status': 'imported', 'rows': len(rows), 'matched': matched,
            'unmatched': len(rows)-matched, 'from': min(incoming_dates), 'to': max(incoming_dates)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--database', default=ROOT / 'data/pricebook.sqlite3')
    parser.add_argument('--replace-sha256', help='Explicit checksum of an import to replace; only UPC corrections allowed')
    args = parser.parse_args()
    print(json.dumps(import_sales(args.source, args.database, args.replace_sha256)))
