"""Read-only product lookup across catalog and invoice lines, including unlinked items."""
from decimal import Decimal, InvalidOperation
import json
import re
from purchase_matching import pack_upc_or_blank


def compact(text):
    return ''.join(c for c in str(text).casefold() if c.isalnum())


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def prepare_history(lines, invoices):
    history = lines.merge(invoices[['id', 'invoice_date', 'invoice_number', 'supplier', 'supplier_id']],
                          left_on='invoice_id', right_on='id', suffixes=('', '_invoice'), validate='many_to_one')
    history['_pack'] = history.pack_upc.map(pack_upc_or_blank)
    history['_matched'] = history.matched_upc.fillna('').astype(str)
    history['_key'] = [item_key(row) for row in history.to_dict('records')]
    return history


def item_key(row):
    if row['_matched']:
        return 'upc:' + row['_matched']
    if row['_pack']:
        return 'upc:' + row['_pack']
    # Missing codes never group unrelated items together. Supplier item codes
    # retain their scope; without one, description and pack identify the source.
    code = str(row.get('product_number') or '').strip()
    identity = [str(row['supplier_id']), code, str(row['unit_of_measure']), str(row['ppc'])]
    if not code:
        identity.append(str(row['description']))
    return 'supplier:' + json.dumps(identity, ensure_ascii=False)


def find_items(query, products, history):
    query = query.strip()
    if not query:
        return []
    if query.startswith('="') and query.endswith('"'):
        query = query[2:-1]
    digits = re.fullmatch(r'[0-9]+', query) is not None
    upc = pack_upc_or_blank(query) if digits and len(query) >= 8 else ''
    tokens = [compact(t) for t in query.split() if compact(t)]
    catalog = products.set_index('upc').to_dict('index')
    source = {}
    for row in history.to_dict('records'):
        source.setdefault(row['_key'], row)
    keys = set()
    for code, product in catalog.items():
        if digits:
            match = code == query or bool(upc and code == upc)
        else:
            text = compact(str(product.get('name') or '') + ' ' + str(product.get('size') or ''))
            match = bool(tokens) and all(t in text for t in tokens)
        if match:
            keys.add('upc:' + code)
    for row in history.to_dict('records'):
        if digits:
            # Only PACK UPC and confirmed catalog links are product identifiers.
            # A CASE UPC (source_upc) is never substituted.
            match = (row['_matched'] == query or bool(upc and row['_matched'] == upc)
                     or (not row['_matched'] and bool(upc) and row['_pack'] == upc)
                     or str(row['product_number']).strip() == query)
        else:
            text = compact(row['description'])
            match = (str(row['product_number']).strip().casefold() == query.casefold()
                     or (bool(tokens) and all(t in text for t in tokens)))
        if match:
            keys.add(row['_key'])
    results = []
    for key in keys:
        code = key[4:] if key.startswith('upc:') else ''
        product = catalog.get(code)
        line = source.get(key, {})
        results.append(dict(key=key, upc=code, catalog=product is not None,
            name=product['name'] if product else line.get('description', ''),
            size=product.get('size', '') if product else '',
            supplier=line.get('supplier', ''), product_number=line.get('product_number', '')))
    return sorted(results, key=lambda r: (not r['catalog'], r['name'].casefold(), r['upc'], r['key']))


def item_history(history, key):
    result = history[history['_key'].eq(key)].copy()
    return result.sort_values(['invoice_date', 'invoice_id', 'id'], ascending=False)


def purchase_summary(history):
    amounts = [number(v) for v in history.extended_price]
    quantities = [number(v) for v in history.quantity]
    credits = [(a is not None and a < 0) or (q is not None and q < 0) for a, q in zip(amounts, quantities)]
    positive = [i for i, (a, q) in enumerate(zip(amounts, quantities))
                if a is not None and q is not None and a >= 0 and q > 0]
    return dict(invoice_count=history.invoice_id.nunique(), credit_lines=sum(credits),
                net_total=sum((v for v in amounts if v is not None), Decimal(0)),
                latest=history.iloc[positive[0]] if positive else None)


def history_export(history):
    columns = {'invoice_date':'Invoice date', 'invoice_number':'Invoice number', 'supplier':'Supplier',
        'product_number':'Supplier item code', 'description':'Invoice description',
        'quantity':'Invoice quantity', 'unit_of_measure':'Invoice unit', 'ppc':'Source PPC / BPC',
        'unit_cost':'Cost per invoice unit', 'discount_cents':'Discount (cents)',
        'adjustments_cents':'Adjustments (cents)', 'extended_price':'Line total',
        'pack_upc':'Original PACK UPC', 'matched_upc':'Confirmed catalog UPC'}
    result = history[list(columns)].rename(columns=columns).copy()
    result['Invoice date'] = result['Invoice date'].dt.strftime('%Y-%m-%d')
    return result
