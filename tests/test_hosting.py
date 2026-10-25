import concurrent.futures
import time
from unittest.mock import patch

from app import Store
from test_app import StoreCase, HttpTests


class HostingStorageTests(StoreCase):
    def test_quota_is_atomic_and_persists_across_store_restart(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.store.allow_quota("writes", 3), range(12)))
        self.assertEqual(sum(results), 3)
        reopened = Store(self.path)
        self.assertFalse(reopened.allow_quota("writes", 3))

    def test_restart_does_not_steal_an_active_worker_lease(self):
        lead_id = self.intake()
        with self.store.db() as db:
            db.execute("UPDATE jobs SET state='running',run_after=? WHERE lead_id=?", (time.time()+120, lead_id))
        reopened = Store(self.path)
        self.assertFalse(reopened.process_one(lead_id))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET run_after=0 WHERE lead_id=?", (lead_id,))
        self.assertTrue(reopened.process_one(lead_id))
        self.assertEqual(reopened.get_lead(lead_id)["status"], "ready")


class HostingHttpTests(HttpTests):
    @patch.dict("os.environ", {"RENDER": "true", "RENDER_EXTERNAL_HOSTNAME": "demo.onrender.com"})
    def test_render_host_and_https_origin(self):
        headers = {"Host": "demo.onrender.com", "Origin": "https://demo.onrender.com", "X-Briefops-CSRF": self.store.csrf}
        self.assertEqual(self.request("/api/health", headers={"Host": "demo.onrender.com"})[0], 200)
        self.assertEqual(self.request("/api/intake", {"text": "Нужен сайт example@example.com"}, headers)[0], 202)
        headers["Origin"] = "https://evil.example"
        self.assertEqual(self.request("/api/intake", {"text": "Нужен сайт"}, headers)[0], 403)

    @patch.dict("os.environ", {"BRIEFOPS_PUBLIC_DEMO": "1", "BRIEFOPS_WRITE_DAILY_LIMIT": "1"})
    def test_public_demo_has_persistent_write_cap(self):
        headers = {"X-Briefops-CSRF": self.store.csrf}
        self.assertEqual(self.request("/api/intake", {"text": "Нужен сайт example@example.com"}, headers)[0], 202)
        self.assertEqual(self.request("/api/intake", {"text": "Нужен другой сайт"}, headers)[0], 429)
