"""Exact metrics with explicit placement, transaction and settlement bases."""
import re
from collections import defaultdict
from decimal import Decimal
from delivery_reports import local_date, number, total


def in_period(row, field, start, end):
    day=local_date(row.get(field))
    return bool(day) and start<=day<=end


def summarize(data,start,end):
    result={}
    for platform,kind,day,sales,status in (
        ('DoorDash','dd_sales','Order placed date','Subtotal',lambda r:r.get('Is cancelled')=='false'),
        ('Uber Eats','ue_orders','Date Ordered','Ticket Size',lambda r:r.get('Completed?')=='1')):
        attempts=[r for r in data.get(kind,[]) if in_period(r,day,start,end)]
        rows=[r for r in attempts if status(r)]
        daily=defaultdict(lambda:{'sales':Decimal(0),'orders':0})
        for r in rows:
            d=local_date(r[day]); daily[d]['sales']+=number(r.get(sales)); daily[d]['orders']+=1
        result[platform]={'orders':len(rows),'sales':total(rows,sales),'average':total(rows,sales)/len(rows) if rows else None,
                          'daily':dict(daily),'available':kind in data,'observed':bool(attempts),'observed_days':len({local_date(r.get(day)) for r in attempts})}
    dd=result['DoorDash']; ue=result['Uber Eats']
    dledger=[r for r in data.get('dd_ledger',[]) if in_period(r,'Timestamp local date',start,end)]
    dd['ledger_available']='dd_ledger' in data
    dd['ledger_observed']=bool(dledger)
    dd['net']=total(dledger,'Net total')
    dd['pass_through']=sum((total(dledger,k) for k in ('Subtotal tax passed to merchant','Bottle deposit fee','Bottle deposit fee tax')),Decimal(0))
    dd['proceeds']=dd['net']-dd['pass_through']
    dd['bridge']=[('Item sales',total(dledger,'Subtotal')),
       ('Merchant discounts',total(dledger,'Customer discounts from marketing | (funded by you)')),
       ('Commission',total(dledger,'Commission')),
       ('Marketing fees',total(dledger,'Marketing fees | (including any applicable taxes)')),
       ('Platform discounts / credits',sum((total(dledger,k) for k in ('Customer discounts from marketing | (funded by DoorDash)','DoorDash marketing credit','Customer discounts from marketing | (funded by a third-party)','Third-party contribution')),Decimal(0))),
       ('Errors / adjustments',total(dledger,'Error charges')+total(dledger,'Adjustments'))]
    dd['canceled']=len({r['DD Order ID'].lower() for r in data.get('dd_cancel',[]) if in_period(r,'Order Placed Date',start,end)}) if 'dd_cancel' in data else None
    dh={r['Order ID'].lower() for r in data.get('dd_sales',[]) if in_period(r,'Order placed date',start,end) and r.get('Is cancelled')=='false'}
    df={r['DoorDash order ID'].lower() for r in dledger if r.get('Transaction type')=='Order'}
    dd['join_ok']=dh==df if dd['available'] and dd['ledger_available'] else None
    ratings=[number(r['Customer rating']) for r in data.get('dd_sales',[]) if in_period(r,'Order placed date',start,end) and r.get('Customer rating') not in ('','NULL',None)]
    dd['ratings']=(len(ratings),sum(ratings)/len(ratings) if ratings else None)
    history=[r for r in data.get('ue_orders',[]) if in_period(r,'Date Ordered',start,end)]
    ue['attempts']=len(history)
    ue['canceled']=sum(r.get('Order Status')=='canceled' for r in history)
    ue['failed']=sum(r.get('Order Status')=='failed' for r in history)
    ledger=[r for r in data.get('ue_ledger',[]) if in_period(r,'Order Date',start,end)]
    completed=[r for r in ledger if r.get('Order Status')=='Completed' and r.get('Workflow ID')]
    misc=[r for r in ledger if not r.get('Workflow ID')]
    ue['ledger_available']='ue_ledger' in data
    ue['ledger_observed']=bool(ledger)
    ue['proceeds']=total(completed,'Total payout')
    ue['discounts']=total(completed,'Offers on items (incl. tax)')-total(completed,'Tax On Offers on items')
    ue['bridge']=[('Item sales',total(completed,'Sales (excl. tax)')),('Merchant discounts',ue['discounts']),('Marketplace fees',total(completed,'Marketplace Fee'))]
    ue['ads']=total([r for r in misc if r.get('Other payments description')=='Ad Spend'],'Total payout')
    ue['unallocated']=total([r for r in misc if r.get('Other payments description')!='Ad Spend'],'Total payout')
    ue['noncompleted']=total([r for r in ledger if r.get('Workflow ID') and r.get('Order Status')!='Completed'],'Total payout')
    ue['ledger_net']=total(ledger,'Total payout')
    ue['refund_tax']=total([r for r in ledger if r.get('Order Status') in ('Refund','Refund Disputed')],'Tax on Chargeback Amount')
    ue['refund_net']=total([r for r in ledger if r.get('Order Status') in ('Refund','Refund Disputed')],'Total payout')
    uh={r['Workflow UUID'] for r in history if r.get('Completed?')=='1'}
    uf={r['Workflow ID'] for r in completed}
    ue['join_ok']=uh==uf if ue['available'] and ue['ledger_available'] else None
    items=[r for r in data.get('ue_items',[]) if in_period(r,'Order Date',start,end) and r.get('Order Status')=='Completed']
    ue['item_sales']=total(items,'Sales (excl. tax)')
    ue['item_join_ok']=ue['item_sales']==total(completed,'Sales (excl. tax)') if 'ue_items' in data and ue['ledger_available'] else None
    downtime=[r for r in data.get('ue_downtime',[]) if in_period(r,'Date',start,end)]
    ue['offline']=total(downtime,'Restaurant Offline') if downtime else None
    ue['scheduled']=total(downtime,'Menu Available') if downtime else None
    ur=[number(r.get('Rating Value')) for r in data.get('ue_ratings',[]) if in_period(r,'Date Ordered',start,end)]
    ue['ratings']=(len(ur),sum(ur)/len(ur) if ur else None)
    for platform,rows,name,value in [('Uber Eats',items,'Item Name','Sales (excl. tax)'),('DoorDash',data.get('dd_products',[]),'Item name','Gross sales')]:
        ranked=defaultdict(Decimal)
        for row in rows: ranked[row[name]]+=number(row.get(value))
        result[platform]['products']=sorted(ranked.items(),key=lambda x:x[1],reverse=True)[:5]
    return result


def common_period(data):
    """Observed overlap is a starting range, not proof of complete reporting."""
    bounds=[]
    for kind,field in [('dd_sales','Order placed date'),('ue_orders','Date Ordered')]:
        days=[local_date(r.get(field)) for r in data.get(kind,[]) if r.get(field)]
        if days: bounds.append((min(days),max(days)))
    if not bounds: return '2026-10-01','2026-10-14'
    start=max(x[0] for x in bounds);end=min(x[1] for x in bounds)
    return (start,end) if start<=end else bounds[0]


def quality_details(data):
    """Expose source contradictions without pooling duplicate quality events."""
    workbook_completed=[];workbook_refunds=[]
    for sheet in data.get('ue_accuracy',[]):
        header=None
        for cells in sheet.get('rows',[]):
            values=list(cells.values())
            if cells.get(next(iter(cells),''))=='Total number of completed orders':
                workbook_completed.append(values[1] if len(values)>1 else '')
            if 'Workflow ID' in values and 'Chargeback Amount' in values:
                header={re.sub(r'\d+$','',k):v for k,v in cells.items()}
            elif header:
                row={header.get(re.sub(r'\d+$','',k),k):v for k,v in cells.items()}
                if row.get('Workflow ID'):
                    workbook_refunds.append(row)
    return workbook_completed,workbook_refunds
