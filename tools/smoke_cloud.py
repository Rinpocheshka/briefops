"""Synthetic HTTP end-to-end check of a deployed BriefOps service."""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "https://briefops.onrender.com"
token = (ROOT / "data" / "cloud-automation-token.txt").read_text().strip()


def call(path, payload=None, headers=None, expected=200):
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(BASE + path, body, {"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as response:
        status, raw = response.code, response.read()
    assert status == expected, f"{path}: HTTP {status}, expected {expected}"
    return json.loads(raw)


health = call("/api/health")
assert health["storage"] == "postgres" and health["ok"]
state = call("/api/state")
assert state["mode"] == "llm" and state["llm"]["provider"] == "nvidia"
assert "key" not in state["llm"]
auth = {"Authorization": "Bearer " + token}
ui = {"X-Briefops-CSRF": state["csrf"], "Origin": BASE}
message_id = "cloud-smoke-" + str(time.time_ns())
payload = {"text": "Нужна автоматизация: заявки с лендинга в CRM и уведомления в Telegram. Бюджет 180 тыс. рублей. Не срочно, запуск в следующем месяце. Контакт cloud-demo@example.com.", "name": "Ирина", "company": "Cloud Demo Studio", "source": "n8n", "message_id": message_id}
call("/api/automation/intake", payload, expected=401)
call("/api/intake", payload, expected=403)
call("/api/intake", payload, {**ui, "Origin": "https://evil.example"}, expected=403)
accepted = call("/api/automation/intake", payload, auth, 202)
lead_id = accepted["lead"]["id"]
call("/api/automation/process", {"id": lead_id}, auth)
for _ in range(12):
    state = call("/api/state")
    lead = next(item for item in state["leads"] if item["id"] == lead_id)
    if lead["status"] not in {"queued", "processing", "retry"}:
        break
    time.sleep(2)
data = lead["analysis"]
assert lead["status"] in {"ready", "needs_info", "duplicate"}
assert data["engine"] == "llm", "NVIDIA request fell back to rules"
assert data["service"] == "automation" and data["budget"] == 180000 and data["urgent"] is False
assert data["contact"] == "cloud-demo@example.com"
assert call("/api/automation/intake", payload, auth)["replayed"]
call("/api/automation/intake", {**payload, "text": "Совершенно другая заявка"}, auth, 409)
if lead["status"] == "duplicate":
    lead_id = lead["duplicate_of"]
else:
    call(f"/api/leads/{lead_id}/review", {"budget": "190000", "draft": "Здравствуйте, Ирина! Уточните, пожалуйста, CRM и поля заявки. После согласования оценим объём и сроки."}, ui)
    call(f"/api/leads/{lead_id}/approve", {}, ui)
    assert call(f"/api/leads/{lead_id}/approve", {}, ui)["replayed"]
state = call("/api/state")
lead = next(item for item in state["leads"] if item["id"] == lead_id)
assert lead["status"] == "approved" and lead["analysis"]["budget"] == 190000
assert next(item for item in state["deals"] if item["lead_id"] == lead_id)["stage"] == "response_ready"
for secret_path in ("data/nvidia-api-key.txt", "data/render-api-key.txt", "data/cloud-automation-token.txt"):
    assert (ROOT / secret_path).read_text().strip() not in json.dumps(state)
result = {"ok": True, "url": BASE, "storage": health["storage"], "model": data["model"], "latency_ms": data["latency_ms"], "lead_id": lead_id, "status": lead["status"], "budget_after_review": 190000, "checks": ["health+Postgres", "NVIDIA extraction", "n8n token", "CSRF+HTTPS origin", "idempotency+conflict", "review+approval", "CRM stage", "no credentials in state"]}
(ROOT / "artifacts" / "cloud-smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
