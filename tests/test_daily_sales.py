import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from import_pricebook import ROOT, import_pricebook
from import_daily_sales import import_sales

class DailySalesTests(unittest.TestCase):
    def test_import_and_overlap_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'test.sqlite3'
            import_pricebook(ROOT / 'data/pricebook.csv', db)
            source = ROOT / 'data/itemsales_by_day.csv'
            result = import_sales(source, db)
            self.assertEqual(result['rows'], 78592)
            self.assertEqual(result['matched'], 77007)
            self.assertEqual(import_sales(source, db)['status'], 'already_imported')
            altered = Path(directory) / 'overlap.csv'
            altered.write_bytes(source.read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                import_sales(altered, db)
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT count(*),sum(sales_cents),sum(scan_sales_cents) FROM daily_sales_rows').fetchone(), (78592,124228353,113273925))
                self.assertEqual(con.execute('SELECT count(DISTINCT sale_date) FROM daily_sales_rows').fetchone()[0],104)
                self.assertEqual(con.execute("SELECT count(*) FROM daily_sales_rows WHERE source_upc=''").fetchone()[0],527)
                self.assertEqual(con.execute('SELECT count(*) FROM sales_lines').fetchone()[0],0)
                self.assertEqual(con.execute('SELECT count(*) FROM imports').fetchone()[0],2)
                self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
                with source.open(encoding='utf-8-sig',newline='') as f:
                    originals = list(csv.DictReader(f))
                restored = [json.loads(r[0]) for r in con.execute('SELECT raw_json FROM daily_sales_rows ORDER BY row_number')]
                self.assertEqual(originals, restored)

    def test_september_october_export_formats(self):
        from decimal import Decimal
        from import_daily_sales import money, parse_date
        self.assertEqual(money('($542.66)'), -54266)
        self.assertEqual(parse_date('9/1/2026'), '2026-09-01')
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'test.sqlite3'
            import_pricebook(ROOT / 'data/pricebook.csv', db)
            source = ROOT / 'data/itemsales_by_day 9-10.csv'
            result = import_sales(source, db)
            self.assertEqual(result, dict(status='imported', rows=31234, matched=52,
                unmatched=31182, **{'from':'2026-09-01','to':'2026-10-15'}))
            self.assertEqual(import_sales(source, db)['status'], 'already_imported')
            with source.open(encoding='utf-8-sig',newline='') as f:
                originals = list(csv.DictReader(f))
            def source_cents(value):
                return int(Decimal(value.strip().replace('$','').replace(',','').replace('(','-').replace(')',''))*100)
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT min(sale_date),max(sale_date),count(DISTINCT sale_date) FROM daily_sales_rows').fetchone(), ('2026-09-01','2026-10-15',45))
                self.assertEqual(con.execute('SELECT sum(sales_cents),sum(scan_sales_cents) FROM daily_sales_rows').fetchone(),
                    tuple(sum(source_cents(r[k]) for r in originals) for k in ['Sales $','Scan Sales']))
                restored=[json.loads(r[0]) for r in con.execute('SELECT raw_json FROM daily_sales_rows ORDER BY row_number')]
                self.assertEqual(originals, restored)
                self.assertEqual(con.execute("SELECT count(*) FROM daily_sales_rows WHERE lower(source_upc) LIKE '%e%' AND matched_upc IS NOT NULL").fetchone()[0],0)
                self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_upc_correction_replaces_without_double_counting(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'test.sqlite3'
            import_pricebook(ROOT / 'data/pricebook.csv', db)
            old = ROOT / 'data/itemsales_by_day 9-10.csv'
            new = ROOT / 'data/itemsales_by_day 9-10 corrected.csv'
            checksum = hashlib.sha256(old.read_bytes()).hexdigest()
            import_sales(old, db)
            with sqlite3.connect(db) as con:
                before = con.execute('SELECT count(*),sum(sales_cents),sum(scan_sales_cents) FROM daily_sales_rows').fetchone()
            with new.open(encoding='utf-8-sig',newline='') as f:
                reader=csv.DictReader(f); rows=list(reader); fields=reader.fieldnames
            rows[0]['Sales $']='$999.00'
            bad=Path(directory)/'changed.csv'
            with bad.open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            with self.assertRaisesRegex(ValueError,'preserve every other field'):
                import_sales(bad,db,checksum)
            result=import_sales(new,db,checksum)
            self.assertEqual(result['matched'],16311)
            self.assertEqual(result['unmatched'],14923)
            self.assertEqual(import_sales(new,db)['status'],'already_imported')
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT count(*),sum(sales_cents),sum(scan_sales_cents) FROM daily_sales_rows').fetchone(),before)
                self.assertEqual(con.execute('SELECT count(*) FROM imports').fetchone()[0],2)
                self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[])
