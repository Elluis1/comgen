import time
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.export_jflap import complete_partial_dfa, export_jflap
from app.interpret import ModelReplyError, interpret_text
from app.main import app
from app.schemas import FiniteAutomaton, State, Transition
from app.simulate import simulate
from app.store import store
from app.validate import prepare_fa, validate_fa


def test_paridad_is_a_complete_dfa_and_exports():
    automaton = EXAMPLES["paridad"].automaton
    check = validate_fa(automaton)
    assert check.errors == []
    assert check.warnings == []

    root = ET.fromstring(export_jflap(automaton).encode("utf-8"))
    assert root.findtext("type") == "fa"
    states = root.findall("./automaton/state")
    assert [state.get("name") for state in states] == ["q0", "q1"]
    assert states[0].find("initial") is not None
    assert states[0].find("final") is not None
    assert states[1].find("final") is None
    transitions = root.findall("./automaton/transition")
    assert len(transitions) == 4
    assert states[0].findtext("x") != states[1].findtext("x")


def test_ends_with_01_accepts_the_right_strings():
    automaton = EXAMPLES["termina-en-01"].automaton
    assert validate_fa(automaton).ok
    assert simulate(automaton, "").accepted is False
    assert simulate(automaton, "01").accepted is True
    assert simulate(automaton, "001").accepted is True
    assert simulate(automaton, "101").accepted is True
    assert simulate(automaton, "010").accepted is False
    assert simulate(automaton, "011").accepted is False


def test_even_ones_and_epsilon_closure():
    automaton = EXAMPLES["paridad"].automaton
    assert simulate(automaton, "").accepted is True
    assert simulate(automaton, "1").accepted is False
    assert simulate(automaton, "11").accepted is True
    assert simulate(automaton, "1010").accepted is True

    epsilon = FiniteAutomaton(
        deterministic=False,
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[Transition(from_state="q0", to="q1", read="ε")],
    )
    prepared, _notes = prepare_fa(epsilon)
    assert validate_fa(prepared).ok
    assert simulate(prepared, "").accepted is True
    xml = export_jflap(prepared)
    read = ET.fromstring(xml.encode("utf-8")).find("./automaton/transition/read")
    assert read is not None
    assert read.text is None


def test_automaton_without_final_states_is_not_exportable():
    empty = FiniteAutomaton(
        alphabet=["a"],
        states=[State(id="q0", initial=True, final=False)],
        transitions=[Transition(from_state="q0", to="q0", read="a")],
    )
    assert any("finales" in error for error in validate_fa(empty).errors)
    broken = FiniteAutomaton(
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=True, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="a"),
            Transition(from_state="q1", to="q1", read="a"),
        ],
    )
    assert any("inicial" in error for error in validate_fa(broken).errors)

    partial = FiniteAutomaton(
        alphabet=["0", "1"],
        states=[State(id="q0", initial=True, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="0")],
    )
    check = validate_fa(partial)
    assert check.ok
    assert any("falta la transición con 1" in warning for warning in check.warnings)


def test_interpret_text_accepts_model_json_and_refuses_turing_machines():
    raw = EXAMPLES["paridad"].automaton.model_dump_json(by_alias=True)
    parsed = interpret_text(raw)
    assert parsed.export_ready
    assert parsed.automaton is not None
    assert simulate(parsed.automaton, "11").accepted is True

    refused = interpret_text('{"kind":"turing","explanation":"Eso es una máquina de Turing."}')
    assert refused.unsupported
    assert refused.automaton is None

    with pytest.raises(ModelReplyError):
        interpret_text('{"kind":"fa","alphabet":["a"],"states":[],"transitions":[]}')


def test_api_example_simulate_and_export():
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        loaded = client.post(f"/api/sessions/{session_id}/examples/paridad")
        assert loaded.status_code == 200
        body = loaded.json()
        assert body["export_ready"] is True
        assert body["automaton"]["transitions"][0]["from"] == "q0"

        accepted = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "11"})
        assert accepted.json()["accepted"] is True
        rejected = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "2"})
        assert rejected.json()["ok"] is False

        exported = client.get(f"/api/sessions/{session_id}/export")
        assert exported.status_code == 200
        assert exported.headers["content-disposition"].endswith('.jff"')
        assert "<type>fa</type>" in exported.text
        assert client.post(f"/api/sessions/{session_id}/examples/no-existe").status_code == 404


def test_export_partial_dfa_adds_a_nonfinal_sink():
    partial = FiniteAutomaton(
        description="Solo ceros",
        alphabet=["0", "1"],
        states=[State(id="q0", initial=True, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="0")],
    )
    check = validate_fa(partial)
    assert check.ok
    assert any("falta la transición con 1" in warning for warning in check.warnings)

    completed = complete_partial_dfa(partial)
    assert [state.id for state in completed.states] == ["q0", "pozo"]
    sink = completed.states[1]
    assert sink.initial is False
    assert sink.final is False
    assert len(partial.states) == 1
    assert len(partial.transitions) == 1

    words = ["", "0", "00", "000", "1", "01", "10", "11", "010"]
    for word in words:
        assert simulate(completed, word).accepted is simulate(partial, word).accepted

    root = _parse_jff(export_jflap(partial))
    assert root.findtext("type") == "fa"
    states = root.findall("./automaton/state")
    assert [state.get("name") for state in states] == ["q0", "pozo"]
    assert states[0].find("initial") is not None
    assert states[0].find("final") is not None
    assert states[1].find("initial") is None
    assert states[1].find("final") is None
    _assert_total(root, ["0", "1"])
    assert validate_fa(partial).warnings == check.warnings


def test_export_keeps_a_total_dfa_and_skips_an_nfa():
    total = EXAMPLES["paridad"].automaton
    assert complete_partial_dfa(total) is total
    assert "pozo" not in export_jflap(total)

    nfa = FiniteAutomaton(
        deterministic=False,
        alphabet=["a", "b"],
        states=[State(id="q0", initial=True, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="a")],
    )
    assert complete_partial_dfa(nfa) is nfa
    names = [state.get("name") for state in _parse_jff(export_jflap(nfa)).findall("./automaton/state")]
    assert names == ["q0"]


def test_sink_name_skips_an_existing_pozo():
    partial = FiniteAutomaton(
        alphabet=["a", "b"],
        states=[
            State(id="pozo", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="pozo", to="q1", read="a"),
            Transition(from_state="q1", to="q1", read="b"),
        ],
    )
    completed = complete_partial_dfa(partial)
    assert [state.id for state in completed.states] == ["pozo", "q1", "pozo2"]
    assert completed.states[2].final is False
    words = ["", "a", "b", "ab", "aa", "ba", "bb", "aab"]
    for word in words:
        assert simulate(completed, word).accepted is simulate(partial, word).accepted
    _assert_total(_parse_jff(export_jflap(partial)), ["a", "b"])


def test_downloaded_jff_is_total_and_the_warning_stays_on_screen():
    partial = FiniteAutomaton(
        description="Solo ceros",
        alphabet=["0", "1"],
        states=[State(id="q0", initial=True, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="0")],
    )
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        session = store.get(session_id)
        session.automaton = partial
        session.warnings = validate_fa(partial).warnings

        exported = client.get(f"/api/sessions/{session_id}/export")
        assert exported.status_code == 200
        assert "<type>fa</type>" in exported.text
        root = _parse_jff(exported.text)
        assert [state.get("name") for state in root.findall("./automaton/state")] == ["q0", "pozo"]
        _assert_total(root, ["0", "1"])

        assert [state.id for state in session.automaton.states] == ["q0"]
        assert any("falta la transición con 1" in warning for warning in session.warnings)


def _parse_jff(xml: str) -> ET.Element:
    return ET.fromstring(xml.encode("utf-8"))


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


def test_export_of_a_large_dfa_stays_fast():
    # Antes, armar el XML de 4000 estados tardaba más de una décima.
    count = 4000
    states = [State(id=f"q{i}", initial=i == 0, final=i == 0) for i in range(count)]
    transitions = [
        Transition(from_state=f"q{index}", to=f"q{(index + 1) % count}", read=symbol)
        for index in range(count)
        for symbol in ("0", "1")
    ]
    automaton = FiniteAutomaton(
        deterministic=True,
        alphabet=["0", "1"],
        states=states,
        transitions=transitions,
        description="ciclo",
    )
    started = time.perf_counter()
    xml = export_jflap(automaton)
    assert time.perf_counter() - started < 0.08
    root = ET.fromstring(xml.encode("utf-8"))
    assert root.findtext("type") == "fa"
    assert len(root.findall("./automaton/state")) == count
    assert len(root.findall("./automaton/transition")) == count * 2
    assert "pozo" not in xml


def test_export_escapes_a_return_a_tab_and_a_less_than():
    automaton = FiniteAutomaton(
        deterministic=False,
        alphabet=["<"],
        description="nota",
        states=[State(id="a\rb\tc", initial=True, final=True)],
        transitions=[Transition(from_state="a\rb\tc", to="a\rb\tc", read="<")],
    )
    xml = export_jflap(automaton)
    assert 'name="a&#13;b&#09;c"' in xml
    assert "<read>&lt;</read>" in xml
    ET.fromstring(xml.encode("utf-8"))


def test_simulate_requires_exactly_one_initial_state():
    missing = FiniteAutomaton(
        alphabet=["a"],
        states=[State(id="q0", initial=False, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="a")],
    )
    result = simulate(missing, "a")
    assert result.ok is False
    assert result.accepted is False
    assert "inicial" in result.message

    two = FiniteAutomaton(
        deterministic=False,
        alphabet=["a"],
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=True, final=True),
        ],
        transitions=[Transition(from_state="q0", to="q0", read="a")],
    )
    assert simulate(two, "").ok is False
    assert simulate(two, "a").accepted is False
