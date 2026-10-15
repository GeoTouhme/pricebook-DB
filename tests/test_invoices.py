import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from import_pricebook import ROOT, import_pricebook
from import_invoices import import_invoices

class InvoiceTests(unittest.TestCase):
    def test_all_files_deduplication_precision_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/'test.sqlite3'
            import_pricebook(ROOT/'data/pricebook.csv',db)
            sources=sorted((ROOT/'data/invoices').glob('*.csv'))
            results=[import_invoices(p,db) for p in sources]
            self.assertEqual(sum(r['status']=='already_imported' for r in results),1)
            for source in sources:
                self.assertEqual(import_invoices(source,db)['status'],'already_imported')
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM suppliers').fetchone()[0],21)
                self.assertEqual(con.execute('SELECT count(*),sum(total_cents),sum(total_cents<0) FROM purchase_invoices').fetchone(),(447,67664269,65))
                self.assertEqual(con.execute('SELECT count(*),sum(matched_upc IS NOT NULL) FROM purchase_lines').fetchone(),(8267,7270))
                self.assertEqual(con.execute('SELECT count(*) FROM purchase_lines WHERE extended_price=?',('-65.716',)).fetchone()[0],1)
                for name,iid in con.execute('SELECT source_name,id FROM imports WHERE id IN (SELECT import_id FROM purchase_source_rows)'):
                    with (ROOT/'data/invoices'/name).open(encoding='utf-8-sig',newline='') as f:
                        original=list(csv.DictReader(f))
                    restored=[json.loads(r[0]) for r in con.execute('SELECT raw_json FROM purchase_source_rows WHERE import_id=? ORDER BY row_number',(iid,))]
                    self.assertEqual(original,restored)
                self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[])
            source=sources[0]
            with source.open(encoding='utf-8-sig',newline='') as f:
                reader=csv.DictReader(f);rows=list(reader);fields=reader.fieldnames
            rows[0]['Quantity']='999'
            conflict=Path(directory)/'conflict.csv'
            with conflict.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
            with self.assertRaisesRegex(ValueError,'Changed or partial invoice'):
                import_invoices(conflict,db)
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM imports').fetchone()[0],10)
                self.assertEqual(con.execute('SELECT count(*) FROM purchase_lines').fetchone()[0],8267)
