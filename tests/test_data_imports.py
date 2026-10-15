import csv
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest

from data_imports import preview_import, save_import
from import_pricebook import ROOT, import_pricebook


def csv_bytes(rows, fields):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode('utf-8-sig')


class UploadTests(unittest.TestCase):
    def test_pricebook_preview_save_backup_and_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'db.sqlite3'
            import_pricebook(ROOT / 'data/pricebook.csv', db)
            with (ROOT / 'data/pricebook.csv').open(encoding='utf-8-sig') as source:
                reader = csv.DictReader(source)
                fields, row = reader.fieldnames, next(reader)
            row['cents'] = str(int(row['cents']) + 100)
            payload = csv_bytes([row], fields)
            before = db.read_bytes()
            preview = preview_import(payload, 'update.csv', 'pricebook', db)
            self.assertEqual(preview['updated_products'], 1)
            self.assertEqual(preview['new_products'], 0)
            self.assertEqual(db.read_bytes(), before)
            saved = save_import(payload, 'update.csv', 'pricebook', db)
            with sqlite3.connect(saved['backup']) as backup_db, sqlite3.connect(db) as updated_db:
                self.assertEqual(updated_db.execute('SELECT sum(price_cents) FROM products').fetchone()[0] - backup_db.execute('SELECT sum(price_cents) FROM products').fetchone()[0], 100)
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM products').fetchone()[0], 9775)
            self.assertEqual(save_import(payload, 'repeat.csv', 'pricebook', db)['status'], 'already_imported')
            bad = csv_bytes([row, row], fields)
            before = db.read_bytes()
            with self.assertRaises(ValueError):
                save_import(bad, 'bad.csv', 'pricebook', db)
            self.assertEqual(db.read_bytes(), before)

    def test_website_history_and_conflicting_date(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'db.sqlite3'
            import_pricebook(ROOT / 'data/pricebook.csv', db)
            with (ROOT / 'data/website-inventory_2026-10-13.csv').open(encoding='utf-8-sig') as source:
                reader = csv.DictReader(source)
                fields, row = reader.fieldnames, next(reader)
            first = csv_bytes([row], fields)
            save_import(first, 'web.csv', 'website', db, '2026-10-13')
            row['Stock'] = '42'
            second = csv_bytes([row], fields)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                save_import(second, 'web.csv', 'website', db, '2026-10-13')
            self.assertEqual(preview_import(second, 'web.csv', 'website', db, '2026-10-14')['rows'], 1)
            save_import(second, 'web.csv', 'website', db, '2026-10-14')
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT snapshot_date,stock FROM website_inventory_rows ORDER BY snapshot_date').fetchall(), [('2026-10-13', '100'), ('2026-10-14', '42')])
                self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
