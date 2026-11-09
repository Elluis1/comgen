import json
from itertools import product

import pytest
from fastapi.testclient import TestClient

from app.examples import EXAMPLES
from app.familias import recognize_family
from app.interpret import interpret_text
from app.main import app
from app.minimize import is_total_dfa, minimize_dfa
from app.schemas import FiniteAutomaton, State, Transition
from app.simulate import simulate
from app.validate import validate_fa

LUIGI = "un AFD sobre {0, 1} que acepte los números binarios divisibles por 5"
BOGUS_REGEX = "0*(0000|0101|1010|1111|1100)*0*" * 5

# Mínimos conocidos: si base y módulo son coprimos quedan n estados.
# En base 10, módulo 4 y módulo 5 se achican al minimizar.
EXPECTED_STATES = {
    (2, 3): 3,
    (2, 4): 3,
    (2, 5): 5,
    (2, 7): 7,
    (10, 3): 3,
    (10, 4): 3,
    (10, 5): 2,
    (10, 7): 7,
}


def _render(number: int, base: int) -> str:
    if number == 0:
        return "0"
    digits = []
    while number:
        digits.append(str(number % base))
        number //= base
    return "".join(reversed(digits))


def _assert_number_language(automaton, base: int, modulus: int, remainder: int) -> None:
    assert simulate(automaton, "").accepted is (remainder == 0)
    for number in range(0, 360):
        word = _render(number, base)
        expects = number % modulus == remainder
        assert simulate(automaton, word).accepted is expects, (number, word)
        assert simulate(automaton, "0" + word).accepted is expects
        assert simulate(automaton, "00" + word).accepted is expects


def _statement(base: int, modulus: int, remainder: int) -> str:
    if base == 2 and remainder == 0:
        return f"un AFD sobre {{0, 1}} que acepte los números binarios divisibles por {modulus}"
    if base == 2:
        return f"números binarios con resto {remainder} módulo {modulus}"
    if remainder == 0:
        return f"un AFD que acepte los números en base 10 divisibles por {modulus}"
    return f"números en base 10 cuyo resto al dividir por {modulus} es {remainder}"


@pytest.mark.parametrize("base,modulus", list(EXPECTED_STATES))
def test_divisible_in_base_2_and_10(base, modulus):
    result = recognize_family(_statement(base, modulus, 0))
    assert result is not None and result.automaton is not None
    assert result.export_ready
    assert result.errors == []
    automaton = result.automaton
    assert validate_fa(automaton).warnings == []
    assert is_total_dfa(automaton)
    assert len(automaton.states) == EXPECTED_STATES[(base, modulus)]
    assert len(minimize_dfa(automaton).states) == len(automaton.states)
    _assert_number_language(automaton, base, modulus, 0)
    assert "cadena vacía" in result.explanation
    assert "ceros a la izquierda" in result.explanation
    assert "Lo armé en código" in result.explanation


def test_binary_divisible_by_5_is_the_remainder_dfa():
    result = recognize_family(LUIGI)
    automaton = result.automaton
    assert [state.id for state in automaton.states] == ["q0", "q1", "q2", "q3", "q4"]
    assert [state.id for state in automaton.states if state.initial] == ["q0"]
    assert [state.id for state in automaton.states if state.final] == ["q0"]
    delta = {(item.from_state, item.read): item.to for item in automaton.transitions}
    for remainder in range(5):
        for bit in (0, 1):
            assert delta[(f"q{remainder}", str(bit))] == f"q{(2 * remainder + bit) % 5}"
    for word in ("0", "101", "1010", "1111", "11001", "00", "000", "0101", "00101"):
        assert simulate(automaton, word).accepted, word
    for word in ("1", "110", "111", "1011", "10"):
        assert not simulate(automaton, word).accepted, word
    assert simulate(automaton, "").accepted


@pytest.mark.parametrize(
    ("base", "modulus", "remainder"),
    [(2, 5, 2), (2, 7, 3), (2, 4, 1), (2, 3, 1), (10, 7, 3), (10, 4, 1), (10, 5, 2)],
)
def test_remainder_variants(base, modulus, remainder):
    if base == 10 and remainder == 3:
        text = f"números decimales congruentes con {remainder} módulo {modulus}"
    else:
        text = _statement(base, modulus, remainder)
    result = recognize_family(text)
    assert result is not None and result.automaton is not None
    assert result.export_ready
    assert validate_fa(result.automaton).warnings == []
    assert len(result.automaton.states) <= modulus
    assert len(minimize_dfa(result.automaton).states) == len(result.automaton.states)
    _assert_number_language(result.automaton, base, modulus, remainder)


def test_even_a_and_b_multiple_of_3_has_six_states():
    phrase = "un AFD sobre {a, b} con par de a y cantidad de b múltiplo de 3"
    result = recognize_family(phrase)
    assert result is not None and result.automaton is not None
    automaton = result.automaton
    assert result.export_ready
    assert validate_fa(automaton).warnings == []
    assert [state.id for state in automaton.states if state.initial] == ["q0"]
    assert len(automaton.states) == 6
    assert automaton.alphabet == ["a", "b"]
    for length in range(7):
        for symbols in product("ab", repeat=length):
            word = "".join(symbols)
            expects = word.count("a") % 2 == 0 and word.count("b") % 3 == 0
            assert simulate(automaton, word).accepted is expects, word


def test_same_product_without_braces():
    result = recognize_family("par de a y cantidad de b múltiplo de 3")
    assert result.automaton is not None
    assert len(result.automaton.states) == 6
    assert simulate(result.automaton, "").accepted
    assert simulate(result.automaton, "aabbb").accepted
    assert not simulate(result.automaton, "abbb").accepted
    assert not simulate(result.automaton, "bb").accepted


def test_luigi_regex_is_never_asked_of_the_model():
    """Esa expresión, repetida, le armó a Luigi un AFD de 90 estados. No se consulta."""

    async def fake_chat(_settings, _messages):
        raise AssertionError(f"No hay que usar la expresión del modelo: {BOGUS_REGEX}")

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        from unittest.mock import patch

        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": LUIGI},
            )
        body = response.json()
        assert response.status_code == 200
        assert body["export_ready"] is True
        assert body["errors"] == []
        assert len(body["automaton"]["states"]) == 5
        assert "90" not in body["messages"][-1]["content"]
        assert "cadena vacía" in body["messages"][-1]["content"]
        for word, accepted in (
            ("", True),
            ("0", True),
            ("101", True),
            ("1010", True),
            ("1111", True),
            ("11001", True),
            ("1", False),
            ("110", False),
            ("111", False),
            ("1011", False),
        ):
            result = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
            assert result.json()["accepted"] is accepted, word
        exported = client.get(f"/api/sessions/{session_id}/export")
        assert exported.status_code == 200
        assert exported.text.count("<state") == 5


def test_paridad_question_is_built_without_the_model():
    async def fake_chat(_settings, _messages):
        raise AssertionError("La paridad de unos se arma en código.")

    phrase = "¿Cadenas binarias con cantidad par de unos?"
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        from unittest.mock import patch

        with patch("app.service.chat", fake_chat):
            response = client.post(f"/api/sessions/{session_id}/messages", json={"text": phrase})
        body = response.json()
        assert body["export_ready"] is True
        assert len(body["automaton"]["states"]) == 2
        assert client.post(f"/api/sessions/{session_id}/simulate", json={"word": ""}).json()["accepted"]
        assert client.post(f"/api/sessions/{session_id}/simulate", json={"word": "11"}).json()["accepted"]
        assert not client.post(f"/api/sessions/{session_id}/simulate", json={"word": "1"}).json()["accepted"]


def test_regex_phrase_is_not_a_family():
    phrase = "un afd que comience por a* siga con bbb* y termine con cc*"
    assert recognize_family(phrase) is None


def test_ends_starts_contains_length_and_complement():
    ends = recognize_family("cadenas binarias que terminan en 01")
    assert ends.automaton is not None
    assert len(ends.automaton.states) == 3
    for word in ("01", "001", "101", "0101"):
        assert simulate(ends.automaton, word).accepted, word
    for word in ("", "0", "1", "10", "11", "010"):
        assert not simulate(ends.automaton, word).accepted, word

    starts = recognize_family("empieza con 01")
    assert starts.automaton is not None
    for word in ("01", "010", "011", "0100"):
        assert simulate(starts.automaton, word).accepted, word
    for word in ("", "0", "1", "00", "10", "11", "001"):
        assert not simulate(starts.automaton, word).accepted, word

    contains = recognize_family("contiene la subcadena 010")
    assert contains.automaton is not None
    for word in ("010", "0010", "0100", "1010", "01010"):
        assert simulate(contains.automaton, word).accepted, word
    for word in ("", "0", "01", "10", "11", "001", "100", "101", "011"):
        assert not simulate(contains.automaton, word).accepted, word

    ends_ab = recognize_family("un AFD sobre {a, b} que acepte cadenas que terminan en ab")
    assert ends_ab.automaton is not None
    assert ends_ab.automaton.alphabet == ["a", "b"]
    for word in ("ab", "aab", "bab", "abab"):
        assert simulate(ends_ab.automaton, word).accepted, word
    for word in ("", "a", "b", "ba", "aa", "aba"):
        assert not simulate(ends_ab.automaton, word).accepted, word

    even = recognize_family("longitud par sobre {a, b}")
    assert even.automaton is not None and len(even.automaton.states) == 2
    assert simulate(even.automaton, "").accepted
    assert not simulate(even.automaton, "a").accepted
    assert simulate(even.automaton, "ab").accepted

    odd = recognize_family("cadenas de longitud impar sobre {0, 1}")
    assert odd.automaton is not None
    assert not simulate(odd.automaton, "").accepted
    assert simulate(odd.automaton, "0").accepted
    assert not simulate(odd.automaton, "01").accepted

    multiple = recognize_family("longitud múltiplo de 3 sobre {0, 1}")
    assert multiple.automaton is not None and len(multiple.automaton.states) == 3
    assert simulate(multiple.automaton, "").accepted
    assert not simulate(multiple.automaton, "00").accepted
    assert simulate(multiple.automaton, "000").accepted
    assert simulate(multiple.automaton, "111").accepted

    negated = recognize_family("números binarios que no sean divisibles por 5")
    assert negated.automaton is not None
    assert len(negated.automaton.states) == 5
    assert not simulate(negated.automaton, "").accepted
    for word in ("1", "110", "111", "1011"):
        assert simulate(negated.automaton, word).accepted, word
    for word in ("0", "101", "1010", "1111"):
        assert not simulate(negated.automaton, word).accepted, word

    union = recognize_family("números binarios divisibles por 3 o por 5")
    assert union.automaton is not None
    assert len(minimize_dfa(union.automaton).states) == len(union.automaton.states)
    for number in range(0, 80):
        word = _render(number, 2)
        expects = number % 3 == 0 or number % 5 == 0
        assert simulate(union.automaton, word).accepted is expects, number


def test_spec_json_builds_the_dfa_without_drawing_states():
    raw = json.dumps(
        {
            "kind": "spec",
            "family": "divisible",
            "base": 2,
            "modulus": 5,
            "remainder": 0,
            "alphabet": ["0", "1"],
            "description": "Números binarios divisibles por 5",
            "states": [],
            "transitions": [],
        }
    )
    parsed = interpret_text(raw)
    assert parsed.export_ready
    assert len(parsed.automaton.states) == 5
    assert simulate(parsed.automaton, "101").accepted
    assert not simulate(parsed.automaton, "1").accepted


def test_model_invented_huge_regex_is_discarded():
    async def fake_chat(_settings, _messages):
        return json.dumps(
            {
                "kind": "regex",
                "pattern": "0" * 60,
                "description": "inventada",
                "explanation": "el modelo adivinó",
            }
        )

    phrase = "armame el lenguaje del ejercicio 12"
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        from unittest.mock import patch

        with patch("app.service.chat", fake_chat):
            response = client.post(f"/api/sessions/{session_id}/messages", json={"text": phrase})
        body = response.json()
        assert body["export_ready"] is False
        assert body["automaton"] is None
        assert "estados" in body["messages"][-1]["content"]
        assert "No lo uso" in body["messages"][-1]["content"]


def test_model_samples_that_fail_are_warned_in_spanish():
    raw = EXAMPLES["paridad"].automaton.model_dump(by_alias=True)
    for state in raw["states"]:
        state["final"] = state["id"] == "q1"
    raw["accept"] = ["11"]
    raw["reject"] = ["1"]

    async def fake_chat(_settings, _messages):
        return json.dumps(raw)

    phrase = "¿Me mostrás otro dibujo del apunte?"
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        from unittest.mock import patch

        with patch("app.service.chat", fake_chat):
            response = client.post(f"/api/sessions/{session_id}/messages", json={"text": phrase})
        body = response.json()
        assert body["export_ready"] is True
        warning = " ".join(body["warnings"])
        assert "11" in warning
        assert "debería aceptarse" in warning
        assert "debería rechazarse" in warning


def test_large_model_dfa_is_warned_but_kept():
    states = [{"id": f"q{index}", "initial": index == 0, "final": index == 24} for index in range(25)]
    transitions = []
    for index in range(25):
        target = min(index + 1, 24)
        transitions.append({"from": f"q{index}", "to": f"q{target}", "read": "a"})
        transitions.append({"from": f"q{index}", "to": f"q{index}", "read": "b"})

    async def fake_chat(_settings, _messages):
        return json.dumps(
            {
                "kind": "fa",
                "description": "cadena larga",
                "explanation": "lo dibujé yo",
                "deterministic": True,
                "alphabet": ["a", "b"],
                "states": states,
                "transitions": transitions,
            }
        )

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        from unittest.mock import patch

        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "el autómata de la figura del apunte"},
            )
        body = response.json()
        assert body["export_ready"] is True
        assert len(body["automaton"]["states"]) == 25
        assert any("25 estados" in warning for warning in body["warnings"])


def test_minimize_merges_equivalent_finals_and_keeps_parity():
    redundant = FiniteAutomaton(
        deterministic=True,
        alphabet=["a", "b"],
        description="dos finales iguales",
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=True),
            State(id="q2", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="a"),
            Transition(from_state="q0", to="q2", read="b"),
            Transition(from_state="q1", to="q1", read="a"),
            Transition(from_state="q1", to="q1", read="b"),
            Transition(from_state="q2", to="q2", read="a"),
            Transition(from_state="q2", to="q2", read="b"),
        ],
    )
    minimized = minimize_dfa(redundant)
    assert len(minimized.states) == 2
    assert simulate(minimized, "").accepted is False
    assert simulate(minimized, "a").accepted is True
    assert simulate(minimized, "b").accepted is True
    assert simulate(minimized, "ab").accepted is True

    parity = EXAMPLES["paridad"].automaton
    assert minimize_dfa(parity) is parity
    assert len(minimize_dfa(parity).states) == 2


EVEN_A_WITHOUT_BB = (
    "AFD sobre el alfabeto {a, b} que acepte las cadenas con una cantidad par de a "
    "y que no contengan la subcadena bb"
)
EVEN_A_ACCEPT = ("", "b", "aa", "aba", "baab", "abab")
EVEN_A_REJECT = ("a", "bab", "ababa", "babaab", "bb", "abba", "aabb")


def _sink_ids(automaton) -> list[str]:
    finals = {state.id for state in automaton.states if state.final}
    delta = {(item.from_state, item.read): item.to for item in automaton.transitions}
    sinks = []
    for state in automaton.states:
        if state.id in finals:
            continue
        if all(delta[(state.id, symbol)] == state.id for symbol in automaton.alphabet):
            sinks.append(state.id)
    return sinks


def test_even_count_of_a_without_bb_is_the_minimal_five_state_dfa():
    result = recognize_family(EVEN_A_WITHOUT_BB)
    assert result is not None and result.automaton is not None
    assert result.errors == []
    assert result.export_ready
    automaton = result.automaton
    assert automaton.alphabet == ["a", "b"]
    assert automaton.deterministic
    assert len(automaton.states) == 5
    assert len(minimize_dfa(automaton).states) == 5
    assert validate_fa(automaton).warnings == []
    assert _sink_ids(automaton) == ["q4"]
    assert [state.id for state in automaton.states if state.initial] == ["q0"]
    for word in EVEN_A_ACCEPT:
        assert simulate(automaton, word).accepted, word
    for word in EVEN_A_REJECT:
        assert not simulate(automaton, word).accepted, word
    assert "Lo armé en código" in result.explanation

    odd = recognize_family("cantidad impar de a y que no contengan la subcadena bb")
    assert odd.automaton is not None
    assert odd.automaton.alphabet == ["a", "b"]
    assert len(odd.automaton.states) == 5
    assert len(_sink_ids(odd.automaton)) == 1
    assert not simulate(odd.automaton, "").accepted
    assert simulate(odd.automaton, "a").accepted
    assert not simulate(odd.automaton, "abb").accepted

    alone = recognize_family("cadenas sobre {a, b} que no contengan la subcadena bb")
    assert alone.automaton is not None
    assert len(alone.automaton.states) == 3
    assert simulate(alone.automaton, "").accepted
    assert not simulate(alone.automaton, "bb").accepted


ANTEPENULTIMO = (
    "AFD sobre el alfabeto {0, 1} que acepte las cadenas cuyo antepenúltimo símbolo sea 1"
)
ANTE_ACCEPT = ("100", "101", "110", "111", "0100", "10111", "11101")
# 11011 tiene antepenúltimo 0: se rechaza, igual que las cadenas cortas.
ANTE_REJECT = ("", "1", "11", "011", "0011", "1000", "11011")


def _nth_is(word: str, k: int, symbol: str, origin: str) -> bool:
    if len(word) < k:
        return False
    if origin == "end":
        return word[-k] == symbol
    return word[k - 1] == symbol


def test_antepenultimate_one_is_the_minimal_eight_state_dfa():
    result = recognize_family(ANTEPENULTIMO)
    assert result is not None and result.automaton is not None
    assert result.errors == []
    assert result.export_ready
    automaton = result.automaton
    assert automaton.alphabet == ["0", "1"]
    assert automaton.deterministic
    assert len(automaton.states) == 8
    assert len(minimize_dfa(automaton).states) == 8
    assert validate_fa(automaton).warnings == []
    assert [state.id for state in automaton.states if state.initial] == ["q0"]
    for word in ANTE_ACCEPT:
        assert simulate(automaton, word).accepted, word
    for word in ANTE_REJECT:
        assert not simulate(automaton, word).accepted, word
    for length in range(7):
        for symbols in product("01", repeat=length):
            word = "".join(symbols)
            assert simulate(automaton, word).accepted is _nth_is(word, 3, "1", "end"), word
    assert "2^3" in result.explanation
    assert "Lo armé en código" in result.explanation

    async def fake_chat(_settings, _messages):
        raise AssertionError("El antepenúltimo símbolo se arma en código.")

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        from unittest.mock import patch

        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": ANTEPENULTIMO},
            )
        body = response.json()
        assert response.status_code == 200
        assert body["export_ready"] is True
        assert body["errors"] == []
        assert len(body["automaton"]["states"]) == 8
        assert body["automaton"]["alphabet"] == ["0", "1"]
        for word in ANTE_ACCEPT:
            result = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
            assert result.json()["accepted"] is True, word
        for word in ANTE_REJECT:
            result = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
            assert result.json()["accepted"] is False, word


def test_position_phrasings_from_both_ends():
    ultimo = recognize_family("cadenas sobre {0, 1} cuyo último símbolo sea 0")
    assert ultimo.automaton is not None
    assert len(ultimo.automaton.states) == 2
    assert simulate(ultimo.automaton, "").accepted is False
    assert simulate(ultimo.automaton, "0").accepted is True
    assert simulate(ultimo.automaton, "10").accepted is True
    assert simulate(ultimo.automaton, "1").accepted is False
    assert simulate(ultimo.automaton, "01").accepted is False

    penultimo = recognize_family("el penúltimo símbolo es 1")
    assert penultimo.automaton is not None
    assert penultimo.automaton.alphabet == ["0", "1"]
    assert len(penultimo.automaton.states) == 4
    for length in range(6):
        for symbols in product("01", repeat=length):
            word = "".join(symbols)
            assert simulate(penultimo.automaton, word).accepted is _nth_is(word, 2, "1", "end"), word

    tercero = recognize_family("el tercero desde el final es 1")
    assert tercero.automaton is not None
    assert len(tercero.automaton.states) == 8
    assert simulate(tercero.automaton, "100").accepted is True
    assert simulate(tercero.automaton, "010").accepted is False

    ordinal = recognize_family("el 3-ésimo símbolo desde el final sea 1")
    assert ordinal.automaton is not None
    assert len(ordinal.automaton.states) == 8
    assert simulate(ordinal.automaton, "111").accepted is True
    assert simulate(ordinal.automaton, "011").accepted is False

    cuarto = recognize_family("el 4-ésimo desde el final es 0")
    assert cuarto.automaton is not None
    assert len(cuarto.automaton.states) == 16
    assert simulate(cuarto.automaton, "0111").accepted is True
    assert simulate(cuarto.automaton, "1111").accepted is False
    assert simulate(cuarto.automaton, "00111").accepted is True

    segundo = recognize_family("el segundo símbolo es 1")
    assert segundo.automaton is not None
    assert segundo.automaton.alphabet == ["0", "1"]
    for length in range(5):
        for symbols in product("01", repeat=length):
            word = "".join(symbols)
            assert simulate(segundo.automaton, word).accepted is _nth_is(word, 2, "1", "start"), word

    desde_principio = recognize_family(
        "AFD sobre {a, b} cuyo segundo símbolo desde el principio sea b"
    )
    assert desde_principio.automaton is not None
    assert desde_principio.automaton.alphabet == ["a", "b"]
    assert simulate(desde_principio.automaton, "ab").accepted is True
    assert simulate(desde_principio.automaton, "abaaa").accepted is True
    assert simulate(desde_principio.automaton, "aa").accepted is False
    assert simulate(desde_principio.automaton, "b").accepted is False

    primero = recognize_family("el primer símbolo sea a")
    assert primero.automaton is not None
    assert primero.automaton.alphabet == ["a", "b"]
    assert simulate(primero.automaton, "a").accepted is True
    assert simulate(primero.automaton, "ab").accepted is True
    assert simulate(primero.automaton, "b").accepted is False
    assert simulate(primero.automaton, "").accepted is False

    letras = recognize_family("AFD sobre {a, b, c} cuyo antepenúltimo símbolo sea b")
    assert letras.automaton is not None
    assert letras.automaton.alphabet == ["a", "b", "c"]
    assert len(letras.automaton.states) == 8
    assert simulate(letras.automaton, "baa").accepted is True
    assert simulate(letras.automaton, "abc").accepted is False
    assert simulate(letras.automaton, "bbbcb").accepted is True

    junto = recognize_family(
        "sobre {0, 1} cuyo antepenúltimo símbolo sea 1 y que terminen en 0"
    )
    assert junto.automaton is not None
    assert junto.export_ready
    assert len(minimize_dfa(junto.automaton).states) == len(junto.automaton.states)
    for word in ("100", "110", "0100", "1110"):
        assert simulate(junto.automaton, word).accepted, word
    for word in ("", "1", "101", "111", "1000", "11011"):
        assert not simulate(junto.automaton, word).accepted, word


def test_position_k_is_capped_in_spanish():
    from app.familias import MAX_FROM_END, MAX_FROM_START

    too_far = recognize_family(
        "AFD sobre el alfabeto {0, 1} cuyo 13-ésimo símbolo desde el final sea 1"
    )
    assert too_far is not None and too_far.automaton is None
    text = " ".join(too_far.errors)
    assert "2^13" in text
    assert "8192" in text
    assert str(MAX_FROM_END) in text
    assert "notebook" in text

    async def fake_chat(_settings, _messages):
        raise AssertionError("El tope se resuelve en código y no llama al modelo.")

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        from unittest.mock import patch

        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={
                    "text": "AFD sobre {0, 1} cuyo 13-ésimo símbolo desde el final sea 1",
                },
            )
        body = response.json()
        assert body["automaton"] is None
        assert body["export_ready"] is False
        assert "2^13" in body["messages"][-1]["content"]

    within = recognize_family("el 13-ésimo símbolo desde el principio es 1")
    assert within.automaton is not None
    assert within.export_ready
    assert simulate(within.automaton, "0" * 12 + "1").accepted is True
    assert simulate(within.automaton, "0" * 12 + "0").accepted is False
    assert simulate(within.automaton, "1" * 12).accepted is False

    start_cap = recognize_family(f"el {MAX_FROM_START + 1}-ésimo símbolo desde el principio es 0")
    assert start_cap.automaton is None
    assert str(MAX_FROM_START) in " ".join(start_cap.errors)

    outside = recognize_family("antepenúltimo símbolo sea a sobre {0, 1}")
    assert outside.automaton is None
    message = " ".join(outside.errors)
    assert "«a»" in message
    assert "«0» no está en el alfabeto" not in message


def test_partial_dfa_is_not_rewritten_by_minimize():
    partial = FiniteAutomaton(
        alphabet=["0", "1"],
        states=[State(id="q0", initial=True, final=True)],
        transitions=[Transition(from_state="q0", to="q0", read="0")],
        description="incompleto",
    )
    assert minimize_dfa(partial) is partial


LUIGI_SEQUENCE = (
    "un afd, sobre el lenguaje {0,1} que acepte cadenas que empiecen por infinitos 1, "
    "continuan con 3 0, infinitos 1 de nuevo y terminen con un 0"
)
_LUIGI_ACCEPT = ("0000", "110001110", "00010", "100010", "1110000", "0001110")
_LUIGI_REJECT = ("000", "00110", "1101", "", "0", "1", "0010", "00000", "11000111", "10001")


def _is_luigi_word(word: str) -> bool:
    import re

    return re.fullmatch(r"1*0001*0", word) is not None


def test_luigi_infinite_ones_three_zeros_is_built_without_the_model():
    async def fake_chat(_settings, _messages):
        raise AssertionError("1*0001*0 se arma en código.")

    result = recognize_family(LUIGI_SEQUENCE)
    assert result is not None and result.automaton is not None
    assert result.errors == []
    assert result.export_ready
    automaton = result.automaton
    assert automaton.alphabet == ["0", "1"]
    assert automaton.deterministic
    assert is_total_dfa(automaton)
    assert len(minimize_dfa(automaton).states) == len(automaton.states)
    assert validate_fa(automaton).warnings == []
    assert "1*0001*0" in result.explanation
    assert "Lo armé en código" in result.explanation
    for word in _LUIGI_ACCEPT:
        assert simulate(automaton, word).accepted, word
    for word in _LUIGI_REJECT:
        assert not simulate(automaton, word).accepted, word
    for length in range(9):
        for symbols in product("01", repeat=length):
            word = "".join(symbols)
            assert simulate(automaton, word).accepted is _is_luigi_word(word), word

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        from unittest.mock import patch

        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": LUIGI_SEQUENCE},
            )
        body = response.json()
        assert response.status_code == 200
        assert body["export_ready"] is True
        assert body["errors"] == []
        assert body["automaton"]["alphabet"] == ["0", "1"]
        for word in ("0000", "110001110", "00010"):
            answer = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
            assert answer.json()["accepted"] is True, word
        for word in ("000", "00110", "1101", ""):
            answer = client.post(f"/api/sessions/{session_id}/simulate", json={"word": word})
            assert answer.json()["accepted"] is False, word


@pytest.mark.parametrize(
    "phrase",
    [
        "infinitos 1, tres 0, infinitos 1 y un 0",
        "infinitos unos, tres ceros, infinitos unos y un cero",
        "cualquier cantidad de 1, 3 ceros, cero o más unos y terminan con un 0",
        "empiezan por infinitos 1, continúan con tres ceros, infinitos 1 de nuevo y terminan con una vez un 0",
    ],
)
def test_sequence_phrasings_match_the_same_language(phrase):
    result = recognize_family(f"un AFD sobre {{0, 1}} de cadenas que {phrase}")
    assert result is not None and result.automaton is not None, phrase
    assert result.export_ready
    assert result.automaton.alphabet == ["0", "1"]
    for word in _LUIGI_ACCEPT:
        assert simulate(result.automaton, word).accepted, (phrase, word)
    for word in _LUIGI_REJECT:
        assert not simulate(result.automaton, word).accepted, (phrase, word)


def test_un_cero_does_not_swallow_termina_empieza_o_contiene():
    """«un 0» solo es un bloque si el enunciado es una secuencia. Si no, es «0»."""
    ends = recognize_family("termina con un 0")
    assert ends is not None and ends.automaton is not None and ends.errors == []
    assert ends.automaton.alphabet == ["0", "1"]
    for word in ("10", "00", "0", "110"):
        assert simulate(ends.automaton, word).accepted, word
    for word in ("", "1", "01", "11"):
        assert not simulate(ends.automaton, word).accepted, word

    starts = recognize_family("empieza con un 0")
    assert starts is not None and starts.automaton is not None and starts.errors == []
    for word in ("0", "00", "01", "011"):
        assert simulate(starts.automaton, word).accepted, word
    for word in ("", "1", "10", "11"):
        assert not simulate(starts.automaton, word).accepted, word

    union = recognize_family("cadenas que empiezan con un 0 o terminan con un 1")
    assert union is not None and union.automaton is not None and union.errors == []
    assert union.automaton.alphabet == ["0", "1"]
    for word in ("0", "00", "01", "1", "11", "011", "101"):
        assert simulate(union.automaton, word).accepted, word
    for word in ("", "10", "100", "110"):
        assert not simulate(union.automaton, word).accepted, word

    contains = recognize_family("contiene un 0")
    assert contains is not None and contains.automaton is not None and contains.errors == []
    for word in ("0", "10", "01", "101"):
        assert simulate(contains.automaton, word).accepted, word
    for word in ("", "1", "11"):
        assert not simulate(contains.automaton, word).accepted, word

    both = recognize_family("empieza con un 0 y longitud par")
    assert both is not None and both.automaton is not None and both.errors == []
    for word in ("00", "01", "0000", "0110"):
        assert simulate(both.automaton, word).accepted, word
    for word in ("", "0", "000", "10", "11", "1"):
        assert not simulate(both.automaton, word).accepted, word

    luigi = recognize_family(LUIGI_SEQUENCE)
    assert luigi is not None and luigi.automaton is not None and luigi.errors == []
    assert "1*0001*0" in luigi.explanation
    for word in ("0000", "110001110", "00010"):
        assert simulate(luigi.automaton, word).accepted, word
    for word in ("000", "00110", "1101", ""):
        assert not simulate(luigi.automaton, word).accepted, word


def test_counts_and_stars_are_repetitions():
    three = recognize_family("tres ceros")
    assert three.automaton is not None
    assert simulate(three.automaton, "000").accepted
    assert not simulate(three.automaton, "00").accepted
    assert not simulate(three.automaton, "0000").accepted
    assert not simulate(three.automaton, "").accepted

    two = recognize_family("dos unos sobre {0, 1}")
    assert two.automaton is not None
    assert two.automaton.alphabet == ["0", "1"]
    assert simulate(two.automaton, "11").accepted
    assert not simulate(two.automaton, "1").accepted
    assert not simulate(two.automaton, "111").accepted
    assert not simulate(two.automaton, "011").accepted

    one_zero = recognize_family("un 0")
    assert one_zero.automaton is not None
    assert simulate(one_zero.automaton, "0").accepted
    assert not simulate(one_zero.automaton, "").accepted
    assert not simulate(one_zero.automaton, "00").accepted
    assert not simulate(one_zero.automaton, "1").accepted

    one_a = recognize_family("una a sobre {a, b}")
    assert one_a.automaton is not None
    assert one_a.automaton.alphabet == ["a", "b"]
    assert simulate(one_a.automaton, "a").accepted
    assert not simulate(one_a.automaton, "").accepted
    assert not simulate(one_a.automaton, "b").accepted
    assert not simulate(one_a.automaton, "aa").accepted

    star = recognize_family("cero o más ceros sobre {0, 1}")
    assert star.automaton is not None
    assert simulate(star.automaton, "").accepted
    assert simulate(star.automaton, "0").accepted
    assert simulate(star.automaton, "000").accepted
    assert not simulate(star.automaton, "1").accepted
    assert not simulate(star.automaton, "01").accepted

    plus = recognize_family("uno o más unos")
    assert plus.automaton is not None
    assert not simulate(plus.automaton, "").accepted
    assert simulate(plus.automaton, "1").accepted
    assert simulate(plus.automaton, "111").accepted
    assert not simulate(plus.automaton, "0").accepted
    assert not simulate(plus.automaton, "10").accepted
    assert "11*" in plus.explanation


def test_three_in_the_alphabet_is_explained_or_written_as_a_word():
    async def fake_chat(_settings, _messages):
        raise AssertionError("El caso ambiguo no llama al modelo.")

    ambiguous = recognize_family("un AFD sobre {0, 1, 2, 3} que acepte 3 0")
    assert ambiguous is not None and ambiguous.automaton is None
    message = " ".join(ambiguous.errors)
    assert "ambiguo" in message
    assert "tres ceros" in message
    assert "{0, 1, 2, 3}" in message

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        from unittest.mock import patch

        with patch("app.service.chat", fake_chat):
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "un AFD sobre {0, 1, 2, 3} que acepte cadenas de 3 0"},
            )
        body = response.json()
        assert body["automaton"] is None
        assert body["export_ready"] is False
        assert "ambiguo" in body["messages"][-1]["content"]

    words = recognize_family("tres ceros sobre {0, 1, 2, 3}")
    assert words.automaton is not None
    assert words.automaton.alphabet == ["0", "1", "2", "3"]
    assert simulate(words.automaton, "000").accepted
    assert not simulate(words.automaton, "30").accepted
    assert not simulate(words.automaton, "3").accepted
    assert not simulate(words.automaton, "111").accepted

    named = recognize_family("3 ceros sobre {0, 1, 2, 3}")
    assert named.automaton is not None
    assert simulate(named.automaton, "000").accepted
    assert not simulate(named.automaton, "30").accepted

    binary = recognize_family("cadenas binarias de 3 0")
    assert binary.automaton is not None
    assert binary.automaton.alphabet == ["0", "1"]
    assert simulate(binary.automaton, "000").accepted
    assert not simulate(binary.automaton, "00").accepted
    assert not simulate(binary.automaton, "3").accepted

    parity = recognize_family("par de 3 sobre {0, 1, 2, 3}")
    assert parity.automaton is not None
    assert parity.automaton.alphabet == ["0", "1", "2", "3"]
    assert simulate(parity.automaton, "").accepted
    assert simulate(parity.automaton, "33").accepted
    assert not simulate(parity.automaton, "3").accepted
    assert simulate(parity.automaton, "303").accepted


def test_sequence_spec_builds_the_dfa_from_blocks():
    raw = json.dumps(
        {
            "kind": "spec",
            "family": "secuencia",
            "alphabet": ["0", "1"],
            "blocks": [
                {"symbol": "1", "repeat": "*"},
                {"symbol": "0", "repeat": "3"},
                {"symbol": "1", "repeat": "*"},
                {"symbol": "0", "repeat": "1"},
            ],
            "states": [],
            "transitions": [],
        }
    )
    parsed = interpret_text(raw, "un AFD sobre {0, 1}")
    assert parsed.export_ready
    assert parsed.automaton.alphabet == ["0", "1"]
    assert simulate(parsed.automaton, "0000").accepted
    assert simulate(parsed.automaton, "110001110").accepted
    assert not simulate(parsed.automaton, "").accepted
    assert not simulate(parsed.automaton, "000").accepted


def test_model_count_digit_is_called_a_repetition():
    from app.interpret import ModelReplyError

    raw = json.dumps(
        {
            "kind": "fa",
            "description": "mal",
            "explanation": "metí el 3",
            "deterministic": True,
            "alphabet": ["0", "1", "3"],
            "states": [
                {"id": "q0", "initial": True, "final": True},
            ],
            "transitions": [
                {"from": "q0", "to": "q0", "read": "0"},
                {"from": "q0", "to": "q0", "read": "1"},
                {"from": "q0", "to": "q0", "read": "3"},
            ],
        }
    )
    with pytest.raises(ModelReplyError) as caught:
        interpret_text(raw, LUIGI_SEQUENCE)
    text = " ".join(caught.value.errors)
    assert "no declara" in text
    assert "repetición" in text
