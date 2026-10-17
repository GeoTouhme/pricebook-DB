"""Local invoice extraction, conservative item matching, and atomic reviewed imports."""
from collections import defaultdict
from contextlib import closing
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import hashlib
import io
import json
import re
import sqlite3

from dashboard_data import ROOT, DATABASE
from import_invoices import HEADERS, cents, iso, numeric
from purchase_matching import normalize_pack_upc, pack_upc_or_blank

LINE_FIELDS = ['product_number','upc','description','quantity','unit_cost',
               'unit_of_measure','ppc','pack_upc','adjustments','discount','extended_price','case_upc']
CSV_FIELDS = dict(zip(LINE_FIELDS, ['Product Number','UPC Number','Product Description',
    'Quantity','Unit Cost','Unit of Measure','PPC','Pack UPC','Total Adjustments',
    'Total Discount','Extended Price']))
EXTRACTION_VERSION = 6
ACTIONS = ['Review needed','Link existing product','Confirm new item','Keep unlinked']


def normalize_header(value):
    return re.sub(r'[^a-z0-9]', '', (value or '').lower())

ALIASES = {
    'product_number':['product number','product no','item number','item code','sku'],
    'upc':['upc','upc number','barcode'],
    'description':['product description','description','item description','product'],
    'quantity':['quantity','qty'], 'unit_cost':['unit cost','cost','unit price'],
    'unit_of_measure':['unit of measure','uom','unit'], 'ppc':['ppc','pack size'],
    'pack_upc':['pack upc'], 'adjustments':['total adjustments','adjustments'],
    'discount':['total discount','discount'],
    'extended_price':['extended price','line total','extended amount','amount'],
}
ALIAS_LOOKUP = {normalize_header(alias):field for field,aliases in ALIASES.items() for alias in aliases}


def blank_line():
    return dict.fromkeys(LINE_FIELDS,'')


def extract_document(payload, filename):
    if len(payload) > 20*1024*1024:
        raise ValueError('Upload a document smaller than 20 MB')
    if not filename.lower().endswith('.pdf'):
        return _extract_document(payload, filename)
    if not payload.startswith(b'%PDF-'):
        raise ValueError('Choose a PDF or a Fintech CSV export')
    import subprocess
    import sys
    import os
    from pathlib import Path
    # Limit concurrency across sessions in this server process.
    if not _PDF_SLOTS.acquire(blocking=False):
        raise ValueError('Another PDF is being processed. Try again shortly.')
    try:
        env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
        completed = subprocess.run([sys.executable, str(Path(__file__).with_name('pdf_worker.py'))],
            input=payload, capture_output=True, timeout=60, env=env)
        if completed.returncode:
            raise ValueError('PDF exceeded processing limits or could not be read. Try a smaller PDF.')
        result = json.loads(completed.stdout)
        if 'error' in result:
            raise ValueError(result['error'])
        return result['result']
    except subprocess.TimeoutExpired as exc:
        raise ValueError('PDF processing exceeded 60 seconds. Split the document and try again.') from exc
    finally:
        _PDF_SLOTS.release()


import threading
_PDF_SLOTS = threading.BoundedSemaphore(1)


def _extract_document(payload, filename):
    """PDF tables require identifiable headers; unknown layouts never become invented lines."""
    if len(payload)>20*1024*1024:
        raise ValueError('Upload a document smaller than 20 MB')
    if filename.lower().endswith('.csv'):
        reader=csv.DictReader(io.StringIO(payload.decode('utf-8-sig'),newline=''))
        if reader.fieldnames!=HEADERS:
            raise ValueError('CSV must use the Fintech invoice export headers')
        records=list(reader)
        if not records:
            raise ValueError('The CSV has no invoice lines')
        return {'kind':'csv','records':records,'text':'','warnings':[]}
    if not filename.lower().endswith('.pdf') or not payload.startswith(b'%PDF-'):
        raise ValueError('Choose a PDF or a Fintech CSV export')
    import pdfplumber
    from fintech_pdf import extract_page, extract_header
    text=[]; lines=[]; warnings=[]; header={}
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        if len(pdf.pages)>100:
            raise ValueError('Upload at most 100 pages at a time')
        from breakthru_pdf import extract_invoice as extract_breakthru
        supplier_result=extract_breakthru(pdf)
        if supplier_result is not None:return supplier_result
        from mercaso_pdf import extract_invoice
        supplier_result=extract_invoice(pdf)
        if supplier_result is not None:return supplier_result
        for page in pdf.pages:
            page_text=page.extract_text() or ''
            text.append(page_text)
            fintech_lines=extract_page(page)
            if fintech_lines is not None:
                values=extract_header(page_text,page)
                if header.get('invoice_number') and values.get('invoice_number',header['invoice_number'])!=header['invoice_number']:
                    raise ValueError('This PDF contains multiple invoices; upload each invoice separately')
                header.update(values)
                lines.extend({**blank_line(),**line} for line in fintech_lines)
                continue
            for table in page.extract_tables():
                mapping=None
                for cells in table:
                    headers={i:ALIAS_LOOKUP.get(normalize_header(value)) for i,value in enumerate(cells)}
                    if {'description','quantity','extended_price'}.issubset(set(headers.values())):
                        mapping={i:field for i,field in headers.items() if field}
                        continue
                    if mapping:
                        line=blank_line()
                        for i,field in mapping.items():
                            if i<len(cells):line[field]=(cells[i] or '').replace('\n',' ').strip()
                        if any(line.values()):lines.append(line)
    content='\n\n'.join(text)
    if not content.strip():
        warnings.append('This PDF appears scanned or has no readable text. Enter the lines manually or use a Fintech CSV; OCR is not configured.')
    if not lines:
        warnings.append('No supported line table was found. Read the extracted text and enter the invoice lines below.')
    else:
        warnings.append('PDF table extraction is a draft. Check every line, totals, and identifiers against the original PDF; remove subtotals or repeated headers.')
    for line in lines:line['upc']=pack_upc_or_blank(line['pack_upc'])
    return {'kind':'pdf','lines':lines,'text':content,'warnings':warnings,'header':header}


def from_csv(records):
    first=records[0]
    for row in records:
        for field in ['Invoice Total','Item Count','Invoice Due Date']:
            if row[field]!=first[field]:
                raise ValueError('Conflicting invoice headers in CSV; check the source report')
    header={'supplier':first['Vendor Name'],'retailer':first['Retailer Name'],
        'customer_id':first['Customer ID'],'store_id':first['Store ID'],
        'invoice_number':first['Invoice Number'],'invoice_date':iso(first['Invoice Date']),
        'due_date':iso(first['Invoice Due Date']) or '', 'invoice_total':first['Invoice Total']}
    lines=[]
    for r in records:
        line={field:r[column] for field,column in CSV_FIELDS.items()}
        line['case_upc']=r['UPC Number'] if len(r['UPC Number'])==14 else ''
        line['upc']=pack_upc_or_blank(r['Pack UPC'])
        lines.append(line)
    return header,lines


def read_history(database=DATABASE):
    with closing(sqlite3.connect(database)) as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        products=[dict(zip(['upc','name'],r)) for r in db.execute('SELECT upc,name FROM products')]
        history=[dict(zip(['supplier','product_number','upc','pack_upc','matched_upc','description','unit_of_measure','ppc'],r))
            for r in db.execute('''SELECT s.name,l.product_number,l.source_upc,l.pack_upc,l.matched_upc,
                l.description,l.unit_of_measure,l.ppc FROM purchase_lines l
                JOIN purchase_invoices i ON i.id=l.invoice_id JOIN suppliers s ON s.id=i.supplier_id''')]
        mappings=[dict(zip(['supplier','product_number','unit_of_measure','ppc','upc'],r)) for r in db.execute('''SELECT s.name,m.product_number,m.unit_of_measure,m.ppc,m.upc
            FROM supplier_product_mappings m JOIN suppliers s ON s.id=m.supplier_id''')] if 'supplier_product_mappings' in tables else []
        candidates=[dict(zip(['retail_upc','description'],r)) for r in db.execute('SELECT retail_upc,description FROM catalog_candidates')] if 'catalog_candidates' in tables else []
    return products,history,mappings,candidates


def name_tokens(name):
    text=name.casefold()
    substitutions={r'\bp\s+noir\b':'pinot_noir',r'\bpinot\s+noir\b':'pinot_noir',
        r'\bpinot\s+grigio\b':'pinot_grigio',r'\bcab\s+sauv\b':'cabernet',
        r'\bcabernet\s+sauvignon\b':'cabernet',r'\bsauvignon\s+blanc\b':'sauvignon_blanc',
        r'\bred\s+blend\b':'red_blend',r'\bteq\b':'tequila',r'\bmarg\b':'margarita',
        r'\bstrwb\b':'strawberry',r'\blme\b':'lime'}
    for pattern,replacement in substitutions.items():text=re.sub(pattern,replacement,text)
    return re.findall(r'[a-z0-9_]+',text)


def compatible_name(source,candidate):
    source_words=name_tokens(source);target=set(name_tokens(candidate));words=set(source_words)
    if not source_words:return False
    brand=source_words[0]
    if len(brand)>=3 and brand not in target:return False
    varieties={'cabernet','merlot','pinot_noir','pinot_grigio','chardonnay',
               'sauvignon_blanc','red_blend','rose','rosé'}
    if words & varieties and target & varieties and words & varieties != target & varieties:return False
    flavors={'watermelon','strawberry','pineapple','peach','mango','apple','raspberry',
             'blueberry','coconut','cherry','grapefruit','orange','lemon','lime'}
    if target & flavors != words & flavors:return False
    return True


def classify_lines(lines,supplier,database=DATABASE):
    products,history,mappings,candidates=read_history(database)
    catalog={p['upc']:p['name'] for p in products}
    candidate_upcs={r['retail_upc'] for r in candidates}
    saved={(m['supplier'],m['product_number'],m['unit_of_measure'],m['ppc']):m['upc'] for m in mappings}
    word_index=defaultdict(set)
    for p in products:
        for word in set(re.findall(r'[a-z0-9]+',p['name'].casefold())):
            if len(word)>2:word_index[word].add(p['upc'])
    result=[]
    for line in lines:
        raw_pack=line.get('pack_upc','').strip()
        pack_error=''
        try:upc=normalize_pack_upc(raw_pack)
        except ValueError as exc:upc='';pack_error=str(exc)
        code=line['product_number'].strip()
        scope=(supplier,code,line['unit_of_measure'].strip(),line['ppc'].strip())
        prior=[r for r in history if (upc and pack_upc_or_blank(r['pack_upc'])==upc) or
               (code and r['supplier']==supplier and r['product_number']==code)]
        same_supplier=any(r['supplier']==supplier for r in prior)
        suggestions=set()
        for old in prior:
            if old['matched_upc'] and old['unit_of_measure']==line['unit_of_measure'] and old['ppc']==line['ppc']:
                suggestions.add(old['matched_upc'])
        if upc in catalog:suggestions.add(upc)
        mapped=saved.get(scope) if code else None
        conflict=mapped and upc in catalog and mapped!=upc
        if conflict:
            status='Possible match';reason='UPC conflicts with a confirmed supplier mapping';suggestions.update([mapped,upc]);match=''
        elif mapped:
            status='Existing item';reason='Confirmed supplier item and pack mapping';match=mapped
        elif upc in catalog:
            status='Existing item';reason='Exact normalized PACK UPC';match=upc
        else:
            match=''
            if not suggestions and line['description'].strip():
                name=line['description'].casefold()
                votes=defaultdict(int)
                for word in set(re.findall(r'[a-z0-9]+',name)):
                    for candidate in word_index.get(word,()):votes[candidate]+=1
                shortlist=sorted(votes,key=lambda u:(-votes[u],u))[:150]
                scores=sorted(((SequenceMatcher(None,name,catalog[u].casefold()).ratio(),u)
                    for u in shortlist if compatible_name(line['description'],catalog[u])),reverse=True)
                suggestions.update(u for score,u in scores[:3] if score>=0.72)
            if suggestions:
                status='Possible match';reason='Candidate only: confirm barcode, product, and pack size'
            elif not upc:
                status='Unreadable code';reason=pack_error or 'PACK UPC is missing; check the invoice'
            else:
                status='Potential new item';reason='No confirmed catalog match'
        if pack_error and not match:
            status='Unreadable code';reason=pack_error
        if prior and not match and not conflict and not pack_error:
            status='Previously purchased'
            reason='Seen in purchase history; retail catalog link needs confirmation'
        if not raw_pack:reason+='; PACK UPC is missing'
        if upc in candidate_upcs:
            if status=='Potential new item':status='Possible match'
            reason+='; already on the pending new-item list'
        if prior:history_label='Seen from this supplier' if same_supplier else 'Seen from another supplier'
        else:history_label='Not seen in imported purchase history'
        result.append({**line,'upc':upc,'status':status,'reason':reason,'purchase_history':history_label,
            'suggestions':'; '.join(f'{u} — {catalog[u]}' for u in sorted(suggestions) if u in catalog),
            'action':'Link existing product' if match else 'Review needed',
            'confirmed_upc':match,'remember_mapping':False})
    return result


def decimal_text(value,field):
    value=str(value).strip().replace('$','').replace(',','')
    if value.startswith('(') and value.endswith(')'):value='-'+value[1:-1]
    try:
        numeric(value)
    except (InvalidOperation,ValueError):
        raise ValueError(f'{field} must contain a number') from None
    return value


def validate_review(header,lines):
    for field in ['supplier','retailer','store_id','invoice_number','invoice_date','invoice_total']:
        if not str(header.get(field,'')).strip():raise ValueError(f'Missing {field}')
    date.fromisoformat(header['invoice_date'])
    if header.get('due_date'):date.fromisoformat(header['due_date'])
    total=cents(decimal_text(header['invoice_total'],'Invoice total'))
    if not lines:raise ValueError('Add at least one invoice line')
    normalized=[]
    for index,line in enumerate(lines,1):
        row={field:str(line.get(field,'') or '').strip() for field in LINE_FIELDS}
        if not row['description']:raise ValueError(f'Line {index}: description is required')
        for field in ['quantity','unit_cost','extended_price']:
            row[field]=decimal_text(row[field],f'Line {index} {field}')
        for field in ['adjustments','discount']:
            # Optional fees/discount fields are explicitly zero when left empty.
            row[field]=decimal_text(row[field] or '0',f'Line {index} {field}')
            cents(row[field])
        if not row['unit_of_measure']:raise ValueError(f'Line {index}: unit of measure is required')
        if row['ppc'] and Decimal(decimal_text(row['ppc'],'PPC'))<0:raise ValueError('PPC cannot be negative')
        row['upc']=pack_upc_or_blank(row['pack_upc'])
        normalized.append(row)
    difference=Decimal(total)/100-sum(Decimal(r['extended_price']) for r in normalized)
    return normalized,difference



def confirm_line_decision(row,decision,catalog,index):
    action=decision.get('action','Review needed');upc=str(decision.get('confirmed_upc','')).strip()
    if action not in ACTIONS[1:]:raise ValueError(f'Line {index} still needs review')
    if action=='Link existing product' and upc not in catalog:
        upc=normalize_pack_upc(upc)
        if upc not in catalog:raise ValueError(f'Line {index}: choose an existing catalog UPC')
    if action=='Confirm new item':
        if upc in catalog:raise ValueError(f'Line {index}: UPC already exists; link it instead')
        upc=normalize_pack_upc(upc)
        if not re.fullmatch(r'[0-9]{12}',upc):
            raise ValueError(f'Line {index}: enter a 12-digit retail UPC for a new item')
        if upc in catalog:raise ValueError(f'Line {index}: normalized UPC already exists; link it instead')
    if decision.get('remember_mapping') and (action!='Link existing product' or not row['product_number']):
        raise ValueError(f'Line {index}: a saved mapping needs an existing product and supplier product number')
    return action,upc,bool(decision.get('remember_mapping'))


def review_decision_errors(decisions,catalog):
    errors=[]
    for index,row in enumerate(decisions,1):
        try:confirm_line_decision(row,row,catalog,index)
        except (ValueError,ArithmeticError) as exc:
            errors.append({'Line':index,'Item':row.get('description',''),'Problem':str(exc)})
    return errors


def save_review(payload,filename,header,decisions,acknowledge_difference=False,database=DATABASE):
    """All database writes, including the original document, commit or roll back together."""
    rows,difference=validate_review(header,decisions)
    if difference and not acknowledge_difference:
        raise ValueError(f'Invoice and line totals differ by {difference}; review and acknowledge the difference')
    document_digest=hashlib.sha256(payload).hexdigest()
    digest=(hashlib.sha256(payload+json.dumps({k:header.get(k,'') for k in
        ['supplier','retailer','customer_id','store_id','invoice_number','invoice_date']},sort_keys=True).encode()).hexdigest()
        if filename.lower().endswith('.csv') else document_digest)
    products,_,_,_=read_history(database)
    catalog={p['upc'] for p in products}
    confirmed=[confirm_line_decision(row,decision,catalog,index)
               for index,(row,decision) in enumerate(zip(rows,decisions),1)]
    with sqlite3.connect(database) as db:
        db.executescript((ROOT/'schema.sql').read_text())
        # Serialize duplicate checks with the writes; concurrent browser sessions cannot double-post.
        db.execute('BEGIN IMMEDIATE')
        if not filename.lower().endswith('.csv') and db.execute('SELECT 1 FROM invoice_reviews WHERE document_sha256=?',(document_digest,)).fetchone():
            raise ValueError('This document was already saved')
        db.execute('INSERT OR IGNORE INTO suppliers(name) VALUES (?)',(header['supplier'],))
        supplier=db.execute('SELECT id FROM suppliers WHERE name=?',(header['supplier'],)).fetchone()[0]
        identity=(supplier,header['retailer'],header.get('customer_id',''),header['store_id'],header['invoice_number'],header['invoice_date'])
        if db.execute('''SELECT 1 FROM purchase_invoices WHERE supplier_id=? AND retailer_name=?
            AND customer_id=? AND store_id=? AND invoice_number=? AND invoice_date=?''',identity).fetchone():
            raise ValueError('This invoice is already in purchases; use a correction workflow instead of importing it again')
        # Also catch an existing invoice when a PDF omits the customer account ID.
        if db.execute('''SELECT 1 FROM purchase_invoices WHERE supplier_id=? AND retailer_name=?
            AND store_id=? AND invoice_number=? AND invoice_date=?''',
            (supplier,header['retailer'],header['store_id'],header['invoice_number'],header['invoice_date'])).fetchone():
            raise ValueError('Invoice number, supplier, date and store already exist; review the existing invoice')
        # Breakthru PDFs and Fintech exports use different store display names,
        # and the export pads invoice/account numbers with zeros. Match the
        # supplier account and printed invoice identity across those formats.
        if (header.get('source_info',{}).get('supplier_format')=='Breakthru California'
                and db.execute('''SELECT 1 FROM purchase_invoices WHERE supplier_id=?
                    AND ltrim(invoice_number,'0')=? AND invoice_date=?
                    AND ltrim(customer_id,'0')=?''',
                    (supplier,header['invoice_number'].lstrip('0'),header['invoice_date'],
                     header.get('customer_id','').lstrip('0'))).fetchone()):
            raise ValueError('This Breakthru invoice is already in purchases under its supplier account; review the existing invoice')
        if db.execute('SELECT 1 FROM imports WHERE sha256=?',(digest,)).fetchone():
            raise ValueError('This source file was already imported')
        batch=db.execute('INSERT INTO imports(source_name,sha256,row_count) VALUES (?,?,?)',
            (filename,digest,len(rows))).lastrowid
        invoice=db.execute('''INSERT INTO purchase_invoices
            (supplier_id,retailer_name,customer_id,store_id,invoice_number,invoice_date,
             due_date,total_cents,item_count,content_sha256) VALUES (?,?,?,?,?,?,?,?,?,?)''',
             (*identity,header.get('due_date') or None,cents(decimal_text(header['invoice_total'],'Invoice total')),len(rows),digest)).lastrowid
        review=db.execute('''INSERT INTO invoice_reviews(document_sha256,filename,document,invoice_id,decisions_json)
            VALUES (?,?,?,?,?)''',(document_digest,filename,payload,invoice,json.dumps({'header':header,'lines':decisions,
                'difference':str(difference),'difference_acknowledged':bool(acknowledge_difference)},ensure_ascii=False))).lastrowid
        for index,(row,(action,upc,remember)) in enumerate(zip(rows,confirmed),1):
            linked=upc if action=='Link existing product' else None
            lid=db.execute('''INSERT INTO purchase_lines
                (invoice_id,line_number,product_number,source_upc,pack_upc,matched_upc,description,
                 quantity,unit_cost,unit_of_measure,ppc,adjustments_cents,discount_cents,extended_price,gl_code)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (invoice,index,row['product_number'],row['upc'],row['pack_upc'],linked,row['description'],
                 row['quantity'],row['unit_cost'],row['unit_of_measure'],row['ppc'],cents(row['adjustments']),
                 cents(row['discount']),row['extended_price'],'')).lastrowid
            db.execute('INSERT INTO purchase_source_rows VALUES (?,?,?,?,?)',
                (batch,index,invoice,lid,json.dumps({'reviewed_line':row,'action':action,'confirmed_upc':upc},ensure_ascii=False)))
            if action=='Confirm new item':
                db.execute('''INSERT INTO catalog_candidates(review_id,line_number,retail_upc,description,supplier_product_number)
                    VALUES (?,?,?,?,?)''',(review,index,upc,row['description'],row['product_number']))
            if remember:
                key=(supplier,row['product_number'],row['unit_of_measure'],row['ppc'])
                old=db.execute('''SELECT upc FROM supplier_product_mappings WHERE supplier_id=?
                    AND product_number=? AND unit_of_measure=? AND ppc=?''',key).fetchone()
                if old and old[0]!=upc:raise ValueError(f'Line {index}: mapping conflicts with a saved mapping')
                db.execute('INSERT OR IGNORE INTO supplier_product_mappings VALUES (?,?,?,?,?)',(*key,upc))
        if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Database reference validation failed')
    return {'invoice_id':invoice,'review_id':review,'new_items':sum(a=='Confirm new item' for a,_,_ in confirmed)}
