"""Pricebook dashboard. Run with streamlit run dashboard.py."""
from datetime import date
import pandas as pd
import streamlit as st
from dashboard_data import DATABASE, load_data, reconcile, sales_coverage

st.set_page_config(page_title='Balport · Store dashboard',page_icon='📊',layout='wide')
st.markdown('''<style>
.block-container {padding-top:2rem;max-width:1500px;}
[data-testid="stMetric"] {background:#f1f5f9;border-radius:12px;padding:16px;}
[data-testid="stMetricLabel"], [data-testid="stMetricValue"] {color:#172554;}
</style>''',unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def cached_data(stamp):
    return load_data()

if not DATABASE.exists():
    st.error('Database is missing. Follow the database build steps in README.md.')
    st.stop()
data = cached_data(DATABASE.stat().st_mtime_ns)
sales, products, inventory, invoices, lines = [data[k] for k in
    ['sales','products','inventory','invoices','purchase_lines']]

st.sidebar.title('BALPORT')
st.sidebar.caption('Store performance & purchasing')
page = st.sidebar.radio('Navigate',['Overview','Products','Inventory','Purchases','Data quality'])
st.sidebar.divider()
st.sidebar.caption('Data is read from your local database. Import files using the repository import commands, then refresh.')
if st.sidebar.button('Refresh data'):
    st.cache_data.clear()
    st.rerun()
st.title(page)


def money(cents):
    return f'${cents/100:,.2f}'


def table(frame, label, key):
    st.dataframe(frame,hide_index=True,width='stretch')
    st.download_button(label,frame.to_csv(index=False).encode('utf-8-sig'),
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
    st.caption('Daily POS report · reported amounts, with unmatched and internal entries clearly separated')
    st.warning('Coverage is incomplete: January–April and August 13–31 are missing. October 15 may be partial. Missing dates are not zero sales.')
    current=dates(sales,'sale_date','sales_dates')
    departments=st.multiselect('Sales departments',sorted(sales.department.unique()))
    if departments:
        current=current[current.department.isin(departments)]
    scope=st.radio('Include',['All report rows','Matched products only','Unmatched / internal rows'],horizontal=True)
    if scope=='Matched products only':
        current=current[current.matched_upc.notna()]
    elif scope=='Unmatched / internal rows':
        current=current[current.matched_upc.isna()]
    cols=st.columns(4)
    cols[0].metric('Reported Sales $',money(current.sales_cents.sum()))
    cols[1].metric('Reported Scan Sales',money(current.scan_sales_cents.sum()))
    cols[2].metric('Report rows',f'{len(current):,}')
    cols[3].metric('Rows linked to products',f'{current.matched_upc.notna().mean():.1%}' if len(current) else '—')
    st.caption('Sales $ and Scan Sales are distinct source fields. These totals are not confirmed net merchandise revenue. All rows can include fees, lottery, tax, and cash back; currency is not explicitly supplied by the reports.')
    if current.empty:
        st.info('No sales rows match these filters.')
    else:
        daily=current.groupby('sale_date')[['sales_cents','scan_sales_cents']].sum()/100
        daily=daily.rename(columns={'sales_cents':'Sales $','scan_sales_cents':'Scan Sales'})
        st.subheader('Daily reported sales')
        # Reindex with nulls: gaps are absent observations, not zero amounts.
        daily=daily.reindex(pd.date_range(current.sale_date.min(),current.sale_date.max()))
        daily.index.name='Date'
        st.bar_chart(daily,y_label='Reported amount ($)')
        left,right=st.columns(2)
        with left:
            st.subheader('Sales by department · top 15')
            grouped=(current.groupby('department').sales_cents.sum()/100).sort_values(ascending=False).head(15)
            st.bar_chart(grouped,horizontal=True,x_label='Reported Sales $')
        with right:
            st.subheader('Top products · exact matches')
            top=current[current.matched_upc.notna()].groupby('matched_upc').sales_cents.sum().nlargest(15).reset_index()
            top=top.merge(products[['upc','name']],left_on='matched_upc',right_on='upc')
            top['Sales $']=top.sales_cents/100
            st.dataframe(top[['upc','name','Sales $']],hide_index=True,width='stretch')
        export=current.drop(columns=['import_id']).rename(columns={'sales_cents':'Sales cents','scan_sales_cents':'Scan Sales cents'})
        with st.expander('View and export filtered sales'):
            table(export,'Download filtered sales','filtered_sales')

elif page == 'Products':
    st.caption('Price book catalog · UPCs remain text, including leading zeros')
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
    st.caption('Price is for price_qty units; source cost is for cost_qty units. Zero costs are not evidence of free goods. No profit estimate is inferred.')
    if not current.empty:
        chosen=st.selectbox('Product history',current.upc.tolist(),format_func=lambda u: f'{u} · {products.loc[products.upc==u,"name"].iloc[0]}')
        history=sales[sales.matched_upc==chosen]
        st.subheader('Daily product sales · exact UPC matches')
        if history.empty:
            st.info('No linked sales rows for this product. This does not establish zero sales.')
        else:
            daily=history.groupby('sale_date').sales_cents.sum()/100
            st.bar_chart(daily.rename('Reported Sales $'))
        purchase_history=lines[lines.matched_upc==chosen].merge(invoices[['id','invoice_date','supplier','invoice_number']],left_on='invoice_id',right_on='id')
        if not purchase_history.empty:
            st.subheader('Purchase history')
            st.dataframe(purchase_history[['invoice_date','supplier','invoice_number','quantity','unit_of_measure','unit_cost','ppc','extended_price']],hide_index=True)

elif page == 'Inventory':
    st.caption('Website snapshots beside source price-book stock · no inferred physical inventory')
    st.warning('Website stock is mostly 100 and may represent defaults. Purchase quantities are not confirmed receipts. These sources do not establish current physical stock.')
    snapshot=st.selectbox('Website snapshot date',sorted(inventory.snapshot_date.unique(),reverse=True))
    current=inventory[inventory.snapshot_date==snapshot].copy()
    current=search(current,['website_upc','name'],'inventory_search')
    category=st.selectbox('Website category',['All categories',*sorted(inventory.category.dropna().unique())])
    if category!='All categories':
        current=current[current.category==category]
    cols=st.columns(3)
    cols[0].metric('Website items',f'{len(current):,}')
    cols[1].metric('Unmatched items',f'{current.matched_upc.isna().sum():,}')
    cols[2].metric('Stock reported as 100',f'{current.stock.eq("100").sum():,}')
    view=current.merge(products[['upc','pricebook_stock']],left_on='matched_upc',right_on='upc',how='left')
    view=view[['website_upc','name','category','subcategory','status','stock','pricebook_stock','matched_upc']]
    table(view,'Download inventory comparison','inventory_comparison')
    st.caption('Website date comes from the export filename. The price book has no confirmed stock observation date. Stock values are displayed as supplied, including negatives.')

elif page == 'Purchases':
    st.caption('Fintech invoices and credits · invoice headers counted once')
    current=dates(invoices,'invoice_date','purchase_dates')
    suppliers=st.multiselect('Suppliers',sorted(invoices.supplier.unique()))
    if suppliers:
        current=current[current.supplier.isin(suppliers)]
    cols=st.columns(4)
    cols[0].metric('Invoice totals incl. credits',money(current.total_cents.sum()))
    cols[1].metric('Invoices / credits',f'{len(current):,}')
    cols[2].metric('Negative-total documents',f'{(current.total_cents<0).sum():,}')
    cols[3].metric('Suppliers',current.supplier.nunique())
    st.caption('These are invoice amounts, not confirmed payments. Invoice dates cover January–September; completeness is not established. Costs and pack sizes require mapping before margins can be calculated.')
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
        st.caption('Unit costs and extended prices retain sub-cent precision. PPC is shown as supplied; no case-to-unit conversion is assumed. Discounts and adjustments are already separate source fields and are not added again.')
        flagged=reconcile(current,lines)
        with st.expander(f'Reconciliation flags ({len(flagged)})'):
            if flagged.empty:
                st.success('Invoice totals and exact decimal line sums agree for these documents.')
            else:
                table(flagged,'Download reconciliation flags','reconciliation')

else:
    st.caption('Coverage, source files, and unresolved product links')
    cols=st.columns(3)
    cols[0].metric('Unmatched sales rows',f'{sales.matched_upc.isna().sum():,}')
    cols[1].metric('Unmatched purchase lines',f'{lines.matched_upc.isna().sum():,}')
    cols[2].metric('Unmatched website items',f'{inventory.matched_upc.isna().sum():,}')
    st.subheader('Sales date coverage')
    st.dataframe(sales_coverage(sales),hide_index=True,width='stretch')
    st.caption('Coverage is checked from January 1 through the latest imported sales date. October 15 may be partial. Present dates do not prove every transaction was exported.')
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
