import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "trace_runner.js"


def _trace(result, automaton, options=None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede armar el recorrido.")
    payload = {"result": result, "automaton": automaton, "options": options or {}}
    completed = subprocess.run(
        [node, str(RUNNER), json.dumps(payload)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(completed.stdout)


def _run(example_id: str, word: str) -> tuple[dict, dict]:
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        loaded = client.post(f"/api/sessions/{session_id}/examples/{example_id}")
        simulated = client.post(
            f"/api/sessions/{session_id}/simulate",
            json={"word": word},
        )
    assert loaded.status_code == 200
    assert simulated.status_code == 200
    return simulated.json(), loaded.json()["automaton"]


def test_page_loads_the_trace_before_the_app():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/trace.js")
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
    assert 'id="run-steps"' in text
    assert 'id="run-steps-wrap"' in text
    assert 'id="run-result"' in text
    trace_at = text.index("/static/trace.js")
    app_at = text.index("/static/app.js")
    assert trace_at < app_at
    assert script.status_code == 200
    assert "simulationTrace" in script.text
    assert "STEP_LIMIT" in script.text
    assert app_js.status_code == 200
    assert "ComgenTrace.simulationTrace" in app_js.text
    assert "data-state" in app_js.text
    assert "is-here" in app_js.text
    assert "step.index + 1" in app_js.text
    assert styles.status_code == 200
    assert "list-style: none" in styles.text


def test_parity_eleven_is_a_step_list_that_ends_final():
    result, automaton = _run("paridad", "11")
    trace = _trace(result, automaton)
    assert trace["ok"] is True
    assert trace["accepted"] is True
    assert trace["verdict"] == "Acepta"
    assert trace["summary"] == "Acepta. Termina en q0, que es final."
    assert [step["text"] for step in trace["steps"]] == [
        "Empieza en q0.",
        "Lee 1 y pasa a q1.",
        "Lee 1 y pasa a q0, que es final.",
    ]
    assert trace["here"] == ["q0"]
    assert trace["visited"] == ["q0", "q1"]
    assert trace["lastLookups"] == [{"from": "q1", "symbol": "1"}]
    assert trace["omitted"] == 0
    assert trace["moreLabel"] == ""
    assert trace["limit"] == 24


def test_parity_one_rejects_outside_a_final_state():
    result, automaton = _run("paridad", "1")
    trace = _trace(result, automaton)
    assert trace["accepted"] is False
    assert trace["summary"] == "Rechaza. Termina en q1, que no es final."
    assert trace["steps"][-1]["text"] == "Lee 1 y pasa a q1."
    assert trace["here"] == ["q1"]
    assert trace["lastLookups"] == [{"from": "q0", "symbol": "1"}]


def test_empty_word_stays_on_the_initial_state():
    result, automaton = _run("paridad", "")
    trace = _trace(result, automaton)
    assert trace["accepted"] is True
    assert trace["summary"] == "Acepta. Termina en q0, que es final."
    assert [step["text"] for step in trace["steps"]] == ["Empieza en q0, que es final."]
    assert trace["lastLookups"] == []


def test_a_loop_says_the_machine_stays():
    result, automaton = _run("paridad", "0")
    trace = _trace(result, automaton)
    assert trace["steps"][-1]["text"] == "Lee 0 y se queda en q0, que es final."
    assert trace["lastLookups"] == [{"from": "q0", "symbol": "0"}]


def test_epsilon_closure_is_spelled_out_and_a_dead_read_is_empty():
    accepted, automaton = _run("a-estrella", "a")
    trace = _trace(accepted, automaton)
    assert trace["accepted"] is True
    assert trace["steps"][0]["text"] == (
        "Empieza en q0 y, por épsilon, también llega a q1 y q2."
    )
    assert trace["steps"][-1]["text"] == "Lee a y pasa a q2, que es final."
    assert trace["here"] == ["q2"]
    assert trace["lastLookups"] == [
        {"from": "q0", "symbol": "a"},
        {"from": "q1", "symbol": "a"},
        {"from": "q2", "symbol": "a"},
    ]

    rejected, _automaton = _run("a-estrella", "b")
    dead = _trace(rejected, automaton)
    assert dead["accepted"] is False
    assert dead["summary"] == "Rechaza. Lee b y no queda en ningún estado."
    assert dead["steps"][-1]["text"] == "Lee b y no queda en ningún estado."
    assert dead["here"] == []
    assert [item["from"] for item in dead["lastLookups"]] == ["q0", "q1", "q2"]
    assert {item["symbol"] for item in dead["lastLookups"]} == {"b"}


def test_a_symbol_outside_the_alphabet_keeps_the_server_message():
    result, automaton = _run("paridad", "2")
    trace = _trace(result, automaton)
    assert result["ok"] is False
    assert trace["ok"] is False
    assert trace["summary"] == result["message"]
    assert "alfabeto" in trace["summary"]
    assert trace["steps"] == []
    assert trace["here"] == []


def test_spaced_names_are_quoted_and_subset_names_are_not():
    result = {
        "ok": True,
        "accepted": True,
        "steps": [
            {"symbol": "", "states": ["{q0,q1}"]},
            {"symbol": "a", "states": ["{q0,q1}", "a, b", "q0 y q1"]},
        ],
    }
    automaton = {
        "states": [
            {"id": "{q0,q1}", "initial": True, "final": False},
            {"id": "a, b", "initial": False, "final": True},
            {"id": "q0 y q1", "initial": False, "final": False},
        ],
    }
    trace = _trace(result, automaton)
    assert trace["steps"][0]["text"] == "Empieza en {q0,q1}."
    assert trace["steps"][1]["text"] == (
        "Lee a y queda en {q0,q1}, «a, b» y «q0 y q1». «a, b» es final."
    )
    assert trace["summary"] == (
        "Acepta. Termina en {q0,q1}, «a, b» y «q0 y q1». «a, b» es final."
    )


def test_numeric_zero_is_a_state_and_not_epsilon():
    result = {
        "ok": True,
        "accepted": False,
        "steps": [
            {"symbol": "", "states": [0]},
            {"symbol": 0, "states": [0]},
        ],
    }
    automaton = {"states": [{"id": "0", "initial": True, "final": False}]}
    trace = _trace(result, automaton)
    assert trace["steps"][0]["text"] == "Empieza en 0."
    assert trace["steps"][1]["text"] == "Lee 0 y se queda en 0."
    assert "épsilon" not in trace["summary"]
    assert trace["lastLookups"] == [{"from": "0", "symbol": "0"}]
    assert trace["here"] == ["0"]


def test_a_long_run_keeps_the_start_and_the_ending():
    steps = [{"symbol": "", "states": ["q0"]}]
    for index in range(29):
        steps.append({"symbol": "a", "states": ["q1" if index % 2 == 0 else "q0"]})
    result = {"ok": True, "accepted": False, "steps": steps}
    automaton = {
        "states": [
            {"id": "q0", "initial": True, "final": True},
            {"id": "q1", "initial": False, "final": False},
        ],
    }
    trace = _trace(result, automaton)
    assert trace["total"] == 30
    assert trace["omitted"] == 6
    assert trace["gap"] == "Se omiten 6 pasos."
    assert trace["moreLabel"] == "Ver los 30 pasos"
    assert len(trace["steps"]) == 24
    assert trace["steps"][0]["index"] == 0
    assert trace["steps"][0]["text"] == "Empieza en q0."
    assert trace["steps"][1]["index"] == 7
    assert trace["steps"][-1]["index"] == 29
    assert trace["here"] == ["q1"]
    assert trace["summary"] == "Rechaza. Termina en q1, que no es final."
    assert trace["lastLookups"] == [{"from": "q0", "symbol": "a"}]

    opened = _trace(result, automaton, {"expanded": True})
    assert opened["omitted"] == 0
    assert opened["gap"] == ""
    assert opened["moreLabel"] == "Ver menos"
    assert len(opened["steps"]) == 30
    assert opened["here"] == ["q1"]


def test_one_omitted_step_uses_the_singular():
    steps = [{"symbol": "", "states": ["q0"]}]
    steps.extend({"symbol": "a", "states": ["q0"]} for _ in range(24))
    result = {"ok": True, "accepted": True, "steps": steps}
    automaton = {"states": [{"id": "q0", "initial": True, "final": True}]}
    trace = _trace(result, automaton)
    assert trace["total"] == 25
    assert trace["omitted"] == 1
    assert trace["gap"] == "Se omite 1 paso."
    assert trace["steps"][0]["index"] == 0
    assert trace["steps"][1]["index"] == 2


def test_a_missing_result_does_not_invent_steps():
    trace = _trace(None, None)
    assert trace["ok"] is False
    assert trace["summary"] == "No pude simular."
    assert trace["steps"] == []
    assert trace["visited"] == []
