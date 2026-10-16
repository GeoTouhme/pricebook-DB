"""Interactively create/reset the two admin accounts on the server."""
import getpass
import json
import os
from pathlib import Path
import tempfile
from auth import DEFAULT_FILE, password_hash


def main():
    path = Path(os.environ.get('PRICEBOOK_ACCOUNTS_FILE', DEFAULT_FILE))
    users = {}
    print('Set both admin accounts. Running this again replaces accounts and ends existing sessions.')
    for label in ('Your account', 'Owner account'):
        name = input(f'{label} username: ').strip()
        if not name or len(name) > 80 or name in users:
            raise SystemExit('Choose two different, nonempty usernames (at most 80 characters).')
        password = getpass.getpass(f'{label} password (12–256 characters): ')
        if not 12 <= len(password) <= 256:
            raise SystemExit('Password must be 12–256 characters. No changes saved.')
        if password != getpass.getpass('Confirm password: '):
            raise SystemExit('Passwords differ. No changes saved.')
        users[name] = password_hash(password)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.accounts-')
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(users, output)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    print('Both admin accounts saved. Start or refresh the dashboard to sign in.')


if __name__ == '__main__':
    main()
