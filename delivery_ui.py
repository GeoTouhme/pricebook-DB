"""Owner-focused delivery charts and reviewed report upload."""
from datetime import date
from decimal import Decimal
import html
import io
import csv
import altair as alt
import pandas as pd
import streamlit as st
from delivery_reports import parse_upload, preview_uploads, save_uploads, load_reports, total
from delivery_metrics import summarize, common_period, quality_details

COLORS=alt.Scale(domain=['DoorDash','Uber Eats'],range=['#2563eb','#93c5fd'])


def prose(value):
    # Streamlit interprets paired dollar signs as LaTeX in Markdown text.
    return value.replace('$',r'\$')


def usd(value):
    return 'Not provided' if value is None else f'${value:,.2f}'


def bars(rows,x,y,color=None):
    frame=pd.DataFrame(rows)
    if frame.empty:
        st.caption('No data provided for this selection.'); return
    chart=alt.Chart(frame).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X(x,type='quantitative',title=None),y=alt.Y(y,type='nominal',sort=[r[y] for r in sorted(rows,key=lambda r:r[x],reverse=True)],title=None),
        tooltip=list(frame.columns))
    chart=chart.encode(color=alt.Color(color,scale=COLORS,legend=None)) if color else chart.encode(color=alt.value('#3b82f6'))
    label=chart.mark_text(align='right',dx=-5).encode(text=alt.Text(x,type='quantitative',format=',.2f' if x=='Sales ($)' else ',d'),color=alt.condition(alt.datum.Platform=='Uber Eats',alt.value('#172554'),alt.value('white')) if color else alt.value('white'))
    st.altair_chart((chart+label).properties(height=max(130,len(rows)*40)),use_container_width=True)


def waterfall(steps,final):
    running=Decimal(0); rows=[]
    for label,value in steps:
        end=running+value
        rows.append({'Step':label,'From':float(min(running,end)),'To':float(max(running,end)),'Change':float(value),'Label':usd(value)})
        running=end
    rows.append({'Step':'Proceeds','From':0.,'To':float(final),'Change':float(final),'Label':usd(final)})
    if running!=final:
        st.warning(f'Unallocated bridge difference: {usd(final-running)}. Review the source before relying on proceeds.')
    base=alt.Chart(pd.DataFrame(rows)).encode(y=alt.Y('Step:N',sort=[r['Step'] for r in rows],title=None))
    chart=base.mark_bar().encode(x=alt.X('From:Q',title='USD'),x2='To:Q',
        color=alt.condition(alt.datum.Change<0,alt.value('#93c5fd'),alt.value('#2563eb')),
        tooltip=['Step','Label'])
    labels=base.mark_text(align='right',dx=-5).encode(x='To:Q',text='Label:N',color=alt.condition(alt.datum.Change<=0,alt.value('#172554'),alt.value('white')))
    st.altair_chart((chart+labels).properties(height=len(rows)*44),use_container_width=True)


def upload_panel(database):
    with st.expander('Upload platform reports',expanded=False):
        st.caption('DoorDash ZIP · Uber Eats CSV / XLSX. Preview first; save creates a database backup. Reports remain separate from POS sales and inventory.')
        files=st.file_uploader('Select reports',type=['zip','csv','xlsx'],accept_multiple_files=True,key='delivery_uploads')
        if not files: return
        try:
            uploads=[parse_upload(f.getvalue(),f.name) for f in files]
            preview=preview_uploads(uploads,database)
        except (ValueError,UnicodeError,KeyError) as exc:
            st.error(f'Could not read reports: {exc}'); return
        signature=tuple(u['hash'] for u in uploads)
        if st.session_state.get('delivery_preview_hash')!=signature:
            st.session_state.delivery_preview_hash=signature
            st.session_state.delivery_approve=False
        st.dataframe(pd.DataFrame(preview['reports']),hide_index=True,width='stretch')
        bounds=common_period(preview['proposed'])
        proposed=summarize(preview['proposed'],*bounds)
        st.caption(f'Proposed observed overlap: {bounds[0]} – {bounds[1]} (existing data plus these uploads)')
        for platform,r in proposed.items():
            if r['available']:
                st.write(f'{platform}: {r["orders"]} completed orders · {usd(r["sales"])} sales')
            if r['join_ok'] is False:
                st.warning(platform+': order and financial coverage differ; review sources before saving.')
            if platform=='Uber Eats' and r['item_join_ok'] is False:
                st.warning('Uber item sales do not match the completed financial cohort.')
        for conflict in preview['conflicts']: st.error(conflict)
        st.caption('Dates shown here are declared report coverage; absent dates and header-only reports do not establish zero activity. Financial row reconciliation is checked during preview.')
        approved=st.checkbox('I reviewed the report types, coverage and duplicate/conflict results.',key='delivery_approve')
        if st.button('Save platform reports',disabled=not approved or bool(preview['conflicts']),type='primary'):
            try:
                with st.spinner('Saving reports and backup…'):
                    result=save_uploads(uploads,database)
                st.session_state.delivery_saved=f'Reports saved. Backup: {result["backup"]}'
                st.cache_data.clear(); st.rerun()
            except Exception as exc:
                st.error(f'Nothing was saved: {exc}')


def render_delivery(database):
    if st.session_state.get('delivery_saved'): st.success(st.session_state.delivery_saved)
    upload_panel(database)
    data,sources=load_reports(database)
    if not data:
        st.info('Upload the DoorDash sales/financial ZIPs and Uber Eats order history/financial CSVs to begin.'); return
    st.caption('Delivery sales only · kept separate from POS · America/Los_Angeles local order dates')
    platforms=st.multiselect('Platforms',['DoorDash','Uber Eats'],default=['DoorDash','Uber Eats'])
    bounds=common_period(data)
    selected=st.date_input('Order placement period',value=tuple(date.fromisoformat(d) for d in bounds),key='delivery_period')
    if len(selected)!=2 or not platforms: st.info('Choose two dates and at least one platform.'); return
    start,end=(d.isoformat() for d in selected)
    m=summarize(data,start,end)
    st.caption(f'{start} – {end} · Missing dates are unknown. Check source coverage before comparing unmatched days.')
    with st.expander('Coverage and source checks'):
        st.dataframe(pd.DataFrame(sources),hide_index=True,width='stretch')
        for p in platforms:
            r=m[p]
            st.write(f'{p}: completed order ↔ financial workflow check: '+('agrees' if r['join_ok'] else 'unavailable' if r['join_ok'] is None else 'MISMATCH — reporting coverage differs'))
        st.caption('Actual row dates can extend beyond filenames. Default date basis is local placement; DoorDash ledger uses local transaction date. Payouts below use settlement date. Header-only optional sources mean unavailable metrics.')
    # No pooled proceeds: their cohorts are different.
    for p in platforms:
        r=m[p]; st.subheader(p)
        st.caption(f'Operational dates with rows: {r["observed_days"]} of {(selected[1]-selected[0]).days+1} selected days. Totals cover observed rows.')
        cols=st.columns(4)
        cols[0].metric('Completed sales',usd(r['sales']) if r['observed'] else 'Not provided')
        cols[1].metric('Completed orders',str(r['orders']) if r['observed'] else 'Not provided')
        cols[2].metric('Average basket',usd(r['average']))
        cols[3].metric('Proceeds before product costs',usd(r['proceeds']) if r['ledger_observed'] else 'Not provided')
        st.caption('Proceeds basis: '+('local transaction dates, excluding passed-through tax and deposits.' if p=='DoorDash' else 'completed-order placement cohort, before date-based ads and miscellaneous events.'))
    overview,money,ops=st.tabs(['Performance','Money','Operations'])
    with overview:
        cols=st.columns(2)
        for col,field,label in [(cols[0],'sales','Sales ($)'),(cols[1],'orders','Orders')]:
            with col:
                st.subheader('Completed '+label.lower())
                bars([{'Platform':p,label:float(m[p][field])} for p in platforms if m[p]['observed']],label,'Platform','Platform')
        metric=st.radio('Daily trend',['Sales','Orders'],horizontal=True,key='delivery_trend')
        field='sales' if metric=='Sales' else 'orders'
        daily=[{'Date':d,'Platform':p,metric:float(v[field])} for p in platforms for d,v in m[p]['daily'].items()]
        if daily:
            chart=alt.Chart(pd.DataFrame(daily)).mark_bar().encode(x=alt.X('Date:O',title='Local order date',axis=alt.Axis(labelExpr='substring(datum.label, 5)',labelAngle=-45,labelOverlap=True)),xOffset='Platform:N',y=alt.Y(metric+':Q',stack=None),color=alt.Color('Platform:N',scale=COLORS),tooltip=['Date:N','Platform',alt.Tooltip(metric+':Q',format='$,.2f' if metric=='Sales' else ',d')]).properties(height=260)
            st.altair_chart(chart,use_container_width=True)
        st.caption('Only observed dates are plotted; gaps are not converted to zero.')
        for p in platforms:
            st.subheader(p+' · top products')
            if p=='DoorDash':
                scopes=[s for s in sources if s['kind']=='dd_products']
                st.caption('Full source product-mix scope · not filtered by the dates above. Aggregate rankings may include canceled sales; they are not a completed-order allocation.')
                st.caption('Product report periods: '+', '.join(f'{s["start"] or "undeclared"} – {s["end"] or "undeclared"}' for s in scopes))
            bars([{'Product':name,'Sales ($)':float(value)} for name,value in m[p]['products']],'Sales ($)','Product')
        out=io.StringIO(); writer=csv.writer(out);writer.writerow(['Platform','Local placement date','Completed orders','Sales USD'])
        for p in platforms:
            for d,v in sorted(m[p]['daily'].items()):writer.writerow([p,d,v['orders'],str(v['sales'])])
        st.download_button('Download daily totals',out.getvalue(),file_name='delivery-daily.csv',mime='text/csv')
        brief='<html><meta name="viewport" content="width=device-width"><title>Delivery summary</title><body style="font:18px system-ui;color:#172554"><h1>Delivery platforms</h1><p>'+html.escape(start+' – '+end)+'</p>'
        for p in platforms: brief+=f'<h2>{html.escape(p)}</h2><p>{usd(m[p]["sales"])} completed sales · {m[p]["orders"]} orders · {usd(m[p]["average"])} average basket</p>'
        brief+='<p>Sales before platform charges and product costs. Separate from POS totals. Print using your browser.</p></body></html>'
        st.download_button('Download printable summary',brief,file_name='delivery-owner-summary.html',mime='text/html')
    with money:
        st.caption('Proceeds are before inventory and operating costs. They are not profit or confirmed bank deposits.')
        for p in platforms:
            st.subheader(p)
            r=m[p]
            if not r['ledger_observed']: st.info('No detailed financial rows provided for this period.'); continue
            waterfall(r['bridge'],r['proceeds'])
            if p=='DoorDash':
                st.caption(prose(f'Passed-through tax / deposits: {usd(r["pass_through"])} · source transaction net: {usd(r["net"])}'))
            else:
                st.write(prose(f'Date-based ads: {usd(r["ads"])} · unallocated miscellaneous payouts: {usd(r["unallocated"])}'))
                st.caption(prose(f'Canceled, failed and refund/dispute events: {usd(r["noncompleted"])}. Explicit mixed-ledger net: {usd(r["ledger_net"])}. Net refund/dispute payouts: {usd(r["refund_net"])}; source chargeback-tax field: {usd(r["refund_tax"])}.'))
                if r['item_join_ok'] is False: st.warning('Item sales do not match the financial completed-order cohort; source coverage needs review.')
            if p=='Uber Eats':
                from delivery_metrics import in_period
                adjustments=[{'Local ledger date':row.get('Order Date'),'Description':row.get('Other payments description'),'Payout USD':row.get('Total payout'),'Allocation':'no workflow reference'} for row in data.get('ue_ledger',[]) if not row.get('Workflow ID') and in_period(row,'Order Date',start,end)]
                with st.expander('Date-based ads and unallocated events'):
                    st.dataframe(pd.DataFrame(adjustments),hide_index=True,width='stretch')
            payout_kind='dd_payout' if p=='DoorDash' else 'ue_payout'
            payout_value='Net total' if p=='DoorDash' else 'Total payout'
            rows=data.get(payout_kind,[])
            with st.expander(p+' settlement statements — separate date basis'):
                st.caption('Statement totals use their own settlement scope. No bank reconciliation is implied.')
                if rows:
                    st.dataframe(pd.DataFrame([{'Payout date':r.get('Payout date') or r.get('Payout Date'),'Statement total':str(r.get(payout_value)), 'Status':r.get('Payout status','reported')} for r in rows]),hide_index=True)
                else: st.info('Not provided')
    with ops:
        for p in platforms:
            r=m[p];st.subheader(p)
            st.metric('Canceled orders',r['canceled'] if r['canceled'] is not None and r['observed'] else 'Not provided')
            if p=='Uber Eats':
                st.metric('Failed orders',r['failed'] if r['observed'] else 'Not provided')
                st.caption(f'Observed attempted workflows: {r["attempts"] if r["observed"] else "not provided"}. Canceled and failed are separate; reports do not attribute all issues to the store.')
                st.metric('Scheduled offline minutes',str(r['offline']) if r['offline'] is not None else 'Not provided')
                st.caption('Scheduled menu time only; pause-event durations include time outside the schedule.')
                from delivery_metrics import in_period
                offline={}
                for row in data.get('ue_downtime',[]):
                    if in_period(row,'Date',start,end):
                        offline[row['Date']]=offline.get(row['Date'],Decimal(0))+Decimal(row.get('Restaurant Offline') or '0')
                if any(offline.values()):
                    bars([{'Date':d,'Minutes':float(n)} for d,n in offline.items() if n],'Minutes','Date')
            else: st.caption('Availability report: not provided.')
            count,rating=r['ratings'];st.caption(f'Ratings: {rating:.1f}/5 from {count} ratings' if rating is not None else 'Ratings: not provided for this period')
        if 'ue_notfound' in data:
            st.caption(f'Uber unavailable items, full source scope: {len(data["ue_notfound"])} item types · {usd(total(data["ue_notfound"],"Item Total Lost Sales"))} source-reported lost item sales. Not a unique order count or a cash loss.')
        with st.expander('Quality conflicts and definitions'):
            counts,workbook=quality_details(data)
            if counts:
                st.warning('Accuracy workbook completed-order denominators: '+', '.join(counts)+'. These have their own evaluation periods; do not mix them into the selected order-history cohort.')
            error_rows=data.get('ue_order_errors',[])
            if error_rows or workbook:
                st.write('Source refund allocation (full report scopes; repeated issues are not additive):')
                st.dataframe(pd.DataFrame([{'Source':source,'Merchant chargeback':str(total(rows,'Chargeback Amount')),'Not covered by merchant':str(total(rows,'Refund Not Covered by Merchant'))} for source,rows in [('Error CSV',error_rows),('Accuracy workbook',workbook)] if rows]),hide_index=True)
            st.write('Quality CSV and XLSX may repeat one issue with conflicting refund allocations. Keep finance refund and dispute events separately; quality amounts are not automatically unrecovered cash losses.')
            st.write('DoorDash product quantities and completed-order item counts differ in the supplied source. Promotion-attributed sales are not incremental sales. Missing ratings are unknown.')
            st.caption('Raw reports contain personal data and are stored privately with database backups. Only aggregated data appears on this page.')
    st.subheader('Actions to review')
    actions=st.columns(3)
    ue=m['Uber Eats'];dd=m['DoorDash']
    actions[0].info(prose(f'Review Uber promotions and ads: {usd(-ue["discounts"])} completed-order discounts and {usd(-ue["ads"])} date-based ads.' if ue['ledger_observed'] else 'Upload Uber detailed finance to review promotion and advertising charges.'))
    actions[1].info(f'Check late-night availability: {ue["offline"]} scheduled offline minutes in this period.' if ue['offline'] is not None else 'Upload Uber menu downtime to check scheduled availability.')
    actions[2].info(f'Improve stock accuracy: {dd["canceled"]} DoorDash cancellations in this period; {len(data.get("ue_notfound",[]))} Uber unavailable item types in the full report.' if dd['canceled'] is not None and dd['observed'] and 'ue_notfound' in data else 'Upload cancellation and unavailable-item reports to review stock accuracy.')
