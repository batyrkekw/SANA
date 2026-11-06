"""Prepare/publish only SANA's ZeroGPU Space. No paid hardware fallback."""

import argparse
import json
import re
import secrets
import shutil
from pathlib import Path

from huggingface_hub import HfApi, SpaceHardware
from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".env.huggingface.local"
SPACE_NAME = "sana-story-lab"
MARKER = "learn-sana"


def local_values():
    values = {}
    if LOCAL.is_file():
        for line in LOCAL.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    return values


def save_local(values):
    # This file is already excluded by .gitignore; never write tokens into the bundle.
    LOCAL.write_text(
        "# Local SANA Hugging Face configuration. Never commit this file.\n"
        + "".join(f"{key}={value}\n" for key, value in values.items())
    )
    LOCAL.chmod(0o600)


def package():
    out = ROOT / ".tooling/huggingface-space-build"
    out.mkdir(parents=True, exist_ok=True)
    names = ("app.py", "engine.py", "service.py", "README.md", "requirements.txt")
    for name in names:
        shutil.copy2(ROOT / "huggingface/space" / name, out / name)
    shutil.copy2(ROOT / "training/comics/protocol.py", out / "protocol.py")
    return out, [*names, "protocol.py"]


def runtime_summary(api, repo_id):
    runtime = api.get_space_runtime(repo_id)
    print(
        json.dumps(
            {
                "space": repo_id,
                "stage": runtime.stage,
                "hardware": runtime.hardware,
                "requested_hardware": runtime.requested_hardware,
            }
        )
    )
    return runtime


def run(command):
    out, names = package()
    if command == "package":
        print(f"Prepared {len(names)} explicitly allowed source files; no credentials.")
        return
    values = local_values()
    token = values.get("HF_TOKEN", "")
    if not token.startswith("hf_"):
        raise SystemExit(
            "Save HF_TOKEN in .env.huggingface.local first; do not paste it in chat."
        )
    api = HfApi(token=token)
    identity = api.whoami()
    owner = identity.get("name", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", owner):
        raise SystemExit("Unable to confirm a personal Hugging Face account")
    repo_id = f"{owner}/{SPACE_NAME}"
    print(
        json.dumps(
            {
                "account": owner,
                "email_verified": identity.get("emailVerified"),
                "target_space": repo_id,
            }
        )
    )
    if command == "check":
        print(
            "Authentication checked. Free ZeroGPU eligibility is confirmed only when its request succeeds."
        )
        return
    if command == "status":
        runtime_summary(api, repo_id)
        return
    if command != "publish":
        raise ValueError("Unknown command")
    try:
        api.repo_info(repo_id=repo_id, repo_type="space")
        exists = True
    except RepositoryNotFoundError as error:
        if error.response is not None and error.response.status_code not in (404,):
            raise
        exists = False
    key = values.get("SANA_SPACE_KEY", "") or secrets.token_urlsafe(48)
    if len(key) < 32:
        raise SystemExit("SANA_SPACE_KEY must have at least 32 characters")
    if exists:
        variables = api.get_space_variables(repo_id)
        marker = variables.get("SANA_PROJECT")
        if not marker or marker.value != MARKER:
            raise SystemExit(
                "Existing Space is not marked as this SANA project; refusing to overwrite"
            )
        runtime = api.get_space_runtime(repo_id)
        if any(
            h and h != SpaceHardware.ZERO_A10G
            for h in (
                runtime.hardware,
                runtime.requested_hardware,
            )
        ):
            raise SystemExit(
                "Existing hardware is not ZeroGPU; refusing to change billing/hardware"
            )
        api.add_space_secret(repo_id, key="SANA_SPACE_KEY", value=key)
    else:
        # Explicit ZeroGPU: never create cpu-basic then upgrade, never pick a paid GPU.
        api.create_repo(
            repo_id=repo_id,
            repo_type="space",
            space_sdk="gradio",
            private=False,
            space_hardware=SpaceHardware.ZERO_A10G,
            space_secrets=[{"key": "SANA_SPACE_KEY", "value": key}],
            space_variables=[{"key": "SANA_PROJECT", "value": MARKER}],
        )
    values.update(SANA_HF_SPACE=repo_id, SANA_SPACE_KEY=key)
    save_local(values)
    api.upload_folder(
        repo_id=repo_id,
        repo_type="space",
        folder_path=out,
        allow_patterns=names,
        commit_message="Prepare SANA ZeroGPU story pilot; baseline until reviewed adapter is configured",
    )
    runtime_summary(api, repo_id)
    print(f"https://huggingface.co/spaces/{repo_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("package", "check", "publish", "status"))
    try:
        run(parser.parse_args().command)
    except HfHubHTTPError as error:
        status = error.response.status_code if error.response is not None else "unknown"
        # Avoid printing requests, headers, credential-bearing object representations.
        raise SystemExit(
            f"Hugging Face HTTP {status}. No paid fallback was requested. "
            "Check token permissions, account verification and free ZeroGPU eligibility."
        ) from None
