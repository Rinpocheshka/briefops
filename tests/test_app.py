import concurrent.futures
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app import Conflict, Store, analyze, analyze_rules, extract_budget, handler_for


class StoreCase(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / "artifacts" / "tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.store = Store(self.path, token="test-token")

    def tearDown(self):
        self.temp.cleanup()

    def intake(self, **kwargs):
        payload = {"text": "Нужен лендинг. Бюджет 180 тыс. рублей. test@example.com", "name": "Анна", "company": "Пример", "source": "website"}
        payload.update(kwargs)
        return self.store.intake(payload)["id"]

class AutomationTests(StoreCase):
    def test_money_is_not_a_phone_or_deadline(self):
        for text, expected in [("бюджет 180 тыс. рублей", 180000), ("бюджет до 250 000 ₽", 250000), ("бюджет 1,5 млн", 1500000), ("100–150 тыс.", 150000), ("срок 2 недели, телефон +7 999 123-45-67", None), ("бюджет 90000", 90000), ("сумма 90k", 90000)]:
            with self.subTest(text=text):
                self.assertEqual(extract_budget(text), expected)

    def test_contact_and_service(self):
        result = analyze_rules("Нужен лендинг, связь в telegram @hello_demo, бюджет 140 тыс.")
        self.assertEqual(result["contact"], "@hello_demo")
        self.assertEqual(result["service"], "website")

    def test_bot_substring_in_obrabotka_is_not_a_service(self):
        self.assertEqual(analyze_rules("Хотим улучшить обработку обращений. Пока не понимаем решение.")["service"], "unknown")

    def test_success_creates_one_deal_draft_and_task(self):
        lead_id = self.intake()
        self.store.process_one()
        lead = self.store.get_lead(lead_id)
        self.assertEqual(lead["status"], "ready")
        self.assertEqual(lead["analysis"]["budget"], 180000)
        self.assertIn("Стоимость и сроки согласуем отдельно", lead["draft"])
        self.assertEqual(len(self.store.state()["deals"]), 1)
        self.assertEqual(len(lead["tasks"]), 1)
        self.assertFalse(self.store.process_one(lead_id))

    def test_ingestion_idempotency_and_conflict(self):
        payload = {"text": "Сайт, бюджет 150 тыс., test@example.com", "message_id": "provider-1"}
        first = self.store.intake(payload)
        again = self.store.intake(payload)
        self.assertEqual(first["id"], again["id"])
        self.assertTrue(again["replayed"])
        with self.assertRaises(Conflict):
            self.store.intake({**payload, "text": "Другая заявка на автоматизацию"})

    def test_concurrent_intake_same_key_is_one_record(self):
        payload = {"text": "Нужен бот, 100 тыс., test@example.com", "message_id": "same"}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            ids = list(pool.map(lambda _: self.store.intake(payload)["id"], range(10)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.store.state()["stats"]["total"], 1)

    def test_exact_cross_channel_duplicate_does_not_create_deal(self):
        first = self.intake()
        self.store.process_one()
        second = self.intake(source="telegram")
        self.store.process_one()
        lead = self.store.get_lead(second)
        self.assertEqual(lead["status"], "duplicate")
        self.assertEqual(lead["duplicate_of"], first)
        self.assertEqual(lead["draft"], "")
        self.assertEqual(len(self.store.state()["deals"]), 1)

    def test_same_contact_new_request_is_not_discarded(self):
        first = self.intake()
        self.store.process_one()
        second = self.intake(text="Ещё один лендинг. На другой продукт. Бюджет 220 тыс. test@example.com")
        self.store.process_one()
        lead = self.store.get_lead(second)
        self.assertEqual(lead["status"], "ready")
        self.assertEqual(lead["possible_duplicate"], first)
        self.assertEqual(len(self.store.state()["deals"]), 2)

    def test_identical_anonymous_messages_are_not_silently_dropped(self):
        for _ in range(2):
            self.store.intake({"text": "Здравствуйте, хотим заказать сайт, расскажите об условиях"})
            self.store.process_one()
        self.assertEqual(len(self.store.state()["deals"]), 2)
        self.assertEqual(self.store.state()["stats"]["duplicates"], 0)

    def test_missing_fields_and_budget_floor_are_explicit(self):
        missing = self.intake(text="Хотим понять, что вы можете предложить для нашей компании")
        self.store.process_one()
        lead = self.store.get_lead(missing)
        self.assertEqual(lead["status"], "needs_info")
        self.assertEqual(len(lead["analysis"]["missing"]), 3)
        with self.assertRaises(ValueError):
            self.store.review(missing, {}, approve=True)
        small = self.intake(text="Нужен сайт. Бюджет 30 тыс. low@example.com")
        self.store.process_one()
        self.assertTrue(self.store.get_lead(small)["analysis"]["below_floor"])

    def test_failure_retries_without_lost_request_or_duplicate_deal(self):
        lead_id = self.intake(simulate_failure=True)
        self.store.process_one()
        self.assertEqual(self.store.get_lead(lead_id)["status"], "retry")
        self.assertEqual(len(self.store.state()["deals"]), 0)
        with self.store.db() as db:
            db.execute("UPDATE jobs SET run_after=0")
        self.store.process_one()
        self.assertEqual(self.store.get_lead(lead_id)["status"], "ready")
        self.assertEqual(self.store.get_lead(lead_id)["attempts"], 2)
        self.assertEqual(len(self.store.state()["deals"]), 1)

    def test_terminal_failure_requires_human_retry(self):
        lead_id = self.intake()
        with patch("app.analyze", side_effect=RuntimeError("private error")):
            for _ in range(3):
                with self.store.db() as db:
                    db.execute("UPDATE jobs SET run_after=0")
                self.store.process_one()
        lead = self.store.get_lead(lead_id)
        self.assertEqual(lead["status"], "failed")
        self.assertNotIn("private error", json.dumps(lead))
        self.store.retry(lead_id)
        self.store.process_one()
        self.assertEqual(self.store.get_lead(lead_id)["status"], "ready")

    def test_restart_recovers_running_job(self):
        lead_id = self.intake()
        with self.store.db() as db:
            db.execute("UPDATE jobs SET state='running'")
        recovered = Store(self.path)
        recovered.process_one()
        self.assertEqual(recovered.get_lead(lead_id)["status"], "ready")
        self.assertIn("recovered", [e["kind"] for e in recovered.get_lead(lead_id)["events"]])

    def test_sla_sweep_is_idempotent_and_stops_after_approval(self):
        lead_id = self.store.intake({"text": "Нужен сайт. 180 тыс. old@example.com"}, created_at=time.time()-1300)["id"]
        self.store.process_one()
        self.assertEqual(self.store.sweep()["created"], 1)
        self.assertEqual(self.store.sweep()["created"], 0)
        self.store.review(lead_id, {}, approve=True)
        self.assertEqual(self.store.sweep()["created"], 0)
        self.assertEqual(self.store.state()["stats"]["sla"], 0)

    def test_approval_is_atomic_idempotent_and_does_not_send(self):
        lead_id = self.intake()
        self.store.process_one()
        with patch("urllib.request.urlopen", side_effect=AssertionError("Must not send externally")):
            self.store.review(lead_id, {"draft": "Проверенный менеджером ответ"}, approve=True)
            self.assertTrue(self.store.review(lead_id, {}, approve=True)["replayed"])
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='approved'").fetchone()[0], 1)

    def test_model_failure_falls_back_without_inventing_contacts(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test", "OPENROUTER_MODEL": "test"}), patch("urllib.request.urlopen", side_effect=TimeoutError()):
            result, warning = analyze("Нужен сайт, бюджет 120 тыс. client@example.com", use_llm=True)
        self.assertEqual(result["contact"], "client@example.com")
        self.assertEqual(result["budget"], 120000)
        self.assertEqual(result["engine"], "rules")
        self.assertTrue(warning)

    def test_review_validates_budget_and_updates_crm(self):
        lead_id = self.intake()
        self.store.process_one()
        for bad in (-10, True, "NaN", "100000001", "abc"):
            with self.subTest(budget=bad), self.assertRaises(ValueError):
                self.store.review(lead_id, {"budget": bad})
        self.store.review(lead_id, {"budget": "200000", "company": "Изменено", "draft": "Уточнённый текст"})
        self.assertEqual(self.store.state()["deals"][0]["value"], 200000)


class HttpTests(StoreCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.store))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        super().tearDown()

    def request(self, path, payload=None, headers=None):
        req = urllib.request.Request(self.url+path, data=None if payload is None else json.dumps(payload).encode(), headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_csrf_and_origin(self):
        payload = {"text": "Нужен сайт. 150 тыс. hi@example.com"}
        self.assertEqual(self.request("/api/intake", payload)[0], 403)
        self.assertEqual(self.request("/api/intake", payload, {"X-Briefops-CSRF": self.store.csrf, "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("/api/intake", payload, {"X-Briefops-CSRF": self.store.csrf})[0], 202)

    def test_authenticated_n8n_path(self):
        payload = {"text": "Нужен бот. Бюджет 120 тыс. api@example.com", "source": "n8n"}
        self.assertEqual(self.request("/api/automation/intake", payload)[0], 401)
        headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "n8n-42"}
        code, result = self.request("/api/automation/intake", payload, headers)
        self.assertEqual(code, 202)
        self.assertEqual(self.request("/api/automation/process", {"id": result["lead"]["id"]}, headers)[1]["lead"]["status"], "ready")
        self.assertTrue(self.request("/api/automation/intake", payload, headers)[1]["replayed"])

    def test_broken_json_and_static_path_traversal(self):
        self.assertEqual(self.request("/api/intake", [], {"X-Briefops-CSRF": self.store.csrf})[0], 400)
        self.assertEqual(self.request("/../app.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
