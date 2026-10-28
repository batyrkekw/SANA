"""Create the SANA Hyperdrive binding using the existing Wrangler login.

Run after migrate.py. Passwords remain in request bodies, never argv or logs.
"""

import json
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ACCOUNT = "1f10d8debbf323a3c6778e33f1cb1f78"


def main():
    values = {}
    for line in (ROOT / ".env.cloudflare.local").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip()
    password = values.get("SANA_CLOUD_RUNTIME_PASSWORD")
    if not password:
        raise SystemExit("Run the database migration first")
    auth_path = Path.home() / "Library/Preferences/.wrangler/config/default.toml"
    token = tomllib.loads(auth_path.read_text())["oauth_token"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/hyperdrive/configs"

    def api(method="GET", body=None):
        request = urllib.request.Request(
            url,
            method=method,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            data=json.dumps(body).encode() if body else None,
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.load(response)
        if not data.get("success"):
            raise RuntimeError("Cloudflare request failed")
        return data["result"]

    existing = [row for row in api() if row["name"] == "sana-postgres"]
    if existing:
        result = existing[0]
        if (
            result["origin"]["host"] != "db.xbmphrhmgahqydrdbgbi.supabase.co"
            or result["origin"]["user"] != "sana_runtime"
        ):
            raise SystemExit("Existing Hyperdrive resource has another origin; no changes made")
        if not result.get("caching", {}).get("disabled"):
            raise SystemExit("Disable Hyperdrive query caching before using transactional balances")
    else:
        result = api(
            "POST",
            {
                "name": "sana-postgres",
                "origin": {
                    "scheme": "postgresql",
                    "host": "db.xbmphrhmgahqydrdbgbi.supabase.co",
                    "port": 5432,
                    "database": "postgres",
                    "user": "sana_runtime",
                    "password": password,
                },
                "caching": {"disabled": True},
                "origin_connection_limit": 5,
                "mtls": {
                    "sslmode": "verify-full",
                    "ca_certificate_id": json.loads((HERE / "certs/cloudflare.json").read_text())[
                        "id"
                    ],
                },
            },
        )
    binding = {"binding": "HYPERDRIVE", "id": result["id"]}
    (HERE / "hyperdrive.json").write_text(json.dumps(binding, indent=2) + "\n")
    print("Hyperdrive configured with TLS, disabled caching and limited SANA database role.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print(
            "Provisioning failed:",
            type(error).__name__,
            "(credential details suppressed)",
            file=sys.stderr,
        )
        sys.exit(1)
