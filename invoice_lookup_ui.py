"""Search first, then inspect one product's supplier invoices."""
from decimal import Decimal
import hashlib
import json
import altair as alt
import pandas as pd
import streamlit as st
from invoice_lookup import (prepare_history, find_items, item_history, purchase_summary,
                            history_export, number)
from safe_exports import csv_bytes
from table_ui import table_page


def choice_key(prefix, options):
    # A new result set needs a new native widget identity. Reusing a keyed
    # selectbox can leave its browser label showing the previous product.
    digest=hashlib.sha256(json.dumps(options, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return prefix+'_'+digest


def render_invoice_lookup(products, lines, invoices):
    st.caption('Find a product, check its source costs, and see the invoices behind it.')
    with st.container(border=True):
        query = st.text_input('Product name, UPC or supplier item code', key='invoice_lookup_query',
            placeholder='033544000250 · Blue Moon · 48367',
            help='Searches the catalog and invoice descriptions, including items without catalog links. UPC searches use PACK UPC or a confirmed catalog link; CASE UPC is reference only.')
    if invoices.empty:
        st.info('No supplier invoices have been imported yet. Catalog products can still be searched.')
    else:
        st.caption(f'Available invoice dates: {invoices.invoice_date.min():%b %d, %Y} – {invoices.invoice_date.max():%b %d, %Y}. Results cover imported invoices only.')
    if not query.strip():
        st.info('Enter a product name or scan/paste its UPC to begin.')
        return
    history = prepare_history(lines, invoices)
    items = find_items(query, products, history)
    if not items:
        st.info('No matching product or invoice item in the imported data. Try part of the name or the supplier item code.')
        return
    if len(items) > 100:
        st.info(f'{len(items):,} items match. Refine the search to choose a product.')
        return
    by_key = {item['key']:item for item in items}
    options = list(by_key)
    product_choice_key=choice_key('invoice_lookup_item',items)
    def label(key):
        item = by_key[key]
        identity = item['upc'] or f"{item['supplier']} · {item['product_number'] or 'no supplier code'}"
        return f"{item['name']} · {item['size']} · {identity}".replace(' ·  · ', ' · ')
    key = st.selectbox('Matching product', options, format_func=label, key=product_choice_key)
    item = by_key[key]
    st.subheader(item['name'])
    st.caption((item['upc'] + ' · ' if item['upc'] else '') + (item['size'] or 'Supplier invoice item'))
    if item['catalog']:
        product = products.loc[products.upc.eq(item['upc'])].iloc[0]
        left, right = st.columns(2)
        price_qty, cost_qty = int(product.price_qty), int(product.cost_qty)
        left.metric('Price-book selling price', f'${product.price_cents/100:,.2f} / {price_qty} unit(s)')
        right.metric('Price-book source cost', f'${product.cost_cents/100:,.2f} / {cost_qty} unit(s)')
        if cost_qty > 0:
            st.caption(f'Price-book cost per catalog unit: ${Decimal(int(product.cost_cents))/100/Decimal(cost_qty):,.2f}. Source stock: {product.pricebook_stock}; not a confirmed current count.')
        else:
            st.warning('Price-book cost quantity needs review before calculating a unit cost.')
    else:
        st.info('Found in supplier invoices, with no matching catalog record. This does not establish that the product is new.')
    full = item_history(history, key)
    if full.empty:
        st.info('No matching invoice lines for this product in the imported data. Similar products and other pack sizes are separate.')
        return
    st.subheader('Invoice history')
    with st.expander('Filter invoice history'):
        selected = st.date_input('Invoice period', value=(full.invoice_date.min().date(), full.invoice_date.max().date()),
            min_value=full.invoice_date.min().date(), max_value=full.invoice_date.max().date(),
            key='invoice_lookup_period_' + key)
        suppliers = st.multiselect('Supplier', sorted(full.supplier.unique()), key='invoice_lookup_suppliers_' + key)
    if len(selected) != 2:
        st.info('Choose both a start and end date.')
        return
    current = full[full.invoice_date.between(*map(pd.Timestamp, selected))]
    if suppliers:
        current = current[current.supplier.isin(suppliers)]
    if current.empty:
        st.info('No invoices match this period and supplier. Adjust the filters above.')
        return
    summary = purchase_summary(current)
    latest = summary['latest']
    if latest is not None:
        with st.container(border=True):
            st.markdown('**Latest purchase in this selection**')
            st.write(f"{latest.invoice_date:%b %d, %Y} · {latest.supplier} · Invoice {latest.invoice_number}")
            st.write(fr"{latest.quantity} {latest.unit_of_measure} · \${latest.unit_cost} per invoice unit · Line total \${latest.extended_price}")
            st.caption(f'Supplier item {latest.product_number} · PPC / BPC {latest.ppc or "not supplied"}. Unit cost is the source price; the line total already includes source discounts and adjustments.')
    st.caption('Compare costs using the same units. CA = case; BO = bottle. PPC / BPC retains the supplier definition and may count bottles rather than retail multipacks; no case-to-retail conversion is assumed.')
    a,b,c = st.columns(3)
    a.metric('Invoices / credits', f"{summary['invoice_count']:,}")
    b.metric('Net line total', f"${summary['net_total']:,.2f}", help='Sum of final source line amounts, including credit lines. Not confirmed payments.')
    c.metric('Credit / return lines', str(summary['credit_lines']))
    view = history_export(current)
    st.dataframe(table_page(view, 'invoice_lookup_history'), hide_index=True, width='stretch')
    st.download_button('Download product invoice history', lambda: csv_bytes(view),
        'product_invoice_history.csv', 'text/csv', key='invoice_lookup_download', on_click='ignore')
    # Drill down without changing Purchases filters or mixing product variants.
    with st.expander('See the full invoice'):
        invoice_ids = current.invoice_id.drop_duplicates().tolist()
        def invoice_label(invoice_id):
            row = current[current.invoice_id.eq(invoice_id)].iloc[0]
            return f'{row.invoice_date:%b %d, %Y} · {row.supplier} · {row.invoice_number}'
        invoice_key = choice_key('invoice_lookup_document_'+key,invoice_ids)
        chosen = st.selectbox('Invoice', invoice_ids, format_func=invoice_label, key=invoice_key)
        detail = history[history.invoice_id.eq(chosen)].sort_values('line_number')
        st.dataframe(table_page(history_export(detail), 'invoice_lookup_document_lines'), hide_index=True, width='stretch')
        st.caption('Full-invoice lines above include other products. Product totals and the download remain limited to your selected item.')
    with st.expander('Unit-cost history'):
        groups = current[['supplier', 'unit_of_measure', 'ppc']].fillna('').drop_duplicates()
        choices = [tuple(row) for row in groups.itertuples(index=False, name=None)]
        group_key = choice_key('invoice_lookup_cost_group_'+key,choices)
        chosen_group = st.selectbox('Supplier, invoice unit and source pack', choices,
            format_func=lambda g:f'{g[0]} · {g[1]} · PPC / BPC {g[2] or "not supplied"}',
            key=group_key)
        supplier, unit, ppc = chosen_group
        chart_rows = current[current.supplier.eq(supplier) & current.unit_of_measure.eq(unit) & current.ppc.fillna('').eq(ppc)].copy()
        positive = pd.Series([number(q) is not None and number(q)>0 and number(a) is not None and number(a)>=0
                              for q,a in zip(chart_rows.quantity,chart_rows.extended_price)], index=chart_rows.index, dtype=bool)
        chart_rows = chart_rows.loc[positive]
        chart_rows['Source unit cost'] = chart_rows.unit_cost.map(lambda v:float(number(v)) if number(v) is not None else None)
        if chart_rows.empty:
            st.info('No positive purchase lines for this unit and pack selection.')
        else:
            chart = alt.Chart(chart_rows).mark_circle(color='#3ba6f1', size=70).encode(
                x=alt.X('invoice_date:T', title=None), y=alt.Y('Source unit cost:Q', title=f'USD / {unit}', scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip('invoice_date:T', title='Date'),alt.Tooltip('invoice_number:N',title='Invoice'),alt.Tooltip('Source unit cost:Q',format='$,.4f')])
            st.altair_chart(chart.properties(height=220), width='stretch')
        st.caption('Source unit prices before line-level discounts and adjustments. Credits are excluded from this chart and remain in the history table.')
