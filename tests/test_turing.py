"""Máquina de Turing de una cinta. No abre Ollama ni usa los ejemplos.

Si falta la transición y el estado no es final, la simulación rechaza.
No dice «no terminó» ni deja salir una excepción. Aceptar es detenerse
en un estado final: también falta la transición, y esa no es un rechazo.
«No terminó» queda para el tope de pasos o el de celdas.
"""

import gc
import time
import unicodedata
from dataclasses import replace

import pytest

from app.turing import (
    MAX_CELLS,
    MAX_STEPS,
    Configuration,
    TuringError,
    TuringMachine,
    TuringState,
    TuringTransition,
    run,
    start,
    step,
    validate_tm,
)


def _edge(state: str, read: str, to: str, write: str, move: str) -> TuringTransition:
    return TuringTransition(state, read, to, write, move)


def _an_bn() -> TuringMachine:
    """{ aⁿbⁿ | n ≥ 1 }. Escrita acá, no en la lista de ejemplos.

    q0 marca la primera a. q1 busca una b y la tacha. q2 vuelve a la X.
    q3 marca otra a, o pasa a q4 si ya solo quedan Y. q4 confirma el
    blanco y se queda en qf. S está fijado en esa última flecha.
    """
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


def _stay_into_final() -> TuringMachine:
    return TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=["a", "b", "_"],
        blank="_",
        transitions=[_edge("q0", "a", "qf", "b", "S")],
    )


def test_an_bn_accepts_and_rejects_without_a_sink_or_ollama():
    machine = _an_bn()
    assert validate_tm(machine) == []
    names = {state.id for state in machine.states}
    for word in ("ab", "aabb", "aaabbb", "aaaabbbb"):
        result = run(machine, word, trace=True)
        assert result.status == "accept", word
        assert result.accepted is True
        assert result.state == "qf"
        assert result.state in names
        assert "pozo" not in names
        assert result.steps_run > 0
        assert len(result.steps) == result.steps_run + 1
        assert result.steps[-1].status == "accept"
        assert result.steps[-1].head == result.head
        assert result.steps[-1].tape == result.tape

    for word in ("", "a", "b", "aa", "bb", "ba", "aab", "abb", "abab", "aaa", "X", "Y"):
        result = run(machine, word)
        assert result.status == "reject", word
        assert result.accepted is False
        assert result.state in names
        assert "no terminó" not in result.message.casefold()
        assert "falta la transición" in result.message


def test_an_bn_trace_starts_at_the_first_symbol():
    result = run(_an_bn(), "ab", trace=True)
    seen = [(item.state, item.head, "".join(item.tape)) for item in result.steps[:4]]
    assert seen == [
        ("q0", 0, "ab"),
        ("q1", 1, "Xb"),
        ("q2", 0, "XY"),
        ("q3", 1, "XY"),
    ]
    assert result.steps[-1].state == "qf"
    assert "".join(result.tape) == "XY_"
    assert result.head == 2


def test_missing_transition_rejects_unless_the_state_is_final():
    stuck = TuringMachine(
        states=[TuringState("q0", initial=True)],
        tape_alphabet=["a", "_"],
        blank="_",
        transitions=[],
    )
    rejected = run(stuck, "a")
    assert rejected.status == "reject"
    assert rejected.accepted is False
    assert rejected.steps_run == 0
    assert rejected.message == "Rechaza: falta la transición de «q0» leyendo «a»."
    assert "no terminó" not in rejected.message.casefold()

    final = TuringMachine(
        states=[TuringState("q0", initial=True, final=True)],
        tape_alphabet=["a", "_"],
        blank="_",
        transitions=[],
    )
    accepted = run(final, "")
    assert accepted.status == "accept"
    assert accepted.accepted is True
    assert accepted.tape == ("_",)
    assert accepted.head == 0
    assert accepted.message == "Acepta: se detuvo en el estado final «q0»."
    assert "no terminó" not in accepted.message.casefold()


def test_stay_is_a_legal_move_and_the_last_budgeted_step_can_accept():
    machine = _stay_into_final()
    result = run(machine, "a", trace=True)
    assert result.status == "accept"
    assert result.steps_run == 1
    assert result.tape == ("b",)
    assert result.head == 0
    assert [(item.state, item.status) for item in result.steps] == [
        ("q0", "running"),
        ("qf", "accept"),
    ]

    on_the_budget = run(machine, "a", max_steps=1)
    assert on_the_budget.status == "accept"
    assert on_the_budget.steps_run == 1

    no_budget = run(machine, "a", max_steps=0)
    assert no_budget.status == "timeout"
    assert no_budget.accepted is None
    assert no_budget.steps_run == 0
    assert no_budget.message == "No terminó: se agotaron los 0 pasos."
    assert no_budget.tape == ("a",)


def test_step_by_step_matches_the_whole_run():
    machine = _an_bn()
    whole = run(machine, "aabb", trace=True)
    config = start(machine, "aabb")
    assert config.state == whole.steps[0].state
    assert config.tape == whole.steps[0].tape
    assert config.head == 0
    walked = [config]
    for _ in range(whole.steps_run):
        config = step(machine, config)
        walked.append(config)
    config = step(machine, config)
    assert config.status == "accept"
    assert [(item.state, item.head, item.tape) for item in walked] == [
        (item.state, item.head, item.tape) for item in whole.steps
    ]
    assert step(machine, config) is config


def test_move_left_writes_a_blank_and_does_not_mutate_the_machine():
    transitions = [_edge("q0", "a", "qf", "a", "L")]
    machine = TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=["a", "_"],
        blank="_",
        transitions=transitions,
    )
    result = run(machine, "a")
    assert result.status == "accept"
    assert result.tape == ("_", "a")
    assert result.head == 0
    assert machine.transitions is transitions
    assert transitions[0].move == "L"
    assert [state.initial for state in machine.states] == [True, False]


def test_right_only_machine_stops_with_no_termino():
    machine = _right_only()
    by_steps = run(machine, "a", max_steps=40, trace=True)
    assert by_steps.status == "timeout"
    assert by_steps.accepted is None
    assert by_steps.message == "No terminó: se agotaron los 40 pasos."
    assert by_steps.steps_run == 40
    assert by_steps.head == 40
    assert len(by_steps.tape) == 41
    assert len(by_steps.steps) == 41

    started = time.perf_counter()
    by_cells = run(machine, "a", trace=False)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.5
    assert by_cells.status == "timeout"
    assert by_cells.accepted is None
    assert by_cells.message == f"No terminó: la cinta llegó a {MAX_CELLS} celdas."
    assert by_cells.steps_run == MAX_CELLS - 1
    assert len(by_cells.tape) == MAX_CELLS
    assert by_cells.steps == ()

    tight = run(machine, "a", max_steps=MAX_STEPS, max_cells=8, trace=False)
    assert tight.message == "No terminó: la cinta llegó a 8 celdas."
    assert tight.steps_run == 7
    assert len(tight.tape) == 8


def test_a_machine_that_stays_forever_stops_at_the_step_limit():
    machine = TuringMachine(
        states=[TuringState("q0", initial=True)],
        tape_alphabet=["a", "_"],
        blank="_",
        transitions=[_edge("q0", "a", "q0", "a", "S")],
    )
    started = time.perf_counter()
    result = run(machine, "a", trace=False)
    assert time.perf_counter() - started < 0.5
    assert result.status == "timeout"
    assert result.message == f"No terminó: se agotaron los {MAX_STEPS} pasos."
    assert result.steps_run == MAX_STEPS
    assert result.tape == ("a",)
    assert result.head == 0


def test_validation_errors_are_in_spanish_and_do_not_run():
    alphabet = ["a", "_"]
    blank = "_"

    def build(**kwargs) -> TuringMachine:
        payload = {
            "states": [TuringState("q0", initial=True)],
            "tape_alphabet": alphabet,
            "blank": blank,
            "transitions": [],
        }
        payload.update(kwargs)
        return TuringMachine(**payload)

    two = build(
        transitions=[
            _edge("q0", "a", "q0", "a", "R"),
            _edge("q0", "a", "q0", "b", "L"),
        ],
        tape_alphabet=["a", "b", "_"],
    )
    none = build(states=[TuringState("q0", initial=False)])
    both = build(
        states=[
            TuringState("q0", initial=True),
            TuringState("q1", initial=True),
        ]
    )
    outside = build(transitions=[_edge("q0", "c", "q0", "a", "R")])
    bad_move = build(transitions=[_edge("q0", "a", "q0", "a", "l")])
    empty_read = build(transitions=[_edge("q0", "", "q0", "a", "R")])
    missing_state = build(transitions=[_edge("q0", "a", "q9", "a", "R")])

    cases = [
        (two, "dos transiciones"),
        (none, "exactamente un estado inicial"),
        (both, "exactamente un estado inicial"),
        (outside, "no está en el alfabeto"),
        (bad_move, "no es L, R ni S"),
        (empty_read, "no puede estar vacía"),
        (missing_state, "no existe"),
    ]
    for machine, piece in cases:
        with pytest.raises(TuringError) as exc:
            run(machine, "a")
        assert piece in str(exc.value)
        assert validate_tm(machine)

    with pytest.raises(TuringError) as exc:
        run(_right_only(), "a", max_steps=True)
    assert "entero" in str(exc.value)
    with pytest.raises(TuringError) as exc:
        run(_right_only(), "a", max_steps=10**20)
    assert "10000" in str(exc.value)
    with pytest.raises(TuringError) as exc:
        run(_right_only(), None)
    assert "texto" in str(exc.value)
    with pytest.raises(TuringError) as exc:
        run(_right_only(), 0)
    assert "texto" in str(exc.value)


def test_hostile_tape_symbols_do_not_crash_or_fold():
    machine = TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=["a", "b", "_"],
        blank="_",
        transitions=[_edge("q0", "a", "qf", "a", "R")],
    )
    with pytest.raises(TuringError) as exc:
        run(machine, "_")
    assert "blanco" in str(exc.value)
    with pytest.raises(TuringError) as exc:
        run(machine, "０")
    assert "no está en el alfabeto" in str(exc.value)
    with pytest.raises(TuringError) as exc:
        run(machine, "a" * (MAX_CELLS + 1))
    assert "no entra" in str(exc.value)

    mark = "\u0301"
    marked = TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("q1"), TuringState("qf", final=True)],
        tape_alphabet=["e", mark, "_"],
        blank="_",
        transitions=[
            _edge("q0", "e", "q1", "e", "R"),
            _edge("q1", mark, "qf", mark, "R"),
        ],
    )
    # «e» + acento está en el alfabeto: no se arma «é» y no se pierde el símbolo.
    kept = run(marked, "e" + mark)
    assert kept.status == "accept"
    assert kept.tape[:2] == ("e", mark)

    syllable = "\uac00"
    jamo = "\u1100\u1161"
    assert unicodedata.normalize("NFC", jamo) == syllable
    folded = TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=[syllable, "_"],
        blank="_",
        transitions=[_edge("q0", syllable, "qf", syllable, "R")],
    )
    assert run(folded, jamo).status == "accept"

    lead = "\u1100"
    apart = TuringMachine(
        states=[TuringState("q0", initial=True)],
        tape_alphabet=[lead, "_"],
        blank="_",
        transitions=[_edge("q0", lead, "q0", lead, "S")],
    )
    with pytest.raises(TuringError) as exc:
        run(apart, syllable)
    assert "no está en el alfabeto" in str(exc.value)

    compat = "\u3131"
    assert unicodedata.normalize("NFC", compat) == compat
    assert unicodedata.normalize("NFKC", compat) != compat
    compat_machine = TuringMachine(
        states=[TuringState("q0", initial=True, final=True)],
        tape_alphabet=[compat, "_"],
        blank="_",
        transitions=[],
    )
    assert run(compat_machine, compat).status == "accept"
    with pytest.raises(TuringError) as exc:
        run(compat_machine, lead)
    assert "no está en el alfabeto" in str(exc.value)


def test_blank_can_be_a_space_and_epsilon_is_just_a_symbol():
    space = TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=["a", " "],
        blank=" ",
        transitions=[_edge("q0", "a", "qf", "a", "R")],
    )
    result = run(space, "a")
    assert result.status == "accept"
    assert result.tape == ("a", " ")
    assert result.head == 1

    epsilon = "ε"
    with_epsilon = TuringMachine(
        states=[TuringState("q0", initial=True, final=True)],
        tape_alphabet=[epsilon, "_"],
        blank="_",
        transitions=[],
    )
    accepted = run(with_epsilon, epsilon)
    assert accepted.status == "accept"
    assert accepted.tape == (epsilon,)


def test_step_rejects_a_head_outside_the_tape_without_an_index_error():
    machine = _stay_into_final()
    with pytest.raises(TuringError) as exc:
        step(machine, Configuration("q0", ("a",), 5, "running"))
    assert "cabezal" in str(exc.value)
    assert not isinstance(exc.value, IndexError)

    original = ["a"]
    moved = step(machine, Configuration("q0", original, 0, "running"))
    assert original == ["a"]
    assert moved.tape == ("b",)
    assert moved.state == "qf"

    accent = "e\u0301"
    same = TuringMachine(
        states=[TuringState("é", initial=True), TuringState(accent)],
        tape_alphabet=["a", "_"],
        blank="_",
        transitions=[],
    )
    with pytest.raises(TuringError) as exc:
        run(same, "a")
    assert "mismo nombre" in str(exc.value)

    repeated = TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=["é", "_"],
        blank="_",
        transitions=[
            _edge("q0", "é", "qf", "é", "S"),
            _edge("q0", accent, "q0", "é", "R"),
        ],
    )
    with pytest.raises(TuringError) as exc:
        run(repeated, "é")
    assert "dos transiciones" in str(exc.value)


def test_limits_match_the_roadmap_and_a_second_run_starts_clean():
    assert MAX_STEPS == 10000
    assert MAX_CELLS == 4096
    machine = _an_bn()
    assert run(machine, "ab").accepted is True
    assert run(machine, "ba").accepted is False
    assert run(machine, "aabb").accepted is True


def test_stepping_to_the_cell_cap_does_not_reread_the_tape():
    """4096 pasos no pueden releer la cinta entera en cada uno.

    Antes, cada step revisaba todas las celdas. Ir a la derecha hasta el
    tope tardaba unos 6,6 s. run, que no hace eso, tarda cerca de 1 ms.
    """
    machine = _right_only()
    started = time.perf_counter()
    config = start(machine, "a")
    taken = 0
    while config.status == "running":
        config = step(machine, config)
        taken += 1
        if taken > MAX_CELLS + 2:
            break
    elapsed = time.perf_counter() - started
    whole = run(machine, "a", trace=False)
    assert elapsed < 0.5
    assert taken == MAX_CELLS
    assert config.status == whole.status == "timeout"
    assert config.state == whole.state
    assert config.head == whole.head
    assert config.tape == whole.tape
    assert config.message == whole.message
    assert len(config.tape) == MAX_CELLS


def test_step_uses_a_transition_replaced_before_the_next_step():
    machine = _right_only()
    config = start(machine, "a")
    config = step(machine, config)
    assert config.tape == ("a", "_")
    assert config.head == 1
    machine.transitions[:] = [
        _edge("q0", "a", "q0", "a", "S"),
        _edge("q0", "_", "q0", "a", "S"),
    ]
    moved = step(machine, config)
    assert moved.status == "running"
    assert moved.state == "q0"
    assert moved.head == 1
    assert moved.tape == ("a", "a")


def test_step_rejects_a_symbol_when_the_alphabet_changes():
    machine = _right_only()
    config = start(machine, "a")
    machine.tape_alphabet = ["b", "_"]
    machine.transitions[:] = [
        _edge("q0", "b", "q0", "b", "R"),
        _edge("q0", "_", "q0", "_", "R"),
    ]
    with pytest.raises(TuringError) as exc:
        step(machine, config)
    assert "«a» no está en el alfabeto" in str(exc.value)


def test_step_normalizes_an_external_tape_before_trusting_it():
    accent = "e\u0301"
    machine = TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=["é", "_"],
        blank="_",
        transitions=[_edge("q0", "é", "qf", "é", "S")],
    )
    moved = step(machine, Configuration("q0", (accent,), 0, "running"))
    assert moved.state == "qf"
    assert moved.tape == ("é",)
    assert moved.status == "running"
    done = step(machine, moved)
    assert done.status == "accept"
    assert done.tape == ("é",)


def test_step_does_not_keep_the_old_write_when_new_arrows_reuse_the_address():
    """Treinta reemplazos. clear() libera las flechas y la dirección se reusa.

    La firma no puede ser id(): 15 de esos reemplazos seguían escribiendo
    lo viejo. Cada par nuevo escribe b y se queda.
    """
    machine = TuringMachine(
        states=[TuringState("q0", initial=True)],
        tape_alphabet=["a", "b", "_"],
        blank="_",
        transitions=[
            _edge("q0", "a", "q0", "a", "R"),
            _edge("q0", "_", "q0", "_", "R"),
        ],
    )
    warmed = step(machine, start(machine, "a"))
    assert warmed.tape == ("a", "_")
    assert warmed.head == 1
    stale = 0
    for _ in range(30):
        machine.transitions.clear()
        machine.transitions.append(_edge("q0", "a", "q0", "b", "S"))
        machine.transitions.append(_edge("q0", "_", "q0", "b", "S"))
        gc.collect()
        moved = step(machine, start(machine, "a"))
        if moved.tape != ("b",) or moved.head != 0 or moved.status != "running":
            stale += 1
    assert stale == 0

    # El mismo hueco, del lado de los estados: el final nuevo reusa la dirección.
    halting = TuringMachine(
        states=[TuringState("q0", initial=True)],
        tape_alphabet=["a", "_"],
        blank="_",
        transitions=[],
    )
    first = step(halting, start(halting, "a"))
    assert first.status == "reject"
    missed = 0
    for _ in range(30):
        halting.states.clear()
        halting.states.append(TuringState("q0", initial=True, final=True))
        gc.collect()
        halted = step(halting, start(halting, "a"))
        if halted.status != "accept" or halted.tape != ("a",):
            missed += 1
    assert missed == 0


def test_replace_does_not_carry_the_tape_check_to_another_tape():
    """El sello vive en la configuración. replace lo copiaba a otra cinta.

    La máquina se queda en a. («a», «Z») no puede seguir corriendo: Z no
    está en el alfabeto. Tres pasos seguidos lo dejaban en running.
    """
    machine = TuringMachine(
        states=[TuringState("q0", initial=True)],
        tape_alphabet=["a", "b", "_"],
        blank="_",
        transitions=[_edge("q0", "a", "q0", "a", "S")],
    )
    config = start(machine, "a")
    kept = replace(config, tape=("a", "b"))
    moved = step(machine, kept)
    assert moved.status == "running"
    assert moved.tape == ("a", "b")
    assert moved.head == 0
    forged = replace(config, tape=("a", "Z"))
    with pytest.raises(TuringError) as exc:
        current = forged
        for _ in range(3):
            current = step(machine, current)
    assert "«Z» no está en el alfabeto" in str(exc.value)


class _Igual:
    """Igual por == al valor guardado, y de otro tipo."""

    def __init__(self, value: object) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return other == self.value


def _warm_one_step() -> tuple[TuringMachine, Configuration]:
    machine = TuringMachine(
        states=[TuringState("q0", initial=True, final=True), TuringState("q1", final=False)],
        tape_alphabet=["a", "1", "_"],
        blank="_",
        transitions=[_edge("q0", "a", "q1", "1", "R")],
    )
    config = start(machine, "a")
    moved = step(machine, config)
    assert moved.status == "running"
    assert moved.state == "q1"
    return machine, config


def _assert_step_matches_run(machine: TuringMachine, config: Configuration) -> str:
    step_error = None
    try:
        step(machine, config)
    except TuringError as exc:
        step_error = str(exc)
    run_error = None
    try:
        run(machine, "a")
    except TuringError as exc:
        run_error = str(exc)
    assert step_error == run_error
    assert step_error is not None
    return step_error


def test_step_rejects_bool_flags_written_as_integers():
    """True == 1 y False == 0. La firma no puede compararlos pelados.

    Después de un paso válido, final=1, final=0 e initial=1 tienen que
    fallar igual que run.
    """
    replacements = [
        [TuringState("q0", initial=True, final=1), TuringState("q1", final=False)],
        [TuringState("q0", initial=True, final=True), TuringState("q1", final=0)],
        [TuringState("q0", initial=1, final=True), TuringState("q1", final=False)],
        [TuringState("q0", initial=1.0, final=True), TuringState("q1", final=False)],
    ]
    for states in replacements:
        machine, config = _warm_one_step()
        machine.states[:] = states
        message = _assert_step_matches_run(machine, config)
        assert "Inicial y final tienen que ser sí o no." in message


def test_step_rejects_a_field_whose_type_changed():
    """1, True y «1» no son el mismo símbolo. Tampoco un objeto igual a «a».

    El alfabeto, el blanco y cada campo de la flecha tienen que invalidar
    el cache. step y run dicen el mismo texto.
    """
    swaps = [
        lambda machine: machine.tape_alphabet.__setitem__(1, 1),
        lambda machine: machine.tape_alphabet.__setitem__(1, True),
        lambda machine: machine.tape_alphabet.__setitem__(0, _Igual("a")),
        lambda machine: setattr(machine, "blank", _Igual("_")),
        lambda machine: machine.states.__setitem__(0, TuringState(_Igual("q0"), initial=True, final=True)),
        lambda machine: machine.transitions.__setitem__(0, TuringTransition(_Igual("q0"), "a", "q1", "1", "R")),
        lambda machine: machine.transitions.__setitem__(0, TuringTransition("q0", _Igual("a"), "q1", "1", "R")),
        lambda machine: machine.transitions.__setitem__(0, TuringTransition("q0", "a", _Igual("q1"), "1", "R")),
        lambda machine: machine.transitions.__setitem__(0, TuringTransition("q0", "a", "q1", 1, "R")),
        lambda machine: machine.transitions.__setitem__(0, TuringTransition("q0", "a", "q1", True, "R")),
        lambda machine: machine.transitions.__setitem__(0, TuringTransition("q0", "a", "q1", _Igual("1"), "R")),
        lambda machine: machine.transitions.__setitem__(0, TuringTransition("q0", "a", "q1", "1", 1)),
        lambda machine: machine.transitions.__setitem__(0, TuringTransition("q0", "a", "q1", "1", True)),
        lambda machine: machine.transitions.__setitem__(0, TuringTransition("q0", "a", "q1", "1", "1")),
    ]
    for swap in swaps:
        machine, config = _warm_one_step()
        swap(machine)
        _assert_step_matches_run(machine, config)

    machine, config = _warm_one_step()
    machine.transitions[0] = TuringTransition("q0", "a", "q1", "1", _Igual("R"))
    moved = step(machine, config)
    traced = run(machine, "a", trace=True)
    assert (moved.state, moved.head, moved.tape) == (
        traced.steps[1].state,
        traced.steps[1].head,
        traced.steps[1].tape,
    )


def test_a_control_in_the_alphabet_is_rejected_in_spanish():
    machine = TuringMachine(
        states=[TuringState("q0", initial=True)],
        tape_alphabet=["a", "\n", "_"],
        blank="_",
        transitions=[],
    )
    with pytest.raises(TuringError) as exc:
        run(machine, "a")
    text = str(exc.value)
    assert "control" in text
    assert "\n" not in text
