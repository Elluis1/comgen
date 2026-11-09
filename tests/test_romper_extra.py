"""Ataques de la corrida Romper del 2026-10-17. No usan Ollama."""

import threading
import time
import xml.etree.ElementTree as ET
from unittest.mock import patch
from xml.parsers.expat import ParserCreate

import pytest
from fastapi.testclient import TestClient

from app.determinize import MAX_SUBSETS, DeterminizeError, nfa_to_dfa
from app.examples import EXAMPLES
from app.export_jflap import export_jflap
from app.main import app
from app.memory import MemoryStoreError, save
from app.regex_from_fa import MAX_STATES, RegexFromFaError, fa_to_regex
from app.regex_lang import compile_pattern
from app.sanitize import is_epsilon_symbol, xml_char_allowed
from app.schemas import FiniteAutomaton, State, Transition
from app.service import regex_session
from app.simulate import simulate
from app.store import MAX_SESSIONS, store
from app.validate import prepare_fa


MARK = "\u0301"
STAR_OP = "\u2217"  # ∗ operador, el compilador lo pliega a *
STAR_LOOK = "\u22c6"  # ⋆
FULLWIDTH_STAR = "\uff0a"  # ＊ no se pliega
OPEN_E = "\u025b"  # ɛ
UKRAINIAN_E = "\u0454"  # є


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


def _agree(original, pattern, words):
    compiled, _explanation = compile_pattern(pattern)
    for word in words:
        left = simulate(original, word)
        right = simulate(compiled, word)
        assert left.ok and right.ok, (pattern, word, left.message, right.message)
        assert left.accepted is right.accepted, (pattern, word, left.accepted, right.accepted)


def _same_acceptance(original, pattern, words):
    """Aceptar tiene que coincidir. Un símbolo que la expresión no nombra rechaza."""
    compiled, _explanation = compile_pattern(pattern)
    for word in words:
        left = bool(simulate(original, word).ok and simulate(original, word).accepted)
        right = bool(simulate(compiled, word).ok and simulate(compiled, word).accepted)
        assert left is right, (pattern, word, left, right)


def test_a_combining_mark_in_the_alphabet_is_not_eaten_by_nfc():
    automaton = _fa(
        ["a", MARK, "é"],
        [State(id="q0", initial=True, final=True)],
        [
            Transition(from_state="q0", to="q0", read="a"),
            Transition(from_state="q0", to="q0", read=MARK),
            Transition(from_state="q0", to="q0", read="é"),
        ],
    )
    word = "a" + MARK + "a"
    result = simulate(automaton, word)
    assert result.ok and result.accepted is True
    assert [step.symbol for step in result.steps] == ["", "a", MARK, "a"]
    assert "á" not in result.message
    alone = simulate(automaton, MARK + MARK)
    assert alone.ok and alone.accepted is True
    precomposed = simulate(automaton, "á")
    assert precomposed.ok is False
    assert "á" in precomposed.message

    accented, _explanation = compile_pattern("é*")
    assert simulate(accented, "e" + MARK + "e" + MARK).accepted is True
    assert simulate(accented, "éé").accepted is True

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        store.get(session_id).automaton = automaton
        accepted = client.post(
            f"/api/sessions/{session_id}/simulate",
            json={"word": word},
        )
        assert accepted.status_code == 200
        assert accepted.json()["accepted"] is True
        assert [step["symbol"] for step in accepted.json()["steps"]] == ["", "a", MARK, "a"]


def test_folded_stars_do_not_change_the_language_and_other_lookalikes_stay():
    for symbol in (STAR_OP, STAR_LOOK, "*", "|", "(", "+", "?", ")", "[", "]", "{", "}", "\\"):
        automaton = _fa(
            ["b", symbol],
            [
                State(id="q0", initial=True, final=False),
                State(id="q1", initial=False, final=True),
            ],
            [
                Transition(from_state="q0", to="q1", read="b"),
                Transition(from_state="q1", to="q1", read=symbol),
            ],
        )
        before = automaton.model_dump()
        with pytest.raises(RegexFromFaError) as exc:
            fa_to_regex(automaton)
        assert "escapes" in str(exc.value)
        assert automaton.model_dump() == before

    literal = _fa(
        [FULLWIDTH_STAR],
        [
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
        ],
        [Transition(from_state="q0", to="q1", read=FULLWIDTH_STAR)],
    )
    pattern = fa_to_regex(literal)
    assert pattern == FULLWIDTH_STAR
    _agree(literal, pattern, ["", FULLWIDTH_STAR, FULLWIDTH_STAR * 2])


def test_open_e_and_ukrainian_e_stay_symbols_in_the_expression():
    for symbol in (OPEN_E, UKRAINIAN_E):
        assert is_epsilon_symbol(symbol) is False
        automaton = _fa(
            [symbol],
            [
                State(id="q0", initial=True, final=False),
                State(id="q1", initial=False, final=True),
            ],
            [Transition(from_state="q0", to="q1", read=symbol)],
        )
        pattern = fa_to_regex(automaton)
        assert pattern == symbol
        assert simulate(automaton, "").accepted is False
        assert simulate(automaton, symbol).accepted is True
        _agree(automaton, pattern, ["", symbol])


def test_space_and_control_in_a_transition_are_spanish_errors():
    for symbol, needle in ((" ", "espacio"), ("\x08", "control"), ("\u200b", "control")):
        automaton = _fa(
            [symbol],
            [State(id="q0", initial=True, final=True)],
            [Transition(from_state="q0", to="q0", read=symbol)],
        )
        with pytest.raises(RegexFromFaError) as exc:
            fa_to_regex(automaton)
        assert needle in str(exc.value)
        if symbol == " ":
            prepared, _notes = prepare_fa(automaton)
            assert prepared.alphabet == [" "]
            assert prepared.transitions[0].read == " "
            assert simulate(prepared, " ").accepted is True
            assert simulate(prepared, "").accepted is True


def test_sixteen_states_convert_and_seventeen_stops():
    assert MAX_STATES == 16

    def chain(count):
        return _fa(
            ["a"],
            [State(id=f"q{index}", initial=index == 0, final=index == count - 1) for index in range(count)],
            [Transition(from_state=f"q{index}", to=f"q{index + 1}", read="a") for index in range(count - 1)],
        )

    fifteen = chain(16)
    before = fifteen.model_dump()
    started = time.perf_counter()
    pattern = fa_to_regex(fifteen)
    assert time.perf_counter() - started < 1
    assert pattern == "a" * 15
    assert fifteen.model_dump() == before
    assert "pozo" not in {state.id for state in fifteen.states}
    _agree(fifteen, pattern, ["a" * 14, "a" * 15, "a" * 16, ""])

    copies = _fa(
        ["a"],
        [State(id=f"q{index}", initial=index == 0, final=True) for index in range(16)],
        [
            Transition(from_state=f"q{index}", to=f"q{index}", read="a")
            for index in range(16)
        ],
    )
    assert fa_to_regex(copies) == "a*"

    seventeen = chain(17)
    started = time.perf_counter()
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(seventeen)
    assert time.perf_counter() - started < 0.5
    assert "17" in str(exc.value)
    assert "trabar" in str(exc.value)


def test_only_the_empty_word_with_a_dead_end_has_no_expression():
    automaton = _fa(
        ["a"],
        [
            State(id="q0", initial=True, final=True),
            State(id="q1", initial=False, final=False),
        ],
        [
            Transition(from_state="q0", to="q1", read="a"),
            Transition(from_state="q1", to="q1", read="a"),
        ],
    )
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(automaton)
    assert "vacía" in str(exc.value)


def test_a_partial_dfa_keeps_rejecting_and_the_sink_stays_out_of_the_session():
    partial = _fa(
        ["0", "1"],
        [State(id="q0", initial=True, final=True)],
        [Transition(from_state="q0", to="q0", read="0")],
        description="parcial \u202e con flecha",
    )
    before = partial.model_dump()
    pattern = fa_to_regex(partial)
    assert partial.model_dump() == before
    assert "pozo" not in pattern
    _agree(partial, pattern, ["", "0", "00", "000"])
    compiled, _explanation = compile_pattern(pattern)
    assert simulate(compiled, "1").accepted is not True
    assert simulate(compiled, "01").accepted is not True
    assert simulate(partial, "1").accepted is False

    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("La expresión no llama a Ollama.")

    with TestClient(app) as client:
        with patch("app.service.chat", fake_chat):
            session_id = client.post("/api/sessions").json()["id"]
            store.get(session_id).automaton = partial.model_copy(deep=True)
            converted = client.post(f"/api/sessions/{session_id}/regex")
            assert converted.status_code == 200
            body = converted.json()
            assert body["pattern"]
            assert "pozo" not in {state["id"] for state in body["automaton"]["states"]}
            assert [item["read"] for item in body["automaton"]["transitions"]] == ["0"]
            exported = client.get(f"/api/sessions/{session_id}/export")
            assert exported.status_code == 200
            assert "\n" not in exported.headers["content-disposition"]
            assert "\r" not in exported.headers["content-disposition"]
            root = _strict_xml(exported.text)
            names = {state.get("name") for state in root.findall("./automaton/state")}
            assert "pozo" in names
            assert store.get(session_id).automaton is not None
            assert "pozo" not in {state.id for state in store.get(session_id).automaton.states}
            assert simulate(store.get(session_id).automaton, "1").accepted is False


def test_another_epsilon_cycle_asks_to_determinize_and_then_matches():
    cycle = _fa(
        ["b", "c"],
        [
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=False),
            State(id="q2", initial=False, final=True),
            State(id="fuera", initial=False, final=False),
        ],
        [
            Transition(from_state="q0", to="q1", read="ε"),
            Transition(from_state="q1", to="q2", read="λ"),
            Transition(from_state="q2", to="q0", read="ϵ"),
            Transition(from_state="q1", to="q1", read="c"),
            Transition(from_state="q0", to="fuera", read="b"),
        ],
        deterministic=False,
        description="ciclo distinto de a*",
    )
    with pytest.raises(RegexFromFaError) as exc:
        fa_to_regex(cycle)
    assert "determinizar" in str(exc.value)

    started = time.perf_counter()
    dfa = nfa_to_dfa(cycle).automaton
    assert time.perf_counter() - started < 1
    assert dfa.deterministic is True
    assert all(transition.read for transition in dfa.transitions)
    assert all(state.id not in {"{}", ""} for state in dfa.states)
    for word in ("", "c", "cc", "ccc"):
        assert simulate(cycle, word).accepted is True
        assert simulate(dfa, word).accepted is True
    for word in ("b", "cb", "a"):
        assert simulate(cycle, word).accepted is False
        assert simulate(dfa, word).accepted is False
    pattern = fa_to_regex(dfa)
    _same_acceptance(dfa, pattern, ["", "c", "cc", "ccc", "b", "cb"])
    assert "pozo" not in {state.id for state in dfa.states}


def test_exactly_512_subsets_fit_and_the_next_one_does_not():
    assert MAX_SUBSETS == 512

    def nth_from_the_end(n):
        states = [State(id=f"q{index}", initial=index == 0, final=index == n) for index in range(n + 1)]
        transitions = [
            Transition(from_state="q0", to="q0", read="0"),
            Transition(from_state="q0", to="q0", read="1"),
            Transition(from_state="q0", to="q1", read="1"),
        ]
        for index in range(1, n):
            transitions.append(Transition(from_state=f"q{index}", to=f"q{index + 1}", read="0"))
            transitions.append(Transition(from_state=f"q{index}", to=f"q{index + 1}", read="1"))
        return _fa(["0", "1"], states, transitions, deterministic=False)

    started = time.perf_counter()
    fitted = nfa_to_dfa(nth_from_the_end(9)).automaton
    assert time.perf_counter() - started < 1
    assert len(fitted.states) == 512
    assert simulate(fitted, "1" + "0" * 8).accepted is True
    assert simulate(fitted, "0" * 9).accepted is False

    started = time.perf_counter()
    with pytest.raises(DeterminizeError) as exc:
        nfa_to_dfa(nth_from_the_end(10))
    assert time.perf_counter() - started < 1
    assert "512" in str(exc.value)
    assert "trabar" in str(exc.value)


def test_concurrent_regex_on_one_session_does_not_touch_the_automaton():
    session = store.create()
    session.automaton = EXAMPLES["paridad"].automaton.model_copy(deep=True)
    before = session.automaton.model_dump()
    errors: list[BaseException] = []
    patterns: list[str] = []

    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("Sacar la expresión no tiene que llamar a Ollama.")

    def once() -> None:
        try:
            with patch("app.service.chat", fake_chat):
                body = regex_session(session.id)
            patterns.append(body["pattern"])
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=once) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(patterns) == 8
    assert len(set(patterns)) == 1
    assert session.automaton is not None
    assert session.automaton.model_dump() == before
    assert "pozo" not in {state.id for state in session.automaton.states}
    _agree(session.automaton, patterns[0], ["", "0", "1", "11", "10"])


def test_a_chain_of_399_as_is_not_merged_away():
    started = time.perf_counter()
    automaton, _explanation = compile_pattern("a" * 399)
    assert time.perf_counter() - started < 0.2
    assert len(automaton.states) == 401
    assert simulate(automaton, "a" * 399).accepted is True
    assert simulate(automaton, "a" * 398).accepted is False
    assert simulate(automaton, "a" * 400).accepted is False
    assert simulate(automaton, "").accepted is False


def test_roundtrip_of_a_hostile_jff_keeps_the_language():
    smile = "😀"
    names = ["q0", "{q0,q1}", 'a"b', "a&b<c", smile]
    automaton = _fa(
        ["a", "&", "<", '"', smile],
        [
            State(id="q0", initial=True, final=False),
            State(id="{q0,q1}", initial=False, final=True),
            State(id='a"b', initial=False, final=False),
            State(id="a&b<c", initial=False, final=False),
            State(id=smile, initial=False, final=True),
        ],
        [
            Transition(from_state="q0", to="{q0,q1}", read="a"),
            Transition(from_state="q0", to='a"b', read="&"),
            Transition(from_state="q0", to="a&b<c", read="<"),
            Transition(from_state="q0", to=smile, read='"'),
            Transition(from_state="q0", to=smile, read=smile),
        ],
        description='Expresión --> rara \u202e😀 "con" salto\r\n',
    )
    xml = export_jflap(automaton)
    root = _strict_xml(xml)
    comment = xml.split("<!--", 1)[1].split("-->", 1)[0]
    assert "-->" not in comment
    assert "😀" in xml
    back = _automaton_from_jff(root)
    for word in ("a", "&", "<", '"', smile, "", "aa", "a&"):
        assert simulate(automaton, word).accepted is simulate(back, word).accepted

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        store.get(session_id).automaton = automaton
        exported = client.get(f"/api/sessions/{session_id}/export")
        assert exported.status_code == 200
        disposition = exported.headers["content-disposition"]
        assert "\n" not in disposition
        assert "\r" not in disposition
        assert disposition.count('"') == 2
        _strict_xml(exported.text)


def test_when_every_session_has_an_automaton_the_oldest_goes(monkeypatch):
    assert MAX_SESSIONS == 128
    monkeypatch.setattr("app.store.MAX_SESSIONS", 3)
    with store._registry:
        store._sessions.clear()
        store._locks.clear()
        store._guards.clear()
    with TestClient(app) as client:
        kept_ids = []
        for _ in range(3):
            session_id = client.post("/api/sessions").json()["id"]
            loaded = client.post(f"/api/sessions/{session_id}/examples/paridad")
            assert loaded.status_code == 200
            kept_ids.append(session_id)
        newest = client.post("/api/sessions").json()["id"]
        assert client.post(f"/api/sessions/{newest}/examples/termina-en-01").status_code == 200
        gone = client.post(f"/api/sessions/{kept_ids[0]}/simulate", json={"word": "11"})
        assert gone.status_code == 404
        assert "Recargá" in gone.json()["detail"]
        still = client.post(f"/api/sessions/{kept_ids[-1]}/simulate", json={"word": "11"})
        assert still.status_code == 200
        assert still.json()["accepted"] is True
        assert store.get(newest).automaton is not None


def test_deeply_nested_memory_is_damaged_and_not_overwritten(tmp_path):
    path = tmp_path / "solutions.json"
    path.write_text('{"solutions": ' + ("[" * 10000) + "1" + ("]" * 10000) + "}", encoding="utf-8")
    before = path.read_bytes()
    with TestClient(app) as client:
        listed = client.get("/api/memory")
    assert listed.status_code == 200
    assert listed.json()["count"] == 0
    with pytest.raises(MemoryStoreError, match="dañada"):
        save("paridad de unos sobre el alfabeto", "texto", {"kind": "fa", "alphabet": ["0", "1"]})
    assert path.read_bytes() == before


def test_nan_and_a_wrong_typed_body_do_not_crash(monkeypatch):
    async def fake_chat(*_args, **_kwargs):
        return '{"kind":"fa","explanation": NaN, "alphabet": ["z"], "states": "no", "transitions": 5}'

    monkeypatch.setattr("app.service.chat", fake_chat)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        answered = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "zeta del apunte, sin una familia del curso"},
        )
        assert answered.status_code == 200
        body = answered.json()
        assert body["errors"]
        assert "No pude armar" in body["messages"][-1]["content"]
        weird = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": ["no es texto"]},
        )
        assert weird.status_code == 422


def _automaton_from_jff(root: ET.Element) -> FiniteAutomaton:
    names: dict[str, str] = {}
    states: list[State] = []
    for node in root.findall("./automaton/state"):
        state_id = node.get("id") or ""
        name = node.get("name") or ""
        names[state_id] = name
        states.append(
            State(
                id=name,
                initial=node.find("initial") is not None,
                final=node.find("final") is not None,
            )
        )
    transitions: list[Transition] = []
    alphabet: list[str] = []
    for node in root.findall("./automaton/transition"):
        read = node.findtext("read") or ""
        transitions.append(
            Transition(
                from_state=names[node.findtext("from") or ""],
                to=names[node.findtext("to") or ""],
                read=read,
            )
        )
        if read and read not in alphabet:
            alphabet.append(read)
    deterministic = True
    seen: set[tuple[str, str]] = set()
    for transition in transitions:
        if not transition.read or (transition.from_state, transition.read) in seen:
            deterministic = False
            break
        seen.add((transition.from_state, transition.read))
    return FiniteAutomaton(
        deterministic=deterministic,
        alphabet=alphabet,
        states=states,
        transitions=transitions,
        description="vuelta",
    )
