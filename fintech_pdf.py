"""Read Fintech's invoice report using its header-cell geometry, not ruled data rows."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

HEADERS = ['PRODUCT #','DESCRIPTION','CASE UPC','PACK UPC','QTY','U/M','PPC',
           'PRICE','SUBTOTAL','DISC','ADJ','TOTAL']
FIELDS = ['product_number','description','case_upc','pack_upc','quantity','unit_of_measure',
          'ppc','unit_cost','subtotal','discount','adjustments','extended_price']


def amount(value):
    text=value.strip().replace('$','').replace(',','')
    if text.startswith('(') and text.endswith(')'):text='-'+text[1:-1]
    try:
        if not Decimal(text).is_finite():raise ValueError('Non-finite amount')
    except (InvalidOperation,ValueError):return value
    return text


def extract_header(text,page):
    """Only labeled values from the document become editable defaults."""
    result={}
    for field,label in [('invoice_number','Invoice Number'),('invoice_date','Invoice Date'),('due_date','Due Date')]:
        match=re.search(re.escape(label)+r'\s+([^\s]+)',text)
        if match:
            value=match[1]
            if field.endswith('date'):
                try:value=datetime.strptime(value,'%m/%d/%Y').date().isoformat()
                except ValueError:continue
            result[field]=value
    total=re.findall(r'^Total\s+([($\d,.-]+\)?)\s*$',text,re.MULTILINE)
    if total:result['invoice_total']=amount(total[-1])
    first=text.splitlines()[0] if text else ''
    if first.endswith(' Invoice'):result['supplier']=first[:-8].strip()
    words=page.extract_words()
    bill=next((word for word in words if word['text']=='BILL' and word['x0']<page.width/2),None)
    if bill:
        left_words=[w for w in words if bill['bottom']<w['top']<bill['bottom']+35
                    and w['x0']>=bill['x0'] and w['x1']<page.width/2]
        if left_words:
            top=min(w['top'] for w in left_words)
            result['retailer']=' '.join(w['text'] for w in sorted(left_words,key=lambda w:w['x0'])
                                      if abs(w['top']-top)<2)

    return result


def extract_page(page):
    for table in page.find_tables():
        extracted=table.extract()
        if not extracted:continue
        names=[' '.join((value or '').split()).upper() for value in extracted[0]]
        if names!=HEADERS:continue
        cells=table.rows[0].cells
        if any(cell is None for cell in cells):continue
        groups=[]
        for word in sorted(page.extract_words(),key=lambda w:(w['top'],w['x0'])):
            if word['top']<=table.rows[0].bbox[3]:continue
            if not groups or abs(groups[-1][0]['top']-word['top'])>2:groups.append([])
            groups[-1].append(word)
        lines=[];current=None
        for words in groups:
            columns=[]
            for cell in cells:
                selected=[w for w in words if cell[0]<= (w['x0']+w['x1'])/2 < cell[2]]
                columns.append(' '.join(w['text'] for w in sorted(selected,key=lambda w:w['x0'])))
            row=dict(zip(FIELDS,columns))
            if re.fullmatch(r'[A-Za-z0-9-]{4,}',row['product_number']) and row['quantity'] and row['extended_price']:
                current={k:amount(v) if k in {'quantity','ppc','unit_cost','discount','adjustments','extended_price'} else v
                         for k,v in row.items() if k!='subtotal'}
                current['upc']=''  # CASE UPC is a packaging identifier, not a retail UPC.
                lines.append(current)
            elif current and row['description'] and not any(v for k,v in row.items() if k!='description'):
                current['description']+=' '+row['description']
            else:
                current=None
        return lines
    return None
