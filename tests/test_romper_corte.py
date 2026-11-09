"""Ataques de la corrida Romper del 2026-10-19. No usan Ollama.

La secuencia con muchos «uno o más», el ? con una marca, el ordinal °,
un entero enorme, un true en la repetición y un nombre con flecha en la gramática.
"""

import asyncio
import json
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.familias import BlockSpec, _sequence_accepts, recognize_family
from app.interpret import interpret_text
from app.main import app
from app.regex_lang import compile_pattern, extract_regex
from app.service import _looks_like_regex_request, create_session, handle_message, run_word
from app.simulate import simulate

MARK = "\u0301"
ZWS = "\u200b"
RTL = "\u202e"
FW_Q = "？"


def _post(phrase: str, chat):
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": phrase},
            )
        return client, session_id, response


def _accepts(client, session_id, word: str) -> bool:
    answer = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
    assert answer.status_code == 200, word
    return answer.json()["accepted"]


def test_many_plus_blocks_finish_and_keep_the_language():
    blocks = tuple(BlockSpec("a", "plus", 1) for _ in range(18))
    started = time.perf_counter()
    assert _sequence_accepts(blocks, "a" * 40)
    assert not _sequence_accepts(blocks, "a" * 40 + "b")
    assert not _sequence_accepts(blocks, "a" * 10)
    assert time.perf_counter() - started < 0.5

    phrase = "sobre {0, 1} " + ", ".join(["uno o más 0"] * 16)
    started = time.perf_counter()
    result = recognize_family(phrase)
    assert time.perf_counter() - started < 2
    assert result is not None and result.automaton is not None and result.errors == []
    automaton = result.automaton
    assert simulate(automaton, "0" * 16).accepted
    assert simulate(automaton, "0" * 40).accepted
    assert not simulate(automaton, "0" * 15).accepted
    assert not simulate(automaton, "").accepted
    assert not simulate(automaton, "0" * 16 + "1").accepted
    assert not simulate(automaton, "1" + "0" * 16).accepted


def test_degree_ordinal_is_a_position_and_zero_is_rejected():
    async def fake_chat(_settings, _messages):
        raise AssertionError("el ordinal no tiene que llamar al modelo")

    second = "el 2° símbolo es 1 sobre {0, 1}"
    masculine = "el 2º símbolo es 1 sobre {0, 1}"
    feminine = "el 2ª símbolo es 0 sobre {0, 1}"
    spaced = "el 2 ° símbolo desde el final es 1 sobre {0, 1}"
    for phrase, word_yes, word_no in (
        (second, "01", "00"),
        (masculine, "11", "10"),
        (feminine, "10", "11"),
        (spaced, "10", "01"),
    ):
        result = recognize_family(phrase)
        assert result is not None and result.automaton is not None, phrase
        assert result.errors == []
        assert simulate(result.automaton, word_yes).accepted, phrase
        assert not simulate(result.automaton, word_no).accepted, phrase
        assert not simulate(result.automaton, "").accepted, phrase

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            zero = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "el 0° símbolo es 1 sobre {0, 1}"},
            )
            far = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "sobre {0, 1} el 13° símbolo desde el final es 1"},
            )
    assert zero.status_code == 200
    assert zero.json()["export_ready"] is False
    assert "mayor que 0" in zero.json()["messages"][-1]["content"]
    assert far.status_code == 200
    assert far.json()["export_ready"] is False
    assert "tope es 12" in far.json()["messages"][-1]["content"]


def test_question_mark_with_a_mark_stays_a_family():
    async def fake_chat(_settings, _messages):
        raise AssertionError("el ? de la pregunta no tiene que llamar al modelo")

    ends = f"un AFD que termine en 01?{MARK}"
    parity = f"¿Cadenas binarias con cantidad par de unos{MARK}?"
    fullwidth = f"un AFD que termine en 01{FW_Q}"
    assert not _looks_like_regex_request(ends)
    assert not _looks_like_regex_request(parity)
    assert not _looks_like_regex_request(fullwidth)

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            first = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": ends},
            )
        assert first.status_code == 200
        assert first.json()["export_ready"] is True
        assert _accepts(client, session_id, "101")
        assert _accepts(client, session_id, "01")
        assert not _accepts(client, session_id, "0")
        assert not _accepts(client, session_id, "10")

        with patch("app.service.chat", fake_chat):
            second = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": parity},
            )
        assert second.status_code == 200
        assert second.json()["export_ready"] is True
        assert _accepts(client, session_id, "")
        assert _accepts(client, session_id, "11")
        assert not _accepts(client, session_id, "1")

        with patch("app.service.chat", fake_chat):
            third = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": fullwidth},
            )
        assert third.status_code == 200
        assert _accepts(client, session_id, "101")
        assert not _accepts(client, session_id, "10")


def test_fullwidth_optional_and_digits_are_read():
    assert _looks_like_regex_request("quiero un afd para ０１?")
    assert _looks_like_regex_request(f"01{FW_Q}")
    assert _looks_like_regex_request("01 ?")
    assert _looks_like_regex_request(f"bb?{MARK}")
    assert extract_regex("０１?") == "01?"
    assert extract_regex(f"01{FW_Q}") == "01?"
    assert extract_regex(f"bb?{MARK}") == "bb?"
    # La estrella de ancho completo sigue siendo un símbolo, no un cuantificador.
    star = compile_pattern("a＊")[0]
    assert star.alphabet == ["a", "＊"]
    assert simulate(star, "a＊").accepted
    assert not simulate(star, "a").accepted
    assert not simulate(star, "").accepted
    assert not _looks_like_regex_request("a＊")

    seen: list[str] = []

    async def fake_chat(_settings, messages):
        seen.append(messages[-1]["content"])
        if len(seen) == 1:
            return json.dumps(
                {
                    "kind": "fa",
                    "description": "dibujo",
                    "explanation": "flechas",
                    "deterministic": True,
                    "alphabet": ["0", "1"],
                    "states": [{"id": "q0", "initial": True, "final": True}],
                    "transitions": [
                        {"from": "q0", "to": "q0", "read": "0"},
                        {"from": "q0", "to": "q0", "read": "1"},
                    ],
                }
            )
        return json.dumps(
            {
                "kind": "regex",
                "pattern": "01?",
                "description": "Expresión 01?",
                "explanation": "copié la expresión",
            }
        )

    client, session_id, response = _post("quiero un afd para ０１?", fake_chat)
    body = response.json()
    assert response.status_code == 200
    assert len(seen) == 2
    assert body["export_ready"] is True
    assert _accepts(client, session_id, "0")
    assert _accepts(client, session_id, "01")
    assert not _accepts(client, session_id, "")
    assert not _accepts(client, session_id, "1")

    three = recognize_family("sobre {0, 1} ３ ceros")
    assert three is not None and three.automaton is not None
    assert simulate(three.automaton, "000").accepted
    assert not simulate(three.automaton, "00").accepted
    assert not simulate(three.automaton, "0000").accepted
    assert not simulate(three.automaton, "3").accepted


def test_invisible_between_symbols_does_not_change_the_word():
    async def fake_chat(_settings, _messages):
        raise AssertionError("el invisible no tiene que llamar al modelo")

    for phrase in (f"termina con 0{ZWS}1", f"termina con {RTL}01"):
        result = recognize_family(phrase)
        assert result is not None and result.automaton is not None, phrase
        assert simulate(result.automaton, "01").accepted
        assert simulate(result.automaton, "101").accepted
        assert not simulate(result.automaton, "10").accepted
        assert not simulate(result.automaton, "0").accepted

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": f"termina con 0{ZWS}1"},
            )
        assert response.status_code == 200
        assert response.json()["export_ready"] is True
        assert _accepts(client, session_id, "001")
        assert not _accepts(client, session_id, "10")


def test_negative_repeat_and_huge_integer_are_spanish_errors():
    async def fake_chat(_settings, _messages):
        raise AssertionError("no tiene que llamar al modelo")

    negative = recognize_family("sobre {0, 1} -3 ceros")
    assert negative is not None and negative.automaton is None
    assert "negativ" in negative.errors[0]

    huge = recognize_family("números binarios divisibles por " + "9" * 5000)
    assert huge is not None and huge.automaton is None
    assert "demasiado grande" in huge.errors[0]
    assert "9" * 20 not in huge.errors[0]

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "sobre {0, 1} -3 ceros"},
            )
        body = response.json()
        assert response.status_code == 200
        assert body["export_ready"] is False
        assert "negativ" in body["messages"][-1]["content"]
        assert "integer" not in body["messages"][-1]["content"].lower()


def test_model_repeat_bool_and_giant_digit_string_are_not_a_500():
    calls = {"n": 0}

    async def fake_chat(_settings, _messages):
        calls["n"] += 1
        if calls["n"] % 2 == 1:
            repeat: object = True
        else:
            repeat = "9" * 5000
        return json.dumps(
            {
                "kind": "spec",
                "family": "secuencia",
                "alphabet": ["0", "1"],
                "blocks": [{"symbol": "0", "repeat": repeat}],
            }
        )

    phrase = "dibujá el ejemplo del apunte de la práctica 7"
    assert recognize_family(phrase) is None
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": phrase},
            )
        body = response.json()
        assert response.status_code == 200
        assert body["export_ready"] is False
        text = body["messages"][-1]["content"]
        assert "integer string" not in text
        assert "4300" not in text
        # El primer llamado manda true y se rechaza. El reintento manda el entero.
        assert calls["n"] == 2
        assert "repetición" in text or "demasiado" in text or "tope" in text

    raw = json.dumps(
        {
            "kind": "spec",
            "family": "secuencia",
            "alphabet": ["0", "1"],
            "blocks": [{"symbol": "0", "repeat": "9" * 5000}],
        }
    )
    try:
        interpret_text(raw, phrase)
    except Exception as exc:
        message = str(exc)
    else:
        raise AssertionError("el entero enorme tenía que rechazarse")
    assert "integer string" not in message
    assert "demasiado" in message or "tope" in message


def test_surrogate_in_the_statement_does_not_crash():
    # Un sustituto suelto no entra en JSON de HTTP. Igual puede llegar
    # como texto de Python: no tiene que tirar el enunciado.
    phrase = "termina con \ud800"
    assert recognize_family(phrase) is None

    async def fake_chat(_settings, _messages):
        return json.dumps(
            {
                "kind": "fa",
                "description": "paridad",
                "explanation": "sirve",
                "deterministic": True,
                "alphabet": ["0", "1"],
                "states": [
                    {"id": "q0", "initial": True, "final": True},
                    {"id": "q1", "initial": False, "final": False},
                ],
                "transitions": [
                    {"from": "q0", "to": "q0", "read": "0"},
                    {"from": "q0", "to": "q1", "read": "1"},
                    {"from": "q1", "to": "q0", "read": "1"},
                    {"from": "q1", "to": "q1", "read": "0"},
                ],
            }
        )

    session = create_session()
    with patch("app.service.chat", fake_chat):
        body = asyncio.run(handle_message(session.id, phrase))
    assert body["export_ready"] is True
    assert run_word(session.id, "11")["accepted"] is True
    assert run_word(session.id, "1")["accepted"] is False
