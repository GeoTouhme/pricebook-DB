# Price book database

SQLite database built from the supplied price book: 9,775 products, 91 departments.
Requires Python 3; no external packages, credentials, or database server.

## Build and validate

From this repository directory:

```sh
python3 import_pricebook.py
python3 -m unittest discover -s tests -v
```

The database is generated at `data/pricebook.sqlite3`. To import another price book:

```sh
python3 import_pricebook.py /path/to/pricebook.csv --database data/pricebook.sqlite3
```

Identical files are skipped using SHA-256. Changed files update matching UPCs
and retain original import rows; products absent from a later file are retained.
A failed import rolls back its data changes. The expected CSV structure is the
29-column supplied export. Duplicate or blank UPCs within an import are rejected.

## Data model and interpretation

- `products`: latest imported catalog, keyed by text UPC to retain leading zeros.
- `departments`: source department names, without speculative merging.
- `imports` and `pricebook_rows`: source filename, checksum, import time, and every
  original field for traceability, including POS button settings and pack fields.
- `inventory_snapshots`: reserved for future inventory by product, source,
  location, and observation time. Quantities use decimal text to avoid rounding.
- `sales_lines`: reserved for future dated sales, quantities, currency, and monetary
  amounts in integer cents. Source row keys prevent duplicate future ingestion.
- `product_catalog`: convenient join with department and calculated unit price.

`cents` is the price for `qty` units; original integers are retained. The calculated
unit price is for display and is not a rounded accounting amount. Currency is
not supplied by the price book and has not been assumed. `cost_cents` and
`cost_qty` are retained as supplied; zero cost is not evidence of zero actual cost.
Blank EBT remains unknown. Excel wrappers such as `="000123"` are removed only
in the parsed values; raw values remain available in `pricebook_rows`.

`setstock` is stored as `pricebook_stock`, including negatives. It is not labeled
as live website inventory. The import timestamp is not the inventory observation
date. No sales, profit, or stock availability is invented from the price book.

## Query example

```python
import sqlite3
with sqlite3.connect('data/pricebook.sqlite3') as db:
    rows = db.execute('''SELECT upc, name, department, price_cents, price_qty
                         FROM product_catalog ORDER BY name LIMIT 20''').fetchall()
    print(rows)
```

## Next sheets

Upload the website inventory and sales exports when available. Their importers
must be mapped to the actual headers before populating the reserved tables.
Inventory needs a UPC or confirmed SKU-to-UPC mapping, quantity, location, and
snapshot date. Sales needs a product identifier, sale date (or reporting period),
quantity, net sales amount, currency, and preferably stable order/line identifiers.
Monthly aggregate sales require a separate monthly-summary table rather than
invented transaction dates. Keep unmatched SKUs for review instead of matching
products by name alone. Confirm returns, discounts, taxes, and date/time conventions
before calculating trends or margins. Future website inventory credentials are
not needed to import files.

## Website inventory import

```sh
python3 import_website_inventory.py data/website-inventory_2026-10-13.csv --snapshot-date 2026-10-13
```

The snapshot date comes from the supplied filename, not an embedded timestamp;
no time of day is inferred. All 8,746 rows and original fields are retained in
`website_inventory_rows`. Exact UPC matching links 8,727 rows; 19 unmatched rows
remain with a null `matched_upc` for review. No padding, truncation, name matching,
or product creation is performed. Linked rows also populate `inventory_snapshots`.
Website prices remain separate from price book prices. Blank prices are NULL,
not zero. Stock is website-reported: 8,745 rows say 100 and one says 98; this
pattern may reflect website defaults rather than physical inventory.
Identical files are skipped; reimporting identical contents under another date
is rejected. Different files are retained as independent snapshots, not added
together. Inspect `data/website_unmatched.csv` for the current unmatched list.

## Daily sales import and coverage

```sh
python3 import_daily_sales.py data/itemsales_by_day.csv
```

The supplied file contains 78,592 daily report rows on all 104 dates from
2026-05-01 through 2026-08-12. The intended period is January–August 2026;
January–April and August 13–31 are missing, not zero sales.
77,007 rows link to catalog products by exact UPC; 1,585 remain unmatched,
including 527 blank-code rows. There are 45 distinct nonblank unmatched codes.
All rows and original fields are preserved in `daily_sales_rows`; nothing is
inserted into transaction-level `sales_lines`. A date/UPC pair is not unique
in this export, so rows are preserved individually rather than collapsed.

`Sales $` and `Scan Sales` are stored separately as integer cents, with the
report's quantity, basket count, averages, and scan rate retained. Their tax,
fee, discount, and currency semantics have not been confirmed. Negative amounts
and quantities are retained. Tax, cash-back, lottery, fee, and other internal
rows must not automatically be treated as merchandise revenue. Basket counts
are per report row and must not be summed to estimate unique orders.
The raw sum of `Sales $` is 1,242,283.53 and `Scan Sales` is 1,132,739.25;
these are reconciliation totals, not a claim of net merchandise revenue.

Identical files are skipped. Different files with any overlapping imported dates
are rejected to prevent double counting; review and an explicit replacement or
merge policy are needed for corrected or overlapping exports. Future files may
be imported directly when their dates do not overlap. The review file
`data/sales_unmatched.csv` groups unmatched codes by department and item.

### September–October report

```sh
python3 import_daily_sales.py 'data/itemsales_by_day 9-10.csv'
```

This file adds 31,234 rows covering September 1–October 15, 2026 (45 dates).
October 15 contains only 24 report rows and may be partial. US-style dates are
normalized to ISO dates; original dates remain in raw JSON. Accounting parentheses
are parsed as negative monetary amounts. All original fields are retained.
Only 52 rows match catalog UPCs exactly. 14,167 rows contain scientific-notation
codes, which may have lost significant digits, and many other codes appear to
have lost leading zeros. No scientific expansion, padding, truncation, or name
matching is applied. The remaining 31,182 rows are retained without product links.
Re-export from the original POS with full UPCs stored as text for reliable links;
formatting an already rounded CSV as text cannot restore lost digits. A corrected
report overlaps existing dates and must replace/reconcile this import explicitly
rather than be added again. Review `data/sales_9_10_unmatched.csv`.

Current combined coverage is May 1–August 12 and September 1–October 15, 2026.
January–April and August 13–31 are still absent; missing dates are not zero sales.

### Corrected September–October file (current database)

`data/itemsales_by_day 9-10 corrected.csv` supersedes the original September–October
import. Every non-UPC field and row order was verified identical before replacement.
The original file is retained for comparison; it is no longer counted in the database.
The corrected file links 16,311 rows exactly; 14,923 remain unmatched, including
198 blank-code rows. Many scientific values were expanded to rounded digit strings
(e.g. `6.0925E+11` became `609250000000`), so full identifier recovery is incomplete.
The unmatched report has been refreshed. Combined sales row count remains 109,826,
and replacement preserves both monetary totals.

For a fresh database, import the corrected file instead of the original.
For an existing original import, use `--replace-sha256` with its source SHA-256;
replacement is atomic and accepts only a row-for-row UPC correction with all other
fields identical. An identical corrected file is skipped on repeat import.

## Fintech purchase invoices

```sh
python3 import_invoices.py data/invoices/*.csv
```

Ten supplied files contain nine distinct exports: `(8)` and `(9)` are identical.
The import retains 8,267 lines across 447 invoices/credits and 21 suppliers,
with invoice dates January 6–September 30, 2026. This date range does not prove
all purchases are included. Invoice totals sum to 676,642.69 including 65
negative-total documents; the files do not establish payment status or currency.

Tables: `suppliers`, `purchase_invoices`, `purchase_lines`, and
`purchase_source_rows`. All 27 original columns remain in source-row JSON.
Invoice totals, adjustments, and discounts are integer cents. Unit costs and
extended prices retain exact decimal text because some have sub-cent precision.
Quantities, unit-of-measure codes, PPC, UPCs, pack UPCs, references, and supplier
product numbers are preserved. No automatic case conversion, cost allocation,
stock receipt, or margin calculation is performed. Adjustments and discounts
are not added again to the supplied extended price.

Invoices are identified by supplier, retailer, customer, store, invoice number,
and invoice date; an invoice number in this dataset is reused on different dates.
Identical files are skipped by checksum. Identical whole invoices across different
exports are counted once, with source provenance preserved. Conflicting or partial
versions of an existing invoice are rejected for review; identical repeated lines
within a source invoice are retained. Imports are transactional per file.

1,265 lines match the catalog by exact `UPC Number`; 7,002 remain unlinked.
Pack barcodes and supplier product numbers are retained but not assumed equivalent
to retail UPCs. See `data/purchase_unmatched.csv` for mapping review.
`data/invoice_reconciliation.csv` lists 10 documents with differences between
invoice totals and exact decimal line sums. Some differences are fractions of a
cent; no amounts were altered to force reconciliation. A future dashboard should
sum invoice headers once for purchasing totals and keep them separate from sales.

## Dashboard

Five pages provide sales trends and filters, product lookup and history, inventory
comparison, supplier/invoice purchasing views, and data quality with CSV exports.
The dashboard reads SQLite in read-only mode and does not modify imported data.
It refreshes cached tables when the database file changes or when Refresh data is
clicked. It intentionally omits profit, live inventory, and unique-order estimates
because the current sources do not support them reliably.

To install pinned dependencies and reproduce the current database (safe to repeat):

```sh
bash /workspace/pricebook-DB/setup.sh
```

To start:

```sh
cd /workspace/pricebook-DB
/workspace/.venvs/pricebook/bin/python -m streamlit run dashboard.py --server.address 0.0.0.0 --server.port 8501
```

Use your hosting environment's application access facility for port 8501.
Streamlit is a development server with no application login configured; hosting
access controls are needed before making these business records publicly accessible.
Processes must be restarted in a new environment. A fresh database build imports
the corrected September–October report directly, omitting its superseded original.

Run all checks with the installed environment:

```sh
/workspace/.venvs/pricebook/bin/python -m unittest discover -s tests -v
```
