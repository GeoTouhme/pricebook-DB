import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from import_pricebook import ROOT, import_pricebook

class ImportTests(unittest.TestCase):
    def test_full_import_and_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'test.sqlite3'
            self.assertEqual(import_pricebook(ROOT / 'data/pricebook.csv', db)['rows'], 9775)
            self.assertEqual(import_pricebook(ROOT / 'data/pricebook.csv', db)['status'], 'already_imported')
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM products').fetchone()[0], 9775)
                self.assertEqual(con.execute('SELECT count(*) FROM departments').fetchone()[0], 91)
                self.assertEqual(con.execute('SELECT count(*) FROM imports').fetchone()[0], 1)
                self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
                with (ROOT / 'data/pricebook.csv').open(encoding='utf-8-sig', newline='') as f:
                    source = list(csv.DictReader(f))
                restored = [json.loads(r[0]) for r in con.execute('SELECT raw_json FROM pricebook_rows ORDER BY row_number')]
                self.assertEqual(source, restored)
                self.assertEqual(con.execute("SELECT price_cents,pricebook_stock FROM products WHERE upc='200001000003'").fetchone(), (1499,'84'))
                self.assertEqual(con.execute('SELECT count(*) FROM sales_lines').fetchone()[0], 0)

    def test_duplicate_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'duplicate.csv'
            with (ROOT / 'data/pricebook.csv').open(encoding='utf-8-sig', newline='') as f:
                reader = csv.reader(f)
                header, row = next(reader), next(reader)
            with source.open('w', newline='') as f:
                writer = csv.writer(f)
                writer.writerows([header, row, row])
            db = Path(directory) / 'test.sqlite3'
            with self.assertRaises(ValueError):
                import_pricebook(source, db)
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM products').fetchone()[0], 0)
                self.assertEqual(con.execute('SELECT count(*) FROM imports').fetchone()[0], 0)

if __name__ == '__main__':
    unittest.main()
