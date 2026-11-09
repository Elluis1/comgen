"""Ataques del 2026-10-20. No abre Ollama.

La cinta mezclaba una letra con acento y un jamo del alfabeto. La sesión
que se borraba en el medio era un 500. Un dígito arábigo-índico se leía
como cantidad. Una marca combinante se pegaba al texto de la pantalla.
"""

import json
import shutil
import subprocess
import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.familias import recognize_family
from app.interpret import ModelReplyError, interpret_text
from app.main import app
from app.sanitize import declared_alphabet
from app.simulate import simulate
from app.schemas import FiniteAutomaton, State, Transition
from app.store import store
from app.turing import (
    Configuration,
    TuringError,
    TuringMachine,
    TuringState,
    TuringTransition,
    run,
    start,
    step,
)

ROOT = Path(__file__).resolve().parents[1]
MARK = "\u0301"
LEAD = "\u1100"
VOWEL = "\u1161"
TRAIL = "\u11a8"
SYLLABLE = "\uac00"
SYLLABLE_T = "\uac01"
ARABIC_TWO = "\u0662"
FULLWIDTH_THREE = "\uff13"


def _edge(state: str, read: str, to: str, write: str, move: str) -> TuringTransition:
    return TuringTransition(state, read, to, write, move)


def _machine(alphabet: list[str], reads: list[str]) -> TuringMachine:
    names = [f"q{index}" for index in range(len(reads) + 1)]
    names[-1] = "qf"
    transitions = [
        _edge(names[index], symbol, names[index + 1], symbol, "R")
        for index, symbol in enumerate(reads)
    ]
    return TuringMachine(
        states=[TuringState(name, initial=index == 0, final=name == "qf") for index, name in enumerate(names)],
        tape_alphabet=[*alphabet, "_"],
        blank="_",
        transitions=transitions,
    )


def _node(script: str, payload: dict) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede mirar la pantalla.")
    completed = subprocess.run(
        [node, str(ROOT / "tests" / script)],
        input=json.dumps(payload),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(completed.stdout)


def _node_arg(script: str, payload: dict) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede mirar la pantalla.")
    completed = subprocess.run(
        [node, str(ROOT / "tests" / script), json.dumps(payload)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(completed.stdout)


def test_the_tape_composes_a_letter_beside_a_jamo_and_does_not_split_a_syllable():
    assert unicodedata.normalize("NFC", "e" + MARK) == "é"
    assert unicodedata.normalize("NFC", LEAD + VOWEL) == SYLLABLE
    assert unicodedata.normalize("NFC", LEAD + VOWEL + TRAIL) == SYLLABLE_T

    mixed = _machine(["é", LEAD, VOWEL], ["é", LEAD, VOWEL])
    word = "e" + MARK + LEAD + VOWEL
    result = run(mixed, word)
    assert result.status == "accept"
    assert result.tape[:3] == ("é", LEAD, VOWEL)
    assert result.message.startswith("Acepta")
    with pytest.raises(TuringError) as exc:
        run(mixed, "a")
    assert "no está en el alfabeto" in str(exc.value)
    assert mixed.tape_alphabet[0] == "é"

    partial = _machine([SYLLABLE, TRAIL], [SYLLABLE, TRAIL])
    partial_run = run(partial, LEAD + VOWEL + TRAIL)
    assert partial_run.status == "accept"
    assert partial_run.tape[:2] == (SYLLABLE, TRAIL)

    pieces = _machine([LEAD, VOWEL], [LEAD])
    with pytest.raises(TuringError) as exc:
        run(pieces, SYLLABLE)
    assert "no está en el alfabeto" in str(exc.value)
    assert not isinstance(exc.value, IndexError)

    kept = _machine(["e", MARK], ["e", MARK])
    apart = run(kept, "e" + MARK)
    assert apart.status == "accept"
    assert apart.tape[:2] == ("e", MARK)


def test_an_external_tape_is_not_joined_and_a_composed_blank_is_rejected():
    machine = _machine(["e", MARK], ["e", MARK])
    moved = step(machine, Configuration("q0", ("e", MARK), 0, "running"))
    assert moved.status == "running"
    assert moved.tape[:2] == ("e", MARK)
    assert "é" not in moved.tape

    blank = TuringMachine(
        states=[TuringState("q0", initial=True, final=True)],
        tape_alphabet=["é", "a", "_"],
        blank="é",
        transitions=[],
    )
    with pytest.raises(TuringError) as exc:
        run(blank, "e" + MARK)
    assert "blanco" in str(exc.value)


def test_moving_left_on_a_full_tape_stops_in_spanish():
    machine = TuringMachine(
        states=[TuringState("q0", initial=True)],
        tape_alphabet=["a", "_"],
        blank="_",
        transitions=[
            _edge("q0", "a", "q0", "a", "L"),
            _edge("q0", "_", "q0", "_", "L"),
        ],
    )
    result = run(machine, "a", max_cells=1)
    assert result.status == "timeout"
    assert result.accepted is None
    assert result.tape == ("a",)
    assert result.head == 0
    assert result.steps_run == 0
    assert result.message == "No terminó: la cinta llegó a 1 celdas."

    final = TuringMachine(
        states=[TuringState("q0", initial=True, final=True)],
        tape_alphabet=["a", "_"],
        blank="_",
        transitions=[],
    )
    halted = step(final, start(final, "a", max_cells=1), max_cells=1)
    assert halted.status == "accept"
    assert "no terminó" not in halted.message.casefold()
    assert halted.tape == ("a",)


def test_arabic_indic_digits_are_not_a_count_and_fullwidth_still_are():
    arabic = recognize_family(f"números en base 10 divisibles por {ARABIC_TWO}")
    assert arabic is None
    position = recognize_family(f"el {ARABIC_TWO}° símbolo es 1 sobre {{0, 1}}")
    assert position is None
    sequence = recognize_family(
        f"sobre {{0, 1}} continúa con infinitos 1, {ARABIC_TWO} 0 y un 0"
    )
    assert sequence is not None and sequence.automaton is None
    assert sequence.errors
    assert "No entiendo el número" in sequence.errors[0]
    assert ARABIC_TWO in sequence.errors[0]

    full = recognize_family(f"números en base 10 divisibles por {FULLWIDTH_THREE}")
    assert full is not None and full.automaton is not None
    assert len(full.automaton.states) == 3
    assert simulate(full.automaton, "6").accepted is True
    assert simulate(full.automaton, "1").accepted is False

    third = recognize_family(f"el {FULLWIDTH_THREE}° símbolo es 1 sobre {{0, 1}}")
    assert third is not None and third.automaton is not None
    assert simulate(third.automaton, "111").accepted is True
    assert simulate(third.automaton, "110").accepted is False

    blocks = recognize_family(
        f"sobre {{0, 1}} continúa con infinitos 1, {FULLWIDTH_THREE} 0 y un 0"
    )
    assert blocks is not None and blocks.automaton is not None
    assert simulate(blocks.automaton, "10000").accepted is True
    assert simulate(blocks.automaton, "1000").accepted is False

    declared = declared_alphabet(f"sobre {{{ARABIC_TWO}, 0}}")
    assert declared == [ARABIC_TWO, "0"]

    raw = json.dumps(
        {
            "kind": "spec",
            "family": "secuencia",
            "alphabet": ["0", "1"],
            "blocks": [{"symbol": "0", "repeat": ARABIC_TWO}],
            "description": "secuencia",
        }
    )
    with pytest.raises(ModelReplyError) as exc:
        interpret_text(raw, "secuencia de bloques")
    assert "No entiendo el número" in str(exc.value)


def test_a_session_that_vanishes_mid_request_is_a_404():
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        loaded = client.post(f"/api/sessions/{session_id}/examples/paridad")
        assert loaded.status_code == 200
        alive = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "11"})
        assert alive.status_code == 200
        assert alive.json()["accepted"] is True

        real_get = store.get

        def get_then_drop(key: str):
            session = real_get(key)
            with store._registry:
                store._sessions.pop(key, None)
                store._locks.pop(key, None)
                store._guards.pop(key, None)
            return session

        store.get = get_then_drop
        try:
            calls = [
                ("post", f"/api/sessions/{session_id}/simulate", {"json": {"word": "0"}}),
                ("post", f"/api/sessions/{session_id}/regex", {}),
                ("post", f"/api/sessions/{session_id}/grammar", {}),
                ("post", f"/api/sessions/{session_id}/determinize", {}),
                ("post", f"/api/sessions/{session_id}/reset", {}),
                ("post", f"/api/sessions/{session_id}/remember", {}),
                ("post", f"/api/sessions/{session_id}/messages", {"json": {"text": "par de unos"}}),
                ("get", f"/api/sessions/{session_id}/export", {}),
                ("get", f"/api/sessions/{session_id}/grammar/export", {}),
            ]
            for method, path, kwargs in calls:
                response = getattr(client, method)(path, **kwargs)
                assert response.status_code == 404, path
                assert "Recargá" in response.json()["detail"]
        finally:
            store.get = real_get


def test_a_combining_mark_is_quoted_on_the_screen_and_zero_stays_a_symbol():
    mark = MARK
    automaton = {
        "deterministic": True,
        "alphabet": ["0", mark],
        "states": [
            {"id": "0", "initial": True, "final": True},
            {"id": mark, "initial": False, "final": False},
        ],
        "transitions": [
            {"from": "0", "to": "0", "read": "0"},
            {"from": "0", "to": mark, "read": mark},
        ],
    }
    result = {
        "ok": True,
        "accepted": True,
        "message": "Acepta",
        "steps": [
            {"symbol": "", "states": ["0"]},
            {"symbol": mark, "states": ["0"]},
            {"symbol": "0", "states": [0]},
        ],
    }
    trace = _node_arg("trace_runner.js", {"result": result, "automaton": automaton})
    assert trace["steps"][1]["text"].startswith("Lee «")
    assert mark in trace["steps"][1]["text"]
    assert not trace["steps"][1]["text"].startswith("Lee " + mark)
    assert trace["steps"][2]["text"].startswith("Lee 0")
    assert "«" + mark not in trace["steps"][0]["text"]

    play = _node_arg("playback_runner.js", {"result": result, "automaton": automaton})
    assert play["frames"][1]["text"].startswith("Lee «")
    assert mark in play["frames"][1]["text"]
    assert not play["frames"][1]["text"].startswith("Lee " + mark)
    assert any(frame["text"].startswith("Lee 0") for frame in play["frames"])
    assert play["frames"][0]["text"].startswith("Empieza en 0")

    hint = _node_arg("word_hint_runner.js", {"fn": "alphabetHint", "args": [["0", mark, "a"]]})
    assert hint.startswith("Alfabeto {0, «")
    assert mark in hint
    assert "«0»" not in hint
    label = _node_arg("word_hint_runner.js", {"fn": "probeLabel", "args": [mark]})
    assert label.startswith("«") and mark in label
    assert _node_arg("word_hint_runner.js", {"fn": "probeLabel", "args": ["0"]}) == "0"

    table = _node("delta_runner.js", {"automaton": automaton})
    columns = {column["id"]: column["label"] for column in table["columns"]}
    assert columns["0"] == "0"
    assert columns[mark].startswith("«")
    assert mark in columns[mark]
    spoken = table["rows"][0]["spoken"]
    assert spoken == "0" or spoken.startswith("«")

    drawing = _node_arg("diagram_runner.js", automaton)
    labels = [edge["label"] for edge in drawing["edges"]]
    assert any(label.startswith("«") and mark in label for label in labels)
    assert any(label == "0" for label in labels)
    assert "«" + mark in drawing["summary"]
    assert "con " + mark not in drawing["summary"].casefold()
