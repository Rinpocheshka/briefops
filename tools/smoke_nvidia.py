"""Live synthetic contract check. Saves only non-secret test results."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import Store
from llm import load_local_settings, NVIDIA_MODEL

assert load_local_settings(ROOT), "Local NVIDIA config missing"
target = ROOT / "artifacts" / ("nvidia-smoke-" + str(time.time_ns()) + ".sqlite3")
store = Store(target, use_llm=True, demo=False)
cases = [
    ("automation", False, 150000, "Хочу, чтобы заявки с лендинга автоматически попадали в CRM, а менеджер получал уведомление. На это есть 150 тыс. рублей. Запуск не срочный. Контакт demo@example.com."),
    ("bot", True, 90000, "Нужен чат-бот в Telegram для записи в студию. Сделать срочно, на этой неделе. Бюджет 90 тыс. рублей. demo2@example.com"),
    ("unknown", False, None, "Здравствуйте, можно обсудить проект? Пока не знаю, какой инструмент нам нужен."),
]
report = []
for service, urgent, budget, text in cases:
    lead_id = store.intake({"text": text, "source": "manual"})["id"]
    store.process_one(lead_id)
    lead = store.get_lead(lead_id)
    data = lead["analysis"]
    ok = data.get("engine") == "llm" and data["service"] == service and data["urgent"] == urgent and data["budget"] == budget
    report.append({"expected_service": service, "service": data.get("service"), "engine": data.get("engine"), "latency_ms": data.get("latency_ms"), "status": lead["status"], "ok": ok})
assert "key" not in store.state()["llm"]
result = {"model": NVIDIA_MODEL, "cases": report, "passed": sum(item["ok"] for item in report), "total": len(report)}
(ROOT / "artifacts" / "nvidia-smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
sys.exit(0 if all(item["ok"] for item in report) else 1)
