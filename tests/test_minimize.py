"""Límites y velocidad de la minimización, la simulación y el JSON del modelo."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.familias import (
    MAX_CONTROL_WORDS,
    _control_words,
    _fill_bases,
    _parse_request,
    _resolve_alphabet,
    recognize_family,
)
from app.interpret import MAX_REPLY_STATES, MAX_REPLY_TRANSITIONS, ModelReplyError, interpret_text
from app.main import app
from app.minimize import MAX_MINIMIZE_STATES, MinimizeError, minimize_dfa
from app.regex_lang import RegexError, compile_pattern
from app.schemas import FiniteAutomaton, State, Transition
from app.service import MAX_MODEL_HISTORY, MAX_REPAIR_ECHO, _model_messages
from app.simulate import MAX_SIMULATION_STATES, MAX_WORD_LENGTH, Simulator, simulate
from app.validate import validate_fa
from app.store import store


def _counter(n: int) -> FiniteAutomaton:
    """Cada estado es distinguible: hace falta una a más para llegar al final."""
    states = [State(id=f"q{i}", initial=i == 0, final=i == n - 1) for i in range(n)]
    transitions = []
    for index in range(n):
        transitions.append(Transition(from_state=f"q{index}", to=f"q{min(index + 1, n - 1)}", read="a"))
        transitions.append(Transition(from_state=f"q{index}", to="q0", read="b"))
    return FiniteAutomaton(
        deterministic=True,
        alphabet=["a", "b"],
        states=states,
        transitions=transitions,
        description="contador",
    )


def test_minimize_of_a_large_dfa_stays_fast_and_keeps_the_language():
    small = minimize_dfa(_counter(30))
    assert len(small.states) == 30
    assert simulate(small, "a" * 29).accepted is True
    assert simulate(small, "a" * 28).accepted is False
    assert simulate(small, "b").accepted is False

    automaton = _counter(1500)
    started = time.perf_counter()
    minimized = minimize_dfa(automaton)
    assert time.perf_counter() - started < 2
    assert len(minimized.states) == 1500
    assert simulate(minimized, "a" * 10).accepted is False
    assert minimize_dfa(minimized) is minimized


def test_minimize_merges_copies_that_behave_the_same():
    states = [State(id=f"s{i}", initial=i == 0, final=i == 0) for i in range(40)]
    transitions = []
    for index in range(40):
        transitions.append(Transition(from_state=f"s{index}", to="s0", read="a"))
        transitions.append(Transition(from_state=f"s{index}", to="s1", read="b"))
    automaton = FiniteAutomaton(
        deterministic=True,
        alphabet=["a", "b"],
        states=states,
        transitions=transitions,
        description="copias",
    )
    minimized = minimize_dfa(automaton)
    assert len(minimized.states) == 2
    assert simulate(minimized, "").accepted is True
    assert simulate(minimized, "a").accepted is True
    assert simulate(minimized, "b").accepted is False
    assert simulate(minimized, "ba").accepted is True


def test_minimize_limit_covers_the_family_product_and_fails_in_spanish(monkeypatch):
    # El producto de las familias llega a 4096 estados. El tope tiene que dejarlo pasar.
    assert MAX_MINIMIZE_STATES >= 4096
    monkeypatch.setattr("app.minimize.MAX_MINIMIZE_STATES", 4)
    started = time.perf_counter()
    with pytest.raises(MinimizeError, match="se corta en 4"):
        minimize_dfa(_counter(5))
    assert time.perf_counter() - started < 1


def test_family_intersection_near_the_product_cap_finishes_quickly():
    phrase = "longitud múltiplo de 48 y longitud múltiplo de 47 sobre {0, 1}"
    started = time.perf_counter()
    result = recognize_family(phrase)
    assert time.perf_counter() - started < 3
    assert result is not None
    assert result.errors == []
    assert len(result.automaton.states) == 2256
    # 48 y 47 son coprimos: el mínimo tiene 2256 estados. La vacía es múltiplo; 48 no lo es de 47.
    assert simulate(result.automaton, "").accepted is True
    assert simulate(result.automaton, "0" * 48).accepted is False


def test_family_reports_the_minimize_limit_in_spanish(monkeypatch):
    monkeypatch.setattr("app.minimize.MAX_MINIMIZE_STATES", 10)
    result = recognize_family("longitud múltiplo de 30 sobre {a, b}")
    assert result is not None
    assert result.automaton is None
    assert result.errors
    assert "10" in result.errors[0]
    assert "minimización" in result.errors[0]


def test_validate_of_a_large_dfa_stays_fast_and_names_an_unreachable_state():
    automaton = _counter(4000)
    started = time.perf_counter()
    check = validate_fa(automaton)
    assert time.perf_counter() - started < 0.2
    assert check.errors == []
    assert check.warnings == []

    automaton.states.append(State(id="lejos", initial=False, final=False))
    started = time.perf_counter()
    check = validate_fa(automaton)
    assert time.perf_counter() - started < 0.2
    assert check.errors == []
    assert "Hay estados inalcanzables: lejos." in check.warnings


def test_subset_construction_names_its_cap():
    pattern = "(a|b)*a" + "(a|b)" * 14
    with pytest.raises(RegexError, match="demasiados estados") as caught:
        compile_pattern(pattern)
    assert "512" in str(caught.value)


def test_simulation_rejects_a_long_word_and_a_huge_automaton():
    parity = EXAMPLES["paridad"].automaton
    long = simulate(parity, "1" * (MAX_WORD_LENGTH + 1))
    assert long.ok is False
    assert str(MAX_WORD_LENGTH) in long.message
    assert "más corta" in long.message

    huge = FiniteAutomaton(
        deterministic=True,
        alphabet=["a"],
        states=[State(id=f"q{i}", initial=i == 0, final=True) for i in range(MAX_SIMULATION_STATES + 1)],
        transitions=[],
        description="enorme",
    )
    blocked = simulate(huge, "a")
    assert blocked.ok is False
    assert str(MAX_SIMULATION_STATES) in blocked.message
    assert "simulación" in blocked.message


def test_decimal_divisibility_stays_fast_and_keeps_the_language():
    # El control prueba unas 1500 palabras. Antes, cada una rearmaba el índice.
    started = time.perf_counter()
    result = recognize_family("un AFD que acepte los números en base 10 divisibles por 32")
    assert time.perf_counter() - started < 0.05
    assert result is not None
    assert result.errors == []
    automaton = result.automaton
    assert automaton is not None
    assert simulate(automaton, "").accepted is True
    assert simulate(automaton, "0").accepted is True
    assert simulate(automaton, "32").accepted is True
    assert simulate(automaton, "64").accepted is True
    assert simulate(automaton, "31").accepted is False
    assert simulate(automaton, "33").accepted is False


def test_base36_control_stops_before_formatting_every_integer():
    # 13825 enteros, y cada uno rearmaba los 36 dígitos: 32 ms y 2,4 MiB.
    # Con el alfabeto ya armado, formatearlos igual eran unos 5 ms.
    phrase = "números en base 36 divisibles por 128"
    request = _parse_request(phrase)
    assert request is not None
    warnings: list[str] = []
    spec = _fill_bases(request.spec, request.explicit, request.text, warnings)
    alphabet = _resolve_alphabet(spec, request.explicit, request.text, warnings)
    started = time.perf_counter()
    sample = _control_words(spec, alphabet)
    assert time.perf_counter() - started < 0.01
    assert len(sample) == MAX_CONTROL_WORDS == 1500
    assert sample[0] == ""
    assert "3k" in sample
    assert sample[-4:] == ["002r", "02s", "002s", "02t"]

    result = recognize_family(phrase)
    assert result is not None
    assert result.errors == []
    automaton = result.automaton
    assert automaton is not None
    assert len(automaton.states) == 18
    # 128 es 3k, 256 es 74, 127 es 3j y 129 es 3l, en base 36.
    assert simulate(automaton, "").accepted is True
    assert simulate(automaton, "0").accepted is True
    assert simulate(automaton, "3k").accepted is True
    assert simulate(automaton, "74").accepted is True
    assert simulate(automaton, "1").accepted is False
    assert simulate(automaton, "3j").accepted is False
    assert simulate(automaton, "3l").accepted is False


def test_family_product_of_64_and_63_stays_under_the_old_simulation_cost():
    phrase = "longitud múltiplo de 64 y longitud múltiplo de 63 sobre {0, 1}"
    started = time.perf_counter()
    result = recognize_family(phrase)
    # En Windows este caso midió 0,56 s. 2 s deja ese margen y sigue
    # cortando el recorrido cuadrático, que acá tardaba minutos.
    assert time.perf_counter() - started < 2
    assert result is not None
    assert result.errors == []
    automaton = result.automaton
    assert automaton is not None
    assert len(automaton.states) == 4032
    # 64 y 63 son coprimos: el mínimo tiene 4032 estados. Dentro del tope de
    # simulación, solo la vacía es múltiplo de los dos.
    assert simulate(automaton, "").accepted is True
    assert simulate(automaton, "0" * 48).accepted is False
    assert simulate(automaton, "0" * 63).accepted is False
    assert simulate(automaton, "0" * 64).accepted is False
    assert simulate(automaton, "0" * 126).accepted is False


def test_many_words_on_a_large_dfa_reuse_one_index():
    # 501 estados: la palabra que acepta entra justo en el tope de 500 símbolos.
    automaton = _counter(501)
    runner = Simulator(automaton)
    started = time.perf_counter()
    for length in range(400):
        result = runner.run("b" + "a" * (length % 5), trace=False)
        assert result.ok is True
        assert result.accepted is False
        assert result.steps == []
    assert time.perf_counter() - started < 0.05
    assert runner.run("a" * 500).accepted is True
    assert runner.run("a" * 499).accepted is False
    assert runner.run("a" * 400 + "b").accepted is False
    assert runner.run("b" * 3).accepted is False


def test_runner_agrees_with_simulate_on_epsilon_and_a_decomposed_name():
    epsilon = FiniteAutomaton(
        deterministic=False,
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="epsilon"),
            Transition(from_state="q1", to="q1", read="a"),
        ],
    )
    marked = FiniteAutomaton(
        deterministic=True,
        alphabet=["é"],
        states=[State(id="e\u0301", initial=True, final=True)],
        transitions=[Transition(from_state="é", to="e\u0301", read="e\u0301")],
    )
    cases = (
        (epsilon, ["", "a", "aa", "b"]),
        (marked, ["", "é", "e\u0301", "éé", "e"]),
    )
    for automaton, words in cases:
        runner = Simulator(automaton)
        for word in words:
            left = simulate(automaton, word)
            right = runner.run(word)
            assert left.ok is right.ok
            assert left.accepted is right.accepted
            assert left.message == right.message
            assert [(step.symbol, step.states) for step in left.steps] == [
                (step.symbol, step.states) for step in right.steps
            ]
    assert simulate(epsilon, "").accepted is True
    assert simulate(epsilon, "aa").accepted is True
    assert simulate(marked, "e\u0301").accepted is True
    assert "no está en el alfabeto" in simulate(marked, "e").message


def test_a_foreign_symbol_is_reported_before_two_initial_states():
    two = FiniteAutomaton(
        deterministic=False,
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=True, final=True),
        ],
        transitions=[],
    )
    foreign = simulate(two, "b")
    assert foreign.ok is False
    assert "no está en el alfabeto" in foreign.message
    initial = simulate(two, "a")
    assert initial.ok is False
    assert "inicial" in initial.message
    # La palabra larga se corta antes de mirar el símbolo.
    long = simulate(two, "b" * (MAX_WORD_LENGTH + 1))
    assert str(MAX_WORD_LENGTH) in long.message
    assert "más corta" in long.message


def test_api_rejects_a_long_word_in_spanish():
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        loaded = client.post(f"/api/sessions/{session_id}/examples/paridad")
        assert loaded.status_code == 200
        response = client.post(
            f"/api/sessions/{session_id}/simulate",
            json={"word": "1" * (MAX_WORD_LENGTH + 1)},
        )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert str(MAX_WORD_LENGTH) in detail
    assert "más corta" in detail


def _fa_payload(states: int, copies: int = 1) -> dict:
    body = {
        "kind": "fa",
        "description": "cadena",
        "explanation": "cuenta aes",
        "deterministic": True,
        "alphabet": ["a", "b"],
        "states": [
            {"id": f"q{index}", "initial": index == 0, "final": index == states - 1}
            for index in range(states)
        ],
        "transitions": [],
    }
    transitions = []
    for index in range(states):
        transitions.append({"from": f"q{index}", "to": f"q{min(index + 1, states - 1)}", "read": "a"})
        transitions.append({"from": f"q{index}", "to": "q0", "read": "b"})
    body["transitions"] = transitions * copies
    return body


def test_model_reply_over_the_state_cap_is_rejected_before_building():
    ok = interpret_text(json.dumps(_fa_payload(2)))
    assert ok.automaton is not None
    assert len(ok.automaton.states) == 2

    with pytest.raises(ModelReplyError, match="demasiado grande") as caught:
        interpret_text(json.dumps(_fa_payload(MAX_REPLY_STATES + 1)))
    assert str(MAX_REPLY_STATES) in caught.value.errors[0]
    assert "transiciones" in caught.value.errors[0]

    with pytest.raises(ModelReplyError, match="demasiado grande") as caught:
        interpret_text(json.dumps(_fa_payload(2, copies=MAX_REPLY_TRANSITIONS)))
    assert str(MAX_REPLY_TRANSITIONS) in caught.value.errors[0]


def test_model_context_keeps_the_last_turns_and_a_compact_automaton():
    session = store.create()
    session.automaton = EXAMPLES["paridad"].automaton
    for index in range(10):
        session.model_messages.append({"role": "user", "content": f"pedido {index}"})
        session.model_messages.append({"role": "assistant", "content": "{}"})
    messages = _model_messages(session, "nuevo")
    assert messages[0]["role"] == "system"
    history = messages[1:-1]
    assert len(history) == MAX_MODEL_HISTORY
    assert history[0]["content"] == "pedido 6"
    body = messages[-1]["content"]
    assert "Autómata actual, en JSON:" in body
    compact = body.split("Autómata actual, en JSON:\n", 1)[1]
    assert "\n" not in compact
    indented = EXAMPLES["paridad"].automaton.model_dump_json(by_alias=True, indent=2)
    assert len(compact) < len(indented)


def test_repair_does_not_echo_a_huge_json_into_the_small_context():
    huge = json.dumps(_fa_payload(MAX_REPLY_STATES + 1))
    assert len(huge) > MAX_REPAIR_ECHO
    parity = EXAMPLES["paridad"].automaton.model_dump(by_alias=True)
    parity.update(
        {
            "kind": "fa",
            "description": "Cadenas binarias con cantidad par de unos",
            "explanation": "q0 es par.",
        }
    )
    seen: list[list[dict]] = []

    async def fake_chat(_settings, messages):
        seen.append(messages)
        if len(seen) == 1:
            return huge
        return json.dumps(parity)

    phrase = "el autómata de la figura del apunte"
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        from unittest.mock import patch

        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": phrase},
            )
    body = response.json()
    assert response.status_code == 200
    assert body["export_ready"] is True
    assert len(seen) == 2
    echoed = seen[1][-2]["content"]
    assert len(echoed) < len(huge)
    assert len(echoed) <= MAX_REPAIR_ECHO + 80
    assert "cortada" in echoed
    assert "modelo chico" in echoed
