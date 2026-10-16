from safe_exports import csv_bytes
"""Sales overview focused on the selected reporting period."""
import altair as alt
import pandas as pd
import streamlit as st
from dashboard_data import SALES_DEPARTMENT_GROUPS, filter_sales_departments, sales_coverage
from sales_chart import chart_periods
from non_moving import non_moving_products
from table_ui import table_page


def render_overview(sales, products):
    if sales.empty:
        st.info('No sales reports yet. Import a sales report to get started.')
        return
    first, latest = sales.sale_date.min().date(), sales.sale_date.max().date()
    left, middle, right = st.columns([1.3, 1.3, 1])
    with left:
        selected = st.date_input('Date range', value=(max(first, latest.replace(day=1)), latest),
            min_value=first, max_value=latest, key='sales_dates')
    with middle:
        departments = st.multiselect('Sales departments',
            [*SALES_DEPARTMENT_GROUPS, *sorted(sales.department.unique())])
    with right:
        measure = st.selectbox('Sales measure', ['Sales $', 'Scan Sales'], key='sales_measure',
            help='Separate POS report fields. They are not added together; neither is verified net revenue.')
    if not isinstance(selected, (tuple, list)) or len(selected) != 2:
        st.info('Choose a start and end date.')
        return
    start, end = map(pd.Timestamp, selected)
    period = sales[sales.sale_date.between(start, end)].copy()
    reported_days = period.sale_date.nunique()
    expected_days = (end - start).days + 1
    status = f'{reported_days} of {expected_days} dates reported'
    if reported_days < expected_days:
        st.warning(f'{status}. Missing dates are not zero sales.')
    else:
        st.caption(status + (f' · {latest:%b %d} may be partial' if end.date() == latest else ''))
    current = filter_sales_departments(period, departments)
    with st.expander('Report details and filters'):
        scope = st.radio('Include', ['All report rows', 'Matched products only', 'Unmatched / internal rows'],
            horizontal=True, key='sales_scope')
        st.caption('Sales $ and Scan Sales are separate POS fields. Amounts may include fees, lottery, tax and cash back; they are not confirmed net merchandise revenue.')
        for selection in departments:
            if selection in SALES_DEPARTMENT_GROUPS:
                st.caption(selection + ': ' + ', '.join(sorted(SALES_DEPARTMENT_GROUPS[selection])))
        st.dataframe(sales_coverage(sales), hide_index=True, width='stretch')
    if scope == 'Matched products only':
        current = current[current.matched_upc.notna()]
    elif scope == 'Unmatched / internal rows':
        current = current[current.matched_upc.isna()]
    column = 'sales_cents' if measure == 'Sales $' else 'scan_sales_cents'
    total = int(current[column].sum())
    main, average = st.columns(2)
    main.metric('Reported sales' if measure == 'Sales $' else 'Reported scan sales', f'${total / 100:,.2f}',
        help='Selected POS report amount before any unverified adjustments. This is not a profit figure.')
    average.metric('Average per reported day', f'${total / 100 / reported_days:,.2f}' if reported_days else '—',
        help='Selected amount divided by dates present in the report. Missing dates are excluded; partial dates may affect the average.')
    if current.empty:
        st.info('No sales rows match these filters.')
    else:
        st.subheader('Sales over time')
        grouping = st.selectbox('Chart detail', ['Auto', 'Daily', 'Weekly', 'Monthly'],
            key='sales_chart_detail',
            help='Auto shows days for up to 31 days, weeks for up to 180 days, and months for longer ranges.')
        # Null dates remain gaps, never invented zero-sale observations.
        daily = current.groupby('sale_date')[column].sum() / 100
        daily = daily.reindex(pd.date_range(start, end, freq='D')).rename(measure)
        daily.index.name = 'Date'
        coverage = pd.Series(daily.index.isin(period.sale_date.unique()), index=daily.index)
        interval, chart_data = chart_periods(daily, coverage, grouping)
        st.caption(f'{interval} totals · Only dates within your selected range are included. '
                   'Missing reports are excluded; edge periods may be partial. Tap a bar for dates and reporting coverage.')
        chart = alt.Chart(chart_data).mark_bar(color='#2563eb', cornerRadiusEnd=2,
            size=max(2, min(18, 220 / len(chart_data)))).encode(
            x=alt.X('Start:T', title=None,
                axis=alt.Axis(format='%b %d', tickCount=4, labelAngle=0, labelOverlap=True)),
            y=alt.Y('Amount:Q', title=measure, axis=alt.Axis(format='~s', tickCount=4)),
            tooltip=[alt.Tooltip('Start:T', title='From', format='%b %d, %Y'),
                     alt.Tooltip('End:T', title='Through', format='%b %d, %Y'),
                     alt.Tooltip('Amount:Q', title=measure, format='$,.2f'),
                     alt.Tooltip('Coverage:N', title='Reports')]
        ).properties(height=280)
        st.altair_chart(chart, width='stretch')
        left, right = st.columns(2)
        with left:
            st.subheader('Top departments')
            grouped = (current.groupby('department')[column].sum() / 100).nlargest(10)
            frame = grouped.rename(measure).reset_index()
            chart = alt.Chart(frame).mark_bar(color='#2563eb', cornerRadiusEnd=3).encode(
                x=alt.X(f'{measure}:Q', title=measure),
                y=alt.Y('department:N', sort='-x', title=None, axis=alt.Axis(labelLimit=170)),
                tooltip=[alt.Tooltip('department:N', title='Department'), alt.Tooltip(f'{measure}:Q', format='$,.2f')])
            st.altair_chart(chart.properties(height=300), use_container_width=True)
        with right:
            st.subheader('Top products')
            top = current[current.matched_upc.notna()].groupby('matched_upc')[column].sum().nlargest(10).reset_index()
            top = top.merge(products[['upc', 'name']], left_on='matched_upc', right_on='upc')
            if top.empty:
                st.info('No catalog-linked products in this selection.')
            else:
                top[measure] = top[column] / 100
                top['label'] = top['name']
                duplicates = top['name'].duplicated(keep=False)
                top.loc[duplicates, 'label'] += ' · ' + top.loc[duplicates, 'upc']
                chart = alt.Chart(top).mark_bar(color='#2563eb', cornerRadiusEnd=3).encode(
                    x=alt.X(f'{measure}:Q', title=measure),
                    y=alt.Y('label:N', sort='-x', title=None, axis=alt.Axis(labelLimit=180)),
                    tooltip=[alt.Tooltip('name:N', title='Product'), alt.Tooltip('upc:N', title='UPC'), alt.Tooltip(f'{measure}:Q', format='$,.2f')])
                st.altair_chart(chart.properties(height=300), use_container_width=True)
            st.caption('Products with exact catalog UPC matches.')
    with st.expander('Sales data and download'):
        a, b = st.columns(2)
        a.metric('Report rows', f'{len(current):,}')
        b.metric('Rows linked to products', f'{current.matched_upc.notna().mean():.1%}' if len(current) else '—')
        export = current.drop(columns=['import_id']).rename(columns={'sales_cents': 'Sales cents', 'scan_sales_cents': 'Scan Sales cents'})
        if st.checkbox('Show sales table', key='show_sales_table'):
            st.dataframe(table_page(export, 'sales_preview'), hide_index=True, width='stretch')
        st.download_button('Download filtered sales', lambda: csv_bytes(export),
            file_name='filtered_sales.csv', mime='text/csv', key='filtered_sales', on_click='ignore')
    st.subheader('Non-moving items · review before reordering')
    st.caption(f'No positive recorded quantity, Sales $, or Scan Sales from {start:%b %d, %Y} '
               f'to {end:%b %d, %Y}, using exact catalog UPC matches. '
               'Department filters use current catalog departments. This review is independent of the sales measure and report-row filter.')
    if not reported_days:
        st.info('No reports in this date range. Import sales reports before reviewing non-moving items.')
        return
    unmatched = period.matched_upc.isna().sum()
    st.warning(f'{reported_days} of {expected_days} dates reported; {unmatched:,} report rows have no catalog match. '
               'Missing reports or UPC mismatches can hide sales. New or unavailable items may not have had a chance to sell. '
               'Price-book stock has no confirmed count date; check physical stock and availability before changing orders.')
    stocked_only = st.checkbox('Only items with positive price-book stock', value=True,
                               key='non_moving_stocked')
    term = st.text_input('Find a non-moving item', placeholder='Product name or UPC',
                         key='non_moving_search').strip()
    candidates = non_moving_products(sales, products, start, end, departments)
    if stocked_only:
        candidates = candidates[candidates.stock_number.gt(0)]
    if term:
        candidates = candidates[candidates['name'].str.contains(term, case=False, regex=False, na=False)
                                | candidates.upc.str.contains(term, regex=False, na=False)]
    st.caption(f'{len(candidates):,} items to review · Last sale is based on available reports through {end:%b %d, %Y}.')
    if candidates.empty:
        st.info('No non-moving items match these filters.')
    else:
        view = candidates[['name', 'pricebook_stock', 'last_sale', 'days_since_sale',
                           'history', 'upc', 'size', 'department']].rename(columns={
            'name': 'Product', 'size': 'Size', 'upc': 'UPC', 'department': 'Department',
            'pricebook_stock': 'Price-book stock', 'last_sale': 'Last recorded sale',
            'days_since_sale': 'Days since recorded sale', 'history': 'Review reason'})
        st.dataframe(table_page(view, 'non_moving'), hide_index=True, width='stretch',
                     column_config={'Last recorded sale': st.column_config.DateColumn(format='MMM D, YYYY')})
        st.download_button('Download reorder review', lambda: csv_bytes(view),
                           file_name='non_moving_items.csv', mime='text/csv', key='non_moving_download', on_click='ignore')
