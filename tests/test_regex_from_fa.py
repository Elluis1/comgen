import time
import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.main import app
from app.regex_from_fa import MAX_STATES, RegexFromFaError, fa_to_regex
from app.regex_lang import compile_pattern
from app.schemas import FiniteAutomaton, State, Transition
from app.simulate import simulate
from app.store import store


# Conjunto escrito: la vacía y cadenas de largo 4 y 5, además de otras cortas.
PARITY_ACCEPT = ["", "0", "00", "11", "0000", "0011", "1010", "1111", "01010", "11110"]
PARITY_REJECT = ["1", "10", "01", "111", "0001", "1110", "0111", "00001", "10101", "11111"]
ENDS_ACCEPT = ["01", "001", "101", "0001", "1101", "0101", "1001", "00101", "11101", "00001"]
ENDS_REJECT = ["", "0", "1", "10", "11", "00", "010", "0000", "1111", "0110", "01011", "11110"]


def _words(alphabet: list[str], limit: int) -> list[str]:
    words = [""]
    layer = [""]
    for _ in range(limit):
        layer = [word + symbol for word in layer for symbol in alphabet]
        words.extend(layer)
    return words


def _expect(automaton: FiniteAutomaton, accept: list[str], reject: list[str]) -> None:
    for word in accept:
        result = simulate(automaton, word)
        assert result.ok and result.accepted is True, word
    for word in reject:
        result = simulate(automaton, word)
        assert result.ok and result.accepted is False, word


def _agree(original: FiniteAutomaton, pattern: str, words: list[str]) -> None:
    compiled, _explanation = compile_pattern(pattern)
    for word in words:
        left = simulate(original, word)
        right = simulate(compiled, word)
        assert left.ok and right.ok, (pattern, word, left.message, right.message)
        assert left.accepted is right.accepted, (pattern, word, left.accepted, right.accepted)


def test_examples_compile_to_the_same_language():
    cases = {
        "paridad": PARITY_ACCEPT + PARITY_REJECT,
        "termina-en-01": ENDS_ACCEPT + ENDS_REJECT,
    }
    for example_id, written in cases.items():
        automaton = EXAMPLES[example_id].automaton
        if example_id == "paridad":
            _expect(automaton, PARITY_ACCEPT, PARITY_REJECT)
        else:
            _expect(automaton, ENDS_ACCEPT, ENDS_REJECT)
        before = automaton.model_dump()
        started = time.perf_counter()
        pattern = fa_to_regex(automaton)
        assert time.perf_counter() - started < 1
        assert automaton.model_dump() == before
        assert pattern
        _agree(automaton, pattern, written)
        _agree(automaton, pattern, _words(list(automaton.alphabet), 5))


def test_small_automata_have_the_obvious_expression():
    symbol = FiniteAutomaton(
        deterministic=True,
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[Transition(from_state="q0", to="q1", read="a")],
    )
    assert fa_to_regex(symbol) == "a"

    star = FiniteAutomaton(
        deterministic=True,
        alphabet=["0", "1"],
        states=[State(id="q0", initial=True, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="0")],
    )
    assert fa_to_regex(star) == "0*"

    union = FiniteAutomaton(
        deterministic=True,
        alphabet=["a", "b"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="a"),
            Transition(from_state="q0", to="q1", read="b"),
        ],
    )
    assert fa_to_regex(union) == "a|b"

    optional = FiniteAutomaton(
        deterministic=True,
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=True),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[Transition(from_state="q0", to="q1", read="a")],
    )
    assert fa_to_regex(optional) == "a?"


def test_a_copy_is_minimized_and_the_original_stays():
    automaton = FiniteAutomaton(
        deterministic=True,
        alphabet=["a", "b"],
        states=[
            State(id="q0", initial=True, final=True),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q0", read="a"),
            Transition(from_state="q0", to="q0", read="b"),
            Transition(from_state="q1", to="q1", read="a"),
            Transition(from_state="q1", to="q1", read="b"),
        ],
    )
    before = automaton.model_dump()
    pattern = fa_to_regex(automaton)
    assert automaton.model_dump() == before
    assert len(automaton.states) == 2
    _agree(automaton, pattern, _words(["a", "b"], 4))


def test_an_nfa_asks_to_determinize_first():
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(EXAMPLES["a-estrella"].automaton)
    assert "determinizar" in str(exc.value)

    two = FiniteAutomaton(
        deterministic=False,
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q0", read="a"),
            Transition(from_state="q0", to="q1", read="a"),
        ],
    )
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(two)
    assert "determinizar" in str(exc.value)


def test_empty_language_and_only_epsilon_are_spanish_errors():
    none = FiniteAutomaton(
        deterministic=True,
        alphabet=["a"],
        states=[State(id="q0", initial=True, final=False)],
        transitions=[Transition(from_state="q0", to="q0", read="a")],
    )
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(none)
    assert "finales" in str(exc.value)

    only_empty = FiniteAutomaton(
        deterministic=True,
        alphabet=["a"],
        states=[State(id="q0", initial=True, final=True)],
        transitions=[],
    )
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(only_empty)
    assert "vacía" in str(exc.value)

    unreachable = FiniteAutomaton(
        deterministic=True,
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[Transition(from_state="q0", to="q0", read="a")],
    )
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(unreachable)
    assert "ninguna" in str(exc.value)


def test_an_operator_symbol_is_rejected():
    automaton = FiniteAutomaton(
        deterministic=True,
        alphabet=["*"],
        states=[State(id="q0", initial=True, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="*")],
    )
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(automaton)
    assert "escapes" in str(exc.value)


def test_over_the_state_cap_refuses_quickly():
    assert MAX_STATES == 16
    states = [State(id=f"q{index}", initial=index == 0, final=index == 30) for index in range(31)]
    transitions = [
        Transition(from_state=f"q{index}", to=f"q{index + 1}", read="a") for index in range(30)
    ]
    automaton = FiniteAutomaton(
        deterministic=True,
        alphabet=["a"],
        states=states,
        transitions=transitions,
    )
    started = time.perf_counter()
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(automaton)
    assert time.perf_counter() - started < 0.5
    assert "estados" in str(exc.value)
    assert "trabar" in str(exc.value)


def test_a_huge_expression_stops(monkeypatch):
    monkeypatch.setattr("app.regex_from_fa.MAX_EXPRESSION", 4)
    started = time.perf_counter()
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(EXAMPLES["termina-en-01"].automaton)
    assert time.perf_counter() - started < 1
    assert "trabar" in str(exc.value)


def test_the_screen_returns_the_expression_without_ollama():
    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("Sacar la expresión no tiene que llamar a Ollama.")

    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
        assert page.status_code == 200
        assert 'id="regex"' in page.text
        assert "Expresión" in page.text
        assert 'id="fresh"' in page.text
        assert 'id="download"' in page.text
        assert 'id="remember"' in page.text
        assert 'id="determinize"' in page.text
        assert "Nuevo autómata" in page.text
        assert "/regex" in script.text
        assert "Armando la expresión" in script.text
        assert "regex-line" in script.text

        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            missing = client.post(f"/api/sessions/{session_id}/regex")
            assert missing.status_code == 409
            assert "expresión" in missing.json()["detail"]

            loaded = client.post(f"/api/sessions/{session_id}/examples/paridad")
            assert loaded.status_code == 200
            before = loaded.json()["automaton"]

            converted = client.post(f"/api/sessions/{session_id}/regex")
            assert converted.status_code == 200
            body = converted.json()
            assert body["pattern"]
            assert body["pattern"] in body["messages"][-1]["content"]
            assert "expresión regular" in body["messages"][-1]["content"]
            assert body["automaton"]["states"] == before["states"]
            assert body["automaton"]["transitions"] == before["transitions"]
            _agree(EXAMPLES["paridad"].automaton, body["pattern"], PARITY_ACCEPT + PARITY_REJECT)

            ends = client.post(f"/api/sessions/{session_id}/examples/termina-en-01")
            assert ends.status_code == 200
            expressed = client.post(f"/api/sessions/{session_id}/regex")
            assert expressed.status_code == 200
            _agree(
                EXAMPLES["termina-en-01"].automaton,
                expressed.json()["pattern"],
                ENDS_ACCEPT + ENDS_REJECT,
            )

            nfa = client.post(f"/api/sessions/{session_id}/examples/a-estrella")
            assert nfa.json()["automaton"]["deterministic"] is False
            nfa_states = nfa.json()["automaton"]["states"]
            refused = client.post(f"/api/sessions/{session_id}/regex")
            assert refused.status_code == 409
            assert "determinizar" in refused.json()["detail"]
            kept = store.get(session_id).automaton
            assert kept is not None
            assert kept.deterministic is False
            assert [state.id for state in kept.states] == [state["id"] for state in nfa_states]

            determined = client.post(f"/api/sessions/{session_id}/determinize")
            assert determined.status_code == 200
            states_before = determined.json()["automaton"]["states"]
            expressed_nfa = client.post(f"/api/sessions/{session_id}/regex")
            assert expressed_nfa.status_code == 200
            pattern = expressed_nfa.json()["pattern"]
            assert expressed_nfa.json()["automaton"]["states"] == states_before
            assert "pozo" not in {state["id"] for state in expressed_nfa.json()["automaton"]["states"]}
            compiled, _explanation = compile_pattern(pattern)
            for word in ("", "a", "aa"):
                assert simulate(compiled, word).accepted is True
            assert simulate(compiled, "b").accepted is False

            exported = client.get(f"/api/sessions/{session_id}/export")
            assert exported.status_code == 200
            root = ET.fromstring(exported.text.encode("utf-8"))
            assert "pozo" in {state.get("name") for state in root.findall("./automaton/state")}

            unknown = client.post("/api/sessions/no-existe/regex")
            assert unknown.status_code == 404
