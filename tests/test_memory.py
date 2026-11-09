import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.memory import MemoryStoreError, save, search, set_memory_path
from app.regex_lang import compile_pattern


def test_saved_solution_is_shown_to_the_model_and_not_returned_directly(tmp_path):
    set_memory_path(tmp_path / "solutions.json")
    automaton, explanation = compile_pattern("a*bbb*cc*")
    save(
        request="un afd que comience por a* siga con bbb* y termine con cc*",
        explanation=explanation,
        automaton=automaton.dump(),
        pattern="a*bbb*cc*",
    )
    seen = {}

    async def fake_chat(_settings, messages):
        seen["content"] = messages[-1]["content"]
        return json.dumps(
            {
                "kind": "regex",
                "pattern": "a*bbb*cc*",
                "description": "Cadenas de a*bbb*cc*",
                "explanation": "Revisé la memoria y el pedido es el mismo lenguaje.",
            }
        )

    phrase = "necesito un afd que comience por a* siga con bbb* y termine con cc*"
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": phrase},
            )
        body = response.json()
        assert response.status_code == 200
        assert "Memoria compartida" in seen["content"]
        assert "a*bbb*cc*" in seen["content"]
        assert body["recalled"]
        assert body["can_remember"] is True
        stored = client.post(f"/api/sessions/{session_id}/remember")
        assert stored.status_code == 200
        assert stored.json()["remembered"] is True
        assert stored.json()["memory_count"] == 1
        assert client.get("/api/memory").json()["count"] == 1
    set_memory_path(None)


def test_search_skips_a_solution_whose_alphabet_the_statement_does_not_declare(tmp_path):
    set_memory_path(tmp_path / "solutions.json")
    saved = (
        "AFD sobre el alfabeto {0, 1} que acepte las cadenas con una cantidad par de a "
        "y que no contengan la subcadena bb"
    )
    save(
        request=saved,
        explanation="Quedó un AFD binario.",
        automaton={"alphabet": ["0", "1"], "states": [], "transitions": []},
    )
    asked = saved.replace("{0, 1}", "{a, b}")
    assert search(asked) == []
    assert search(saved)[0]["request"] == saved
    set_memory_path(None)


def test_unrelated_requests_do_not_recall_the_saved_solution(tmp_path):
    set_memory_path(tmp_path / "solutions.json")
    automaton, explanation = compile_pattern("a*bbb*cc*")
    save(
        request="un afd que comience por a* siga con bbb* y termine con cc*",
        explanation=explanation,
        automaton=automaton.dump(),
        pattern="a*bbb*cc*",
    )
    assert search("cadenas binarias con cantidad par de unos") == []
    assert search("quiero un afd que comience por (ab|ba)* siga por aaa* y luego termine con (c|bb)*") == []
    set_memory_path(None)


def test_corrupt_memory_does_not_crash_or_get_overwritten(tmp_path):
    path = tmp_path / "solutions.json"
    original = "{esto no es json"
    path.write_text(original, encoding="utf-8")
    set_memory_path(path)
    try:
        assert search("cadenas con cantidad par de unos") == []
        with TestClient(app) as client:
            listed = client.get("/api/memory")
            assert listed.status_code == 200
            assert listed.json() == {"count": 0, "recent": []}
            session_id = client.post("/api/sessions").json()["id"]
            loaded = client.post(f"/api/sessions/{session_id}/examples/paridad")
            assert loaded.status_code == 200
            stored = client.post(f"/api/sessions/{session_id}/remember")
            assert stored.status_code == 409
            assert "dañada" in stored.json()["detail"]
        with pytest.raises(MemoryStoreError):
            save(request="paridad", explanation="par", automaton={})
        assert path.read_text(encoding="utf-8") == original
    finally:
        set_memory_path(None)
