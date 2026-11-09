import threading
import time
import xml.etree.ElementTree as ET
from unittest.mock import patch
from xml.parsers.expat import ParserCreate

import pytest
from fastapi.testclient import TestClient

from app.determinize import nfa_to_dfa
from app.examples import EXAMPLES
from app.export_jflap import export_jflap
from app.grammar import (
    MAX_PRODUCTIONS,
    MAX_STATES,
    GrammarError,
    Production,
    RegularGrammar,
    dfa_to_grammar,
    export_jflap_grammar,
    grammar_to_nfa,
    validate_grammar,
)
from app.main import app
from app.sanitize import xml_char_allowed
from app.schemas import FiniteAutomaton, State, Transition
from app.service import grammar_session
from app.simulate import simulate
from app.store import store
from app.validate import validate_fa


PARITY_ACCEPT = ["", "0", "11", "1010"]
PARITY_REJECT = ["1", "10"]
PARITY_TEXT = "S → 0S | 1A | ε\nA → 0A | 1S"
ENDS_TEXT = "S → 0A | 1S\nA → 0A | 1B\nB → 0A | 1S | ε"


def _words(alphabet: list[str], limit: int) -> list[str]:
    words = [""]
    layer = [""]
    for _ in range(limit):
        layer = [word + symbol for word in layer for symbol in alphabet]
        words.extend(layer)
    return words


def _strict_xml(document: str) -> ET.Element:
    for char in document:
        assert xml_char_allowed(char), hex(ord(char))
    parser = ParserCreate(encoding="UTF-8")
    parser.Parse(document.encode("utf-8"), True)
    return ET.fromstring(document.encode("utf-8"))


def _same(original: FiniteAutomaton, other: FiniteAutomaton, words: list[str]) -> None:
    for word in words:
        left = simulate(original, word)
        right = simulate(other, word)
        assert left.ok and right.ok, (word, left.message, right.message)
        assert left.accepted is right.accepted, (word, left.accepted, right.accepted)


def _partial() -> FiniteAutomaton:
    return FiniteAutomaton(
        deterministic=True,
        alphabet=["0", "1"],
        description="Solo ceros -- \x00\x08 con --> y salto\r\n",
        states=[State(id="q0", initial=True, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="0")],
    )


def test_parity_grammar_roundtrips_up_to_length_6_and_does_not_touch_the_dfa():
    automaton = EXAMPLES["paridad"].automaton
    before = automaton.model_dump()
    started = time.perf_counter()
    grammar = dfa_to_grammar(automaton)
    assert time.perf_counter() - started < 0.2
    assert automaton.model_dump() == before
    assert grammar.text() == PARITY_TEXT
    assert grammar.start == "S"
    assert not validate_grammar(grammar)
    assert "pozo" not in grammar.nonterminals

    nfa = grammar_to_nfa(grammar)
    assert validate_fa(nfa).ok
    assert {state.id for state in nfa.states} == {"S", "A"}
    for word in PARITY_ACCEPT:
        assert simulate(nfa, word).accepted is True, word
    for word in PARITY_REJECT:
        assert simulate(nfa, word).accepted is False, word
    _same(automaton, nfa, _words(["0", "1"], 6))

    root = _strict_xml(export_jflap_grammar(grammar))
    assert root.findtext("type") == "grammar"
    productions = [
        (node.findtext("left"), node.findtext("right") or "")
        for node in root.findall("production")
    ]
    assert productions[0][0] == "S"
    assert ("S", "0S") in productions
    assert ("S", "1A") in productions
    assert ("S", "") in productions
    assert ("A", "0A") in productions
    assert ("A", "1S") in productions
    assert "pozo" not in {left for left, _right in productions}
    comment = export_jflap_grammar(grammar).split("<!--", 1)[1].split("-->", 1)[0]
    assert "--" not in comment


def test_ends_with_01_and_a_star_keep_the_language():
    ends = EXAMPLES["termina-en-01"].automaton
    grammar = dfa_to_grammar(ends)
    assert grammar.text() == ENDS_TEXT
    _same(ends, grammar_to_nfa(grammar), _words(["0", "1"], 6))

    with pytest.raises(GrammarError) as exc:
        dfa_to_grammar(EXAMPLES["a-estrella"].automaton)
    assert "determinizar" in str(exc.value)

    determined = nfa_to_dfa(EXAMPLES["a-estrella"].automaton).automaton
    before = determined.model_dump()
    star = dfa_to_grammar(determined)
    assert determined.model_dump() == before
    assert "pozo" not in star.nonterminals
    built = grammar_to_nfa(star)
    for word in ("", "a", "aa"):
        assert simulate(built, word).accepted is True
    assert simulate(built, "b").accepted is False


def test_terminal_only_and_empty_productions_are_right_linear():
    only_a = RegularGrammar(
        terminals=("a",),
        nonterminals=("S",),
        start="S",
        productions=(Production("S", "a", None),),
    )
    assert not validate_grammar(only_a)
    nfa = grammar_to_nfa(only_a)
    assert validate_fa(nfa).ok
    assert any(state.id == "qf" and state.final and not state.initial for state in nfa.states)
    assert simulate(nfa, "a").accepted is True
    assert simulate(nfa, "").accepted is False
    assert simulate(nfa, "aa").accepted is False
    assert _strict_xml(export_jflap_grammar(only_a)).findtext("./production/right") == "a"

    empty = RegularGrammar(
        terminals=("a",),
        nonterminals=("S",),
        start="S",
        productions=(Production("S", None, None),),
    )
    built = grammar_to_nfa(empty)
    assert simulate(built, "").accepted is True
    assert simulate(built, "a").accepted is False
    right = _strict_xml(export_jflap_grammar(empty)).find("./production/right")
    assert right is not None and not (right.text or "")


def test_validation_rejects_the_forms_that_are_not_right_linear():
    unit = RegularGrammar(
        terminals=("a",),
        nonterminals=("S", "A"),
        start="S",
        productions=(Production("S", None, "A"),),
    )
    unit_errors = validate_grammar(unit)
    assert any("A → aB" in error for error in unit_errors)
    with pytest.raises(GrammarError):
        grammar_to_nfa(unit)

    overlap = validate_grammar(RegularGrammar(("a",), ("a",), "a", ()))
    assert any("terminal y no terminal" in error for error in overlap)

    missing = validate_grammar(RegularGrammar(("a",), ("A",), "", ()))
    assert any("símbolo inicial" in error for error in missing)

    repeated = validate_grammar(RegularGrammar(("a",), ("S", "S"), "S", ()))
    assert any("mismo nombre" in error for error in repeated)

    long_symbol = validate_grammar(RegularGrammar(("ab",), ("S",), "S", ()))
    assert any("un solo carácter" in error for error in long_symbol)

    unknown = validate_grammar(
        RegularGrammar(("a",), ("S",), "S", (Production("S", "a", "B"),))
    )
    assert any("no está en la gramática" in error for error in unknown)


def test_a_partial_dfa_omits_the_missing_arrow_and_the_sink_stays_in_the_jff_only():
    automaton = _partial()
    before = automaton.model_dump()
    grammar = dfa_to_grammar(automaton)
    assert automaton.model_dump() == before
    assert grammar.text() == "S → 0S | ε"
    assert "pozo" not in grammar.nonterminals
    built = grammar_to_nfa(grammar)
    assert "pozo" not in {state.id for state in built.states}
    _same(automaton, built, ["", "0", "00", "000", "1", "10", "01", "11"])

    xml = export_jflap_grammar(grammar)
    root = _strict_xml(xml)
    assert root.findtext("type") == "grammar"
    assert "pozo" not in xml
    comment = xml.split("<!--", 1)[1].split("-->", 1)[0]
    assert "--" not in comment
    assert "\x00" not in xml
    assert "\x08" not in xml
    fa = export_jflap(automaton)
    assert "<type>fa</type>" in fa
    assert "pozo" in fa


def test_uppercase_terminal_and_too_many_states_skip_jflap_but_the_nfa_remains():
    letters = FiniteAutomaton(
        deterministic=True,
        alphabet=["A", "b"],
        states=[
            State(id="q0", initial=True, final=True),
            State(id="q1", initial=False, final=False),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="A"),
            Transition(from_state="q0", to="q0", read="b"),
            Transition(from_state="q1", to="q1", read="A"),
            Transition(from_state="q1", to="q0", read="b"),
        ],
    )
    grammar = dfa_to_grammar(letters)
    assert grammar.start == "S"
    assert "A" not in grammar.nonterminals
    assert "A" in grammar.terminals
    with pytest.raises(GrammarError) as exc:
        export_jflap_grammar(grammar)
    assert "JFLAP" in str(exc.value)
    assert "mayúscula" in str(exc.value)
    _same(letters, grammar_to_nfa(grammar), _words(["A", "b"], 3))

    states = [State(id=f"q{index}", initial=index == 0, final=index == 0) for index in range(30)]
    transitions = [
        Transition(from_state=f"q{index}", to=f"q{(index + 1) % 30}", read="a")
        for index in range(30)
    ]
    wide = FiniteAutomaton(deterministic=True, alphabet=["a"], states=states, transitions=transitions)
    wide_grammar = dfa_to_grammar(wide)
    assert wide_grammar.start == "S"
    assert any(len(name) > 1 for name in wide_grammar.nonterminals)
    with pytest.raises(GrammarError) as refused:
        export_jflap_grammar(wide_grammar)
    assert "JFLAP" in str(refused.value)
    built = grammar_to_nfa(wide_grammar)
    assert simulate(built, "").accepted is True
    assert simulate(built, "a" * 30).accepted is True
    assert simulate(built, "a").accepted is False


def test_lookalike_epsilon_stays_a_terminal_and_a_real_epsilon_asks_to_determinize():
    epsilon = FiniteAutomaton(
        deterministic=True,
        alphabet=["a"],
        states=[State(id="q0", initial=True, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="ε")],
    )
    with pytest.raises(GrammarError) as exc:
        dfa_to_grammar(epsilon)
    assert "determinizar" in str(exc.value)

    lookalike = FiniteAutomaton(
        deterministic=True,
        alphabet=["ɛ"],
        states=[State(id="q0", initial=True, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="ɛ")],
    )
    grammar = dfa_to_grammar(lookalike)
    assert grammar.terminals == ("ɛ",)
    built = grammar_to_nfa(grammar)
    assert simulate(built, "").accepted is True
    assert simulate(built, "ɛ").accepted is True
    assert simulate(built, "ε").ok is False


def test_operators_and_markup_survive_in_the_grammar_file():
    automaton = FiniteAutomaton(
        deterministic=True,
        alphabet=["<", "&", "*"],
        description='Gramática --> rara \x00\x08 "con" salto\r\n',
        states=[
            State(id="{q0,q1}", initial=True, final=False),
            State(id="a&b<c", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="{q0,q1}", to="a&b<c", read="<"),
            Transition(from_state="{q0,q1}", to="{q0,q1}", read="&"),
            Transition(from_state="{q0,q1}", to="{q0,q1}", read="*"),
            Transition(from_state="a&b<c", to="a&b<c", read="<"),
            Transition(from_state="a&b<c", to="{q0,q1}", read="&"),
            Transition(from_state="a&b<c", to="{q0,q1}", read="*"),
        ],
    )
    before = automaton.model_dump()
    grammar = dfa_to_grammar(automaton)
    assert automaton.model_dump() == before
    assert grammar.nonterminals == ("S", "A")
    root = _strict_xml(export_jflap_grammar(grammar))
    rights = [node.findtext("right") or "" for node in root.findall("production")]
    assert "<A" in rights
    assert "&S" in rights
    assert "*S" in rights
    comment = export_jflap_grammar(grammar).split("<!--", 1)[1].split("-->", 1)[0]
    assert "-->" not in comment
    _same(automaton, grammar_to_nfa(grammar), ["<", "&", "*", "", "<&", "*<"])


def test_an_unminimized_dfa_keeps_every_state_in_the_grammar():
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
    grammar = dfa_to_grammar(automaton)
    assert grammar.nonterminals == ("S", "A")
    assert grammar.text() == "S → aS | bS | ε\nA → aA | bA | ε"
    _same(automaton, grammar_to_nfa(grammar), _words(["a", "b"], 3))


def test_oversized_automata_fail_fast(monkeypatch):
    monkeypatch.setattr("app.grammar.MAX_STATES", 2)
    started = time.perf_counter()
    with pytest.raises(GrammarError) as exc:
        dfa_to_grammar(EXAMPLES["termina-en-01"].automaton)
    assert time.perf_counter() - started < 0.2
    assert "trabar" in str(exc.value)
    assert "2" in str(exc.value)

    monkeypatch.setattr("app.grammar.MAX_STATES", MAX_STATES)
    monkeypatch.setattr("app.grammar.MAX_PRODUCTIONS", 5)
    started = time.perf_counter()
    with pytest.raises(GrammarError) as exc:
        dfa_to_grammar(EXAMPLES["paridad"].automaton)
    assert time.perf_counter() - started < 0.2
    assert "trabar" in str(exc.value)
    assert str(MAX_PRODUCTIONS) not in str(exc.value)


def test_the_screen_returns_the_grammar_without_ollama():
    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("Armar la gramática no tiene que llamar a Ollama.")

    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
        assert page.status_code == 200
        assert 'id="grammar"' in page.text
        assert "Gramática" in page.text
        assert 'id="fresh"' in page.text
        assert 'id="download"' in page.text
        assert 'id="remember"' in page.text
        assert 'id="determinize"' in page.text
        assert 'id="regex"' in page.text
        assert "Nuevo autómata" in page.text
        assert "/grammar" in script.text
        assert "Armando la gramática" in script.text
        assert "grammar-line" in script.text
        assert "grammar-download" in script.text
        assert "GRAMMAR_LINE_LIMIT = 32" in script.text

        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            missing = client.post(f"/api/sessions/{session_id}/grammar")
            assert missing.status_code == 409
            assert "gramática" in missing.json()["detail"]
            missing_file = client.get(f"/api/sessions/{session_id}/grammar/export")
            assert missing_file.status_code == 409

            loaded = client.post(f"/api/sessions/{session_id}/examples/paridad")
            assert loaded.status_code == 200
            before = loaded.json()["automaton"]

            converted = client.post(f"/api/sessions/{session_id}/grammar")
            assert converted.status_code == 200
            body = converted.json()
            assert body["grammar"]["text"] == PARITY_TEXT
            assert body["grammar"]["jflap"] is True
            assert body["grammar"]["start"] == "S"
            assert "gramática lineal a derecha" in body["messages"][-1]["content"]
            assert "S → 0S | 1A | ε" in body["messages"][-1]["content"]
            assert body["automaton"]["states"] == before["states"]
            assert body["automaton"]["transitions"] == before["transitions"]
            assert "pozo" not in {state["id"] for state in body["automaton"]["states"]}

            exported = client.get(f"/api/sessions/{session_id}/grammar/export")
            assert exported.status_code == 200
            assert exported.headers["content-type"].startswith("application/xml")
            disposition = exported.headers["content-disposition"]
            assert disposition.startswith('attachment; filename="gramatica-')
            assert disposition.endswith('.jff"')
            assert "\n" not in disposition
            assert "\r" not in disposition
            assert '"' not in disposition[len('attachment; filename="') : -1]
            root = _strict_xml(exported.text)
            assert root.findtext("type") == "grammar"
            assert ("S", "") in [
                (node.findtext("left"), node.findtext("right") or "")
                for node in root.findall("production")
            ]

            nfa = client.post(f"/api/sessions/{session_id}/examples/a-estrella")
            assert nfa.json()["automaton"]["deterministic"] is False
            nfa_states = nfa.json()["automaton"]["states"]
            refused = client.post(f"/api/sessions/{session_id}/grammar")
            assert refused.status_code == 409
            assert "determinizar" in refused.json()["detail"]
            kept = store.get(session_id).automaton
            assert kept is not None
            assert [state.id for state in kept.states] == [state["id"] for state in nfa_states]

            determined = client.post(f"/api/sessions/{session_id}/determinize")
            assert determined.status_code == 200
            states_before = determined.json()["automaton"]["states"]
            expressed = client.post(f"/api/sessions/{session_id}/grammar")
            assert expressed.status_code == 200
            assert expressed.json()["automaton"]["states"] == states_before
            assert "pozo" not in {state["id"] for state in expressed.json()["automaton"]["states"]}
            built = grammar_to_nfa(dfa_to_grammar(store.get(session_id).automaton))
            for word in ("", "a", "aa"):
                assert simulate(built, word).accepted is True
            assert simulate(built, "b").accepted is False

            unknown = client.post("/api/sessions/no-existe/grammar")
            assert unknown.status_code == 404
            unknown_file = client.get("/api/sessions/no-existe/grammar/export")
            assert unknown_file.status_code == 404


def test_concurrent_grammar_on_one_session_does_not_touch_the_automaton():
    session = store.create()
    session.automaton = EXAMPLES["paridad"].automaton.model_copy(deep=True)
    before = session.automaton.model_dump()
    errors: list[BaseException] = []
    texts: list[str] = []

    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("Armar la gramática no tiene que llamar a Ollama.")

    def once() -> None:
        try:
            with patch("app.service.chat", fake_chat):
                body = grammar_session(session.id)
            texts.append(body["grammar"]["text"])
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=once) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert texts == [PARITY_TEXT] * 8
    assert session.automaton is not None
    assert session.automaton.model_dump() == before
    assert "pozo" not in {state.id for state in session.automaton.states}
