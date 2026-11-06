"""A separate SANA experiment; no automatic production routing."""
# ruff: noqa: I001

import os

import spaces  # noqa: F401 -- initialize ZeroGPU before any transitive torch import.
import gradio as gr
from service import authorize, normalize_request


def build_demo(engine, provenance, secret):
    if len(secret) < 32:
        raise ValueError("Configure SANA_SPACE_KEY before starting the Space")

    def story(request_json, request: gr.Request):
        try:
            authorize(request.headers, secret)
            clean = normalize_request(request_json)
        except (ValueError, PermissionError) as error:
            raise gr.Error(str(error)) from None
        try:
            return engine(clean)
        except Exception:
            # Do not echo provider internals, input material or credentials to clients.
            raise gr.Error("story_generation_failed") from None

    status = {**provenance, "site_connected": False, "status": "ready_for_testing"}
    with gr.Blocks(title="SANA Story Lab") as demo:
        gr.Markdown("# SANA Story Lab\nПроверка сценариев перед подключением к сайту.")
        label = (
            "Загружен экспериментальный адаптер. Качество ещё требует проверки."
            if provenance["fine_tuned"]
            else "Работает базовая Qwen. Дообученный адаптер пока не загружен."
        )
        gr.Markdown(
            label
            + "\n\nПубличный сайт продолжает использовать текущую модель Cloudflare."
        )
        status_output = gr.JSON(value=status, label="Состояние")
        refresh = gr.Button("Проверить состояние")
        refresh.click(
            lambda: status, outputs=status_output, api_name="status", queue=False
        )
        request_input = gr.JSON(visible=False)
        result_output = gr.JSON(visible=False)
        trigger = gr.Button("API", visible=False)
        trigger.click(
            story, inputs=request_input, outputs=result_output, api_name="story"
        )
    return demo.queue(max_size=4, default_concurrency_limit=1)


if __name__ == "__main__":
    secret = os.environ.get("SANA_SPACE_KEY", "")
    if len(secret) < 32:
        raise RuntimeError("SANA_SPACE_KEY is missing")
    from engine import load_engine

    engine, provenance = load_engine()
    build_demo(engine, provenance, secret).launch(show_error=False)
