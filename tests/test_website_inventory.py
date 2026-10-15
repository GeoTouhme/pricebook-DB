from pathlib import Path
import sqlite3
import tempfile
import unittest
from import_pricebook import ROOT, import_pricebook
from import_website_inventory import import_inventory

class WebsiteTests(unittest.TestCase):
    def test_import_preserves_and_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'test.sqlite3'
            import_pricebook(ROOT / 'data/pricebook.csv', db)
            source = ROOT / 'data/website-inventory_2026-10-13.csv'
            result = import_inventory(source, db, '2026-10-13')
            self.assertEqual(result, dict(status='imported', rows=8746, matched=8727, unmatched=19))
            self.assertEqual(import_inventory(source, db, '2026-10-13')['status'], 'already_imported')
            with self.assertRaises(ValueError):
                import_inventory(source, db, '2026-10-14')
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM inventory_snapshots').fetchone()[0], 8727)
                self.assertEqual(con.execute('SELECT count(*) FROM products').fetchone()[0], 9775)
                self.assertEqual(con.execute('SELECT count(*) FROM website_inventory_rows WHERE matched_upc IS NULL').fetchone()[0], 19)
                self.assertEqual(con.execute("SELECT quantity FROM inventory_snapshots WHERE upc='200001000003'").fetchone()[0], '100')
                self.assertEqual(con.execute("SELECT pricebook_stock FROM products WHERE upc='200001000003'").fetchone()[0], '84')
                self.assertEqual(con.execute('SELECT count(*) FROM website_inventory_rows WHERE price_cents IS NULL').fetchone()[0], 8745)
                self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
