"""Read Mercaso fulfilled invoice lines; excluded merchandise never becomes purchases."""
from datetime import datetime
from decimal import Decimal
import re
from pdfplumber.utils import extract_text
from purchase_matching import normalize_pack_upc


def money(text,empty=False):
    text=text.strip().replace('$','').replace(',','')
    if not text and empty:return Decimal(0)
    if text.startswith('(') and text.endswith(')'):text='-'+text[1:-1]
    value=Decimal(text)
    if not value.is_finite():raise ValueError('Non-finite Mercaso amount')
    return value


def upce_to_upca(code):
    if not re.fullmatch(r'[01][0-9]{7}',code):raise ValueError('Invalid UPC-E barcode')
    ns=code[0];a,b,c,d,e,f=code[1:7]
    if f in '012':body=ns+a+b+f+'0000'+c+d+e
    elif f=='3':body=ns+a+b+c+'00000'+d+e
    elif f=='4':body=ns+a+b+c+d+'00000'+e
    else:body=ns+a+b+c+d+e+'0000'+f
    check=str((-sum(int(n)*(3 if i%2==0 else 1) for i,n in enumerate(body[::-1])))%10)
    if code[-1]!=check:raise ValueError('UPC-E checksum does not match its expanded UPC-A')
    return body+check


def decode_item_barcode(page,bbox):
    import zxingcpp
    image=page.crop(bbox).to_image(resolution=300).original
    results=zxingcpp.read_barcodes(image)
    decoded={(r.text,str(r.format)) for r in results if r.valid}
    if len(decoded)!=1:return '',{'note':'Barcode could not be uniquely decoded; enter the full item UPC manually.'}
    raw,kind=decoded.pop()
    try:
        normalized=upce_to_upca(raw) if kind=='BarcodeFormat.UPCE' else normalize_pack_upc(raw)
    except ValueError as exc:return '',{'barcode_raw':raw,'barcode_format':kind,'note':str(exc)}
    return normalized,{'barcode_raw':raw,'barcode_format':kind,'normalized_upc':normalized}


def word_rows(page):
    rows=[]
    for word in sorted(page.extract_words(),key=lambda w:(w['top'],w['x0'])):
        if not rows or abs(rows[-1][0]['top']-word['top'])>2:rows.append([])
        rows[-1].append(word)
    return rows


def page_items(page):
    rows=word_rows(page)
    result=[]
    for header_index,header in enumerate(rows):
        tokens=[w['text'] for w in header]
        if not {'Line','Item','Code','CRV','Disc','Qty','Amount'}.issubset(tokens):continue
        prices=[w['x0'] for w in header if w['text']=='Price']
        if len(prices)!=3:continue
        at=lambda token:next(w['x0'] for w in header if w['text']==token)
        qty_index=tokens.index('Qty')
        qty=header[qty_index-1]['x0'] if tokens[qty_index-1]=='Case' else at('Qty')
        starts=[at('Line'),at('Item'),at('Code'),prices[0],prices[1],at('CRV'),at('Disc'),at('Total'),qty,at('Amount')]
        # Data values are slightly left of their header labels.
        edges=[x-3 for x in starts]+[at('Key')-3 if 'Key' in tokens else page.width-20]
        fields=['line','description','code_text','each_price','unit_cost','crv_case','discount_case','total_case','quantity','amount']
        for source in rows[header_index+1:]:
            y=source[0]['top']
            chars=[c for c in page.chars if abs(c['top']-y)<2]
            values={field:extract_text([c for c in chars if left<=(c['x0']+c['x1'])/2<right],
                x_tolerance=2,y_tolerance=2).strip() for field,left,right in zip(fields,edges,edges[1:])}
            if re.fullmatch(r'[0-9]+',values['line']) and values['quantity'] and '$' in values['amount']:
                values.update(top=y,bottom=page.height-30,code_left=edges[2],code_right=edges[3],page=page)
                result.append(values)
        # A recognized header has one geometry for this page.
        break
    for index,item in enumerate(result):
        end=result[index+1]['top'] if index+1<len(result) else min(item['top']+100,page.height-30)
        item['bottom']=end
        continuations=[row for row in rows if item['top']+2<row[0]['top']<end]
        sku_top=end
        for row in continuations:
            left_words=[w for w in row if starts[1]-3<=w['x0']<starts[2]-3]
            text=' '.join(w['text'] for w in sorted(left_words,key=lambda w:w['x0']))
            sku=re.search(r'\bSKU\s+(\S+)',text)
            if sku:item['product_number']=sku[1];sku_top=row[0]['top'];break
            if text:item['description']+=' '+text
        item.setdefault('product_number','')
        item['bottom']=min(end,sku_top+55)
    return result


def extract_invoice(pdf):
    first=pdf.pages[0].extract_text() or ''
    if 'mercaso.com' not in first or 'Mercaso, Inc.' not in first:return None
    match=re.search(r'\bInvoice\s+(M-[A-Za-z0-9-]+)',first)
    if not match:raise ValueError('Mercaso invoice number could not be read')
    order=re.search(r'Order Date\s+(\d{2}-\d{2}-\d{4})',first)
    header={'supplier':'Mercaso, Inc.','invoice_number':match[1],'due_date':'','invoice_total':''}
    if order:header['invoice_date']=datetime.strptime(order[1],'%m-%d-%Y').date().isoformat()
    business=re.search(r'^Business\s+Delivery date\s+Customer\s*\n(.+)$',first,re.MULTILINE)
    if business:
        # Use the business column, not the delivery/customer text to its right.
        rows=word_rows(pdf.pages[0]);label=next((r for r in rows if [w['text'] for w in r][:1]==['Business']),None)
        if label:
            cutoff=next(w['x0'] for w in label if w['text']=='Delivery')
            next_row=next((r for r in rows if r[0]['top']>label[0]['bottom']),[])
            header['retailer']=' '.join(w['text'] for w in next_row if w['x1']<cutoff)
    warnings=['Mercaso supplies an Order Date rather than a separate invoice date. The Order Date is prefilled; verify it before saving.',
        'Mercaso quantities and unit costs use cases. Price / Each is retained as a reference; case totals determine purchase amounts.']
    lines=[];excluded=[];source_details=[];texts=[];section_unfulfilled=False
    for page_number,page in enumerate(pdf.pages,1):
        text=page.extract_text() or '';texts.append(text)
        invoice_ids=re.findall(r'\bInvoice\s+(M-[A-Za-z0-9-]+)',text)
        if any(i!=header['invoice_number'] for i in invoice_ids):raise ValueError('Upload one Mercaso invoice at a time')
        totals=re.findall(r'^Total\s+(\$[0-9,.]+)\s*$',text,re.MULTILINE)
        if totals:header['invoice_total']=str(money(totals[-1]))
        paid=re.search(r'^Paid\s+(\$[0-9,.]+)',text,re.MULTILINE)
        due=re.search(r'^Amount Due\s+(\$[0-9,.]+)',text,re.MULTILINE)
        if paid:header['paid']=str(money(paid[1]))
        if due:header['amount_due']=str(money(due[1]))
        sections=[]
        for words in word_rows(page):
            label=' '.join(w['text'] for w in sorted(words,key=lambda w:w['x0']))
            if re.search(r'Unfulfilled and not charged',label,re.IGNORECASE):sections.append((words[0]['top'],True))
            elif re.search(r'- Mercaso$',label):sections.append((words[0]['top'],False))
        for item in page_items(page):
            # This supplier prints unfulfilled merchandise in its own section/page.
            before=[flag for top,flag in sections if top<item['top']]
            unfulfilled=before[-1] if before else section_unfulfilled
            if unfulfilled:
                excluded.append({'product_number':item['product_number'],'description':item['description'],
                    'quantity':item['quantity'],'amount':str(money(item['amount'])),'reason':'Unfulfilled and not charged'})
                continue
            upc,details=decode_item_barcode(page,(item['code_left'],max(item['top']-3,0),
                item['code_right'],min(item['bottom'],page.height)))
            details.update(product_number=item['product_number'],page=page_number,each_price=str(money(item['each_price'])))
            source_details.append(details)
            if not upc:warnings.append(f"Item {item['product_number']}: {details.get('note','Barcode needs review')}")
            quantity=money(item['quantity']);pack=re.search(r'\((\d+)\s+Pack\)',item['description'],re.IGNORECASE)
            lines.append({'product_number':item['product_number'],'upc':upc,'pack_upc':upc,'case_upc':'',
                'description':item['description'],'quantity':str(quantity),'unit_cost':str(money(item['unit_cost'])),
                'unit_of_measure':'CA','ppc':pack[1] if pack else '',
                'adjustments':str(money(item['crv_case'],True)*quantity),
                'discount':str(-abs(money(item['discount_case'],True))*quantity),
                'extended_price':str(money(item['amount']))})
        if sections:section_unfulfilled=sections[-1][1]
    if not header['invoice_total']:warnings.append('Invoice Total was not found. Enter and verify the charged total; do not use Amount Due or the unfulfilled subtotal.')
    if excluded:warnings.append(f'{len(excluded)} unfulfilled/not-charged line(s) excluded from purchases and new-item checks.')
    header['source_info']={'supplier_format':'Mercaso','date_basis':'Order Date',
        'barcode_details':source_details,'excluded_lines':excluded}
    return {'kind':'pdf','header':header,'lines':lines,'text':'\n\n'.join(texts),'warnings':warnings}
