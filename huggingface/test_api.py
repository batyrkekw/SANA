"""Exercise actual Gradio HTTP/queue with a fake engine; no GPU/LLM claim."""

import os
import socket
import sys
from pathlib import Path

os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "space"))

from app import build_demo  # noqa: E402
from gradio_client import Client  # noqa: E402

calls = []


def fake_engine(value):
    calls.append(value)
    return {"test_fixture": True, "language": value["language"]}


with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
key = "test-key-" * 8
demo = build_demo(fake_engine, {"fine_tuned": False, "quality_approved": False}, key)
try:
    _, url, _ = demo.launch(
        server_name="127.0.0.1",
        server_port=port,
        prevent_thread_lock=True,
        quiet=True,
        show_error=False,
    )
    public = Client(url, verbose=False)
    status = public.predict(api_name="/status")
    assert status["fine_tuned"] is False and not calls
    request = {"subject": "Математика", "topic": "Доли", "language": "ru", "grade": 4}
    try:
        public.predict(request, api_name="/story")
    except Exception:
        pass
    else:
        raise AssertionError("Unauthenticated story was accepted")
    assert not calls, "Unauthorized call reached the GPU boundary"
    authenticated = Client(url, headers={"X-SANA-Key": key}, verbose=False)
    result = authenticated.predict(request, api_name="/story")
    assert result == {"test_fixture": True, "language": "ru"}
    assert len(calls) == 1 and calls[0]["length"] == 4
    try:
        authenticated.predict({**request, "grade": True}, api_name="/story")
    except Exception:
        pass
    else:
        raise AssertionError("Invalid grade was accepted")
    assert len(calls) == 1, "Invalid input reached the GPU boundary"
    print(
        "PASS: actual Gradio API status, authenticated call, unauthorized/invalid requests rejected before engine"
    )
    print("Engine was a test fixture; no real model or GPU was used.")
finally:
    demo.close()
