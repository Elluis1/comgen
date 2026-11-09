import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.main import app
from app.schemas import FiniteAutomaton, State
from app.service import _should_start_fresh
from app.store import Session, store

LUIGI = "un AFD sobre {0, 1} que acepte los números binarios divisibles por 5"
EVEN_A_WITHOUT_BB = (
    "AFD sobre el alfabeto {a, b} que acepte las cadenas con una cantidad par de a "
    "y que no contengan la subcadena bb"
)
OTHER = "el autómata de la figura del apunte"
ACCEPT = ("", "b", "aa", "aba", "baab", "abab")
REJECT = ("a", "bab", "ababa", "babaab", "bb", "abba", "aabb")


def _parity_json() -> str:
    return json.dumps(EXAMPLES["paridad"].automaton.model_dump(by_alias=True))


def _user_text(messages: list[dict]) -> str:
    return messages[-1]["content"]


def test_even_a_without_bb_does_not_inherit_the_binary_automaton():
    async def fake_chat(_settings, _messages):
        raise AssertionError("Ese enunciado se arma en código y no tiene que ver el AFD anterior.")

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            first = client.post(f"/api/sessions/{session_id}/messages", json={"text": LUIGI})
            second = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": EVEN_A_WITHOUT_BB},
            )
        assert first.status_code == 200
        assert first.json()["automaton"]["alphabet"] == ["0", "1"]
        body = second.json()
        assert second.status_code == 200
        assert body["errors"] == []
        assert body["export_ready"] is True
        assert body["recalled"] == []
        automaton = body["automaton"]
        assert automaton["alphabet"] == ["a", "b"]
        assert len(automaton["states"]) == 5
        assert "0" not in body["messages"][-1]["content"]
        assert "1" not in body["messages"][-1]["content"]
        for word in ACCEPT:
            result = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
            assert result.json()["accepted"] is True, word
        for word in REJECT:
            result = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
            assert result.json()["accepted"] is False, word


def test_a_different_statement_does_not_send_previous_turns_or_automaton():
    seen: list[list[dict]] = []

    async def fake_chat(_settings, messages):
        seen.append(messages)
        return _parity_json()

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with patch("app.service.chat", fake_chat):
            client.post(f"/api/sessions/{session_id}/messages", json={"text": LUIGI})
            response = client.post(f"/api/sessions/{session_id}/messages", json={"text": OTHER})
            assert response.status_code == 200
            assert [message["role"] for message in seen[0]] == ["system", "user"]
            assert "Autómata actual" not in _user_text(seen[0])
            assert "divisibles" not in _user_text(seen[0])
            assert LUIGI not in _user_text(seen[0])

            again = client.post(f"/api/sessions/{session_id}/messages", json={"text": OTHER})
            assert again.status_code == 200
            assert "Autómata actual" in _user_text(seen[1])
            assert any(message["role"] == "assistant" for message in seen[1])
            assert "divisibles" not in json.dumps(seen[1])


def test_same_text_with_a_foreign_alphabet_starts_fresh():
    phrase = "un dibujo sobre {a, b} del apunte de hoy"
    session = Session(id="x", current_statement=phrase)
    session.automaton = FiniteAutomaton(
        alphabet=["0", "1"],
        description="binario viejo",
        states=[State(id="q0", initial=True, final=True)],
    )
    assert _should_start_fresh(session, phrase)
    session.automaton = FiniteAutomaton(
        alphabet=["a", "b"],
        description="letras",
        states=[State(id="q0", initial=True, final=True)],
    )
    assert not _should_start_fresh(session, phrase)

    seen: list[list[dict]] = []

    async def fake_chat(_settings, messages):
        seen.append(messages)
        payload = EXAMPLES["paridad"].automaton.model_dump(by_alias=True)
        payload["alphabet"] = ["a", "b"]
        for transition in payload["transitions"]:
            transition["read"] = "a" if transition["read"] == "0" else "b"
        return json.dumps(payload)

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        stored = store.get(session_id)
        stored.current_statement = phrase
        stored.automaton = FiniteAutomaton(
            alphabet=["0", "1"],
            description="binario viejo",
            states=[State(id="q0", initial=True, final=True)],
        )
        stored.model_messages = [
            {"role": "user", "content": LUIGI},
            {"role": "assistant", "content": '{"alphabet":["0","1"]}'},
        ]
        with patch("app.service.chat", fake_chat):
            response = client.post(f"/api/sessions/{session_id}/messages", json={"text": phrase})
        assert response.status_code == 200
        assert response.json()["automaton"]["alphabet"] == ["a", "b"]
        assert [message["role"] for message in seen[0]] == ["system", "user"]
        assert "Autómata actual" not in _user_text(seen[0])
        assert "divisibles" not in _user_text(seen[0])
        assert "binario viejo" not in _user_text(seen[0])


def test_new_automaton_button_resets_the_session():
    async def fake_chat(_settings, messages):
        assert "divisibles" not in messages[-1]["content"]
        assert "Autómata actual" not in messages[-1]["content"]
        return _parity_json()

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="fresh" type="button"' in page.text
        assert "Nuevo autómata" in page.text
        script = client.get("/static/app.js")
        assert script.status_code == 200
        assert "/reset" in script.text
        assert "startFresh" in script.text

        session_id = client.post("/api/sessions").json()["id"]
        built = client.post(f"/api/sessions/{session_id}/messages", json={"text": LUIGI})
        assert built.json()["export_ready"] is True
        remembered = client.post(f"/api/sessions/{session_id}/remember")
        assert remembered.status_code == 200
        assert client.get("/api/memory").json()["count"] == 1

        emptied = client.post(f"/api/sessions/{session_id}/reset")
        body = emptied.json()
        assert emptied.status_code == 200
        assert body["automaton"] is None
        assert body["messages"] == []
        assert body["warnings"] == []
        assert body["errors"] == []
        assert body["export_ready"] is False
        assert body["recalled"] == []
        assert body["can_remember"] is False
        assert body["memory_count"] == 1
        assert client.get("/api/memory").json()["count"] == 1

        simulated = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "0"})
        assert simulated.status_code == 409
        assert "autómata" in simulated.json()["detail"]

        missing = client.post("/api/sessions/no-existe/reset")
        assert missing.status_code == 404

        with patch("app.service.chat", fake_chat):
            follow = client.post(f"/api/sessions/{session_id}/messages", json={"text": OTHER})
        assert follow.status_code == 200
        assert follow.json()["export_ready"] is True
