"""Synthetic actual PDFs; private source invoices are optional local checks."""
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from invoice_review import extract_document, classify_lines, validate_review, save_review
from import_pricebook import import_pricebook, ROOT
from breakthru_pdf import SUPPLIER


def fixture(number='900000001', mixed=False, invalid=False, supplier=True):
    commands = []
    def text(x, top, value, size=8):
        value = value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        commands.append(f'BT /F1 {size} Tf {x} {792-top-size} Td ({value}) Tj ET')
    def line(x0, top0, x1, top1):
        commands.append(f'{x0} {792-top0} m {x1} {792-top1} l S')
    text(20,20,'Breakthru Beverage California' if supplier else 'Other supplier')
    text(320,40,f'Invoice #: {number}')
    text(320,55,'Invoice Date: 10/16/2026')
    text(320,70,'Customer #: 123456789')
    text(320,85,'Due Date: 11/15/2026')
    text(20,90,'BALPORT LIQUOR')
    text(20,740,'BBCA XML Final Invoice')
    edges=[15,34,51,77,111,137,153,408,445,475,504,537,585,600]
    labels=['Case','Btles','Pieces','Item','Size','BPC','Description','Price','Disc','Price','Btl','Sales','Deal']
    for x in edges: line(x,195,x,500)
    for y in [195,212,258,304,350,500]:line(15,y,600,y)
    for left,label in zip(edges,labels):text(left+1,200,label,5)
    rows=[['1','2' if mixed else '', '6','1234567','750ML','6','Example product','30.00','3.00','27.00','4.50','27.00','*'],
          ['', '4','4','7654321','1L','6','Loose bottles','5.00','0.00','5.00','5.00','20.00',''],
          ['', '', '0','2222222','1L','6','Not shipped','','','','','0.00','']]
    for top,row in zip([216,262,308],rows):
        for left,value in zip(edges,row):
            if value:text(left+1,top,value,7)
    # UPC-A outer digits and central ten use different baselines; preserve leading zero.
    for top,code in [(216,'070897013315' if not invalid else '070897013310'),(262,'070655001929')]:
        text(325,top+10,code[0],8);text(345,top+22,code[1:-1],8);text(401,top+10,code[-1],8)
    text(154,230,'Wrapped size reference',7)
    text(335,323,'Out of Stock',7)
    # Separate summary table, including CRV and sweetener amount.
    footer_edges=[15,77,137,200,270,330,400,470,537,600]
    for x in footer_edges:line(x,520,x,560)
    for y in [520,540,560]:line(15,y,600,y)
    for left,label in zip(footer_edges,['Cases Shipped','Bottles Shipped','Pieces Shipped','Spirits','Wine','Beer','CRV Tax','Sweetner Tax','']):text(left+1,523,label,5)
    for left,value in zip(footer_edges,['1','4','10','','','','0.50','0','']):
        if value:text(left+1,544,value,7)
    text(540,526,'47.50',8)
    stream='\n'.join(commands).encode()
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    payload=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(payload));payload+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(payload);payload+=b'xref\n0 6\n0000000000 65535 f \n'
    for offset in offsets[1:]:payload+=f'{offset:010d} 00000 n \n'.encode()
    return payload+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()


class BreakthruTests(unittest.TestCase):
    def test_actual_pdf_units_barcodes_and_invoice_charges(self):
        result=extract_document(fixture(),'invoice.pdf')
        self.assertEqual(result['header']['invoice_total'],'47.50')
        self.assertEqual(result['header']['invoice_date'],'2026-10-16')
        self.assertEqual(result['header']['due_date'],'2026-11-15')
        self.assertEqual(result['header']['supplier'],SUPPLIER)
        self.assertEqual(len(result['lines']),2)
        case,bottle=result['lines']
        self.assertEqual((case['quantity'],case['unit_of_measure'],case['ppc']),('1','CA','6'))
        self.assertEqual((case['unit_cost'],case['discount'],case['extended_price']),('30.00','-3.00','27.00'))
        self.assertEqual(case['description'],'Example product Wrapped size reference')
        self.assertEqual(case['pack_upc'],'070897013315')
        self.assertEqual((bottle['quantity'],bottle['unit_of_measure']),('4','BO'))
        self.assertEqual(bottle['pack_upc'],'070655001929')
        self.assertEqual(result['header']['source_info']['invoice_charges'],{'crv_tax':'0.50','sweetener_tax':'0'})
        self.assertEqual(result['header']['source_info']['excluded_lines'][0]['product_number'],'2222222')
        self.assertTrue(all(line['case_upc']=='' for line in result['lines']))

    def test_bad_barcode_is_not_repaired_or_auto_linked(self):
        result=extract_document(fixture(invalid=True),'invoice.pdf')
        self.assertEqual(result['lines'][0]['pack_upc'],'')
        self.assertEqual(result['lines'][0]['upc'],'')
        self.assertEqual(result['header']['source_info']['barcode_details'][0]['barcode_raw'],'070897013310')
        self.assertTrue(any('check digit' in w for w in result['warnings']))

    def test_mixed_case_bottle_row_requires_manual_units(self):
        result=extract_document(fixture(mixed=True),'invoice.pdf')
        self.assertEqual(result['lines'][0]['quantity'],'')
        self.assertEqual(result['lines'][0]['unit_of_measure'],'')
        with self.assertRaises(ValueError):
            validate_review({**result['header'],'store_id':'test'},result['lines'])

    def test_save_and_padded_export_duplicate_are_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'test.sqlite3';import_pricebook(ROOT/'data/pricebook.csv',db)
            payload=fixture();result=extract_document(payload,'invoice.pdf')
            header={**result['header'],'store_id':'test'}
            decisions=[dict(line,action='Keep unlinked',remember_mapping=False) for line in result['lines']]
            with self.assertRaisesRegex(ValueError,'totals differ'):
                save_review(payload,'invoice.pdf',header,decisions,database=db)
            saved=save_review(payload,'invoice.pdf',header,decisions,database=db,acknowledge_difference=True)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute('SELECT total_cents,item_count FROM purchase_invoices').fetchone(),(4750,2))
                self.assertEqual(conn.execute('SELECT count(*) FROM products').fetchone()[0],9775)
                # Simulate Fintech's padded identifiers and retailer label.
                conn.execute("UPDATE purchase_invoices SET invoice_number='0900000001',customer_id='0123456789',retailer_name='Export retailer',store_id='000001'")
            with self.assertRaisesRegex(ValueError,'supplier account'):
                save_review(payload+b'\n','copy.pdf',header,decisions,database=db,acknowledge_difference=True)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM purchase_invoices').fetchone()[0],1)

    def test_upload_review_defaults_and_charge_difference(self):
        from unittest.mock import patch
        from auth_helpers import logged_in_app
        import invoice_review_ui
        payload=fixture()
        class Uploaded:
            name='breakthru.pdf'
            def getvalue(self):return payload
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'test.sqlite3';import_pricebook(ROOT/'data/pricebook.csv',db)
            with patch.object(invoice_review_ui,'DATABASE',db),patch('streamlit.file_uploader',return_value=Uploaded()):
                app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
                app.sidebar.radio[0].set_value('New Items Review').run()
                self.assertFalse(app.exception)
                fields={w.label:w.value for w in app.text_input}
                self.assertEqual(fields['Invoice total (credits negative)'],'47.50')
                self.assertEqual(fields['Invoice date (YYYY-MM-DD)'],'2026-10-16')
                self.assertTrue(any('Invoice-level CRV: $0.50' in c.value for c in app.caption))
                next(b for b in app.button if b.label=='Check for new items').click().run()
                self.assertFalse(app.exception)
                self.assertTrue(any('Invoice total minus line totals: 0.50' in w.value for w in app.warning))
                self.assertTrue(next(b for b in app.button if b.label=='Save reviewed invoice').disabled)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM purchase_invoices').fetchone()[0],0)

    @unittest.skipUnless(os.environ.get('BREAKTHRU_PDF_DIRECTORY'),'Private source invoices not configured')
    def test_private_original_invoices(self):
        folder=Path(os.environ['BREAKTHRU_PDF_DIRECTORY'])
        cases=[('Invoice-0129359703.pdf',10,'2238.19','11.50',9),('Invoice-0129249702.pdf',7,'633.12','8.40',7)]
        for filename,count,total,crv,upcs in cases:
            with self.subTest(filename=filename):
                result=extract_document((folder/filename).read_bytes(),filename)
                self.assertEqual(len(result['lines']),count)
                self.assertEqual(result['header']['invoice_total'],total)
                info=result['header']['source_info']
                self.assertEqual(info['invoice_charges']['crv_tax'],crv)
                self.assertEqual(len(info['excluded_lines']),1)
                self.assertEqual(sum(bool(r['pack_upc']) for r in result['lines']),upcs)
                self.assertTrue(all(len(r['pack_upc'])==12 for r in result['lines'] if r['pack_upc']))
                self.assertEqual(sum(Decimal(r['extended_price']) for r in result['lines'])+Decimal(crv),Decimal(total))
                self.assertTrue(all(info['barcode_details'][i]['barcode_raw'] not in r['description'] for i,r in enumerate(result['lines']) if info['barcode_details'][i]['barcode_raw']))
