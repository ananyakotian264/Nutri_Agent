import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import db


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.old_db_path = db.DB_PATH
        db.DB_PATH = Path(self.temp_dir.name) / "test.sqlite3"
        db.init_db()
        self.first_user = db.create_user("first.user", "unused-hash")
        self.second_user = db.create_user("second.user", "unused-hash")

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def add_session(self, token, user_id, expires_at=None):
        db.create_session(
            hashlib.sha256(token.encode()).hexdigest(),
            user_id,
            expires_at or datetime.now(timezone.utc) + timedelta(days=1),
        )

    def test_session_resolves_only_its_account(self):
        self.add_session("opaque-first-token", self.first_user)
        self.add_session("opaque-second-token", self.second_user)
        first_hash = hashlib.sha256("opaque-first-token".encode()).hexdigest()
        second_hash = hashlib.sha256("opaque-second-token".encode()).hexdigest()
        self.assertEqual(db.get_user_id_for_session(first_hash), self.first_user)
        self.assertEqual(db.get_user_id_for_session(second_hash), self.second_user)

    def test_expired_and_revoked_sessions_do_not_resolve(self):
        expired_token = "expired-token"
        self.add_session(expired_token, self.first_user, datetime.now(timezone.utc) - timedelta(seconds=1))
        expired_hash = hashlib.sha256(expired_token.encode()).hexdigest()
        self.assertIsNone(db.get_user_id_for_session(expired_hash))

        revoked_token = "revoked-token"
        self.add_session(revoked_token, self.first_user)
        revoked_hash = hashlib.sha256(revoked_token.encode()).hexdigest()
        db.revoke_session(revoked_hash)
        self.assertIsNone(db.get_user_id_for_session(revoked_hash))

if __name__ == "__main__":
    unittest.main()
