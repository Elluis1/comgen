import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "word_hint_runner.js"


def _call(fn: str, *args):
    node = shutil.which("node")
    if node is None:
        pytest.skip("No está node: sin eso no se puede armar el texto de la cadena.")
    result = subprocess.run(
        [node, str(RUNNER), json.dumps({"fn": fn, "args": list(args)})],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def test_page_names_the_empty_string_and_loads_the_hint_script():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/word_hint.js")
        app_js = client.get("/static/app.js")
        styles = client.get("/static/styles.css")
        examples = client.get("/api/examples")
    assert page.status_code == 200
    text = page.text
    assert 'id="fresh" type="button"' in text
    assert "Nuevo autómata" in text
    assert 'id="word-hint"' in text
    assert 'id="probes"' in text
    assert "cadena vacía" in text
    assert 'aria-describedby="word-hint run-mode-hint run-result playback-live"' in text
    hint_at = text.index("/static/word_hint.js")
    app_at = text.index("/static/app.js")
    assert hint_at < app_at
    assert script.status_code == 200
    assert "alphabetHint" in script.text
    assert "resultWithWord" in script.text
    assert app_js.status_code == 200
    assert "ComgenWord.alphabetHint" in app_js.text
    assert "ComgenWord.probeWords" in app_js.text
    assert "ComgenWord.resultWithWord" in app_js.text
    assert styles.status_code == 200
    assert ".probes[hidden]" in styles.text
    assert examples.status_code == 200
    by_id = {item["id"]: item for item in examples.json()}
    assert by_id["paridad"]["probes"] == ["", "0", "1", "11"]
    assert by_id["termina-en-01"]["probes"] == ["", "01", "1", "001"]
    assert by_id["a-estrella"]["probes"] == ["", "a", "aa", "b"]


def test_the_hint_names_the_alphabet_and_the_empty_string():
    assert _call("alphabetHint", ["0", "1"]) == (
        "Alfabeto {0, 1}. Si dejás el campo vacío, se prueba la cadena vacía."
    )
    assert _call("alphabetHint", ["a", "b"]) == (
        "Alfabeto {a, b}. Si dejás el campo vacío, se prueba la cadena vacía."
    )
    assert _call("alphabetHint", []) == "Si dejás el campo vacío, se prueba la cadena vacía."
    assert _call("alphabetHint", None) == "Si dejás el campo vacío, se prueba la cadena vacía."
    assert "«a, b»" in _call("alphabetHint", ["a, b", "c"])


def test_the_placeholder_follows_the_alphabet():
    assert _call("placeholderFor", ["0", "1"]) == "0101"
    assert _call("placeholderFor", ["a", "b"]) == "abab"
    assert _call("placeholderFor", []) == ""
    assert _call("placeholderFor", ["aa", "bb"]) == "aabb"


def test_example_probes_keep_the_empty_string_first_and_skip_duplicates():
    assert _call("probeWords", ["0", "1"], ["", "0", "1", "11"]) == ["", "0", "1", "11"]
    assert _call("probeWords", ["a", "b"], ["", "a", "aa", "b"]) == ["", "a", "aa", "b"]
    assert _call("probeWords", ["0", "1"], None) == ["", "0", "1"]
    assert _call("probeWords", ["a", "b", "c", "d", "e"], None) == [""]
    assert _call("probeLabel", "") == "vacía"
    assert _call("probeLabel", "11") == "11"
    assert _call("probeSpoken", "") == "Probar la cadena vacía"
    assert _call("probeSpoken", "01") == "Probar la cadena «01»"
    long_word = "a" * 40
    assert long_word not in _call("probeWords", ["a"], ["", long_word, "aa"])


def test_the_result_names_the_word_without_rewriting_an_error():
    summary = "Acepta. Termina en q0, que es final."
    assert _call("resultWithWord", summary, "") == (
        "Acepta la cadena vacía. Termina en q0, que es final."
    )
    assert _call("resultWithWord", "Rechaza. Termina en q1, que no es final.", "1") == (
        "Rechaza «1». Termina en q1, que no es final."
    )
    assert _call("resultWithWord", "Rechaza. Lee b y no queda en ningún estado.", "b") == (
        "Rechaza «b». Lee b y no queda en ningún estado."
    )
    error = "«2» no está en el alfabeto."
    assert _call("resultWithWord", error, "2") == error
    assert _call("resultWithWord", summary, 0) == "Acepta «0». Termina en q0, que es final."
    quoted = _call("resultWithWord", summary, "a, b")
    assert quoted.startswith("Acepta «a, b».")
