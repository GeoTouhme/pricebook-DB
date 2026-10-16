"""Sanitized synthetic cases; real uploads are never committed as fixtures."""
import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from decimal import Decimal

from delivery_reports import (parse_upload,preview_uploads,save_uploads,load_reports,
                              facts,number,local_date,DD_BRIDGE)
from delivery_metrics import summarize


def upload(kind,rows,filename='sample.csv'):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    out=io.StringIO(); w=csv.DictWriter(out,fields);w.writeheader();w.writerows(rows)
    return parse_upload(out.getvalue().encode('utf-8-sig'),filename)


def order(workflow='workflow-1',day='2026-10-01',amount='10.00'):
    return {'Store UUID':'store-1','Workflow UUID':workflow,'Completed?':'1','Date Ordered':day,
            'Order Status':'completed','Ticket Size':amount}


def ledger(workflow='workflow-1',status='Completed',amount='10.00',payout='8.00'):
    return {'Store UUID':'store-1','Workflow ID':workflow,'Order Status':status,
            'Order Date':'10/1/26','Order Completion time':'2026-10-01 12:00',
            'Total payout':payout,'Sales (excl. tax)':amount,'Marketplace Fee':'-2.00' if status=='Completed' else '0',
            'Total Sales after Adjustments (incl tax)':amount,'Marketplace Facilitator Tax':'0',
            'Marketplace Facilitator Tax Adjustment':'0','Currency Code':'USD'}


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'data.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE sentinel(value TEXT)');db.execute("INSERT INTO sentinel VALUES('untouched')")

    def test_preview_read_only_save_backup_and_idempotency(self):
        u=upload('ue_orders',[order()])
        before=self.db.read_bytes();p=preview_uploads([u],self.db)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse(p['conflicts'])
        r=save_uploads([u],self.db);self.assertTrue(Path(r['backup']).exists())
        with sqlite3.connect(r['backup']) as backup:
            self.assertEqual(backup.execute('SELECT * FROM sentinel').fetchall(),[('untouched',)])
            self.assertEqual(backup.execute("SELECT count(*) FROM sqlite_master WHERE name='delivery_facts'").fetchone()[0],0)
        save_uploads([u],self.db)
        data,_=load_reports(self.db);self.assertEqual(len(data['ue_orders']),1)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT * FROM sentinel').fetchall(),[('untouched',)])

    def test_revisions_block_entire_batch(self):
        save_uploads([upload('ue_orders',[order()])],self.db)
        changed=upload('ue_orders',[order(amount='11')]);new=upload('ue_orders',[order('new')])
        before=self.db.read_bytes()
        self.assertTrue(preview_uploads([changed,new],self.db)['conflicts'])
        with self.assertRaises(ValueError):save_uploads([changed,new],self.db)
        self.assertEqual(self.db.read_bytes(),before)

    def test_refund_dispute_events_survive_same_workflow(self):
        rows=[ledger(),ledger(status='Refund',amount='0',payout='-3.00'),ledger(status='Refund Disputed',amount='0',payout='3.00')]
        save_uploads([upload('ue_ledger',rows),upload('ue_orders',[order()])],self.db)
        data,_=load_reports(self.db);self.assertEqual(len(data['ue_ledger']),3)
        r=summarize(data,'2026-10-01','2026-10-14')['Uber Eats']
        self.assertEqual(r['orders'],1);self.assertEqual(r['refund_net'],0);self.assertEqual(r['proceeds'],8)

    def test_two_row_headers_and_mixed_item_context(self):
        completed=dict(ledger(),**{'Store Name':'Sample shop','Item Name':''})
        item=dict(completed,**{'Store Name':'','Item Name':'Sample item','Final Quantity':'1'})
        refund=dict(completed,**{'Order Status':'Refund','Total payout':'-3','Sales (excl. tax)':'0'})
        refunditem=dict(item,**{'Order Status':'','Sales (excl. tax)':'0'})
        u=upload('ue_mixed',[completed,item,refund,refunditem])
        rows=facts(u['reports'][0]);self.assertEqual(len(rows),2)
        self.assertEqual(json.loads(rows[0][4])['Order Status'],'Completed')
        self.assertEqual(json.loads(rows[1][4])['Order Status'],'Refund')
        fields=list(ledger());out=io.StringIO();w=csv.writer(out)
        w.writerow(['definitions']*len(fields));w.writerow(fields);w.writerow(ledger().values())
        report=parse_upload(out.getvalue().encode(),'ledger.csv')['reports'][0]
        self.assertEqual(report['kind'],'ue_ledger');self.assertEqual(len(facts(report)),1)

    def test_archive_equivalence_and_traversal(self):
        u=upload('ue_orders',[order()]);payload=u['payload']
        def zipped(name):
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as z:z.writestr(name,payload)
            return out.getvalue()
        a=parse_upload(zipped('one.csv'),'one.zip');b=parse_upload(zipped('different.csv'),'two.zip')
        save_uploads([a,b],self.db)
        self.assertEqual(len(load_reports(self.db)[0]['ue_orders']),1)
        with self.assertRaises(ValueError):parse_upload(zipped('../bad.csv'),'bad.zip')
        with self.assertRaises(ValueError):parse_upload(b'not a zip','bad.zip')
        with self.assertRaises(ValueError):parse_upload(b'not excel','bad.xlsx')

    def test_optional_header_only_and_malformed_money(self):
        empty=parse_upload(b'Item Name,Rating\n','ratings.csv')
        save_uploads([empty],self.db)
        self.assertEqual(load_reports(self.db)[0]['ue_sku_ratings'],[])
        with self.assertRaises(ValueError):facts(upload('ue_orders',[order(amount='NaN')])['reports'][0])
        with self.assertRaises(ValueError):number('not money')

    def test_local_placement_boundary_and_missing_finance(self):
        u=upload('ue_orders',[dict(order(day='2026-09-30'),**{'Order Completion Time':'2026-10-01 00:01'}),order('oct')])
        save_uploads([u],self.db)
        r=summarize(load_reports(self.db)[0],'2026-10-01','2026-10-14')['Uber Eats']
        self.assertEqual(r['orders'],1);self.assertFalse(r['ledger_available'])
        self.assertEqual(local_date('10/1/26'),'2026-10-01')

    def test_financial_reconciliation_rejects_invalid_row(self):
        bad=upload('ue_ledger',[ledger(payout='100')])
        with self.assertRaises(ValueError):save_uploads([bad],self.db)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='delivery_facts'").fetchone()[0],0)

    def test_ambiguous_misc_and_aggregate_overlap_blocked(self):
        misc=dict(ledger(workflow='',status='',amount='0',payout='-3'),**{'Other payments description':'Other fee'})
        save_uploads([upload('ue_ledger',[misc])],self.db)
        revised=dict(misc,**{'Total payout':'-4'})
        self.assertTrue(preview_uploads([upload('ue_ledger',[revised])],self.db)['conflicts'])
        product={'Store ID':'s','Item name':'Sample','Gross sales':'2','Start date':'2026-10-01','End date':'2026-10-15'}
        save_uploads([upload('dd_products',[product])],self.db)
        product['Gross sales']='3'
        self.assertTrue(preview_uploads([upload('dd_products',[product])],self.db)['conflicts'])

    def test_overlapping_orders_no_duplicate_or_header_item_doublecount(self):
        save_uploads([upload('ue_orders',[order('a'),order('b')])],self.db)
        save_uploads([upload('ue_orders',[order('b'),order('c')])],self.db)
        self.assertEqual(len(load_reports(self.db)[0]['ue_orders']),3)

    def test_streamlit_charts_and_filters(self):
        from streamlit.testing.v1 import AppTest
        save_uploads([upload('ue_orders',[order()]),upload('ue_ledger',[ledger()])],self.db)
        app=AppTest.from_string('from delivery_ui import render_delivery\nrender_delivery('+repr(str(self.db))+')',default_timeout=30).run()
        self.assertEqual(list(app.exception),[])
        app.multiselect[0].set_value(['Uber Eats']).run()
        self.assertEqual(app.metric[0].value,'$10.00')
        app.radio[0].set_value('Orders').run()
        self.assertEqual(list(app.exception),[])
        from datetime import date
        app.date_input[0].set_value((date(2026,10,2),date(2026,10,3))).run()
        self.assertEqual(app.metric[1].value,'Not provided')
        self.assertEqual(list(app.exception),[])

    def test_rollback_if_write_fails_after_first_report(self):
        from unittest.mock import patch
        import delivery_reports
        first=upload('ue_orders',[order()]);second=upload('ue_orders',[order('second')])
        original=delivery_reports.facts;calls=0
        def failing(report):
            nonlocal calls
            calls+=1
            if calls==4: raise ValueError('simulated late validation failure')
            return original(report)
        with patch('delivery_reports.facts',side_effect=failing):
            with self.assertRaises(ValueError):save_uploads([first,second],self.db)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='delivery_facts'").fetchone()[0],0)
            self.assertEqual(db.execute('SELECT * FROM sentinel').fetchall(),[('untouched',)])

    def test_identical_misc_events_preserved_and_batch_revisions_blocked(self):
        misc=dict(ledger(workflow='',status='',amount='0',payout='-3'),**{'Other payments description':'Other fee'})
        a=upload('ue_ledger',[misc,misc]);save_uploads([a],self.db)
        self.assertEqual(len(load_reports(self.db)[0]['ue_ledger']),2)
        revised=upload('ue_ledger',[dict(misc,**{'Total payout':'-4'})])
        self.assertTrue(preview_uploads([a,revised],self.db)['conflicts'])
        empty=Path(self.tmp.name)/'empty.sqlite3';sqlite3.connect(empty).close()
        self.assertTrue(preview_uploads([a,revised],empty)['conflicts'])

    def test_doordash_local_date_and_case_normalized_join(self):
        row=dict.fromkeys(DD_BRIDGE,'0')
        row.update({'Store ID':'store-1','DoorDash transaction ID':'TX-1','DoorDash order ID':'ABC',
            'Timestamp local date':'2026-10-01','Timestamp UTC date':'2026-10-02',
            'Transaction type':'Order','Subtotal':'10','Commission':'-2','Net total':'8'})
        sales={'Store ID':'store-1','Order ID':'abc','Order placed date':'2026-10-01',
               'Is cancelled':'false','Subtotal':'10','Currency':'USD'}
        save_uploads([upload('dd_ledger',[row]),upload('dd_sales',[sales])],self.db)
        result=summarize(load_reports(self.db)[0],'2026-10-01','2026-10-01')['DoorDash']
        self.assertTrue(result['join_ok']);self.assertEqual(result['proceeds'],8)
        result=summarize(load_reports(self.db)[0],'2026-10-02','2026-10-02')['DoorDash']
        self.assertFalse(result['ledger_observed']);self.assertFalse(result['observed'])
