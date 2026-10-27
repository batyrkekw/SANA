import json

import httpx
import pytest

from app.ai import LocalDiffusersProvider, LocalLLMProvider
from app.errors import AppError
from app.schemas import GenerationInput, Question, arithmetic, validate_result
from app.storage import LocalStorageProvider


def test_result_validation_checks_language_shape_and_limits(quiz):
    request = GenerationInput(kind="quiz", subject="Физика", topic="Ток")
    assert validate_result(quiz, request, 20000)["kind"] == "quiz"
    for data in [
        {**quiz, "language": "kk"},
        {**quiz, "questions": quiz["questions"][:1]},
        {**quiz, "kind": "lesson"},
    ]:
        with pytest.raises(ValueError):
            validate_result(data, request, 20000)
    with pytest.raises(ValueError):
        validate_result(quiz, request, 5)
    with pytest.raises(ValueError):
        Question(prompt="Тест", options=["A", "A"], correct_index=0, explanation="Тест")


def test_arithmetic_is_bounded_and_cannot_execute_code():
    assert arithmetic("(12 + 4) / 2") == 8
    for value in ["__import__('os').system('id')", "2 ** 10000000", "1/0", "[1,2]", "1e99"]:
        with pytest.raises(ValueError):
            arithmetic(value)


def test_storage_rejects_arbitrary_paths(tmp_path):
    storage = LocalStorageProvider(tmp_path)
    for key in ["../../etc/passwd", "/etc/passwd", "."]:
        with pytest.raises(AppError):
            storage.resolve(key)


def test_missing_image_dependencies_reported_without_download(config, monkeypatch):
    monkeypatch.setattr("app.ai.importlib.util.find_spec", lambda _: None)
    provider = LocalDiffusersProvider(config)
    assert provider.health_check()["status"] == "dependencies_missing"
    with pytest.raises(AppError, match="dependencies_missing"):
        provider.load_model()
    with pytest.raises(AppError, match="invalid_image_prompt"):
        provider.generate_image("x" * 6001, "educational", "1:1", 100)


def test_local_llm_adapter_validates_real_http_shape(config, quiz, monkeypatch):
    provider_result = json.loads(json.dumps(quiz))
    for question in provider_result["questions"]:
        question["correct_answer"] = question["options"][question.pop("correct_index")]

    def handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["response_format"]["type"] == "json_schema"
        schema = payload["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["questions"]["minItems"] == 3
        assert schema["properties"]["questions"]["maxItems"] == 3
        assert schema["properties"]["language"]["const"] == "ru"
        assert schema["additionalProperties"] is False
        assert "grade" not in schema["properties"]
        assert "correct_index" not in schema["$defs"]["Question"]["properties"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(provider_result)}}
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr("app.ai.httpx.stream", client.stream)
        result = LocalLLMProvider(config).generate(
            GenerationInput(kind="quiz", subject="Физика", topic="Ток")
        )
    assert result["title"] == quiz["title"]


def test_local_llm_does_not_accept_truncated_content(config, monkeypatch):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"finish_reason": "length"}]})
        )
    ) as client:
        monkeypatch.setattr("app.ai.httpx.stream", client.stream)
        with pytest.raises(AppError, match="model_output_truncated"):
            LocalLLMProvider(config).generate(GenerationInput(subject="Физика", topic="Ток"))


def test_arithmetic_rejects_wrong_selected_option(quiz):
    from app.schemas import EducationalContent

    quiz["questions"][0]["arithmetic_check"] = {"expression": "2+2", "result": 4}
    quiz["questions"][0]["correct_index"] = 0
    with pytest.raises(ValueError, match="Selected numeric answer"):
        EducationalContent.model_validate(quiz)
    quiz["questions"][0]["correct_index"] = 1
    EducationalContent.model_validate(quiz)


def test_provider_answer_must_match_an_option(config, quiz, monkeypatch):
    for question in quiz["questions"]:
        question.pop("correct_index")
        question["correct_answer"] = "not one of the options"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(quiz)}}]
                },
            )
        )
    ) as client:
        monkeypatch.setattr("app.ai.httpx.stream", client.stream)
        with pytest.raises(AppError, match="invalid_model_output"):
            LocalLLMProvider(config).generate(
                GenerationInput(kind="quiz", subject="Физика", topic="Ток")
            )
