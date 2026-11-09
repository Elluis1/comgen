"""Traza de la cinta en la pantalla. No abre Ollama."""

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.turing import (
    MAX_CELLS,
    MAX_TRACE_STEPS,
    TuringError,
    TuringMachine,
    TuringState,
    TuringTransition,
    run,
)
from app.turing_jflap import export_turing_jflap

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "cinta_runner.js"


def _edge(state: str, read: str, to: str, write: str, move: str) -> TuringTransition:
    return TuringTransition(state, read, to, write, move)


def _an_bn() -> TuringMachine:
    return TuringMachine(
        states=[
            TuringState("q0", initial=True),
            TuringState("q1"),
            TuringState("q2"),
            TuringState("q3"),
            TuringState("q4"),
            TuringState("qf", final=True),
        ],
        tape_alphabet=["a", "b", "X", "Y", "_"],
        blank="_",
        description="a^n b^n, n mayor o igual que 1",
        transitions=[
            _edge("q0", "a", "q1", "X", "R"),
            _edge("q1", "a", "q1", "a", "R"),
            _edge("q1", "Y", "q1", "Y", "R"),
            _edge("q1", "b", "q2", "Y", "L"),
            _edge("q2", "a", "q2", "a", "L"),
            _edge("q2", "Y", "q2", "Y", "L"),
            _edge("q2", "X", "q3", "X", "R"),
            _edge("q3", "a", "q1", "X", "R"),
            _edge("q3", "Y", "q4", "Y", "R"),
            _edge("q4", "Y", "q4", "Y", "R"),
            _edge("q4", "_", "qf", "_", "S"),
        ],
    )


def _right_only() -> TuringMachine:
    return TuringMachine(
        states=[TuringState("q0", initial=True)],
        tape_alphabet=["a", "_"],
        blank="_",
        transitions=[
            _edge("q0", "a", "q0", "a", "R"),
            _edge("q0", "_", "q0", "_", "R"),
        ],
    )


def _one_step() -> TuringMachine:
    return TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=["a", "_"],
        blank="_",
        description="un paso",
        transitions=[_edge("q0", "a", "qf", "a", "R")],
    )


def _trace(result, options=None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede armar la traza de la cinta.")
    payload = {"result": result, "options": options or {}}
    completed = subprocess.run(
        [node, str(RUNNER)],
        input=json.dumps(payload, ensure_ascii=False),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(completed.stdout)


def _long_steps(count: int) -> dict:
    steps = []
    for index in range(count):
        steps.append({
            "state": "q1" if index else "q0",
            "tape": ["a", "b"],
            "head": index % 2,
            "status": "running",
            "message": "",
        })
    steps[-1]["status"] = "reject"
    steps[-1]["message"] = "Rechaza: falta la transición de «q1» leyendo «b»."
    return {
        "status": "reject",
        "accepted": False,
        "message": steps[-1]["message"],
        "state": "q1",
        "tape": ["a", "b"],
        "head": 1,
        "steps_run": count - 1,
        "steps": steps,
    }


def test_page_offers_the_tape_trace_without_touching_the_automaton():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/cinta.js")
        app_js = client.get("/static/app.js")
        styles = client.get("/static/styles.css")
        delta = client.get("/static/delta.js")
        diagram = client.get("/static/diagram.js")
    assert page.status_code == 200
    text = page.text
    assert 'id="fresh" type="button"' in text
    assert "Nuevo autómata" in text
    assert 'id="download"' in text
    assert 'id="remember"' in text
    assert 'id="determinize"' in text
    assert 'id="regex"' in text
    assert 'id="grammar"' in text
    assert 'id="accion-guia"' in text
    assert 'id="turing-file"' in text
    assert 'id="turing-runner"' in text
    assert 'id="turing-word"' in text
    assert 'id="turing-result"' in text
    assert 'id="turing-steps"' in text
    assert 'id="turing-steps-wrap"' in text
    assert "Simular máquina" in text
    assert "Cargar máquina" in text
    assert "Elegir archivo" in text
    assert "Ningún archivo elegido" in text
    cinta_at = text.index("/static/cinta.js")
    app_at = text.index("/static/app.js")
    assert cinta_at < app_at
    assert script.status_code == 200
    assert "tapeTrace" in script.text
    assert "STEP_LIMIT = 24" in script.text
    assert "CELL_LIMIT = 24" in script.text
    assert app_js.status_code == 200
    assert "ComgenCinta.tapeTrace" in app_js.text
    assert "trace: true" in app_js.text
    assert "turing/run" in app_js.text
    assert "Se cortó la conexión con el servidor." in app_js.text
    assert "step.cells" in app_js.text
    assert 'id: "turing-more"' in app_js.text
    assert styles.status_code == 200
    assert ".cinta-cell.is-head" in styles.text
    assert ".run-result.timeout" in styles.text
    assert "[hidden]" in styles.text
    assert delta.status_code == 200
    assert "ROW_LIMIT = 32" in delta.text
    assert "COL_LIMIT = 32" in delta.text
    assert diagram.status_code == 200
    assert "STATE_LIMIT = 16" in diagram.text


def test_ab_shows_the_tape_the_head_and_the_state():
    result = run(_an_bn(), "ab", trace=True)
    trace = _trace(result.dump())
    assert trace["ok"] is True
    assert trace["verdict"] == "Acepta"
    assert trace["summary"].startswith("Acepta")
    assert trace["limit"] == 24
    assert trace["cellLimit"] == 24
    first = trace["steps"][0]
    assert first["index"] == 0
    assert first["state"] == "q0"
    assert first["head"] == 0
    assert first["text"].startswith("Empieza en q0.")
    assert "posición 1" in first["text"]
    assert "sobre a" in first["text"]
    assert first["cells"][0]["head"] is True
    assert first["cells"][0]["text"] == "a"
    assert [cell["text"] for cell in first["cells"]] == ["a", "b"]
    last = trace["steps"][-1]
    assert last["state"] == "qf"
    assert any(cell["head"] for cell in last["cells"])
    assert trace["omitted"] == 0
    assert trace["moreLabel"] == ""


def test_a_rejection_and_a_timeout_are_in_spanish():
    rejected = run(_an_bn(), "aab")
    reject_trace = _trace(rejected.dump())
    assert reject_trace["ok"] is True
    assert reject_trace["verdict"] == "Rechaza"
    assert reject_trace["accepted"] is False
    assert "Rechaza" in reject_trace["summary"]
    assert "No terminó" not in reject_trace["summary"]
    assert "falta la transición" in reject_trace["summary"]

    timeout = {
        "status": "timeout",
        "accepted": None,
        "message": "No terminó: la cinta llegó a 4096 celdas.",
        "state": "q0",
        "tape": ["a", "_"],
        "head": 1,
        "steps_run": 1,
        "steps": [
            {"state": "q0", "tape": ["a"], "head": 0, "status": "running"},
            {
                "state": "q0",
                "tape": ["a", "_"],
                "head": 1,
                "status": "timeout",
                "message": "No terminó: la cinta llegó a 4096 celdas.",
            },
        ],
    }
    trace = _trace(timeout)
    assert trace["verdict"] == "No terminó"
    assert trace["accepted"] is None
    assert trace["summary"] == "No terminó: la cinta llegó a 4096 celdas."
    assert trace["steps"][1]["cells"][1]["text"] == "␣"
    assert trace["steps"][1]["cells"][1]["blank"] is True
    assert "el blanco" in trace["steps"][1]["text"]


def test_a_long_run_shows_the_start_and_the_end_until_the_button():
    trace = _trace(_long_steps(30))
    assert trace["total"] == 30
    assert trace["omitted"] == 6
    assert trace["gap"] == "Se omiten 6 pasos."
    assert trace["moreLabel"] == "Ver los 30 pasos"
    assert len(trace["steps"]) == 24
    assert trace["steps"][0]["index"] == 0
    assert trace["steps"][0]["text"].startswith("Empieza en q0.")
    assert trace["steps"][1]["index"] == 7
    assert trace["steps"][-1]["index"] == 29
    assert trace["limit"] == 24

    opened = _trace(_long_steps(30), {"expanded": True})
    assert opened["omitted"] == 0
    assert opened["gap"] == ""
    assert opened["moreLabel"] == "Ver menos"
    assert len(opened["steps"]) == 30
    assert opened["steps"][1]["index"] == 1
    assert opened["steps"][-1]["index"] == 29


def test_one_omitted_step_uses_the_singular():
    trace = _trace(_long_steps(25))
    assert trace["omitted"] == 1
    assert trace["gap"] == "Se omite 1 paso."
    assert trace["steps"][1]["index"] == 2


def test_a_tape_of_4096_cells_stays_inside_the_window():
    tape = ["b"] * 4096
    result = {
        "status": "timeout",
        "accepted": None,
        "message": "No terminó: se agotaron los 10000 pasos.",
        "state": "q0",
        "tape": tape,
        "head": 0,
        "steps": [{"state": "q0", "tape": tape, "head": 0, "status": "timeout"}],
    }
    trace = _trace(result)
    step = trace["steps"][0]
    assert len(step["cells"]) == 24
    assert step["leading"] == 0
    assert step["trailing"] == 4096 - 24
    assert step["cells"][0]["head"] is True
    assert all(cell["text"] == "b" for cell in step["cells"])

    at_the_end = _trace({
        **result,
        "head": 4095,
        "steps": [{"state": "q0", "tape": tape, "head": 4095, "status": "timeout"}],
    })
    end = at_the_end["steps"][0]
    assert len(end["cells"]) == 24
    assert end["trailing"] == 0
    assert end["leading"] == 4096 - 24
    assert end["cells"][-1]["head"] is True
    assert end["head"] == 4095


def test_zero_is_a_symbol_and_a_mark_is_quoted():
    mark = "\u0301"
    result = {
        "status": "accept",
        "accepted": True,
        "message": "Acepta: se detuvo en el estado final «0».",
        "state": 0,
        "tape": [0, mark, "q0, q1"],
        "head": 0,
        "steps": [{
            "state": 0,
            "tape": [0, mark, "q0, q1"],
            "head": 1,
            "status": "accept",
        }],
    }
    trace = _trace(result)
    step = trace["steps"][0]
    assert step["state"] == "0"
    assert "épsilon" not in step["text"]
    assert step["cells"][0]["text"] == "0"
    assert step["cells"][1]["text"].startswith("«")
    assert mark in step["cells"][1]["text"]
    assert step["cells"][1]["head"] is True
    assert step["cells"][2]["text"].startswith("«")
    named = _trace({
        "status": "reject",
        "accepted": False,
        "message": "Rechaza.",
        "state": "q0, q1",
        "tape": ["a"],
        "head": 0,
        "steps": [{"state": "q0, q1", "tape": ["a"], "head": 0}],
    })
    assert named["steps"][0]["text"].startswith("Empieza en «q0, q1».")


def test_a_collapsed_trace_marks_each_gap_where_the_steps_are_missing():
    """La vista de 24 no junta el hueco que no se guardó con el corte de al lado.

    Con tope 256, una corrida de 4096 configuraciones deja índices
    [0, 1, …, 254, 4095]. La vista cerrada muestra [0, 233…254, 4095].
    Entre el paso 1 y el 234 faltan 232, que sí se guardaron. Los 3840
    que no se copiaron (pasos 256 a 4095) están entre el 255 y el 4096.
    """
    indexes = list(range(255)) + [4095]
    steps = []
    for index in indexes:
        steps.append({
            "index": index,
            "state": "q0",
            "tape": ["a"],
            "head": 0,
            "status": "running",
        })
    steps[-1]["status"] = "timeout"
    steps[-1]["message"] = "No terminó: la cinta llegó a 4096 celdas."
    result = {
        "status": "timeout",
        "accepted": None,
        "message": steps[-1]["message"],
        "state": "q0",
        "tape": ["a"],
        "head": 0,
        "steps_run": 4095,
        "trace_omitted": 3840,
        "steps": steps,
    }
    trace = _trace(result)
    shown = [step["index"] for step in trace["steps"]]
    assert shown == [0, *range(233, 255), 4095]
    assert trace["steps"][1]["gaps"] == ["Se omiten 232 pasos."]
    assert trace["steps"][1]["gapBefore"] == "Se omiten 232 pasos."
    assert trace["steps"][-1]["gaps"] == ["No se guardaron 3840 pasos."]
    assert trace["steps"][-1]["gapBefore"] == "No se guardaron 3840 pasos."
    assert all(step["gapBefore"] == "" for step in trace["steps"][2:-1])
    assert trace["gap"] == ""
    assert "4072" not in trace["steps"][1]["gapBefore"]

    opened = _trace(result, {"expanded": True})
    assert [step["index"] for step in opened["steps"]] == indexes
    assert opened["steps"][-1]["gapBefore"] == "No se guardaron 3840 pasos."
    assert all(step["gapBefore"] == "" for step in opened["steps"][:-1])
    assert opened["gap"] == ""


def test_a_window_cut_and_an_unstored_stretch_in_the_same_place_are_both_marked():
    # 0, y después 5…39: faltan 1…4, que no se guardaron. La vista de 24
    # esconde además 5…16, que sí están. Los dos avisos van entre el
    # primero y el 18, en ese orden.
    indexes = [0, *range(5, 40)]
    steps = []
    for index in indexes:
        steps.append({
            "index": index,
            "state": "q0",
            "tape": ["a"],
            "head": 0,
            "status": "running",
        })
    steps[-1]["status"] = "timeout"
    steps[-1]["message"] = "No terminó."
    result = {
        "status": "timeout",
        "accepted": None,
        "message": "No terminó.",
        "state": "q0",
        "tape": ["a"],
        "head": 0,
        "steps_run": 39,
        "trace_omitted": 4,
        "steps": steps,
    }
    trace = _trace(result)
    shown = trace["steps"]
    assert [step["index"] for step in shown] == [0, *range(17, 40)]
    assert shown[1]["gaps"] == ["No se guardaron 4 pasos.", "Se omiten 12 pasos."]
    assert shown[1]["gapBefore"] == "No se guardaron 4 pasos. Se omiten 12 pasos."
    assert all(step["gapBefore"] == "" for step in shown[2:])
    assert trace["gap"] == ""


def test_a_real_capped_run_marks_the_unstored_steps_on_the_last_shown_one():
    capped = run(_right_only(), "a", trace=True, trace_cap=30, max_cells=80)
    dumped = capped.dump()
    stored = [step["index"] for step in dumped["steps"]]
    assert stored[0] == 0
    assert stored[-1] == capped.steps_run
    assert stored[:-1] == list(range(len(stored) - 1))
    assert stored[-1] > stored[-2] + 1
    view = _trace(dumped)
    shown = view["steps"]
    assert shown[0]["index"] == 0
    assert shown[-1]["index"] == capped.steps_run
    hidden = shown[1]["index"] - shown[0]["index"] - 1
    assert shown[1]["gapBefore"] == f"Se omiten {hidden} pasos."
    hole = shown[-1]["index"] - stored[-2] - 1
    assert hole == dumped["trace_omitted"]
    assert shown[-1]["gapBefore"] == f"No se guardaron {hole} pasos."
    assert all(step["gapBefore"] == "" for step in shown[2:-1])
    lumped = shown[-1]["index"] - shown[0]["index"] + 1 - len(shown)
    assert lumped != hidden
    assert view["gap"] == ""
    assert dumped["blank"] == "_"


def test_a_blank_other_than_underscore_is_the_blank_cell():
    machine = TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=["a", "_", "□"],
        blank="□",
        transitions=[_edge("q0", "a", "qf", "_", "R")],
    )
    result = run(machine, "a", trace=True)
    dumped = result.dump()
    assert dumped["blank"] == "□"
    assert dumped["tape"] == ["_", "□"]
    assert dumped["head"] == 1
    trace = _trace(dumped)
    last = trace["steps"][-1]
    assert [cell["text"] for cell in last["cells"]] == ["_", "␣"]
    assert last["cells"][0]["blank"] is False
    assert last["cells"][0]["spoken"] == "_"
    assert last["cells"][1]["blank"] is True
    assert last["cells"][1]["spoken"] == "blanco"
    assert last["cells"][1]["head"] is True
    assert "posición 2" in last["text"]
    assert "el blanco" in last["text"]
    assert "□" not in last["text"]
    assert "␣" not in trace["steps"][0]["text"]
    # El mismo «_» sigue siendo el blanco cuando la máquina lo usa.
    underscore = _trace({
        "status": "accept",
        "accepted": True,
        "message": "Acepta.",
        "state": "qf",
        "tape": ["_"],
        "head": 0,
        "blank": "_",
        "steps": [{"state": "qf", "tape": ["_"], "head": 0, "status": "accept"}],
    })
    assert underscore["steps"][0]["cells"][0]["text"] == "␣"
    assert underscore["steps"][0]["cells"][0]["blank"] is True


def test_a_hole_in_the_stored_steps_says_they_were_not_kept():
    steps = [
        {"index": 0, "state": "q0", "tape": ["a"], "head": 0, "status": "running"},
        {"index": 1, "state": "q0", "tape": ["a", "_"], "head": 1, "status": "running"},
        {"index": 40, "state": "q0", "tape": ["a", "_"], "head": 1, "status": "timeout"},
    ]
    result = {
        "status": "timeout",
        "accepted": None,
        "message": "No terminó: la cinta llegó a 4096 celdas.",
        "state": "q0",
        "tape": ["a", "_"],
        "head": 1,
        "steps_run": 40,
        "trace_omitted": 38,
        "steps": steps,
    }
    trace = _trace(result)
    assert trace["hole"] == 38
    assert trace["verdict"] == "No terminó"
    assert trace["steps"][2]["gapBefore"] == "No se guardaron 38 pasos."
    assert trace["moreLabel"] == ""
    assert trace["gap"] == ""


def test_a_missing_result_does_not_invent_a_tape():
    trace = _trace(None)
    assert trace["ok"] is False
    assert trace["summary"] == "No pude simular."
    assert trace["steps"] == []
    assert trace["verdict"] == ""


def test_trace_is_optional_and_the_cap_does_not_copy_every_cell():
    machine = _one_step()
    xml = export_turing_jflap(machine)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        loaded = client.post(f"/api/sessions/{session_id}/turing", content=xml.encode("utf-8"))
        assert loaded.status_code == 200
        plain = client.post(f"/api/sessions/{session_id}/turing/run", json={"word": "a"})
        assert plain.status_code == 200
        assert plain.json()["steps"] == []
        assert plain.json()["accepted"] is True
        assert "trace_omitted" not in plain.json()
        traced = client.post(
            f"/api/sessions/{session_id}/turing/run",
            json={"word": "a", "trace": True},
        )
        assert traced.status_code == 200
        body = traced.json()
        assert body["accepted"] is True
        assert body["steps"]
        assert body["steps"][0]["state"] == "q0"
        assert body["steps"][0]["head"] == 0
        assert body["steps"][-1]["state"] == "qf"
        assert "tape" in body["steps"][-1]
        assert "trace_omitted" not in body

    short = run(_an_bn(), "ab", trace=True, trace_cap=MAX_TRACE_STEPS)
    full = run(_an_bn(), "ab", trace=True)
    assert short.trace_omitted == 0
    assert len(short.steps) == len(full.steps) == short.steps_run + 1
    assert "index" not in short.dump()["steps"][0]
    assert short.steps[-1].status == "accept"

    started = time.perf_counter()
    capped = run(_right_only(), "a", trace=True, trace_cap=MAX_TRACE_STEPS)
    assert time.perf_counter() - started < 0.5
    assert capped.status == "timeout"
    assert capped.message == f"No terminó: la cinta llegó a {MAX_CELLS} celdas."
    assert len(capped.steps) == MAX_TRACE_STEPS
    assert capped.trace_omitted == (capped.steps_run + 1) - MAX_TRACE_STEPS
    assert capped.step_indexes[0] == 0
    assert capped.step_indexes[-1] == capped.steps_run
    assert len(capped.steps[0].tape) == 1
    assert len(capped.steps[1].tape) == 2
    assert len(capped.steps[-1].tape) == MAX_CELLS
    dumped = capped.dump()
    assert dumped["trace_omitted"] == capped.trace_omitted
    assert dumped["steps"][0]["index"] == 0
    assert dumped["steps"][-1]["index"] == capped.steps_run
    assert len(dumped["steps"][-1]["tape"]) == MAX_CELLS
    view = _trace(dumped)
    assert view["verdict"] == "No terminó"
    assert "No terminó" in view["summary"]
    assert len(view["steps"][0]["cells"]) <= 24
    assert len(view["steps"][-1]["cells"]) == 24
    assert view["moreLabel"] == f"Ver los {MAX_TRACE_STEPS} pasos guardados"
    assert view["steps"][0]["index"] == 0
    assert view["steps"][-1]["index"] == capped.steps_run
    # [0, 233…254, 4095]: el corte de la vista y el tramo que no se copió
    # no son el mismo hueco. 4072 sería la suma, y no va entre el 1 y el 234.
    assert [step["index"] for step in view["steps"]] == [0, *range(233, 255), capped.steps_run]
    assert view["steps"][1]["gapBefore"] == "Se omiten 232 pasos."
    assert view["steps"][-1]["gapBefore"] == (
        f"No se guardaron {capped.steps_run - (MAX_TRACE_STEPS - 2) - 1} pasos."
    )
    assert view["gap"] == ""

    plain_run = run(_right_only(), "a", trace=False)
    assert plain_run.steps == ()
    assert plain_run.message == capped.message
    assert "trace_omitted" not in plain_run.dump()


def test_a_bad_trace_cap_is_an_error_in_spanish():
    machine = _one_step()
    with pytest.raises(TuringError, match="entero entre 2"):
        run(machine, "a", trace=True, trace_cap=True)
    with pytest.raises(TuringError, match="entero entre 2"):
        run(machine, "a", trace=True, trace_cap=1)
    with pytest.raises(TuringError, match="pide guardar los pasos"):
        run(machine, "a", trace=False, trace_cap=8)
