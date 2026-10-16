"""Candidates for reorder review, based on observed positive sales activity."""
import pandas as pd
from dashboard_data import filter_sales_departments


def non_moving_products(sales, products, start, end, departments=()):
    history = sales[sales.sale_date.le(end)].copy()
    quantity = pd.to_numeric(history.quantity, errors='coerce')
    activity = history[(quantity.gt(0) | history.sales_cents.gt(0)
                        | history.scan_sales_cents.gt(0)) & history.matched_upc.notna()]
    sold = activity.loc[activity.sale_date.ge(start), 'matched_upc']
    candidates = filter_sales_departments(products, departments)
    candidates = candidates[~candidates.upc.isin(sold)].copy()
    last = activity.groupby('matched_upc').sale_date.max()
    candidates['last_sale'] = candidates.upc.map(last)
    candidates['days_since_sale'] = (end - candidates.last_sale).dt.days.astype('Int64')
    candidates['history'] = candidates.last_sale.notna().map({
        True: 'Previously sold; none in selected range',
        False: 'No recorded sale; verify listing and UPC'})
    candidates['stock_number'] = pd.to_numeric(candidates.pricebook_stock, errors='coerce')
    return candidates.sort_values(['stock_number', 'name'], ascending=[False, True])
