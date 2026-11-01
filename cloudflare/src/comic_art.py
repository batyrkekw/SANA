"""Private Workers AI/KV adapters. No GPU, user keys or public bucket URLs."""

import asyncio
import base64
import binascii
import json
import logging
import re

from app.errors import AppError

MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
# One 512px page per comic, distilled four-step model (Apache-2.0).
IMAGE_SIZE = 512
logger = logging.getLogger("sana.art")
MAX_PANEL_BYTES = 1024 * 1024


class TransientRenderError(AppError):
    pass


def daily_quota_exhausted(exc):
    message = str(exc).lower()
    return "daily free allocation" in message and any(
        word in message for word in ("used up", "exceed", "exhaust")
    )


def provider_error(exc):
    # Never log provider messages (they can echo the prompt). Classify locally.
    if daily_quota_exhausted(exc):
        return AppError("ai_daily_quota_exhausted", 429)
    message = str(exc).lower()
    denied = any(
        word in message
        for word in (
            "quota",
            "limit",
            "429",
            "filter",
            "moderat",
            "safety",
            "policy",
            "nsfw",
            "payment",
            "forbidden",
        )
    )
    temporary = isinstance(exc, TimeoutError) or bool(
        re.search(
            r"\b50[0234]\b|temporar|bad gateway|service unavailable|internal server error|upstream connect",
            message,
        )
    )
    code = re.search(r"\b(?:[1-5]\d{2}|[1-9]\d{3})\b", message)
    logger.warning(
        "comic_provider_failure type=%s code=%s transient=%s restricted=%s",
        type(exc).__name__,
        code.group() if code else "unknown",
        temporary,
        denied,
    )
    cls = TransientRenderError if temporary and not denied else AppError
    return cls("image_inference_failed", 503)


def unpack_image(encoded):
    if not isinstance(encoded, str) or not 0 < len(encoded) <= 4 * ((MAX_PANEL_BYTES + 2) // 3):
        raise AppError("image_inference_failed", 502)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise AppError("image_inference_failed", 502) from error
    if len(data) <= MAX_PANEL_BYTES:
        if data.startswith(b"\xff\xd8\xff"):
            return data, "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return data, "image/png"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return data, "image/webp"
    raise AppError("image_inference_failed", 502)


async def visual_briefs(ai, model, content):
    """Repair unusable art briefs once, including English-looking CamelCase tags."""
    prompts = [p["image_prompt"] for p in content["panels"]]

    def valid(items):
        return (
            isinstance(items, list)
            and len(items) == len(prompts)
            and all(
                isinstance(p, str)
                and 0 < len(p) <= 2500
                and len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", p)) >= 8
                and not re.search("[Ѐ-ԯ]", p)
                for p in items
            )
        )

    if valid(prompts):
        return prompts
    response = await asyncio.wait_for(
        ai.run(
            model,
            {
                "messages": [
                    {
                        "role": "system",
                        "content": "Rewrite the supplied comic panels as standalone English image prompts. Preserve their order and educational meaning. Use normal English sentences WITH SPACES, 40-100 words per prompt, never CamelCase tags. Name the central physical object, its small or large scale, its exact current state and the parts that must remain visibly connected. For a process, preserve the starting object instead of replacing it with a standalone organ or a later-stage object. Lead with that subject, then the stable surroundings; observers are secondary. Describe one clear drawable scene, not an abstract concept. Never ask for lettering. Return JSON with a single prompts array of English strings.",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {key: content.get(key) for key in ("title", "objectives", "panels")},
                            ensure_ascii=False,
                        ),
                    },
                ],
                "max_tokens": 2000,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
        ),
        timeout=90,
    )
    try:
        result = json.loads(response["choices"][0]["message"]["content"])["prompts"]
        if not valid(result):
            raise ValueError
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise AppError("invalid_model_output", 502) from exc
    return result


def page_prompt(briefs, style):
    """All frames share one canvas; positions are structural, never model-generated JSON."""
    layouts = {
        1: ("one full-page panel", ["Full page"]),
        2: ("two equal panels side by side", ["Left", "Right"]),
        3: (
            "two equal panels across the top and one wide panel below",
            ["Top left", "Top right", "Bottom"],
        ),
        4: (
            "a strict 2 by 2 grid of four equal square panels",
            ["Top left", "Top right", "Bottom left", "Bottom right"],
        ),
    }
    if len(briefs) not in layouts:
        raise AppError("plan_limit", 422)
    layout, positions = layouts[len(briefs)]
    scenes = "\n".join(
        f"{position} panel: {brief[:1000]}"
        for position, brief in zip(positions, briefs, strict=True)
    )
    return (
        f"Draw ONE complete {style} educational comic page with {layout}. "
        "Use thin straight black panel borders and narrow white gutters. Read left to right, top to bottom. "
        "Each panel is a different moment of ONE coherent story. Repeat the SAME characters, "
        "clothing, objects and drawing style. Clean hand-drawn outlines, flat warm colors, "
        "simple uncluttered backgrounds, large clear subjects. Keep physical counts and connections accurate. "
        "No text, letters, numbers, captions, labels, speech bubbles or extra panels. "
        "Do not merge the moments into a single scene.\n" + scenes
    )


async def render_page(ai, briefs, style):
    from workers import FormData, Response

    form = FormData(
        {
            "prompt": page_prompt(briefs, style),
            "width": str(IMAGE_SIZE),
            "height": str(IMAGE_SIZE),
        }
    )
    packet = Response(form)
    try:
        result = await asyncio.wait_for(
            ai.run(
                MODEL,
                {
                    "multipart": {
                        "body": packet.body,
                        "contentType": packet.headers["content-type"],
                    }
                },
            ),
            timeout=75,
        )
        encoded = result.get("image")
        if not encoded:
            logger.warning("comic_empty_image")
        return unpack_image(encoded)
    except AppError:
        raise
    except Exception as error:
        raise provider_error(error) from error


async def store_panel(kv, key, image):
    from workers import Blob

    data, mime = image
    # Pass a native ArrayBuffer rather than copying bytes through RPC one by one.
    await kv.put(key, await Blob([data], content_type=mime).js_object.arrayBuffer())
