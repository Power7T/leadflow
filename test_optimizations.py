import unittest
from unittest.mock import patch, MagicMock
import os
import sqlite3
import json

# Import the modules we want to test
import sync_engine
from scheduler import is_primary_active

class TestLeadflowOptimizations(unittest.TestCase):
    def setUp(self):
        # Create a temporary memory database for safety
        self.test_db_path = ":memory:"
        self.conn = sqlite3.connect(self.test_db_path)
        self.create_test_schema()

    def tearDown(self):
        self.conn.close()

    def create_test_schema(self):
        # Create tables needed for sync engine testing
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS businesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                status TEXT,
                demo_viewed INTEGER DEFAULT 0
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                amount REAL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                payload TEXT,
                synced INTEGER DEFAULT 0
            )
        """)

    @patch("sync_engine.get_conn")
    def test_sql_injection_protection_insert_business(self, mock_get_conn):
        mock_get_conn.return_value = self.conn

        # Test Case 1: Valid payload (legal column names/identifiers)
        payload_valid = {
            "business": {
                "name": "Acme Corp",
                "status": "active"
            }
        }
        sync_engine.apply_sync_transaction(self.conn, "insert_business", payload_valid)

        # Verify the record exists
        cursor = self.conn.execute("SELECT name, status FROM businesses WHERE name='Acme Corp'")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Acme Corp")
        self.assertEqual(row[1], "active")

        # Test Case 2: SQL Injection payload inside column names/identifiers
        payload_malicious = {
            "business": {
                "name": "Injection Corp",
                "status; DROP TABLE businesses; --": "malicious"
            }
        }

        # We mock logging to see if it logs an error
        with patch("sync_engine.log.error") as mock_log_err:
            sync_engine.apply_sync_transaction(self.conn, "insert_business", payload_malicious)
            # Ensure it logged the error
            mock_log_err.assert_called_once()
            # Ensure the table businesses was not dropped and Injection Corp was not inserted
            cursor = self.conn.execute("SELECT count(*) FROM businesses WHERE name='Injection Corp'")
            self.assertEqual(cursor.fetchone()[0], 0)

            # Ensure table still exists
            cursor = self.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='businesses'")
            self.assertEqual(cursor.fetchone()[0], 1)

    @patch("sync_engine.get_conn")
    def test_sql_injection_protection_insert_deal(self, mock_get_conn):
        mock_get_conn.return_value = self.conn

        # Test Case 1: Valid deal payload
        payload_valid = {
            "deal": {
                "title": "Big deal",
                "amount": 5000.0
            }
        }
        sync_engine.apply_sync_transaction(self.conn, "insert_deal", payload_valid)

        cursor = self.conn.execute("SELECT title, amount FROM deals WHERE title='Big deal'")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Big deal")
        self.assertEqual(row[1], 5000.0)

        # Test Case 2: SQL Injection deal payload (malicious column key)
        payload_malicious = {
            "deal": {
                "title; DELETE FROM deals; --": "malicious"
            }
        }
        with patch("sync_engine.log.error") as mock_log_err:
            sync_engine.apply_sync_transaction(self.conn, "insert_deal", payload_malicious)
            mock_log_err.assert_called_once()

            # Ensure the valid deal was not deleted
            cursor = self.conn.execute("SELECT count(*) FROM deals WHERE title='Big deal'")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_get_adb_binary(self):
        # We mock os.path.exists to return True for homeostasis target
        with patch("os.path.exists") as mock_exists:
            # If homebrew exists
            mock_exists.side_effect = lambda path: path == "/opt/homebrew/bin/adb.orig"
            self.assertEqual(sync_engine.get_adb_binary(), "/opt/homebrew/bin/adb.orig")

            # If usr/local/bin exists
            mock_exists.side_effect = lambda path: path == "/usr/local/bin/adb.orig"
            self.assertEqual(sync_engine.get_adb_binary(), "/usr/local/bin/adb.orig")

            # If neither exists
            mock_exists.side_effect = lambda path: False
            self.assertEqual(sync_engine.get_adb_binary(), "adb")

    @patch("requests.get")
    @patch("requests.post")
    @patch("os.getenv")
    @patch("pathlib.Path.write_text")
    @patch("pathlib.Path.read_text")
    @patch("pathlib.Path.exists")
    def test_is_primary_active_lan_first(self, mock_exists, mock_read, mock_write, mock_getenv, mock_post, mock_get):
        # Mocks
        mock_exists.return_value = False

        # Set up default getenv return values for the test
        def getenv_mock(key, default=None):
            if key == "LEADFLOW_DEVICE_ROLE":
                return "primary"
            if key in ("LEADFLOW_PUBLIC_URL", "CF_WORKER_URL"):
                return "https://test-relay.workers.dev"
            if key in ("LEADFLOW_SECRET_TOKEN", "SECRET_TOKEN"):
                return "test-secret"
            return default

        # Test Case 1: Primary role
        mock_getenv.side_effect = getenv_mock
        res = is_primary_active()
        # Primary role should return False because primary does not stand down (runs its own jobs)
        self.assertFalse(res)
        # Should post heartbeat to Cloudflare KV
        mock_post.assert_called_once()
        self.assertTrue(mock_post.call_args[0][0].startswith('http'))

        # Reset mock
        mock_post.reset_mock()
        mock_get.reset_mock()

        # Test Case 2: Backup role, LAN health endpoint is healthy
        def getenv_backup(key, default=None):
            if key == "LEADFLOW_DEVICE_ROLE":
                return "backup"
            if key in ("LEADFLOW_PUBLIC_URL", "CF_WORKER_URL"):
                return "https://test-relay.workers.dev"
            if key in ("LEADFLOW_SECRET_TOKEN", "SECRET_TOKEN"):
                return "test-secret"
            return default
        mock_getenv.side_effect = getenv_backup

        # Mock requests.get to return 200 OK from LAN health endpoint
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "db": "connected"}
        mock_get.return_value = mock_response

        res = is_primary_active()
        # Since LAN endpoint is healthy, backup should stand down (return True)
        self.assertTrue(res)
        # We should NOT call Cloudflare KV requests.post
        mock_post.assert_not_called()
        mock_write.assert_called_with("0")

        # Test Case 3: Backup role, LAN health endpoint is down, CF KV heartbeat is fresh
        mock_get.side_effect = Exception("Connection Refused")

        # Mock requests.post to return KV heartbeat from Cloudflare
        mock_cf_response = MagicMock()
        import time
        mock_cf_response.json.return_value = {"value": str(time.time() - 100)} # 100 seconds old (fresh)
        mock_post.return_value = mock_cf_response

        # Reset write_text mockup to verify it resets failure counter
        mock_write.reset_mock()
        res = is_primary_active()
        self.assertTrue(res)
        # Verify Cloudflare check was queried
        mock_post.assert_called_once()
        self.assertTrue(mock_post.call_args[0][0].startswith('http'))
        # Verify failover counter was reset
        mock_write.assert_called_with("0")

        # Test Case 4: Backup role, LAN health down, CF KV heartbeat is stale (e.g. > 10 min old)
        mock_post.reset_mock()
        mock_write.reset_mock()
        mock_read.return_value = "0"
        mock_exists.return_value = True

        mock_cf_response_stale = MagicMock()
        mock_cf_response_stale.json.return_value = {"value": str(time.time() - 700)} # 11.6 mins old (stale)
        mock_post.return_value = mock_cf_response_stale

        res = is_primary_active()
        # Since it is the first failure, it registers standby monitoring (stands down for now, returns True)
        self.assertTrue(res)
        # Verify the failure count is written as "1"
        mock_write.assert_called_with("1")

        # Test Case 5: Second consecutive failure should trigger actual failover (return False)
        mock_post.reset_mock()
        mock_write.reset_mock()
        mock_read.return_value = "1" # Already failed once

        res = is_primary_active()
        # Hand off active role to Backup (returns False)
        self.assertFalse(res)
        # Verify it writes failure count as "2"
        mock_write.assert_called_with("2")

    @patch("os.getenv")
    def test_is_primary_active_missing_env(self, mock_getenv):
        # Case A: missing LEADFLOW_PUBLIC_URL
        def getenv_missing_url(key, default=None):
            if key == "LEADFLOW_SECRET_TOKEN":
                return "some-token"
            return default
        mock_getenv.side_effect = getenv_missing_url
        with self.assertRaises(ValueError) as context:
            is_primary_active()
        self.assertIn("LEADFLOW_PUBLIC_URL is missing", str(context.exception))

        # Case B: missing LEADFLOW_SECRET_TOKEN
        def getenv_missing_token(key, default=None):
            if key == "LEADFLOW_PUBLIC_URL":
                return "https://test.workers.dev"
            return default
        mock_getenv.side_effect = getenv_missing_token
        with self.assertRaises(ValueError) as context:
            is_primary_active()
        self.assertIn("LEADFLOW_SECRET_TOKEN is missing", str(context.exception))


if __name__ == "__main__":
    unittest.main()
