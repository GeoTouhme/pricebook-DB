from datetime import date
from pathlib import Path
import unittest
from streamlit.testing.v1 import AppTest
from dashboard_data import ROOT, load_data, reconcile, sales_coverage

class DashboardTests(unittest.TestCase):
    def test_coverage_and_exact_reconciliation(self):
        data=load_data()
        coverage=sales_coverage(data['sales']).set_index('Month')
        self.assertEqual(int(coverage.loc['2026-01','Dates present']),0)
        self.assertEqual(int(coverage.loc['2026-08','Missing dates']),19)
        self.assertEqual(int(coverage.loc['2026-10','Dates in period']),15)
        self.assertEqual(len(reconcile(data['invoices'],data['purchase_lines'])),10)

    def test_pages_and_filters(self):
        app=AppTest.from_file(str(ROOT/'dashboard.py'),default_timeout=30).run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.metric[0].value,'$1,721,263.07')
        app.main.radio[0].set_value('Matched products only').run()
        self.assertEqual(len(app.exception),0)
        self.assertNotEqual(app.metric[0].value,'$1,721,263.07')
        app.date_input[0].set_value((date(2026,8,13),date(2026,8,31))).run()
        self.assertEqual(app.metric[2].value,'0')
        self.assertTrue(any('No sales rows' in info.value for info in app.info))
        app.sidebar.radio[0].set_value('Products').run()
        app.text_input[0].set_value('200001000003').run()
        self.assertEqual(app.metric[0].value,'1')
        self.assertEqual(len(app.exception),0)
        app.text_input[0].set_value('[').run()
        self.assertEqual(len(app.exception),0)
        app.sidebar.radio[0].set_value('Inventory').run()
        self.assertEqual(app.metric[0].value,'8,746')
        app.sidebar.radio[0].set_value('Purchases').run()
        self.assertEqual(app.metric[0].value,'$676,642.69')
        self.assertEqual(len(app.exception),0)
        app.multiselect[0].set_value(['Breakthru Beverage California LLC']).run()
        self.assertEqual(app.metric[3].value,'1')
        self.assertEqual(len(app.exception),0)
        app.sidebar.radio[0].set_value('Data quality').run()
        self.assertEqual(app.metric[0].value,'16,508')
        self.assertEqual(len(app.exception),0)

    def test_all_beer_group_across_department_change(self):
        app=AppTest.from_file(str(ROOT/'dashboard.py'),default_timeout=30).run()
        app.multiselect[0].set_value(['All Beer']).run()
        for day,total in [(date(2026,6,12),'$1,582.79'),(date(2026,6,13),'$2,097.16')]:
            app.date_input[0].set_value((day,day)).run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(app.metric[0].value,total)
        # A group and one of its members must not count the same rows twice.
        app.multiselect[0].set_value(['All Beer','BEER']).run()
        self.assertEqual(app.metric[0].value,'$2,097.16')
        app.multiselect[0].set_value(['BEER']).run()
        self.assertEqual(app.metric[0].value,'$202.97')
        from dashboard_data import filter_sales_departments
        sales=load_data()['sales']
        original=sales.department.copy()
        combined=filter_sales_departments(sales,['All Beer'])
        self.assertNotIn('Non-Alcoholic Beer & Wine',set(combined.department))
        self.assertTrue(sales.department.equals(original))
