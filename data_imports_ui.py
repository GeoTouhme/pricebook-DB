"""Dashboard CSV update flow."""
from datetime import date
import hashlib
import streamlit as st
from data_imports import preview_import, save_import


def render_data_imports(database):
    st.caption('Upload a price book or website stock snapshot.')
    receipt = st.session_state.get('data_import_receipt')
    if receipt:
        st.success(receipt)
    kind_label = st.selectbox('Upload type', ['Price book', 'Website inventory snapshot'])
    kind = 'pricebook' if kind_label == 'Price book' else 'website'
    if kind == 'pricebook':
        st.caption('Updates matching UPCs and adds new products. Products missing from this file stay in the catalog.')
        with st.expander('What changes in the catalog'):
            st.write('The price-book CSV updates source names, departments, sizes, prices, costs and price-book stock. Use the same columns as the original export.')
    else:
        st.caption('Adds a dated stock snapshot. Earlier snapshots remain available; catalog prices and costs stay unchanged.')
    snapshot = st.date_input('Snapshot date', value=date.today(), help='Choose the date represented by this export.') if kind == 'website' else None
    uploaded = st.file_uploader('Choose CSV export', type=['csv'], key='data_import_upload', help='Original CSV export format, up to 20 MB.')
    if uploaded is None:
        return
    payload = uploaded.getvalue()
    snapshot_date = snapshot.isoformat() if snapshot else None
    token = (hashlib.sha256(payload).hexdigest(), kind, snapshot_date)
    if st.button('Validate and preview', type='primary'):
        st.session_state.pop('data_import_preview', None)
        try:
            with st.spinner('Checking file…'):
                preview = preview_import(payload, uploaded.name, kind, database, snapshot_date)
            st.session_state.data_import_preview = (token, preview)
        except Exception as exc:
            st.error(f'Cannot import this CSV: {exc}')
    saved_preview = st.session_state.get('data_import_preview')
    if not saved_preview or saved_preview[0] != token:
        return
    preview = saved_preview[1]
    if preview['status'] == 'already_imported':
        st.info('This exact file has already been imported. No changes needed.')
        return
    st.subheader('Import preview')
    st.write(f"{preview['rows']:,} source rows validated.")
    if kind == 'pricebook':
        a, b = st.columns(2)
        a.metric('New products', preview['new_products'])
        b.metric('Products with changes', preview['updated_products'])
    else:
        st.write(f"{preview['matched']:,} exact catalog matches · {preview['unmatched']:,} unmatched website items")
        st.caption(f'Snapshot date: {snapshot_date}')
    if preview['sample']:
        st.dataframe(preview['sample'], hide_index=True, width='stretch')
        st.caption('First 50 rows shown. All rows will be imported.')
    confirmed = st.checkbox('I checked the preview and import details.', key=f'import_ack_{token}')
    if st.button('Save import', disabled=not confirmed, type='primary'):
        try:
            with st.spinner('Saving import…'):
                result = save_import(payload, uploaded.name, kind, database, snapshot_date)
            st.session_state.data_import_receipt = (
                'This file was already imported; no duplicate was added.' if result['status'] == 'already_imported'
                else f"Saved {result['rows']:,} rows from {uploaded.name}. Database backup created.")
            st.session_state.pop('data_import_preview', None)
            st.cache_data.clear()
            st.rerun()
        except Exception as exc:
            st.error(f'Import was not saved: {exc}')
