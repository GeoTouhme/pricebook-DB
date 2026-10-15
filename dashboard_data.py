"""Read-only dashboard queries and exact invoice reconciliation."""
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import sqlite3
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / 'data/pricebook.sqlite3'


def load_data(database=DATABASE):
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        frames = {
            'sales': pd.read_sql_query('''SELECT sale_date,source_upc,matched_upc,department,item,
                quantity,sales_cents,scan_sales_cents,import_id FROM daily_sales_rows''', db),
            'products': pd.read_sql_query('''SELECT p.upc,p.name,p.size,d.name AS department,
                p.price_cents,p.price_qty,p.cost_cents,p.cost_qty,p.pricebook_stock
                FROM products p JOIN departments d ON d.id=p.department_id''', db),
            'inventory': pd.read_sql_query('SELECT * FROM website_inventory_rows', db),
            'invoices': pd.read_sql_query('''SELECT i.*,s.name AS supplier FROM purchase_invoices i
                JOIN suppliers s ON s.id=i.supplier_id''', db),
            'purchase_lines': pd.read_sql_query('SELECT * FROM purchase_lines', db),
            'imports': pd.read_sql_query('SELECT * FROM imports ORDER BY imported_at DESC,id DESC', db),
        }
    frames['sales']['sale_date'] = pd.to_datetime(frames['sales']['sale_date'])
    frames['invoices']['invoice_date'] = pd.to_datetime(frames['invoices']['invoice_date'])
    return frames


def reconcile(invoices, lines):
    totals = {}
    counts = {}
    for row in lines.itertuples():
        totals[row.invoice_id] = totals.get(row.invoice_id, Decimal(0)) + Decimal(row.extended_price)
        counts[row.invoice_id] = counts.get(row.invoice_id, 0) + 1
    result = []
    for row in invoices.itertuples():
        line_total = totals.get(row.id, Decimal(0))
        difference = Decimal(int(row.total_cents))/100 - line_total
        if difference or counts.get(row.id,0) != row.item_count:
            result.append(dict(Supplier=row.supplier, Invoice=row.invoice_number,
                Date=row.invoice_date.date().isoformat(),
                **{'Invoice total':str(Decimal(int(row.total_cents))/100),
                   'Line total':str(line_total), 'Difference':str(difference),
                   'Declared lines':row.item_count,'Imported lines':counts.get(row.id,0)}))
    return pd.DataFrame(result)


def sales_coverage(sales):
    """Missing dates are coverage gaps, never zero-sales observations."""
    if sales.empty:
        return pd.DataFrame(columns=['Month','Dates present','Dates in period','Missing dates'])
    end = sales.sale_date.max()
    expected = pd.date_range(end.replace(month=1,day=1),end,freq='D')
    present = set(sales.sale_date.dt.normalize())
    frame = pd.DataFrame({'Date':expected})
    frame['Month'] = frame.Date.dt.strftime('%Y-%m')
    frame['Present'] = frame.Date.isin(present).astype(int)
    result = frame.groupby('Month').agg(**{'Dates present':('Present','sum'),
        'Dates in period':('Present','size')}).reset_index()
    result['Missing dates'] = result['Dates in period']-result['Dates present']
    return result
