"""Synthetic multipage PDFs and optional private Southern Glazer's originals."""
from decimal import Decimal
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from invoice_review import extract_document, validate_review, save_review
from import_pricebook import import_pricebook, ROOT
from southern_glazers_pdf import SUPPLIER


def fixture(sequence=(1,2), invalid=False, mixed=False, other_number=False):
    pages=[]
    for page_number in (1,2):
        commands=[]
        def text(x,top,value,size=8):
            value=value.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            commands.append(f'BT /F1 {size} Tf {x} {792-top-size} Td ({value}) Tj ET')
        def line(x0,y0,x1,y1):commands.append(f'{x0} {792-y0} m {x1} {792-y1} l S')
        def table(xs,top,labels,values):
            for x in xs:line(x,top,x,top+32)
            for y in (top,top+16,top+32):line(xs[0],y,xs[-1],y)
            for x,label,value in zip(xs,labels,values):
                text(x+2,top+3,label,5);text(x+2,top+19,value,7)
        def item(top,description,sku,case_qty,bottle_qty,price,discount,net,amount,upc,crv='0',crv_total='0',notes=''):
            for x,v in [(56,case_qty),(100,bottle_qty),(138,description),(355,price),(400,discount),(440,net),(490,'0.00'),(535,amount)]:
                if v:text(x,top,v,7)
            text(138,top+11.25,f'ITEM#: {sku}  BPC: 12  SIZE: 750ML',7)
            text(138,top+22.5,('CRV / UPC: ' if crv!='0' else 'UPC: ')+upc,7)
            if crv!='0':text(355,top+22.5,crv,7);text(535,top+22.5,crv_total,7)
            if notes:text(138,top+33.75,notes,7)
        if page_number==1:
            text(36,38,'Southern Glazers Wine and Spirits of California South',8)
            text(36,80,'arsocal@sgws.com',8)
            table([36,250],210,['SOLD TO:'],['EXAMPLE STORE'])
            table([36,250,400,575],270,['PO NUMBER','INVOICE DATE','DELIVERY DATE/TIME'],['','10/1/2026','10/1/26'])
            table([36,250,575],312,['ACCOUNT #','VENDOR #'],['123456',''])
            xs=[36,50,93,135,348,391,433,483,525,575]
            for x in xs:line(x,360,x,389)
            for y in (360,389):line(36,y,575,y)
            text(66,366,'CS',6);text(106,366,'BTLS',6)
            for x,v in [(231,'ITEM'),(355,'UNIT PRICE'),(400,'UNIT DISC'),(440,'UNIT NET'),(488,'TAXES'),(540,'TOTAL')]:text(x,373,v,5)
            item(400,'Example case product','A100','3/1','1/1' if mixed else '',
                 '120.00','20.00','100.00','100.00',
                 '7501398100325' if invalid else '0-81308-01101-1','1.20','1.20')
        else:
            text(36,40,'CUSTOMER: 123456 EXAMPLE STORE',8)
            item(84,'Example loose bottle','B200','','2/2','10.00','0.00','10.00','20.00','0-85200-00056-2','0.10','0.20')
            item(140,'Undelivered product','C300','1/0','','15.00','0.00','15.00','0.00','0-85200-00057-9','0.10','0.00','CUSTOMER DID NOT ORDER')
            item(200,'-196 backordered product','D400','','','0.00','0.00','0.00','0.00','0-80686-01443-0',notes='1 CASE(S) BACKORDERED, REORDER')
            item(260,'DELIVERY CHARGE','126161','1/1','','8.00','0.00','8.00','8.00','9-99901-26161-3')
            table([36,126,216,306,396,486,575],330,
                  ['TOTAL CS/BTLS','TOTAL BOTTLES','TOTAL GROSS AMOUNT','TOTAL DISCOUNTS','TOTAL NET AMOUNT','TOTAL TAXES'],
                  ['1/2','14','149.40','20.00','129.40','0.00'])
            table([36,200],380,['PAYMENT DUE DATE'],['10/31/26'])
            table([450,575],380,['PAY THIS AMOUNT'],['129.40'])
        text(520,38 if page_number==1 else 40,'INVOICE',10)
        text(530,57,'900002' if other_number and page_number==2 else '900001',10)
        text(36,720,'https://shop.sgproof.com/termsOfUse.',6)
        text(270,750,f'Page {page_number} of 2',7)
        pages.append('\n'.join(commands).encode())
    contents=[pages[i-1] for i in sequence]
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids=[]
    for content in contents:
        page_id=len(objects)+1;stream_id=page_id+1;kids.append(f'{page_id} 0 R')
        objects += [f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>'.encode(),
                    b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream']
    objects[1]=f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(kids)} >>'.encode()
    payload=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(payload));payload+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(payload);payload+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    for offset in offsets[1:]:payload+=f'{offset:010d} 00000 n \n'.encode()
    return payload+f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()


class SouthernGlazersTests(unittest.TestCase):
    def test_multipage_delivered_units_discounts_and_fees(self):
        result=extract_document(fixture(),'sgws.pdf')
        header=result['header'];info=header['source_info']
        self.assertEqual(header['supplier'],SUPPLIER)
        self.assertEqual((header['invoice_number'],header['invoice_date'],header['due_date']),('900001','2026-10-01','2026-10-31'))
        self.assertEqual(header['invoice_total'],'129.40')
        self.assertEqual(info['invoice_charges'],{'crv_tax':'1.40','delivery_charge':'8.00'})
        self.assertEqual(len(result['lines']),2)
        case,bottle=result['lines']
        self.assertEqual((case['quantity'],case['unit_of_measure'],case['unit_cost'],case['discount']),('1','CA','120.00','-20.00'))
        self.assertEqual(case['pack_upc'],'081308011011')
        self.assertEqual((bottle['quantity'],bottle['unit_of_measure'],bottle['extended_price']),('2','BO','20.00'))
        self.assertEqual(len(info['excluded_lines']),2)
        self.assertEqual(info['charge_lines'][0]['product_number'],'126161')
        self.assertFalse(any(line['product_number']=='126161' for line in result['lines']))
        self.assertFalse(any('Unexplained' in warning for warning in result['warnings']))
        normalized,difference=validate_review({**header,'store_id':'test'},result['lines'])
        self.assertEqual(difference,Decimal('9.40'))

    def test_nonzero_13_digit_upc_is_retained_not_truncated(self):
        result=extract_document(fixture(invalid=True),'sgws.pdf')
        self.assertEqual(result['lines'][0]['pack_upc'],'')
        self.assertEqual(result['header']['source_info']['barcode_details'][0]['barcode_raw'],'7501398100325')
        self.assertTrue(any('12 digits' in warning for warning in result['warnings']))

    def test_incomplete_repeated_reordered_and_mixed_invoice_pages_rejected(self):
        from invoice_review import _extract_document
        # In-process inspection exposes the validation reason; the public worker
        # deliberately returns a generic processing error to the upload UI.
        for content in [fixture(sequence=(1,)),fixture(sequence=(2,)),fixture(sequence=(1,1,2)),fixture(sequence=(2,1)),fixture(other_number=True)]:
            with self.subTest(length=len(content)):
                with self.assertRaises(ValueError):_extract_document(content,'sgws.pdf')

    def test_mixed_units_require_manual_review(self):
        result=extract_document(fixture(mixed=True),'sgws.pdf')
        self.assertEqual(result['lines'][0]['quantity'],'')
        self.assertEqual(result['lines'][0]['unit_of_measure'],'')
        with self.assertRaises(ValueError):validate_review({**result['header'],'store_id':'test'},result['lines'])

    def test_review_save_account_duplicate_and_no_catalog_mutation(self):
        payload=fixture();result=extract_document(payload,'sgws.pdf')
        header={**result['header'],'store_id':'test'}
        lines=[dict(line,action='Keep unlinked') for line in result['lines']]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'db.sqlite3';import_pricebook(ROOT/'data/pricebook.csv',path)
            with self.assertRaisesRegex(ValueError,'totals differ'):save_review(payload,'sgws.pdf',header,lines,database=path)
            save_review(payload,'sgws.pdf',header,lines,acknowledge_difference=True,database=path)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT total_cents,item_count FROM purchase_invoices').fetchone(),(12940,2))
                self.assertEqual(db.execute('SELECT count(*) FROM catalog_candidates').fetchone()[0],0)
                db.execute("UPDATE purchase_invoices SET retailer_name='Other display',store_id='000001',invoice_number='00900001',customer_id='00123456'")
            with self.assertRaisesRegex(ValueError,'supplier account'):
                save_review(payload+b'\n','copy.pdf',header,lines,acknowledge_difference=True,database=path)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM purchase_invoices').fetchone()[0],1)

    def test_upload_preview_and_charge_display(self):
        from unittest.mock import patch
        from auth_helpers import logged_in_app
        import invoice_review_ui
        payload=fixture()
        class Uploaded:
            name='sgws.pdf'
            def getvalue(self):return payload
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'db.sqlite3';import_pricebook(ROOT/'data/pricebook.csv',path)
            with patch.object(invoice_review_ui,'DATABASE',path),patch('streamlit.file_uploader',return_value=Uploaded()):
                app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
                app.radio(key='navigation').set_value('New Items Review').run()
                self.assertFalse(app.exception)
                self.assertTrue(any('Delivery charge: $8.00' in c.value and 'Invoice-level CRV: $1.40' in c.value for c in app.caption))
                next(b for b in app.button if b.label=='Check for new items').click().run()
                self.assertFalse(app.exception)
                self.assertTrue(any('Invoice total minus line totals: 9.40' in w.value for w in app.warning))
                self.assertTrue(next(b for b in app.button if b.label=='Save reviewed invoice').disabled)

    @unittest.skipUnless(os.environ.get('SGWS_PDF_DIRECTORY'),'Private SGWS originals not configured')
    def test_private_originals(self):
        folder=Path(os.environ['SGWS_PDF_DIRECTORY'])
        cases=[('2750590',28,'5160.90','55.20',0,'2026-10-07','2026-11-06',50,6),
               ('2755843',6,'1835.88','14.40',0,'2026-10-09','2026-11-08',13,0),
               ('2761760',22,'4342.76','42.60',2,'2026-10-14','2026-11-13',26,1)]
        for invoice,count,total,crv,excluded,issued,due,cases_qty,bottles_qty in cases:
            with self.subTest(invoice=invoice):
                result=extract_document((folder/f'Invoice_{invoice}.pdf').read_bytes(),f'Invoice_{invoice}.pdf')
                header=result['header'];info=header['source_info']
                self.assertEqual((header['invoice_number'],header['invoice_date'],header['due_date']),(invoice,issued,due))
                self.assertEqual(len(result['lines']),count)
                self.assertEqual(header['invoice_total'],total)
                self.assertEqual(info['invoice_charges'],{'crv_tax':crv,'delivery_charge':'8.00'})
                self.assertEqual(len(info['excluded_lines']),excluded)
                self.assertEqual(sum(Decimal(line['extended_price']) for line in result['lines'])+Decimal(crv)+8,Decimal(total))
                self.assertEqual(sum(Decimal(line['quantity']) for line in result['lines'] if line['unit_of_measure']=='CA'),cases_qty)
                self.assertEqual(sum(Decimal(line['quantity']) for line in result['lines'] if line['unit_of_measure']=='BO'),bottles_qty)
                self.assertTrue(all(len(line['pack_upc'])==12 for line in result['lines'] if line['pack_upc']))
                self.assertFalse(any('DELIVERY CHARGE' in line['description'] for line in result['lines']))
                if invoice=='2761760':
                    self.assertEqual(next(line['pack_upc'] for line in result['lines'] if line['product_number']=='949176'),'')
