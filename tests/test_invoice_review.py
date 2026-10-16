from auth_helpers import logged_in_app
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
            'upc':'200001000003','pack_upc':overrides.get('upc','200001000003'),'quantity':'2','unit_cost':'5','extended_price':'10.00',
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
        from purchase_matching import pack_upc_or_blank
        self.assertEqual(lines[0]['upc'],pack_upc_or_blank(first['Pack UPC']))
        self.assertEqual(lines[0]['pack_upc'],first['Pack UPC'])
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
            [self.line(upc='00100000000001',remember_mapping=True)],database=self.db)
        mapped=classify_lines([self.line(upc='00100000000001')],self.header['supplier'],self.db)[0]
        self.assertEqual(mapped['status'],'Existing item')
        self.assertEqual(mapped['confirmed_upc'],'200001000003')
        self.assertEqual(mapped['purchase_history'],'Seen from this supplier')
        other_pack=classify_lines([self.line(upc='00100000000001',ppc='24')],self.header['supplier'],self.db)[0]
        self.assertNotEqual(other_pack['status'],'Existing item')
        other_vendor=classify_lines([self.line(upc='00100000000001')],'Different supplier',self.db)[0]
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
            'Product Number':'UI-1','Pack UPC':'00200001000003','UPC Number':'499733700064','Product Description':'ULTRA WATERMELON FOCUS',
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
            app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
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
            self.assertTrue(any('UI-TEST' in s.value and '$10.00' in s.value for s in app.success))
            app.run()
            self.assertTrue(any('UI-TEST' in s.value for s in app.success))
            self.assertFalse(any(b.label=='Save reviewed invoice' for b in app.button))
            button(app,'View in Purchases').click().run()
            self.assertEqual(app.sidebar.radio[0].value,'Purchases')
            app.sidebar.radio[0].set_value('New Items Review').run()
            self.assertTrue(any('UI-TEST' in s.value for s in app.success))
            with sqlite3.connect(self.db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM purchase_invoices').fetchone()[0],1)
                self.assertEqual(con.execute('SELECT document FROM invoice_reviews').fetchone()[0],payload)

    def test_real_fintech_pdf_extraction_and_historical_matches(self):
        from decimal import Decimal
        pdf=ROOT/'tests/fixtures/fintech_invoice.pdf'
        result=extract_document(pdf.read_bytes(),pdf.name)
        self.assertEqual(result['header'],dict(supplier='Breakthru Beverage California LLC',
            retailer='Balport Liquor Store',invoice_number='0129249702',invoice_date='2026-10-09',
            due_date='2026-11-08',invoice_total='633.12'))
        self.assertEqual(len(result['lines']),7)
        self.assertEqual([r['product_number'] for r in result['lines']],
            ['9039439','9092415','9110002','9179061','9179063','9186491','9264126'])
        self.assertEqual(result['lines'][0]['description'],'1800 TEQ ULT MARG RTD 1.75L')
        self.assertEqual(result['lines'][1]['description'],'CUERVO AUTH MARG STRWB LME PET 12B 375ML')
        self.assertEqual(result['lines'][-1]['description'],'LINE 39 RED BLEND EXCURSION 750ML')
        self.assertEqual([r['extended_price'] for r in result['lines']],
            ['80.16','42.48','127.08','153.36','76.68','76.68','76.68'])
        self.assertTrue(all(not row['upc'] for row in result['lines']))
        for row in result['lines']:
            self.assertEqual(len(row['case_upc']),14)
            self.assertEqual(Decimal(row['quantity'])*Decimal(row['unit_cost'])+
                Decimal(row['discount'])+Decimal(row['adjustments']),Decimal(row['extended_price']))
        header={**result['header'],'store_id':'000001','customer_id':''}
        self.assertEqual(validate_review(header,result['lines'])[1],0)
        for source in sorted((ROOT/'data/invoices').glob('*.csv')):
            import_invoices(source,self.db)
        matches=classify_lines(result['lines'],header['supplier'],self.db)
        self.assertTrue(all(row['status']=='Previously purchased' for row in matches))
        self.assertEqual([row['suggestions'].split(' — ')[0] for row in matches[1:]],
            ['','080516406947','','898756001477','898756001231',''])
        self.assertEqual(matches[0]['suggestions'],'')
        self.assertTrue(all(row['action']=='Review needed' for row in matches))
        # Blank PACK UPC must remain blank; CASE UPC is preserved only in the review audit.
        decisions=[{**r,'action':'Keep unlinked','confirmed_upc':''} for r in matches]
        saved=save_review(pdf.read_bytes(),pdf.name,header,decisions,database=self.db)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT source_upc FROM purchase_lines WHERE invoice_id=? ORDER BY line_number',
                (saved['invoice_id'],)).fetchall(),[('',) for r in result['lines']])
            self.assertEqual(con.execute('SELECT total_cents FROM purchase_invoices WHERE id=?',(saved['invoice_id'],)).fetchone()[0],63312)

    def test_pack_upc_normalization_and_compatible_names(self):
        from purchase_matching import normalize_pack_upc
        from invoice_review import compatible_name
        for raw,expected in [('00070897013315','070897013315'),('070897013315','070897013315'),
                             ('70897013315','070897013315'),('12345678','000012345678'),('', '')]:
            self.assertEqual(normalize_pack_upc(raw),expected)
        for raw in ['10898756001474','6.0925E+11','123.0','1234-5678']:
            with self.assertRaises(ValueError):normalize_pack_upc(raw)
        self.assertFalse(compatible_name('LINE 39 P NOIR 750ML','Line 39 merlot 750ml'))
        self.assertFalse(compatible_name('1800 TEQ ULT MARG RTD 1.75L','1800 TEQ ULT WATERMELON MARG RTD 1.75L'))
        self.assertFalse(compatible_name('BANFI CHIANTI SUPERIORE 750ML','SANTA CRISTINA CHIANTI SUPERIORE 750ML'))
        self.assertTrue(compatible_name('LINE 39 P NOIR 750ML','LINE 39 PINOT NOIR, 750 ml'))

    def test_fintech_pdf_prefills_review_page(self):
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        import invoice_review_ui
        import hashlib
        pdf=ROOT/'tests/fixtures/fintech_invoice.pdf'
        class Uploaded:
            name='invoice.pdf'
            def getvalue(self):return pdf.read_bytes()
        with patch.object(invoice_review_ui,'DATABASE',self.db),patch('streamlit.file_uploader',return_value=Uploaded()):
            app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
            app.session_state['review_document']=hashlib.sha256(pdf.read_bytes()).hexdigest()
            app.session_state['review_extracted']={'kind':'pdf','lines':[],'text':'old result','warnings':[]}
            app.sidebar.radio[0].set_value('New Items Review').run()
            self.assertEqual(len(app.exception),0)
            values={item.label:item.value for item in app.text_input}
            self.assertEqual(values['Invoice number'],'0129249702')
            self.assertEqual(values['Invoice total (credits negative)'],'633.12')
            self.assertEqual(values['Invoice date (YYYY-MM-DD)'],'2026-10-09')
            self.assertEqual(values['Due date (YYYY-MM-DD, optional)'],'2026-11-08')
            self.assertEqual(values['Retailer'],'Balport Liquor Store')
            self.assertTrue(any(s.label=='Supplier' and s.value=='Breakthru Beverage California LLC' for s in app.selectbox))
            source=next(frame.value for frame in app.dataframe if 'case_upc' in frame.value.columns)
            self.assertEqual(len(source),7)
            next(b for b in app.button if b.label=='Check for new items').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(sum(int(metric.value) for metric in app.metric),7)

    def test_matching_uses_normalized_pack_and_never_case(self):
        known=self.line(upc='499733700064',case_upc='10898756001474',pack_upc='00200001000003')
        result=classify_lines([known],self.header['supplier'],self.db)[0]
        self.assertEqual(result['upc'],'200001000003')
        self.assertEqual(result['confirmed_upc'],'200001000003')
        example=classify_lines([self.line(pack_upc='00070897013315')],self.header['supplier'],self.db)[0]
        self.assertEqual(example['upc'],'070897013315')
        self.assertEqual(example['confirmed_upc'],'070897013315')
        missing=self.line(upc='200001000003',case_upc='10898756001474',pack_upc='',description='UNKNOWN UNIQUE THING')
        result=classify_lines([missing],self.header['supplier'],self.db)[0]
        self.assertEqual(result['upc'],'')
        self.assertEqual(result['status'],'Unreadable code')
        self.assertEqual(result['confirmed_upc'],'')
        self.assertEqual(result['suggestions'],'')
        invalid={**known,'pack_upc':'10898756001474','description':'UNKNOWN UNIQUE THING'}
        result=classify_lines([invalid],self.header['supplier'],self.db)[0]
        self.assertEqual(result['status'],'Unreadable code')
        self.assertEqual(result['confirmed_upc'],'')

    def test_new_item_confirmation_stores_twelve_digits(self):
        row=self.line(pack_upc='00123456789012',description='BRAND NEW PRODUCT',
            action='Confirm new item',confirmed_upc='00123456789012')
        save_review(b'new normalized','new.pdf',self.header,[row],database=self.db)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT retail_upc FROM catalog_candidates').fetchone()[0],'123456789012')
            self.assertEqual(con.execute('SELECT source_upc,pack_upc FROM purchase_lines').fetchone(),('123456789012','00123456789012'))

    def test_refresh_auto_links_preserves_explicit_reviews(self):
        from purchase_matching import refresh_purchase_pack_links
        for source in sorted((ROOT/'data/invoices').glob('*.csv')):import_invoices(source,self.db)
        self.assertEqual(refresh_purchase_pack_links(self.db)['updated_links'],0)
        with sqlite3.connect(self.db) as con:
            lid,correct=con.execute("SELECT id,matched_upc FROM purchase_lines WHERE matched_upc IS NOT NULL AND matched_upc!='200001000003' LIMIT 1").fetchone()
            con.execute('UPDATE purchase_lines SET matched_upc=? WHERE id=?',('200001000003',lid))
        saved=save_review(b'manually linked','manual.pdf',self.header,
            [self.line(confirmed_upc='499733700064')],database=self.db)
        self.assertEqual(refresh_purchase_pack_links(self.db)['updated_links'],1)
        self.assertEqual(refresh_purchase_pack_links(self.db)['updated_links'],0)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT matched_upc FROM purchase_lines WHERE id=?',(lid,)).fetchone()[0],correct)
            self.assertEqual(con.execute('SELECT matched_upc FROM purchase_lines WHERE invoice_id=?',(saved['invoice_id'],)).fetchone()[0],'499733700064')

    def test_five_page_pdf_reassembles_wrapped_pack_and_adjacent_cells(self):
        from decimal import Decimal
        import re
        pdf=ROOT/'tests/fixtures/fintech_wrapped_pack_invoice.pdf'
        result=extract_document(pdf.read_bytes(),pdf.name)
        self.assertEqual(result['header']['invoice_number'],'100986029')
        self.assertEqual(result['header']['invoice_total'],'7014.88')
        self.assertEqual(len(result['lines']),81)
        first=result['lines'][0]
        self.assertEqual(first['pack_upc'],'00070897013315')
        self.assertEqual(first['upc'],'070897013315')
        self.assertEqual(first['case_upc'],'00070897013353')
        self.assertTrue(all(re.fullmatch(r'[0-9]{14}',row['pack_upc']) for row in result['lines']))
        self.assertTrue(all(re.fullmatch(r'[0-9]{12}',row['upc']) for row in result['lines']))
        indexed={row['product_number']:row for row in result['lines']}
        self.assertEqual(len(indexed),81)
        self.assertEqual(indexed['61212']['quantity'],'14.00')
        self.assertEqual(indexed['61212']['pack_upc'],'00033544001820')
        self.assertEqual(indexed['64438']['case_upc'],'00033544002346')
        self.assertEqual(indexed['64438']['pack_upc'],'00033544002339')
        self.assertEqual(indexed['71940']['upc'],'033544002933')
        self.assertEqual(indexed['67653']['description'],'HIGH NOON VODKA PEACH C12 700ML')
        self.assertEqual(indexed['67653']['case_upc'],'30085000034492')
        self.assertEqual(indexed['10436']['description'],'SAM ADAMS OCTOBERFEST B24 12OZ 6P')
        self.assertEqual(sum(Decimal(row['extended_price']) for row in result['lines']),Decimal('7014.88'))
        for row in result['lines']:
            self.assertEqual(Decimal(row['quantity'])*Decimal(row['unit_cost'])+
                Decimal(row['discount'])+Decimal(row['adjustments']),Decimal(row['extended_price']))
        self.assertEqual(validate_review({**result['header'],'store_id':'000001'},result['lines'])[1],0)

    def test_wrapped_pack_pdf_ui_refreshes_old_truncated_extraction(self):
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        import hashlib
        import invoice_review_ui
        pdf=ROOT/'tests/fixtures/fintech_wrapped_pack_invoice.pdf'
        class Uploaded:
            name='invoice-report.pdf'
            def getvalue(self):return pdf.read_bytes()
        with patch.object(invoice_review_ui,'DATABASE',self.db),patch('streamlit.file_uploader',return_value=Uploaded()):
            app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
            app.session_state['review_document']=hashlib.sha256(pdf.read_bytes()).hexdigest()+':3'
            app.session_state['review_extracted']={'kind':'pdf','lines':[{**blank_line(),'pack_upc':'0007089701'}],
                'text':'old truncated result','warnings':[]}
            app.sidebar.radio[0].set_value('New Items Review').run()
            self.assertEqual(len(app.exception),0)
            source=next(frame.value for frame in app.dataframe if 'pack_upc' in frame.value.columns)
            self.assertEqual(len(source),81)
            self.assertEqual(source.iloc[0].pack_upc,'00070897013315')
            next(b for b in app.button if b.label=='Check for new items').click().run()
            self.assertEqual(len(app.exception),0)
            matches=next(frame.value for frame in app.dataframe if 'suggestions' in frame.value.columns)
            self.assertEqual(matches.iloc[0].upc,'070897013315')
            self.assertEqual(sum(int(metric.value) for metric in app.metric),81)
            with sqlite3.connect(self.db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM purchase_invoices').fetchone()[0],0)

    def test_save_preflight_lists_every_blocking_line(self):
        from invoice_review import review_decision_errors
        rows=[self.line(action='Review needed'),
              self.line(action='Link existing product',confirmed_upc='123456789012'),
              self.line(action='Keep unlinked',remember_mapping=True)]
        errors=review_decision_errors(rows,{'200001000003'})
        self.assertEqual([row['Line'] for row in errors],[1,2,3])
        self.assertIn('still needs review',errors[0]['Problem'])
        self.assertEqual(review_decision_errors([self.line()],{'200001000003'}),[])

    def test_unfinished_pdf_decisions_visibly_disable_save(self):
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        import invoice_review_ui
        pdf=ROOT/'tests/fixtures/fintech_wrapped_pack_invoice.pdf'
        class Uploaded:
            name='invoice.pdf'
            def getvalue(self):return pdf.read_bytes()
        with patch.object(invoice_review_ui,'DATABASE',self.db),patch('streamlit.file_uploader',return_value=Uploaded()),patch.object(invoice_review_ui,'save_review') as save:
            app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
            app.sidebar.radio[0].set_value('New Items Review').run()
            next(b for b in app.button if b.label=='Check for new items').click().run()
            next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
            self.assertEqual(len(app.exception),0)
            self.assertTrue(next(b for b in app.button if b.label=='Save reviewed invoice').disabled)
            self.assertTrue(any('lines need a valid decision' in item.value for item in app.info))
            errors=next(frame.value for frame in app.dataframe if 'Problem' in frame.value.columns)
            self.assertGreater(len(errors),0)
            self.assertTrue(all(errors.Line>0))
            save.assert_not_called()

    def test_save_errors_persist_until_another_attempt(self):
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        import invoice_review_ui
        from import_invoices import HEADERS
        record=dict.fromkeys(HEADERS,'')
        record.update({'Vendor Name':'Test Supplier','Retailer Name':'Balport Liquor Store',
            'Store ID':'000001','Invoice Number':'ERROR-TEST','Invoice Date':'10/15/2026 00:00:00',
            'Invoice Total':'10.00','Item Count':'1','Product Number':'TEST','Pack UPC':'200001000003',
            'Product Description':'ULTRA WATERMELON FOCUS','Quantity':'2','Unit Cost':'5',
            'Unit of Measure':'BO','PPC':'1','Total Adjustments':'0','Total Discount':'0','Extended Price':'10.00'})
        stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=HEADERS)
        writer.writeheader();writer.writerow(record);payload=stream.getvalue().encode()
        class Uploaded:
            name='error.csv'
            def getvalue(self):return payload
        with patch.object(invoice_review_ui,'DATABASE',self.db),patch('streamlit.file_uploader',return_value=Uploaded()),patch.object(invoice_review_ui,'save_review',side_effect=sqlite3.OperationalError('database is locked')):
            app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
            app.sidebar.radio[0].set_value('New Items Review').run()
            next(b for b in app.button if b.label=='Check for new items').click().run()
            next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
            next(b for b in app.button if b.label=='Save reviewed invoice').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertTrue(any('Invoice was not saved: database is locked' in error.value for error in app.error))
            app.run()
            self.assertTrue(any('database is locked' in error.value for error in app.error))
            with sqlite3.connect(self.db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM purchase_invoices').fetchone()[0],0)

    def test_mercaso_extracts_only_fulfilled_items_and_charged_total(self):
        from mercaso_pdf import upce_to_upca
        self.assertEqual(upce_to_upca('00985234'),'009800000524')
        with self.assertRaises(ValueError):upce_to_upca('00985235')
        pdf=ROOT/'tests/fixtures/mercaso_invoice.pdf'
        result=extract_document(pdf.read_bytes(),pdf.name)
        header=result['header']
        self.assertEqual(header['supplier'],'Mercaso, Inc.')
        self.assertEqual(header['invoice_number'],'M-303112')
        self.assertEqual(header['invoice_date'],'2026-10-11')
        self.assertEqual(header['retailer'],'Bal-Port Liquors')
        self.assertEqual(header['invoice_total'],'27.49')
        self.assertEqual(header['paid'],'27.49')
        self.assertEqual(header['amount_due'],'0.00')
        self.assertEqual(header['due_date'],'')
        self.assertEqual(header['source_info']['date_basis'],'Order Date')
        self.assertTrue(any('Order Date' in text for text in result['warnings']))
        excluded=header['source_info']['excluded_lines']
        self.assertEqual(len(excluded),1)
        self.assertEqual(excluded[0]['product_number'],'DW167380-1')
        self.assertEqual(excluded[0]['quantity'],'7')
        self.assertEqual(excluded[0]['amount'],'23.03')
        self.assertEqual(len(result['lines']),1)
        line=result['lines'][0]
        self.assertEqual(line['description'],'Kinder Joy, Eggs (20 Pack)')
        self.assertEqual(line['product_number'],'DW215490')
        self.assertEqual((line['quantity'],line['unit_cost'],line['ppc'],line['unit_of_measure']),('1','27.49','20','CA'))
        self.assertEqual(line['extended_price'],'27.49')
        self.assertEqual(line['pack_upc'],'009800000524')
        barcode=header['source_info']['barcode_details'][0]
        self.assertEqual(barcode['barcode_raw'],'00985234')
        self.assertEqual(barcode['barcode_format'],'BarcodeFormat.UPCE')
        self.assertEqual(barcode['each_price'],'1.37')
        self.assertEqual(validate_review({**header,'store_id':'000001'},result['lines'])[1],0)
        matches=classify_lines(result['lines'],header['supplier'],self.db)
        self.assertEqual(matches[0]['status'],'Existing item')
        self.assertEqual(matches[0]['confirmed_upc'],'009800000524')
        saved=save_review(pdf.read_bytes(),pdf.name,{**header,'store_id':'000001'},matches,database=self.db)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute('SELECT total_cents FROM purchase_invoices').fetchone()[0],2749)
            self.assertEqual(con.execute('SELECT count(*),max(product_number) FROM purchase_lines').fetchone(),(1,'DW215490'))
            audit=json.loads(con.execute('SELECT decisions_json FROM invoice_reviews').fetchone()[0])
            self.assertEqual(audit['header']['source_info']['excluded_lines'][0]['product_number'],'DW167380-1')
        with self.assertRaisesRegex(ValueError,'already saved'):
            save_review(pdf.read_bytes(),'renamed.pdf',{**header,'store_id':'000001'},matches,database=self.db)

    def test_mercaso_upload_review_save_and_receipt(self):
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        import invoice_review_ui
        pdf=ROOT/'tests/fixtures/mercaso_invoice.pdf'
        class Uploaded:
            name='mercaso.pdf'
            def getvalue(self):return pdf.read_bytes()
        with patch.object(invoice_review_ui,'DATABASE',self.db),patch('streamlit.file_uploader',return_value=Uploaded()):
            app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
            app.sidebar.radio[0].set_value('New Items Review').run()
            self.assertEqual(len(app.exception),0)
            values={item.label:item.value for item in app.text_input}
            self.assertEqual(values['Invoice number'],'M-303112')
            self.assertEqual(values['Invoice total (credits negative)'],'27.49')
            self.assertEqual(values['Invoice date (YYYY-MM-DD)'],'2026-10-11')
            self.assertTrue(any('unfulfilled/not-charged' in item.value for item in app.warning))
            excluded=next(frame.value for frame in app.dataframe if 'reason' in frame.value.columns)
            self.assertEqual(excluded.iloc[0].product_number,'DW167380-1')
            next(b for b in app.button if b.label=='Check for new items').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(app.metric[0].value,'1')
            next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
            next(b for b in app.button if b.label=='Save reviewed invoice').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertTrue(any('M-303112' in item.value and '$27.49' in item.value for item in app.success))
            with sqlite3.connect(self.db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM purchase_lines').fetchone()[0],1)

    def test_mercaso_unknown_barcode_does_not_pad_partial_text(self):
        from unittest.mock import patch
        import pdfplumber
        from mercaso_pdf import decode_item_barcode
        pdf=ROOT/'tests/fixtures/mercaso_invoice.pdf'
        with pdfplumber.open(pdf) as doc,patch('zxingcpp.read_barcodes',return_value=[]):
            upc,info=decode_item_barcode(doc.pages[0],(214,374,280,440))
        self.assertEqual(upc,'')
        self.assertIn('manually',info['note'])
