"""Read Fintech's invoice report using its header-cell geometry, not ruled data rows."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from pdfplumber.utils import extract_text

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
        # Segment characters before forming words: PDF text may join adjacent cells
        # (CASE/PACK, PACK/QTY, or description/CASE) into a single extracted word.
        groups=[]
        for char in sorted(page.chars,key=lambda c:(c['top'],c['x0'])):
            if char['top']<=table.rows[0].bbox[3]:continue
            if not groups or abs(groups[-1][0]['top']-char['top'])>2:groups.append([])
            groups[-1].append(char)
        lines=[];current=None
        for chars in groups:
            columns=[]
            for index,cell in enumerate(cells):
                selected=[c for c in chars if cell[0]<= (c['x0']+c['x1'])/2 < cell[2]]
                if FIELDS[index] in {'case_upc','pack_upc'}:
                    value=''.join(c['text'] for c in sorted(selected,key=lambda c:c['x0']) if not c['text'].isspace())
                else:
                    value=extract_text(selected,x_tolerance=2,y_tolerance=2).strip() if selected else ''
                columns.append(value)
            row=dict(zip(FIELDS,columns))
            if re.fullmatch(r'[A-Za-z0-9-]{4,}',row['product_number']) and row['quantity'] and row['extended_price']:
                current={k:amount(v) if k in {'quantity','ppc','unit_cost','discount','adjustments','extended_price'} else v
                         for k,v in row.items() if k!='subtotal'}
                current['upc']=''  # The review normalizes only PACK UPC after all fragments are joined.
                lines.append(current)
            elif current and any(row.values()) and not any(
                    value for field,value in row.items() if field not in {'description','case_upc','pack_upc'}):
                if row['description']:current['description']+=' '+row['description']
                for field in ['case_upc','pack_upc']:current[field]+=row[field]
            else:
                current=None
        return lines
    return None
