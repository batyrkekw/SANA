"""Small, explicit QLoRA experiment. Run on a Colab NVIDIA GPU, never as a web server."""

import argparse
import hashlib
import html
import json
import os
import random
import shutil
import subprocess
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from protocol import (
    MODEL_ID,
    MODEL_REVISION,
    SYSTEM,
    check_output,
    encode_example,
    load_records,
    messages_for,
)

HERE = Path(__file__).resolve().parent


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class StoryDataset:
    def __init__(self, examples):
        self.examples = examples

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, index):
        return self.examples[index]


class Collator:
    def __init__(self, pad_id):
        self.pad_id = pad_id

    def __call__(self, features):
        import torch

        length = max(len(x["input_ids"]) for x in features)
        return {
            key: torch.tensor(
                [row[key] + [fill] * (length - len(row[key])) for row in features]
            )
            for key, fill in (
                ("input_ids", self.pad_id),
                ("attention_mask", 0),
                ("labels", -100),
            )
        }


def generate_eval(model, tokenizer, records, max_new_tokens):
    import torch

    outputs = []
    model.eval()
    model.config.use_cache = True
    for row in records:
        inputs = tokenizer.apply_chat_template(
            messages_for(row),
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(model.device)
        with torch.inference_mode():
            result = model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=max_new_tokens,
                pad_token_id=tokenizer.pad_token_id,
            )
        completion = result[0, inputs["input_ids"].shape[-1] :]
        text = tokenizer.decode(completion, skip_special_tokens=True)
        truncated = len(completion) >= max_new_tokens and completion[-1].item() not in (
            tokenizer.eos_token_id,
            tokenizer.pad_token_id,
        )
        try:
            check_output(json.loads(text), row["request"]["language"])
            valid, error = not truncated, "length" if truncated else None
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            valid, error = False, type(exc).__name__
        outputs.append(
            {
                "id": row["id"],
                "text": text,
                "structurally_valid": valid,
                "error": error,
                "generated_tokens": len(completion),
                "truncated": truncated,
            }
        )
        print(
            f"Evaluation {row['id']}: {len(completion)} tokens; JSON valid={valid}",
            flush=True,
        )
    model.config.use_cache = False
    return outputs


def write_comparison(out, records, before, after):
    """Randomized labels reduce reviewer expectation; the separate key is not embedded."""
    rng = random.Random(20261106)
    key, sections = {}, []
    for row, base, tuned in zip(records, before, after, strict=True):
        pair = [("base", base), ("adapter", tuned)]
        rng.shuffle(pair)
        key[row["id"]] = {
            label: item[0] for label, item in zip(("A", "B"), pair, strict=True)
        }
        cards = []
        for label, (_, result) in zip(("A", "B"), pair, strict=True):
            try:
                value = json.loads(result["text"])
                body = f"<h3>{html.escape(str(value.get('title', '')))}</h3>"
                for i, panel in enumerate(value.get("panels", []), 1):
                    body += (
                        f"<p><b>{i}. {html.escape(str(panel.get('scene', '')))}</b></p>"
                    )
                    for field in ("dialogue", "narration", "image_prompt"):
                        body += f"<p>{html.escape(str(panel.get(field, '')))}</p>"
            except (ValueError, TypeError, AttributeError):
                body = "<pre>" + html.escape(result["text"]) + "</pre>"
            cards.append(f"<article><h2>Вариант {label}</h2>{body}</article>")
        sections.append(
            f"<section><h2>{html.escape(row['request']['topic'])}</h2>"
            f"<p>{row['request']['grade']} класс · {row['request']['language']}</p>"
            f"<div class='pair'>{''.join(cards)}</div></section>"
        )
    (out / "comparison.html").write_text(
        "<!doctype html><html lang='ru'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>SANA: проверка сценариев</title><style>"
        "body{font:17px/1.6 system-ui;background:#edf2f8;color:#172842;margin:24px}"
        "main{max-width:1200px;margin:auto}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}"
        "article{background:white;padding:24px;border-radius:18px;min-width:0}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}section{margin:40px 0}"
        "@media(max-width:700px){.pair{grid-template-columns:1fr}body{margin:12px}}"
        "</style><main><h1>Какая история лучше?</h1>"
        "<p>Оцените каждый вариант: точность, понятность для возраста, сюжет, юмор, "
        "рисуемость — по 0–2 балла. Критическая фактическая ошибка означает отклонение. "
        "Ничья допустима. Это тексты, рисунки здесь не проверяются. "
        "Ключ вариантов лежит отдельно в comparison-key.json; сначала оцените вслепую.</p>"
        + "".join(sections)
        + "</main></html>"
    )
    save_json(out / "comparison-key.json", key)
    save_json(
        out / "review-template.json",
        [
            {"id": r["id"], "winner": None, "A": {}, "B": {}, "notes": ""}
            for r in records
        ],
    )


def run(args):
    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    records = load_records(args.data)
    if not args.check_data and not args.cpu_smoke:
        if not torch.cuda.is_available():
            raise SystemExit(
                "Нет NVIDIA GPU. В Colab выбери Среда выполнения → Сменить тип → T4 GPU."
            )
        if torch.cuda.get_device_properties(0).total_memory < 14 * 1024**3:
            raise SystemExit(
                "Для этого пилота нужен GPU примерно с 15–16 ГБ памяти или больше."
            )
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    train_rows = [r for r in records if r["split"] == "train"]
    eval_rows = [r for r in records if r["split"] == "eval"]
    train_data = StoryDataset(
        [encode_example(tokenizer, r, args.max_length) for r in train_rows]
    )
    eval_data = StoryDataset(
        [encode_example(tokenizer, r, args.max_length) for r in eval_rows]
    )
    lengths = [len(x["input_ids"]) for x in train_data.examples + eval_data.examples]
    print(
        f"Validated {len(train_rows)} train / {len(eval_rows)} held-out; max tokens={max(lengths)}"
    )
    if args.check_data:
        return
    out = Path(args.output)
    if out.exists():
        raise SystemExit(
            "Output directory exists. Choose a new run directory; results are not overwritten."
        )
    out.mkdir(parents=True)
    set_seed(42)
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    if args.cpu_smoke:
        from transformers import Qwen3Config, Qwen3ForCausalLM

        # Tests the real Trainer/PEFT plumbing with random tiny weights, not model quality.
        # Keep a prompt prefix and supervised suffix; avoid a huge CPU logits tensor.
        train_data = StoryDataset(
            [{key: values[:24] + values[-24:] for key, values in train_data[0].items()}]
        )
        model = Qwen3ForCausalLM(
            Qwen3Config(
                vocab_size=len(tokenizer),
                hidden_size=32,
                intermediate_size=64,
                num_hidden_layers=1,
                num_attention_heads=2,
                num_key_value_heads=1,
                head_dim=16,
                max_position_embeddings=args.max_length,
            )
        )
    else:
        from transformers import BitsAndBytesConfig

        bf16 = torch.cuda.is_bf16_supported()
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            revision=MODEL_REVISION,
            device_map={"": 0},
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16 if bf16 else torch.float16,
            ),
            torch_dtype=torch.bfloat16 if bf16 else torch.float16,
            attn_implementation="sdpa",
        )
        model = prepare_model_for_kbit_training(
            model,
            gradient_checkpointing_kwargs={"use_reentrant": False},
        )
    model = get_peft_model(
        model,
        LoraConfig(
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        ),
    )
    model.config.use_cache = False
    model.print_trainable_parameters()
    smoke = args.cpu_smoke
    initial_adapter = {
        name: parameter.detach().clone()
        for name, parameter in model.named_parameters()
        if smoke and parameter.requires_grad
    }
    manifest = {
        "status": "started",
        "smoke_only": smoke,
        "model": "tiny-random-Qwen3" if smoke else MODEL_ID,
        "tokenizer_model": MODEL_ID,
        "revision": MODEL_REVISION,
        "dataset_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
        "seed": 42,
        "max_length": args.max_length,
        "epochs": args.epochs,
        "max_new_tokens": args.max_new_tokens,
        "train_ids": [r["id"] for r in train_rows],
        "eval_ids": [r["id"] for r in eval_rows],
        "started_utc": datetime.now(UTC).isoformat(),
        "gpu": torch.cuda.get_device_name(0) if not smoke else "CPU tiny random model",
        "packages": {
            p: version(p) for p in ("torch", "transformers", "peft", "accelerate")
        },
        "quality_approved": False,
        "deployed": False,
    }
    if not smoke:
        manifest["packages"]["bitsandbytes"] = version("bitsandbytes")
    git = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True
    )
    source_revision = HERE / "source-revision.txt"
    manifest["code_revision"] = (
        git.stdout.strip()
        if git.returncode == 0
        else source_revision.read_text().strip()
        if source_revision.exists()
        else None
    )
    save_json(out / "manifest.json", manifest)
    (out / "system-prompt.txt").write_text(SYSTEM)
    if not smoke:
        with model.disable_adapter():
            before = generate_eval(model, tokenizer, eval_rows, args.max_new_tokens)
        save_json(out / "before.json", before)
    train_args = TrainingArguments(
        output_dir=str(out / "checkpoints"),
        num_train_epochs=args.epochs,
        max_steps=1 if smoke else -1,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=1 if smoke else 4,
        learning_rate=5e-5,
        warmup_ratio=0 if smoke else 0.1,
        lr_scheduler_type="linear",
        optim="adamw_torch",
        weight_decay=0.01,
        fp16=not smoke and not bf16,
        bf16=not smoke and bf16,
        gradient_checkpointing=not smoke,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=1,
        save_strategy="steps",
        save_steps=4,
        save_total_limit=2,
        eval_strategy="no",
        report_to="none",
        seed=42,
        data_seed=42,
        dataloader_num_workers=0,
        use_cpu=smoke,
    )
    trainer = Trainer(
        model=model,
        args=train_args,
        train_dataset=train_data,
        eval_dataset=eval_data,
        data_collator=Collator(tokenizer.pad_token_id),
        processing_class=tokenizer,
    )
    # Held-out text is never used for gradient updates or checkpoint selection.
    before_loss = trainer.evaluate()["eval_loss"] if not smoke else None
    result = trainer.train()
    if smoke and not any(
        not torch.equal(parameter.detach(), initial_adapter[name])
        for name, parameter in model.named_parameters()
        if name in initial_adapter
    ):
        raise RuntimeError("CPU smoke failed: no adapter weight changed")
    model.save_pretrained(out / "adapter", safe_serialization=True)
    tokenizer.save_pretrained(out / "adapter")
    (out / "adapter/README.md").write_text(
        "# SANA comic story pilot\n\nBase: "
        + ("TINY RANDOM SMOKE MODEL, NOT QWEN 4B" if smoke else MODEL_ID)
        + " at "
        + MODEL_REVISION
        + ". Base license: Apache-2.0.\n\nSmall synthetic experiment, not quality-approved. "
        "Use the saved system-prompt.txt. This adapter cannot be loaded into the current "
        "Cloudflare Qwen3-30B endpoint. No image model was trained.\n"
    )
    after_loss = trainer.evaluate()["eval_loss"] if not smoke else None
    if not smoke:
        model.gradient_checkpointing_disable()
        after = generate_eval(model, tokenizer, eval_rows, args.max_new_tokens)
        save_json(out / "after.json", after)
        write_comparison(out, eval_rows, before, after)
    manifest.update(
        {
            "status": "cpu_smoke_completed"
            if smoke
            else "training_completed_pending_review",
            "finished_utc": datetime.now(UTC).isoformat(),
            "steps": trainer.state.global_step,
            "train_metrics": result.metrics,
            "eval_loss_before": before_loss,
            "eval_loss_after": after_loss,
            "log_history": trainer.state.log_history,
            "peak_gpu_gib": torch.cuda.max_memory_allocated() / 1024**3
            if not smoke
            else None,
        }
    )
    save_json(out / "manifest.json", manifest)
    bundle = out / "download"
    bundle.mkdir()
    shutil.copytree(out / "adapter", bundle / "adapter")
    for path in out.iterdir():
        if path.is_file():
            shutil.copy2(path, bundle / path.name)
    archive = shutil.make_archive(str(out / "sana-comic-pilot"), "zip", bundle)
    print(
        f"Saved {archive}. Training completion is not quality approval or deployment."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=HERE / "data/stories.jsonl")
    parser.add_argument("--output", default="/content/sana-comic-pilot")
    parser.add_argument("--check-data", action="store_true")
    parser.add_argument(
        "--cpu-smoke",
        action="store_true",
        help="One step on a tiny random model; no CUDA/4B weights",
    )
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--max-new-tokens", type=int, default=1200)
    parser.add_argument("--epochs", type=int, default=2, choices=(1, 2, 3))
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    run(args)


if __name__ == "__main__":
    main()
