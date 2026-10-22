"""OCR drafts for Straub, Sunset and Pepsi paper documents. No guessed identifiers."""
from datetime import datetime
from decimal import Decimal
import re
from statistics import median
from purchase_matching import normalize_pack_upc


def amount(raw):
    raw=raw.strip().replace('$','').replace(' ','')
    if re.fullmatch(r'-?\d+,\d{2}',raw):raw=raw.replace(',','.')
    if not re.fullmatch(r'-?(?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2}',raw):return ''
    return raw.replace(',','')


def integer(raw):
    return raw.strip() if re.fullmatch(r'\d+',raw.strip()) else ''


def row_data(page, alternate=False):
    words=page.get('alternate_words',[]) if alternate else page['words']
    chars=page.get('alternate_chars',[]) if alternate else page['chars']
    heights=[w['bottom']-w['top'] for w in words if w['bottom']>w['top']]
    tolerance=max(3,median(heights)*.48) if heights else 5
    rows=[]
    for word in sorted(words,key=lambda w:((w['top']+w['bottom'])/2,w['x0'])):
        middle=(word['top']+word['bottom'])/2
        if not rows or abs(middle-rows[-1]['y'])>tolerance:
            rows.append(dict(y=middle,words=[]))
        rows[-1]['words'].append(word)
    for row in rows:
        row['words'].sort(key=lambda w:w['x0'])
        row['text']=' '.join(w['text'] for w in row['words'])
        row['top']=min(w['top'] for w in row['words']);row['bottom']=max(w['bottom'] for w in row['words'])
        row['chars']=[c for c in chars if any(w['x0']-2 <= (c['x0']+c['x1'])/2 <= w['x1']+2 and w['top']-2 <= (c['top']+c['bottom'])/2 <= w['bottom']+2 for w in row['words'])]
        row['width']=page['width']
    return rows


def cell(row,left=0,right=1,words=False):
    width=row['width']
    values=row['words'] if words else row['chars']
    selected=sorted((v for v in values if left*width<=(v['x0']+v['x1'])/2<right*width),key=lambda v:v['x0'])
    return (' ' if words else '').join(v['text'] for v in selected).strip()


def new_line(**values):
    fields=['product_number','upc','description','quantity','unit_cost','unit_of_measure','ppc',
            'pack_upc','adjustments','discount','extended_price','case_upc']
    return dict(dict.fromkeys(fields,''),**values)


def valid_code(raw):
    if not re.fullmatch(r'[0-9\s-]+',raw.strip()):return ''
    digits=re.sub(r'[\s-]','',raw)
    if len(digits)<12:return ''
    try:code=normalize_pack_upc(digits)
    except ValueError:return ''
    return code if code and (-sum(int(n)*(3 if i%2==0 else 1) for i,n in enumerate(code[:-1])))%10==int(code[-1]) else ''


def code_for(page,top,bottom,raw='',left=0,right=1):
    barcodes=[b for b in page.get('barcodes',[]) if top<=(b['top']+b['bottom'])/2<bottom]
    codes={valid_code(b['text']) for b in barcodes if valid_code(b['text'])}
    if len(codes)==1:return codes.pop(),'Decoded product barcode'
    if len(codes)>1:return '', 'Multiple product barcodes in this row; select the correct PACK UPC manually'
    # OCR alone requires two passes to agree, not a character-replacement guess.
    primary=valid_code(raw)
    if primary:
        alternative=[c for c in page.get('alternate_chars',[]) if top<=(c['top']+c['bottom'])/2<bottom
                     and left*page['width']<=(c['x0']+c['x1'])/2<right*page['width']]
        groups=row_data(dict(page,words=page.get('alternate_words',[]),chars=alternative))
        if any(valid_code(cell(r,left,right))==primary for r in groups):
            return primary,'Two OCR passes agree; check digit valid'
    return '','Barcode unreadable, ambiguous or OCR passes disagree; verify PACK UPC on the product.'


def label_amount(rows,label,last=True):
    hits=[]
    for row in rows:
        if re.search(label,row['text'],re.I):
            values=re.findall(r'\$?-?[\d,]+[.,]\d{2}\b',row['text'])
            if values and amount(values[-1]):hits.append(amount(values[-1]))
    return (hits[-1] if last else hits[0]) if hits else ''


def source_date(text,pattern):
    match=re.search(pattern,text,re.I)
    if not match:return ''
    for fmt in ('%m/%d/%Y','%m/%d/%y','%b %d, %Y'):
        try:return datetime.strptime(match[1],fmt).date().isoformat()
        except ValueError:pass
    return ''


def extract_straub(pages):
    page=pages[0];rows=row_data(page)
    starts=[r['top'] for r in rows if re.search(r'STRA[UO]B\s+DISTRIBUT',r['text'],re.I)]
    start=starts[0] if starts else 0
    rows=[r for r in rows if r['top']>=start]
    header=dict(supplier='Straub Distributing Co., Ltd.',invoice_number='',invoice_date='',due_date='',invoice_total='')
    scoped='\n'.join(r['text'] for r in rows)
    header['due_date']=source_date(scoped,r'Due\s+date\s+(\d{1,2}/\d{1,2}/\d{2,4})')
    header['invoice_date']=source_date(scoped,r'Delivered\s*(\d{1,2}/\d{1,2}/\d{2,4})')
    # Header OCR can be poor on a narrow thermal receipt. Do not use totals,
    # account balances or a CamScanner filename as a substitute invoice ID/date.
    header['invoice_total']=label_amount(rows,r'Invoice\s+total')
    alternate=[r for r in row_data(page,True) if r['top']>=start]
    other=label_amount(alternate,r'Invoice\s+total')
    if other and header['invoice_total']!=other:header['invoice_total']=''
    lines=[];details=[]
    body_start=next((r['top'] for r in rows if 'DESCRIPTION' in r['text'] and 'UPC' in r['text']),None)
    if body_start is None:body_start=next((r['top'] for r in alternate if 'DESCRIPTION' in r['text'] and 'UPC' in r['text']),0)
    body=[r for r in rows if r['top']>body_start and not (r['text'].startswith('EXTENDED'))]
    stop=next((r['top'] for r in rows if 'EXTENDED SUB' in r['text']),page['height'])
    body=[r for r in body if r['top']<stop]
    anchors=[r for r in body if amount(cell(r,.88,1))]
    # A slanted thermal line can have its quantity below the amount.
    anchors=[dict(r, words=[w for w in page['words'] if r['top']-5 <= w['top'] <= r['bottom']+25], chars=[c for c in page['chars'] if r['top']-5 <= c['top'] <= r['bottom']+25]) for r in anchors]
    for index,row in enumerate(anchors):
        end=anchors[index+1]['top'] if index+1<len(anchors) else stop
        raw=dict(product_number=cell(row,0,.10),quantity=cell(row,.10,.135),description=cell(row,.135,.40,True),
                 upc=cell(row,.40,.60),unit_cost=cell(row,.60,.70),discount=cell(row,.70,.79),
                 crv=cell(row,.79,.88),extended_price=cell(row,.88,1))
        continuations=[r for r in body if row['bottom']+25<r['top']<end]
        description=' '.join([raw['description'],*[cell(r,.135,.4,True) for r in continuations if cell(r,.135,.4,True)]])
        upc,note=code_for(page,row['top'],end,raw['upc'],.40,.60)
        q=integer(raw['quantity']);cost=amount(raw['unit_cost']);disc=amount(raw['discount']);crv=amount(raw['crv'])
        lines.append(new_line(product_number=integer(raw['product_number']),description=description,quantity=q,
            unit_of_measure='CA',unit_cost=cost,ppc='',pack_upc=upc,upc=upc,
            discount=str(-Decimal(q)*Decimal(disc)) if q and disc else '',
            adjustments=str(Decimal(q)*Decimal(crv)) if q and crv else '',extended_price=amount(raw['extended_price'])))
        details.append(dict(raw_fields=raw,page=1,normalized_upc=upc,note=note))
    warnings=['A fragment of an earlier receipt appears above the Straub header and was ignored. Verify the invoice number, date and final invoice total; payment/due/balance amounts are not invoice totals.'] if start>page['height']*.1 else []
    return header,lines,details,[],{},warnings


def extract_sunset(pages):
    page=pages[0];rows=row_data(page);alternate=row_data(page,True)
    combined=page['text']+'\n'+page.get('alternate_text','')
    header=dict(supplier='Sunset Distributing',invoice_number='',invoice_date='',due_date='',invoice_total='')
    match=re.search(r'Invoice[#f:]\s*:?\s*(\d{8,})',combined,re.I)
    if match:header['invoice_number']=match[1]
    date=re.search(r'(Oct\s+\d{1,2},\s+20\d{2})',combined,re.I)
    if date:
        try:header['invoice_date']=datetime.strptime(date[1],'%b %d, %Y').date().isoformat()
        except ValueError:pass
    account=re.search(r'Account:\s*(\d+)',combined,re.I)
    if account:header['customer_id']=account[1]
    header['invoice_total']=label_amount(rows,r'Picksheet\s+Total') or label_amount(alternate,r'Picksheet\s+Total')
    crv=label_amount(rows,r'Total\s+CRV') or label_amount(alternate,r'Total\s+CRV')
    lines=[];details=[];excluded=[]
    barcodes=sorted(page.get('barcodes',[]),key=lambda b:b['top'])
    for barcode in barcodes:
        upc=valid_code(barcode['text'])
        if not upc:continue
        # Anchor each source item to its independently decoded graphic. This
        # retains rows even when the curved left edge loses a quantity or SKU.
        top=barcode['top']-page['width']*.105
        bottom=barcode['bottom']+page['width']*.045
        words=[w for w in page['words'] if top <= w['top'] <= bottom]
        names=[r for r in rows if top<=r['top']<barcode['top']-page['width']*.025
               and re.search(r'[A-Za-z]{3}',cell(r,0,.60,True))
               and not re.search(r'Selling|Units|Stock|PALLET|Subtotal',r['text'],re.I)]
        description=' '.join(cell(r,0,.60,True) for r in names) or 'Unreadable product name — verify original'
        sku=next((w['text'] for w in words if w['x0']/page['width']<.10 and re.fullmatch(r'\d{4,6}',w['text'])), '')
        if sku:description=re.sub(r'^'+re.escape(sku)+r'\s*','',description)
        def money(left,right):
            candidates=[w for w in words if left <= (w['x0']+w['x1'])/2/page['width'] < right
                        and w['top']<barcode['top']-10 and amount(w['text'])]
            return amount(candidates[-1]['text']) if candidates else ''
        qwords=[w['text'] for w in words if .11<=(w['x0']+w['x1'])/2/page['width']<.18
                and barcode['top']-page['width']*.055<w['top']<barcode['top'] and integer(w['text'])]
        q=qwords[0] if len(qwords)==1 else ''
        cost=money(.61,.71);discount=money(.72,.81);total=money(.89,1)
        section=' '.join(r['text'] for r in rows if top <= r['top'] <= bottom)
        selling=re.search(r'Units:\s*(\d+)',section)
        units=selling[1] if selling else ''
        if units=='0' or q=='0' or re.search(r'Out\s+of\s+Stock',section,re.I):
            excluded.append(dict(description=description,quantity='0',amount=total,reason='Out of stock / not delivered'));continue
        adjustment=str(Decimal(total)-Decimal(q)*(Decimal(cost)-Decimal(discount))) if q and cost and discount and total else ''
        lines.append(new_line(product_number=sku,description=description,quantity=q,unit_of_measure='CA',
            unit_cost=cost,ppc=str(int(units)//int(q)) if units and q and int(q)>0 and int(units)%int(q)==0 else '',
            pack_upc=upc,upc=upc,discount=str(-Decimal(q)*Decimal(discount)) if q and discount else '',
            adjustments=adjustment,extended_price=total))
        details.append(dict(page=1,barcode_raw=barcode['text'],normalized_upc=upc,
            note='Decoded product barcode; verify printed quantity and amounts',selling_units=units,raw_block=section))
    reconciled=bool(crv and lines and all(line['adjustments'] for line in lines))
    if reconciled:reconciled=sum(Decimal(line['adjustments']) for line in lines)==Decimal(crv)
    if not reconciled:
        for line in lines:line['adjustments']=''
    return header,lines,details,excluded,{},['Sunset document is marked NOT A FINAL INVOICE. Confirm the final charged purchase before saving. Per-line adjustments must reconcile to the printed Total CRV; do not use Amount Due or A/R balances.']


def extract_pepsi(pages,reference=False):
    header=dict(supplier='PepsiCo Beverages Company',invoice_number='',invoice_date='',due_date='',invoice_total='')
    text='\n'.join(p['text']+'\n'+p.get('alternate_text','') for p in pages)
    match=re.search(r'(?:#\s*|FOR\s+INV\S*\s*\n)(\d{8})\b',text,re.I)
    if match:header['invoice_number']=match[1]
    header['invoice_date']=source_date(text,r'(\d{1,2}/\d{1,2}/20\d{2})')
    account=re.search(r'Customer\s*#:\s*(\d+)',text,re.I)
    if account:header['customer_id']=account[1]
    lines=[];details=[];charges={}
    if reference:
        for page in pages:
            rows=row_data(page)
            for barcode in sorted(page.get('barcodes',[]),key=lambda b:b['top']):
                upc=valid_code(barcode['text'])
                if not upc:continue
                previous=[r for r in rows if barcode['top']-page['width']*.15<r['y']<barcode['top']
                          and re.search(r'[A-Za-z]',cell(r,0,.62,True))
                          and not re.search(r'PKG TOTAL|Bay\s*#',r['text'],re.I)]
                row=previous[-1] if previous else None
                description=cell(row,0,.62,True) if row else 'Unreadable product name — verify original'
                q=integer(cell(row,.6,.74)) if row else ''
                lines.append(new_line(description=description,quantity=q,unit_of_measure='CA',pack_upc=upc,upc=upc))
                details.append(dict(page=page['page'],barcode_raw=barcode['text'],normalized_upc=upc,note='Reference only; barcode decoded from image'))
        return header,lines,details,[],{},['Pepsi product pick list is marked NOT AN INVOICE. It can check catalog items, but cannot be saved as a purchase invoice or used to invent prices.']
    summary_rows=row_data(pages[0])
    summary_alt=row_data(pages[0],True)
    header['invoice_total']=label_amount(summary_rows,r'Amount\s+Due') or label_amount(summary_alt,r'Amount\s+Due')
    charge=label_amount(summary_rows,r'State\s*/\s*Local\s+Charges') or label_amount(summary_alt,r'State\s*/\s*Local\s+Charges')
    if charge:charges['state_local_charges']=charge
    for page in pages:
        rows=row_data(page);body_start=next((r['bottom'] for r in rows if 'ITEM DETAIL' in r['text']),0)
        stop=next((r['top'] for r in rows if r['top']>body_start and re.search(r'STATE.?/?LOCAL CHARGES',r['text'],re.I)),page['height'])
        group=''
        for i,row in enumerate(rows):
            if not body_start<row['top']<stop:continue
            if re.search(r'\b(?:PL|CN|SLCEL)\b.*\d/\d|\d/\d.*(?:SW|SCP)',row['text']):group=row['text']
            # An item-description/UPC row precedes its five numeric columns.
            candidates=re.findall(r'\d-\d[\d -]{7,}[0-9A-Za-z-]',row['text'])
            candidate=next((c for c in candidates if len(re.sub(r'\D','',c))>=10),'')
            if not candidate or 'SUBTOTAL' in row['text'] or not re.search(r'[A-Za-z]',row['text'].split(candidate)[0]):continue
            # Keep an item with an unreadable numeric row as an incomplete draft.
            # Character boxes split columns joined by OCR; no decimal is inferred.
            following=None
            for candidate_row in rows[i+1:i+4]:
                if re.search(r'\d-\d[\d -]{7,}',candidate_row['text']):break
                if re.search(r'SUBTOTAL|UPC|PL|CN',candidate_row['text']):break
                if candidate_row['y']>row['y'] and re.search(r'\d[.,]\d{2}',candidate_row['text']):
                    following=candidate_row;break
            if following is None:
                following=dict(row,words=[],chars=[],text='')
            # Receipt columns drift slightly with perspective; use the source
            # UPC row's left edge to keep the quantity/net/amount boxes aligned.
            offset=min(w['x0'] for w in row['words'])/page['width']-.18
            q=integer(cell(following,.43+offset,.51+offset));units=integer(cell(following,.52+offset,.595+offset))
            cost=amount(cell(following,.595+offset,.72+offset));total=amount(cell(following,.735+offset,.91+offset))
            raw=re.sub(r'\s+','',candidate)
            upc_words=[w for w in row['words'] if '-' in w['text'] and re.search(r'\d',w['text'])]
            left=min((w['x0']/page['width'] for w in upc_words),default=.38)
            upc,note=code_for(page,row['top'],max(row['bottom']+1,following['bottom']),raw,left,.82)
            description=row['text'].split(candidate)[0].strip()
            if not description:description='Unreadable product name — verify original'
            if q and cost and total and Decimal(q)*Decimal(cost)!=Decimal(total):q='';cost=''
            lines.append(new_line(description=(description+' · '+group).strip(' ·'),quantity=q,unit_of_measure='CA',
                ppc=str(int(units)//int(q)) if units and q and int(q)>0 and int(units)%int(q)==0 else '',
                unit_cost=cost,pack_upc=upc,upc=upc,discount='0',adjustments='0',extended_price=total))
            details.append(dict(page=page['page'],raw_upc=raw,normalized_upc=upc,note=note,
                                source_units=units,raw_numeric_row=following['text']))
    return header,lines,details,[],charges,['Pepsi net prices, case quantities and state/local charges are OCR drafts. Blank fields indicate unreadable or inconsistent values; compare every line with the original.']


def parse_scans(pages):
    combined='\n'.join(p['text']+'\n'+p.get('alternate_text','') for p in pages)
    upper=combined.upper()
    status='reference_only' if 'NOT AN INVOICE' in upper else 'invoice'
    suppliers=sum(bool(re.search(pattern,upper)) for pattern in (r'STRA[UO]B\s+DISTRIBUT',r'SUNSET DISTRIBUTING',r'PEPSI'))
    if suppliers>1:raise ValueError('Upload one supplier document at a time; this scan contains multiple suppliers.')
    if len(pages)>1 and re.search(r'STRA[UO]B\s+DISTRIBUT|SUNSET DISTRIBUTING',upper):
        raise ValueError('Straub and Sunset scans currently support one receipt page at a time. Upload each document separately.')
    identifiers=set(re.findall(r'(?:INVOICE\s*#|FOR\s+INV#)\s*(\d{8,})',upper))
    if len(identifiers)>1:raise ValueError('This scan contains multiple invoice numbers; upload each document separately.')
    if re.search(r'STRA[UO]B\s+DISTRIBUT',upper):result=extract_straub(pages);kind='Straub scan'
    elif 'SUNSET DISTRIBUTING' in upper:
        result=extract_sunset(pages);kind='Sunset scan';status='preliminary'
    elif ('PEPSI' in upper or 'ALISO' in upper) and ('PICK LIST' in upper or 'ITEM DETAIL' in upper):
        reference='NOT AN INVOICE' in upper or 'PICK LIST FOR' in upper
        result=extract_pepsi(pages,reference);kind='Pepsi scan';status='reference_only' if reference else 'invoice'
    else:
        result=({},[],[],[],{},['Unknown scanned layout. Read the OCR text and enter the invoice details and lines manually; no amounts or UPCs are inferred.']);kind='Unknown scan'
    header,lines,details,excluded,charges,warnings=result
    if charges:
        header['source_info']={'invoice_charges':charges,'merchandise_total':str(sum(Decimal(l['extended_price']) for l in lines)) if lines and all(l['extended_price'] for l in lines) else 'not fully read'}
    info=header.setdefault('source_info',{})
    info.update(ocr=True,supplier_format=kind,document_status=status,barcode_details=details,excluded_lines=excluded,
                ocr_pages=[dict(page=p['page'],rotation=p['rotation'],scanned=p['scanned']) for p in pages])
    warnings.insert(0,'Scanned document — local OCR draft. Check all identifiers, delivered quantities, units, prices and totals against the original before product matching or saving. OCR confidence does not prove correctness.')
    if lines and status!='reference_only':
        incomplete=sum(any(not line.get(field) for field in ('quantity','unit_cost','extended_price')) for line in lines)
        if incomplete:warnings.append(f'{incomplete} item rows have unreadable financial fields. Correct the blank fields and check for omitted rows against every page of the original.')
    if not lines and status!='reference_only':warnings.append('No complete item rows were read. Enter the lines manually; the scan has not been saved.')
    return dict(kind='pdf',header=header,lines=lines,text=combined,warnings=warnings)
