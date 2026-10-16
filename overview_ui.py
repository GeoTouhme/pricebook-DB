"""Sales overview focused on the selected reporting period."""
import altair as alt
import pandas as pd
import streamlit as st
from dashboard_data import SALES_DEPARTMENT_GROUPS, filter_sales_departments, sales_coverage


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
        st.subheader('Daily sales')
        # Null dates remain gaps, never invented zero-sale observations.
        daily = current.groupby('sale_date')[column].sum() / 100
        daily = daily.reindex(pd.date_range(start, end, freq='D')).rename(measure)
        daily.index.name = 'Date'
        st.bar_chart(daily, y_label=measure, color='#2563eb', height=280)
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
        st.dataframe(export, hide_index=True, width='stretch')
        st.download_button('Download filtered sales', export.to_csv(index=False).encode('utf-8-sig'),
            file_name='filtered_sales.csv', mime='text/csv', key='filtered_sales')
