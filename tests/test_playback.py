import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "playback_runner.js"
TRACE = ROOT / "tests" / "trace_runner.js"


def _node(runner: Path, result, automaton) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede armar la prueba lenta.")
    payload = {"result": result, "automaton": automaton}
    completed = subprocess.run(
        [node, str(runner), json.dumps(payload)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(completed.stdout)


def _playback(result, automaton) -> dict:
    return _node(RUNNER, result, automaton)


def _trace(result, automaton) -> dict:
    return _node(TRACE, result, automaton)


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


def test_page_offers_a_fast_mode_and_a_slow_one():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/playback.js")
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
    assert 'id="run-steps"' in text
    assert 'id="run-result"' in text
    assert 'name="run-mode" value="rapida" checked' in text
    assert 'name="run-mode" value="lenta"' in text
    assert "Prueba rápida" in text
    assert "Prueba lenta" in text
    assert "Paso a paso" in text
    assert ">Reproducir<" in text
    assert ">Paso anterior<" in text
    assert ">Paso siguiente<" in text
    assert ">Reiniciar<" in text
    assert "Velocidad" in text
    assert 'id="play-speed"' in text
    assert 'id="playback"' in text
    assert 'id="tape"' in text
    assert 'aria-live="polite"' in text
    playback_at = text.index("/static/playback.js")
    app_at = text.index("/static/app.js")
    assert playback_at < app_at
    assert script.status_code == 200
    assert "function playback(" in script.text
    assert app_js.status_code == 200
    assert "ComgenPlayback.playback" in app_js.text
    assert "ComgenTrace.simulationTrace" in app_js.text
    assert 'button[type="submit"]' in app_js.text
    assert "prefers-reduced-motion" in app_js.text
    assert "data-to" in app_js.text
    assert styles.status_code == 200
    assert "prefers-reduced-motion" in styles.text
    assert ".playback-dot" in styles.text
    assert ".tape-cell.is-stuck" in styles.text


def test_parity_eleven_steps_the_tape_and_ends_accepting():
    result, automaton = _run("paridad", "11")
    play = _playback(result, automaton)
    trace = _trace(result, automaton)
    assert play["ok"] is True
    assert play["accepted"] is True
    assert play["verdict"] == "Acepta"
    assert play["tape"] == ["1", "1"]
    assert play["stuckIndex"] == -1
    assert play["stopped"] is False
    assert [frame["kind"] for frame in play["frames"]] == ["start", "read", "read", "verdict"]
    assert [frame["text"] for frame in play["frames"] if frame["kind"] != "verdict"] == [
        step["text"] for step in trace["steps"]
    ]
    assert play["frames"][-1]["text"] == trace["summary"] == "Acepta. Termina en q0, que es final."
    assert play["frames"][1]["states"] == ["q1"]
    assert play["frames"][1]["tapeIndex"] == 0
    assert play["frames"][1]["readCount"] == 0
    assert play["frames"][1]["edges"] == [{"from": "q0", "to": "q1", "symbol": "1"}]
    assert play["frames"][1]["cells"] == [{"from": "q0", "symbol": "1"}]
    assert play["frames"][2]["edges"] == [{"from": "q1", "to": "q0", "symbol": "1"}]
    assert play["frames"][2]["states"] == ["q0"]
    assert play["frames"][-1]["readCount"] == 2
    assert play["frames"][-1]["edges"] == []


def test_parity_one_rejects_and_a_loop_stays():
    rejected, automaton = _run("paridad", "1")
    play = _playback(rejected, automaton)
    assert play["accepted"] is False
    assert play["frames"][-1]["text"] == "Rechaza. Termina en q1, que no es final."
    assert play["frames"][1]["edges"] == [{"from": "q0", "to": "q1", "symbol": "1"}]

    stayed, _automaton = _run("paridad", "0")
    loop = _playback(stayed, automaton)
    assert loop["frames"][1]["text"] == "Lee 0 y se queda en q0, que es final."
    assert loop["frames"][1]["edges"] == [{"from": "q0", "to": "q0", "symbol": "0"}]


def test_the_empty_word_is_only_the_start_and_the_verdict():
    result, automaton = _run("paridad", "")
    play = _playback(result, automaton)
    trace = _trace(result, automaton)
    assert play["empty"] is True
    assert play["tape"] == []
    assert [frame["kind"] for frame in play["frames"]] == ["start", "verdict"]
    assert play["frames"][0]["text"] == trace["steps"][0]["text"] == "Empieza en q0, que es final."
    assert play["frames"][0]["edges"] == []
    assert play["frames"][-1]["text"] == "Acepta. Termina en q0, que es final."


def test_epsilon_moves_light_up_and_a_missing_arrow_stops_the_tape():
    accepted, automaton = _run("a-estrella", "a")
    play = _playback(accepted, automaton)
    trace = _trace(accepted, automaton)
    assert play["accepted"] is True
    assert play["frames"][0]["text"] == trace["steps"][0]["text"]
    assert "épsilon" in play["frames"][0]["text"]
    assert play["frames"][0]["states"] == ["q0", "q1", "q2"]
    assert play["frames"][0]["edges"] == [
        {"from": "q0", "to": "q1", "symbol": ""},
        {"from": "q1", "to": "q2", "symbol": ""},
    ]
    assert play["frames"][1]["text"] == "Lee a y pasa a q2, que es final."
    assert play["frames"][1]["edges"] == [{"from": "q2", "to": "q2", "symbol": "a"}]
    assert play["frames"][1]["cells"] == [{"from": "q2", "symbol": "a"}]

    rejected, _automaton = _run("a-estrella", "ba")
    dead = _playback(rejected, automaton)
    assert dead["accepted"] is False
    assert dead["tape"] == ["b", "a"]
    assert dead["stopped"] is True
    assert dead["stuckIndex"] == 0
    assert [frame["kind"] for frame in dead["frames"]] == ["start", "stuck", "verdict"]
    assert dead["frames"][1]["states"] == []
    assert dead["frames"][1]["text"] == "Lee b y no queda en ningún estado."
    assert dead["frames"][1]["note"] == (
        "La cadena se corta: desde q0, q1 y q2 no hay una flecha con b, "
        "así que se rechaza. Lo que sigue no se lee."
    )
    assert dead["frames"][1]["edges"] == []
    assert dead["frames"][1]["cells"] == [
        {"from": "q0", "symbol": "b"},
        {"from": "q1", "symbol": "b"},
        {"from": "q2", "symbol": "b"},
    ]
    assert dead["frames"][-1]["text"] == "Rechaza. Lee b y no queda en ningún estado."
    assert dead["frames"][-1]["note"] == dead["frames"][1]["note"]
    assert dead["frames"][-1]["cells"] == dead["frames"][1]["cells"]
    assert "se corta" in dead["frames"][-1]["note"]
    assert dead["frames"][-1]["readCount"] == 0


def test_an_nfa_shows_every_active_state_and_epsilon_after_the_symbol():
    branch = _playback(
        {
            "ok": True,
            "accepted": True,
            "steps": [
                {"symbol": "", "states": ["q0"]},
                {"symbol": "a", "states": ["q1", "q2"]},
            ],
        },
        {
            "states": [
                {"id": "q0", "initial": True, "final": False},
                {"id": "q1", "initial": False, "final": True},
                {"id": "q2", "initial": False, "final": True},
            ],
            "transitions": [
                {"from": "q0", "read": "a", "to": "q1"},
                {"from": "q0", "read": "a", "to": "q2"},
            ],
        },
    )
    assert branch["frames"][1]["text"] == "Lee a y queda en q1 y q2, que son finales."
    assert branch["frames"][1]["states"] == ["q1", "q2"]
    assert branch["frames"][1]["edges"] == [
        {"from": "q0", "to": "q1", "symbol": "a"},
        {"from": "q0", "to": "q2", "symbol": "a"},
    ]
    assert branch["frames"][1]["cells"] == [{"from": "q0", "symbol": "a"}]

    closed = _playback(
        {
            "ok": True,
            "accepted": True,
            "steps": [
                {"symbol": "", "states": ["q0"]},
                {"symbol": "a", "states": ["q1", "q2"]},
            ],
        },
        {
            "states": [
                {"id": "q0", "initial": True, "final": False},
                {"id": "q1", "initial": False, "final": False},
                {"id": "q2", "initial": False, "final": True},
            ],
            "transitions": [
                {"from": "q0", "read": "a", "to": "q1"},
                {"from": "q1", "read": "", "to": "q2"},
            ],
        },
    )
    assert closed["frames"][1]["edges"] == [
        {"from": "q0", "to": "q1", "symbol": "a"},
        {"from": "q1", "to": "q2", "symbol": ""},
    ]
    assert closed["frames"][1]["text"] == "Lee a y queda en q1 y q2. q2 es final."
    assert closed["frames"][1]["cells"] == [
        {"from": "q0", "symbol": "a"},
        {"from": "q1", "symbol": ""},
    ]


def test_a_symbol_outside_the_alphabet_keeps_the_server_message():
    result, automaton = _run("paridad", "2")
    play = _playback(result, automaton)
    assert result["ok"] is False
    assert play["ok"] is False
    assert play["summary"] == result["message"]
    assert "alfabeto" in play["summary"]
    assert play["frames"] == []
    assert play["tape"] == []


def test_numeric_zero_is_a_state_and_not_epsilon():
    play = _playback(
        {
            "ok": True,
            "accepted": False,
            "steps": [
                {"symbol": "", "states": [0]},
                {"symbol": 0, "states": [0]},
            ],
        },
        {
            "states": [{"id": 0, "initial": True, "final": False}],
            "transitions": [{"from": 0, "read": 0, "to": 0}],
        },
    )
    assert play["frames"][0]["text"] == "Empieza en 0."
    assert play["frames"][1]["text"] == "Lee 0 y se queda en 0."
    assert play["frames"][1]["edges"] == [{"from": "0", "to": "0", "symbol": "0"}]
    assert "épsilon" not in play["summary"]
    assert play["frames"][-1]["text"] == "Rechaza. Termina en 0, que no es final."


def test_spaced_names_stay_in_one_piece_and_an_epsilon_cycle_stops():
    play = _playback(
        {
            "ok": True,
            "accepted": False,
            "steps": [
                {"symbol": "", "states": ["q0, q1"]},
                {"symbol": "a", "states": []},
            ],
        },
        {
            "states": [{"id": "q0, q1", "initial": True, "final": False}],
            "transitions": [],
        },
    )
    assert play["frames"][0]["text"] == "Empieza en «q0, q1»."
    assert play["frames"][1]["note"] == (
        "La cadena se corta: desde «q0, q1» no hay una flecha con a, así que se rechaza."
    )

    cycle = _playback(
        {
            "ok": True,
            "accepted": False,
            "steps": [
                {"symbol": "", "states": ["q0", "q1"]},
            ],
        },
        {
            "states": [
                {"id": "q0", "initial": True, "final": False},
                {"id": "q1", "initial": False, "final": False},
            ],
            "transitions": [
                {"from": "q0", "read": "", "to": "q1"},
                {"from": "q1", "read": "", "to": "q0"},
                {"from": "q1", "read": "", "to": "q0"},
            ],
        },
    )
    assert cycle["frames"][0]["edges"] == [
        {"from": "q0", "to": "q1", "symbol": ""},
        {"from": "q1", "to": "q0", "symbol": ""},
    ]
    assert cycle["frames"][-1]["text"] == "Rechaza. Termina en q0 y q1, que no son finales."


def test_a_long_run_keeps_every_symbol_on_the_tape():
    steps = [{"symbol": "", "states": ["q0"]}]
    for index in range(29):
        steps.append({"symbol": "a", "states": ["q1" if index % 2 == 0 else "q0"]})
    play = _playback(
        {"ok": True, "accepted": False, "steps": steps},
        {
            "states": [
                {"id": "q0", "initial": True, "final": True},
                {"id": "q1", "initial": False, "final": False},
            ],
            "transitions": [
                {"from": "q0", "read": "a", "to": "q1"},
                {"from": "q1", "read": "a", "to": "q0"},
            ],
        },
    )
    assert play["stopped"] is False
    assert len(play["tape"]) == 29
    assert len(play["frames"]) == 31
    assert play["frames"][0]["kind"] == "start"
    assert play["frames"][1]["tapeIndex"] == 0
    assert play["frames"][29]["tapeIndex"] == 28
    assert play["frames"][-1]["kind"] == "verdict"
    assert play["frames"][-1]["text"] == "Rechaza. Termina en q1, que no es final."


def test_a_missing_result_does_not_invent_a_tape():
    play = _playback(None, None)
    assert play["ok"] is False
    assert play["summary"] == "No pude simular."
    assert play["frames"] == []
    assert play["stuckIndex"] == -1
