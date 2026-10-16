"""Optional read-only validation of private reports; imports use temporary DBs."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from decimal import Decimal as D
from delivery_reports import parse_upload,preview_uploads,save_uploads,load_reports,total
from delivery_metrics import summarize,quality_details,common_period

MANIFEST=os.environ.get('DELIVERY_REPORT_MANIFEST')


@unittest.skipUnless(MANIFEST,'Set DELIVERY_REPORT_MANIFEST to validate private October reports.')
class SuppliedReportTests(unittest.TestCase):
    def test_all_sources_exact_cohorts_bridges_and_reimport(self):
        manifest=json.loads(Path(MANIFEST).read_text())
        inputs=[parse_upload(Path(v['path']).read_bytes(),Path(v['path']).name) for v in manifest.values()]
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'test.sqlite3';sqlite3.connect(db).close()
            self.assertFalse(preview_uploads(inputs,db)['conflicts'])
            save_uploads(inputs,db)
            data,sources=load_reports(db)
            self.assertEqual(common_period(data),('2026-10-01','2026-10-14'))
            m=summarize(data,'2026-10-01','2026-10-14');dd=m['DoorDash'];ue=m['Uber Eats']
            for platform,orders,sales,proceeds in [('DoorDash',74,'2669.45','2160.29'),('Uber Eats',111,'4059.18','2868.46')]:
                self.assertEqual(m[platform]['orders'],orders)
                self.assertEqual(m[platform]['sales'],D(sales))
                self.assertEqual(m[platform]['proceeds'],D(proceeds))
                self.assertTrue(m[platform]['join_ok'])
                self.assertEqual(sum(v for _,v in m[platform]['bridge']),D(proceeds))
            self.assertEqual((dd['canceled'],ue['attempts'],ue['canceled'],ue['failed']),(2,118,4,3))
            self.assertEqual(dd['net'],D('2374.27'));self.assertEqual(dd['pass_through'],D('213.98'))
            self.assertEqual(ue['ads'],D('-472.38'));self.assertEqual(ue['unallocated'],D('-78.56'))
            self.assertEqual(ue['noncompleted'],D('96.02'));self.assertEqual(ue['ledger_net'],D('2413.54'))
            self.assertEqual(ue['refund_net'],0);self.assertEqual(ue['item_sales'],D('4059.18'));self.assertTrue(ue['item_join_ok'])
            self.assertEqual((ue['offline'],ue['scheduled']),(D('103'),D('15886')))
            self.assertEqual(total(data['dd_payout'],'Net total'),D('2528.62'))
            self.assertEqual(total(data['ue_payout'],'Total payout'),D('2619.76'))
            self.assertEqual(total(data['ue_ledger'],'Total payout'),D('2644.68'))
            self.assertEqual(total(data['dd_products'],'Gross sales'),D('2690.43'))
            self.assertEqual(quality_details(data)[0],['107'])
            self.assertEqual(len(data['dd_ledger']),76);self.assertEqual(len(data['ue_ledger']),151)
            self.assertEqual(len(data['ue_items']),257)
            self.assertEqual(data['dd_customers'],[]);self.assertEqual(data['ue_sku_ratings'],[])
            before={k:len(v) for k,v in data.items()}
            save_uploads(inputs,db)
            self.assertEqual({k:len(v) for k,v in load_reports(db)[0].items()},before)
