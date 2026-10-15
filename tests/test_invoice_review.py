import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from invoice_review import (blank_line, extract_document, from_csv, classify_lines,
                            validate_review, save_review)
from import_pricebook import ROOT, import_pricebook
from import_invoices import import_invoices


def make_pdf(table=True):
    """Small actual PDF fixture with a ruled table, without extra test dependencies."""
    commands=[]
    if table:
        xs=[30,260,360,480];ys=[700,670,640]
        for x in xs:commands.append(f'{x} 640 m {x} 700 l S')
        for y in ys:commands.append(f'30 {y} m 480 {y} l S')
        for x,y,text in [(35,680,'Description'),(265,680,'Qty'),(365,680,'Amount'),
                         (35,650,'Example item'),(265,650,'2'),(365,650,'10.00')]:
            commands.append(f'BT /F1 10 Tf {x} {y} Td ({text}) Tj ET')
    content='\n'.join(commands).encode()
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream']
    payload=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(payload));payload+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(payload)
    payload+=b'xref\n0 6\n0000000000 65535 f \n'
    for offset in offsets[1:]:payload+=f'{offset:010d} 00000 n \n'.encode()
    payload+=f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    return payload


class InvoiceReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'test.sqlite3'
        import_pricebook(ROOT/'data/pricebook.csv',self.db)
        self.header=dict(supplier='Review Test Supplier',retailer='Balport Liquor Store',
            customer_id='account',store_id='000001',invoice_number='REVIEW-001',
            invoice_date='2026-10-15',due_date='',invoice_total='10.00')

    def line(self,**overrides):
        return {**blank_line(),'product_number':'ABC-1','description':'ULTRA WATERMELON FOCUS',
            'upc':'200001000003','quantity':'2','unit_cost':'5','extended_price':'10.00',
            'unit_of_measure':'BO','ppc':'1','action':'Link existing product',
            'confirmed_upc':'200001000003','remember_mapping':False,**overrides}

    def test_pdf_table_and_unreadable_document(self):
        result=extract_document(make_pdf(),'example.pdf')
        self.assertEqual(len(result['lines']),1)
        self.assertEqual(result['lines'][0]['description'],'Example item')
        self.assertEqual(result['lines'][0]['quantity'],'2')
        self.assertEqual(result['lines'][0]['extended_price'],'10.00')
        self.assertIn('Example item',result['text'])
        empty=extract_document(make_pdf(False),'scan.pdf')
        self.assertEqual(empty['lines'],[])
        self.assertTrue(any('scanned' in warning for warning in empty['warnings']))
        with self.assertRaises(ValueError):extract_document(b'not a pdf','bad.pdf')

    def test_fintech_csv_extraction_preserves_codes(self):
        source=ROOT/'data/invoices/invoices-report (1).csv'
        result=extract_document(source.read_bytes(),source.name)
        first=result['records'][0]
        selected=[r for r in result['records'] if r['Invoice Number']==first['Invoice Number']]
        header,lines=from_csv(selected)
        self.assertEqual(header['invoice_number'],first['Invoice Number'])
        self.assertEqual(lines[0]['upc'],first['UPC Number'])
        self.assertEqual(header['invoice_date'],'2026-02-27')
        changed=[dict(row) for row in selected]
        changed[-1]['Invoice Total']='999999'
        with self.assertRaisesRegex(ValueError,'Conflicting invoice headers'):
            from_csv(changed)

    def test_matching_and_explicit_pack_scoped_mapping(self):
        before=classify_lines([self.line()],self.header['supplier'],self.db)[0]
        self.assertEqual(before['status'],'Existing item')
        self.assertEqual(before['purchase_history'],'Not seen in imported purchase history')
        result=save_review(b'invoice test','invoice.pdf',self.header,
            [self.line(upc='10000000000001',remember_mapping=True)],database=self.db)
        mapped=classify_lines([self.line(upc='10000000000001')],self.header['supplier'],self.db)[0]
        self.assertEqual(mapped['status'],'Existing item')
        self.assertEqual(mapped['confirmed_upc'],'200001000003')
        self.assertEqual(mapped['purchase_history'],'Seen from this supplier')
        other_pack=classify_lines([self.line(upc='10000000000001',ppc='24')],self.header['supplier'],self.db)[0]
        self.assertNotEqual(other_pack['status'],'Existing item')
        other_vendor=classify_lines([self.line(upc='10000000000001')],'Different supplier',self.db)[0]
        self.assertNotEqual(other_vendor['status'],'Existing item')
        self.assertEqual(other_vendor['purchase_history'],'Seen from another supplier')
        conflicting=classify_lines([self.line(upc='499733700064')],self.header['supplier'],self.db)[0]
        self.assertEqual(conflicting['status'],'Possible match')
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT document FROM invoice_reviews').fetchone()[0],b'invoice test')
            self.assertEqual(con.execute('SELECT matched_upc FROM purchase_lines').fetchone()[0],'200001000003')
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_new_item_and_no_guessed_catalog_entry(self):
        line=self.line(upc='123456789012',description='UNSEEN UNIQUE PRODUCT',
            action='Confirm new item',confirmed_upc='123456789012')
        proposed=classify_lines([line],self.header['supplier'],self.db)[0]
        self.assertEqual(proposed['status'],'Potential new item')
        result=save_review(b'new item','new.pdf',self.header,[line],database=self.db)
        self.assertEqual(result['new_items'],1)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT retail_upc FROM catalog_candidates').fetchone()[0],'123456789012')
            self.assertEqual(con.execute('SELECT count(*) FROM products').fetchone()[0],9775)
            self.assertIsNone(con.execute('SELECT matched_upc FROM purchase_lines').fetchone()[0])
        unreadable=classify_lines([self.line(upc='6.0925E+11',description='UNKNOWN UNUSUAL ITEM')],self.header['supplier'],self.db)[0]
        self.assertEqual(unreadable['status'],'Unreadable code')

    def test_atomic_duplicates_and_validation(self):
        with self.assertRaisesRegex(ValueError,'still needs review'):
            save_review(b'one','one.pdf',self.header,[self.line(action='Review needed')],database=self.db)
        with self.assertRaisesRegex(ValueError,'differ'):
            save_review(b'one','one.pdf',{**self.header,'invoice_total':'11'},[self.line()],database=self.db)
        save_review(b'one','one.pdf',self.header,[self.line()],database=self.db)
        with self.assertRaisesRegex(ValueError,'already saved'):
            save_review(b'one','renamed.pdf',self.header,[self.line()],database=self.db)
        with self.assertRaisesRegex(ValueError,'already in purchases'):
            save_review(b'changed','other.pdf',self.header,[self.line()],database=self.db)
        # A mapping conflict occurs after inserts; all those inserts must roll back.
        second={**self.header,'invoice_number':'REVIEW-002'}
        save_review(b'two','two.pdf',second,[self.line(remember_mapping=True)],database=self.db)
        with self.assertRaisesRegex(ValueError,'mapping conflicts'):
            save_review(b'three','three.pdf',{**self.header,'invoice_number':'REVIEW-003'},
                [self.line(confirmed_upc='499733700064',remember_mapping=True)],database=self.db)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM purchase_invoices').fetchone()[0],2)
            self.assertEqual(con.execute('SELECT count(*) FROM invoice_reviews').fetchone()[0],2)
            self.assertEqual(con.execute('SELECT count(*) FROM imports').fetchone()[0],3)

    def test_existing_fintech_invoice_cannot_be_reimported_from_pdf(self):
        source=ROOT/'data/invoices/invoices-report (1).csv'
        import_invoices(source,self.db)
        parsed=extract_document(source.read_bytes(),source.name)
        first=parsed['records'][0]
        records=[r for r in parsed['records'] if r['Invoice Number']==first['Invoice Number']]
        header,lines=from_csv(records)
        decisions=[{**line,'action':'Keep unlinked','confirmed_upc':''} for line in lines]
        with self.assertRaisesRegex(ValueError,'already in purchases'):
            save_review(b'pdf duplicate','duplicate.pdf',header,decisions,True,self.db)

    def test_credits_and_subcent_precision(self):
        line=self.line(quantity='-2',unit_cost='5.0004',extended_price='-10.0008',
            action='Keep unlinked',confirmed_upc='')
        result=save_review(b'credit','credit.pdf',{**self.header,'invoice_total':'-10.00'},
            [line],True,self.db)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT total_cents FROM purchase_invoices').fetchone()[0],-1000)
            self.assertEqual(con.execute('SELECT extended_price,unit_cost FROM purchase_lines').fetchone(),('-10.0008','5.0004'))

    def test_two_invoices_in_same_csv_and_document_audit(self):
        source=b'csv with multiple invoices'
        save_review(source,'multiple.csv',self.header,[self.line()],database=self.db)
        save_review(source,'multiple.csv',{**self.header,'invoice_number':'SECOND'},[self.line()],database=self.db)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM invoice_reviews').fetchone()[0],2)
            self.assertEqual(con.execute('SELECT count(DISTINCT document_sha256) FROM invoice_reviews').fetchone()[0],1)
        with self.assertRaises(ValueError):
            save_review(source,'multiple.csv',self.header,[self.line()],database=self.db)

    def test_review_page_upload_preview_and_save(self):
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        import invoice_review_ui
        from import_invoices import HEADERS
        record=dict.fromkeys(HEADERS,'')
        record.update({'Vendor Name':self.header['supplier'],'Retailer Name':self.header['retailer'],
            'Customer ID':'account','Store ID':'000001','Invoice Number':'UI-TEST',
            'Invoice Date':'10/15/2026 00:00:00','Invoice Total':'10.00','Item Count':'1',
            'Product Number':'UI-1','UPC Number':'200001000003','Product Description':'ULTRA WATERMELON FOCUS',
            'Quantity':'2','Unit Cost':'5','Unit of Measure':'BO','PPC':'1',
            'Total Adjustments':'0','Total Discount':'0','Extended Price':'10.00'})
        stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=HEADERS)
        writer.writeheader();writer.writerow(record)
        payload=stream.getvalue().encode()
        class Uploaded:
            name='ui-invoice.csv'
            def getvalue(self):return payload
        def button(app,label):return next(b for b in app.button if b.label==label)
        with patch.object(invoice_review_ui,'DATABASE',self.db),patch('streamlit.file_uploader',return_value=Uploaded()):
            app=AppTest.from_file(str(ROOT/'dashboard.py'),default_timeout=30).run()
            app.sidebar.radio[0].set_value('New Items Review').run()
            self.assertEqual(len(app.exception),0)
            button(app,'Check for new items').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(app.metric[0].value,'1')
            self.assertTrue(button(app,'Save reviewed invoice').disabled)
            next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
            button(app,'Save reviewed invoice').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertTrue(any('Saved invoice' in s.value for s in app.success))
            with sqlite3.connect(self.db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM purchase_invoices').fetchone()[0],1)
                self.assertEqual(con.execute('SELECT document FROM invoice_reviews').fetchone()[0],payload)
