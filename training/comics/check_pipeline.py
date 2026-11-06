import copy
import json
import tempfile
from pathlib import Path

from protocol import MODEL_ID, MODEL_REVISION, encode_example, load_records
from train import Collator, write_comparison
from transformers import AutoTokenizer

rows = load_records(Path(__file__).resolve().parent / "data/stories.jsonl")
tok = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
tok.pad_token = tok.eos_token
items = [encode_example(tok, r, 2048) for r in rows]
for item in items:
    labels = item["labels"]
    first = next(i for i, v in enumerate(labels) if v != -100)
    assert first > 0 and labels[:first] == [-100] * first
    assert labels[first:] == item["input_ids"][first:]
    # Qwen's template appends a newline after the supervised end-of-turn token.
    assert tok.eos_token_id in labels[first:]
batch = Collator(tok.pad_token_id)(items[:2])
for i, item in enumerate(items[:2]):
    n = len(item["labels"])
    assert batch["labels"][i, n:].tolist() == [-100] * (batch["labels"].shape[1] - n)
    assert batch["attention_mask"][i, n:].sum() == 0
try:
    encode_example(tok, rows[0], 20)
except ValueError:
    pass
else:
    raise AssertionError("Silent truncation")
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    bad = copy.deepcopy(rows)
    bad[-1]["topic_group"] = bad[0]["topic_group"]
    p = d / "bad.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in bad))
    try:
        load_records(p)
    except ValueError as e:
        assert "leakage" in str(e)
    else:
        raise AssertionError("Topic leakage not rejected")
    held = [r for r in rows if r["split"] == "eval"]
    valid = [dict(text=json.dumps(r["target"])) for r in held]
    write_comparison(d, held, valid, valid)
    assert (d / "comparison.html").exists()
    assert len(json.loads((d / "comparison-key.json").read_text())) == 4
    malformed = [dict(text="<script>alert(1)</script>") for _ in held]
    write_comparison(d, held, malformed, malformed)
    assert "<script>" not in (d / "comparison.html").read_text()
print(
    "PASS: assistant-only loss, EOS loss, padding, fail on truncation, topic isolation, review escaping"
)
