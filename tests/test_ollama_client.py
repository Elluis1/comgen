import asyncio
import json
import logging

import httpx

from app import config
from app.config import DEFAULT_OLLAMA_MODEL, Settings, model_parameter_billions
from app.ollama_client import GENERATION_OPTIONS, OllamaEmpty, OllamaError, chat
from app.prompts import JSON_SCHEMA, SYSTEM_PROMPT, repair_prompt


def test_default_model_fits_a_small_notebook(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    settings = Settings()
    assert settings.ollama_model == DEFAULT_OLLAMA_MODEL == "gemma3:1b"
    assert model_parameter_billions(settings.ollama_model) == 1
    assert settings.ollama_timeout_seconds == 180.0


def test_model_size_comes_from_the_tag_not_the_family_name():
    assert model_parameter_billions("llama3.2:1b") == 1
    assert model_parameter_billions("qwen2.5:0.5b") == 0.5
    assert model_parameter_billions("qwen2.5:1.5b") == 1.5
    assert model_parameter_billions("qwen2.5:3b") == 3
    assert model_parameter_billions("gemma3:4b") == 4
    assert model_parameter_billions("qwen2.5:7b-instruct-q4_K_M") == 7
    assert model_parameter_billions("llama3.2") is None


def test_large_model_logs_a_spanish_warning_and_is_still_used(monkeypatch, caplog):
    config._warned_models.clear()
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b")
    with caplog.at_level(logging.WARNING, logger="comgen"):
        settings = Settings()
        again = Settings()
    assert settings.ollama_model == "qwen2.5:7b"
    assert again.ollama_model == "qwen2.5:7b"
    warnings = [record.message for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "7B" in warnings[0]
    assert "notebook" in warnings[0]
    assert DEFAULT_OLLAMA_MODEL in warnings[0]

    calls = _patch_client(
        monkeypatch,
        [_response(200, {"message": {"content": '{"kind":"fa"}'}})],
    )
    assert asyncio.run(chat(settings, [{"role": "user", "content": "paridad"}])) == '{"kind":"fa"}'
    assert calls[0]["json"]["model"] == "qwen2.5:7b"

    caplog.clear()
    config._warned_models.clear()
    monkeypatch.setenv("OLLAMA_MODEL", "gemma3:4b")
    with caplog.at_level(logging.WARNING, logger="comgen"):
        assert Settings().ollama_model == "gemma3:4b"
    assert any("4B" in record.message for record in caplog.records)


def test_models_up_to_about_3b_do_not_warn(monkeypatch, caplog):
    config._warned_models.clear()
    with caplog.at_level(logging.WARNING, logger="comgen"):
        for name in ("gemma3:1b", "qwen2.5:0.5b", "llama3.2:1b", "qwen2.5:3b", "llama3.2"):
            monkeypatch.setenv("OLLAMA_MODEL", name)
            assert Settings().ollama_model == name
    assert caplog.records == []


def test_system_prompt_stays_short_and_keeps_the_contract():
    assert len(SYSTEM_PROMPT) < 2600
    for piece in ("regex", '"spec"', '"fa"', "unsupported", "caa*b*", "(ab|ba)*aaa*(c|bb)*"):
        assert piece in SYSTEM_PROMPT
    repaired = repair_prompt(["falta pattern"], "comience por a*")
    assert "pattern" in repaired
    assert "caa*b*" in repaired


def test_chat_asks_for_json_schema_with_a_short_context(monkeypatch):
    calls = _patch_client(
        monkeypatch,
        [
            _response(200, {"message": {"content": '{"kind":"fa"}'}}),
        ],
    )
    settings = Settings()
    settings.ollama_timeout_seconds = 12
    text = asyncio.run(chat(settings, [{"role": "user", "content": "paridad"}]))

    assert text == '{"kind":"fa"}'
    assert len(calls) == 1
    payload = calls[0]["json"]
    assert payload["model"] == settings.ollama_model
    assert payload["stream"] is False
    assert payload["format"] == JSON_SCHEMA
    assert payload["format"]["properties"]["kind"]["enum"] == ["regex", "spec", "fa", "unsupported"]
    assert payload["options"] == GENERATION_OPTIONS == {
        "temperature": 0,
        "num_ctx": 4096,
        "num_predict": 768,
    }
    assert calls[0]["timeout"] == 12


def test_chat_falls_back_to_json_mode_when_the_schema_is_rejected(monkeypatch):
    calls = _patch_client(
        monkeypatch,
        [
            _response(400, {"error": "schema"}),
            _response(200, {"message": {"content": '{"kind":"regex"}'}}),
        ],
    )
    text = asyncio.run(chat(Settings(), [{"role": "user", "content": "a*"}]))
    assert text == '{"kind":"regex"}'
    assert calls[0]["json"]["format"] == JSON_SCHEMA
    assert calls[1]["json"]["format"] == "json"
    assert calls[1]["json"]["options"]["temperature"] == 0


def test_chat_falls_back_when_structured_output_is_empty(monkeypatch):
    calls = _patch_client(
        monkeypatch,
        [
            _response(200, {"message": {"content": "  "}}),
            _response(200, {"message": {"content": '{"kind":"fa"}'}}),
        ],
    )
    text = asyncio.run(chat(Settings(), [{"role": "user", "content": "paridad"}]))
    assert text == '{"kind":"fa"}'
    assert len(calls) == 2
    assert calls[1]["json"]["format"] == "json"


def test_chat_does_not_retry_when_ollama_is_down(monkeypatch):
    calls = _patch_client(monkeypatch, [], connect_error=True)
    try:
        asyncio.run(chat(Settings(), [{"role": "user", "content": "paridad"}]))
    except OllamaError as exc:
        assert "No pude conectar" in str(exc)
    else:
        raise AssertionError("tenía que fallar sin Ollama")
    assert len(calls) == 1


def test_empty_json_mode_is_an_error(monkeypatch):
    _patch_client(
        monkeypatch,
        [
            _response(400, {"error": "schema"}),
            _response(200, {"message": {"content": ""}}),
        ],
    )
    try:
        asyncio.run(chat(Settings(), [{"role": "user", "content": "paridad"}]))
    except OllamaEmpty:
        return
    raise AssertionError("una respuesta vacía tiene que fallar")


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.text = json.dumps(payload)
        self._payload = payload

    def json(self):
        return self._payload


def _response(status_code, payload):
    return _Response(status_code, payload)


def _patch_client(monkeypatch, responses, connect_error=False):
    calls = []

    class FakeClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, json):
            calls.append({"url": url, "json": json, "timeout": self.timeout})
            if connect_error:
                raise httpx.ConnectError("refused")
            return responses.pop(0)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    return calls
