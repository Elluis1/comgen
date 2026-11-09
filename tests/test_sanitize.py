import json
import xml.etree.ElementTree as ET
from unittest.mock import patch
from xml.parsers.expat import ExpatError, ParserCreate

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.export_jflap import export_jflap
from app.interpret import ModelReplyError, interpret_text
from app.main import app
from app.regex_lang import RegexError, compile_pattern
from app.sanitize import declared_alphabet, xml_char_allowed
from app.schemas import FiniteAutomaton, State, Transition
from app.store import store

# Lo que devolvió gemma3:1b: un backspace adelante (no se ve) y una barra al final.
BUG_PATTERN = "\x08(0|1)\\"
STATEMENT = "un AFD sobre {0, 1} que acepte los números binarios divisibles por 5"
# El enunciado de arriba se arma en código y no llega al modelo.
# Este declara el mismo alfabeto y sí pasa por el saneo.
MODEL_STATEMENT = "un AFD sobre {0, 1} para el dibujo del apunte"


def assert_strict_xml(document: str) -> ET.Element:
    """Expat es el parser estricto: rechaza U+0008 y cualquier Char ilegal de XML 1.0."""
    for char in document:
        assert xml_char_allowed(char), hex(ord(char))
    parser = ParserCreate(encoding="UTF-8")
    parser.Parse(document.encode("utf-8"), True)
    return ET.fromstring(document.encode("utf-8"))


def test_export_strips_controls_and_parses_with_expat():
    poisoned = FiniteAutomaton(
        description="Expresión \x00\x08(0|1)\\\x1f -- con\ufffe\ud800 control",
        alphabet=["0", "\x08", "\x0b"],
        states=[
            State(id="q0\x08", initial=True, final=True),
            State(id="\x08", initial=False, final=False),
        ],
        transitions=[
            Transition(from_state="q0\x08", to="q0\x08", read="0"),
            Transition(from_state="q0\x08", to="\x08", read="\x08"),
            Transition(from_state="\x08", to="\x08", read="\x0b"),
            Transition(from_state="\x08", to="q0\x08", read="1\x00"),
        ],
    )
    xml = export_jflap(poisoned)
    root = assert_strict_xml(xml)
    assert root.findtext("type") == "fa"
    comment = xml.split("<!--", 1)[1].split("-->", 1)[0]
    assert "\x08" not in comment
    assert "\x00" not in comment
    assert "--" not in comment
    assert "Expresión" in comment
    names = [state.get("name") for state in root.findall("./automaton/state")]
    assert names == ["q0", "q1"]
    assert all("\x08" not in (name or "") for name in names)
    reads = [node.text for node in root.findall("./automaton/transition/read")]
    assert reads == ["0", None, None, "1"]
    assert all(read is None or "\x08" not in read for read in reads)
    bad = '<?xml version="1.0"?><structure><!-- \x08 --></structure>'
    with pytest.raises(ExpatError):
        ParserCreate(encoding="UTF-8").Parse(bad.encode("utf-8"), True)


def test_downloaded_jff_with_a_control_in_the_comment_parses():
    poisoned = EXAMPLES["paridad"].automaton.model_copy(
        update={"description": "Paridad\x08 -- binaria\x00"}
    )
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        store.get(session_id).automaton = poisoned
        exported = client.get(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 200
    root = assert_strict_xml(exported.text)
    comment = exported.text.split("<!--", 1)[1].split("-->", 1)[0]
    assert "\x08" not in exported.text
    assert "\x00" not in exported.text
    assert "--" not in comment
    assert "Paridad" in comment
    assert root.findtext("type") == "fa"


def test_dangling_backslash_and_controls_are_not_compiled():
    dangling = "(0|1)\\"  # (0|1)\
    middle = "a\\b"  # a\b
    only = "\\"  # \
    for pattern in (dangling, middle, only, BUG_PATTERN, "(\x08"):
        with pytest.raises(RegexError):
            compile_pattern(pattern)
    automaton, _explanation = compile_pattern("(0|1)*")
    assert automaton.alphabet == ["0", "1"]


def test_model_expression_with_backspace_is_rejected():
    raw = json.dumps(
        {
            "kind": "regex",
            "pattern": BUG_PATTERN,
            "description": "Divisibles\x08 por 5",
            "explanation": "q1: Lee la \x08.",
            "alphabet": ["\x08", "0", "1", "\\"],
            "states": [],
            "transitions": [],
        }
    )
    with pytest.raises(ModelReplyError) as caught:
        interpret_text(raw, STATEMENT)
    text = " ".join(caught.value.errors)
    assert "control" in text
    assert "barra invertida" in text
    assert "{0, 1}" in text
    assert "«\\»" in text or "vacío" in text


def test_control_in_prose_is_removed_and_the_automaton_still_exports():
    parity = EXAMPLES["paridad"].automaton
    raw = parity.model_dump_json(by_alias=True)
    data = json.loads(raw)
    data["pattern"] = ""
    data["description"] = "Paridad\x08 de unos"
    data["explanation"] = "q0 es par.\u200b\nSigue siendo par."
    parsed = interpret_text(json.dumps(data))
    assert parsed.export_ready
    assert parsed.automaton is not None
    assert "\x08" not in parsed.automaton.description
    assert "\u200b" not in parsed.explanation
    assert "\n" in parsed.explanation
    assert_strict_xml(export_jflap(parsed.automaton))


def test_empty_invisible_and_backslash_symbols_are_rejected():
    base = {
        "kind": "fa",
        "pattern": "",
        "description": "mal",
        "explanation": "mal",
        "deterministic": True,
        "states": [{"id": "q0", "initial": True, "final": True}],
        "transitions": [
            {"from": "q0", "to": "q0", "read": "0"},
            {"from": "q0", "to": "q0", "read": "1"},
        ],
    }
    empty = {**base, "alphabet": ["", "0", "1"]}
    with pytest.raises(ModelReplyError, match="vacío"):
        interpret_text(json.dumps(empty), STATEMENT)

    invisible = {**base, "alphabet": ["\u200b", "0", "1"]}
    with pytest.raises(ModelReplyError, match="invisible"):
        interpret_text(json.dumps(invisible))

    backslash = {
        **base,
        "alphabet": ["0", "1", "\\"],
        "transitions": base["transitions"]
        + [{"from": "q0", "to": "q0", "read": "\\"}],
    }
    with pytest.raises(ModelReplyError, match=r"\{0, 1\}") as caught:
        interpret_text(json.dumps(backslash), STATEMENT)
    assert "«\\»" in " ".join(caught.value.errors)

    named = {**base, "alphabet": ["0", "1"], "states": [{"id": "q0\x08", "initial": True, "final": True}]}
    with pytest.raises(ModelReplyError, match="estado"):
        interpret_text(json.dumps(named))


def test_result_alphabet_can_be_a_subset_of_the_statement():
    parity = EXAMPLES["paridad"].automaton
    raw = json.loads(parity.model_dump_json(by_alias=True))
    raw["pattern"] = ""
    parsed = interpret_text(json.dumps(raw), STATEMENT)
    assert parsed.export_ready
    assert parsed.automaton is not None
    assert set(parsed.automaton.alphabet) <= {"0", "1"}


def test_declared_alphabet_reads_the_statement_and_ignores_a_bare_modulus():
    assert declared_alphabet(STATEMENT) == ["0", "1"]
    assert declared_alphabet("un AFD sobre {a, b} que acepte cadenas que terminan en ab") == ["a", "b"]
    assert declared_alphabet("alfabeto {0,1}") == ["0", "1"]
    assert declared_alphabet("cadenas binarias con cantidad par de unos") is None
    assert declared_alphabet("números divisibles por {5}") is None


def test_luigi_attack_is_rejected_and_nothing_is_exported():
    calls = {"n": 0}

    async def fake_chat(_settings, _messages):
        calls["n"] += 1
        return json.dumps(
            {
                "kind": "regex",
                "pattern": BUG_PATTERN,
                "description": "Números binarios",
                "explanation": "q1: Lee la .",
                "deterministic": True,
                "alphabet": ["\x08", "0", "1", "\\"],
                "states": [],
                "transitions": [],
            }
        )

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": MODEL_STATEMENT},
            )
        body = response.json()
        assert calls["n"] == 2
        assert body["export_ready"] is False
        assert body["automaton"] is None
        text = " ".join(body["errors"]) + "\n" + body["messages"][-1]["content"]
        assert "barra invertida" in text
        assert "{0, 1}" in text
        assert "\x08" not in text
        exported = client.get(f"/api/sessions/{session_id}/export")
        assert exported.status_code == 409


def test_repair_accepts_a_later_automaton_inside_the_declared_alphabet():
    calls = {"n": 0}
    parity = json.loads(EXAMPLES["paridad"].automaton.model_dump_json(by_alias=True))
    parity["pattern"] = ""

    async def fake_chat(_settings, _messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps(
                {
                    "kind": "regex",
                    "pattern": "(0|1)\\",
                    "description": "todo",
                    "explanation": "",
                    "alphabet": [],
                    "states": [],
                    "transitions": [],
                }
            )
        return json.dumps(parity)

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": MODEL_STATEMENT},
            )
        body = response.json()
        assert calls["n"] == 2
        assert body["export_ready"] is True
        assert body["automaton"]["alphabet"] == ["0", "1"]
        exported = client.get(f"/api/sessions/{session_id}/export")
        assert exported.status_code == 200
        assert_strict_xml(exported.text)


def test_unclosed_parenthesis_is_rejected():
    with pytest.raises(RegexError):
        compile_pattern("(0|1")


def test_extra_symbol_does_not_also_blame_a_declared_one():
    """gemma3:1b mezcló «a» con el alfabeto {0, 1} y una transición con 0."""
    raw = {
        "kind": "fa",
        "pattern": "1*",
        "description": "mal",
        "explanation": "mal",
        "deterministic": True,
        "alphabet": ["a"],
        "states": [{"id": "q0", "initial": True, "final": True}],
        "transitions": [
            {"from": "q0", "to": "q0", "read": "0"},
            {"from": "q0", "to": "q0", "read": "a"},
        ],
    }
    with pytest.raises(ModelReplyError) as caught:
        interpret_text(json.dumps(raw), "AFD sobre el alfabeto {0, 1} para el dibujo del apunte")
    text = " ".join(caught.value.errors)
    assert "no declara" in text
    assert "«a»" in text
    assert "«0» no está en el alfabeto" not in text


def test_bogus_regex_keeps_the_declared_alphabet():
    """Después del «a», el modelo contestó 1*. El 0 del enunciado se puede leer."""
    calls = {"n": 0}

    async def fake_chat(_settings, _messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps(
                {
                    "kind": "fa",
                    "pattern": "",
                    "description": "mal",
                    "explanation": "agregué una a",
                    "deterministic": True,
                    "alphabet": ["0", "1", "a"],
                    "states": [
                        {"id": "q0", "initial": True, "final": True},
                        {"id": "q1", "initial": False, "final": False},
                    ],
                    "transitions": [
                        {"from": "q0", "to": "q0", "read": "0"},
                        {"from": "q0", "to": "q1", "read": "1"},
                        {"from": "q0", "to": "q0", "read": "a"},
                        {"from": "q1", "to": "q1", "read": "0"},
                        {"from": "q1", "to": "q0", "read": "1"},
                        {"from": "q1", "to": "q1", "read": "a"},
                    ],
                }
            )
        return json.dumps(
            {
                "kind": "regex",
                "pattern": "1*",
                "description": "unos",
                "explanation": "solo unos",
                "deterministic": True,
                "alphabet": ["1"],
                "states": [],
                "transitions": [],
            }
        )

    phrase = "un AFD sobre el alfabeto {0, 1} para el dibujo del apunte"
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
        assert body["automaton"]["alphabet"] == ["0", "1"]
        shown = body["messages"][-1]["content"]
        assert "«0» no está en el alfabeto" not in shown
        assert "no declara" not in shown
        zero = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "0"})
        assert zero.json()["ok"] is True
        assert zero.json()["accepted"] is False
        assert zero.json()["message"] != "«0» no está en el alfabeto"
        assert client.post(f"/api/sessions/{session_id}/simulate", json={"word": ""}).json()["accepted"]
        assert client.post(f"/api/sessions/{session_id}/simulate", json={"word": "11"}).json()["accepted"]
        assert not client.post(f"/api/sessions/{session_id}/simulate", json={"word": "10"}).json()["accepted"]
