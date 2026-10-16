from auth_helpers import logged_in_app
from datetime import date
from pathlib import Path
import unittest
from streamlit.testing.v1 import AppTest
from dashboard_data import ROOT, load_data, reconcile, sales_coverage

class DashboardTests(unittest.TestCase):
    def test_sales_preview_is_opt_in_and_paginated(self):
        app = logged_in_app(str(ROOT/'dashboard.py'), default_timeout=30)
        app.date_input[0].set_value((date(2026,5,1),date(2026,8,15))).run()
        self.assertFalse(app.checkbox(key='show_sales_table').value)
        app.checkbox(key='show_sales_table').set_value(True).run()
        data = load_data()['sales']
        expected = data[data.sale_date.between('2026-05-01', '2026-08-15')].drop(columns='import_id')
        # Coverage is first; sales preview is the next table.
        self.assertEqual(len(app.dataframe[1].value), 200)
        self.assertEqual(app.dataframe[1].value.source_upc.tolist(), expected.iloc[:200].source_upc.tolist())
        app.number_input(key='sales_preview_page').set_value(2).run()
        self.assertEqual(app.dataframe[1].value.source_upc.tolist(), expected.iloc[200:400].source_upc.tolist())
        app.number_input(key='sales_preview_page').set_value(100).run()
        app.date_input[0].set_value((date(2026,8,12),date(2026,8,12))).run()
        self.assertEqual(app.number_input(key='sales_preview_page').value, 4)
        self.assertEqual(len(app.exception), 0)

    def test_non_moving_review_filters_and_download(self):
        app = logged_in_app(str(ROOT/'dashboard.py'), default_timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(app.checkbox(key='non_moving_stocked').value)
        app.text_input(key='non_moving_search').set_value('no-such-product-xyz').run()
        self.assertTrue(any('No non-moving items match' in item.value for item in app.info))
        app.checkbox(key='non_moving_stocked').set_value(False).run()
        app.text_input(key='non_moving_search').set_value('').run()
        self.assertEqual(len(app.exception), 0)

    def test_mobile_and_sidebar_navigation_stay_in_sync(self):
        app = logged_in_app(str(ROOT/'dashboard.py'), default_timeout=30)
        app.selectbox(key='mobile_page').set_value('Products').run()
        self.assertEqual(app.radio(key='navigation').value, 'Products')
        self.assertEqual(app.title[0].value, 'Products')
        self.assertEqual(len(app.exception), 0)
        app.radio(key='navigation').set_value('Inventory').run()
        self.assertEqual(app.selectbox(key='mobile_page').value, 'Inventory')
        self.assertEqual(app.title[0].value, 'Inventory')
        self.assertEqual(len(app.exception), 0)

    def test_coverage_and_exact_reconciliation(self):
        data=load_data()
        coverage=sales_coverage(data['sales']).set_index('Month')
        self.assertEqual(int(coverage.loc['2026-01','Dates present']),0)
        self.assertEqual(int(coverage.loc['2026-08','Missing dates']),0)
        self.assertEqual(int(coverage.loc['2026-10','Dates in period']),15)
        self.assertEqual(len(reconcile(data['invoices'],data['purchase_lines'])),10)

    def test_pages_and_filters(self):
        app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.date_input[0].value,(date(2026,10,1),date(2026,10,15)))
        app.date_input[0].set_value((date(2026,5,1),date(2026,10,15))).run()
        self.assertEqual(app.metric[0].value,'$1,959,533.66')
        app.date_input[0].set_value((date(2026,8,12),date(2026,8,12))).run()
        self.assertEqual(app.metric[0].value,'$10,460.68')
        self.assertEqual(app.metric[2].value,'668')
        app.selectbox(key='sales_measure').set_value('Scan Sales').run()
        self.assertEqual(app.metric[0].value,'$8,123.51')
        app.selectbox(key='sales_measure').set_value('Sales $').run()
        app.main.radio[0].set_value('Matched products only').run()
        self.assertEqual(len(app.exception),0)
        self.assertNotEqual(app.metric[0].value,'$1,959,533.66')
        app.date_input[0].set_value((date(2026,8,13),date(2026,8,31))).run()
        self.assertEqual(app.metric[2].value,'14,298')
        app.main.radio[0].set_value('All report rows').run()
        self.assertEqual(app.metric[2].value,'14,613')
        self.assertEqual(app.metric[0].value,'$227,951.72')
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
        self.assertEqual(app.metric[0].value,'16,834')
        self.assertEqual(len(app.exception),0)

    def test_all_beer_group_across_department_change(self):
        app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
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

    def test_department_groups_cover_sources_without_changing_totals(self):
        from collections import Counter
        from dashboard_data import SALES_DEPARTMENT_GROUPS, filter_sales_departments
        sales=load_data()['sales']
        memberships=Counter(d for group in SALES_DEPARTMENT_GROUPS.values() for d in group)
        self.assertEqual(set(sales.department)-memberships.keys(),set())
        self.assertTrue(all(count==1 for count in memberships.values()))
        selected=filter_sales_departments(sales,list(SALES_DEPARTMENT_GROUPS))
        self.assertEqual(len(selected),len(sales))
        self.assertEqual(selected.sales_cents.sum(),sales.sales_cents.sum())
        self.assertEqual(selected.scan_sales_cents.sum(),sales.scan_sales_cents.sum())
        self.assertNotIn('Non-Alcoholic Beer & Wine',SALES_DEPARTMENT_GROUPS['All Wine'])
        self.assertIn('Champagne',SALES_DEPARTMENT_GROUPS['All Wine'])

    def test_wine_filter_and_multiple_groups(self):
        app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
        app.multiselect[0].set_value(['All Wine']).run()
        day=date(2026,6,12)
        app.date_input[0].set_value((day,day)).run()
        self.assertEqual(app.metric[0].value,'$808.69')
        app.multiselect[0].set_value(['All Wine','White Wine','Champagne']).run()
        self.assertEqual(app.metric[0].value,'$808.69')
        app.multiselect[0].set_value(['All Wine','All Beer']).run()
        self.assertEqual(app.metric[0].value,'$2,391.48')
        day=date(2026,6,13)
        app.date_input[0].set_value((day,day)).run()
        self.assertEqual(app.metric[0].value,'$4,035.18')
        self.assertEqual(len(app.exception),0)
