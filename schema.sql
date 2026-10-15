PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS imports (
 id INTEGER PRIMARY KEY, source_name TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
 imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, row_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS departments (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS products (
 upc TEXT PRIMARY KEY, department_id INTEGER NOT NULL REFERENCES departments(id),
 name TEXT NOT NULL, size TEXT, price_qty INTEGER NOT NULL CHECK(price_qty > 0),
 price_cents INTEGER NOT NULL, cost_qty INTEGER NOT NULL CHECK(cost_qty >= 0),
 cost_cents INTEGER NOT NULL, includes_taxes INTEGER NOT NULL CHECK(includes_taxes IN (0,1)),
 includes_fees INTEGER NOT NULL CHECK(includes_fees IN (0,1)),
 ebt INTEGER CHECK(ebt IN (0,1)), by_weight INTEGER NOT NULL CHECK(by_weight IN (0,1)),
 variable_price INTEGER NOT NULL CHECK(variable_price IN (0,1)), fee_multiplier TEXT NOT NULL,
 pricebook_stock TEXT, import_id INTEGER NOT NULL REFERENCES imports(id)
);
CREATE TABLE IF NOT EXISTS pricebook_rows (
 import_id INTEGER NOT NULL REFERENCES imports(id), row_number INTEGER NOT NULL,
 upc TEXT NOT NULL REFERENCES products(upc), raw_json TEXT NOT NULL,
 PRIMARY KEY(import_id,row_number)
);
-- Populate these only after mapping the future sheets and confirming their units/dates.
CREATE TABLE IF NOT EXISTS inventory_snapshots (
 id INTEGER PRIMARY KEY, upc TEXT NOT NULL REFERENCES products(upc),
 source TEXT NOT NULL, location TEXT NOT NULL, observed_at TEXT NOT NULL,
 quantity TEXT NOT NULL, source_row_key TEXT NOT NULL,
 UNIQUE(source,source_row_key)
);
CREATE TABLE IF NOT EXISTS sales_lines (
 id INTEGER PRIMARY KEY, upc TEXT NOT NULL REFERENCES products(upc),
 source TEXT NOT NULL, source_row_key TEXT NOT NULL, sold_at TEXT NOT NULL,
 order_id TEXT, quantity TEXT NOT NULL, net_sales_cents INTEGER NOT NULL,
 cost_cents INTEGER, currency TEXT NOT NULL,
 UNIQUE(source,source_row_key)
);
CREATE INDEX IF NOT EXISTS sales_product_date ON sales_lines(upc,sold_at);
CREATE INDEX IF NOT EXISTS inventory_product_date ON inventory_snapshots(upc,observed_at);
CREATE VIEW IF NOT EXISTS product_catalog AS
 SELECT p.*, d.name AS department,
 CAST(p.price_cents AS REAL)/100/p.price_qty AS unit_price
 FROM products p JOIN departments d ON d.id=p.department_id;
CREATE TABLE IF NOT EXISTS website_inventory_rows (
 import_id INTEGER NOT NULL REFERENCES imports(id), row_number INTEGER NOT NULL,
 website_upc TEXT NOT NULL, matched_upc TEXT REFERENCES products(upc),
 snapshot_date TEXT NOT NULL, name TEXT NOT NULL, price_cents INTEGER,
 sale_price_cents INTEGER, stock TEXT NOT NULL, category TEXT, subcategory TEXT,
 status TEXT, code TEXT, image_url TEXT, raw_json TEXT NOT NULL,
 PRIMARY KEY(import_id,row_number), UNIQUE(import_id,website_upc)
);
-- Daily POS report rows, not individual transactions. Blank and internal codes retained.
CREATE TABLE IF NOT EXISTS daily_sales_rows (
 import_id INTEGER NOT NULL REFERENCES imports(id), row_number INTEGER NOT NULL,
 sale_date TEXT NOT NULL, source_upc TEXT NOT NULL, matched_upc TEXT REFERENCES products(upc),
 department TEXT NOT NULL, item TEXT NOT NULL, baskets INTEGER NOT NULL,
 quantity TEXT NOT NULL, sales_cents INTEGER NOT NULL, scan_sales_cents INTEGER NOT NULL,
 avg_items TEXT NOT NULL, avg_sale_cents INTEGER NOT NULL, scan_rate TEXT NOT NULL,
 raw_json TEXT NOT NULL, PRIMARY KEY(import_id,row_number)
);
CREATE INDEX IF NOT EXISTS daily_sales_product_date ON daily_sales_rows(matched_upc,sale_date);
CREATE TABLE IF NOT EXISTS suppliers (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS purchase_invoices (
 id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
 retailer_name TEXT NOT NULL, customer_id TEXT NOT NULL, store_id TEXT NOT NULL,
 invoice_number TEXT NOT NULL, invoice_date TEXT NOT NULL, due_date TEXT,
 total_cents INTEGER NOT NULL, item_count INTEGER NOT NULL,
 content_sha256 TEXT NOT NULL,
 UNIQUE(supplier_id,retailer_name,customer_id,store_id,invoice_number,invoice_date)
);
CREATE TABLE IF NOT EXISTS purchase_lines (
 id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES purchase_invoices(id),
 line_number INTEGER NOT NULL, product_number TEXT NOT NULL,
 source_upc TEXT NOT NULL, pack_upc TEXT NOT NULL, matched_upc TEXT REFERENCES products(upc),
 description TEXT NOT NULL, quantity TEXT NOT NULL, unit_cost TEXT NOT NULL,
 unit_of_measure TEXT NOT NULL, ppc TEXT NOT NULL,
 adjustments_cents INTEGER NOT NULL, discount_cents INTEGER NOT NULL,
 extended_price TEXT NOT NULL, gl_code TEXT,
 UNIQUE(invoice_id,line_number)
);
CREATE TABLE IF NOT EXISTS purchase_source_rows (
 import_id INTEGER NOT NULL REFERENCES imports(id), row_number INTEGER NOT NULL,
 invoice_id INTEGER NOT NULL REFERENCES purchase_invoices(id),
 line_id INTEGER NOT NULL REFERENCES purchase_lines(id), raw_json TEXT NOT NULL,
 PRIMARY KEY(import_id,row_number)
);
-- Reviews keep the original uploaded document and explicit user decisions.
CREATE TABLE IF NOT EXISTS invoice_reviews (
 id INTEGER PRIMARY KEY, document_sha256 TEXT NOT NULL, filename TEXT NOT NULL,
 document BLOB NOT NULL, invoice_id INTEGER NOT NULL UNIQUE REFERENCES purchase_invoices(id),
 reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, decisions_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS supplier_product_mappings (
 supplier_id INTEGER NOT NULL REFERENCES suppliers(id), product_number TEXT NOT NULL,
 unit_of_measure TEXT NOT NULL, ppc TEXT NOT NULL, upc TEXT NOT NULL REFERENCES products(upc),
 PRIMARY KEY(supplier_id,product_number,unit_of_measure,ppc)
);
CREATE TABLE IF NOT EXISTS catalog_candidates (
 id INTEGER PRIMARY KEY, review_id INTEGER NOT NULL REFERENCES invoice_reviews(id),
 line_number INTEGER NOT NULL, retail_upc TEXT NOT NULL, description TEXT NOT NULL,
 supplier_product_number TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Pending catalog setup', UNIQUE(review_id,line_number)
);
