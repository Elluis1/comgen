"""Ataques de la corrida Romper del 2026-10-18. No usan Ollama.

Jamo, la gramática que se lee mal, la expresión que junta símbolos y el
nombre con coma en el dibujo y en la tabla.
"""

import json
import shutil
import subprocess
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
from xml.parsers.expat import ParserCreate

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.grammar import (
    GrammarError,
    Production,
    RegularGrammar,
    dfa_to_grammar,
    export_jflap_grammar,
    grammar_to_nfa,
    validate_grammar,
)
from app.main import app
from app.regex_from_fa import RegexFromFaError, fa_to_regex
from app.regex_lang import compile_pattern
from app.sanitize import xml_char_allowed
from app.schemas import FiniteAutomaton, State, Transition
from app.simulate import simulate
from app.store import store


ROOT = Path(__file__).resolve().parents[1]
MARK = "\u0301"
LEAD = "\u1100"  # ᄀ
VOWEL = "\u1161"  # ᅡ
TRAIL = "\u11A8"  # ᆨ
LEAD2 = "\u1102"  # ᄂ
SYLLABLE = "\uac00"  # 가
SYLLABLE_T = "\uac01"  # 각
NA = "\ub098"  # 나
COMPAT_L = "\u3131"  # ㄱ
COMPAT_V = "\u314f"  # ㅏ
NFD_E = "e\u0301"


def _strict_xml(document: str) -> ET.Element:
    for char in document:
        assert xml_char_allowed(char), hex(ord(char))
    parser = ParserCreate(encoding="UTF-8")
    parser.Parse(document.encode("utf-8"), True)
    return ET.fromstring(document.encode("utf-8"))


def _fa(alphabet, states, transitions, deterministic=True, description="ataque"):
    return FiniteAutomaton(
        deterministic=deterministic,
        alphabet=list(alphabet),
        states=states,
        transitions=transitions,
        description=description,
    )


def _chain(alphabet, symbols):
    """Una cadena de símbolos, el último estado es final."""
    states = [
        State(id=f"q{index}", initial=index == 0, final=index == len(symbols))
        for index in range(len(symbols) + 1)
    ]
    transitions = [
        Transition(from_state=f"q{index}", to=f"q{index + 1}", read=symbol)
        for index, symbol in enumerate(symbols)
    ]
    return _fa(alphabet, states, transitions)


def _node_json(runner: str, payload: dict, options: dict | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede armar el dibujo ni la tabla.")
    command = [node, str(ROOT / "tests" / runner), json.dumps(payload)]
    if options is not None:
        command.append(json.dumps(options))
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def test_hangul_pieces_in_the_alphabet_are_not_eaten():
    assert unicodedata.normalize("NFC", LEAD + VOWEL) == SYLLABLE
    assert unicodedata.normalize("NFC", LEAD + VOWEL + TRAIL) == SYLLABLE_T
    assert unicodedata.normalize("NFC", LEAD2 + VOWEL) == NA
    assert unicodedata.normalize("NFC", COMPAT_L + COMPAT_V) == COMPAT_L + COMPAT_V

    pieces = _chain([LEAD, VOWEL], [LEAD, VOWEL])
    word = LEAD + VOWEL
    result = simulate(pieces, word)
    assert result.ok and result.accepted is True
    assert [step.symbol for step in result.steps] == ["", LEAD, VOWEL]
    composed = simulate(pieces, SYLLABLE)
    assert composed.ok is False
    assert SYLLABLE in composed.message

    syllable = _fa(
        [SYLLABLE],
        [State(id="q0", initial=True, final=True)],
        [Transition(from_state="q0", to="q0", read=SYLLABLE)],
    )
    folded = simulate(syllable, word)
    assert folded.ok and folded.accepted is True
    assert [step.symbol for step in folded.steps] == ["", SYLLABLE]
    assert simulate(syllable, LEAD).ok is False

    three = _chain([LEAD, VOWEL, TRAIL], [LEAD, VOWEL, TRAIL])
    full = LEAD + VOWEL + TRAIL
    accepted = simulate(three, full)
    assert accepted.ok and accepted.accepted is True
    assert [step.symbol for step in accepted.steps] == ["", LEAD, VOWEL, TRAIL]

    one = _fa(
        [SYLLABLE_T],
        [State(id="q0", initial=True, final=True)],
        [Transition(from_state="q0", to="q0", read=SYLLABLE_T)],
    )
    assert [step.symbol for step in simulate(one, full).steps] == ["", SYLLABLE_T]

    mixed_alphabet = ["é", LEAD, VOWEL]
    mixed = _chain(mixed_alphabet, ["é", LEAD, VOWEL])
    mixed_word = "e" + MARK + LEAD + VOWEL
    mixed_run = simulate(mixed, mixed_word)
    assert mixed_run.ok and mixed_run.accepted is True
    assert [step.symbol for step in mixed_run.steps] == ["", "é", LEAD, VOWEL]

    partial = _chain([SYLLABLE, TRAIL], [SYLLABLE, TRAIL])
    partial_word = LEAD + VOWEL + TRAIL
    partial_run = simulate(partial, partial_word)
    assert partial_run.ok and partial_run.accepted is True
    assert [step.symbol for step in partial_run.steps] == ["", SYLLABLE, TRAIL]

    compat = _chain([COMPAT_L, COMPAT_V], [COMPAT_L, COMPAT_V])
    compat_run = simulate(compat, COMPAT_L + COMPAT_V)
    assert compat_run.ok and compat_run.accepted is True
    assert [step.symbol for step in compat_run.steps] == ["", COMPAT_L, COMPAT_V]

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        store.get(session_id).automaton = pieces
        accepted_http = client.post(
            f"/api/sessions/{session_id}/simulate",
            json={"word": word},
        )
        assert accepted_http.status_code == 200
        assert [step["symbol"] for step in accepted_http.json()["steps"]] == ["", LEAD, VOWEL]


def test_a_regex_refuses_symbols_that_would_compose_and_keeps_a_union():
    concat = _chain(["e", MARK], ["e", MARK])
    before = concat.model_dump()
    started = time.perf_counter()
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(concat)
    assert time.perf_counter() - started < 0.2
    assert "carácter" in str(exc.value)
    assert concat.model_dump() == before

    hangul = _chain([LEAD, VOWEL], [LEAD, VOWEL])
    with pytest.raises(RegexFromFaError) as hangul_exc:
        fa_to_regex(hangul)
    assert "carácter" in str(hangul_exc.value)

    union = _fa(
        [LEAD, VOWEL],
        [
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        [
            Transition(from_state="q0", to="q1", read=LEAD),
            Transition(from_state="q0", to="q1", read=VOWEL),
        ],
    )
    pattern = fa_to_regex(union)
    assert SYLLABLE not in pattern
    compiled, _explanation = compile_pattern(pattern)
    for word in (LEAD, VOWEL, LEAD + VOWEL, SYLLABLE, ""):
        left = simulate(union, word)
        right = simulate(compiled, word)
        left_yes = bool(left.ok and left.accepted)
        right_yes = bool(right.ok and right.accepted)
        assert left_yes is right_yes, (pattern, word, left_yes, right_yes)

    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("Sacar la expresión no tiene que llamar a Ollama.")

    with TestClient(app) as client, patch("app.service.chat", fake_chat):
        session_id = client.post("/api/sessions").json()["id"]
        store.get(session_id).automaton = concat
        refused = client.post(f"/api/sessions/{session_id}/regex")
        assert refused.status_code == 409
        assert "carácter" in refused.json()["detail"]
        kept = store.get(session_id).automaton
        assert kept is not None
        assert kept.model_dump() == before
        assert "pozo" not in {state.id for state in kept.states}


def test_grammar_text_quotes_a_bar_a_space_and_a_mark():
    automaton = _fa(
        ["|", "a", " ", MARK, "→"],
        [State(id="q0", initial=True, final=True)],
        [
            Transition(from_state="q0", to="q0", read="|"),
            Transition(from_state="q0", to="q0", read="a"),
            Transition(from_state="q0", to="q0", read=" "),
            Transition(from_state="q0", to="q0", read=MARK),
            Transition(from_state="q0", to="q0", read="→"),
        ],
        description="Barras -- y \x08",
    )
    before = automaton.model_dump()
    grammar = dfa_to_grammar(automaton)
    assert automaton.model_dump() == before
    text = grammar.text()
    assert text.startswith("S → ")
    alternatives = text.removeprefix("S → ").split(" | ")
    assert "" not in alternatives
    assert "«|»" in text
    assert "« »" in text
    assert "«→»" in text
    assert MARK + "S" not in text
    assert "|S" not in text
    built = grammar_to_nfa(grammar)
    for word in ("", "|", "a", " ", MARK, "→", "||", "a|", "|a"):
        assert simulate(automaton, word).accepted is simulate(built, word).accepted

    xml = export_jflap_grammar(grammar)
    root = _strict_xml(xml)
    assert root.findtext("type") == "grammar"
    rights = [node.findtext("right") or "" for node in root.findall("production")]
    assert "|S" in rights
    assert " S" in rights
    assert "→S" in rights
    assert f"{MARK}S" in rights
    comment = xml.split("<!--", 1)[1].split("-->", 1)[0]
    assert "--" not in comment
    assert "\x08" not in xml

    named = RegularGrammar(
        terminals=(LEAD,),
        nonterminals=("S", VOWEL),
        start="S",
        productions=(Production("S", LEAD, VOWEL), Production(VOWEL, None, None)),
    )
    shown = named.text()
    assert SYLLABLE not in unicodedata.normalize("NFC", shown)
    spaced = grammar_to_nfa(named)
    assert simulate(spaced, LEAD).accepted is True
    assert simulate(spaced, "").accepted is False
    with pytest.raises(GrammarError) as refused:
        export_jflap_grammar(named)
    assert "JFLAP" in str(refused.value)


def test_three_productions_and_nfc_names_roundtrip():
    trio = RegularGrammar(
        terminals=("a", "b"),
        nonterminals=("S", "A"),
        start="S",
        productions=(
            Production("S", "a", "A"),
            Production("S", "a", None),
            Production("S", None, None),
            Production("A", "b", None),
        ),
    )
    assert not validate_grammar(trio)
    nfa = grammar_to_nfa(trio)
    assert nfa.deterministic is False
    assert any(state.id == "qf" and state.final and not state.initial for state in nfa.states)
    for word, accepted in (("", True), ("a", True), ("ab", True), ("b", False), ("aa", False)):
        assert simulate(nfa, word).accepted is accepted

    clash = RegularGrammar(
        terminals=("a",),
        nonterminals=("S", "é", NFD_E),
        start="S",
        productions=(Production("S", "a", "é"), Production(NFD_E, None, None)),
    )
    clash_errors = validate_grammar(clash)
    assert any("mismo nombre" in error for error in clash_errors)
    with pytest.raises(GrammarError):
        grammar_to_nfa(clash)

    repeated = validate_grammar(RegularGrammar(("é", NFD_E), ("S",), "S", ()))
    assert any("repetido" in error for error in repeated)

    linked = RegularGrammar(
        terminals=("a",),
        nonterminals=("S", "é"),
        start="S",
        productions=(Production("S", "a", NFD_E), Production("é", None, None)),
    )
    assert not validate_grammar(linked)
    linked_nfa = grammar_to_nfa(linked)
    assert {state.id for state in linked_nfa.states} == {"S", "é"}
    assert simulate(linked_nfa, "a").accepted is True
    assert simulate(linked_nfa, "").accepted is False

    # El terminal está escrito en NFD. En el AFN y en el .jff es la «é».
    same = RegularGrammar(
        terminals=(NFD_E, "a"),
        nonterminals=("S", "A"),
        start="S",
        productions=(
            Production("S", "a", "A"),
            Production("A", None, None),
            Production("S", NFD_E, None),
        ),
    )
    assert not validate_grammar(same)
    built = grammar_to_nfa(same)
    assert built.alphabet == ["é", "a"]
    assert NFD_E not in {state.id for state in built.states}
    assert simulate(built, "a").accepted is True
    assert simulate(built, "é").accepted is True
    assert simulate(built, NFD_E).accepted is True
    assert simulate(built, "aa").accepted is False
    exported = export_jflap_grammar(same)
    root = _strict_xml(exported)
    rights = [node.findtext("right") or "" for node in root.findall("production")]
    assert "aA" in rights
    assert "é" in rights
    assert NFD_E not in exported


def test_the_screen_quotes_the_bar_without_ollama_and_leaves_the_dfa():
    automaton = _fa(
        ["|", "a"],
        [State(id="q0", initial=True, final=True)],
        [
            Transition(from_state="q0", to="q0", read="|"),
            Transition(from_state="q0", to="q0", read="a"),
        ],
    )

    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("Armar la gramática no tiene que llamar a Ollama.")

    with TestClient(app) as client, patch("app.service.chat", fake_chat):
        session_id = client.post("/api/sessions").json()["id"]
        store.get(session_id).automaton = automaton
        before = store.get(session_id).automaton.model_dump()
        converted = client.post(f"/api/sessions/{session_id}/grammar")
        assert converted.status_code == 200
        body = converted.json()
        assert "«|»" in body["grammar"]["text"]
        assert store.get(session_id).automaton.model_dump() == before
        assert "pozo" not in {state["id"] for state in body["automaton"]["states"]}
        assert "pozo" not in body["grammar"]["text"]
        exported = client.get(f"/api/sessions/{session_id}/grammar/export")
        assert exported.status_code == 200
        root = _strict_xml(exported.text)
        rights = [node.findtext("right") or "" for node in root.findall("production")]
        assert "|S" in rights


def test_a_comma_name_is_one_state_in_the_drawing_and_the_table():
    payload = {
        "deterministic": True,
        "alphabet": ["a", "b"],
        "states": [
            {"id": "q0", "initial": True, "final": False},
            {"id": "q0, q1", "initial": False, "final": True},
            {"id": "q0 y q1", "initial": False, "final": False},
            {"id": "{q0,q1}", "initial": False, "final": False},
        ],
        "transitions": [
            {"from": "q0", "read": "a", "to": "q0, q1"},
            {"from": "q0", "read": "b", "to": "q0 y q1"},
            {"from": "q0, q1", "read": "a", "to": "q0, q1"},
            {"from": "{q0,q1}", "read": "a", "to": "{q0,q1}"},
        ],
    }
    diagram = _node_json("diagram_runner.js", payload)
    assert diagram["drawn"] is True
    summary = diagram["summary"]
    assert "va a «q0, q1»" in summary
    assert "va a q0, q1" not in summary
    assert "va a «q0 y q1»" in summary
    assert "vuelve a «q0, q1»" in summary
    assert "{q0,q1}" in summary
    assert "«{q0,q1}»" not in summary
    named = next(node for node in diagram["nodes"] if node["id"] == "q0, q1")
    assert named["accessibleName"] == "«q0, q1», final"
    braced = next(node for node in diagram["nodes"] if node["id"] == "{q0,q1}")
    assert braced["accessibleName"] == "{q0,q1}"

    table = _node_json("delta_runner.js", payload)
    row = next(item for item in table["rows"] if item["id"] == "q0, q1")
    assert row["spoken"] == "«q0, q1»"
    assert row["accessibleName"] == "«q0, q1», final"
    plain = next(item for item in table["rows"] if item["id"] == "q0")
    assert plain["accessibleName"] == "q0, inicial"
    assert plain["spoken"] == "q0"
    cell = next(item for item in plain["cells"] if item["symbol"] == "a")
    assert cell["text"] == "«q0, q1»"


def test_numeric_zero_is_a_state_in_the_drawing_and_the_table():
    payload = {
        "deterministic": False,
        "alphabet": ["a", "b"],
        "states": [
            {"id": 0, "initial": True, "final": True},
            {"id": "0", "initial": False, "final": False},
            {"id": "q1", "initial": False, "final": False},
        ],
        "transitions": [
            {"from": 0, "read": "a", "to": "q1"},
            {"from": "0", "read": "b", "to": 0},
            {"from": 0, "read": "", "to": "q1"},
        ],
    }
    diagram = _node_json("diagram_runner.js", payload)
    assert diagram["drawn"] is True
    assert diagram["total"] == 2
    assert [node["id"] for node in diagram["nodes"]] == ["0", "q1"]
    labels = {(edge["from"], edge["to"]): edge for edge in diagram["edges"]}
    assert labels[("0", "q1")]["label"] == "a, ε"
    assert labels[("0", "q1")]["epsilon"] is True
    assert labels[("0", "0")]["label"] == "b"
    assert labels[("0", "0")]["epsilon"] is False
    zero = next(node for node in diagram["nodes"] if node["id"] == "0")
    assert zero["initial"] is True and zero["final"] is True
    assert "0 es inicial y final" in diagram["summary"]

    table = _node_json("delta_runner.js", payload)
    assert [row["id"] for row in table["rows"]] == ["0", "q1"]
    zero_row = table["rows"][0]
    by_symbol = {cell["symbol"]: cell for cell in zero_row["cells"]}
    assert by_symbol["a"]["targets"] == ["q1"]
    assert by_symbol["b"]["targets"] == ["0"]
    assert by_symbol[""]["targets"] == ["q1"]
    assert by_symbol["a"]["text"] == "q1"
    assert by_symbol[""]["text"] == "q1"


def test_parity_grammar_text_stays_the_course_notation():
    grammar = dfa_to_grammar(EXAMPLES["paridad"].automaton)
    assert grammar.text() == "S → 0S | 1A | ε\nA → 0A | 1S"
