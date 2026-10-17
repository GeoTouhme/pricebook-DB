"""Fail-closed, server-side admin sessions; credentials never belong in Git."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time

DEFAULT_FILE = Path(__file__).resolve().parent / '.streamlit' / 'accounts.json'
_LOCK = threading.Lock()
_ATTEMPTS = {}
SESSION_SECONDS = 8 * 60 * 60


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'scrypt${salt}${digest}'


def verify(password, stored):
    try:
        algorithm, salt, _ = stored.split('$')
        return algorithm == 'scrypt' and hmac.compare_digest(password_hash(password, salt), stored)
    except (ValueError, TypeError):
        return False


def accounts():
    path = Path(os.environ.get('PRICEBOOK_ACCOUNTS_FILE', DEFAULT_FILE))
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not 1 <= len(data) <= 2:
        raise ValueError('Configure one or two admin accounts.')
    for name, value in data.items():
        if not isinstance(name, str) or not isinstance(value, str) or not value.startswith('scrypt$'):
            raise ValueError('Invalid account configuration.')
    return data


def authenticate(username, password, users):
    # Shared across browser sessions. Unknown names use one bucket to bound memory.
    key = username if username in users else '<unknown>'
    with _LOCK:
        now = time.monotonic()
        failures = [t for t in _ATTEMPTS.get(key, []) if now-t < 300]
        if len(failures) >= 5:
            return False
        stored = users.get(username, 'scrypt$' + '00'*16 + '$' + '00'*64)
        valid = verify(password, stored) and username in users
        _ATTEMPTS[key] = [] if valid else failures + [now]
        return valid


def logout():
    import streamlit as st
    for key in list(st.session_state):
        del st.session_state[key]


def require_login():
    import streamlit as st
    try:
        users = accounts()
    except (OSError, ValueError):
        logout()
        st.error('Login is not configured. On the server, run: python manage_accounts.py')
        st.stop()
    session = st.session_state.get('_admin_session', {})
    username = session.get('username')
    if (username in users and session.get('credential') == users[username]
            and time.time() < session.get('expires', 0)):
        st.sidebar.button('Sign out', icon=':material/logout:', on_click=logout, key='sign_out')
        return username
    if session:
        logout()
    st.title('Bal-Port Liquors')
    with st.form('login'):
        username = st.text_input('Username', max_chars=80)
        password = st.text_input('Password', type='password', max_chars=256)
        submitted = st.form_submit_button('Sign in', type='primary')
    if submitted:
        if authenticate(username.strip(), password, users):
            st.session_state['_admin_session'] = dict(username=username.strip(),
                credential=users[username.strip()], expires=time.time()+SESSION_SECONDS)
            st.rerun()
        st.error('Unable to sign in. Check your credentials; after five failed attempts, wait five minutes.')
    st.stop()
