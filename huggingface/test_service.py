"""CPU contract tests only; no model weights, auth tokens or GPU requests."""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "space"), str(HERE.parent / "training/comics")]

from protocol import MODEL_ID, check_output, load_records  # noqa: E402
from service import authorize, check_adapter_config, decode_content, normalize_request  # noqa: E402


class ServiceTests(unittest.TestCase):
    def test_missing_and_wrong_keys_are_rejected(self):
        for headers in ({}, {"X-SANA-Key": "wrong"}):
            with self.assertRaises(PermissionError):
                authorize(headers, "a" * 64)
        authorize({"X-SANA-Key": "a" * 64}, "a" * 64)
        with self.assertRaises(ValueError):
            authorize({}, "")

    def test_inputs_are_bounded_before_inference(self):
        valid = {"subject": "Математика", "topic": "Доли", "language": "ru", "grade": 4}
        self.assertEqual(normalize_request(valid)["length"], 4)
        for bad in (
            {"grade": True},
            {"language": "en"},
            {"language": []},
            {"topic": "x" * 201},
            {"instructions": "x" * 1501},
            {"length": 8},
            {"model": "some/other-model"},
        ):
            with self.assertRaises(ValueError):
                normalize_request({**valid, **bad})

    def test_wrong_adapter_base_or_modules_are_rejected(self):
        config = {
            "base_model_name_or_path": MODEL_ID,
            "peft_type": "LORA",
            "task_type": "CAUSAL_LM",
            "r": 8,
            "target_modules": ["q_proj", "v_proj"],
        }
        check_adapter_config(config, MODEL_ID)
        for bad in (
            {"base_model_name_or_path": ""},
            {"base_model_name_or_path": "Qwen/other"},
            {"peft_type": "OTHER"},
            {"r": 128},
            {"target_modules": []},
            {"target_modules": ["lm_head"]},
        ):
            with self.assertRaises(ValueError):
                check_adapter_config({**config, **bad}, MODEL_ID)

    def test_invalid_model_response_is_not_repaired(self):
        rows = load_records(HERE.parent / "training/comics/data/stories.jsonl")
        row = rows[0]
        text = json.dumps(row["target"], ensure_ascii=False)
        self.assertEqual(decode_content(text, "ru", check_output), row["target"])
        with self.assertRaises(ValueError):
            decode_content("```json\n" + text + "\n```", "ru", check_output)
        with self.assertRaises(ValueError):
            decode_content(text, "kk", check_output)


if __name__ == "__main__":
    unittest.main()
