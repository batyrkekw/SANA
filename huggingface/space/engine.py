"""Load on emulated CUDA at startup; actual inference runs only inside spaces.GPU."""

import os
import re
import time

import spaces  # Must initialize ZeroGPU before importing torch.
import torch
from huggingface_hub import hf_hub_download
from peft import PeftModel
from protocol import MODEL_ID, MODEL_REVISION, check_output, messages_for
from service import check_adapter_config, decode_content
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = None
TOKENIZER = None
PROVENANCE = {
    "model": MODEL_ID,
    "model_revision": MODEL_REVISION,
    "fine_tuned": False,
    "quality_approved": False,
    "provider": "huggingface_zerogpu",
}


def load_engine():
    import json
    from pathlib import Path

    global MODEL, TOKENIZER
    if not os.environ.get("SPACE_ID"):
        raise RuntimeError("Run this service on a Hugging Face ZeroGPU Space.")
    adapter_repo = os.environ.get("SANA_ADAPTER_REPO", "").strip()
    adapter_revision = os.environ.get("SANA_ADAPTER_REVISION", "").strip()
    if bool(adapter_repo) != bool(adapter_revision):
        raise ValueError("Set both adapter repo and immutable revision")
    if adapter_repo and not re.fullmatch(r"[0-9a-f]{40}", adapter_revision):
        raise ValueError("Adapter revision must be an exact commit SHA")
    adapter_path = None
    if adapter_repo:
        config_path = hf_hub_download(
            adapter_repo,
            "adapter_config.json",
            revision=adapter_revision,
        )
        check_adapter_config(json.loads(Path(config_path).read_text()), MODEL_ID)
        weights_path = hf_hub_download(
            adapter_repo,
            "adapter_model.safetensors",
            revision=adapter_revision,
        )
        if Path(weights_path).stat().st_size > 300 * 1024**2:
            raise ValueError("Adapter exceeds pilot size limit")
        adapter_path = str(Path(config_path).parent)
    TOKENIZER = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
    TOKENIZER.pad_token = TOKENIZER.eos_token
    MODEL = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
        trust_remote_code=False,
    )
    if adapter_path:
        MODEL = PeftModel.from_pretrained(MODEL, adapter_path, is_trainable=False)
        PROVENANCE.update(
            fine_tuned=True,
            adapter_repo=adapter_repo,
            adapter_revision=adapter_revision,
        )
    MODEL.to("cuda")
    MODEL.eval()
    MODEL.config.use_cache = True
    return generate, dict(PROVENANCE)


@spaces.GPU(duration=60)
def generate(request):
    started = time.monotonic()
    inputs = TOKENIZER.apply_chat_template(
        messages_for({"request": request}),
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(MODEL.device)
    if inputs["input_ids"].shape[-1] > 1600:
        raise ValueError("input_token_limit")
    with torch.inference_mode():
        output = MODEL.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=1200,
            pad_token_id=TOKENIZER.pad_token_id,
        )
    generated = output[0, inputs["input_ids"].shape[-1] :]
    if len(generated) >= 1200 and generated[-1].item() != TOKENIZER.eos_token_id:
        raise ValueError("model_output_truncated")
    content = decode_content(
        TOKENIZER.decode(generated, skip_special_tokens=True),
        request["language"],
        check_output,
    )
    return {
        "content": content,
        "provenance": dict(PROVENANCE),
        "usage": {
            "input_tokens": inputs["input_ids"].shape[-1],
            "output_tokens": len(generated),
        },
        "inference_seconds": round(time.monotonic() - started, 3),
    }
