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

7,270 lines match the catalog using normalized `Pack UPC`; 997 remain unlinked.
Original UPC Number and Pack UPC values are retained. Only PACK UPC supplies
the automatic barcode match; CASE UPC is not substituted. See `data/purchase_unmatched.csv` for mapping review.
`data/invoice_reconciliation.csv` lists 10 documents with differences between
invoice totals and exact decimal line sums. Some differences are fractions of a
cent; no amounts were altered to force reconciliation. A future dashboard should
sum invoice headers once for purchasing totals and keep them separate from sales.

## Dashboard

Six pages provide sales trends and filters, product lookup and history, inventory
comparison, supplier/invoice purchasing views, and data quality with CSV exports.
Reporting pages read SQLite in read-only mode. New Items Review writes reviewed invoices only after explicit confirmation; existing imported data is preserved.
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

### Beer department grouping

In Overview, select **All Beer** under Sales departments for combined beer sales
across the historic department changes. It includes BEER, IPA BEER 1, SOUR BEER,
Craft / Local Beer, Domestic Beer, Import Beer, IPA Beer, Sour Beer, and Mexican
Beer. The mixed Non-Alcoholic Beer & Wine department remains separately selectable.
Selecting All Beer together with one of its member departments does not duplicate
rows. Source department names remain unchanged in the database, breakdowns, and
CSV exports. For all report rows, June 12 totals 1,582.79 and June 13 totals
2,097.16 across All Beer; BEER alone remains 1,019.27 and 202.97 respectively.

### Groups for all sales departments

Overview now offers 54 combined department groups, with explicit membership in
`department_groups.json`. Every currently imported sales department belongs to
one group. The original department options, chart breakdowns, and export values
remain available. Selecting multiple groups or a group plus its member uses the
union of matching rows, so each report row is counted once.

All Wine includes the wine varieties, general/organic/small-format wine, and
Champagne/sparkling departments. Non-Alcoholic Beer & Wine and Sake & Soju have
separate groups. Spirits are grouped by type (vodka, tequila, whiskey/scotch,
gin, rum, brandy/cognac, liqueur, shots, and other spirits). Drinks, food, tobacco,
accessories, fees, lottery, tax categories, and other source families also have
combined filters. Mixed source departments keep their existing contents;
grouping does not classify individual products, fix incorrect source categories,
or turn tax/cash-back/lottery totals into merchandise revenue. Ambiguous
NonAlcohol source departments are kept under All Unclassified Drinks.

For all report rows, All Wine totals 808.69 on June 12 and 1,938.02 on June 13.
New source department names remain individually selectable and should be reviewed
for addition to the mapping when new exports are imported.


## New Items Review: PDF and CSV invoice upload

On Windows, update the application and install the new PDF dependency:

```powershell
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

Choose **New Items Review** in the sidebar:

1. Upload one invoice PDF, or a Fintech CSV and select one invoice from it.
2. Check the invoice identity, dates, total, and extracted lines. All fields are
   editable before analysis; the line grid supports pasted cells and added rows.
3. Click **Check for new items**. Results distinguish catalog matches, suggestions,
   potential new items, and unreadable codes. Purchase history is shown separately.
4. Choose a decision for every line: link an existing catalog UPC, confirm a new
   item with its retail UPC, or keep the line unlinked. An existing-product link
   can optionally be remembered for this supplier item code, unit, and PPC.
5. Check the original document, acknowledge any total difference, then explicitly
   save. Only then are the invoice and lines added to Purchases.

Original documents are stored as BLOBs in SQLite alongside an audit of reviewed
values and decisions. Download them under Previously reviewed invoices. The
existing upload checksum and supplier/store/invoice/date identity protect against
repeat imports, including an invoice already imported through the Fintech CSV
workflow. A review and all its purchase, mapping, and candidate records commit
atomically. Mapping conflicts are rejected without partially saving an invoice.
Repeated lines within a valid invoice are preserved.

New-item confirmations appear in the pending catalog list and its CSV download.
They do **not** create a priced catalog product: retail pricing, department, and
unit-cost setup are still needed before adding them to the price book. Purchases
are not treated as received stock. Document totals are counted once; no
case-to-unit conversion or profit calculation is inferred.

PDF extraction runs locally using pdfplumber, without an external AI service or
credentials. It recognizes ruled tables with identifiable description, quantity,
and amount headers, plus the Fintech invoice-report layout with a ruled header
and unruled, wrapped item rows. That layout is regression-tested against the
supplied seven-line Breakthru invoice. Other layouts can require manual entry
and verification. Scanned/image-only PDFs
need manual entry or a Fintech CSV; OCR is not configured. Every PDF extraction is
an editable draft, including codes, prices, pack sizes, and totals. A preview can
show the PDF and extracted text. Uploaded files are limited to 20 MB and PDFs to
100 pages. No document content is executed.

Name similarity, pack barcodes, and historical supplier links are suggestions;
only an exact normalized PACK UPC or an explicitly remembered supplier/pack mapping is
linked automatically. Historical purchases with no catalog match remain distinct
from genuinely new catalog candidates. Scientific notation, missing barcodes,
and pack-vs-retail ambiguity require review.

New records live in `invoice_reviews`, `supplier_product_mappings`, and
`catalog_candidates`, alongside the existing purchase/import tables. The schema
is created additively on first reviewed save; existing databases need no reset.
Keep backups of `data/pricebook.sqlite3`: it now contains original uploaded
invoices and user-confirmed mappings that rebuilding from the original CSVs
alone cannot restore. These local records remain excluded from Git.


### Fintech PDF layout and matching corrections

The supported Fintech report fills supplier, bill-to retailer, invoice number,
invoice date, due date, and total directly from labeled document fields. It uses
the table header geometry to read body columns even when there are no vertical
body rules, joins wrapped descriptions, and keeps PRICE separate from final TOTAL.
CASE UPC is retained for reference and in the review audit. The matching UPC is
derived only from PACK UPC. Reviewed purchases store the normalized PACK UPC
in the source barcode field; raw PACK UPC remains separately available.

Items found in prior purchases but without a confirmed retail link are labeled
**Previously purchased**, even if they are missing from the price book. They are
not labeled potentially new merely because a case barcode differs from retail.
CASE UPC is not converted into a retail barcode or used as a fallback. Missing
PACK UPC needs review; supplier history and compatible names may still provide
suggestions, and explicitly confirmed supplier mappings remain available.
Name suggestions require compatible brand, wine variety, and flavor tokens;
for example, Merlot is not suggested for Pinot Noir, and watermelon is not
suggested for an unflavored margarita description. Unknown source layouts and
scans retain the editable/manual fallback.


### PACK UPC: 12-digit matching rule

Invoice matching uses **PACK UPC**, never CASE UPC. Values are kept as text.
For example, `00070897013315` becomes `070897013315`: remove only extra leading
zeros beyond 12 digits. Shorter digit-only values are left-padded to 12 digits.
Nonzero prefixes beyond 12 digits, letters, decimal values, and scientific notation
are flagged rather than truncated or guessed. Original document values remain
unchanged. A blank PACK UPC stays blank and is not replaced by CASE UPC.
New-item confirmations use 12-digit UPCs and check for an existing catalog item
after normalization. Existing price-book UPCs are not rewritten.

To update automatic matches in an existing Windows database, stop Streamlit and run:

```powershell
git pull
.\.venv\Scripts\python.exe purchase_matching.py
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

The refresh command is idempotent. It updates only original CSV automatic links;
explicitly reviewed invoice links, raw source values, quantities, and monetary
amounts are preserved. The cloud setup script also runs this refresh step.
The seven-line sample PDF has no PACK UPC values, so its rows need review or a
confirmed supplier mapping; the app does not substitute its populated CASE UPCs.

### Wrapped PACK UPCs in multi-page PDFs

The Fintech parser reassembles barcode fragments within each item before applying
12-digit normalization. For example, a PACK UPC printed as `0007089701` followed
by `3315` on the next line is read as `00070897013315`, then matched as
`070897013315`. It assigns characters to header-defined columns before forming
words, preventing touching CASE/PACK, PACK/quantity, and description/CASE text
from merging into the wrong field. CASE UPC remains reference-only.

The supplied five-page Harbor report is regression-tested for all 81 lines,
including zero quantities, wrapped descriptions, full PACK UPCs, a quantity of
14 beside a barcode, and exact reconciliation to 7,014.88. Saved extraction
sessions are versioned so pre-fix truncated results are read again after updating.
This correction affects extraction and does not post the sample invoice or alter
previously saved invoices; any previously saved incorrect values require review.

### Saving a reviewed invoice

Step 4 lists every line whose decision, UPC, or saved-mapping choice needs
attention, using line numbers that match the decision editor. Save becomes
available after those issues are resolved, the original-document review box is
checked, and any invoice-total difference is acknowledged. Press Enter or leave
a grid cell to apply its latest edit before checking readiness.

The page displays a saving indicator and a receipt containing the actual invoice
number, supplier, amount, purchase record ID, and line count. This confirmation
survives reruns and navigation during the browser session. **View in Purchases**
opens the purchasing page. The same successfully saved upload cannot be submitted
again from the review page. Failed attempts show a persistent explanation at the
top and beside Save, while retaining the review for correction or retry. Duplicate
and database errors are reported explicitly; they do not produce a success receipt.
Previously reviewed invoices and their original documents remain available from
the database after a browser/session restart.

### Mercaso invoices

New Items Review also recognizes the Mercaso invoice layout. Update dependencies
before using its barcode decoder:

```powershell
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

Only fulfilled/charged product lines enter purchase and new-item review. Lines
under **Unfulfilled and not charged** are displayed separately and retained in
source metadata, without becoming purchases. Their exclusion state is carried
across continued pages. Invoice Total is used for reconciliation; Paid, Amount
Due, the unfulfilled subtotal, and price-change notices are not added to purchases.

Mercaso's **Code** column contains barcode graphics rather than Fintech's PACK UPC
text column. The local ZXing decoder reads each product barcode within its own
column/row region. A verified UPC-E symbol is expanded to its checksum-validated
12-digit UPC-A, rather than zero-padding the compressed code. For this sample,
`00985234` (UPC-E) becomes `009800000524`, matching the existing Kinder product.
Original decoded values and barcode formats remain in the saved source metadata.
An unreadable, ambiguous, or unsupported barcode stays blank for review; short
PDF text fragments are not guessed into a product identifier. CASE UPC is not used.

Price / Case is retained as unit cost, Case Qty as quantity, and the printed pack
count as PPC when explicitly present in the description. Price / Each is preserved
as a reference, not multiplied to reconstruct a rounded case cost. Per-case CRV
and discounts are scaled by case quantity; final line Amount is retained exactly.
No stock receipt or product price/cost update is inferred.

The sample M-303112 contains one fulfilled Kinder Joy case (20 Pack) at 27.49 and
seven unfulfilled Axe units totaling 23.03. Only the Kinder line is posted after
confirmation. Invoice Total and Paid are 27.49, while Amount Due is 0.00. Mercaso
provides an Order Date rather than a separately labeled invoice date, so the
Order Date is proposed in the editable invoice-date field with a warning to
verify it. A due date is left empty when none is supplied. Supplier metadata,
barcode provenance, excluded lines, and payment summary are stored with the review
and original PDF. Tests exercise the supplied document through extraction,
matching, reviewed saving, duplicate rejection, and the dashboard receipt.
