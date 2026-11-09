import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "delta_runner.js"


def _table(automaton: dict, options: dict | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede armar la tabla de transiciones.")
    # stdin, no argv: miles de columnas no entran en la línea de comandos de Windows.
    payload = json.dumps({"automaton": automaton, "options": options or {}})
    result = subprocess.run(
        [node, str(RUNNER)],
        input=payload,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def _cell(table: dict, state_id: str, symbol: str) -> dict:
    row = next(item for item in table["rows"] if item["id"] == state_id)
    return next(item for item in row["cells"] if item["symbol"] == symbol)


def test_page_keeps_the_student_controls_and_loads_the_delta_script():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/delta.js")
        app_js = client.get("/static/app.js")
    assert page.status_code == 200
    text = page.text
    assert 'id="fresh" type="button"' in text
    assert "Nuevo autómata" in text
    assert 'id="download"' in text
    assert 'id="remember"' in text
    delta_at = text.index("/static/delta.js")
    app_at = text.index("/static/app.js")
    assert delta_at < app_at
    assert script.status_code == 200
    assert "transitionTable" in script.text
    assert app_js.status_code == 200
    assert "ComgenDelta.transitionTable" in app_js.text
    assert "Desde" not in app_js.text


def test_parity_example_is_a_delta_table():
    payload = EXAMPLES["paridad"].automaton.model_dump(by_alias=True)
    table = _table(payload)
    assert table["total"] == 2
    assert table["hidden"] == 0
    assert [column["id"] for column in table["columns"]] == ["0", "1"]
    assert table["hasGap"] is False
    assert "falta" not in table["legend"]
    q0 = next(row for row in table["rows"] if row["id"] == "q0")
    q1 = next(row for row in table["rows"] if row["id"] == "q1")
    assert q0["initial"] is True
    assert q0["final"] is True
    assert q0["marks"] == "→*"
    assert q0["accessibleName"] == "q0, inicial y final"
    assert q1["marks"] == ""
    assert q1["accessibleName"] == "q1"
    assert _cell(table, "q0", "0")["text"] == "q0"
    assert _cell(table, "q0", "1")["text"] == "q1"
    assert _cell(table, "q1", "0")["text"] == "q1"
    assert _cell(table, "q1", "1")["text"] == "q0"
    assert _cell(table, "q0", "0")["gap"] is False


def test_a_missing_arrow_is_a_gap_only_on_a_dfa():
    partial = {
        "deterministic": True,
        "alphabet": ["0", "1"],
        "states": [{"id": "q0", "initial": True, "final": True}],
        "transitions": [{"from": "q0", "read": "0", "to": "q0"}],
    }
    table = _table(partial)
    assert _cell(table, "q0", "0") == {
        "symbol": "0",
        "label": "0",
        "targets": ["q0"],
        "text": "q0",
        "gap": False,
    }
    assert _cell(table, "q0", "1")["gap"] is True
    assert _cell(table, "q0", "1")["text"] == "—"
    assert "flecha que falta" in table["legend"]

    partial["deterministic"] = False
    nfa = _table(partial)
    assert _cell(nfa, "q0", "1")["gap"] is False
    assert "no hay flecha" in nfa["legend"]


def test_nfa_groups_targets_and_puts_epsilon_last():
    payload = {
        "deterministic": False,
        "alphabet": ["a"],
        "states": [
            {"id": "q0", "initial": True, "final": False},
            {"id": "q1", "initial": False, "final": True},
        ],
        "transitions": [
            {"from": "q0", "read": "a", "to": "q0"},
            {"from": "q0", "read": "a", "to": "q1"},
            {"from": "q0", "read": "a", "to": "q0"},
            {"from": "q0", "read": "", "to": "q1"},
            {"from": "q1", "read": "b", "to": "q0"},
        ],
    }
    table = _table(payload)
    assert [column["id"] for column in table["columns"]] == ["a", "b", ""]
    assert table["columns"][1]["extra"] is True
    assert table["columns"][2]["epsilon"] is True
    assert table["columns"][2]["label"] == "ε"
    assert _cell(table, "q0", "a")["targets"] == ["q0", "q1"]
    assert _cell(table, "q0", "a")["text"] == "q0, q1"
    assert _cell(table, "q0", "")["text"] == "q1"
    assert _cell(table, "q1", "a")["gap"] is False
    assert "separadas por coma" in table["legend"]
    assert "no está en el alfabeto" in table["legend"]
    q1 = next(row for row in table["rows"] if row["id"] == "q1")
    assert q1["marks"] == "*"
    assert q1["accessibleName"] == "q1, final"


def test_a_long_automaton_stays_folded_until_asked():
    states = [{"id": f"q{i}", "initial": i == 0, "final": i == 0} for i in range(40)]
    transitions = [
        item
        for i in range(40)
        for item in (
            {"from": f"q{i}", "read": "0", "to": f"q{i}"},
            {"from": f"q{i}", "read": "1", "to": f"q{(i + 1) % 40}"},
        )
    ]
    payload = {
        "deterministic": True,
        "alphabet": ["0", "1"],
        "states": states,
        "transitions": transitions,
    }
    folded = _table(payload)
    assert folded["total"] == 40
    assert folded["hidden"] == 8
    assert [row["id"] for row in folded["rows"]] == [f"q{i}" for i in range(32)]
    assert folded["moreLabel"] == "Ver los 40 estados"
    assert "primeros 32 de 40" in folded["caption"]

    opened = _table(payload, {"expanded": True})
    assert opened["hidden"] == 0
    assert len(opened["rows"]) == 40
    assert opened["moreLabel"] == "Ver menos"
    assert opened["rows"][-1]["id"] == "q39"


def test_a_null_byte_does_not_merge_two_cells():
    table = _table(
        {
            "deterministic": True,
            "alphabet": ["b"],
            "states": [
                {"id": "q0", "initial": True, "final": True},
                {"id": "q0\x00a", "initial": False, "final": False},
            ],
            "transitions": [
                {"from": "q0", "read": "a\x00b", "to": "X"},
                {"from": "q0\x00a", "read": "b", "to": "Y"},
            ],
        }
    )
    assert _cell(table, "q0", "a\x00b")["targets"] == ["X"]
    assert _cell(table, "q0\x00a", "b")["targets"] == ["Y"]
    assert _cell(table, "q0", "a\x00b")["text"] == "X"
    assert _cell(table, "q0\x00a", "b")["text"] == "Y"


def test_a_subset_name_with_commas_is_one_arrival():
    table = _table(
        {
            "deterministic": True,
            "alphabet": ["a"],
            "states": [
                {"id": "{q0}", "initial": True, "final": False},
                {"id": "{q0,q1}", "initial": False, "final": True},
            ],
            "transitions": [{"from": "{q0}", "read": "a", "to": "{q0,q1}"}],
        }
    )
    cell = _cell(table, "{q0}", "a")
    assert cell["targets"] == ["{q0,q1}"]
    assert cell["text"] == "{q0,q1}"
    assert cell["gap"] is False


def test_a_comma_space_in_one_name_is_not_two_arrivals():
    table = _table(
        {
            "deterministic": False,
            "alphabet": ["a"],
            "states": [
                {"id": "q0", "initial": True, "final": False},
                {"id": "q0, q1", "initial": False, "final": True},
                {"id": "q2", "initial": False, "final": False},
            ],
            "transitions": [
                {"from": "q0", "read": "a", "to": "q0, q1"},
                {"from": "q0", "read": "a", "to": "q2"},
            ],
        }
    )
    cell = _cell(table, "q0", "a")
    assert cell["targets"] == ["q0, q1", "q2"]
    assert cell["text"] == "«q0, q1», «q2»"
    assert cell["text"] != "q0, q1, q2"
    braced = _table(
        {
            "deterministic": True,
            "alphabet": ["a"],
            "states": [
                {"id": "{q0}", "initial": True, "final": False},
                {"id": "{q0,q1}", "initial": False, "final": True},
            ],
            "transitions": [{"from": "{q0}", "read": "a", "to": "{q0,q1}"}],
        }
    )
    assert _cell(braced, "{q0}", "a")["text"] == "{q0,q1}"


def test_numeric_zero_is_a_symbol_and_does_not_join_epsilon():
    table = _table(
        {
            "deterministic": False,
            "alphabet": ["a", 0],
            "states": [
                {"id": "q0", "initial": True, "final": False},
                {"id": "0", "initial": False, "final": False},
                {"id": "q1", "initial": False, "final": True},
                {"id": "q2", "initial": False, "final": False},
            ],
            "transitions": [
                {"from": "q0", "read": 0, "to": "q1"},
                {"from": "q0", "read": "", "to": "q2"},
                {"from": 0, "read": "a", "to": "q2"},
            ],
        }
    )
    assert [column["id"] for column in table["columns"]] == ["a", "0", ""]
    assert _cell(table, "q0", "0")["targets"] == ["q1"]
    assert _cell(table, "q0", "0")["text"] == "q1"
    assert _cell(table, "q0", "")["targets"] == ["q2"]
    assert _cell(table, "q0", "")["text"] == "q2"
    assert _cell(table, "0", "a")["targets"] == ["q2"]


def test_thousands_of_columns_stay_capped():
    alphabet = [chr(0x4E00 + index) for index in range(4000)]
    table = _table(
        {
            "deterministic": True,
            "alphabet": alphabet,
            "states": [{"id": "q0", "initial": True, "final": True}],
            "transitions": [
                {"from": "q0", "read": "", "to": "q0"},
                {"from": "q0", "read": alphabet[0], "to": "q0"},
            ],
        }
    )
    assert table["columnTotal"] == 4001
    assert table["hiddenColumns"] == 4001 - 32
    assert len(table["columns"]) == 32
    assert table["columns"][-1]["epsilon"] is True
    assert table["columns"][-1]["id"] == ""
    assert "columnas" in table["legend"]
    assert "liviana" in table["legend"]
    assert _cell(table, "q0", "")["text"] == "q0"


def test_null_rows_and_transitions_do_not_throw():
    table = _table(
        {
            "deterministic": True,
            "alphabet": ["a"],
            "states": [None, {"id": "q0", "initial": True, "final": True}],
            "transitions": [None, {"from": "q0", "read": "a", "to": "q0"}],
        }
    )
    assert table["total"] == 1
    assert [row["id"] for row in table["rows"]] == ["q0"]
    assert _cell(table, "q0", "a")["targets"] == ["q0"]
    empty = _table(None)
    assert empty["rows"] == []
    assert empty["columns"] == []
