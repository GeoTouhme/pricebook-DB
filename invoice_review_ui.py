"""Streamlit invoice review page; parsing never writes purchases."""
import base64
from collections import defaultdict
from contextlib import closing
import hashlib
import json
import sqlite3
from decimal import Decimal
import logging
import pandas as pd
import streamlit as st
from dashboard_data import DATABASE
from purchase_matching import pack_upc_or_blank
from invoice_review import (LINE_FIELDS, ACTIONS, EXTRACTION_VERSION, blank_line, extract_document,
    from_csv, classify_lines, validate_review, save_review, review_decision_errors, decimal_text)


def pending_items(database=DATABASE):
    with closing(sqlite3.connect(database)) as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_candidates'").fetchone()
        if not exists:return pd.DataFrame()
        return pd.read_sql_query('''SELECT c.retail_upc,c.description,c.supplier_product_number,c.status,
            s.name AS supplier,i.invoice_number,i.invoice_date FROM catalog_candidates c
            JOIN invoice_reviews r ON r.id=c.review_id JOIN purchase_invoices i ON i.id=r.invoice_id
            JOIN suppliers s ON s.id=i.supplier_id ORDER BY c.id DESC''',db)


def open_purchases():
    st.session_state.navigation='Purchases'


def show_saved_receipt(receipt,key="last_saved"):
    st.success(f"Saved invoice {receipt['invoice_number']} · {receipt['supplier']} · ${receipt['total']:,.2f}")
    st.caption(f"Purchase record #{receipt['invoice_id']} · {receipt['line_count']} lines · "
        f"{receipt['new_items']} new items pending catalog setup. Inventory is unchanged.")
    st.button('View in Purchases',on_click=open_purchases,key=key+'_view')



def render_invoice_review(database=None):
    database=database or DATABASE
    st.caption('Upload → check invoice lines → review product matches → save invoice')
    feedback=st.empty()
    receipt=st.session_state.get('last_invoice_save')
    if receipt:
        st.caption('Last successful save')
        show_saved_receipt(receipt)
    with st.expander('Confirmed new items awaiting catalog setup'):
        pending=pending_items(database)
        if pending.empty:st.info('No confirmed new items yet.')
        else:
            st.dataframe(pending,hide_index=True,width='stretch')
            st.download_button('Download new-item list',pending.to_csv(index=False).encode('utf-8-sig'),
                'new_items.csv','text/csv')
        st.caption('Confirmed new items stay on this list until retail pricing and catalog setup are completed. Saving an invoice does not mark goods received.')
    with st.expander('Previously reviewed invoices and original documents'):
        with closing(sqlite3.connect(database)) as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='invoice_reviews'").fetchone()
            saved=db.execute('''SELECT r.id,r.filename,i.invoice_number,i.invoice_date,s.name
                FROM invoice_reviews r JOIN purchase_invoices i ON i.id=r.invoice_id
                JOIN suppliers s ON s.id=i.supplier_id ORDER BY r.id DESC''').fetchall() if exists else []
            if saved:
                selected_review=st.selectbox('Saved invoice',saved,format_func=lambda r:f'{r[4]} · {r[2]} · {r[3]}')
                original=db.execute('SELECT document FROM invoice_reviews WHERE id=?',(selected_review[0],)).fetchone()[0]
                st.download_button('Download saved original',original,selected_review[1],key='saved_original')
            else:st.caption('No invoices have been saved through review yet.')
    uploaded=st.file_uploader('Upload an invoice PDF or Fintech CSV',type=['pdf','csv'])
    if uploaded is None:
        st.info('Choose a PDF to start. Text-based tables can be extracted locally. Scanned or unfamiliar layouts may need manual entry; a Fintech CSV is also supported.')
        return
    payload=uploaded.getvalue()
    digest=hashlib.sha256(payload).hexdigest()
    document_key=f'{digest}:{EXTRACTION_VERSION}'
    if st.session_state.get('review_document')!=document_key:
        try:extracted=extract_document(payload,uploaded.name)
        except Exception as exc:
            st.error(f'Could not read this document: {exc}')
            return
        st.session_state.review_document=document_key
        st.session_state.review_extracted=extracted
        st.session_state.pop('review_preview',None)
    extracted=st.session_state.review_extracted
    for warning in extracted['warnings']:st.warning(warning)
    defaults={'supplier':'','retailer':'Balport Liquor Store','customer_id':'','store_id':'000001',
              'invoice_number':'','invoice_date':'','due_date':'','invoice_total':''}
    token=document_key
    if extracted['kind']=='csv':
        groups=defaultdict(list)
        for r in extracted['records']:
            key=tuple(r[k] for k in ['Vendor Name','Retailer Name','Customer ID','Store ID','Invoice Number','Invoice Date'])
            groups[key].append(r)
        selected=st.selectbox('Invoice in this export',list(groups),
            format_func=lambda k:f'{k[0]} · {k[4]} · {k[5]}')
        try:defaults,raw_lines=from_csv(groups[selected])
        except (ValueError,KeyError) as exc:
            st.error(str(exc))
            return
        token+=hashlib.sha256(json.dumps(selected).encode()).hexdigest()[:12]
    else:
        defaults.update(extracted.get('header',{}))
        raw_lines=extracted['lines'] or [blank_line()]
        st.download_button('Download original PDF',payload,uploaded.name,'application/pdf')
        if st.checkbox('Show PDF beside the review'):
            # A fixed PDF data URI is the only embedded content; extracted text is never HTML.
            encoded=base64.b64encode(payload).decode('ascii')
            st.markdown(f'<iframe src="data:application/pdf;base64,{encoded}" width="100%" height="550"></iframe>',unsafe_allow_html=True)
        with st.expander('Extracted text'):
            st.text(extracted['text'] or 'No readable text found.')
    if receipt and receipt['token']==token:
        st.info('This invoice is saved. Open Purchases to see it, or choose a different invoice to continue.')
        return
    st.subheader('1. Check invoice details')
    left,right=st.columns(2)
    header={}
    labels={'supplier':'Supplier','retailer':'Retailer','customer_id':'Customer account ID',
        'store_id':'Store ID','invoice_number':'Invoice number','invoice_date':'Invoice date (YYYY-MM-DD)',
        'due_date':'Due date (YYYY-MM-DD, optional)','invoice_total':'Invoice total (credits negative)'}
    with closing(sqlite3.connect(database)) as db:
        supplier_names={row[0] for row in db.execute('SELECT name FROM suppliers')}
    if defaults['supplier']:supplier_names.add(defaults['supplier'])
    for index,(field,label) in enumerate(labels.items()):
        with left if index%2==0 else right:
            if field=='supplier':
                options=['Choose a supplier',*sorted(supplier_names),'Add new supplier']
                chosen=st.selectbox(label,options,index=options.index(defaults[field]) if defaults[field] else 0,
                    key=f'{token}_supplier_picker')
                header[field]=(st.text_input('New supplier name',key=f'{token}_new_supplier').strip()
                    if chosen=='Add new supplier' else '' if chosen=='Choose a supplier' else chosen)
            else:
                header[field]=st.text_input(label,value=defaults[field] or '',key=f'{token}_{field}').strip()
    st.caption('Supplier spelling should match purchase history. Use the invoice date from the document, not the upload date.')
    st.subheader('2. Check the invoice lines')
    st.caption('Matching uses PACK UPC, normalized to 12 digits by padding or removing only extra leading zeros. CASE UPC is retained for reference. Missing or invalid PACK UPC needs review. Edit extracted values, paste spreadsheet cells, or add rows. Keep UPCs and supplier codes as text. Remove subtotal/footer rows. Quantity and unit cost retain their invoice units; extended_price is the final line amount. Empty adjustments and discount mean zero.')
    edited=st.data_editor(pd.DataFrame(raw_lines,columns=[field for field in LINE_FIELDS if field!='upc']).fillna('').astype(str),
        num_rows='dynamic',hide_index=True,width='stretch',key=f'{token}_source_lines',
        column_config={field:st.column_config.TextColumn('PACK UPC (as supplied)' if field=='pack_upc' else field.replace('_',' ').title()) for field in LINE_FIELDS if field!='upc'})
    raw_records=edited.fillna('').to_dict('records')
    records=[r for r in raw_records if any(str(v).strip() for v in r.values())]
    for row in records:row['upc']=pack_upc_or_blank(row['pack_upc'])
    signature=hashlib.sha256(json.dumps({'header':header,'lines':records},sort_keys=True).encode()).hexdigest()
    if st.button('Check for new items',type='primary'):
        try:
            normalized,difference=validate_review(header,records)
            with st.spinner('Comparing catalog and purchase history…'):
                classified=classify_lines(normalized,header['supplier'],database)
            st.session_state.review_preview={'signature':signature,'rows':classified,'difference':str(difference)}
        except (ValueError,ArithmeticError) as exc:st.error(str(exc))
    preview=st.session_state.get('review_preview')
    if not preview or preview['signature']!=signature:
        st.info('Complete the details and lines, then check for new items. Changes require a fresh check before saving.')
        return
    st.subheader('3. Review product matches')
    result=pd.DataFrame(preview['rows'])
    cols=st.columns(5)
    for col,status in zip(cols,['Existing item','Previously purchased','Possible match','Potential new item','Unreadable code']):
        col.metric(status,int(result.status.eq(status).sum()))
    st.caption('The normalized UPC comes only from PACK UPC. CASE UPC is never substituted. Supplier history and name suggestions still require review. Previously purchased means the item was bought before but still needs a catalog link. Purchase history distinguishes previously purchased items from catalog matches. A possible match is a suggestion, not a link. Confirm new items with a retail UPC; case barcodes and supplier codes are preserved separately.')
    st.dataframe(result[['product_number','upc','pack_upc','case_upc','description','quantity','unit_cost','unit_of_measure','ppc',
        'extended_price','status','purchase_history','reason','suggestions']],hide_index=True,width='stretch',
        column_config={'upc':st.column_config.TextColumn('PACK UPC (12 digits)'),
            'pack_upc':st.column_config.TextColumn('Original PACK UPC'),
            'case_upc':st.column_config.TextColumn('CASE UPC (reference)')})
    st.download_button('Download match report',result.to_csv(index=False).encode('utf-8-sig'),
        'invoice_match_review.csv','text/csv')
    decision_frame=result[['description','status','action','confirmed_upc','remember_mapping']].copy()
    decision_frame.insert(0,'Line',range(1,len(decision_frame)+1))
    decisions=st.data_editor(decision_frame,
        hide_index=True,width='stretch',key=f'{token}_{signature}_decisions',
        disabled=['Line','description','status'],column_config={
            'action':st.column_config.SelectboxColumn('Decision',options=ACTIONS,required=True),
            'confirmed_upc':st.column_config.TextColumn('Confirmed retail UPC'),
            'remember_mapping':st.column_config.CheckboxColumn('Remember supplier + pack mapping')})
    st.caption('Link existing product: enter its exact catalog UPC. Confirm new item: add it to the pending catalog list. Keep unlinked: import without a product link. Remember mapping applies only to existing products with supplier item codes and this same unit/pack. Press Enter or leave the cell to apply an edit; the save checklist updates below.')
    with st.expander('Search existing catalog UPCs'):
        with closing(sqlite3.connect(database)) as db:
            products=pd.read_sql_query('SELECT p.upc,p.name,p.size,d.name AS department FROM products p JOIN departments d ON d.id=p.department_id',db)
        term=st.text_input('Find a product by UPC or name',key=f'{token}_find')
        if term:
            mask=products.upc.str.contains(term,regex=False,case=False)|products.name.str.contains(term,regex=False,case=False)
            st.dataframe(products.loc[mask,['upc','name','size','department']].head(100),hide_index=True)
    st.subheader('4. Save invoice')
    reviewed=[{**line,**decision} for line,decision in zip(preview['rows'],decisions.to_dict('records'))]
    errors=review_decision_errors(reviewed,set(products.upc))
    if errors:
        st.warning(f"{len(errors)} of {len(reviewed)} lines need attention before this invoice can be saved.")
        st.dataframe(pd.DataFrame(errors),hide_index=True,width='stretch')
    else:
        st.success(f'All {len(reviewed)} line decisions are ready.')
    difference=Decimal(preview['difference'])
    if difference:
        st.warning('Invoice total minus line totals: '+preview['difference']+'. Check fees, missing lines, and rounding.')
        acknowledge=st.checkbox('I reviewed and accept any difference between invoice and line totals',key=f'{signature}_difference')
    else:
        acknowledge=False
        st.caption('Invoice and line totals match.')
    checked=st.checkbox('I checked this invoice and every line against the original document',key=f'{signature}_checked')
    blockers=[]
    if errors:blockers.append(f'{len(errors)} lines need a valid decision or UPC (see step 4)')
    if difference and not acknowledge:blockers.append('acknowledge the difference between invoice and line totals')
    if not checked:blockers.append('tick the invoice review confirmation')
    previous_error=st.session_state.get('review_save_error')
    if previous_error and previous_error['signature']==signature:
        feedback.error('Invoice was not saved: '+previous_error['message'])
        st.error('Invoice was not saved: '+previous_error['message'])
    elif blockers:
        feedback.info('Not saved yet: '+'; '.join(blockers)+'.')
    else:
        feedback.info('Ready to save. Click Save reviewed invoice in step 4.')
    if blockers:st.info('To enable Save: '+'; '.join(blockers)+'.')
    if st.button('Save reviewed invoice',type='primary',disabled=bool(blockers),
                 help='Resolve the checklist above before saving.' if blockers else 'Save this invoice and its reviewed product decisions.'):
        try:
            with st.spinner('Saving invoice…'):
                saved=save_review(payload,uploaded.name,header,reviewed,acknowledge,database)
        except Exception as exc:
            if not isinstance(exc,(ValueError,ArithmeticError,sqlite3.Error)):
                logging.exception('Unexpected error saving reviewed invoice')
            message=str(exc) or type(exc).__name__
            st.session_state.review_save_error={'signature':signature,'message':message}
            feedback.error('Invoice was not saved: '+message)
            st.error('Invoice was not saved: '+message)
        else:
            st.session_state.last_invoice_save={**saved,'token':token,'invoice_number':header['invoice_number'],
                'supplier':header['supplier'],'total':float(decimal_text(header['invoice_total'],'Invoice total')),
                'line_count':len(reviewed)}
            st.session_state.pop('review_save_error',None)
            st.session_state.pop('review_preview',None)
            st.cache_data.clear()
            feedback.success(f"Saved invoice {header['invoice_number']}. It is now in Purchases.")
            show_saved_receipt(st.session_state.last_invoice_save,key='saved_now')
