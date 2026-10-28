"""Package the shared API; write public runtime config, never copy .env or local data."""

import base64
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "cloudflare"
OUT = HERE / ".build"
OUT.mkdir(exist_ok=True)
for path in (HERE / "src").glob("*.py"):
    shutil.copyfile(path, OUT / path.name)
shutil.copytree(
    ROOT / "backend/app",
    OUT / "app",
    dirs_exist_ok=True,
    ignore=shutil.ignore_patterns("__pycache__", "worker.py", "manage.py", "ai.py", "storage.py"),
)
# Only the two explicitly public browser settings cross the build boundary.
values = {}
for line in (ROOT / ".env").read_text().splitlines():
    if line.startswith(("SANA_SUPABASE_URL=", "SANA_SUPABASE_PUBLISHABLE_KEY=")):
        key, value = line.split("=", 1)
        values[key] = value.strip().strip("\"'")
if not all(values.get(key) for key in ("SANA_SUPABASE_URL", "SANA_SUPABASE_PUBLISHABLE_KEY")):
    raise SystemExit("Configure public Supabase URL and publishable key in root .env first")
public_key = values["SANA_SUPABASE_PUBLISHABLE_KEY"]
if not public_key.startswith("sb_publishable_"):
    try:
        payload = public_key.split(".")[1]
        role = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role")
        if role != "anon":
            raise ValueError("Not an anonymous key")
    except (IndexError, ValueError, TypeError):
        raise SystemExit(
            "Use a publishable or legacy anon key; refusing to package a secret"
        ) from None
config = json.loads((HERE / "wrangler.jsonc").read_text())
config["vars"] = {"SANA_PUBLIC_CONFIG": json.dumps(values)}
connection = HERE / "hyperdrive.json"
if connection.exists():
    config["hyperdrive"] = [json.loads(connection.read_text())]
(HERE / "wrangler.local.json").write_text(json.dumps(config, indent=2) + "\n")
print("Shared Python API and public configuration prepared; secrets excluded.")
shutil.copytree(ROOT / "dist", OUT / "site", dirs_exist_ok=True)
shutil.copytree(
    HERE / "pages",
    OUT / "site",
    dirs_exist_ok=True,
    ignore=shutil.ignore_patterns("wrangler.jsonc"),
)
(OUT / "site/sana-config.json").write_text(
    json.dumps(
        {
            "auth_configured": True,
            "supabase_url": values["SANA_SUPABASE_URL"],
            "supabase_publishable_key": public_key,
            "google_oauth_enabled": False,
            "api_base": "/api/v1",
        }
    )
    + "\n"
)
