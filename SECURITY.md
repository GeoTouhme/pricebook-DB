# Dashboard access and deployment

Both configured accounts are administrators. Sign-in runs before loading business data or rendering downloads, imports, or invoice review. No default password or bypass is provided. Sessions last eight hours, end at sign-out, and are invalidated on the next interaction when the account password changes or the account is removed. Five failed sign-ins block that account for five minutes across browser sessions in the same process. Restarting the server resets this throttle. Use one application process; this is not a distributed authentication service.

## Ubuntu update and account setup

Stop Streamlit with Ctrl+C, then run from the repository:

```bash
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
python manage_accounts.py
python -m streamlit run dashboard.py --server.address 127.0.0.1 --server.port 8501
```

The account command prompts for your username/password and the owner's username/password. Password entry is hidden; choose separate passwords of at least 12 characters. It saves only salted scrypt hashes in `.streamlit/accounts.json`, with owner-only permissions on Ubuntu. This file is Git-ignored. Run the command again to reset both accounts. Optionally set `PRICEBOOK_ACCOUNTS_FILE` to a private absolute path outside the checkout. A missing or invalid configuration locks the app.

For immediate remote use without exposing an HTTP login on the network, keep the server bound to `127.0.0.1` and run this on each user's computer:

```bash
ssh -L 8501:127.0.0.1:8501 YOUR_SERVER_USER@SERVER_IP
```

Open `http://localhost:8501` on that computer. The SSH connection encrypts the connection and closes the public route to Streamlit. Each person needs their own authorized SSH access; no SSH credentials are configured by this application.

For a normal shared web URL, deploy a TLS reverse proxy with authentication covering **all** paths, including Streamlit media/download/upload endpoints and WebSockets. Keep Streamlit on loopback and block external port 8501. Streamlit's generated download URLs are bearer URLs and are not independently checked by the Python login gate; use the SSH tunnel or an authenticated proxy for the whole server boundary. No server firewall, TLS certificate, SSH account, or reverse proxy has been configured by this code change.

## Uploads, exports, and backups

- PDF extraction runs in a separate process with a 60-second wall timeout, one active PDF per app process, and on Linux a 45-second CPU / 2 GiB address-space limit. Inputs are at most 20 MiB / 100 pages. This is resource isolation, not an OS security sandbox.
- Delivery imports accept at most 20 files, 20 MiB per file, 50 MiB total, and 100 MiB expanded across the batch. Archive traversal/encryption checks still apply. These limits reduce resource abuse; authenticated administrators can still submit workloads or accumulate database storage over time.
- CSV downloads prefix formula-leading text with an apostrophe. Numeric values and stored source data are preserved. Original uploaded document downloads remain originals and may contain spreadsheet formulas.
- After successful catalog/snapshot/delivery saves, retain the latest 10 automatic `before-upload-*` / `before-delivery-*` backups combined. Manually named backups are untouched. Retention is count-based, not a disk quota; monitor disk use and keep separate off-server backups.
- Pinned upgrades: Streamlit 1.54.0, pdfplumber 0.11.10, pdfminer.six 20260107. These address the two cited advisories; this is not a claim that every dependency is vulnerability-free.

## Repository data exposure

The repository was confirmed public during this review. Tracked `data/` CSVs contain business records. App login cannot restrict GitHub access. Changing repository visibility or rewriting Git history requires a separate decision; neither retracts copies others already downloaded. Do not commit credentials, database files, new private reports, or backups.
