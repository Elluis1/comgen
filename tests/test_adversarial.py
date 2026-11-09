"""Ataques de la corrida Romper: no usan Ollama."""

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from xml.parsers.expat import ParserCreate

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.examples import EXAMPLES
from app.export_jflap import export_jflap
from app.familias import recognize_family
from app.interpret import ModelReplyError, interpret_text
from app.main import app
from app.memory import MemoryStoreError, save, search
from app.ollama_client import OllamaBadPayload, OllamaError, chat, list_models
from app.prompts import memory_context
from app.regex_lang import RegexError, compile_pattern
from app.sanitize import declared_alphabet
from app.schemas import FiniteAutomaton, State, Transition
from app.service import (
    create_session,
    export_session,
    handle_message,
    load_example,
    payload,
    remember_solution,
    run_word,
)
from app.simulate import simulate
from app.store import store
from app.validate import prepare_fa, validate_fa


def _strict_xml(document: str) -> None:
    ParserCreate(encoding="UTF-8").Parse(document.encode("utf-8"), True)


def test_deeply_nested_parentheses_fail_in_spanish_and_a_shallow_one_works():
    shallow = "(" * 8 + "a" + ")" * 8
    automaton, _explanation = compile_pattern(shallow)
    assert simulate(automaton, "a").accepted is True
    assert simulate(automaton, "").accepted is False

    started = time.perf_counter()
    with pytest.raises(RegexError, match="paréntesis"):
        compile_pattern("(" * 400 + "a" + ")" * 400)
    assert time.perf_counter() - started < 2


def test_braces_and_brackets_are_not_silent_literals():
    for pattern in ("a{2}", "a{2,5}", "(ab){3}", "a[0-9]", "a[0-9]*"):
        with pytest.raises(RegexError):
            compile_pattern(pattern)
    with pytest.raises(RegexError, match="llaves"):
        compile_pattern("a{2}")
    with pytest.raises(RegexError, match="corchetes"):
        compile_pattern("a[0-9]*")
    plain, _explanation = compile_pattern("aa")
    assert simulate(plain, "aa").accepted is True
    assert simulate(plain, "a{2}").accepted is False


def test_nfd_letter_is_one_symbol_in_a_pattern_and_in_the_statement():
    automaton, _explanation = compile_pattern("e\u0301*")
    assert automaton.alphabet == ["é"]
    assert simulate(automaton, "éé").accepted is True
    assert simulate(automaton, "").accepted is True
    assert declared_alphabet("sobre {e\u0301, o\u0301}") == ["é", "ó"]


def test_accented_alphabet_is_not_folded_away():
    phrase = "un AFD sobre {á, é} con cantidad par de á"
    result = recognize_family(phrase)
    assert result is not None and result.automaton is not None
    assert result.export_ready
    assert result.errors == []
    assert result.automaton.alphabet == ["á", "é"]
    automaton = result.automaton
    assert simulate(automaton, "").accepted is True
    assert simulate(automaton, "é").accepted is True
    assert simulate(automaton, "áá").accepted is True
    assert simulate(automaton, "á").accepted is False
    assert simulate(automaton, "éáé").accepted is False
    _strict_xml(export_jflap(automaton))

    folded = "un AFD sobre {e\u0301, o\u0301} con cantidad par de e\u0301"
    nfd = recognize_family(folded)
    assert nfd is not None and nfd.automaton is not None
    assert nfd.automaton.alphabet == ["é", "ó"]
    assert simulate(nfd.automaton, "éé").accepted is True
    assert simulate(nfd.automaton, "é").accepted is False


def test_family_cannot_smuggle_symbols_outside_the_statement(monkeypatch):
    def fake(_text):
        from app.interpret import Interpretation

        return Interpretation(
            explanation="binario",
            automaton=EXAMPLES["paridad"].automaton,
            export_ready=True,
        )

    monkeypatch.setattr("app.service.recognize_family", fake)

    async def explode(_settings, _messages):
        raise AssertionError("no tiene que llamar al modelo")

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", explode):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "un AFD sobre {a, b} para este ataque"},
            )
    body = response.json()
    assert response.status_code == 200
    assert body["automaton"] is None
    assert body["export_ready"] is False
    text = body["messages"][-1]["content"]
    assert "{a, b}" in text
    assert "0" in text or "1" in text


def test_epsilon_cycle_accepts_without_hanging_and_nfa_keeps_both_branches():
    cycle = FiniteAutomaton(
        deterministic=False,
        alphabet=["a", "ε", "lambda"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="ε"),
            Transition(from_state="q1", to="q0", read="lambda"),
            Transition(from_state="q1", to="q1", read="eps"),
            Transition(from_state="q1", to="q1", read="a"),
        ],
    )
    prepared, _notes = prepare_fa(cycle)
    assert validate_fa(prepared).ok
    assert simulate(prepared, "").accepted is True
    assert simulate(prepared, "aaa").accepted is True
    dead = FiniteAutomaton(
        deterministic=False,
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q0", read=""),
            Transition(from_state="q0", to="q1", read="a"),
            Transition(from_state="q1", to="q1", read="a"),
        ],
    )
    dead_prepared, _notes = prepare_fa(dead)
    assert simulate(dead_prepared, "").accepted is False
    assert simulate(dead_prepared, "a").accepted is True

    # «a» acepta por una rama y «aa» cae en la otra, que no es final.
    branch = FiniteAutomaton(
        deterministic=False,
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=False),
            State(id="q2", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="a"),
            Transition(from_state="q0", to="q2", read="a"),
            Transition(from_state="q1", to="q1", read="a"),
            Transition(from_state="q2", to="q1", read="a"),
        ],
    )
    branched, _notes = prepare_fa(branch)
    assert validate_fa(branched).ok
    assert simulate(branched, "").accepted is False
    assert simulate(branched, "a").accepted is True
    assert simulate(branched, "aa").accepted is False

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        store.get(session_id).automaton = prepared
        empty = client.post(f"/api/sessions/{session_id}/simulate", json={"word": ""})
        assert empty.status_code == 200
        assert empty.json()["accepted"] is True
        exported = client.get(f"/api/sessions/{session_id}/export")
        assert exported.status_code == 200
        _strict_xml(exported.text)
        assert "\r" not in exported.headers["content-disposition"]
        assert "\n" not in exported.headers["content-disposition"]


def test_model_json_rejects_a_huge_integer_and_truncates_a_long_modulus():
    huge = (
        '{"kind":"spec","family":"divisible","modulus":'
        + "9" * 5000
        + ',"base":2,"description":"d","explanation":"e","pattern":"",'
        + '"deterministic":true,"alphabet":[],"states":[],"transitions":[]}'
    )
    with pytest.raises(ModelReplyError, match="demasiado grande") as caught:
        interpret_text(huge)
    assert "999999" not in caught.value.errors[0]

    long = (
        '{"kind":"spec","family":"divisible","modulus":'
        + "9" * 80
        + ',"base":2,"description":"d","explanation":"e","pattern":"",'
        + '"deterministic":true,"alphabet":[],"states":[],"transitions":[]}'
    )
    with pytest.raises(ModelReplyError, match="demasiado grande") as caught:
        interpret_text(long)
    assert len(caught.value.errors[0]) < 180
    assert "…" in caught.value.errors[0]
    assert "128" in caught.value.errors[0]


def test_nested_regex_from_the_model_is_an_error_response_not_a_crash():
    pattern = "(" * 400 + "a" + ")" * 400

    async def fake_chat(_settings, _messages):
        return json.dumps(
            {
                "kind": "regex",
                "pattern": pattern,
                "description": "anidada",
                "explanation": "anidada",
            }
        )

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "compilá esta expresión rara a+"},
            )
    assert response.status_code == 200
    body = response.json()
    assert body["automaton"] is None
    assert "paréntesis" in body["messages"][-1]["content"]


def test_bad_api_payloads_do_not_crash_and_the_download_name_stays_a_filename():
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        listed = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": ["hola"]},
        )
        assert listed.status_code == 422
        blank = client.post(f"/api/sessions/{session_id}/messages", json={"text": "   "})
        assert blank.status_code == 400
        assert "enunciado" in blank.json()["detail"]
        missing = client.get("/api/sessions/no-existe/export")
        assert missing.status_code == 404
        loaded = client.post(f"/api/sessions/{session_id}/examples/paridad")
        assert loaded.status_code == 200
        store.get(session_id).automaton = EXAMPLES["paridad"].automaton.model_copy(
            update={"description": 'a"\r\nX-Evil: 1'}
        )
        exported = client.get(f"/api/sessions/{session_id}/export")
        disposition = exported.headers["content-disposition"]
        assert exported.status_code == 200
        assert "\r" not in disposition
        assert "\n" not in disposition
        assert '"' not in disposition.split("filename=", 1)[-1].strip('"') or disposition.count('"') == 2
        assert "X-Evil" not in exported.headers


def test_payload_is_a_snapshot_not_the_live_log():
    session = create_session()
    load_example(session.id, "paridad")
    body = payload(session)
    session.ui.append({"role": "user", "content": "inyectado"})
    assert all(item.get("content") != "inyectado" for item in body["messages"])


def test_corrupt_memory_shapes_do_not_crash_or_get_overwritten(tmp_path):
    from app.memory import set_memory_path

    path = tmp_path / "solutions.json"
    original = json.dumps(
        {"solutions": [{"tokens": None, "request": "paridad de unos", "explanation": 12}]}
    )
    path.write_text(original, encoding="utf-8")
    set_memory_path(path)
    assert search("paridad de unos binaria") == []
    with pytest.raises(MemoryStoreError, match="dañada"):
        save(request="paridad de unos binaria", explanation="x", automaton={})
    assert path.read_text(encoding="utf-8") == original

    path.write_text('{"solutions":{"no":"lista"}}', encoding="utf-8")
    with pytest.raises(MemoryStoreError, match="dañada"):
        save(request="otra cosa distinta", explanation="x", automaton={})
    assert path.read_text(encoding="utf-8") == '{"solutions":{"no":"lista"}}'

    path.write_bytes("\ufeff{}".encode("utf-16"))
    assert search("paridad de unos") == []
    before = path.read_bytes()
    with pytest.raises(MemoryStoreError):
        save(request="paridad de unos", explanation="x", automaton={})
    assert path.read_bytes() == before

    good = {
        "solutions": [
            {
                "request": "paridad de unos",
                "tokens": ["paridad", "unos"],
                "pattern": "",
                "explanation": "q0 es par.",
            }
        ]
    }
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(good).encode("utf-8"))
    found = search("quiero paridad de unos")
    assert found and found[0]["request"] == "paridad de unos"
    assert "q0 es par." in memory_context(found)

    directory = tmp_path / "directorio.json"
    directory.mkdir()
    set_memory_path(directory)
    assert search("paridad de unos") == []
    with pytest.raises(MemoryStoreError):
        save(request="paridad de unos", explanation="x", automaton={})
    assert directory.is_dir()


def test_oversized_memory_is_left_alone(tmp_path, monkeypatch):
    from app import memory as memory_module
    from app.memory import set_memory_path

    monkeypatch.setattr(memory_module, "_MAX_MEMORY_BYTES", 40)
    path = tmp_path / "solutions.json"
    original = json.dumps(
        {"solutions": [{"request": "paridad de unos bien larga", "tokens": ["paridad", "unos"]}]}
    )
    assert len(original.encode("utf-8")) > 40
    path.write_text(original, encoding="utf-8")
    set_memory_path(path)
    assert search("paridad de unos") == []
    with pytest.raises(MemoryStoreError, match="demasiado grande"):
        save(request="otro pedido distinto", explanation="x", automaton={})
    assert path.read_text(encoding="utf-8") == original


def test_concurrent_saves_keep_a_valid_file():
    errors = []

    def worker(index: int) -> None:
        try:
            save(
                request=f"pedido alfa{index} beta{index} gamma{index} unico",
                explanation="ok",
                automaton={"alphabet": ["a"], "states": [], "transitions": []},
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    from app.memory import count

    assert count() == 12


def test_concurrent_session_use_does_not_crash():
    session = create_session()
    load_example(session.id, "paridad")
    errors: list[BaseException] = []

    def sync_work() -> None:
        try:
            for _ in range(20):
                # Entre un enunciado y el siguiente el autómata se vacía a propósito.
                try:
                    run_word(session.id, "11")
                    export_session(session.id)
                except ValueError:
                    pass
                try:
                    remember_solution(session.id)
                except (ValueError, MemoryStoreError):
                    pass
                load_example(session.id, "termina-en-01")
        except Exception as exc:
            errors.append(exc)

    async def async_work() -> None:
        await asyncio.gather(
            *[
                handle_message(session.id, "cadenas binarias con cantidad par de unos")
                for _ in range(4)
            ]
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(sync_work) for _ in range(4)]
        asyncio.run(async_work())
        for future in futures:
            future.result()
    assert errors == []
    assert run_word(session.id, "11")["ok"] is True


def test_ollama_garbage_is_an_error_in_spanish_and_health_stays_up(monkeypatch):
    responses = []

    class Response:
        def __init__(self, status_code, payload=None, boom=False):
            self.status_code = status_code
            self.text = "" if payload is None else json.dumps(payload)
            self._payload = payload
            self._boom = boom

        def json(self):
            if self._boom:
                raise json.JSONDecodeError("bad", "", 0)
            return self._payload

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, json=None):
            return responses.pop(0)

        async def get(self, url):
            return responses.pop(0)

    monkeypatch.setattr("app.ollama_client.httpx.AsyncClient", FakeClient)

    responses.extend(
        [
            Response(200, boom=True),
            Response(200, boom=True),
        ]
    )
    with pytest.raises(OllamaBadPayload, match="no devolvió JSON"):
        asyncio.run(chat(Settings(), [{"role": "user", "content": "paridad"}]))

    responses.append(Response(200, payload=[]))
    with pytest.raises(OllamaError, match="no devolvió JSON"):
        asyncio.run(list_models(Settings()))

    responses.append(Response(200, payload={"models": ["gemma3:1b", {"name": "gemma3:1b"}]}))
    assert asyncio.run(list_models(Settings())) == ["gemma3:1b"]

    async def broken(_settings):
        raise OllamaError("Ollama no devolvió JSON.")

    monkeypatch.setattr("app.main.list_models", broken)
    with TestClient(app) as client:
        health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["online"] is False


def test_nfd_symbol_from_the_model_becomes_one_character():
    raw = json.dumps(
        {
            "kind": "fa",
            "pattern": "",
            "description": "una e acentuada",
            "explanation": "q0 lee é.",
            "deterministic": True,
            "alphabet": ["e\u0301"],
            "states": [{"id": "q0", "initial": True, "final": True}],
            "transitions": [{"from": "q0", "to": "q0", "read": "e\u0301"}],
        }
    )
    parsed = interpret_text(raw, "un AFD sobre {é}")
    assert parsed.automaton is not None
    assert parsed.automaton.alphabet == ["é"]
    assert simulate(parsed.automaton, "é").accepted is True
