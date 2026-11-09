import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "card_runner.js"


def _call(fn: str, *args):
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede armar la ficha.")
    result = subprocess.run(
        [node, str(RUNNER), json.dumps({"fn": fn, "args": list(args)}, ensure_ascii=False)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def _rows(card: dict) -> dict:
    return {row["key"]: row for row in card["rows"]}


def _fa(**overrides):
    payload = {
        "deterministic": True,
        "alphabet": ["0", "1"],
        "states": [
            {"id": "q0", "initial": True, "final": True},
            {"id": "q1", "initial": False, "final": False},
        ],
        "transitions": [
            {"from": "q0", "to": "q0", "read": "0"},
            {"from": "q0", "to": "q1", "read": "1"},
            {"from": "q1", "to": "q1", "read": "0"},
            {"from": "q1", "to": "q0", "read": "1"},
        ],
    }
    payload.update(overrides)
    return payload


def test_page_loads_the_card_before_the_app():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/card.js")
        app_js = client.get("/static/app.js")
        styles = client.get("/static/styles.css")
    assert page.status_code == 200
    text = page.text
    assert 'id="fresh" type="button"' in text
    assert "Nuevo autómata" in text
    assert 'id="download"' in text
    assert 'id="remember"' in text
    assert 'id="determinize"' in text
    assert 'id="regex"' in text
    assert 'id="grammar"' in text
    card_at = text.index("/static/card.js")
    app_at = text.index("/static/app.js")
    assert card_at < app_at
    assert script.status_code == 200
    assert "automatonCard" in script.text
    assert "NAME_LIMIT" in script.text
    assert "GAP_SCAN" in script.text
    assert app_js.status_code == 200
    assert "ComgenCard.automatonCard" in app_js.text
    assert "titulo-definicion" in app_js.text
    assert 'class: "alphabet"' not in app_js.text
    assert styles.status_code == 200
    assert ".def-row" in styles.text
    assert ".card-note" in styles.text


def test_parity_and_the_examples_name_the_definition():
    parity = _call("automatonCard", EXAMPLES["paridad"].automaton.model_dump(by_alias=True))
    rows = _rows(parity)
    assert parity["shown"] is True
    assert parity["note"] == ""
    assert rows["Q"]["value"] == "q0, q1"
    assert rows["Q"]["spoken"] == "2 estados: q0, q1."
    assert rows["Σ"]["value"] == "{0, 1}"
    assert rows["Σ"]["spoken"] == "Alfabeto: 0, 1."
    assert rows["q₀"]["value"] == "q0"
    assert rows["q₀"]["spoken"] == "Estado inicial: q0."
    assert rows["F"]["value"] == "q0"
    assert rows["F"]["label"] == "Finales"

    ends = _rows(_call("automatonCard", EXAMPLES["termina-en-01"].automaton.model_dump(by_alias=True)))
    assert ends["Q"]["value"] == "q0, q1, q2"
    assert ends["F"]["value"] == "q2"
    assert ends["q₀"]["value"] == "q0"

    star = _call("automatonCard", EXAMPLES["a-estrella"].automaton.model_dump(by_alias=True))
    star_rows = _rows(star)
    assert star["note"] == ""
    assert star_rows["Σ"]["value"] == "{a, b}"
    assert star_rows["F"]["value"] == "q2"
    assert "Faltan" not in star["note"]


def test_a_missing_arrow_is_a_rejection_and_an_nfa_is_not_counted():
    partial = _fa(
        states=[{"id": "q0", "initial": True, "final": False}],
        transitions=[{"from": "q0", "to": "q0", "read": "0"}],
    )
    card = _call("automatonCard", partial)
    assert card["note"] == "Falta 1 flecha. En la tabla, el guión es un rechazo."

    two = _fa(
        states=[{"id": "q0", "initial": True, "final": True}],
        alphabet=["a", "b"],
        transitions=[],
    )
    assert _call("automatonCard", two)["note"] == (
        "Faltan 2 flechas. En la tabla, el guión es un rechazo."
    )

    # La épsilon no llena la celda de a. El 0 numérico es el símbolo 0.
    epsilon = _fa(
        alphabet=["a", 0],
        states=[{"id": 0, "initial": True, "final": True}],
        transitions=[{"from": 0, "to": 0, "read": ""}],
    )
    zero = _call("automatonCard", epsilon)
    assert _rows(zero)["Q"]["value"] == "0"
    assert _rows(zero)["Σ"]["value"] == "{a, 0}"
    assert zero["note"] == "Faltan 2 flechas. En la tabla, el guión es un rechazo."

    nfa = _fa(deterministic=False, transitions=[])
    assert _call("automatonCard", nfa)["note"] == ""


def test_names_stay_whole_and_long_lists_stay_short():
    quoted = _fa(
        alphabet=["a, b", "\u0301", "c"],
        states=[
            {"id": "q0, q1", "initial": True, "final": False},
            {"id": "{q0,q1}", "initial": False, "final": True},
        ],
        transitions=[],
    )
    rows = _rows(_call("automatonCard", quoted))
    assert rows["Q"]["value"] == "«q0, q1», {q0,q1}"
    assert rows["Q"]["spoken"] == "2 estados: «q0, q1», {q0,q1}."
    assert rows["F"]["value"] == "{q0,q1}"
    assert rows["Σ"]["value"] == "{«a, b», «\u0301», c}"

    many = _fa(
        states=[{"id": f"q{index}", "initial": index == 0, "final": False} for index in range(9)],
        transitions=[
            {"from": f"q{index}", "to": "q0", "read": symbol}
            for index in range(9)
            for symbol in ("0", "1")
        ],
    )
    wide = _call("automatonCard", many)
    assert _rows(wide)["Q"]["value"] == "9 estados"
    assert "q8" not in _rows(wide)["Q"]["spoken"]
    assert "q7" in _rows(wide)["Q"]["spoken"]
    assert wide["note"] == ""

    symbols = [f"s{index}" for index in range(13)]
    crowded = _fa(
        alphabet=symbols,
        states=[{"id": "q0", "initial": True, "final": True}],
        transitions=[{"from": "q0", "to": "q0", "read": symbol} for symbol in symbols],
    )
    alphabet = _rows(_call("automatonCard", crowded))["Σ"]
    assert alphabet["value"].endswith("…}")
    assert "s12" not in alphabet["value"]
    assert alphabet["spoken"] == "Alfabeto de 13 símbolos."


def test_empty_and_odd_shapes_do_not_invent_a_machine():
    assert _call("automatonCard", None) == {"shown": False, "rows": [], "note": ""}
    assert _call("automatonCard", [])["shown"] is False
    bare = _call("automatonCard", {"states": [{"id": "q0"}]})
    rows = _rows(bare)
    assert bare["shown"] is True
    assert rows["Q"]["value"] == "q0"
    assert rows["Σ"]["value"] == "vacío"
    assert rows["q₀"]["value"] == "ninguno"
    assert rows["F"]["spoken"] == "No hay estado final."
    assert bare["note"] == "No hay estado inicial."

    none = _call("automatonCard", {"deterministic": True})
    assert none["note"] == "No hay estados."
    assert _rows(none)["Q"]["value"] == "ninguno"

    doubled = _fa(
        states=[
            {"id": "q0", "initial": False, "final": False},
            {"id": "q0", "initial": True, "final": True},
            {"id": True, "initial": True, "final": True},
            {"id": 1, "initial": False, "final": False},
        ],
        transitions=[
            {"from": "q0", "to": "q0", "read": "0"},
            {"from": "q0", "to": "q0", "read": "1"},
            {"from": 1, "to": 1, "read": "0"},
            {"from": 1, "to": 1, "read": "1"},
        ],
    )
    merged = _rows(_call("automatonCard", doubled))
    assert merged["Q"]["value"] == "q0, 1"
    assert merged["q₀"]["value"] == "q0"
    assert merged["F"]["value"] == "q0"

    huge_states = [{"id": f"q{index}", "initial": index == 0, "final": False} for index in range(100)]
    huge = _call(
        "automatonCard",
        {"deterministic": True, "alphabet": [f"s{index}" for index in range(50)], "states": huge_states},
    )
    assert "Faltan" not in huge["note"]
    assert _rows(huge)["Q"]["value"] == "100 estados"
