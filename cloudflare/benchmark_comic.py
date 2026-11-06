"""Run a bounded real Workers AI comic benchmark; outputs stay local, never print secrets.

Uses the same prompts, validation and optional brief repair as the deployed worker.
Neurons are a tariff estimate from provider token usage and image dimensions, not a bill.
Run: backend/.venv/bin/python cloudflare/benchmark_comic.py --case benchmarks/comics/ice.json --out .tooling/comic-benchmark/ice
"""

import argparse
import asyncio
import json
import os
import sys
import time
import tomllib
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "cloudflare/src")]
from comic_art import IMAGE_SIZE, MODEL, page_prompt, unpack_image, visual_briefs  # noqa: E402

from app.config import Settings  # noqa: E402
from app.prompts import generation_payload, parse_completion  # noqa: E402
from app.schemas import GenerationInput, validate_result  # noqa: E402

TEXT_MODEL = "@cf/qwen/qwen3-30b-a3b-fp8"


class Provider:
    def __init__(self, client, base):
        self.client, self.base = client, base
        self.calls = []

    async def run(self, model, payload):
        start = time.monotonic()
        response = await self.client.post(self.base + "/ai/run/" + model, json=payload)
        data = response.json()
        result = data.get("result") or {}
        self.calls.append(
            {
                "model": model,
                "seconds": round(time.monotonic() - start, 2),
                "status": response.status_code,
                "usage": result.get("usage"),
                "error_codes": [e.get("code") for e in data.get("errors", [])],
            }
        )
        if response.status_code != 200 or data.get("success") is False:
            raise RuntimeError("provider_request_failed")
        return result


async def benchmark(args):
    request = GenerationInput.model_validate_json(args.case.read_text())
    if request.kind != "comic" or not request.include_images or not 1 <= request.length <= 4:
        raise ValueError("Benchmark requires 1-4 illustrated comic panels")
    if args.out.exists():
        raise ValueError("Use a new output directory; existing evaluations are not overwritten")
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        config = Path.home() / "Library/Preferences/.wrangler/config/default.toml"
        token = tomllib.loads(config.read_text())["oauth_token"]
    account = json.loads((ROOT / "cloudflare/wrangler.jsonc").read_text())["account_id"]
    base = f"https://api.cloudflare.com/client/v4/accounts/{account}"
    args.out.mkdir(parents=True)
    report = {
        "request": request.model_dump(),
        "image_model": MODEL,
        "image_size": args.size,
        "text_model": TEXT_MODEL,
        "pricing_source": "https://developers.cloudflare.com/workers-ai/platform/pricing/",
        "pricing_checked": "2026-11-06",
        "billing_verified": False,
    }
    async with httpx.AsyncClient(
        timeout=180, headers={"Authorization": "Bearer " + token}
    ) as client:
        provider = Provider(client, base)
        try:
            settings = Settings(_env_file=None, llm_model=TEXT_MODEL)
            payload = generation_payload(request, settings)
            payload.pop("model", None)
            payload.pop("reasoning_effort", None)
            if args.script:
                content = validate_result(
                    json.loads(args.script.read_text()), request, settings.max_result_bytes
                )
                briefs = [panel["image_prompt"] for panel in content["panels"]]
                report["mode"] = "editorial_script_image_only"
            else:
                content = parse_completion(
                    await provider.run(TEXT_MODEL, payload), request, settings
                )
                briefs = await visual_briefs(provider, TEXT_MODEL, content)
                for panel, brief in zip(content["panels"], briefs, strict=True):
                    panel["image_prompt"] = brief
                report["mode"] = "full_generation"
            prompt = (
                args.page_prompt.read_text()
                if args.page_prompt
                else page_prompt(briefs, request.style)
            )
            fields = {
                "prompt": prompt,
                "width": str(args.size),
                "height": str(args.size),
                "seed": str(args.seed),
            }
            start = time.monotonic()
            response = await client.post(
                base + "/ai/run/" + MODEL, files={k: (None, v) for k, v in fields.items()}
            )
            data = response.json()
            report["image_status"] = response.status_code
            report["image_usage"] = (data.get("result") or {}).get("usage")
            report["image_result_fields"] = [k for k in (data.get("result") or {}) if k != "image"]
            report["image_seconds"] = round(time.monotonic() - start, 2)
            if response.status_code != 200 or not data.get("success"):
                report["image_error_codes"] = [e.get("code") for e in data.get("errors", [])]
                raise RuntimeError("image_request_failed")
            image, mime = unpack_image(data["result"].get("image"))
            image_file = args.out / (
                "page.jpg"
                if mime == "image/jpeg"
                else "page.png"
                if mime == "image/png"
                else "page.webp"
            )
            image_file.write_bytes(image)
            (args.out / "content.json").write_text(
                json.dumps(content, ensure_ascii=False, indent=2)
            )
            (args.out / "page-prompt.txt").write_text(prompt)
            usages = [call["usage"] for call in provider.calls]
            measured_tokens = all(
                isinstance(u, dict)
                and all(
                    type(u.get(k)) is int and u[k] >= 0
                    for k in ("prompt_tokens", "completion_tokens")
                )
                for u in usages
            )
            text_neurons = (
                sum(
                    u["prompt_tokens"] * 0.004625 + u["completion_tokens"] * 0.030475
                    for u in usages
                )
                if measured_tokens
                else None
            )
            reported_text_neurons = (
                sum(u["neurons"] for u in usages)
                if all(
                    isinstance(u, dict) and type(u.get("neurons")) in (int, float) for u in usages
                )
                else None
            )
            report["text_neurons_reported"] = reported_text_neurons
            image_neurons = 26.05 * ((args.size + 511) // 512) ** 2
            report.update(
                success=True,
                calls=provider.calls,
                image_bytes=len(image),
                image_file=str(image_file),
                text_neurons_estimate=round(text_neurons, 3) if text_neurons is not None else None,
                image_neurons_estimate=image_neurons,
                total_neurons_estimate=round(text_neurons + image_neurons, 3)
                if text_neurons is not None
                else None,
            )
        except Exception as error:
            report.update(success=False, calls=provider.calls, error_type=type(error).__name__)
        (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in report.items() if k != "request"}, ensure_ascii=False))
        return report["success"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", type=int, choices=[512, 1024], default=IMAGE_SIZE)
    parser.add_argument(
        "--page-prompt",
        type=Path,
        help="Exact saved image prompt for a controlled image-only rerun",
    )
    parser.add_argument(
        "--script",
        type=Path,
        help="Reviewed content JSON; isolates image quality without an LLM call",
    )
    parser.add_argument("--seed", type=int, default=314159)
    args = parser.parse_args()
    if args.page_prompt and not args.script:
        parser.error("--page-prompt requires --script (image-only comparison)")
    return 0 if asyncio.run(benchmark(args)) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit(
            f"Benchmark stopped: {type(error).__name__} (details suppressed)"
        ) from None
