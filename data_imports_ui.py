"""Dashboard CSV update flow."""
from datetime import date
import hashlib
import streamlit as st
from data_imports import preview_import, save_import


def render_data_imports(database):
    st.caption('Update the product catalog or add a dated website inventory snapshot.')
    receipt = st.session_state.get('data_import_receipt')
    if receipt:
        st.success(receipt)
    kind_label = st.selectbox('Upload type', ['Price book', 'Website inventory snapshot'])
    kind = 'pricebook' if kind_label == 'Price book' else 'website'
    if kind == 'pricebook':
        st.info('Use the same CSV export format as the original price book. Matching UPCs update product details, prices, costs, and price-book stock. New UPCs add products. Products absent from this file are retained.')
    else:
        st.info('Use the website inventory CSV export. Earlier snapshots remain available. Website stock is recorded separately from price-book stock; product prices and costs are unchanged.')
    snapshot = st.date_input('Snapshot date', value=date.today(), help='Choose the date represented by this export.') if kind == 'website' else None
    uploaded = st.file_uploader('Choose CSV export', type=['csv'], key='data_import_upload')
    if uploaded is None:
        return
    payload = uploaded.getvalue()
    snapshot_date = snapshot.isoformat() if snapshot else None
    token = (hashlib.sha256(payload).hexdigest(), kind, snapshot_date)
    if st.button('Validate and preview', type='primary'):
        st.session_state.pop('data_import_preview', None)
        try:
            with st.spinner('Checking every row against a temporary database copy…'):
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
        st.caption('Preview shows up to 50 rows. All rows are validated and imported.')
    confirmed = st.checkbox('I reviewed the upload type, preview, and snapshot date where applicable.', key=f'import_ack_{token}')
    if st.button('Save import', disabled=not confirmed, type='primary'):
        try:
            with st.spinner('Backing up the database and saving the upload…'):
                result = save_import(payload, uploaded.name, kind, database, snapshot_date)
            st.session_state.data_import_receipt = (
                'This file was already imported; no duplicate was added.' if result['status'] == 'already_imported'
                else f"Saved {result['rows']:,} rows from {uploaded.name}. Database backup created.")
            st.session_state.pop('data_import_preview', None)
            st.cache_data.clear()
            st.rerun()
        except Exception as exc:
            st.error(f'Import was not saved: {exc}')
