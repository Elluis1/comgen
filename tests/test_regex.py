import json
import re
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.interpret import interpret_text
from app.main import app
from app.memory import set_memory_path
from app.ollama_client import OllamaError
from app.regex_lang import RegexError, compile_pattern, extract_regex
from app.service import _looks_like_regex_request
from app.simulate import simulate
from app.validate import validate_fa


def _accepted(pattern: str, word: str) -> bool:
    automaton, _explanation = compile_pattern(pattern)
    result = simulate(automaton, word)
    assert result.ok, result.message
    return result.accepted


def test_user_phrase_becomes_the_regex_and_uses_two_b_states():
    phrase = "quiero que me des un afd que comience por a* siga con bbb* y termine con cc*"
    assert extract_regex(phrase) == "a*bbb*cc*"

    automaton, explanation = compile_pattern("a*bbb*cc*")
    check = validate_fa(automaton)
    assert check.errors == []
    assert check.warnings == []
    assert "dos estados de verificación para b" in explanation
    assert "primera b" in explanation
    assert "segunda b" in explanation

    exits: dict[tuple[str, str], list[str]] = {}
    for transition in automaton.transitions:
        exits.setdefault((transition.from_state, transition.read), []).append(transition.to)
    for targets in exits.values():
        assert len(targets) == 1

    assert _accepted("a*bbb*cc*", "bbc")
    assert _accepted("a*bbb*cc*", "bbbc")
    assert _accepted("a*bbb*cc*", "abbc")
    assert _accepted("a*bbb*cc*", "aabbbcc")
    assert not _accepted("a*bbb*cc*", "")
    assert not _accepted("a*bbb*cc*", "bc")
    assert not _accepted("a*bbb*cc*", "bb")
    assert not _accepted("a*bbb*cc*", "bbca")
    assert not _accepted("a*bbb*cc*", "ccc")
    assert not _accepted("a*bbb*cc*", "abc")


def test_extract_leaves_non_regex_sentences_alone():
    assert extract_regex("cadenas binarias con cantidad par de unos") is None
    assert extract_regex("un AFD que termine en 01") is None
    assert extract_regex("agregá una transición con a*") is None
    assert extract_regex("a* bbb* cc*") == "a*bbb*cc*"


def test_other_regular_expressions():
    assert _accepted("a*", "")
    assert _accepted("a*", "aa")
    assert _accepted("(a|b)*abb", "abb")
    assert _accepted("(a|b)*abb", "babb")
    assert _accepted("(a|b)*abb", "aabb")
    assert not _accepted("(a|b)*abb", "ab")
    assert not _accepted("(a|b)*abb", "abba")
    assert not _accepted("(a|b)*abb", "")
    assert _accepted("bb+", "bb")
    assert _accepted("bb+", "bbbb")
    assert not _accepted("bb+", "b")


def test_starts_with_c_then_aa_star_then_b_star():
    assert _accepted("caa*b*", "ca")
    assert _accepted("caa*b*", "caa")
    assert _accepted("caa*b*", "cab")
    assert _accepted("caa*b*", "caabb")
    assert not _accepted("caa*b*", "")
    assert not _accepted("caa*b*", "c")
    assert not _accepted("caa*b*", "cb")
    assert not _accepted("caa*b*", "a")
    assert not _accepted("caa*b*", "cabc")

    raw = json.dumps(
        {
            "kind": "regex",
            "pattern": "",
            "description": "caa*b*",
            "explanation": "el modelo dejó la expresión en description",
        }
    )
    parsed = interpret_text(raw)
    assert parsed.export_ready
    assert simulate(parsed.automaton, "cab").accepted
    assert not simulate(parsed.automaton, "cb").accepted


def test_model_regex_kind_compiles_instead_of_drawing_transitions():
    raw = json.dumps(
        {
            "kind": "regex",
            "pattern": "a*bbb*cc*",
            "description": "pedido en lenguaje natural",
            "explanation": "el modelo no debería dibujar las flechas",
        }
    )
    parsed = interpret_text(raw)
    assert parsed.export_ready
    assert parsed.automaton is not None
    assert simulate(parsed.automaton, "bbc").accepted
    assert "dos estados de verificación para b" in parsed.explanation


def test_api_asks_the_model_and_compiles_its_regex(tmp_path):
    set_memory_path(tmp_path / "solutions.json")
    phrase = "un afd que comience por a* siga con bbb* y termine con cc*"
    seen = {}

    async def fake_chat(_settings, messages):
        seen["content"] = messages[-1]["content"]
        return json.dumps(
            {
                "kind": "regex",
                "pattern": "a*bbb*cc*",
                "description": "Cadenas de a*bbb*cc*",
                "explanation": "Leí a*, después bbb* y al final cc*.",
            }
        )

    try:
        with TestClient(app) as client:
            session_id = client.post("/api/sessions").json()["id"]
            with patch("app.service.chat", fake_chat):
                response = client.post(
                    f"/api/sessions/{session_id}/messages",
                    json={"text": phrase},
                )
            assert response.status_code == 200
            body = response.json()
            assert phrase in seen["content"]
            assert "Memoria compartida" not in seen["content"]
            assert body["export_ready"] is True
            assert body["can_remember"] is True
            accepted = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "abbc"})
            rejected = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "bc"})
            assert accepted.json()["accepted"] is True
            assert rejected.json()["accepted"] is False
    finally:
        set_memory_path(None)


def test_hand_built_fa_for_a_regex_is_repaired_into_the_pattern(tmp_path):
    set_memory_path(tmp_path / "solutions.json")
    phrase = "quiero un afd que comience por (ab|ba)* siga por aaa* y luego termine con (c|bb)*"
    calls = {"n": 0}

    async def fake_chat(_settings, messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps(
                {
                    "kind": "fa",
                    "pattern": "",
                    "description": "autómata dibujado a mano",
                    "explanation": "armé las flechas yo",
                    "deterministic": True,
                    "alphabet": ["a", "b", "c"],
                    "states": [
                        {"id": "q0", "initial": True, "final": False},
                        {"id": "q1", "initial": False, "final": True},
                    ],
                    "transitions": [
                        {"from": "q0", "to": "q1", "read": "a"},
                        {"from": "q0", "to": "q0", "read": "b"},
                        {"from": "q0", "to": "q0", "read": "c"},
                        {"from": "q1", "to": "q1", "read": "a"},
                        {"from": "q1", "to": "q1", "read": "b"},
                        {"from": "q1", "to": "q1", "read": "c"},
                    ],
                }
            )
        assert "pattern" in messages[-1]["content"]
        return json.dumps(
            {
                "kind": "regex",
                "pattern": "(ab|ba)*aaa*(c|bb)*",
                "description": "Cadenas de (ab|ba)*aaa*(c|bb)*",
                "explanation": "copié los bloques",
            }
        )

    try:
        with TestClient(app) as client:
            session_id = client.post("/api/sessions").json()["id"]
            with patch("app.service.chat", fake_chat):
                response = client.post(
                    f"/api/sessions/{session_id}/messages",
                    json={"text": phrase},
                )
            body = response.json()
            assert calls["n"] == 2
            assert body["export_ready"] is True
            assert "(ab|ba)*aaa*(c|bb)*" in body["messages"][-1]["content"]
            for word, accepted in (("aa", True), ("abaa", True), ("aabb", True), ("a", False), ("abc", False)):
                result = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
                assert result.json()["accepted"] is accepted
    finally:
        set_memory_path(None)


def test_parenthesized_union_language():
    pattern = "(ab|ba)*aaa*(c|bb)*"
    automaton, explanation = compile_pattern(pattern)
    assert "\nb usa" not in explanation
    assert "aaa* usa dos estados de verificación para a" in explanation
    assert "bb usa dos estados de verificación para b" in explanation
    for word in ("aa", "aaa", "abaa", "baaa", "abbaaa", "aabb", "aac", "aacbb"):
        result = simulate(automaton, word)
        assert result.accepted, word
    for word in ("a", "aba", "aab", "bb", "abc", "c", ""):
        result = simulate(automaton, word)
        assert not result.accepted, word


def test_regex_phrase_is_not_built_without_the_model():
    async def unavailable(_settings, _messages):
        raise OllamaError("No pude conectar con Ollama.")

    phrase = "un afd que comience por a* siga con bbb* y termine con cc*"
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", unavailable):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": phrase},
            )
        body = response.json()
        assert body["export_ready"] is False
        assert body["automaton"] is None
        assert "Ollama" in body["messages"][-1]["content"]


def test_extract_does_not_swallow_spanish_sentences():
    assert extract_regex("¿un AFD que acepte cadenas binarias con cantidad par de unos?") is None
    assert extract_regex("un AFD que termine en 01?") is None
    assert extract_regex("comience por a*") is None
    assert extract_regex("un afd que comience por a*") is None
    assert extract_regex("hola?") is None
    assert extract_regex("a?") == "a?"
    assert extract_regex("(a|b)* abb") == "(a|b)*abb"
    assert extract_regex("a* | b*") == "a*|b*"


def test_spanish_question_is_not_treated_as_a_regex():
    assert not _looks_like_regex_request("¿Cadenas binarias con cantidad par de unos?")
    assert not _looks_like_regex_request("un AFD que termine en 01?")
    assert _looks_like_regex_request("quiero un afd que acepte a?")
    assert _looks_like_regex_request("comience por (ab|ba)*")


def test_short_optional_literal_is_an_expression():
    # bb? y 01? tienen el ? pegado a más de un carácter. Igual son expresión.
    assert _looks_like_regex_request("bb?")
    assert _looks_like_regex_request("01?")
    assert _looks_like_regex_request("quiero un afd para bb?")
    assert extract_regex("bb?") == "bb?"
    assert extract_regex("01?") == "01?"
    assert extract_regex("quiero un afd para bb?") == "bb?"
    assert not _looks_like_regex_request("¿Cadenas binarias con cantidad par de unos?")
    assert not _looks_like_regex_request("un AFD que termine en 01?")
    assert not _looks_like_regex_request("no?")
    assert not _looks_like_regex_request("hola?")
    assert not _looks_like_regex_request("¿Sí?")
    assert not _looks_like_regex_request("¿un AFD?")
    assert not _looks_like_regex_request("¿Me armás el autómata del apunte?")


def _drawn_automaton(alphabet: list[str]) -> str:
    return json.dumps(
        {
            "kind": "fa",
            "pattern": "",
            "description": "autómata dibujado a mano",
            "explanation": "armé las flechas yo",
            "deterministic": True,
            "alphabet": alphabet,
            "states": [{"id": "q0", "initial": True, "final": True}],
            "transitions": [{"from": "q0", "to": "q0", "read": symbol} for symbol in alphabet],
        }
    )


@pytest.mark.parametrize(
    ("phrase", "pattern", "alphabet", "samples"),
    [
        ("bb?", "bb?", ["b"], (("", False), ("b", True), ("bb", True), ("bbb", False))),
        (
            "01?",
            "01?",
            ["0", "1"],
            (("", False), ("0", True), ("01", True), ("1", False), ("00", False)),
        ),
        (
            "quiero un afd para bb?",
            "bb?",
            ["b"],
            (("", False), ("b", True), ("bb", True), ("bbb", False)),
        ),
    ],
)
def test_optional_literal_gets_a_second_attempt_when_the_model_draws_arrows(
    phrase, pattern, alphabet, samples
):
    seen: list[str] = []

    async def fake_chat(_settings, messages):
        seen.append(messages[-1]["content"])
        if len(seen) == 1:
            return _drawn_automaton(alphabet)
        return json.dumps(
            {
                "kind": "regex",
                "pattern": pattern,
                "description": f"Expresión {pattern}",
                "explanation": "copié la expresión",
            }
        )

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            response = client.post(f"/api/sessions/{session_id}/messages", json={"text": phrase})
        body = response.json()
        assert response.status_code == 200
        assert len(seen) == 2
        assert "ya trae la expresión" in seen[1]
        assert body["export_ready"] is True
        assert pattern in body["messages"][-1]["content"]
        for word, accepted in samples:
            result = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
            assert result.json()["accepted"] is accepted, word


@pytest.mark.parametrize(
    ("phrase", "samples"),
    [
        (
            "¿Cadenas binarias con cantidad par de unos?",
            (("", True), ("11", True), ("1", False)),
        ),
        (
            "un AFD que termine en 01?",
            (("01", True), ("101", True), ("", False), ("1", False), ("10", False)),
        ),
    ],
)
def test_question_phrases_stay_families_and_do_not_call_the_model(phrase, samples):
    async def fake_chat(_settings, _messages):
        raise AssertionError("el ? de la pregunta no tiene que llamar al modelo")

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            response = client.post(f"/api/sessions/{session_id}/messages", json={"text": phrase})
        body = response.json()
        assert response.status_code == 200
        assert body["export_ready"] is True
        for word, accepted in samples:
            result = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
            assert result.json()["accepted"] is accepted, word


@pytest.mark.parametrize(
    "phrase",
    [
        "¿Cadenas binarias con cantidad par de unos?",
        "un AFD que termine en 01?",
    ],
)
def test_question_mark_keeps_a_valid_dfa_on_the_first_model_call(phrase, monkeypatch):
    # Estas dos se arman en código. Acá se apaga la familia para ver el modelo:
    # el ? de la pregunta no pide un segundo intento.
    monkeypatch.setattr("app.service.recognize_family", lambda _text: None)
    calls = {"n": 0}
    raw = json.loads(EXAMPLES["paridad"].automaton.model_dump_json(by_alias=True))
    raw["explanation"] = "Este autómata salió del modelo."

    async def fake_chat(_settings, _messages):
        calls["n"] += 1
        return json.dumps(raw)

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            response = client.post(f"/api/sessions/{session_id}/messages", json={"text": phrase})
        body = response.json()
        assert response.status_code == 200
        assert calls["n"] == 1
        assert body["export_ready"] is True
        assert "Este autómata salió del modelo." in body["messages"][-1]["content"]
        assert "No pude armar" not in body["messages"][-1]["content"]
        accepted = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "11"})
        rejected = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "1"})
        assert accepted.json()["accepted"] is True
        assert rejected.json()["accepted"] is False


def test_spanish_question_keeps_a_valid_automaton(tmp_path):
    set_memory_path(tmp_path / "solutions.json")
    calls = {"n": 0}
    raw = EXAMPLES["paridad"].automaton.model_dump_json(by_alias=True)

    async def fake_chat(_settings, _messages):
        calls["n"] += 1
        return raw

    phrase = "¿Me armás el autómata del apunte?"
    try:
        with TestClient(app) as client:
            session_id = client.post("/api/sessions").json()["id"]
            with patch("app.service.chat", fake_chat):
                response = client.post(
                    f"/api/sessions/{session_id}/messages",
                    json={"text": phrase},
                )
            body = response.json()
            assert response.status_code == 200
            assert calls["n"] == 1
            assert body["export_ready"] is True
            assert "No pude armar" not in body["messages"][-1]["content"]
            accepted = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "11"})
            rejected = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "1"})
            assert accepted.json()["accepted"] is True
            assert rejected.json()["accepted"] is False
    finally:
        set_memory_path(None)


@pytest.mark.parametrize(
    ("pattern", "word", "accepted"),
    [
        ("((b?)*)+", "", True),
        ("((b?)*)+", "bb", True),
        ("(c+)(c*)+", "", False),
        ("(c+)(c*)+", "c", True),
        ("(c+)(c*)+", "cccc", True),
        ("((b|a)?)+", "", True),
        ("((b|a)?)+", "ba", True),
        ("(ca|c*)+", "", True),
        ("(ca|c*)+", "ca", True),
        ("(ca|c*)+", "cac", True),
        ("(ca|c*)+", "a", False),
        ("(((c))*)+", "", True),
        ("(((c))*)+", "cc", True),
        ("((a+)?)+", "", True),
        ("((a+)?)+", "aaa", True),
        ("(a*)+", "", True),
        ("(a*)+", "aa", True),
        ("bb+", "", False),
        ("bb+", "b", False),
        ("bb+", "bbb", True),
    ],
)
def test_plus_of_a_nullable_expression_matches_the_language(pattern, word, accepted):
    assert (re.fullmatch(pattern, word) is not None) is accepted
    assert _accepted(pattern, word) is accepted


def test_huge_regex_fails_fast():
    pattern = "(a|b)*a" + "(a|b)" * 14
    started = time.perf_counter()
    with pytest.raises(RegexError, match="demasiados estados"):
        compile_pattern(pattern)
    assert time.perf_counter() - started < 2


def test_a_long_literal_chain_compiles_quickly_and_keeps_the_language():
    # 400 aes: el AFD tiene un estado por cada cantidad y un pozo. Antes, la
    # minimización recorría todos los bloques y tardaba más de 0,3 s.
    pattern = "a" * 400
    started = time.perf_counter()
    automaton, _explanation = compile_pattern(pattern)
    assert time.perf_counter() - started < 0.2
    assert len(automaton.states) == 402
    assert _accepted(pattern, "a" * 400)
    assert not _accepted(pattern, "")
    assert not _accepted(pattern, "a" * 399)
    assert not _accepted(pattern, "a" * 401)

    star, _explanation = compile_pattern("a*")
    assert len(star.states) == 1
    abb, _explanation = compile_pattern("(a|b)*abb")
    assert len(abb.states) == 4
