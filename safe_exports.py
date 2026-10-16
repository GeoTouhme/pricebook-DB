"""Spreadsheet-facing exports; database/source values are never changed."""
def safe_cell(value):
    if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@'))
                                  or value.startswith(('\t', '\r', '\n'))):
        return "'" + value
    return value


def csv_bytes(frame):
    safe = frame.map(safe_cell)
    safe.columns = [safe_cell(c) for c in safe.columns]
    return safe.to_csv(index=False).encode('utf-8-sig')
