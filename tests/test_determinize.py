import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.determinize import MAX_SUBSETS, DeterminizeError, nfa_to_dfa
from app.examples import EXAMPLES
from app.main import app
from app.schemas import FiniteAutomaton, State, Transition
from app.simulate import simulate
from app.store import store
from app.validate import prepare_fa, validate_fa


def test_subset_cap_is_the_same_small_limit():
    assert MAX_SUBSETS == 512


def test_epsilon_chain_for_a_star_becomes_a_dfa():
    nfa = EXAMPLES["a-estrella"].automaton
    before = nfa.model_dump()
    result = nfa_to_dfa(nfa)
    dfa = result.automaton

    assert nfa.model_dump() == before
    assert result.already is False
    assert dfa.deterministic is True
    assert [state.id for state in dfa.states if state.initial] == ["{q0,q1,q2}"]
    assert {state.id for state in dfa.states} == {"{q0,q1,q2}", "{q2}"}
    assert all(transition.read for transition in dfa.transitions)
    assert validate_fa(dfa).errors == []

    prepared, _notes = prepare_fa(nfa)
    for word in ("", "a", "aa", "aaa"):
        assert simulate(dfa, word).accepted is True, word
        assert simulate(prepared, word).accepted is True, word
    for word in ("b", "ab", "ba", "bb"):
        assert simulate(dfa, word).ok is True
        assert simulate(dfa, word).accepted is False, word
        assert simulate(prepared, word).accepted is False, word
    _same_language(prepared, dfa, length=4)


def test_epsilon_after_the_symbol_stays_in_the_closure():
    nfa = FiniteAutomaton(
        deterministic=False,
        alphabet=["a", "b"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=False),
            State(id="q2", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="a"),
            Transition(from_state="q1", to="q2", read="ε"),
        ],
    )
    dfa = nfa_to_dfa(nfa).automaton
    assert validate_fa(dfa).errors == []
    assert simulate(dfa, "").accepted is False
    assert simulate(dfa, "a").accepted is True
    assert simulate(dfa, "aa").accepted is False
    assert simulate(dfa, "b").accepted is False
    prepared, _notes = prepare_fa(nfa)
    _same_language(prepared, dfa, length=3)


def test_a_branch_on_the_same_symbol_merges_in_one_subset():
    nfa = FiniteAutomaton(
        deterministic=False,
        alphabet=["a", "b"],
        description="Termina en a",
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q0", read="a"),
            Transition(from_state="q0", to="q1", read="a"),
            Transition(from_state="q0", to="q0", read="b"),
        ],
    )
    dfa = nfa_to_dfa(nfa).automaton
    assert "{q0,q1}" in {state.id for state in dfa.states}
    assert validate_fa(dfa).errors == []
    assert all(transition.read for transition in dfa.transitions)
    prepared, _notes = prepare_fa(nfa)
    _same_language(prepared, dfa, length=4)


def test_an_epsilon_cycle_finishes_and_accepts_the_empty_word():
    nfa = FiniteAutomaton(
        deterministic=False,
        alphabet=["a", "b"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="ε"),
            Transition(from_state="q1", to="q0", read="epsilon"),
            Transition(from_state="q1", to="q1", read="a"),
        ],
    )
    dfa = nfa_to_dfa(nfa).automaton
    assert validate_fa(dfa).errors == []
    assert simulate(dfa, "").accepted is True
    assert simulate(dfa, "aa").accepted is True
    assert simulate(dfa, "b").accepted is False
    prepared, _notes = prepare_fa(nfa)
    _same_language(prepared, dfa, length=3)


def test_an_unreachable_state_is_left_out():
    nfa = EXAMPLES["a-estrella"].automaton.model_copy(deep=True)
    nfa.states.append(State(id="lejos", initial=False, final=False))
    dfa = nfa_to_dfa(nfa).automaton
    assert all("lejos" not in state.id for state in dfa.states)
    assert len(EXAMPLES["a-estrella"].automaton.states) == 3


def test_a_dfa_keeps_its_states():
    parity = EXAMPLES["paridad"].automaton
    result = nfa_to_dfa(parity)
    assert result.already is True
    assert [state.id for state in result.automaton.states] == ["q0", "q1"]
    assert result.automaton.description == parity.description
    assert simulate(result.automaton, "11").accepted is True
    assert simulate(result.automaton, "1").accepted is False


def test_subset_names_that_would_collide_get_a_suffix():
    nfa = FiniteAutomaton(
        deterministic=False,
        alphabet=["x", "y"],
        states=[
            State(id="q0", initial=True, final=True),
            State(id="a,b", initial=False, final=False),
            State(id="c", initial=False, final=False),
            State(id="a", initial=False, final=False),
            State(id="b,c", initial=False, final=False),
        ],
        transitions=[
            Transition(from_state="q0", to="a,b", read="x"),
            Transition(from_state="q0", to="c", read="x"),
            Transition(from_state="q0", to="a", read="y"),
            Transition(from_state="q0", to="b,c", read="y"),
        ],
    )
    ids = [state.id for state in nfa_to_dfa(nfa).automaton.states]
    assert len(ids) == len(set(ids)) == 3
    assert "{a,b,c}" in ids
    assert "{a,b,c}#2" in ids


def test_subset_cap_refuses_in_spanish(monkeypatch):
    nfa = _three_subsets()
    assert len(nfa_to_dfa(nfa).automaton.states) == 3
    monkeypatch.setattr("app.determinize.MAX_SUBSETS", 2)
    with pytest.raises(DeterminizeError) as exc:
        nfa_to_dfa(nfa)
    message = str(exc.value)
    assert "2" in message
    assert "trabar" in message


def test_a_broken_nfa_is_a_spanish_error():
    broken = FiniteAutomaton(
        deterministic=False,
        alphabet=["a"],
        states=[State(id="q0", initial=True, final=False)],
        transitions=[Transition(from_state="q0", to="q0", read="a")],
    )
    with pytest.raises(DeterminizeError) as exc:
        nfa_to_dfa(broken)
    assert "finales" in str(exc.value)


def test_the_screen_determinizes_the_example_and_exports_without_epsilon():
    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("Determinizar no tiene que llamar a Ollama.")

    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
        assert page.status_code == 200
        assert 'id="determinize"' in page.text
        assert "Determinizar" in page.text
        assert 'id="fresh"' in page.text
        assert 'id="download"' in page.text
        assert 'id="remember"' in page.text
        assert "Determinizando" in script.text
        assert "/determinize" in script.text

        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            missing = client.post(f"/api/sessions/{session_id}/determinize")
            assert missing.status_code == 409
            assert "determinizar" in missing.json()["detail"]

            loaded = client.post(f"/api/sessions/{session_id}/examples/a-estrella")
            assert loaded.status_code == 200
            assert loaded.json()["automaton"]["deterministic"] is False

            converted = client.post(f"/api/sessions/{session_id}/determinize")
            assert converted.status_code == 200
            body = converted.json()
            assert body["errors"] == []
            assert body["export_ready"] is True
            assert body["automaton"]["deterministic"] is True
            assert "subconjuntos" in body["messages"][-1]["content"]
            assert all(item["read"] for item in body["automaton"]["transitions"])
            assert "pozo" not in {state["id"] for state in body["automaton"]["states"]}
            assert any("falta la transición con b" in warning for warning in body["warnings"])

            for word in ("", "a", "aa"):
                result = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
                assert result.json()["accepted"] is True, word
            rejected = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "b"})
            assert rejected.json()["accepted"] is False

            exported = client.get(f"/api/sessions/{session_id}/export")
            assert exported.status_code == 200
            assert exported.headers["content-type"].startswith("application/xml")
            root = ET.fromstring(exported.text.encode("utf-8"))
            assert root.findtext("type") == "fa"
            initials = [state for state in root.findall("./automaton/state") if state.find("initial") is not None]
            assert len(initials) == 1
            reads = [node.text for node in root.findall("./automaton/transition/read")]
            assert reads
            assert all(reads)
            _assert_total(root, ["a", "b"])
            assert "pozo" in {state.get("name") for state in root.findall("./automaton/state")}

            again = client.post(f"/api/sessions/{session_id}/determinize")
            assert again.status_code == 200
            assert "Ya es un AFD" in again.json()["messages"][-1]["content"]
            assert [state["id"] for state in again.json()["automaton"]["states"]] == [
                state["id"] for state in body["automaton"]["states"]
            ]

            unknown = client.post("/api/sessions/no-existe/determinize")
            assert unknown.status_code == 404


def test_over_the_cap_the_api_answers_409(monkeypatch):
    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("Determinizar no tiene que llamar a Ollama.")

    monkeypatch.setattr("app.determinize.MAX_SUBSETS", 2)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        store.get(session_id).automaton = _three_subsets()
        with patch("app.service.chat", fake_chat):
            response = client.post(f"/api/sessions/{session_id}/determinize")
        assert response.status_code == 409
        assert "trabar" in response.json()["detail"]
        assert store.get(session_id).automaton.deterministic is False


def _three_subsets() -> FiniteAutomaton:
    # Dos flechas con a, así no es un AFD. Los subconjuntos alcanzables son tres.
    return FiniteAutomaton(
        deterministic=False,
        alphabet=["a", "b"],
        description="Tres subconjuntos",
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=False),
            State(id="q2", initial=False, final=False),
            State(id="q3", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="a"),
            Transition(from_state="q0", to="q2", read="a"),
            Transition(from_state="q1", to="q3", read="b"),
        ],
    )


def _same_language(left: FiniteAutomaton, right: FiniteAutomaton, length: int) -> None:
    for word in _words(left.alphabet, length):
        assert simulate(left, word).accepted is simulate(right, word).accepted, word


def _words(alphabet: list[str], length: int) -> list[str]:
    found = [""]
    frontier = [""]
    for _ in range(length):
        frontier = [word + symbol for word in frontier for symbol in alphabet]
        found.extend(frontier)
    return found


def _assert_total(root: ET.Element, alphabet: list[str]) -> None:
    states = root.findall("./automaton/state")
    names = {state.get("id"): state.get("name") for state in states}
    counts: dict[tuple[str, str], int] = {}
    for transition in root.findall("./automaton/transition"):
        source = names[transition.findtext("from")]
        symbol = transition.findtext("read")
        assert symbol in alphabet
        key = (source, symbol)
        counts[key] = counts.get(key, 0) + 1
    for state in states:
        for symbol in alphabet:
            assert counts.get((state.get("name"), symbol), 0) == 1
