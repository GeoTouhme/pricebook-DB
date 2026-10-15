#!/usr/bin/env bash
set -euo pipefail
cd /workspace/pricebook-DB
python3 -m venv /workspace/.venvs/pricebook
/workspace/.venvs/pricebook/bin/python -m pip install -r requirements.lock.txt
/workspace/.venvs/pricebook/bin/python import_pricebook.py
/workspace/.venvs/pricebook/bin/python import_website_inventory.py data/website-inventory_2026-10-13.csv --snapshot-date 2026-10-13
/workspace/.venvs/pricebook/bin/python import_daily_sales.py data/itemsales_by_day.csv
/workspace/.venvs/pricebook/bin/python import_daily_sales.py 'data/itemsales_by_day 9-10 corrected.csv'
/workspace/.venvs/pricebook/bin/python import_invoices.py data/invoices/*.csv
