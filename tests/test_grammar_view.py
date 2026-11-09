import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "grammar_view_runner.js"

PARITY = {
    "start": "S",
    "text": "S → 0S | 1A | ε\nA → 0A | 1S",
    "jflap": True,
}


def _view(grammar: dict, options: dict | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede armar la gramática de la pantalla.")
    result = subprocess.run(
        [node, str(RUNNER), json.dumps(grammar), json.dumps(options or {})],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def test_page_loads_the_grammar_view_before_the_app():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/grammar_view.js")
        app_js = client.get("/static/app.js")
    assert page.status_code == 200
    text = page.text
    assert 'id="grammar"' in text
    assert 'id="fresh"' in text
    assert "Nuevo autómata" in text
    view_at = text.index("/static/grammar_view.js")
    app_at = text.index("/static/app.js")
    assert view_at < app_at
    assert script.status_code == 200
    assert "grammarView" in script.text
    assert "LINE_LIMIT = 32" in script.text
    assert app_js.status_code == 200
    assert "ComgenGrammar.grammarView" in app_js.text
    assert "GRAMMAR_LINE_LIMIT = 32" in app_js.text
    assert "grammar-line" in app_js.text
    assert "grammar-download" in app_js.text


def test_parity_marks_the_start_and_the_empty_word():
    view = _view(PARITY)
    assert view["total"] == 2
    assert view["hidden"] == 0
    assert view["legend"] == "S es el símbolo inicial. Donde dice ε, la derivación puede terminar."
    start, other = view["lines"]
    assert start["variable"] == "S"
    assert start["start"] is True
    assert [alt["text"] for alt in start["alternatives"]] == ["0S", "1A", "ε"]
    assert [alt["empty"] for alt in start["alternatives"]] == [False, False, True]
    assert start["spoken"] == "S, símbolo inicial: 0S, o 1A, o épsilon"
    assert other["variable"] == "A"
    assert other["start"] is False
    assert other["spoken"] == "A: 0A, o 1S"
    assert all(alt["empty"] is False for alt in other["alternatives"])


def test_a_quoted_bar_stays_one_alternative_and_zero_is_not_epsilon():
    view = _view({
        "start": "A | B",
        "text": "«A | B» → «|» C | 0 | ε\n«q0, q1» → a «q0, q1»",
    })
    first, second = view["lines"]
    assert first["start"] is True
    assert first["variable"] == "«A | B»"
    assert [alt["text"] for alt in first["alternatives"]] == ["«|» C", "0", "ε"]
    assert first["alternatives"][1]["empty"] is False
    assert first["alternatives"][2]["empty"] is True
    assert "«A | B», símbolo inicial" in first["spoken"]
    assert second["start"] is False
    assert second["alternatives"] == [{"text": "a «q0, q1»", "empty": False}]
    assert second["spoken"] == "«q0, q1»: a «q0, q1»"
    assert "q0, q1" in second["spoken"]
    assert second["spoken"].count("q0") == 2


def test_only_the_first_lines_are_shown():
    lines = [f"N{index} → aN{index}" for index in range(40)]
    lines[0] = "S → aN1 | ε"
    view = _view({"start": "S", "text": "\n".join(lines)})
    assert view["total"] == 40
    assert view["hidden"] == 8
    assert len(view["lines"]) == 32
    assert view["lines"][0]["variable"] == "S"
    assert view["lines"][-1]["variable"] == "N31"
    assert "N32" not in [line["variable"] for line in view["lines"]]

    short = _view({"start": "S", "text": "\n".join(lines)}, {"limit": 2})
    assert len(short["lines"]) == 2
    assert short["hidden"] == 38


def test_an_arrow_inside_quotes_does_not_split_the_name():
    view = _view({
        "start": "A → B",
        "text": "«A → B» → aS | ε\nS → « → »A | 0 | ε",
    })
    named, other = view["lines"]
    assert named["ok"] is True
    assert named["variable"] == "«A → B»"
    assert named["start"] is True
    assert [alt["text"] for alt in named["alternatives"]] == ["aS", "ε"]
    assert named["alternatives"][1]["empty"] is True
    assert named["spoken"].startswith("«A → B», símbolo inicial")
    assert other["start"] is False
    assert [alt["text"] for alt in other["alternatives"]] == ["« → »A", "0", "ε"]
    assert other["alternatives"][1]["empty"] is False
    assert other["alternatives"][2]["empty"] is True


def test_a_line_without_an_arrow_stays_whole():
    view = _view({"start": "S", "text": "esto no es una producción\nS → ε"})
    assert view["lines"][0]["ok"] is False
    assert view["lines"][0]["raw"] == "esto no es una producción"
    assert view["lines"][0]["spoken"] == "esto no es una producción"
    assert view["lines"][1]["start"] is True
    assert view["lines"][1]["alternatives"] == [{"text": "ε", "empty": True}]
    assert view["lines"][1]["spoken"] == "S, símbolo inicial: épsilon"
