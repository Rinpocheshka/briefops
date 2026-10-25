"""Run the existing behavioral suite against an isolated Neon development branch."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from dotenv import dotenv_values
from app import Store
from test_app import AutomationTests, HttpTests, StoreCase

env = dotenv_values(ROOT / "artifacts" / "neon-test.env")
assert env.get("NEON_BRANCH") == "dev-briefops", "Tests require the dedicated dev-briefops branch"
assert "DATABASE_URL" in env and "DATABASE_URL_UNPOOLED" in env
original_setup = StoreCase.setUp
original_teardown = StoreCase.tearDown


def setup(case):
    original_setup(case)
    # This branch was explicitly created for tests; production is never cleaned.
    with case.store.db() as db:
        db.connection.execute("TRUNCATE outbox,tasks,events,deals,jobs,leads,quotas RESTART IDENTITY CASCADE")


def teardown(case):
    case.store.database.close()
    original_teardown(case)


if __name__ == "__main__":
    # The restart test constructs a second Store from a local path. Give only
    # that constructor the same explicit test connection, never modify env.
    real_store = Store
    def reopened(path, **kwargs):
        return real_store(path, database_url=env["DATABASE_URL"], direct_url=env["DATABASE_URL_UNPOOLED"], **kwargs)
    with patch.object(StoreCase, "setUp", setup), patch.object(StoreCase, "tearDown", teardown), patch("test_app.Store", reopened):
        suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(AutomationTests), unittest.defaultTestLoader.loadTestsFromTestCase(HttpTests)])
        result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
