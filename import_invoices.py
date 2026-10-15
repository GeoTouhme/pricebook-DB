"""Import Fintech invoice lines; preserve source precision and deduplicate invoices."""
import argparse
from collections import defaultdict
import csv
from datetime import datetime
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from import_pricebook import ROOT
from purchase_matching import pack_upc_or_blank

HEADERS = ['Vendor Name', 'Retailer Name', 'Retailer Vendor ID', 'Customer ID',
 'Store ID', 'Retailer Relationship ID', 'Process Date', 'Invoice Date',
 'Invoice Due Date', 'Invoice Number', 'Invoice Total', 'Item Count', 'PO Number',
 'PO Date', 'Reference Invoice Number', 'Product Number', 'Quantity', 'Unit Cost',
 'Unit of Measure', 'UPC Number', 'Product Description', 'Total Adjustments',
 'Total Discount', 'Extended Price', 'PPC', 'Pack UPC', 'GL Code']

def numeric(value):
    if not Decimal(value).is_finite():
        raise ValueError(f'Invalid numeric value {value!r}')
    return value

def cents(value):
    amount = Decimal(numeric(value)) * 100
    if amount != amount.to_integral_value():
        raise ValueError(f'Non-cent monetary total {value!r}')
    return int(amount)

def iso(value):
    return datetime.strptime(value, '%m/%d/%Y %H:%M:%S').date().isoformat() if value else None

def import_invoices(source, database):
    source = Path(source)
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig'), newline=''))
    if reader.fieldnames != HEADERS:
        raise ValueError('Unexpected invoice headers')
    rows = list(reader)
    if not rows:
        raise ValueError('No invoice rows')
    groups = defaultdict(list)
    for line, row in enumerate(rows, 2):
        key = (row['Vendor Name'], row['Retailer Name'], row['Customer ID'], row['Store ID'],
               row['Invoice Number'], iso(row['Invoice Date']))
        if not key[0] or not key[4] or not key[5]:
            raise ValueError(f'Missing invoice identity at row {line}')
        groups[key].append((line, row))
    with sqlite3.connect(database) as db:
        db.executescript((ROOT/'schema.sql').read_text())
        old = db.execute('SELECT id FROM imports WHERE sha256=?', (digest,)).fetchone()
        if old:
            if not db.execute('SELECT 1 FROM purchase_source_rows WHERE import_id=? LIMIT 1', old).fetchone():
                raise ValueError('File registered as another import type')
            return {'status':'already_imported', 'rows':len(rows)}
        batch = db.execute('INSERT INTO imports(source_name,sha256,row_count) VALUES (?,?,?)',
                           (source.name,digest,len(rows))).lastrowid
        products = {r[0] for r in db.execute('SELECT upc FROM products')}
        added = 0
        for key, entries in groups.items():
            header = entries[0][1]
            for _, row in entries:
                for field in ['Invoice Total','Item Count','Invoice Due Date']:
                    if row[field] != header[field]:
                        raise ValueError(f'Conflicting invoice header: {key}')
            # Keep duplicate identical lines within an invoice; fingerprints cover the entire list.
            canonical = sorted(json.dumps(r,sort_keys=True,ensure_ascii=False) for _,r in entries)
            fingerprint = hashlib.sha256(json.dumps(canonical).encode()).hexdigest()
            db.execute('INSERT OR IGNORE INTO suppliers(name) VALUES (?)',(key[0],))
            supplier = db.execute('SELECT id FROM suppliers WHERE name=?',(key[0],)).fetchone()[0]
            identity = (supplier,*key[1:])
            existing = db.execute('''SELECT id,content_sha256 FROM purchase_invoices
                WHERE supplier_id=? AND retailer_name=? AND customer_id=? AND store_id=?
                AND invoice_number=? AND invoice_date=?''',identity).fetchone()
            if existing:
                if existing[1] != fingerprint:
                    raise ValueError(f'Changed or partial invoice needs review: {key}')
                invoice = existing[0]
                # Same full invoice can occur in another export in a different order.
                line_lookup = defaultdict(list)
                for raw, lid in db.execute('''SELECT r.raw_json,r.line_id FROM purchase_source_rows r
                    WHERE r.invoice_id=? AND r.import_id=(SELECT min(import_id)
                    FROM purchase_source_rows WHERE invoice_id=?) ORDER BY r.row_number''',(invoice,invoice)):
                    line_lookup[json.dumps(json.loads(raw),sort_keys=True,ensure_ascii=False)].append(lid)
            else:
                added += 1
                invoice = db.execute('''INSERT INTO purchase_invoices
                    (supplier_id,retailer_name,customer_id,store_id,invoice_number,invoice_date,
                    due_date,total_cents,item_count,content_sha256) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (*identity,iso(header['Invoice Due Date']),cents(header['Invoice Total']),
                     int(header['Item Count']),fingerprint)).lastrowid
            for number,(source_line,row) in enumerate(entries,1):
                if existing:
                    lid = line_lookup[json.dumps(row,sort_keys=True,ensure_ascii=False)].pop()
                else:
                    lid = db.execute('''INSERT INTO purchase_lines
                        (invoice_id,line_number,product_number,source_upc,pack_upc,matched_upc,
                        description,quantity,unit_cost,unit_of_measure,ppc,adjustments_cents,
                        discount_cents,extended_price,gl_code)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (invoice,number,row['Product Number'],row['UPC Number'],row['Pack UPC'],
                         pack_upc_or_blank(row['Pack UPC']) if pack_upc_or_blank(row['Pack UPC']) in products else None,
                         row['Product Description'],numeric(row['Quantity']),numeric(row['Unit Cost']),
                         row['Unit of Measure'],row['PPC'],cents(row['Total Adjustments']),
                         cents(row['Total Discount']),numeric(row['Extended Price']),row['GL Code'])).lastrowid
                db.execute('INSERT INTO purchase_source_rows VALUES (?,?,?,?,?)',
                           (batch,source_line,invoice,lid,json.dumps(row,ensure_ascii=False)))
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Foreign key validation failed')
    return {'status':'imported','source_rows':len(rows),'new_invoices':added}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources',nargs='+',type=Path)
    parser.add_argument('--database',default=ROOT/'data/pricebook.sqlite3')
    args=parser.parse_args()
    for source in args.sources:
        print(source.name, json.dumps(import_invoices(source,args.database)))
