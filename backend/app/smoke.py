"""Explicit real inference checks. Never run by the unit test suite."""

import argparse
import json
import time
from pathlib import Path

from app.ai import LocalDiffusersProvider, LocalLLMProvider
from app.config import ROOT, get_settings
from app.schemas import GenerationInput


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["image", "lesson", "quiz", "comic", "flashcards"])
    parser.add_argument("--language", choices=["ru", "kk"], default="ru")
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path, default=ROOT / ".data/smoke")
    args = parser.parse_args()
    config = get_settings()
    args.output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    if args.kind == "image":
        config = config.model_copy(update={"image_enabled": True})
        provider = LocalDiffusersProvider(config)
        result = provider.generate_image(
            "A friendly white dove next to a blue school book, simple clear shapes, golden sunlight",
            "educational",
            "1:1",
            start + config.job_timeout_seconds,
        )
        path = args.output / "image.png"
        result.save(path)
        print(
            json.dumps(
                {
                    "status": "generated",
                    "file": str(path),
                    "size": result.size,
                    "model": provider.get_model_info(),
                    "seconds": round(time.monotonic() - start, 2),
                }
            )
        )
        provider.unload_model()
    else:
        if args.model:
            config = config.model_copy(update={"llm_model": args.model})
        result = LocalLLMProvider(config).generate(
            GenerationInput(
                kind=args.kind,
                subject="Математика",
                topic="Сложение натуральных чисел",
                grade=5,
                language=args.language,
                length=3,
            )
        )
        path = args.output / f"{args.kind}-{args.language}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    "status": "generated_and_validated",
                    "file": str(path),
                    "model": config.llm_model,
                    "seconds": round(time.monotonic() - start, 2),
                }
            )
        )


if __name__ == "__main__":
    main()
