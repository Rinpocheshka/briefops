"""Validate deployable Python and static sources without touching a database."""
import ast
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for filename in ("app.py", "llm.py", "database.py", "access.py", "email_delivery.py"):
    ast.parse((root / filename).read_text(encoding="utf-8"), filename)
for path in (root / "workflows").glob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
for filename in ("static/index.html", "static/styles.css", "static/app.js", "static/auth.js", "static/login.html", "requirements.txt"):
    assert (root / filename).stat().st_size > 0, filename
print("BUILD OK: Python syntax, workflow JSON and static assets validated")
