"""Delivery report ingestion. Source facts stay separate from POS and inventory.

Decimal arithmetic, bounded in-memory archives, explicit revisions, private provenance.
"""
import csv
import hashlib
import io
import json
import re
import sqlite3
import zipfile
from collections import defaultdict, Counter
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

MAX_BYTES = 30 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
SCHEMA = '''
CREATE TABLE IF NOT EXISTS delivery_sources (
 hash TEXT PRIMARY KEY, filename TEXT NOT NULL, original BLOB NOT NULL,
 imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS delivery_reports (
 hash TEXT PRIMARY KEY, kind TEXT NOT NULL, filename TEXT NOT NULL,
 coverage_start TEXT, coverage_end TEXT, row_count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS delivery_provenance (
 source_hash TEXT, report_hash TEXT, PRIMARY KEY(source_hash,report_hash));
CREATE TABLE IF NOT EXISTS delivery_facts (
 kind TEXT, store TEXT, fact_key TEXT, report_hash TEXT NOT NULL,
 raw_json TEXT NOT NULL, PRIMARY KEY(kind,store,fact_key));
'''
DD_BRIDGE = ['Subtotal','Subtotal tax passed to merchant','Bottle deposit fee','Bottle deposit fee tax',
 'Commission','Marketing fees | (including any applicable taxes)',
 'Customer discounts from marketing | (funded by you)',
 'Customer discounts from marketing | (funded by DoorDash)',
 'Customer discounts from marketing | (funded by a third-party)',
 'DoorDash marketing credit','Third-party contribution','Error charges','Adjustments']
UE_BRIDGE = ['Total Sales after Adjustments (incl tax)','Marketplace Fee',
 'Marketplace Facilitator Tax Adjustment','Marketplace Facilitator Tax']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def number(value):
    value = str(value or '').strip()
    if value in ('', 'NULL', 'None', 'N/A', '--'):
        return Decimal(0)
    try:
        result = Decimal(value.replace('$','').replace(',',''))
    except InvalidOperation as exc:
        raise ValueError(f'Invalid numeric value: {value[:40]}') from exc
    if not result.is_finite():
        raise ValueError('Non-finite numeric value')
    return result


def total(rows, key):
    return sum((number(r.get(key)) for r in rows), Decimal(0))


def local_date(value):
    """Never derive a local order day from an export timestamp or UTC date."""
    value = str(value or '').strip()
    if value in ('', 'NULL'):
        return ''
    if re.match(r'^\d{4}-\d\d-\d\d',value):
        return datetime.strptime(value[:10], '%Y-%m-%d').date().isoformat()
    for fmt in ('%m/%d/%y','%m/%d/%Y'):
        try:
            return datetime.strptime(value.split(' ')[0], fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f'Unrecognized local date: {value[:30]}')


def archive_members(payload):
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if len(entries) > 200 or sum(e.file_size for e in entries) > MAX_EXPANDED:
                raise ValueError('Archive exceeds member or expanded-size limit.')
            result = []
            for entry in entries:
                name = entry.filename.replace('\\','/')
                if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or ':' in name:
                    raise ValueError('Unsafe archive member path.')
                if entry.flag_bits & 1:
                    raise ValueError('Encrypted archives are unsupported.')
                if not entry.is_dir():
                    result.append((name, archive.read(entry)))
            return result
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError('Malformed or unsupported archive.') from exc


def csv_rows(payload):
    rows = list(csv.reader(io.StringIO(payload.decode('utf-8-sig'))))
    if not rows:
        raise ValueError('Empty document: CSV header required.')
    # Uber detailed financial exports can begin with a definitions row.
    if len(rows)>1 and 'Workflow ID' in [x.strip() for x in rows[1]]:
        rows = rows[1:]
    headers = [h.strip() for h in rows[0]]
    if len(set(headers)) != len(headers):
        raise ValueError('Duplicate CSV column names.')
    result = []
    for row in rows[1:]:
        if not any(row):
            continue
        if len(row) != len(headers):
            raise ValueError('CSV row has an unexpected number of columns.')
        result.append(dict(zip(headers, (v.strip() for v in row))))
    return headers, result


def classify(headers):
    h = set(headers)
    checks = [
      ('dd_ledger', {'Timestamp local date','DoorDash transaction ID','Bottle deposit fee'}),
      ('dd_sales', {'Order placed date','Is cancelled','Order ID'}),
      ('dd_payout', {'Payout status','Net total','Payout ID'}),
      ('dd_products', {'Item name','Gross sales','Start date'}),
      ('dd_cancel', {'Cancellation Category - Description','DD Order ID'}),
      ('dd_errors', {'Error Category','Item Name','DD Order ID'}),
      ('dd_wait', {'Avoidable Wait Time','DD Order ID'}),
      ('dd_promotion', {'Campaign ID','Type of promotion'}),
      ('dd_sponsored', {'Campaign ID','Impressions'}),
      ('dd_customers', {'OCL points balance','Order ID'}),
      ('dd_duplicate', {'DoorDash transaction ID','Transaction type'}),
      ('ue_mixed', {'Workflow ID','Item Name','Total payout'}),
      ('ue_ledger', {'Workflow ID','Total payout','Order Date'}),
      ('ue_payout', {'Payout reference ID','Order Count'}),
      ('ue_orders', {'Workflow UUID','Completed?','Date Ordered'}),
      ('ue_notfound', {'Item Total Lost Sales','Item Name'}),
      ('ue_downtime', {'Menu Available','Restaurant Offline'}),
      ('ue_availability', {'Start Time (Local)','Event Summary'}),
      ('ue_order_errors', {'Workflow UUID','Customer Refunded'}),
      ('ue_item_errors', {'Workflow UUID','Item Quantity Refunded'}),
      ('ue_ratings', {'Rating Value','Rating Type'}),
      ('ue_sku_ratings', {'Item Name','Rating'})]
    for kind, required in checks:
        if required <= h:
            return kind
    # Header-only SKU ratings still need retained provenance.
    if any('rating' in x.lower() for x in headers) and 'Item Name' in h:
        return 'ue_sku_ratings'
    raise ValueError('Unrecognized report schema; no data was saved.')


def read_xlsx(payload):
    """Read actual XLSX cell values with stdlib; never reinterpret CSV as XLSX."""
    members = dict(archive_members(payload))
    ns = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    def xml(name):
        data = members[name]
        if b'<!DOCTYPE' in data or b'<!ENTITY' in data:
            raise ValueError('Unsupported XML declarations.')
        return ET.fromstring(data)
    if 'xl/workbook.xml' not in members:
        raise ValueError('Not a valid XLSX workbook.')
    strings = []
    if 'xl/sharedStrings.xml' in members:
        strings = [''.join(e.itertext()) for e in xml('xl/sharedStrings.xml').findall('s:si',ns)]
    sheets=[]
    for name in sorted(members):
        if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', name):
            rows=[]
            for row in xml(name).findall('.//s:sheetData/s:row',ns):
                cells={}
                for c in row.findall('s:c',ns):
                    v=c.find('s:v',ns)
                    value=v.text if v is not None else ''.join(c.find('s:is',ns).itertext()) if c.find('s:is',ns) is not None else ''
                    if c.get('t')=='s': value=strings[int(value)]
                    cells[c.get('r')]=value
                rows.append(cells)
            sheets.append({'sheet':name,'rows':rows})
    return sheets


def coverage(filename, rows):
    match = re.search(r'(202\d-\d\d-\d\d)_(202\d-\d\d-\d\d)',filename)
    if match:
        return match.groups()
    starts=[r.get('Start date') for r in rows if r.get('Start date')]
    ends=[r.get('End date') for r in rows if r.get('End date')]
    return (min(starts),max(ends)) if starts and ends else (None,None)


def parse_upload(payload, filename):
    if not payload or len(payload)>MAX_BYTES:
        raise ValueError('Choose a nonempty report up to 30 MB.')
    suffix=Path(filename).suffix.lower()
    members=archive_members(payload) if suffix=='.zip' else [(filename,payload)]
    reports=[]
    for name, data in members:
        if suffix=='.xlsx':
            kind='ue_accuracy'; rows=read_xlsx(data); headers=[]
        elif name.lower().endswith('.csv'):
            headers,rows=csv_rows(data); kind=classify(headers)
        else:
            if suffix=='.zip': continue
            raise ValueError('Use CSV, ZIP or XLSX reports.')
        start,end=coverage(name,rows)
        canonical=json.dumps({'kind':kind,'headers':headers,'rows':rows},sort_keys=True,separators=(',',':'))
        reports.append(dict(hash=digest(canonical.encode()),kind=kind,filename=Path(name).name,
                            start=start,end=end,rows=rows))
    if not reports:
        raise ValueError('No supported reports in this upload.')
    return dict(hash=digest(payload),filename=Path(filename.replace('\\','/')).name,
                payload=payload,reports=reports)


def fact_identity(kind, row, report, index):
    store=row.get('Store ID') or row.get('Store UUID') or row.get('External Store ID') or row.get('Store') or 'unprovided'
    if kind=='dd_sales': key=row['Order ID'].lower()
    elif kind=='dd_ledger': key=row['DoorDash transaction ID'].lower()
    elif kind=='dd_payout': key=row['Payout ID']
    elif kind=='ue_orders': key=row['Workflow UUID']
    elif kind=='ue_ledger':
        if row.get('Workflow ID'):
            key='|'.join(row.get(k,'') for k in ('Workflow ID','Order Status','Order Completion time','Other payments description'))
        else:
            # Misc has no stable event ID: retain report scope and block ambiguous overlaps.
            key='misc|'+digest(json.dumps(row,sort_keys=True).encode())
    elif kind=='ue_payout': key='|'.join(row.get(k,'') for k in ('Payout reference ID','Payout Date'))
    elif kind=='ue_items':
        key='|'.join(row.get(k,'') for k in ('Workflow ID','Order Status','Item Name','External ID','Unit Sold By','Item Priced By'))
        # Repeated identical item lines must not collapse; occurrence index is added by caller.
    elif kind=='ue_downtime': key='|'.join(row.get(k,'') for k in ('Date','Restaurant Opened At'))
    else:
        key=f'{report["hash"]}|{index}'
    if not key or key=='|': raise ValueError(f'Missing stable identifier in {kind}.')
    return str(store),key


def facts(report):
    kind=report['kind']
    if kind=='dd_duplicate': return []
    result=[]; occurrences=defaultdict(int)
    # Item rows carry Workflow ID but store/date/status must come from their own header.
    contexts={}
    for index,original in enumerate(report['rows']):
        row=dict(original); target=kind
        if kind=='ue_mixed':
            if not row.get('Item Name'):
                if row.get('Store Name') and row.get('Workflow ID'):
                    contexts[row['Workflow ID']]=row
                continue
            context=contexts.get(row.get('Workflow ID'))
            if not context: raise ValueError('Item row has no matching workflow header.')
            for k in ('Store UUID','External Store ID','Order Date','Order Status','Currency Code'):
                row[k]=context.get(k,'')
            target='ue_items'
        currency=row.get('Currency') or row.get('Currency Code')
        if currency and currency not in ('USD','NULL'):
            raise ValueError('Only USD reports are supported.')
        # Reject malformed business-critical fields before transactional save.
        keys={'dd_sales':['Subtotal'],'dd_ledger':DD_BRIDGE+['Net total'],
              'ue_orders':['Ticket Size'],'ue_ledger':UE_BRIDGE+['Total payout','Offers on items (incl. tax)','Tax On Offers on items','Sales (excl. tax)','Chargeback Amount (incl. tax)'],
              'ue_items':['Sales (excl. tax)','Final Quantity'],
              'dd_products':['Gross sales'],'dd_payout':['Net total'],'ue_payout':['Total payout'],
              'dd_cancel':['Order Subtotal'],'dd_errors':['Error Charge'],
              'ue_notfound':['Item Total Lost Sales'],'ue_ratings':['Rating Value'],
              'ue_order_errors':['Customer Refunded','Chargeback Amount','Refund Not Covered by Merchant'],
              'ue_downtime':['Menu Available','Restaurant Online','Restaurant Offline']}.get(target,[])
        for k in keys: number(row.get(k))
        if target=='dd_sales': number(row.get('Customer rating'))
        if target=='ue_accuracy':
            header=None
            for cells in row.get('rows',[]):
                if 'Workflow ID' in cells.values() and 'Chargeback Amount' in cells.values():
                    header={re.sub(r'\d+$','',k):v for k,v in cells.items()}
                elif header:
                    for key,value in cells.items():
                        if header.get(re.sub(r'\d+$','',key)) in ('Chargeback Amount','Refund Not Covered by Merchant'):
                            number(value)
        if target=='dd_ledger' and total([row], 'Net total') != sum((number(row.get(k)) for k in DD_BRIDGE),Decimal(0)):
            raise ValueError('DoorDash financial row does not reconcile.')
        if target=='ue_ledger' and row.get('Order Status')=='Completed' and number(row.get('Total payout')) != sum((number(row.get(k)) for k in UE_BRIDGE),Decimal(0)):
            raise ValueError('Uber completed financial row does not reconcile.')
        for k in ('Order placed date','Timestamp local date','Date Ordered','Order Date','Date','Order Placed Date'):
            if row.get(k) and target not in ('dd_promotion','dd_sponsored'): local_date(row[k])
        store,key=fact_identity(target,row,report,index)
        if target=='ue_items' or target=='ue_ledger' and not row.get('Workflow ID'):
            occurrences[(store,key)]+=1; key+=f'|{occurrences[(store,key)]}'
        result.append((target,store,key,report['hash'],json.dumps(row,sort_keys=True)))
    return result


def connect_read(database):
    return sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True)


def existing_reports(db):
    try:
        return {r[0]:r[1:] for r in db.execute('SELECT hash,kind,coverage_start,coverage_end FROM delivery_reports')}
    except sqlite3.OperationalError:
        return {}


def assess(db, uploads):
    reports=existing_reports(db); preview=[]; conflicts=[]; pending={}
    try:
        known_misc=[json.loads(r[0]) for r in db.execute("SELECT raw_json FROM delivery_facts WHERE kind='ue_ledger'")]
    except sqlite3.OperationalError:
        known_misc=[]
    for upload in uploads:
        for report in upload['reports']:
            status='duplicate' if report['hash'] in reports else 'ready'
            incoming=facts(report)
            if status!='duplicate':
                # Aggregates without stable IDs cannot safely combine overlapping snapshots.
                unsafe=report['kind'] not in ('dd_sales','dd_ledger','dd_payout','dd_duplicate','ue_orders','ue_ledger','ue_mixed','ue_payout','ue_downtime')
                if unsafe:
                    for oldhash,(kind,start,end) in reports.items():
                        if kind==report['kind'] and (not start or not report['start'] or start<=report['end'] and report['start']<=end):
                            conflicts.append(f'{report["filename"]}: overlapping aggregate/support report; retain existing source or review a replacement separately.')
                for fact in incoming:
                    key=fact[:3]; raw=fact[4]
                    previous=pending.get(key)
                    if previous is None:
                        try:
                            found=db.execute('SELECT raw_json FROM delivery_facts WHERE kind=? AND store=? AND fact_key=?',key).fetchone()
                            previous=found[0] if found else None
                        except sqlite3.OperationalError: pass
                    if previous is not None and previous!=raw:
                        conflicts.append(f'{report["kind"]}: revised {fact[0]} fact {fact[2][:45]}; nothing will be overwritten.')
                    pending[key]=raw
                # Misc rows have no transaction IDs. Different snapshots sharing a date/description
                # are ambiguous; require explicit review rather than append invented events.
                if report['kind']=='ue_ledger':
                    old=known_misc
                    groups=lambda rs:{(r.get('Store UUID'),r.get('Order Date'),r.get('Other payments description')) for r in rs if not r.get('Workflow ID')}
                    shared=groups(old)&groups(report['rows'])
                    for group in shared:
                        group_rows=lambda rs:Counter(json.dumps(r,sort_keys=True) for r in rs if (r.get('Store UUID'),r.get('Order Date'),r.get('Other payments description'))==group and not r.get('Workflow ID'))
                        if not group_rows(report['rows'])<=group_rows(old):
                            conflicts.append('Uber miscellaneous events overlap without stable event identifiers; explicit source review required.')
                    known_misc.extend(r for r in report['rows'] if not r.get('Workflow ID') and (r.get('Store UUID'),r.get('Order Date'),r.get('Other payments description')) not in shared)
                reports[report['hash']]=(report['kind'],report['start'],report['end'])
            observed=[]
            for fact in incoming:
                row=json.loads(fact[4])
                field={'dd_sales':'Order placed date','dd_ledger':'Timestamp local date','ue_orders':'Date Ordered','ue_ledger':'Order Date','ue_items':'Order Date','ue_downtime':'Date'}.get(fact[0])
                if field and row.get(field): observed.append(local_date(row[field]))
            preview.append({'Observed local rows':f'{min(observed)} – {max(observed)}' if observed else 'not order/date-grained','Report':report['kind'],'File':report['filename'],'Rows':len(report['rows']),
                            'Coverage':f'{report["start"] or "not declared"} – {report["end"] or "not declared"}',
                            'Status':status,'Facts':len(incoming)})
    return {'reports':preview,'conflicts':sorted(set(conflicts))}


def preview_uploads(uploads,database):
    with closing(connect_read(database)) as db:
        result=assess(db,uploads)
        merged={}
        try:
            merged={(k,s,i):raw for k,s,i,raw in db.execute('SELECT kind,store,fact_key,raw_json FROM delivery_facts')}
        except sqlite3.OperationalError:
            pass
        for upload in uploads:
            for report in upload['reports']:
                for k,s,i,_,raw in facts(report): merged.setdefault((k,s,i),raw)
        proposed=defaultdict(list)
        for (kind,_,_),raw in merged.items(): proposed[kind].append(json.loads(raw))
        result['proposed']=dict(proposed)
        return result


def save_uploads(uploads,database):
    from data_imports import copy_database
    from uuid import uuid4
    with closing(sqlite3.connect(database)) as db:
        db.execute('BEGIN IMMEDIATE')
        result=assess(db,uploads)
        if result['conflicts']:
            db.rollback(); raise ValueError('\n'.join(result['conflicts']))
        folder=Path(database).parent/'backups'; folder.mkdir(exist_ok=True)
        backup=folder/f'before-delivery-{uuid4().hex}.sqlite3'
        copy_database(database,backup)
        try:
            # executescript would implicitly commit: execute DDL individually instead.
            for statement in SCHEMA.split(';'):
                if statement.strip(): db.execute(statement)
            for upload in uploads:
                db.execute('INSERT OR IGNORE INTO delivery_sources(hash,filename,original) VALUES(?,?,?)',
                           (upload['hash'],upload['filename'],upload['payload']))
                for report in upload['reports']:
                    fresh=db.execute('INSERT OR IGNORE INTO delivery_reports VALUES(?,?,?,?,?,?)',
                                     (report['hash'],report['kind'],report['filename'],report['start'],report['end'],len(report['rows']))).rowcount
                    db.execute('INSERT OR IGNORE INTO delivery_provenance VALUES(?,?)',(upload['hash'],report['hash']))
                    if fresh:
                        db.executemany('INSERT OR IGNORE INTO delivery_facts VALUES(?,?,?,?,?)',facts(report))
            db.commit()
        except Exception:
            db.rollback(); raise
    return dict(result,backup=str(backup))


def load_reports(database):
    with closing(connect_read(database)) as db:
        reports=existing_reports(db)
        if not reports: return {},[]
        rows=defaultdict(list)
        for kind,_,_ in reports.values():
            rows['ue_items' if kind=='ue_mixed' else kind]
        for kind,raw in db.execute('SELECT kind,raw_json FROM delivery_facts'):
            rows[kind].append(json.loads(raw))
        sources=[dict(kind=v[0],start=v[1],end=v[2]) for v in reports.values()]
    return dict(rows),sources
