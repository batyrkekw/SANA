"""Validate requests before allocating a scarce ZeroGPU session."""

import hmac
import json


def authorize(headers, expected_key):
    if not isinstance(expected_key, str) or len(expected_key) < 32:
        raise ValueError("space_key_not_configured")
    headers = {str(k).lower(): str(v) for k, v in headers.items()}
    supplied = headers.get("x-sana-key", "")
    if not hmac.compare_digest(supplied.encode(), expected_key.encode()):
        raise PermissionError("unauthorized")


def normalize_request(value):
    if not isinstance(value, dict):
        raise ValueError("request_must_be_object")
    allowed = {
        "kind",
        "length",
        "subject",
        "topic",
        "grade",
        "language",
        "instructions",
    }
    if set(value) - allowed:
        raise ValueError("unexpected_request_fields")
    if value.get("kind", "comic") != "comic" or value.get("length", 4) != 4:
        raise ValueError("four_panel_comics_only")
    if type(value.get("grade")) is not int or not 1 <= value["grade"] <= 12:
        raise ValueError("invalid_grade")
    if not isinstance(value.get("language"), str) or value["language"] not in {
        "ru",
        "kk",
    }:
        raise ValueError("invalid_language")
    result = {"kind": "comic", "length": 4, "include_images": True}
    for key, maximum in (("subject", 100), ("topic", 200), ("instructions", 1500)):
        text = value.get(key, "")
        if not isinstance(text, str) or len(text.strip()) > maximum:
            raise ValueError("invalid_" + key)
        if key != "instructions" and not text.strip():
            raise ValueError("empty_" + key)
        result[key] = text.strip()
    result.update(grade=value["grade"], language=value["language"])
    return result


def check_adapter_config(config, model_id):
    if config.get("base_model_name_or_path") != model_id:
        raise ValueError("adapter_base_model_mismatch")
    if config.get("peft_type") != "LORA" or config.get("task_type") != "CAUSAL_LM":
        raise ValueError("unsupported_adapter")
    if type(config.get("r")) is not int or not 1 <= config["r"] <= 32:
        raise ValueError("unsupported_adapter_rank")
    targets = config.get("target_modules")
    if (
        not isinstance(targets, list)
        or not targets
        or not set(targets)
        <= {
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
        }
    ):
        raise ValueError("unsupported_adapter_targets")


def decode_content(text, language, validator):
    # No repair/retry here: one request must not silently consume extra GPU quota.
    content = json.loads(text)
    return validator(content, language)
