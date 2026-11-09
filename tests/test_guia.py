import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "guia_runner.js"
GUIA = ROOT / "static" / "guia.js"


def _call(fn: str, *args):
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede armar la guía.")
    result = subprocess.run(
        [node, str(RUNNER), json.dumps({"fn": fn, "args": list(args)}, ensure_ascii=False)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def test_page_shows_the_guide_before_the_app():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/guia.js")
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
    assert 'id="accion-guia"' in text
    assert 'aria-describedby="accion-guia"' in text
    guia_at = text.index("/static/guia.js")
    app_at = text.index("/static/app.js")
    assert guia_at < app_at
    empty = _call("actionGuide", None)
    assert empty["text"] in text
    assert script.status_code == 200
    assert "actionGuide" in script.text
    assert "kindBadge" in script.text
    assert app_js.status_code == 200
    assert "ComgenGuia.actionGuide" in app_js.text
    assert "ComgenGuia.kindBadge" in app_js.text
    assert "Es un AFN. Determinizar arma el AFD por subconjuntos" not in app_js.text
    assert styles.status_code == 200
    assert ".accion-guia" in styles.text
    assert ".badge.is-afn" in styles.text
    assert "[hidden]" in styles.text


def test_a_dfa_names_the_expression_and_an_nfa_asks_to_determinize():
    parity = _call("actionGuide", EXAMPLES["paridad"].automaton.model_dump(by_alias=True))
    epsilon = _call("actionGuide", EXAMPLES["a-estrella"].automaton.model_dump(by_alias=True))
    assert parity["kind"] == "afd"
    assert "autómata finito determinista" in parity["text"]
    assert "expresión" in parity["text"]
    assert "gramática" in parity["text"]
    assert epsilon["kind"] == "afn"
    assert "no determinista" in epsilon["text"]
    assert "Determinizar" in epsilon["text"]
    assert "ya se puede bajar" in epsilon["text"]
    badge = _call("kindBadge", EXAMPLES["paridad"].automaton.model_dump(by_alias=True))
    nfa = _call("kindBadge", EXAMPLES["a-estrella"].automaton.model_dump(by_alias=True))
    assert badge == {
        "shown": True,
        "kind": "afd",
        "text": "AFD · determinista",
        "spoken": "Autómata finito determinista",
    }
    assert nfa["text"] == "AFN · no determinista"
    assert nfa["spoken"] == "Autómata finito no determinista"


def test_only_a_real_boolean_chooses_dfa_or_nfa():
    assert _call("actionGuide", None)["kind"] == "vacio"
    assert _call("actionGuide", [])["kind"] == "vacio"
    assert _call("actionGuide", "AFD")["kind"] == "vacio"
    assert _call("kindBadge", None)["shown"] is False
    for value in (1, 0, "true", "false", None):
        guide = _call("actionGuide", {"deterministic": value, "transitions": list(range(4000))})
        badge = _call("kindBadge", {"deterministic": value})
        assert guide["kind"] == "duda"
        assert "no dice si es un AFD o un AFN" in guide["text"]
        assert badge["kind"] == "duda"
        assert badge["text"] == "Autómata"
        assert "Determinizar" in guide["text"]
