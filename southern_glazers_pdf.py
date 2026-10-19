"""Southern Glazer's California delivery invoices: geometry, delivered units and fees."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from pdfplumber.utils import extract_text
from purchase_matching import normalize_pack_upc

SUPPLIER = "Southern Glazer's Wine & Spirits of S. CA"
FORMAT = 'Southern Glazers California'
FIELDS = ['flag', 'cases', 'bottles', 'description', 'unit_cost', 'unit_discount',
          'net_unit', 'taxes', 'extended_price']


def money(value):
    try:
        number = Decimal(value.strip().replace('$', '').replace(',', ''))
        if not number.is_finite():
            raise InvalidOperation
        return number
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError('Southern Glazer\'s amount could not be read; check the original PDF.') from exc


def iso(value):
    for pattern in ('%m/%d/%Y', '%m/%d/%y'):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError('Southern Glazer\'s date could not be read.')


def group_rows(page):
    groups = []
    for char in sorted(page.chars, key=lambda c: (c['top'], c['x0'])):
        if not groups or abs(char['top'] - groups[-1][0]['top']) > 1.5:
            groups.append([])
        groups[-1].append(char)
    return groups


def text(chars):
    return extract_text(chars, x_tolerance=1, y_tolerance=2).strip() if chars else ''


def columns(chars, edges):
    return dict(zip(FIELDS, [text([c for c in chars if left <= (c['x0']+c['x1'])/2 < right])
                             for left, right in zip(edges, edges[1:])]))


def page_invoice_number(page):
    words = page.extract_words()
    heading = next((w for w in words if w['text'] == 'INVOICE' and w['top'] < 65 and w['x0'] > page.width/2), None)
    if not heading:
        raise ValueError('A Southern Glazer\'s page is missing its invoice identity.')
    numbers = [w['text'] for w in words if heading['bottom'] < w['top'] < heading['bottom']+30
               and w['x0'] > page.width*0.75 and re.fullmatch(r'\d+', w['text'])]
    if len(numbers) != 1:
        raise ValueError('Southern Glazer\'s invoice number could not be uniquely read.')
    return numbers[0]


def item_edges(page):
    words = page.extract_words()
    cs = next((w for w in words if w['text'] == 'CS'), None)
    if not cs or not any(w['text'] == 'BTLS' and abs(w['top']-cs['top']) < 2 for w in words):
        raise ValueError('Southern Glazer\'s case/bottle headers could not be read.')
    rules = sorted(e['x0'] for e in page.edges if e['orientation'] == 'v'
                   and e['top'] < cs['top'] and e['bottom'] > cs['bottom'])
    edges = []
    for x in rules:
        if not edges or x - edges[-1] > 1:
            edges.append(x)
    if len(edges) != len(FIELDS)+1:
        raise ValueError('Unsupported Southern Glazer\'s item columns.')
    return edges


def delivered(value):
    if not value:
        return Decimal(0)
    match = re.fullmatch(r'(-?\d+)/(-?\d+)', value.strip())
    if not match:
        raise ValueError('Southern Glazer\'s ordered/delivered quantity could not be read.')
    return Decimal(match[2])


def pack_code(raw):
    if not re.fullmatch(r'\d+(?:-\d+)*', raw):
        return '', 'UPC is missing or unreadable; enter the retail PACK UPC manually.'
    try:
        code = normalize_pack_upc(raw.replace('-', ''))
    except ValueError:
        return '', 'Printed UPC cannot be normalized to 12 digits using leading zeros only; verify the retail PACK UPC manually.'
    check = (-sum(int(n)*(3 if i % 2 == 0 else 1) for i,n in enumerate(code[:-1]))) % 10
    if check != int(code[-1]):
        return '', 'Printed UPC fails its check digit; verify the retail PACK UPC manually.'
    return code, ''


def page_items(page, edges):
    groups = group_rows(page)
    found = []
    previous_anchor = -1
    for index, chars in enumerate(groups):
        row = columns(chars, edges)
        metadata = re.fullmatch(r'ITEM#:\s*(\S+)\s+BPC:\s*(\d+)\s+SIZE:\s*(.*)', row['description'])
        if not metadata:
            continue
        # The merchandise amount belongs to the preceding main row; the ITEM#
        # row may additionally print per-bottle reference prices, not new lines.
        main = None
        for before in range(index-1, previous_anchor, -1):
            if chars[0]['top']-groups[before][0]['top'] > 45:
                break
            candidate = columns(groups[before], edges)
            if candidate['description'] and all(re.fullmatch(r'-?[\d,]+\.\d{2}', candidate[f])
                    for f in ('unit_cost','unit_discount','net_unit','taxes','extended_price')):
                main = (before, candidate)
                break
        if main is None:
            raise ValueError('Southern Glazer\'s item header has no readable charged row.')
        before, candidate = main
        wrapped = [columns(g, edges)['description'] for g in groups[before+1:index]]
        candidate['description'] = ' '.join([candidate['description'], *filter(None, wrapped)])
        candidate.update(product_number=metadata[1], bpc=metadata[2], size=metadata[3],
                         per_bottle_reference={f:row[f] for f in ('unit_cost','unit_discount','net_unit')},
                         main_index=before, anchor_index=index)
        found.append(candidate)
        previous_anchor = index
    for index, item in enumerate(found):
        end = found[index+1]['main_index'] if index+1 < len(found) else len(groups)
        # Stop at summary/legal sections. Do not interpret their dollar amounts
        # or dates as item prices, UPCs or CRV rows.
        block = []
        for group in groups[item['anchor_index']+1:end]:
            line = text(group)
            if line.startswith(('TOTAL CS/BTLS', 'TERMS AND CONDITIONS', 'Page ')):
                break
            block.append(group)
        item.update(barcode_raw='', crv_unit='0', crv_total='0')
        for group in block:
            values = columns(group, edges)
            upc = re.fullmatch(r'(CRV\s*/\s*)?UPC:\s*(\S+)', values['description'])
            if upc:
                if item['barcode_raw']:
                    raise ValueError('Conflicting UPC rows for a Southern Glazer\'s item.')
                item['barcode_raw'] = upc[2]
                if upc[1]:
                    item['crv_unit'] = str(money(values['unit_cost']))
                    item['crv_total'] = str(money(values['extended_price']))
        item['notes'] = '\n'.join(text(g) for g in block if 'UPC:' not in text(g))
        item.pop('main_index');item.pop('anchor_index')
    # A damaged metadata row must not silently drop an item.
    printed_anchors = sum(1 for w in page.extract_words() if w['text'] == 'ITEM#:')
    if printed_anchors != len(found):
        raise ValueError('Some Southern Glazer\'s item metadata could not be read; check the PDF.')
    return found


def labeled_tables(page):
    values = {}
    for table in page.extract_tables():
        if len(table) < 2:
            continue
        for index, label in enumerate(table[0]):
            label = ' '.join((label or '').split())
            value = table[1][index] if index < len(table[1]) else None
            if not value:
                continue
            if label in ('INVOICE DATE', 'ACCOUNT #', 'PAYMENT DUE DATE', 'PAY THIS AMOUNT'):
                values[label] = value.strip()
            elif label.startswith('TOTAL NET AMOUNT'):
                values['TOTAL NET AMOUNT'] = value.strip()
            elif label == 'SOLD TO:':
                values['retailer'] = value.splitlines()[0].strip()
    return values


def extract_invoice(pdf):
    first = pdf.pages[0].extract_text() or ''
    if ('Southern Glazers Wine and Spirits of California South' not in first
            or 'arsocal@sgws.com' not in first):
        continuation=(re.search(r'^CUSTOMER:\s*\d+.*INVOICE$',first,re.MULTILINE)
                      and 'ITEM#:' in first and 'BPC:' in first
                      and re.search(r'Page\s+[2-9]\d*\s+of\s+\d+',first))
        if 'shop.sgproof.com/termsOfUse' in first or continuation:
            raise ValueError('Southern Glazer\'s first page is missing or out of order; upload the complete invoice.')
        return None
    number = page_invoice_number(pdf.pages[0])
    labels = labeled_tables(pdf.pages[0])
    if not labels.get('INVOICE DATE') or not labels.get('ACCOUNT #'):
        raise ValueError('Southern Glazer\'s invoice date or account number could not be read.')
    header = dict(supplier=SUPPLIER, invoice_number=number, invoice_date=iso(labels['INVOICE DATE']),
                  customer_id=labels['ACCOUNT #'], due_date='', invoice_total='')
    if labels.get('retailer'):
        header['retailer'] = labels['retailer']
    edges = item_edges(pdf.pages[0])
    lines, details, excluded, fee_lines, texts, page_ids = [], [], [], [], [], []
    fees = {'crv_tax':Decimal(0), 'delivery_charge':Decimal(0)}
    warnings = ["Southern Glazer's quantities use delivered CA (cases) or BO (bottles), not ordered quantities. Source BPC and per-bottle reference prices are retained; retail pack conversions are not assumed."]
    total = None
    pay_amount = None
    for index, page in enumerate(pdf.pages, 1):
        if page_invoice_number(page).lstrip('0') != number.lstrip('0'):
            raise ValueError('Upload one Southern Glazer\'s invoice at a time.')
        content = page.extract_text() or ''
        texts.append(content)
        page_id = re.search(r'\bPage\s+(\d+)\s+of\s+(\d+)\b', content)
        if not page_id:
            raise ValueError('Southern Glazer\'s page count is missing; upload the complete invoice.')
        page_ids.append((int(page_id[1]),int(page_id[2])))
        account = re.search(r'CUSTOMER:\s*(\d+)', content)
        if account and account[1].lstrip('0') != header['customer_id'].lstrip('0'):
            raise ValueError('Southern Glazer\'s customer account changes across pages.')
        values = labeled_tables(page) if index != 1 else labels
        if values.get('TOTAL NET AMOUNT'):
            amount = money(values['TOTAL NET AMOUNT'])
            if total is not None and total != amount:
                raise ValueError('Conflicting Southern Glazer\'s invoice totals.')
            total = amount
        if values.get('PAY THIS AMOUNT'):
            pay_amount = str(money(values['PAY THIS AMOUNT']))
        if values.get('PAYMENT DUE DATE'):
            due = iso(values['PAYMENT DUE DATE'])
            if header['due_date'] and header['due_date'] != due:
                raise ValueError('Conflicting Southern Glazer\'s due dates.')
            header['due_date'] = due
        for item in page_items(page, edges):
            item['page'] = index
            cases, bottles = delivered(item['cases']), delivered(item['bottles'])
            charged = money(item['extended_price'])
            crv = money(item['crv_total'])
            if cases == bottles == 0:
                if charged or crv:
                    raise ValueError('Charged Southern Glazer\'s line has no delivered quantity; review manually.')
                excluded.append(dict(product_number=item['product_number'],description=item['description'],
                    quantity='0',amount='0.00',reason='Not delivered / not charged',source_details=item))
                continue
            if item['description'].strip().upper() == 'DELIVERY CHARGE':
                fees['delivery_charge'] += charged
                fees['crv_tax'] += crv
                fee_lines.append(item)
                continue
            mixed = bool(cases and bottles)
            upc, note = pack_code(item['barcode_raw'])
            item.update(normalized_upc=upc, note=note)
            details.append(item)
            if note:
                warnings.append(f"Item {item['product_number']}: {note}")
            if mixed:
                warnings.append(f"Item {item['product_number']}: mixed case/bottle line requires manual quantity, unit and price review.")
            quantity = cases or bottles
            lines.append(dict(product_number=item['product_number'],description=item['description'],
                upc=upc,pack_upc=upc,case_upc='',quantity='' if mixed else str(quantity),
                unit_of_measure='' if mixed else 'CA' if cases else 'BO', ppc=item['bpc'],
                unit_cost='' if mixed else str(money(item['unit_cost'])),
                discount='' if mixed else str(-money(item['unit_discount'])*quantity),
                adjustments=str(money(item['taxes'])),extended_price=str(charged)))
            fees['crv_tax'] += crv
    if page_ids != [(i,len(pdf.pages)) for i in range(1,len(pdf.pages)+1)]:
        raise ValueError('Southern Glazer\'s pages are missing, duplicated or out of order; upload the complete invoice.')
    if not lines or total is None:
        raise ValueError('Southern Glazer\'s merchandise or invoice total could not be read.')
    header['invoice_total'] = str(total)
    goods = sum(money(line['extended_price']) for line in lines)
    difference = total-goods
    if difference:
        warnings.append(f'CRV and delivery remain invoice-level charges ({sum(fees.values()):.2f}), separate from merchandise. Review and acknowledge the invoice/line difference before saving.')
    if difference != sum(fees.values()):
        warnings.append(f'Unexplained invoice difference: {difference-sum(fees.values()):.2f}. Check missing lines and charges before saving.')
    if excluded:
        warnings.append(f'{len(excluded)} undelivered/uncharged item(s) excluded from purchases and new-item checks.')
    header['source_info'] = dict(supplier_format=FORMAT,barcode_details=details,excluded_lines=excluded,
        invoice_charges={k:str(v) for k,v in fees.items()},charge_lines=fee_lines,
        merchandise_total=str(goods),pay_this_amount=pay_amount)
    return dict(kind='pdf',header=header,lines=lines,text='\n\n'.join(texts),warnings=warnings)
