"""Sanitized OCR fixtures; private source receipts are never checked into Git."""
import io
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont
from invoice_review import extract_document, validate_review, save_review, blank_line
from scan_ocr import OCRUnavailable, ocr_pages, orient, page_image
from scanned_receipts import parse_scans, valid_code, code_for, amount


def page_fixture(entries, barcodes=()):
    words=[];chars=[]
    for top, cells in entries:
        for x, text in cells:
            for token in text.split():
                words.append(dict(text=token,x0=x,x1=x+len(token)*5,top=top,bottom=top+12,confidence=95))
                chars.extend(dict(text=c,x0=x+i*5,x1=x+(i+1)*5,top=top,bottom=top+12) for i,c in enumerate(token))
                x+=len(token)*5+5
    text='\n'.join(' '.join(t for _,t in cells) for _,cells in entries)
    return dict(text=text,alternate_text=text,words=words,alternate_words=words,
        chars=chars,alternate_chars=chars,width=1000,height=1800,page=1,rotation=0,scanned=True,
        barcodes=[dict(text=code,top=y,bottom=y+15,x0=600,x1=950) for y,code in barcodes])


def header(**changes):
    return dict(supplier='Test supplier',retailer='Test store',store_id='1',
        invoice_number='TEST-1',invoice_date='2026-10-21',invoice_total='10.00',
        source_info={'ocr':True,'document_status':'invoice'},**changes)


def line():
    return dict(blank_line(),description='Test item',quantity='2',unit_cost='5.00',
        unit_of_measure='CA',extended_price='10.00')


class ScannedInvoiceTests(unittest.TestCase):
    def test_strict_codes_and_no_decimal_or_character_repairs(self):
        self.assertEqual(valid_code('00070897013315'),'070897013315')
        for text in ['O70897013315','07089701331','850000406637','1850000406636']:
            self.assertEqual(valid_code(text),'')
        self.assertEqual(amount('2340'),'')
        self.assertEqual(amount('2O.80'),'')
        self.assertEqual(amount('23.40'),'23.40')
        p=page_fixture([(100,[(400,'070897013315')])])
        self.assertEqual(code_for(p,90,140,'070897013315',.4,.8)[0],'070897013315')
        p['alternate_chars']=[];p['alternate_words']=[]
        self.assertEqual(code_for(p,90,140,'070897013315',.4,.8)[0],'')
        p['barcodes']=[dict(text='070897013315',top=100,bottom=120),dict(text='850000406636',top=100,bottom=120)]
        self.assertEqual(code_for(p,90,140,'070897013315',.4,.8)[0],'')

    def test_sunset_preliminary_zero_delivery_and_decoded_barcode(self):
        p=page_fixture([
            (20,[(20,'SUNSET DISTRIBUTING')]),(50,[(20,'WOT A FINAL INVOICE')]),
            (80,[(20,'Invoice#: 1000012345 Oct 21, 2026')]),
            (200,[(20,'12345 TEST WATER')]),
            (240,[(130,'2'),(630,'5.00'),(730,'0.00'),(910,'11.20')]),
            (290,[(20,'Selling Units: 24')]),
            (430,[(20,'54321 UNAVAILABLE WATER')]),
            (470,[(130,'0'),(630,'5.00'),(730,'0.00'),(910,'0.00')]),
            (520,[(20,'Selling Units: 0')]),
            (650,[(20,'Picksheet Total'),(910,'11.20')]),
            (680,[(20,'Total CRV'),(910,'1.20')]),
        ],[(280,'070897013315'),(510,'850000406636')])
        r=parse_scans([p]);info=r['header']['source_info']
        self.assertEqual(info['document_status'],'preliminary')
        self.assertEqual(len(r['lines']),1)
        self.assertEqual(len(info['excluded_lines']),1)
        self.assertEqual(r['header']['invoice_total'],'11.20')
        self.assertEqual(r['lines'][0]['quantity'],'2')
        self.assertEqual(r['lines'][0]['adjustments'],'1.20')
        self.assertEqual(r['lines'][0]['pack_upc'],'070897013315')

    def test_pepsi_net_prices_not_wholesale_or_case_barcode(self):
        p=page_fixture([
            (20,[(20,'PEPSI INVOICE # 48000001 10/21/2026')]),
            (70,[(20,'State/Local Charges'),(800,'1.00')]),
            (100,[(20,'Amount Due'),(800,'21.80')]),
            (200,[(20,'ITEM DETAIL')]),
            (240,[(20,'1.5L PL 1/12')]),
            (300,[(180,'TEST WATER'),(400,'0-70897-01331-5')]),
            (350,[(200,'40.00'),(460,'1'),(550,'12'),(610,'20.80'),(770,'20.80')]),
            (500,[(20,'STATE/LOCAL CHARGES')]),
        ])
        r=parse_scans([p]);self.assertEqual(len(r['lines']),1)
        self.assertEqual(r['lines'][0]['unit_cost'],'20.80')
        self.assertEqual(r['lines'][0]['quantity'],'1')
        self.assertEqual(r['header']['invoice_total'],'21.80')
        self.assertEqual(r['header']['source_info']['invoice_charges'],{'state_local_charges':'1.00'})
        self.assertEqual(r['lines'][0]['case_upc'],'')

    def test_missing_numeric_row_does_not_borrow_next_items_price(self):
        p=page_fixture([
            (20,[(20,'PEPSI INVOICE # 48000001')]),(80,[(20,'ITEM DETAIL')]),
            (200,[(180,'FIRST WATER'),(400,'0-70897-01331-5')]),
            (240,[(180,'SECOND WATER'),(400,'8-50000-40663-6')]),
            (280,[(200,'40.00'),(460,'1'),(550,'12'),(610,'20.80'),(770,'20.80')]),
        ])
        r=parse_scans([p])
        self.assertEqual(len(r['lines']),2)
        self.assertEqual(r['lines'][0]['unit_cost'],'')
        self.assertEqual(r['lines'][1]['unit_cost'],'20.80')

    def test_multiple_receipt_pages_rejected_instead_of_silently_omitted(self):
        p=page_fixture([(20,[(20,'SUNSET DISTRIBUTING')])])
        with self.assertRaisesRegex(ValueError,'one receipt page'):
            parse_scans([p,p])

    def test_pick_list_read_only_even_when_caller_requests_save(self):
        p=page_fixture([(20,[(20,'PEPSI PRODUCT PICK LIST FOR INV# 48000001')]),
            (50,[(20,'NOT AN INVOICE')]),(150,[(20,'TEST WATER')])],[(200,'070897013315')])
        r=parse_scans([p]);self.assertEqual(r['header']['source_info']['document_status'],'reference_only')
        self.assertEqual(r['lines'][0]['unit_cost'],'')
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'never-created.sqlite3'
            with self.assertRaisesRegex(ValueError,'pick list'):
                save_review(b'test','test.pdf',dict(header(),source_info=r['header']['source_info']),r['lines'],database=db)
            self.assertFalse(db.exists())

    def test_review_guards_and_line_arithmetic(self):
        h=header()
        with self.assertRaisesRegex(ValueError,'Verify the OCR'):
            validate_review(h,[line()])
        h['ocr_reviewed']=True
        validate_review(h,[line()])
        with self.assertRaisesRegex(ValueError,'do not reconcile'):
            validate_review(h,[dict(line(),quantity='9')])
        h['source_info']['document_status']='preliminary'
        with self.assertRaisesRegex(ValueError,'final charged purchase'):
            validate_review(h,[line()])
        h['preliminary_confirmed']=True
        validate_review(h,[line()])

    def test_missing_engine_and_page_image_limits(self):
        with patch('scan_ocr.shutil.which',return_value=None):
            with self.assertRaisesRegex(OCRUnavailable,'sudo apt install'):
                ocr_pages(SimpleNamespace(pages=[]))
        with self.assertRaisesRegex(ValueError,'at most 5'):
            ocr_pages(SimpleNamespace(pages=[None]*6))
        oversized=SimpleNamespace(images=[{'srcsize':(5000,5000)}])
        with self.assertRaisesRegex(ValueError,'20 megapixel'):page_image(oversized)

    def test_clockwise_rotation_and_low_confidence_keeps_orientation(self):
        im=Image.new('L',(1000,200),255)
        with tempfile.TemporaryDirectory() as folder:
            result=SimpleNamespace(stdout='Rotate: 270\nOrientation confidence: 4.26')
            with patch('scan_ocr.subprocess.run',return_value=result):
                rotated,degrees=orient(im,folder,{})
                self.assertEqual(degrees,270);self.assertEqual(rotated.size,(200,1000))
            result.stdout='Rotate: 180\nOrientation confidence: 1.0'
            with patch('scan_ocr.subprocess.run',return_value=result):
                self.assertEqual(orient(im,folder,{})[1],0)

    @unittest.skipUnless(shutil.which('tesseract'),'Tesseract is an optional native dependency')
    def test_real_image_pdf_through_isolated_worker(self):
        im=Image.new('RGB',(1200,1000),'white');draw=ImageDraw.Draw(im)
        fonts=list(Path('/usr/share/fonts').rglob('DejaVuSans.ttf'))
        font=ImageFont.truetype(str(fonts[0]),32) if fonts else ImageFont.load_default(size=32)
        for i,text in enumerate(['TEST PAPER INVOICE','Reference TEST-123','Date 10/21/2026',
                                 'EXAMPLE WATER 2 x 5.00','Invoice total 10.00']):
            draw.text((60,80+i*110),text,fill='black',font=font)
        output=io.BytesIO();im.save(output,format='PDF')
        result=extract_document(output.getvalue(),'sanitized-scan.pdf')
        self.assertTrue(result['header']['source_info']['ocr'])
        self.assertIn('TEST PAPER INVOICE',result['text'])
        self.assertEqual(result['lines'],[])  # Unknown layout requires manual rows.

    def test_review_ui_confirmation_save_and_reference_only(self):
        import sqlite3
        import invoice_review_ui
        from import_pricebook import import_pricebook, ROOT
        from auth_helpers import logged_in_app
        class Uploaded:
            name='test-scan.pdf'
            def getvalue(self):return b'%PDF-sanitized-ui-test'
        with tempfile.TemporaryDirectory() as folder:
            database=Path(folder)/'test.sqlite3'
            import_pricebook(ROOT/'data/pricebook.csv',database)
            h=header();h['source_info']['document_status']='preliminary'
            h['source_info']['supplier_format']='Sunset scan'
            row=dict(line(),pack_upc='200001000003',upc='200001000003')
            extracted=dict(kind='pdf',header=h,lines=[row],warnings=['Scanned document draft'],text='Sanitized scan')
            with patch.object(invoice_review_ui,'DATABASE',database), patch('streamlit.file_uploader',return_value=Uploaded()), patch.object(invoice_review_ui,'extract_document',return_value=extracted):
                app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
                app.sidebar.radio[0].set_value('New Items Review').run()
                self.assertEqual(len(app.exception),0)
                self.assertTrue(next(b for b in app.button if b.label=='Check for new items').disabled)
                next(c for c in app.checkbox if c.label.startswith('I verified all OCR')).check().run()
                self.assertTrue(next(b for b in app.button if b.label=='Check for new items').disabled)
                next(c for c in app.checkbox if c.label.startswith('I confirmed this preliminary')).check().run()
                next(b for b in app.button if b.label=='Check for new items').click().run()
                self.assertEqual(len(app.exception),0)
                next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
                next(b for b in app.button if b.label=='Save reviewed invoice').click().run()
                self.assertEqual(len(app.exception),0)
                self.assertTrue(app.success)
            with sqlite3.connect(database) as db:
                audit=json.loads(db.execute('SELECT decisions_json FROM invoice_reviews').fetchone()[0])
                self.assertTrue(audit['header']['ocr_reviewed'])
                self.assertTrue(audit['header']['preliminary_confirmed'])
            h['source_info']['document_status']='reference_only'
            with patch.object(invoice_review_ui,'DATABASE',database), patch('streamlit.file_uploader',return_value=Uploaded()), patch.object(invoice_review_ui,'extract_document',return_value=extracted):
                app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
                app.sidebar.radio[0].set_value('New Items Review').run()
                self.assertFalse(any(b.label=='Save reviewed invoice' for b in app.button))
                next(c for c in app.checkbox if c.label.startswith('I checked the scanned')).check().run()
                next(b for b in app.button if b.label=='Check pick list items').click().run()
                self.assertEqual(len(app.exception),0)
                self.assertFalse(any(b.label=='Save reviewed invoice' for b in app.button))

    @unittest.skipUnless(os.environ.get('SCANNED_INVOICE_MANIFEST'),'Private scans are optional')
    def test_private_five_scans_end_to_end(self):
        manifest=json.loads(Path(os.environ['SCANNED_INVOICE_MANIFEST']).read_text())
        expected=[(11,0,'invoice'),(4,0,'preliminary'),(40,0,'reference_only'),(7,2,'preliminary'),(40,0,'invoice')]
        for entry,(count,excluded,status) in zip(manifest,expected):
            with self.subTest(scan=entry['index']):
                result=extract_document(Path(entry['path']).read_bytes(),'private-scan.pdf')
                info=result['header']['source_info']
                self.assertEqual(len(result['lines']),count)
                self.assertEqual(len(info['excluded_lines']),excluded)
                self.assertEqual(info['document_status'],status)
                self.assertTrue(all(not r['pack_upc'] or len(r['pack_upc'])==12 for r in result['lines']))
                if entry['index']==4:
                    self.assertEqual(result['header']['invoice_total'],'951.25')
                    self.assertIn(info['ocr_pages'][1]['rotation'],(90,270))
                if entry['index']==0:
                    self.assertNotEqual(result['header']['invoice_total'],'1219.60')
                with self.assertRaises(ValueError):validate_review(result['header'],result['lines'])


if __name__=='__main__':unittest.main()
