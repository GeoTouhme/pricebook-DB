import unittest
import pandas as pd
from non_moving import non_moving_products


class NonMovingTests(unittest.TestCase):
    def setUp(self):
        self.products = pd.DataFrame({
            'upc': ['001', '002', '003', '004', '005'],
            'name': ['Sold', 'Old sale', 'Never sold', 'Return only', 'Free item'],
            'department': ['BEER'] * 4 + ['Wine'],
            'pricebook_stock': ['10', '4', 'unknown', '-2', '5']})
        self.sales = pd.DataFrame([
            ['2026-05-01', '001', '1', 100, 100],
            ['2026-05-02', '001', '-1', -100, -100],
            ['2026-04-01', '002', '1', 100, 100],
            ['2026-08-16', '003', '1', 100, 100],
            ['2026-05-02', '004', '-1', -100, -100],
            ['2026-05-02', '005', '1', 0, 0],
            ['2026-05-02', None, '1', 100, 100],
        ], columns=['sale_date', 'matched_upc', 'quantity', 'sales_cents', 'scan_sales_cents'])
        self.sales.sale_date = pd.to_datetime(self.sales.sale_date)
        self.start, self.end = pd.Timestamp('2026-05-01'), pd.Timestamp('2026-08-15')

    def test_activity_is_not_net_sales_and_future_sales_are_excluded(self):
        result = non_moving_products(self.sales, self.products, self.start, self.end).set_index('upc')
        self.assertEqual(set(result.index), {'002', '003', '004'})
        self.assertEqual(result.loc['002', 'last_sale'], pd.Timestamp('2026-04-01'))
        self.assertEqual(result.loc['002', 'days_since_sale'], 136)
        self.assertTrue(pd.isna(result.loc['003', 'last_sale']))
        self.assertTrue(pd.isna(result.loc['003', 'stock_number']))

    def test_empty_history_and_department_filter(self):
        result = non_moving_products(self.sales.iloc[:0], self.products, self.start, self.end, ['All Beer'])
        self.assertEqual(set(result.upc), {'001', '002', '003', '004'})
        self.assertTrue(result.last_sale.isna().all())
        self.assertTrue(result.days_since_sale.isna().all())

    def test_either_sales_field_counts_as_activity(self):
        self.sales.loc[0, ['quantity', 'sales_cents', 'scan_sales_cents']] = ['0', 0, 10]
        result = non_moving_products(self.sales, self.products, self.start, self.end)
        self.assertNotIn('001', set(result.upc))
