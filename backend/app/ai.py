import importlib.util
import json
import time
from functools import lru_cache
from typing import Protocol

import httpx
from PIL import Image

from app.config import Settings, get_settings
from app.errors import AppError
from app.prompts import generation_payload, parse_completion
from app.schemas import GenerationInput


class TextGenerationProvider(Protocol):
    def generate(self, request: GenerationInput) -> dict: ...
    def health_check(self) -> dict: ...


class ImageGenerationProvider(Protocol):
    def load_model(self) -> None: ...
    def generate_image(
        self, prompt: str, style: str, aspect_ratio: str, deadline: float
    ) -> Image.Image: ...
    def health_check(self) -> dict: ...
    def get_model_info(self) -> dict: ...
    def unload_model(self) -> None: ...


class LocalLLMProvider:
    """OpenAI-compatible local servers: Ollama, llama.cpp, LM Studio. No paid API required."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def health_check(self) -> dict:
        if not self.settings.llm_model:
            return {"status": "not_configured", "model": None}
        try:
            result = httpx.get(
                self.settings.llm_base_url.rstrip("/") + "/models",
                timeout=3,
                headers=self._headers(),
            )
            result.raise_for_status()
            models = {model["id"] for model in result.json().get("data", [])}
            return {
                "status": "available" if self.settings.llm_model in models else "model_missing",
                "model": self.settings.llm_model,
            }
        except (httpx.HTTPError, ValueError, KeyError):
            return {"status": "unavailable", "model": self.settings.llm_model}

    def _headers(self) -> dict:
        key = self.settings.llm_api_key.get_secret_value()
        return {"Authorization": f"Bearer {key}"} if key else {}

    def generate(self, request: GenerationInput) -> dict:
        if not self.settings.llm_model:
            raise AppError("text_model_not_configured", 503)
        try:
            # Stream only transport bytes to enforce a bounded response, not token streaming.
            with httpx.stream(
                "POST",
                self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                headers=self._headers(),
                timeout=self.settings.llm_timeout_seconds,
                json=generation_payload(request, self.settings),
            ) as response:
                response.raise_for_status()
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > self.settings.max_result_bytes * 3:
                        raise AppError("invalid_model_output", 502)
            return parse_completion(json.loads(chunks), request, self.settings)
        except httpx.TimeoutException as error:
            raise AppError("generation_timeout", 504) from error
        except httpx.HTTPError as error:
            raise AppError("text_model_unavailable", 503) from error
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise AppError("invalid_model_output", 502) from error


STYLES = {
    "educational": "clear educational illustration, clean composition, no text",
    "cartoon": "friendly classroom cartoon, consistent simple shapes, no text",
    "infographic": "minimal educational infographic illustration, simple symbols, no text",
    "historical": "historical educational illustration, careful period details, no text",
    "scientific": "clear scientific illustration, legible shapes, no text",
}


class LocalDiffusersProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pipeline = None
        self.device = None

    def get_model_info(self) -> dict:
        return {
            "id": self.settings.image_model_id,
            "provider": "local_diffusers",
            "device": self.device or self.settings.image_device,
            "size": self.settings.image_size,
            "steps": self.settings.image_steps,
        }

    def health_check(self) -> dict:
        if not self.settings.image_enabled:
            return {**self.get_model_info(), "status": "disabled"}
        if not all(importlib.util.find_spec(name) for name in ("torch", "diffusers")):
            return {**self.get_model_info(), "status": "dependencies_missing"}
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(
                self.settings.image_model_id,
                cache_dir=self.settings.model_cache_dir,
                local_files_only=True,
            )
            status = "loaded" if self.pipeline else "cached_not_verified"
        except Exception:
            status = "weights_missing"
        return {**self.get_model_info(), "status": status}

    def load_model(self) -> None:
        if self.pipeline is not None:
            return
        if not self.settings.image_enabled:
            raise AppError("image_model_not_enabled", 503)
        status = self.health_check()["status"]
        if status in ("dependencies_missing", "weights_missing"):
            raise AppError(status, 503)
        try:
            import torch
            from diffusers import AutoPipelineForText2Image

            device = self.settings.image_device
            if device == "auto":
                device = (
                    "cuda"
                    if torch.cuda.is_available()
                    else ("mps" if torch.backends.mps.is_available() else "cpu")
                )
            self.device = device
            pipeline = AutoPipelineForText2Image.from_pretrained(
                self.settings.image_model_id,
                cache_dir=self.settings.model_cache_dir,
                local_files_only=True,
                use_safetensors=True,
                variant=self.settings.image_variant or None,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            )
            pipeline = pipeline.to(device)
            pipeline.enable_attention_slicing()
            pipeline.enable_vae_slicing()
            pipeline.set_progress_bar_config(disable=True)
            self.pipeline = pipeline
        except Exception as error:
            self.unload_model()
            raise AppError("model_load_failed", 503) from error

    def generate_image(
        self, prompt: str, style: str, aspect_ratio: str, deadline: float
    ) -> Image.Image:
        if len(prompt) > 6000 or not prompt.strip() or style not in STYLES:
            raise AppError("invalid_image_prompt", 422)
        self.load_model()
        size = self.settings.image_size
        short = max(256, int(size * 0.75) // 64 * 64)
        shapes = {"1:1": (size, size), "4:3": (size, short), "3:4": (short, size)}
        if aspect_ratio not in shapes:
            raise AppError("invalid_aspect_ratio", 422)

        def step_callback(_pipe, _step, _timestep, kwargs):
            if time.monotonic() > deadline:
                raise AppError("generation_timeout", 504)
            return kwargs

        try:
            import torch

            width, height = shapes[aspect_ratio]
            if time.monotonic() > deadline:
                raise AppError("generation_timeout", 504)
            with torch.inference_mode():
                result = self.pipeline(
                    prompt=f"{STYLES[style]}. {prompt}",
                    width=width,
                    height=height,
                    num_inference_steps=self.settings.image_steps,
                    callback_on_step_end=step_callback,
                )
            if any(getattr(result, "nsfw_content_detected", None) or []):
                raise AppError("image_filtered", 422)
            image = result.images[0]
            if not isinstance(image, Image.Image) or image.size != (width, height):
                raise AppError("invalid_model_output", 502)
            return image.convert("RGB")
        except AppError:
            raise
        except Exception as error:
            code = (
                "model_out_of_memory"
                if "out of memory" in str(error).lower()
                else "image_inference_failed"
            )
            self.unload_model()
            raise AppError(code, 503) from error

    def unload_model(self) -> None:
        self.pipeline = None
        if importlib.util.find_spec("torch"):
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()


@lru_cache
def image_provider() -> LocalDiffusersProvider:
    return LocalDiffusersProvider(get_settings())
