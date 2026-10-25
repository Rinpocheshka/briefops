"""Exercise live tables on the dedicated development branch; never touch production."""
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import Store

env = json.loads((ROOT / "artifacts/live-test-env.json").read_text(encoding="utf-8-sig"))
assert env["NEON_BRANCH"] == "dev-briefops"
assert "/briefops_live?" in env["DATABASE_URL"]
mailer = Mock(configured=True)
mailer.send.return_value = ("sent", "Test provider accepted")
store = Store(ROOT / "artifacts/live-neon-placeholder.sqlite3", database_url=env["DATABASE_URL"],
              direct_url=env["DATABASE_URL_UNPOOLED"], workspace=True, demo=False, mailer=mailer)
submission = "test_" + uuid.uuid4().hex
payload = {"form_data":{"form_id":"wov-v1", "site_url":"https://rinpocheshka.github.io/wov/",
                         "submission_id":submission, "name":"Интеграционный тест",
                         "contact":"integration@example.com", "idea":"Нужен сайт, бюджет 50 тыс. рублей. Проверка " + submission}}
lead_id = store.intake_wov(payload)["id"]
assert store.intake_wov(payload)["replayed"]
assert store.process_one(lead_id)
assert store.get_lead(lead_id)["analysis"]["contact"] == "integration@example.com"
store.review(lead_id, {}, approve=True)
assert not store.deliver_one()
delivery = store.queue_email(lead_id)
assert store.queue_email(lead_id)["id"] == delivery["id"]
assert store.deliver_one()
assert not store.deliver_one()
mailer.send.assert_called_once()
store.database.close()
reopened = Store(ROOT / "artifacts/live-neon-placeholder.sqlite3", database_url=env["DATABASE_URL"],
                 direct_url=env["DATABASE_URL_UNPOOLED"], workspace=True, demo=False)
assert reopened.get_lead(lead_id)["email_delivery"]["status"] == "sent"
reopened.database.close()
print("NEON LIVE OK: isolated migration, website intake, structured contact, approval, one delivery, restart persistence; no real email sent")
