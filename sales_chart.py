"""Sales chart periods retain missing dates and selected-range boundaries."""
import pandas as pd


def chart_periods(daily, coverage, grouping='Auto'):
    days = len(daily)
    interval = grouping if grouping != 'Auto' else (
        'Daily' if days <= 31 else 'Weekly' if days <= 180 else 'Monthly')
    frame = pd.DataFrame({'Amount': daily, 'Reported': coverage.astype(int)})
    frame['Start'] = frame.index
    frame['End'] = frame.index
    frame['Days'] = 1
    if interval != 'Daily':
        frame = frame.resample('W-MON' if interval == 'Weekly' else 'MS',
                               closed='left', label='left').agg({
            'Amount': lambda values: values.sum(min_count=1),
            'Reported': 'sum', 'Start': 'min', 'End': 'max', 'Days': 'sum'})
    frame['Coverage'] = frame['Reported'].astype(str) + ' / ' + frame['Days'].astype(str) + ' days reported'
    return interval, frame.reset_index(drop=True)
