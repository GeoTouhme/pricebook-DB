"""Breakthru California final invoices: ruled columns and printed UPC-A digits.

No CASE UPC fallback or inferred barcode correction. Source units and invoice-level
charges remain separate from catalog matching and merchandise totals.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from pdfplumber.utils import extract_text

from purchase_matching import normalize_pack_upc

SUPPLIER = 'Breakthru Beverage California LLC'
FIELDS = ['cases', 'bottles', 'pieces', 'product_number', 'size', 'bpc',
          'description', 'list_price', 'unit_discount', 'net_price', 'net_bottle',
          'extended_price', 'deal']


def money(value):
    value = value.strip().replace('$', '').replace(',', '')
    if value.startswith('(') and value.endswith(')'):
        value = '-' + value[1:-1]
    try:
        number = Decimal(value)
        if not number.is_finite():
            raise InvalidOperation
        return number
    except InvalidOperation as exc:
        raise ValueError('Breakthru amount could not be read; check the source PDF.') from exc


def rows_of(chars):
    rows = []
    for char in sorted(chars, key=lambda c: (c['top'], c['x0'])):
        if not rows or abs(char['top'] - rows[-1][0]['top']) > 1.5:
            rows.append([])
        rows[-1].append(char)
    return rows


def cell(chars, left, right):
    selected = [c for c in chars if left <= (c['x0'] + c['x1']) / 2 < right]
    return extract_text(selected, x_tolerance=1, y_tolerance=2).strip() if selected else ''


def column_edges(page, words):
    # Use the known supplier's header to select the vertical rules, including
    # dotted rules that pdfplumber's default table finder can merge incorrectly.
    for word in words:
        if word['text'] != 'Case':
            continue
        header = [w['text'] for w in words if abs(w['top'] - word['top']) < 2]
        if not {'Btles', 'Pieces', 'Item', 'Size', 'BPC', 'Description', 'Sales'}.issubset(header):
            continue
        rules = sorted(e['x0'] for e in page.edges if e['orientation'] == 'v'
                       and e['top'] < word['top'] and e['bottom'] > word['bottom'] + 30)
        edges = []
        for x in rules:
            if not edges or x - edges[-1] > 1:
                edges.append(x)
        if len(edges) != len(FIELDS) + 1:
            raise ValueError('Unsupported Breakthru column layout; review the PDF manually.')
        return edges, word['bottom']
    raise ValueError('Breakthru item headers could not be read.')


def printed_upc(words, left, right, top, bottom):
    candidates = []
    barcode_words = []
    for middle in words:
        if not (top < middle['top'] < bottom and left <= middle['x0'] < right
                and re.fullmatch(r'\d{10}', middle['text'])):
            continue
        # UPC-A prints one outside digit at each end, slightly above the central ten.
        outer = [w for w in words if top < w['top'] < middle['top']
                 and 7 < middle['top'] - w['top'] < 16
                 and left <= w['x0'] < right and re.fullmatch(r'\d', w['text'])]
        before = [w for w in outer if w['x1'] < middle['x0']]
        after = [w for w in outer if w['x0'] > middle['x1']]
        if len(before) == len(after) == 1:
            raw = before[0]['text'] + middle['text'] + after[0]['text']
            candidates.append(raw)
            barcode_words.extend([before[0], middle, after[0]])
    if len(candidates) != 1:
        return '', '', barcode_words, 'Printed item UPC could not be uniquely read; enter PACK UPC manually.'
    raw = candidates[0]
    valid = (-sum(int(n) * (3 if i % 2 == 0 else 1) for i, n in enumerate(raw[:-1]))) % 10 == int(raw[-1])
    if not valid:
        return raw, '', barcode_words, 'Printed UPC fails its check digit; verify PACK UPC on the product. No digits were corrected.'
    return raw, normalize_pack_upc(raw), barcode_words, ''


def page_items(page):
    words = page.extract_words()
    edges, start = column_edges(page, words)
    footer = next((w['top'] for w in words if w['text'] == 'Cases' and w['top'] > start
                   and w['x0'] < edges[2]), page.height)
    items = []
    for chars in rows_of([c for c in page.chars if start < c['top'] < footer]):
        row = dict(zip(FIELDS, [cell(chars, l, r) for l, r in zip(edges, edges[1:])]))
        if re.fullmatch(r'\d{7}', row['product_number']):
            row['top'] = min(c['top'] for c in chars)
            items.append(row)
    for index, item in enumerate(items):
        bottom = items[index + 1]['top'] - 1 if index + 1 < len(items) else footer
        raw, upc, barcode_words, note = printed_upc(words, edges[6], edges[7], item['top'], bottom)
        continuations = [w for w in words if item['top'] + 2 < w['top'] < bottom
                         and edges[6] <= w['x0'] and w['x1'] < edges[7]
                         and w not in barcode_words]
        # Source words are top/left ordered by pdfplumber. Keep wrapped names,
        # vintage, and packaging, but never append barcode digits to descriptions.
        item['description'] += ''.join(' ' + w['text'] for w in continuations)
        item.update(barcode_raw=raw, upc=upc, barcode_note=note)
    return items


def footer_values(page):
    for table in page.find_tables():
        rows = table.extract()
        for index, row in enumerate(rows[:-1]):
            if not any((v or '').startswith('Cases Shipped') for v in row):
                continue
            result = {}
            values = rows[index + 1]
            for field, label in [('crv_tax', 'CRV Tax'), ('sweetener_tax', 'Sweetner Tax')]:
                at = next((i for i, v in enumerate(row) if (v or '').startswith(label)), None)
                if at is not None:
                    value = values[at] or ''
                    if not value:
                        # Merged sweetener/total cell can hold its value on a new line.
                        value = next((line for line in (row[at] or '').splitlines()[1:]
                                      if re.fullmatch(r'\d+(?:\.\d{2})?', line)), '')
                    if value:
                        result[field] = str(money(value))
            if re.fullmatch(r'\d+\.\d{2}', row[-1] or ''):
                result['invoice_total'] = str(money(row[-1]))
            return result
    return {}


def extract_invoice(pdf):
    first = pdf.pages[0].extract_text() or ''
    if 'Breakthru Beverage California' not in first or 'BBCA XML Final Invoice' not in first:
        return None
    number = re.search(r'Invoice\s*#:\s*(\d+)', first)
    issued = re.search(r'Invoice Date:\s*(\d{2}/\d{2}/\d{4})', first)
    if not number or not issued:
        raise ValueError('Breakthru invoice number or invoice date could not be read.')
    header = {'supplier': SUPPLIER, 'invoice_number': number[1],
              'invoice_date': datetime.strptime(issued[1], '%m/%d/%Y').date().isoformat(),
              'due_date': '', 'invoice_total': ''}
    due = re.search(r'Due Date:\s*(\d{2}/\d{2}/\d{4})', first)
    account = re.search(r'Customer\s*#:\s*(\d+)', first)
    if due:
        header['due_date'] = datetime.strptime(due[1], '%m/%d/%Y').date().isoformat()
    if account:
        header['customer_id'] = account[1]
    retailer = re.search(r'^(BALPORT LIQUOR)\s*$', first, re.MULTILINE)
    if retailer:
        header['retailer'] = retailer[1]
    lines, excluded, details, texts, fees = [], [], [], [], {}
    warnings = ['Breakthru quantities retain CA (cases) or BO (loose bottles). BPC is the supplier bottles-per-case reference, not a retail pack conversion. Check the printed item UPC against the retail PACK UPC, especially multipacks.']
    for page_number, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or ''
        texts.append(text)
        ids = re.findall(r'Invoice\s*#:\s*(\d+)', text)
        if any(i.lstrip('0') != number[1].lstrip('0') for i in ids):
            raise ValueError('Upload one Breakthru invoice at a time.')
        page_fees = footer_values(page)
        if page_fees:
            if fees and fees != page_fees:
                raise ValueError('Conflicting Breakthru invoice totals; review the document manually.')
            fees = page_fees
        for item in page_items(page):
            quantity_case = money(item['cases'] or '0')
            quantity_bottle = money(item['bottles'] or '0')
            source = {k: v for k, v in item.items() if k != 'top'}
            source['page'] = page_number
            if quantity_case == quantity_bottle == 0 and money(item['pieces'] or '0') == 0 and 'Out of Stock' in item['description']:
                excluded.append(dict(product_number=item['product_number'], description=item['description'],
                                     quantity='0', amount='0.00', reason='Out of stock; not shipped or charged'))
                continue
            details.append(source)
            if item['barcode_note']:
                warnings.append(f"Item {item['product_number']}: {item['barcode_note']}")
            mixed = bool(quantity_case and quantity_bottle)
            if mixed:
                warnings.append(f"Item {item['product_number']}: cases and loose bottles share a line; enter quantity, unit and price manually before saving.")
            lines.append(dict(product_number=item['product_number'], description=item['description'],
                upc=item['upc'], pack_upc=item['upc'], case_upc='',
                quantity='' if mixed else str(quantity_case or quantity_bottle),
                unit_of_measure='' if mixed else 'CA' if quantity_case else 'BO', ppc=item['bpc'],
                unit_cost='' if mixed else str(money(item['list_price'])),
                discount=str(-money(item['unit_discount']) * (quantity_case + quantity_bottle)),
                adjustments='0', extended_price=str(money(item['extended_price']))))
    if not lines:
        raise ValueError('No shipped Breakthru invoice lines could be read.')
    goods = sum(money(line['extended_price']) for line in lines)
    header['invoice_total'] = fees.pop('invoice_total', '')
    if not header['invoice_total']:
        warnings.append('Breakthru invoice total was not found. Enter the printed total manually.')
    else:
        difference = money(header['invoice_total']) - goods
        if difference:
            warnings.append(f'Invoice total includes {difference:.2f} beyond merchandise lines. CRV/taxes remain invoice-level charges; review and acknowledge the difference before saving.')
        if all(k in fees for k in ('crv_tax', 'sweetener_tax')) and sum(map(money, fees.values())) != difference:
            warnings.append('Invoice-level charges do not reconcile with merchandise. Review the printed totals before saving.')
    if excluded:
        warnings.append(f'{len(excluded)} out-of-stock, uncharged item(s) excluded from purchases and new-item checks.')
    header['source_info'] = dict(supplier_format='Breakthru California', printed_supplier='Breakthru Beverage California',
        printed_invoice_number=number[1], barcode_details=details, excluded_lines=excluded,
        invoice_charges=fees, merchandise_total=str(goods))
    return dict(kind='pdf', header=header, lines=lines, text='\n\n'.join(texts), warnings=warnings)
