from safe_exports import csv_bytes
"""Pricebook dashboard. Run with streamlit run dashboard.py."""
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st
from sidebar_style import sidebar_css
from animated_number import install_animated_numbers
from theme_style import install_theme_support
from chart_animation import install_chart_animations
from dashboard_data import (DATABASE, load_data, reconcile, sales_coverage,
                            SALES_DEPARTMENT_GROUPS, filter_sales_departments)

LOGO = Path(__file__).resolve().parent / 'logojpg.jpg'
st.set_page_config(page_title='Bal-Port Liquors · Store dashboard',
                   page_icon=str(LOGO) if LOGO.is_file() else 'B', layout='wide')
from auth import require_login
require_login()

st.markdown('''<style>
.block-container {padding-top:2rem;max-width:1500px;}
[data-testid="stMetric"] {background:var(--dashboard-card, #f1f5f9);border-radius:12px;padding:16px;}
[data-testid="stMetricLabel"], [data-testid="stMetricValue"] {color:var(--dashboard-text, #172554);}
</style>''',unsafe_allow_html=True)

install_animated_numbers()
install_theme_support()
install_chart_animations()

@st.cache_data(show_spinner=False)
def cached_data(stamp):
    return load_data()

if not DATABASE.exists():
    st.error('Database is missing. Follow the database build steps in README.md.')
    st.stop()
data = cached_data(DATABASE.stat().st_mtime_ns)
sales, products, inventory, invoices, lines = [data[k] for k in
    ['sales','products','inventory','invoices','purchase_lines']]

navigation = ['Overview', 'Products', 'Inventory', 'Purchases',
              'New Items Review', 'Data quality', 'Data imports', 'Delivery platforms']
def toggle_sidebar():
    st.session_state.sidebar_pinned = not st.session_state.get('sidebar_pinned', False)


st.markdown(sidebar_css(st.session_state.get('sidebar_pinned', False)), unsafe_allow_html=True)
with st.sidebar:
    st.markdown('<div class="sidebar-brand"><span class="sidebar-monogram">B.</span>'
                '<span class="sidebar-brand-name">Bal-Port Liquors'
                '<small>Store dashboard</small></span></div>', unsafe_allow_html=True)
    pinned = st.session_state.get('sidebar_pinned', False)
    st.button('Unpin sidebar' if pinned else 'Pin sidebar',
              icon=':material/left_panel_close:' if pinned else ':material/left_panel_open:',
              key='sidebar_toggle', on_click=toggle_sidebar, width='stretch',
              help='Pin the menu open or return to the compact icon rail.')
    st.divider()
    page = st.radio('Navigate', navigation,
        label_visibility='collapsed', key='navigation')
    with st.container(key='sidebar_details'):
        st.divider()
        with st.expander('Data summary'):
            st.caption(f'{len(products):,} catalog products · {len(invoices):,} invoices / credits')
            if not sales.empty:
                st.caption(f'Sales reports: {sales.sale_date.min():%b %d, %Y} – {sales.sale_date.max():%b %d, %Y}')
            st.caption('For missing dates and unmatched products, see Data quality.')
        if st.button('Refresh data', width='stretch',
                     help='Reload the latest imports.'):
            st.cache_data.clear()
            st.rerun()
st.title(page)


def money(cents):
    return f'${cents/100:,.2f}'


def table(frame, label, key):
    labels = {'upc':'UPC', 'name':'Product', 'size':'Size', 'department':'Department',
        'price_qty':'Price quantity', 'cost_qty':'Cost quantity', 'pricebook_stock':'Price-book stock',
        'website_upc':'Website UPC', 'matched_upc':'Catalog UPC', 'source_upc':'Source UPC',
        'category':'Category', 'subcategory':'Subcategory', 'status':'Status', 'stock':'Website stock',
        'product_number':'Supplier item', 'pack_upc':'PACK UPC', 'description':'Product',
        'quantity':'Quantity', 'unit_of_measure':'Unit', 'unit_cost':'Price per invoice unit',
        'ppc':'Units per pack', 'extended_price':'Line total', 'adjustments_cents':'Adjustments (cents)',
        'discount_cents':'Discount (cents)', 'invoice_date':'Invoice date', 'supplier':'Supplier',
        'invoice_number':'Invoice number', 'due_date':'Due date', 'item_count':'Lines', 'id':'Record ID'}
    st.dataframe(frame,hide_index=True,width='stretch',
        column_config={field:st.column_config.Column(label) for field,label in labels.items() if field in frame})
    st.download_button(label,csv_bytes(frame),
        file_name=f'{key}.csv',mime='text/csv',key=key)


def dates(frame,column,key):
    if frame.empty:
        return frame
    selected=st.date_input('Date range',value=(frame[column].min().date(),frame[column].max().date()),
        min_value=frame[column].min().date(),max_value=frame[column].max().date(),key=key)
    if not isinstance(selected,(tuple,list)) or len(selected)!=2:
        st.info('Choose both a start and end date.')
        st.stop()
    return frame[frame[column].between(pd.Timestamp(selected[0]),pd.Timestamp(selected[1]))].copy()


def search(frame,columns,key):
    term=st.text_input('Search UPC or product name',key=key).strip()
    if not term:
        return frame
    mask=pd.Series(False,index=frame.index)
    for column in columns:
        mask |= frame[column].fillna('').astype(str).str.contains(term,case=False,regex=False)
    return frame[mask].copy()


if page == 'Overview':
    from overview_ui import render_overview
    render_overview(sales, products)

elif page == 'Products':
    st.caption('Catalog prices and purchase history')
    current=search(products,['upc','name'],'product_search')
    department=st.selectbox('Catalog department',['All departments',*sorted(products.department.unique())])
    if department!='All departments':
        current=current[current.department==department]
    a,b,c=st.columns(3)
    a.metric('Products shown',f'{len(current):,}')
    b.metric('Departments',current.department.nunique())
    c.metric('Zero source costs',f'{(current.cost_cents==0).sum():,}')
    display=current.copy()
    display['Price $']=display.price_cents/100
    display['Source cost $']=display.cost_cents/100
    table(display[['upc','name','size','department','Price $','price_qty','Source cost $','cost_qty','pricebook_stock']],
          'Download catalog','catalog')
    st.caption('Prices and costs apply to the quantities shown. A zero source cost means cost needs review.')
    if not current.empty:
        product_names=products.set_index('upc')['name'].to_dict()
        chosen=st.selectbox('Product history',current.upc.tolist(),format_func=lambda u: f'{u} · {product_names[u]}')
        history=sales[sales.matched_upc==chosen]
        st.subheader('Daily product sales · exact UPC matches')
        if history.empty:
            st.info('No sales linked to this UPC. Unmatched sales may be excluded.')
        else:
            daily=history.groupby('sale_date').sales_cents.sum()/100
            st.bar_chart(daily.rename('Reported Sales $'))
        purchase_history=lines[lines.matched_upc==chosen].merge(invoices[['id','invoice_date','supplier','invoice_number']],left_on='invoice_id',right_on='id')
        if not purchase_history.empty:
            st.subheader('Purchase history')
            st.dataframe(purchase_history[['invoice_date','supplier','invoice_number','quantity','unit_of_measure','unit_cost','ppc','extended_price']],hide_index=True)

elif page == 'Inventory':
    st.caption('Website stock and price-book stock')
    st.warning('Reported stock is not a verified physical count.')
    snapshot=st.selectbox('Website snapshot date',sorted(inventory.snapshot_date.unique(),reverse=True))
    current=inventory[inventory.snapshot_date==snapshot].copy()
    current=search(current,['website_upc','name'],'inventory_search')
    category=st.selectbox('Website category',['All categories',*sorted(inventory.category.dropna().unique())])
    if category!='All categories':
        current=current[current.category==category]
    cols=st.columns(3)
    cols[0].metric('Website items',f'{len(current):,}')
    cols[1].metric('Unmatched items',f'{current.matched_upc.isna().sum():,}')
    cols[2].metric('Stock reported as 100',f'{current.stock.eq("100").sum():,}',
        help='Repeated stock values may be website defaults. Check physical stock before using them to reorder.')
    view=current.merge(products[['upc','pricebook_stock']],left_on='matched_upc',right_on='upc',how='left')
    view=view[['website_upc','name','category','subcategory','status','stock','pricebook_stock','matched_upc']]
    table(view,'Download inventory comparison','inventory_comparison')
    st.caption('Snapshot date is recorded at import. Price-book stock has no confirmed count date.')

elif page == 'Purchases':
    st.caption('Supplier invoices and credits')
    current=dates(invoices,'invoice_date','purchase_dates')
    suppliers=st.multiselect('Suppliers',sorted(invoices.supplier.unique()))
    if suppliers:
        current=current[current.supplier.isin(suppliers)]
    cols=st.columns(4)
    cols[0].metric('Invoice totals incl. credits',money(current.total_cents.sum()))
    cols[1].metric('Invoices / credits',f'{len(current):,}')
    cols[2].metric('Negative-total documents',f'{(current.total_cents<0).sum():,}')
    cols[3].metric('Suppliers',current.supplier.nunique())
    st.caption('Invoice amounts include credits; they are not confirmed payments.')
    if current.empty:
        st.info('No invoices match these filters.')
    else:
        left,right=st.columns(2)
        with left:
            st.subheader('Monthly invoice totals')
            st.bar_chart(current.groupby(current.invoice_date.dt.strftime('%Y-%m')).total_cents.sum()/100,y_label='Amount ($)')
        with right:
            st.subheader('Suppliers · top 15')
            st.bar_chart((current.groupby('supplier').total_cents.sum()/100).nlargest(15),horizontal=True)
        display=current[['id','invoice_date','supplier','invoice_number','due_date','total_cents','item_count']].copy()
        display['Invoice total $']=display.pop('total_cents')/100
        table(display,'Download invoices','invoices')
        chosen=st.selectbox('Invoice details',current.id.tolist(),format_func=lambda i:
            f'{current.loc[current.id==i,"invoice_date"].iloc[0].date()} · {current.loc[current.id==i,"supplier"].iloc[0]} · {current.loc[current.id==i,"invoice_number"].iloc[0]}')
        detail=lines[lines.invoice_id==chosen][['product_number','source_upc','pack_upc','matched_upc','description','quantity','unit_of_measure','unit_cost','ppc','adjustments_cents','discount_cents','extended_price']]
        table(detail,'Download invoice lines','invoice_lines')
        st.caption('Prices and quantities retain invoice units and precision. Line totals already include source discounts and adjustments.')
        flagged=reconcile(current,lines)
        with st.expander(f'Reconciliation flags ({len(flagged)})'):
            if flagged.empty:
                st.success('Invoice totals and exact decimal line sums agree for these documents.')
            else:
                table(flagged,'Download reconciliation flags','reconciliation')

elif page == 'Delivery platforms':
    from delivery_ui import render_delivery
    render_delivery(DATABASE)

elif page == 'Data imports':
    from data_imports_ui import render_data_imports
    render_data_imports(DATABASE)

elif page == 'New Items Review':
    from invoice_review_ui import render_invoice_review
    render_invoice_review()

else:
    st.caption('Coverage, source files, and unresolved product links')
    cols=st.columns(3)
    cols[0].metric('Unmatched sales rows',f'{sales.matched_upc.isna().sum():,}')
    cols[1].metric('Unmatched purchase lines',f'{lines.matched_upc.isna().sum():,}')
    cols[2].metric('Unmatched website items',f'{inventory.matched_upc.isna().sum():,}')
    st.subheader('Sales date coverage')
    st.dataframe(sales_coverage(sales),hide_index=True,width='stretch')
    st.caption('Coverage starts January 1 and ends on the latest report date. The latest date may be partial; reported dates do not prove a complete day.')
    st.subheader('Unmatched sales')
    st.info('September–October includes rounded UPCs. Exact matching avoids speculative links. Blank codes and internal items are retained. Product-name matches require review.')
    unresolved=sales[sales.matched_upc.isna()].groupby(['source_upc','department','item'],dropna=False).agg(
        report_rows=('sales_cents','size'),reported_sales_cents=('sales_cents','sum')).reset_index()
    unresolved=search(unresolved,['source_upc','item'],'unmatched_search')
    table(unresolved,'Download unmatched sales','unmatched_sales')
    with st.expander('Unmatched purchase lines'):
        table(lines[lines.matched_upc.isna()].drop(columns=['id']), 'Download unmatched purchases','unmatched_purchases')
    with st.expander('Invoice reconciliation'):
        table(reconcile(invoices,lines),'Download all invoice flags','all_invoice_flags')
    st.subheader('Import history')
    st.dataframe(data['imports'][['source_name','imported_at','row_count','sha256']],hide_index=True,width='stretch')
    st.caption('The duplicate invoice file is counted once. The corrected September–October sales import replaced the previous version. The hourly report is not included: its reporting period is unknown. No profit or live-stock estimate is shown.')
