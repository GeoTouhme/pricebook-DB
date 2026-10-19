# Price book database

SQLite database built from the supplied price book: 9,775 products, 91 departments.
The CSV import scripts use Python 3 and SQLite. The dashboard requires the pinned dependencies and two local admin accounts; see [secure Ubuntu setup](SECURITY.md).

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

### Southern Glazer's California invoices

New Items Review recognizes the Southern Glazers Wine and Spirits of California
South layout across its merchandise and terms pages. Upload the complete PDF in
page order. Missing, duplicated, reordered, or mixed-invoice pages are rejected.
Invoice date, account, due date and the printed **TOTAL NET AMOUNT** are prefilled;
**PAY THIS AMOUNT** is retained separately as a source reference.

Only delivered quantities from **CS ORD/DLV** and **BTLS ORD/DLV** become purchase
quantities. Per-bottle reference prices beneath each item are not separate lines.
Case/bottle units and source BPC are preserved. Ordered-but-undelivered, backordered,
and otherwise uncharged zero-delivery items are excluded from purchases and
new-item matching. Mixed case/bottle rows require manual quantity/unit review.

Hyphenated item UPCs are normalized to 12-digit PACK UPCs and their check digits
are validated. A nonzero-prefix 13-digit barcode is retained in source details and
left blank for manual retail-UPC review; it is never truncated. CASE UPC is not a
fallback. A charged delivery-fee row is stored as an invoice-level source charge,
not a new catalog item. CRV uses the **printed total CRV**, rather than recalculating
it from reference unit rates. Product line totals retain their printed merchandise
amounts, so saving requires acknowledgement of the documented CRV/delivery gap.
Source details, promotions, charge rows, rejected items and the original PDF remain
in the reviewed-invoice audit. Duplicate checks also compare normalized supplier
account/invoice identifiers against prior Fintech imports.

### Breakthru California invoices

New Items Review recognizes Breakthru Beverage California **BBCA XML Final Invoice**
PDFs. It prefills invoice dates, due dates, the supplier account and printed totals.
Cases (`CA`) and loose bottles (`BO`) retain their source quantities and unit prices;
BPC remains a supplier bottles-per-case reference. The original size, pieces,
net prices and printed barcode digits remain in the source-details expander.
Review the retail PACK UPC for multipacks; BPC is not a retail pack conversion.

The printed UPC-A digits are joined across their separate PDF baselines and checked
before proposing a 12-digit PACK UPC. Invalid or ambiguous barcodes stay blank and
require review; no CASE UPC or guessed digit is substituted. Wrapped descriptions
and leading zeros are preserved. Zero-quantity out-of-stock lines are excluded from
purchases and new-item checks. Mixed case/bottle rows require manual unit review.

CRV and sweetener taxes remain invoice-level source charges, separate from product
lines. The printed invoice total is preserved; saving requires the existing explicit
acknowledgement of any difference from merchandise totals. A Breakthru PDF is also
checked against existing supplier-account invoice numbers with leading zeros ignored,
so a prior Fintech export cannot be re-added because of different display labels.
Original PDFs are retained only after the user reviews and saves the invoice.

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

### Dashboard appearance

On phones, use the **Page** selector above the page title to navigate. Filters,
charts, and statistic cards stack vertically, with larger touch controls and
full-width action buttons. Wide tables can be scrolled horizontally to see all
columns. The sidebar remains available for account actions and data refresh.

Large catalog, inventory comparison, non-moving, and sales tables use 200-row
pages to reduce transfers on mobile connections. In **Sales data and download**,
enable **Show sales table** to load the sales preview. CSV downloads still
include all filtered rows and are generated on request, without rerunning the
dashboard. Closing an expander alone does not defer its contents in Streamlit.

The sales timeline's **Chart detail** control defaults to **Auto**: daily for
up to 31 days, weekly for up to 180 days, and monthly for longer selections.
Choose **Daily** for individual dates. Bar details show the selected period's
dates and reporting coverage. Totals only include the selected date range;
missing reports remain missing, and edge weeks or months may be partial.

Overview also includes **Non-moving items · review before reordering**, using
the selected dates and current catalog department filters. It lists catalog
items without positive recorded quantity, Sales $, or Scan Sales in that range,
regardless of the chart measure or report-row filter. By default it shows only
positive price-book stock, highest stock first, with search and a CSV download.
Last recorded sale uses available exact-UPC sales through the selected end date.
Returns do not cancel evidence of a purchase. Missing reports, unmatched UPCs,
new listings, and unavailable items require review; this list does not prove
zero customer demand. Price-book stock has no confirmed count date.

Open the top-right **⋮ → Settings** menu and select **Dark**, **Light**, or
**Use system setting** in the appearance controls. Streamlit
remembers the selection in this browser. **Light** uses the original
blue and white palette; **Dark** uses a navy palette. Both palettes are defined
in `.streamlit/config.toml` so the native theme selector remains available.
Restart Streamlit and refresh the browser if the selector is missing after updating.
Charts, tables, inputs, the sidebar, and statistic cards
follow the selected theme; navigation and animated counters keep their behavior.

### Upload updated catalog and website inventory

Open **Data imports** in the sidebar, choose **Price book** or **Website inventory
snapshot**, then upload the same CSV export format as the original source.
For website exports, explicitly choose the snapshot date. Click **Validate and
preview**, review the counts and sample, check the confirmation box, and click
**Save import**. Every row is validated against a temporary database copy first.
A SQLite backup is created in `data/backups/` before saving; successful saves
refresh the dashboard automatically. Exact duplicate uploads do not add records.

Price books update existing UPCs and add new products, including source prices,
costs, department, and price-book stock. Missing products are retained and source
UPC text is preserved. Website uploads add dated stock observations separately
from price-book stock and preserve earlier snapshots. A different file for an
already occupied snapshot date is rejected to avoid counting the same date twice;
replacing a saved snapshot is not supported. Uploads do not delete historical
sales or invoices. CSV uploads are limited to 20 MB.

### August sales gap filled (October 16 update)

`data/itemsales_aug13_aug31.csv` adds 14,613 rows for **August 13–31, 2026**
(19 dates), totaling **$227,951.72 Sales $** and **$217,815.15 Scan Sales**.
14,298 rows match catalog UPCs exactly; 315 remain unlinked. January–April is
still missing. The earlier notes describing the August gap are superseded.

The unmodified supplied export is `data/itemsales_aug12_sep01_original.csv`.
It includes six metadata lines and overlapping August 12 / September 1 dates.
Only August 13–31 is imported; filtering and source hashes are recorded in
`data/itemsales_aug13_aug31_provenance.json`. August 12 has 668 incoming rows
versus 21 saved rows, with different values; September 1 has 12 incoming rows
versus 595 saved. Both overlapping dates are retained unchanged pending review.
August 12 and October 15 may be partial.

After pulling on an existing installation, import the gap with:

```powershell
.\.venv\Scripts\python.exe import_daily_sales.py data/itemsales_aug13_aug31.csv
```

Restart Streamlit (or click Refresh data). Repeating this command is safe and
will report `already_imported`. The cloud setup script also imports this file.

### August 12 correction

The subsequently supplied one-day export confirms **668 August 12 rows**,
**$10,460.68 Sales $**, and **$8,123.51 Scan Sales**. It replaces the 21 partial
rows ($141.81) previously retained for August 12; it does not add to them.
August 13 rows at the end of the supplied export are excluded. The original file
is `data/itemsales_aug12_original.csv`; the filtered import and provenance are
`data/itemsales_aug12.csv` and `data/itemsales_aug12_provenance.json`.

On Windows after `git pull`, run:

```powershell
.\.venv\Scripts\python.exe import_daily_sales.py data/itemsales_aug12.csv --replace-date 2026-08-12
```

Restart Streamlit or refresh data. This command is safe to repeat. Date replacement
requires a file containing only the explicitly selected date and runs atomically.
Every replaced row, including original source import IDs and raw source JSON, is
preserved in `sales_date_replacements`. Other dates remain unchanged. Cloud setup
runs the same correction. The previous August 12 partial-data warning is superseded.

### Delivery platforms

Open **Delivery platforms** in the sidebar. Expand **Upload platform reports**, select
DoorDash ZIPs and Uber Eats CSV/XLSX reports together, inspect the preview, confirm,
and choose **Save platform reports**. Saving creates a SQLite backup under
`data/backups/`; the original documents and their provenance stay in the private
database. No delivery source is added to POS sales, purchases, catalog, or inventory.

Run locally with the existing environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

On Ubuntu, from the repository directory:

```bash
git pull
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
python -m streamlit run dashboard.py --server.address 0.0.0.0 --server.port 8501
```

Original platform reports are private and are not included in Git. Upload them on
the new server through this page, or migrate the existing SQLite database while
both applications are stopped. Delivery tables are initialized on the first save.

The initial period is the observed overlap of the two platforms' operational order
reports. For the supplied October reports, this is **October 1–14, 2026** in
`America/Los_Angeles`. An observed row range does not prove full coverage. The upload
preview displays declared coverage separately from actual local row bounds. Dates
without rows are unknown; they are not synthesized as zero-sales days.

- **Sales / orders / basket:** DoorDash sales-by-order and Uber order-history
  completed orders, filtered by local placement date. Workflow IDs and normalized
  DoorDash order IDs join financial data; short Uber order numbers are not join keys.
- **DoorDash proceeds:** local transaction-date ledger net, excluding passed-through
  tax and deposits. The waterfall keeps discounts, commission, marketing and
  error/adjustment events. Payout statements use settlement dates separately.
- **Uber proceeds:** completed placement-cohort financial payouts before date-based
  ads and miscellaneous events. The Money tab separately shows these events and the
  mixed-ledger arithmetic net. It preserves refunds and disputes on the same workflow
  and flags unallocated miscellaneous fees. Proceeds are before product and operating
  costs; they are not profit or confirmed bank cash.
- **Products:** Uber uses item rows associated with the correct preceding financial
  event header within each workflow, avoiding order/item double counting. DoorDash
  product mix is aggregate source reporting over its full declared period, independent
  of the page date filter, and may include canceled sales. Names and sizes are retained.
- **Operations:** cancellations, failures, ratings with sample sizes, source-reported
  unavailable items, and scheduled offline minutes. Event-pause durations are not
  scheduled downtime. Accuracy-workbook counts and refund allocations remain
  source-specific when they contradict CSVs. Header-only reports mean no supplied
  metric, rather than proof of zero activity.

Source mapping: DoorDash detailed financial transactions are canonical; simplified
transactions and error/adjustment exports are provenance-only copies. Sales, payout,
product, promotion, wait, cancellation, and error reports remain separate facts.
Uber order-only detailed finance is canonical for money, mixed finance provides
items, order history provides operational counts, and payout summaries are separate.
Upload both Uber detailed finance and order history for complete comparisons; the
mixed item report alone does not replace the detailed financial ledger. XLSX is read
as an actual workbook using Python's standard library, with no Excel dependency.

Imports use Decimal arithmetic, bounded in-memory archives, and a transactional save.
Repeated files, equivalent ZIP members, and overlapping identical order/event facts
are idempotent. Conflicting revisions are blocked without overwriting saved data.
Aggregate/support reports with overlapping periods and ambiguous revised Uber
miscellaneous events require separate source review; there is no automatic revision
replacement UI. Non-overlapping aggregate report periods may be imported, and the
product chart labels its full source scope. Multiple stores are keyed separately in
storage; the current page aggregates the uploaded stores within each platform.

Reports and backups include personal data. Keep the database, backups, and original
reports private; only sanitized synthetic fixtures belong in Git. Daily aggregates
can be downloaded as CSV and the short HTML owner summary can be printed in a browser.

Run synthetic and Streamlit tests:

```bash
python -m unittest discover -s tests -v
```

To additionally validate the original private October reports without importing into
the live database (a temporary database is used):

```bash
DELIVERY_REPORT_MANIFEST=/path/to/source_manifest.json python -m unittest discover -s tests -p 'test_delivery*.py' -v
```

The verified common cohort is DoorDash **74 orders / $2,669.45** and Uber
**111 / $4,059.18**. Financial bridges are DoorDash **$2,160.29** excluding
passed-through tax/deposits and Uber **$2,868.46** completed-order proceeds; Uber's
explicit mixed-ledger result after other events is **$2,413.54**. The tests keep
settlement statements, canceled sales, refund reversals, and unmatched date coverage
separate from those comparisons.

### Product invoice lookup

Open **Invoice lookup** to search by product name, retail UPC, or supplier item
code. The search includes unlinked supplier items and keeps pack variants separate.
Padded PACK UPCs are normalized for lookup; CASE UPC is never substituted, and
confirmed manual catalog mappings take precedence over a conflicting raw barcode.

Select a product to compare the price-book selling price and source cost with its
invoice history. Price-book prices/costs display their quantity basis (for example,
$33.30 for two catalog units is $16.65 per unit). Invoice prices retain CA/BO and
source PPC/BPC; the page does not assume that bottles-per-case equals retail packs.
Credits remain in the net line total, and the latest-purchase card skips return
lines. Filter by invoice dates/supplier, inspect the full invoice, download the
filtered product history, or view source prices for one supplier/unit/pack at a time.

A product can exist in the catalog without a matching imported invoice. Missing
history is stated explicitly and is not evidence that the product was never bought.
The page reads existing data and does not update costs, stock, or product links.
