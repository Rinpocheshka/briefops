"""Create a source-only archive; never include runtime data or API tokens."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
output = root.parent / "BriefOps.zip"
excluded = {"data", "artifacts", "__pycache__", ".git", "node_modules", ".venv", ".agents", ".claude", ".codex"}
with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in excluded for part in relative.parts):
            continue
        if path.name == ".neon" or path.name.startswith(".env") and path.name != ".env.example" or path.suffix in {".pyc", ".sqlite3", ".log"}:
            continue
        archive.write(path, Path("briefops") / relative)
with ZipFile(output) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    assert "briefops/app.py" in names and "briefops/workflows/intake.json" in names
    assert not any("automation-token" in n or "/data/" in n or "/artifacts/" in n for n in names)
print(f"Source archive ready: {output.name}; files: {len(names)}; bytes: {output.stat().st_size}")
