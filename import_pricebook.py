"""Import a price book using only the Python standard library."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent

def unwrap(value):
    return value[2:-1] if value.startswith('="') and value.endswith('"') else value

def flag(value):
    return {'y': 1, 'n': 0, '': None}[value]

def import_pricebook(source, database):
    source, database = Path(source), Path(database)
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    rows = list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig'), newline='')))
    if not rows:
        raise ValueError('Price book contains no products')
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as db:
        db.executescript((ROOT / 'schema.sql').read_text())
        previous = db.execute('SELECT row_count FROM imports WHERE sha256=?', (digest,)).fetchone()
        if previous:
            return {'status': 'already_imported', 'rows': previous[0]}
        batch = db.execute('INSERT INTO imports(source_name,sha256,row_count) VALUES (?,?,?)',
                           (source.name, digest, len(rows))).lastrowid
        seen = set()
        for number, row in enumerate(rows, 2):
            upc = unwrap(row['Upc'])
            if not upc or upc in seen:
                raise ValueError(f'Empty or duplicate UPC at CSV row {number}')
            seen.add(upc)
            db.execute('INSERT OR IGNORE INTO departments(name) VALUES (?)', (row['Department'],))
            department = db.execute('SELECT id FROM departments WHERE name=?', (row['Department'],)).fetchone()[0]
            values = (upc, department, row['Name'], row['size'] or None, int(row['qty']),
                      int(row['cents']), int(row['cost_qty']), int(row['cost_cents']),
                      flag(row['incltaxes']), flag(row['inclfees']), flag(row['ebt']),
                      flag(row['byweight']), flag(row['variable_price']), row['Fee Multiplier'],
                      unwrap(row['setstock']), batch)
            db.execute('''INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(upc) DO UPDATE SET department_id=excluded.department_id,
                name=excluded.name,size=excluded.size,price_qty=excluded.price_qty,
                price_cents=excluded.price_cents,cost_qty=excluded.cost_qty,
                cost_cents=excluded.cost_cents,includes_taxes=excluded.includes_taxes,
                includes_fees=excluded.includes_fees,ebt=excluded.ebt,by_weight=excluded.by_weight,
                variable_price=excluded.variable_price,fee_multiplier=excluded.fee_multiplier,
                pricebook_stock=excluded.pricebook_stock,import_id=excluded.import_id''', values)
            db.execute('INSERT INTO pricebook_rows VALUES (?,?,?,?)',
                       (batch, number, upc, json.dumps(row, ensure_ascii=False)))
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Foreign key validation failed')
    return {'status': 'imported', 'rows': len(rows)}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', default=ROOT / 'data/pricebook.csv')
    parser.add_argument('--database', default=ROOT / 'data/pricebook.sqlite3')
    args = parser.parse_args()
    print(json.dumps(import_pricebook(args.source, args.database)))
