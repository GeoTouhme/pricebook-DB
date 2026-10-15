"""PACK UPC rules for invoice matching; preserve raw source values."""
import argparse
import json
from pathlib import Path
import re
import sqlite3


def normalize_pack_upc(value):
    text=str(value or '').strip()
    if text.startswith('="') and text.endswith('"'):text=text[2:-1]
    if not text:return ''
    if not re.fullmatch(r'[0-9]+',text):
        raise ValueError('PACK UPC must contain digits only; scientific notation is not accepted')
    if len(text)>12:
        if any(d!='0' for d in text[:-12]):
            raise ValueError('PACK UPC exceeds 12 digits with a nonzero prefix; check the source')
        text=text[-12:]
    return text.zfill(12)


def pack_upc_or_blank(value):
    try:return normalize_pack_upc(value)
    except ValueError:return ''


def refresh_purchase_pack_links(database):
    """Refresh only original CSV auto-links, leaving explicitly reviewed invoices alone."""
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        products={r[0] for r in db.execute('SELECT upc FROM products')}
        lines=db.execute('''SELECT l.id,l.pack_upc,l.matched_upc,min(r.raw_json)
            FROM purchase_lines l JOIN purchase_source_rows r ON r.line_id=l.id GROUP BY l.id''').fetchall()
        changed=0
        for lid,raw_pack,old,raw_json in lines:
            if 'Pack UPC' not in json.loads(raw_json):continue
            upc=pack_upc_or_blank(raw_pack)
            match=upc if upc in products else None
            if match!=old:
                db.execute('UPDATE purchase_lines SET matched_upc=? WHERE id=?',(match,lid));changed+=1
        return {'updated_links':changed,'matched_lines':db.execute(
            'SELECT count(*) FROM purchase_lines WHERE matched_upc IS NOT NULL').fetchone()[0]}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=Path(__file__).resolve().parent/'data/pricebook.sqlite3')
    args=parser.parse_args()
    print(json.dumps(refresh_purchase_pack_links(args.database)))
