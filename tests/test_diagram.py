import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "diagram_runner.js"


def _diagram(automaton: dict) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede armar el dibujo.")
    result = subprocess.run(
        [node, str(RUNNER), json.dumps(automaton)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def _node(diagram: dict, state_id: str) -> dict:
    return next(item for item in diagram["nodes"] if item["id"] == state_id)


def _edge(diagram: dict, source: str, target: str) -> dict:
    return next(item for item in diagram["edges"] if item["from"] == source and item["to"] == target)


def _separated(diagram: dict) -> None:
    nodes = diagram["nodes"]
    for left in range(len(nodes)):
        for right in range(left + 1, len(nodes)):
            a = nodes[left]
            b = nodes[right]
            dx = abs(a["x"] - b["x"])
            dy = abs(a["y"] - b["y"])
            assert dx > (a["w"] + b["w"]) / 2 + 8 or dy > (a["h"] + b["h"]) / 2 + 8


def _inside(diagram: dict) -> None:
    width = diagram["width"]
    height = diagram["height"]
    assert width > 0 and height > 0
    for node in diagram["nodes"]:
        assert node["w"] / 2 - 0.5 <= node["x"] <= width - node["w"] / 2 + 0.5
        assert node["h"] / 2 - 0.5 <= node["y"] <= height - node["h"] / 2 + 0.5
        assert math.isfinite(node["x"]) and math.isfinite(node["y"])
    for edge in diagram["edges"]:
        assert edge["d"].startswith("M ")
        assert "C " in edge["d"] or "Q " in edge["d"]
        assert 0 <= edge["labelX"] <= width
        assert 0 <= edge["labelY"] <= height
        assert 0 <= edge["tip"]["x"] <= width
        assert 0 <= edge["tip"]["y"] <= height


def test_page_loads_the_diagram_before_the_app():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/diagram.js")
        app_js = client.get("/static/app.js")
    assert page.status_code == 200
    text = page.text
    assert 'id="fresh" type="button"' in text
    assert "Nuevo autómata" in text
    assert 'id="download"' in text
    assert 'id="remember"' in text
    assert 'id="determinize"' in text
    diagram_at = text.index("/static/diagram.js")
    app_at = text.index("/static/app.js")
    assert diagram_at < app_at
    assert script.status_code == 200
    assert "automatonDiagram" in script.text
    assert "STATE_LIMIT" in script.text
    assert app_js.status_code == 200
    assert "ComgenDiagram.automatonDiagram" in app_js.text
    assert "titulo-dibujo" in app_js.text


def test_parity_is_two_states_with_loops_and_a_start_arrow():
    payload = EXAMPLES["paridad"].automaton.model_dump(by_alias=True)
    diagram = _diagram(payload)
    assert diagram["drawn"] is True
    assert diagram["total"] == 2
    assert diagram["limit"] == 16
    _inside(diagram)
    _separated(diagram)
    q0 = _node(diagram, "q0")
    q1 = _node(diagram, "q1")
    assert q0["initial"] is True and q0["final"] is True
    assert q0["shape"] == "circle"
    assert q0["accessibleName"] == "q0, inicial y final"
    assert q0["x"] < q1["x"]
    assert _edge(diagram, "q0", "q0")["label"] == "0"
    assert _edge(diagram, "q0", "q0")["loop"] is True
    assert _edge(diagram, "q0", "q0")["d"].count("C ") == 1
    assert _edge(diagram, "q1", "q1")["label"] == "0"
    assert _edge(diagram, "q0", "q1")["label"] == "1"
    assert _edge(diagram, "q1", "q0")["label"] == "1"
    assert _edge(diagram, "q0", "q1")["d"] != _edge(diagram, "q1", "q0")["d"]
    assert diagram["start"]["tip"]["x"] < q0["x"]
    assert "doble círculo" in diagram["legend"]
    assert "lazo" in diagram["legend"]
    assert "guión" not in diagram["legend"]
    assert "q0 es inicial y final" in diagram["summary"]
    assert "vuelve a q0" in diagram["summary"]
    assert "va a q1" in diagram["summary"]


def test_ends_with_01_puts_the_final_state_on_the_drawing():
    payload = EXAMPLES["termina-en-01"].automaton.model_dump(by_alias=True)
    diagram = _diagram(payload)
    assert diagram["drawn"] is True
    assert diagram["total"] == 3
    _inside(diagram)
    _separated(diagram)
    q0 = _node(diagram, "q0")
    q2 = _node(diagram, "q2")
    assert q0["initial"] is True and q0["final"] is False
    assert q2["final"] is True
    assert q0["x"] <= min(node["x"] for node in diagram["nodes"])
    assert _edge(diagram, "q1", "q2")["label"] == "1"
    assert _edge(diagram, "q2", "q1")["label"] == "0"
    assert _edge(diagram, "q0", "q0")["loop"] is True


def test_epsilon_is_labelled_and_a_missing_arrow_is_not_drawn():
    diagram = _diagram(
        {
            "deterministic": False,
            "alphabet": ["a", "b"],
            "states": [
                {"id": "q0", "initial": True, "final": False},
                {"id": "q1", "initial": False, "final": False},
                {"id": "q2", "initial": False, "final": True},
            ],
            "transitions": [
                {"from": "q0", "read": "", "to": "q1"},
                {"from": "q0", "read": "", "to": "q1"},
                {"from": "q1", "read": "a", "to": "q2"},
                {"from": "q1", "read": "", "to": "q2"},
                {"from": "q2", "read": "a", "to": "q2"},
            ],
        }
    )
    assert _edge(diagram, "q0", "q1")["label"] == "ε"
    assert _edge(diagram, "q0", "q1")["epsilon"] is True
    assert _edge(diagram, "q1", "q2")["label"] == "a, ε"
    assert _edge(diagram, "q2", "q2")["label"] == "a"
    assert all(edge["label"] != "b" for edge in diagram["edges"])
    assert "cadena vacía" in diagram["legend"]
    assert "AFN" in diagram["legend"]
    assert "guión" not in diagram["legend"]


def test_a_missing_dfa_arrow_stays_out_of_the_drawing():
    diagram = _diagram(
        {
            "deterministic": True,
            "alphabet": ["0", "1"],
            "states": [{"id": "q0", "initial": True, "final": True}],
            "transitions": [{"from": "q0", "read": "0", "to": "q0"}],
        }
    )
    assert diagram["drawn"] is True
    assert len(diagram["edges"]) == 1
    assert diagram["edges"][0]["label"] == "0"
    assert "guión" in diagram["legend"]
    assert diagram["start"] is not None


def test_a_long_name_is_shortened_on_the_node_and_kept_for_the_reader():
    full = "{q0,q1,q2,q3,q4}"
    diagram = _diagram(
        {
            "deterministic": True,
            "alphabet": ["a"],
            "states": [
                {"id": full, "initial": True, "final": False},
                {"id": "q1", "initial": False, "final": True},
            ],
            "transitions": [{"from": full, "read": "a", "to": "q1"}],
        }
    )
    node = _node(diagram, full)
    assert node["shape"] == "pill"
    assert node["label"].endswith("…")
    assert node["label"] != full
    assert len(node["label"]) <= 14
    assert node["fullLabel"] == full
    assert full in diagram["summary"]
    assert _edge(diagram, full, "q1")["label"] == "a"
    _inside(diagram)
    _separated(diagram)


def test_labels_on_a_five_state_cycle_stay_off_the_circles():
    states = [{"id": f"q{i}", "initial": i == 0, "final": i == 0} for i in range(5)]
    transitions = []
    for index, state in enumerate(states):
        transitions.append({"from": state["id"], "read": "0", "to": f"q{(2 * index) % 5}"})
        transitions.append({"from": state["id"], "read": "1", "to": f"q{(2 * index + 1) % 5}"})
    diagram = _diagram(
        {
            "deterministic": True,
            "alphabet": ["0", "1"],
            "states": states,
            "transitions": transitions,
        }
    )
    assert diagram["drawn"] is True
    assert diagram["total"] == 5
    _inside(diagram)
    _separated(diagram)
    for edge in diagram["edges"]:
        for node in diagram["nodes"]:
            assert abs(edge["labelX"] - node["x"]) > node["w"] / 2 or abs(edge["labelY"] - node["y"]) > node["h"] / 2
    for left in range(len(diagram["edges"])):
        for right in range(left + 1, len(diagram["edges"])):
            a = diagram["edges"][left]
            b = diagram["edges"][right]
            distance = math.hypot(a["labelX"] - b["labelX"], a["labelY"] - b["labelY"])
            assert distance >= 16


def test_more_than_sixteen_states_are_not_drawn():
    states = [{"id": f"q{i}", "initial": i == 0, "final": i == 0} for i in range(17)]
    transitions = [
        {"from": f"q{i}", "read": "0", "to": f"q{(i + 1) % 17}"}
        for i in range(17)
    ]
    diagram = _diagram(
        {
            "deterministic": False,
            "alphabet": ["0"],
            "states": states,
            "transitions": transitions,
        }
    )
    assert diagram["drawn"] is False
    assert diagram["total"] == 17
    assert diagram["limit"] == 16
    assert diagram["nodes"] == []
    assert diagram["edges"] == []
    assert "17" in diagram["message"]
    assert "16" in diagram["message"]
    assert "tabla" in diagram["message"]


def test_numeric_zero_is_its_own_arrow_and_not_epsilon():
    diagram = _diagram(
        {
            "deterministic": False,
            "alphabet": ["a", 0],
            "states": [
                {"id": "q0", "initial": True, "final": False},
                {"id": "q1", "initial": False, "final": True},
                {"id": "q2", "initial": False, "final": False},
            ],
            "transitions": [
                {"from": "q0", "read": 0, "to": "q1"},
                {"from": "q0", "read": "", "to": "q2"},
                {"from": "q0", "read": None, "to": "q0"},
            ],
        }
    )
    zero = _edge(diagram, "q0", "q1")
    epsilon = _edge(diagram, "q0", "q2")
    loop = _edge(diagram, "q0", "q0")
    assert zero["label"] == "0"
    assert zero["epsilon"] is False
    assert epsilon["epsilon"] is True
    assert epsilon["label"] == "ε"
    assert loop["epsilon"] is True
    assert zero["to"] != epsilon["to"]
    _inside(diagram)


def test_null_rows_and_unknown_targets_do_not_throw():
    diagram = _diagram(
        {
            "deterministic": True,
            "alphabet": ["a"],
            "states": [None, {"id": "q0", "initial": True, "final": True}, {"id": "q0", "initial": False, "final": False}],
            "transitions": [None, {"from": "q0", "read": "a", "to": "fantasma"}, {"from": "q0", "read": "a", "to": "q0"}],
        }
    )
    assert diagram["total"] == 1
    assert [node["id"] for node in diagram["nodes"]] == ["q0"]
    assert len(diagram["edges"]) == 1
    assert diagram["edges"][0]["to"] == "q0"
    empty = _diagram(None)
    assert empty["drawn"] is False
    assert empty["nodes"] == []
    assert "no tiene estados" in empty["message"]
