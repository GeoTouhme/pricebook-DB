import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest
import auth
from safe_exports import csv_bytes
from delivery_reports import validate_batch, parse_batch
from backup_policy import prune_backups

ROOT = Path(__file__).resolve().parents[1]


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'accounts.json'
        self.users = {'admin': auth.password_hash('a-long-test-password'),
                      'owner': auth.password_hash('another-test-password')}
        self.path.write_text(json.dumps(self.users))
        patcher = patch.dict(os.environ, PRICEBOOK_ACCOUNTS_FILE=str(self.path))
        patcher.start(); self.addCleanup(patcher.stop)
        auth._ATTEMPTS.clear()

    def test_gate_login_logout_revocation_and_expiry(self):
        app = AppTest.from_file(str(ROOT/'dashboard.py'), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)
        self.assertEqual(len(app.sidebar.radio), 0)
        app.text_input[0].set_value('owner')
        app.text_input[1].set_value('incorrect')
        app.button[0].click().run()
        self.assertEqual(len(app.metric), 0)
        app.text_input[1].set_value('another-test-password')
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertGreater(len(app.metric), 0)
        app.button(key='sign_out').click().run()
        self.assertEqual(len(app.metric), 0)
        app.text_input[0].set_value('admin')
        app.text_input[1].set_value('a-long-test-password')
        app.button[0].click().run()
        app.session_state['_admin_session']['expires'] = 0
        app.run()
        self.assertEqual(len(app.metric), 0)
        app.text_input[0].set_value('admin')
        app.text_input[1].set_value('a-long-test-password')
        app.button[0].click().run()
        self.users['admin'] = auth.password_hash('changed-password')
        self.path.write_text(json.dumps(self.users))
        app.run()
        self.assertEqual(len(app.metric), 0)

    def test_missing_config_fails_closed_before_loading_data(self):
        self.path.unlink()
        with patch('dashboard_data.load_data', side_effect=AssertionError('must not load')):
            app = AppTest.from_file(str(ROOT/'dashboard.py')).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertEqual(len(app.metric), 0)

    def test_hash_and_shared_rate_limit(self):
        self.assertTrue(auth.verify('a-long-test-password', self.users['admin']))
        self.assertFalse(auth.verify('wrong', self.users['admin']))
        for _ in range(5):
            self.assertFalse(auth.authenticate('admin', 'wrong', self.users))
        self.assertFalse(auth.authenticate('admin', 'a-long-test-password', self.users))
        self.assertTrue(auth.authenticate('owner', 'another-test-password', self.users))
        with patch('auth.time.monotonic', return_value=10**15):
            self.assertTrue(auth.authenticate('admin', 'a-long-test-password', self.users))

    def test_csv_formulas_and_source_unchanged(self):
        source = pd.DataFrame({'Name':['=1+1',' +SUM(A1)', '@x', '\ttext','plain'],
                               'Money':[-1,2,3,4,5]})
        original = source.copy(deep=True)
        output = csv_bytes(source).decode('utf-8-sig')
        self.assertIn("'=1+1", output)
        self.assertIn("' +SUM(A1)", output)
        self.assertIn("'@x", output)
        self.assertIn(',-1', output)
        pd.testing.assert_frame_equal(source, original)

    def test_batch_and_backup_limits(self):
        validate_batch([1]*20)
        for sizes in ([1]*21, [20*1024*1024]*3, [21*1024*1024]):
            with self.assertRaises(ValueError): validate_batch(sizes)
        folder = Path(self.temp.name)/'backups'; folder.mkdir()
        for i in range(14): (folder/f'before-upload-{i}.sqlite3').touch()
        (folder/'manual.sqlite3').touch()
        prune_backups(Path(self.temp.name)/'db.sqlite3')
        self.assertEqual(len(list(folder.glob('before-upload-*'))), 10)
        self.assertTrue((folder/'manual.sqlite3').exists())

    def test_batch_expansion_rejected_before_parsing(self):
        import io
        import zipfile
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('report.csv', b'a' * 1024)
        with patch('delivery_reports.MAX_EXPANDED', 1500), patch('delivery_reports.parse_upload') as parse:
            with self.assertRaisesRegex(ValueError, 'batch limit'):
                parse_batch([(output.getvalue(), 'one.zip'), (output.getvalue(), 'two.zip')])
            parse.assert_not_called()

    def test_pdf_timeout_and_worker_failure(self):
        import subprocess
        from invoice_review import extract_document
        from unittest.mock import MagicMock
        worker=MagicMock()
        worker.pid=12345
        worker.communicate.side_effect=[subprocess.TimeoutExpired('worker',180),(b'',b'')]
        with patch('subprocess.Popen',return_value=worker), patch('os.killpg') as kill:
            with self.assertRaisesRegex(ValueError, '180 seconds'):
                extract_document(b'%PDF-invalid', 'test.pdf')
            import os
            if os.name=='posix':kill.assert_called_once()
            else:worker.kill.assert_called_once()
            self.assertEqual(worker.communicate.call_count,2)
        with self.assertRaises(ValueError): extract_document(b'%PDF-invalid', 'test.pdf')
