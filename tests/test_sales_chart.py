import unittest
import pandas as pd
from sales_chart import chart_periods


class SalesChartTests(unittest.TestCase):
    def test_long_range_groups_weeks_without_changing_totals(self):
        dates = pd.date_range('2026-05-01', '2026-08-15')
        daily = pd.Series(10., index=dates)
        interval, frame = chart_periods(daily, daily.notna())
        self.assertEqual(interval, 'Weekly')
        self.assertLess(len(frame), 18)
        self.assertEqual(frame.Amount.sum(), daily.sum())
        self.assertEqual(frame.Start.min(), dates.min())
        self.assertEqual(frame.End.max(), dates.max())
        self.assertEqual(frame.Days.sum(), len(dates))

    def test_missing_weeks_remain_null_and_partial_coverage_is_visible(self):
        daily = pd.Series(float('nan'), index=pd.date_range('2026-05-04', periods=14))
        daily.iloc[0] = 12.
        _, frame = chart_periods(daily, daily.notna(), 'Weekly')
        self.assertEqual(frame.iloc[0].Amount, 12.)
        self.assertEqual(frame.iloc[0].Coverage, '1 / 7 days reported')
        self.assertTrue(pd.isna(frame.iloc[1].Amount))

    def test_daily_override_and_monthly_auto(self):
        daily = pd.Series(1., index=pd.date_range('2026-01-01', periods=200))
        interval, frame = chart_periods(daily, daily.notna())
        self.assertEqual(interval, 'Monthly')
        self.assertEqual(frame.Amount.sum(), 200.)
        interval, frame = chart_periods(daily, daily.notna(), 'Daily')
        self.assertEqual(interval, 'Daily')
        self.assertEqual(len(frame), 200)
