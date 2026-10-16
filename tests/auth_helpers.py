"""Functional tests sign in using a temporary credential file, never a production bypass."""
import json
import os
from pathlib import Path
import tempfile
from auth import password_hash
from streamlit.testing.v1 import AppTest

_DIRECTORY = tempfile.TemporaryDirectory()
_FILE = Path(_DIRECTORY.name) / 'accounts.json'
_FILE.write_text(json.dumps({'test-admin': password_hash('test-password-only')}))


def logged_in_app(path, default_timeout=30):
    os.environ['PRICEBOOK_ACCOUNTS_FILE'] = str(_FILE)
    app = AppTest.from_file(path, default_timeout=default_timeout).run()
    app.text_input[0].set_value('test-admin')
    app.text_input[1].set_value('test-password-only')
    app.button[0].click().run()
    return app
