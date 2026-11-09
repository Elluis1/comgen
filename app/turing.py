"""Máquina de Turing de una cinta, determinista.

El modelo es el de la materia y el que abre JFLAP: estados, un solo inicial,
finales, alfabeto de cinta, blanco y transiciones
(estado, lee) → (estado, escribe, L|R|S). La posición del cabezal vive en
la configuración, no en la transición. Empieza en el primer símbolo. Si la
entrada está vacía, la cinta tiene un blanco y el cabezal está ahí.

La cinta es infinita para los dos lados. L va a la izquierda, R a la
derecha y S se queda. El blanco es un símbolo del alfabeto: no es la
cadena vacía. Irse del tramo escrito agrega un blanco de ese lado.

Si falta la transición del símbolo bajo el cabezal, la máquina se detiene.
Acepta si ese estado es final y rechaza si no. No se inventa un pozo.
«No terminó» queda para el tope de pasos o el de celdas: no es un rechazo
ni una excepción.

El .jff vive en app/turing_jflap.py: el blanco sale como una etiqueta vacía.
Esta simulación no dibuja la cinta: eso está en la pantalla. No agrega
ejemplos y no llama al modelo. Si se pide la traza con un tope, se guardan
como mucho MAX_TRACE_STEPS cintas (el arranque y la última). Sin tope, la
traza copia cada paso, como antes. Sin traza no se copia la cinta del medio.
"""

import unicodedata
from dataclasses import dataclass, field

from app.sanitize import is_control_or_invisible, xml_char_allowed

# Los números de la hoja. Ir solo a la derecha, con los dos topes a la vez,
# llena las celdas antes que los pasos: 4096 es menor que 10000. Igual
# responde «No terminó». El tope de pasos se ve con un máximo más chico,
# o con una máquina que no agranda la cinta.
MAX_STEPS = 10000
MAX_CELLS = 4096
MAX_STATES = 256
MAX_TRANSITIONS = 4096
MAX_ALPHABET = 64
# La pantalla pide la traza con este tope. 256 cintas alcanzan para una
# máquina chica y, si la corrida es más larga, quedan el arranque y la
# última. No subirlo: guardar cada paso hasta 4096 celdas arma un triángulo
# de copias.
MAX_TRACE_STEPS = 256
_NAME_LIMIT = 64
_MOVES = ("L", "R", "S")
# Un texto más largo que esto no entra ni aunque el NFC lo encoja.
_RAW_WORD_LIMIT = MAX_CELLS * 8


class TuringError(Exception):
    pass


@dataclass(frozen=True)
class TuringState:
    id: str
    initial: bool = False
    final: bool = False


@dataclass(frozen=True)
class TuringTransition:
    """(estado, lee) → (estado, escribe, L|R|S)."""

    state: str
    read: str
    to: str
    write: str
    move: str


class TuringMachine:
    def __init__(
        self,
        states: list[TuringState] | tuple[TuringState, ...],
        tape_alphabet: list[str] | tuple[str, ...],
        blank: str,
        transitions: list[TuringTransition] | tuple[TuringTransition, ...],
        description: str = "",
    ) -> None:
        self.states = states
        self.tape_alphabet = tape_alphabet
        self.blank = blank
        self.transitions = transitions
        self.description = description


@dataclass(frozen=True)
class Configuration:
    """Un instante: estado, cinta y posición del cabezal.

    status es running, accept, reject o timeout. La cinta guardada es el
    tramo visitado; afuera hay blancos que todavía no se escribieron.

    Los campos de abajo no salen en dump. Marcan que esa cinta ya se revisó
    para ese alfabeto y esos estados, así el paso siguiente no vuelve a leer
    cada celda. El sello nombra la cinta concreta: copiar la configuración
    a otra cinta no arrastra la revisión.
    """

    state: str
    tape: tuple[str, ...]
    head: int
    status: str
    message: str = ""
    _checked_states: frozenset[str] | None = field(default=None, compare=False, repr=False)
    _checked_alphabet: frozenset[str] | None = field(default=None, compare=False, repr=False)
    _checked_tape: tuple[str, ...] | None = field(default=None, compare=False, repr=False)

    def dump(self) -> dict:
        return {
            "state": self.state,
            "tape": list(self.tape),
            "head": self.head,
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True)
class TuringRun:
    status: str
    accepted: bool | None
    message: str
    state: str
    tape: tuple[str, ...]
    head: int
    steps_run: int
    steps: tuple[Configuration, ...] = ()
    trace_omitted: int = 0
    step_indexes: tuple[int, ...] = ()
    blank: str = "_"

    def dump(self) -> dict:
        indexed = self.trace_omitted > 0 and len(self.step_indexes) == len(self.steps)
        steps = []
        for position, step in enumerate(self.steps):
            item = step.dump()
            if indexed:
                item["index"] = self.step_indexes[position]
            steps.append(item)
        body = {
            "status": self.status,
            "accepted": self.accepted,
            "message": self.message,
            "state": self.state,
            "tape": list(self.tape),
            "head": self.head,
            "steps_run": self.steps_run,
            "steps": steps,
            # La pantalla pinta ␣ con este símbolo. No es siempre «_».
            "blank": self.blank if isinstance(self.blank, str) else "",
        }
        if self.trace_omitted:
            body["trace_omitted"] = self.trace_omitted
        return body


@dataclass(frozen=True)
class _Prepared:
    initial: str
    finals: frozenset[str]
    blank: str
    alphabet: frozenset[str]
    states: frozenset[str]
    table: dict[tuple[str, str], tuple[str, str, str]]


def validate_tm(machine: TuringMachine) -> list[str]:
    """Errores en español. Vacío si la máquina se puede simular."""
    if not isinstance(machine, TuringMachine):
        return ["La máquina no tiene el formato esperado."]
    errors: list[str] = []
    states = _as_list(machine.states)
    alphabet = _as_list(machine.tape_alphabet)
    transitions = _as_list(machine.transitions)
    if states is None:
        errors.append("Los estados tienen que ser una lista.")
    if alphabet is None:
        errors.append("El alfabeto de la cinta tiene que ser una lista.")
    if transitions is None:
        errors.append("Las transiciones tienen que ser una lista.")
    if states is None or alphabet is None or transitions is None:
        return _cap(errors)
    if (
        len(states) > MAX_STATES
        or len(alphabet) > MAX_ALPHABET
        or len(transitions) > MAX_TRANSITIONS
    ):
        errors.append(
            f"La máquina se valida hasta {MAX_STATES} estados, {MAX_ALPHABET} símbolos "
            f"y {MAX_TRANSITIONS} transiciones para no trabar el equipo."
        )
        return _cap(errors)
    if not states:
        errors.append("La máquina no tiene estados.")

    symbol_set: set[str] = set()
    for raw in alphabet:
        canon = _canon_symbol(raw)
        if canon is None:
            errors.append(_symbol_issue(raw))
            continue
        if canon in symbol_set:
            errors.append(f"El símbolo «{canon}» está repetido en el alfabeto.")
        symbol_set.add(canon)

    blank = _canon_symbol(machine.blank)
    if blank is None:
        if isinstance(machine.blank, str) and _has_control(machine.blank):
            errors.append("El blanco no puede ser un carácter de control.")
        else:
            errors.append("El blanco tiene que ser un solo carácter del alfabeto de la cinta.")
    elif blank not in symbol_set:
        errors.append("El blanco tiene que ser un solo carácter del alfabeto de la cinta.")

    name_set: set[str] = set()
    initials: list[str] = []
    for state in states:
        if not isinstance(state, TuringState):
            errors.append("Hay un estado que no es un estado de la máquina.")
            continue
        if not isinstance(state.initial, bool) or not isinstance(state.final, bool):
            errors.append("Inicial y final tienen que ser sí o no.")
            continue
        reason = _name_problem(state.id)
        if reason:
            errors.append(f"El estado no sirve: {reason}.")
            continue
        name = _nfc(state.id)
        if name in name_set:
            errors.append(f"Hay dos estados con el mismo nombre: «{name}».")
        name_set.add(name)
        if state.initial:
            initials.append(name)

    if len(initials) != 1:
        if len(initials) > 1:
            shown = " y ".join(f"«{name}»" for name in initials[:4])
            errors.append(
                f"Tiene que haber exactamente un estado inicial. Hay {len(initials)}: {shown}."
            )
        else:
            errors.append("Tiene que haber exactamente un estado inicial.")

    seen: set[tuple[str, str]] = set()
    for transition in transitions:
        if not isinstance(transition, TuringTransition):
            errors.append("Hay una transición que no es una transición de la máquina.")
            continue
        origin = _known_name(transition.state, name_set, errors, "de origen")
        dest = _known_name(transition.to, name_set, errors, "de destino")
        read = _known_symbol(transition.read, symbol_set, errors, "La lectura")
        write = _known_symbol(transition.write, symbol_set, errors, "La escritura")
        move = transition.move
        if move not in _MOVES:
            errors.append(f"El movimiento «{_show(move)}» no es L, R ni S.")
            move = ""
        if origin is None or read is None or dest is None or write is None or not move:
            continue
        key = (origin, read)
        if key in seen:
            errors.append(f"Hay dos transiciones desde «{origin}» leyendo «{read}».")
            continue
        seen.add(key)
    return _cap(errors)


def start(machine: TuringMachine, word: str = "", *, max_cells: int = MAX_CELLS) -> Configuration:
    """Configuración inicial. El cabezal queda en el primer símbolo."""
    _check_cells(max_cells)
    prepared = _prepare_cached(machine)
    symbols = _read_input(prepared, word, max_cells)
    tape = tuple(symbols) if symbols else (prepared.blank,)
    return _seal(Configuration(prepared.initial, tape, 0, "running"), prepared)


def step(machine: TuringMachine, config: Configuration, *, max_cells: int = MAX_CELLS) -> Configuration:
    """Un paso. Devuelve el estado, la cinta y la posición del cabezal.

    No aplica el tope de pasos: una sola llamada no puede colgarse. Si la
    configuración ya estaba detenida, se devuelve igual. Si la cinta ya se
    revisó para esta máquina, no se vuelven a mirar todas las celdas.
    """
    _check_cells(max_cells)
    if not isinstance(config, Configuration):
        raise TuringError("El paso necesita la configuración de la cinta.")
    if config.status != "running":
        return config
    return _step_prepared(_prepare_cached(machine), config, max_cells)


def run(
    machine: TuringMachine,
    word: str = "",
    *,
    max_steps: int = MAX_STEPS,
    max_cells: int = MAX_CELLS,
    trace: bool = False,
    trace_cap: int | None = None,
) -> TuringRun:
    """Corre hasta aceptar, rechazar o agotar un tope.

    Con trace, steps trae la configuración inicial y una por transición.
    La última tiene el resultado. Sin trace no se copian las cintas del
    medio: en el tope de celdas eso sería un triángulo de miles de casillas.

    Con trace_cap la traza guarda como mucho esa cantidad. Si la corrida
    entra, se copian todos los pasos. Si no, se copian el arranque y la
    última configuración: el medio no se copia.
    """
    if not isinstance(trace, bool):
        raise TuringError("La traza tiene que ser sí o no.")
    cap: int | None = None
    if trace_cap is not None:
        cap = _check_trace_cap(trace_cap)
        if not trace:
            raise TuringError("El tope de la traza pide guardar los pasos.")
    _check_steps(max_steps)
    _check_cells(max_cells)
    _check_word(word)
    prepared = _prepare(machine)
    symbols = _read_input(prepared, word, max_cells)
    tape = list(symbols) if symbols else [prepared.blank]
    state = prepared.initial
    head = 0
    # La traza completa copia la cinta en cada paso. Sin traza se reutiliza
    # la lista: ir solo a la derecha hasta el tope no arma un triángulo.
    # Con tope, al llenarse el arranque se deja de copiar hasta el final.
    steps: list[Configuration] = []
    indexes: list[int] = []
    seen = 0
    skipped = False
    room = (cap - 1) if cap is not None else 0

    def remember() -> None:
        nonlocal seen, skipped
        index = seen
        seen += 1
        if len(steps) >= room:
            skipped = True
            return
        steps.append(Configuration(state, tuple(tape), head, "running"))
        indexes.append(index)

    if trace and cap is None:
        steps.append(Configuration(state, tuple(tape), head, "running"))
    elif trace:
        remember()
    applied = 0
    status = "running"
    message = ""
    while status == "running":
        if applied >= max_steps:
            halted = _halt_on_tape(prepared, state, tape, head)
            if halted is None:
                status = "timeout"
                message = _steps_message(max_steps)
            else:
                status, message = halted
            break
        rule = prepared.table.get((state, tape[head]))
        if rule is None:
            status, message = _finish_on_tape(prepared, state, tape[head])
            break
        moved = _try_move(tape, head, rule, prepared.blank, max_cells)
        if moved is None:
            status = "timeout"
            message = _cells_message(max_cells)
            break
        state, head = moved
        applied += 1
        if trace and cap is None:
            steps.append(Configuration(state, tuple(tape), head, "running"))
        elif trace:
            remember()
    omitted = 0
    step_indexes: tuple[int, ...] = ()
    if trace and cap is None:
        steps[-1] = Configuration(state, tuple(tape), head, status, message)
    elif trace:
        final = Configuration(state, tuple(tape), head, status, message)
        if skipped:
            steps.append(final)
            indexes.append(seen - 1)
            omitted = seen - len(steps)
            if omitted > 0:
                step_indexes = tuple(indexes)
        else:
            steps[-1] = final
    return TuringRun(
        status=status,
        accepted=_accepted(status),
        message=message,
        state=state,
        tape=tuple(tape),
        head=head,
        steps_run=applied,
        steps=tuple(steps),
        trace_omitted=omitted,
        step_indexes=step_indexes,
        blank=prepared.blank,
    )


def _prepare_cached(machine: TuringMachine) -> _Prepared:
    """Revalida solo si cambiaron los estados, el alfabeto o las flechas.

    La firma es por valor y por tipo. id() no sirve: si el objeto viejo se
    libera, uno nuevo puede ocupar esa dirección. == tampoco: True == 1 y
    False == 0, y un símbolo puede igualar a otro sin ser texto. Cada campo
    guarda el tipo junto al valor, así step valida igual que run. El
    resultado queda en la máquina. No hay un diccionario global: cuando la
    máquina se junta, el cache se va con ella. run no pasa por acá.
    """
    signature = _machine_signature(machine)
    cached = getattr(machine, "_prepared_cache", None)
    if signature is not None and isinstance(cached, tuple) and len(cached) == 2 and cached[0] == signature:
        return cached[1]
    prepared = _prepare(machine)
    if signature is not None:
        machine._prepared_cache = (signature, prepared)
    return prepared


def _machine_signature(machine: TuringMachine) -> tuple | None:
    states = machine.states
    alphabet = machine.tape_alphabet
    transitions = machine.transitions
    if (
        not _cacheable_sequence(states)
        or not _cacheable_sequence(alphabet)
        or not _cacheable_sequence(transitions)
    ):
        return None
    if (
        len(states) > MAX_STATES
        or len(alphabet) > MAX_ALPHABET
        or len(transitions) > MAX_TRANSITIONS
    ):
        return None
    # Sin generadores: cada paso arma esta clave, y un generador se queda
    # vivo hasta el recolector. En 4096 pasos eso infla el pico. La tupla
    # guarda los campos, no la dirección del objeto. El tipo va junto al
    # valor: True == 1, pero no son el mismo campo.
    state_key: list[tuple] = []
    for item in states:
        if not isinstance(item, TuringState):
            return None
        state_key.append((_typed(item.id), _typed(item.initial), _typed(item.final)))
    alphabet_key = [_typed(symbol) for symbol in alphabet]
    arrow_key: list[tuple] = []
    for item in transitions:
        if not isinstance(item, TuringTransition):
            return None
        arrow_key.append(
            (
                _typed(item.state),
                _typed(item.read),
                _typed(item.to),
                _typed(item.write),
                _typed(item.move),
            )
        )
    return (tuple(state_key), tuple(alphabet_key), tuple(arrow_key), _typed(machine.blank))


def _typed(value: object) -> tuple[type, object]:
    return (type(value), value)


def _cacheable_sequence(value: object) -> bool:
    return not isinstance(value, (str, bytes)) and isinstance(value, (list, tuple))


def _prepare(machine: TuringMachine) -> _Prepared:
    errors = validate_tm(machine)
    if errors:
        raise TuringError(" ".join(errors))
    names: list[str] = []
    initials: list[str] = []
    finals: set[str] = set()
    for state in machine.states:
        name = _nfc(state.id)
        names.append(name)
        if state.initial:
            initials.append(name)
        if state.final:
            finals.add(name)
    blank = _canon_symbol(machine.blank)
    alphabet = {_canon_symbol(symbol) for symbol in machine.tape_alphabet}
    table: dict[tuple[str, str], tuple[str, str, str]] = {}
    for transition in machine.transitions:
        origin = _nfc(transition.state)
        read = _canon_symbol(transition.read)
        dest = _nfc(transition.to)
        write = _canon_symbol(transition.write)
        if origin is None or read is None or dest is None or write is None:
            continue
        table[(origin, read)] = (dest, write, transition.move)
    return _Prepared(
        initial=initials[0],
        finals=frozenset(finals),
        blank=blank if isinstance(blank, str) else "",
        alphabet=frozenset(symbol for symbol in alphabet if isinstance(symbol, str)),
        states=frozenset(names),
        table=table,
    )


def _step_prepared(prepared: _Prepared, config: Configuration, max_cells: int) -> Configuration:
    if config.status != "running":
        return config
    # Una cinta que armó start o el paso anterior ya está en el alfabeto.
    # Releerla entera en cada paso, hasta el tope de celdas, es un triángulo.
    if not _tape_is_ready(config, prepared):
        config = _normalize_running(prepared, config)
    halted = _halt_on_tape(prepared, config.state, config.tape, config.head)
    if halted is not None:
        status, message = halted
        return _mark(config, status, message)
    rule = prepared.table[(config.state, config.tape[config.head])]
    tape = list(config.tape)
    moved = _try_move(tape, config.head, rule, prepared.blank, max_cells)
    if moved is None:
        return _mark(config, "timeout", _cells_message(max_cells))
    state, head = moved
    return _seal(Configuration(state, tuple(tape), head, "running"), prepared)


def _tape_is_ready(config: Configuration, prepared: _Prepared) -> bool:
    """True si basta con mirar el símbolo bajo el cabezal.

    La cinta que armó start o el paso anterior ya está en el alfabeto.
    El sello es de esa cinta: si la configuración se copió a otra, no vale.
    Si cambiaron las flechas, el cache no pega y esta cinta se revisa de nuevo.
    """
    tape = config.tape
    if tape is not config._checked_tape:
        return False
    if config._checked_states != prepared.states or config._checked_alphabet != prepared.alphabet:
        return False
    head = config.head
    if not isinstance(tape, tuple) or not tape:
        return False
    if isinstance(head, bool) or not isinstance(head, int):
        return False
    if head < 0 or head >= len(tape):
        return False
    if not isinstance(config.state, str) or config.state not in prepared.states:
        return False
    symbol = tape[head]
    return isinstance(symbol, str) and symbol in prepared.alphabet


def _seal(config: Configuration, prepared: _Prepared) -> Configuration:
    return Configuration(
        config.state,
        config.tape,
        config.head,
        config.status,
        config.message,
        prepared.states,
        prepared.alphabet,
        config.tape,
    )


def _halt_on_tape(
    prepared: _Prepared,
    state: str,
    tape: list[str] | tuple[str, ...],
    head: int,
) -> tuple[str, str] | None:
    if (state, tape[head]) in prepared.table:
        return None
    return _finish_on_tape(prepared, state, tape[head])


def _finish_on_tape(prepared: _Prepared, state: str, symbol: str) -> tuple[str, str]:
    if state in prepared.finals:
        return "accept", f"Acepta: se detuvo en el estado final «{state}»."
    return "reject", f"Rechaza: falta la transición de «{state}» leyendo «{symbol}»."


def _try_move(
    tape: list[str],
    head: int,
    rule: tuple[str, str, str],
    blank: str,
    max_cells: int,
) -> tuple[str, int] | None:
    """Aplica la transición sobre la lista. None si no entra otra celda.

    No toca la lista cuando no hay lugar: el paso no queda a medias.
    """
    dest, write, move = rule
    grows = (move == "R" and head == len(tape) - 1) or (move == "L" and head == 0)
    if grows and len(tape) >= max_cells:
        return None
    tape[head] = write
    if move == "R":
        if head == len(tape) - 1:
            tape.append(blank)
        head += 1
    elif move == "L":
        if head == 0:
            tape.insert(0, blank)
            head = 0
        else:
            head -= 1
    return dest, head


def _normalize_running(prepared: _Prepared, config: Configuration) -> Configuration:
    if not isinstance(config.state, str):
        raise TuringError("El estado de la cinta tiene que ser un texto.")
    reason = _name_problem(config.state)
    if reason:
        raise TuringError(f"El estado de la cinta no sirve: {reason}.")
    state = _nfc(config.state)
    if state not in prepared.states:
        raise TuringError(f"El estado «{_show(state)}» no está en la máquina.")
    tape = config.tape
    if isinstance(tape, (str, bytes)) or not isinstance(tape, (list, tuple)):
        raise TuringError("La cinta tiene que ser una lista de símbolos.")
    if isinstance(config.head, bool) or not isinstance(config.head, int):
        raise TuringError("La posición del cabezal tiene que ser un entero.")
    symbols: list[str] = []
    for raw in tape:
        canon = _canon_symbol(raw)
        if canon is None or canon not in prepared.alphabet:
            raise TuringError(f"«{_show(raw)}» no está en el alfabeto de la cinta.")
        symbols.append(canon)
    if not symbols:
        raise TuringError("La cinta no puede estar vacía.")
    if config.head < 0 or config.head >= len(symbols):
        raise TuringError("El cabezal quedó fuera de la cinta.")
    normalized = tuple(symbols)
    if state == config.state and normalized == tape and isinstance(tape, tuple):
        return config
    return Configuration(state, normalized, config.head, "running", config.message)


def _read_input(prepared: _Prepared, word: object, max_cells: int) -> list[str]:
    _check_word(word)
    if not isinstance(word, str):
        raise TuringError("La cadena tiene que ser un texto.")
    symbols = _input_symbols(word, prepared.alphabet)
    if len(symbols) > max_cells:
        raise TuringError(f"La cadena no entra en las {max_cells} celdas de la cinta.")
    for symbol in symbols:
        if symbol == prepared.blank:
            raise TuringError("La entrada no puede traer el blanco.")
        if symbol not in prepared.alphabet:
            raise TuringError(f"«{_show(symbol)}» no está en el alfabeto de la cinta.")
    return symbols


def _input_symbols(word: str, alphabet: frozenset[str]) -> list[str]:
    """Parte la entrada como la simulación del autómata.

    Si una marca o un jamo está en el alfabeto, esa pieza queda sola. El
    resto de la misma palabra igual se compone: «e» + acento sigue siendo
    «é» aunque al lado haya un jamo del alfabeto. Si nada de eso está en
    el alfabeto, se normaliza la palabra entera. Una sílaba ya compuesta
    no se parte.
    """
    # La misma regla que las cadenas del autómata. Partir todo el texto
    # cuando una sola pieza está en el alfabeto se comía la «é» de al lado.
    from app.simulate import _word_symbols

    return _word_symbols(word, alphabet)


def _check_word(word: object) -> None:
    if not isinstance(word, str):
        raise TuringError("La cadena tiene que ser un texto.")
    if len(word) > _RAW_WORD_LIMIT:
        raise TuringError("La cadena es demasiado larga para la cinta.")


def _check_trace_cap(trace_cap: object) -> int:
    if isinstance(trace_cap, bool) or not isinstance(trace_cap, int):
        raise TuringError(
            f"El tope de la traza tiene que ser un entero entre 2 y {MAX_STEPS}."
        )
    if trace_cap < 2 or trace_cap > MAX_STEPS:
        raise TuringError(
            f"El tope de la traza tiene que ser un entero entre 2 y {MAX_STEPS}."
        )
    return trace_cap


def _check_steps(max_steps: object) -> None:
    if isinstance(max_steps, bool) or not isinstance(max_steps, int):
        raise TuringError("El tope de pasos tiene que ser un entero.")
    if max_steps < 0 or max_steps > MAX_STEPS:
        raise TuringError(f"El tope de pasos tiene que estar entre 0 y {MAX_STEPS}.")


def _check_cells(max_cells: object) -> None:
    if isinstance(max_cells, bool) or not isinstance(max_cells, int):
        raise TuringError("El tope de celdas tiene que ser un entero.")
    if max_cells < 1 or max_cells > MAX_CELLS:
        raise TuringError(f"El tope de celdas tiene que estar entre 1 y {MAX_CELLS}.")


def _known_name(value: object, names: set[str], errors: list[str], role: str) -> str | None:
    reason = _name_problem(value)
    if reason:
        errors.append(f"El estado {role} no sirve: {reason}.")
        return None
    assert isinstance(value, str)
    name = _nfc(value)
    if name not in names:
        errors.append(f"La transición usa el estado «{_show(name)}», que no existe.")
    return name


def _known_symbol(value: object, alphabet: set[str], errors: list[str], label: str) -> str | None:
    canon = _canon_symbol(value)
    if canon is None:
        if isinstance(value, str) and value != "" and not _has_control(value):
            errors.append(f"{label} «{_show(value)}» tiene que ser un solo carácter.")
        elif isinstance(value, str) and _has_control(value):
            errors.append(f"{label} no puede ser un carácter de control.")
        else:
            empty = "El blanco es un símbolo, no una cadena vacía." if label == "La lectura" else ""
            errors.append(f"{label} no puede estar vacía. {empty}".rstrip())
        return None
    if canon not in alphabet:
        errors.append(f"«{canon}» no está en el alfabeto de la cinta.")
    return canon


def _canon_symbol(symbol: object) -> str | None:
    if not isinstance(symbol, str) or symbol == "" or _has_control(symbol):
        return None
    folded = symbol if symbol.isascii() else _nfc(symbol)
    if len(folded) != 1 or _has_control(folded):
        return None
    return folded


def _symbol_issue(symbol: object) -> str:
    if not isinstance(symbol, str) or symbol == "":
        return "Hay un símbolo vacío en el alfabeto. Tiene que ser un solo carácter."
    if _has_control(symbol):
        return "Hay un carácter de control en el alfabeto de la cinta."
    folded = symbol if symbol.isascii() else _nfc(symbol)
    if _has_control(folded):
        return "Hay un carácter de control en el alfabeto de la cinta."
    return f"«{_show(folded)}» no puede estar en el alfabeto: tiene que ser un solo carácter."


def _name_problem(name: object) -> str | None:
    # JFLAP guarda «Ret 1». El espacio de adentro entra. Vacío no, ni un
    # espacio Unicode en cualquiera de las dos puntas, ni un tab o un salto.
    if not isinstance(name, str) or name == "" or name[0].isspace() or name[-1].isspace():
        return "está vacío o tiene espacios"
    if any(char.isspace() and char != " " for char in name):
        return "está vacío o tiene espacios"
    folded = name if name.isascii() else _nfc(name)
    if len(folded) > _NAME_LIMIT:
        return "es demasiado largo"
    if _has_control(folded):
        return "tiene un carácter de control"
    return None


def _has_control(text: str) -> bool:
    return any(is_control_or_invisible(char) or not xml_char_allowed(char) for char in text)


def _nfc(value: str) -> str:
    if value.isascii():
        return value
    return unicodedata.normalize("NFC", value)


def _show(value: object) -> str:
    if not isinstance(value, str) or value == "":
        return "vacío"
    if _has_control(value):
        return "un carácter de control"
    if len(value) > 24:
        return value[:24] + "…"
    return value


def _mark(config: Configuration, status: str, message: str) -> Configuration:
    return Configuration(config.state, config.tape, config.head, status, message)


def _accepted(status: str) -> bool | None:
    if status == "accept":
        return True
    if status == "reject":
        return False
    return None


def _steps_message(limit: int) -> str:
    return f"No terminó: se agotaron los {limit} pasos."


def _cells_message(limit: int) -> str:
    return f"No terminó: la cinta llegó a {limit} celdas."


def _as_list(value: object) -> list | None:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        return None
    return list(value)


def _cap(errors: list[str], limit: int = 8) -> list[str]:
    if len(errors) <= limit:
        return errors
    hidden = len(errors) - limit
    return errors[:limit] + [f"Hay {hidden} errores más del mismo tipo."]
