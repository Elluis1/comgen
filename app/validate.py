import unicodedata
from dataclasses import dataclass, field

from app.sanitize import is_epsilon_symbol
from app.schemas import FiniteAutomaton, State, Transition


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _state_name(value: str) -> str:
    # El mismo pliegue que un símbolo: «e» + acento es el mismo nombre.
    return unicodedata.normalize("NFC", value.strip())


def normalize_symbol(symbol: str) -> str:
    # Un espacio solo no es épsilon. Si se borra con strip, la flecha cambia de lenguaje.
    if len(symbol) == 1 and symbol.isspace():
        return symbol
    # NFC: e + acento combinante es un solo símbolo, el que el enunciado nombra.
    cleaned = unicodedata.normalize("NFC", symbol.strip())
    if cleaned == "" or is_epsilon_symbol(cleaned):
        return ""
    return cleaned


def prepare_fa(automaton: FiniteAutomaton) -> tuple[FiniteAutomaton, list[str]]:
    notes: list[str] = []
    alphabet: list[str] = []
    for symbol in automaton.alphabet:
        cleaned = normalize_symbol(symbol)
        if cleaned and cleaned not in alphabet:
            alphabet.append(cleaned)

    states = [
        State(id=_state_name(state.id), initial=state.initial, final=state.final)
        for state in automaton.states
    ]

    transitions: list[Transition] = []
    seen: set[tuple[str, str, str]] = set()
    dropped = 0
    for transition in automaton.transitions:
        item = Transition(
            from_state=_state_name(transition.from_state),
            to=_state_name(transition.to),
            read=normalize_symbol(transition.read),
        )
        key = (item.from_state, item.to, item.read)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        transitions.append(item)
    if dropped:
        notes.append(f"Quité {dropped} transiciones repetidas.")

    prepared = FiniteAutomaton(
        deterministic=automaton.deterministic,
        alphabet=alphabet,
        states=states,
        transitions=transitions,
        description=automaton.description.strip(),
    )
    return prepared, notes


def validate_fa(automaton: FiniteAutomaton) -> CheckResult:
    result = CheckResult()
    if not automaton.states:
        result.errors.append("El autómata no tiene estados.")
        return result

    ids = [state.id for state in automaton.states]
    if any(not state_id for state_id in ids):
        result.errors.append("Hay un estado sin nombre.")
    if len(ids) != len(set(ids)):
        result.errors.append("Hay dos estados con el mismo nombre.")

    if not automaton.alphabet:
        result.errors.append("Falta el alfabeto. Cada símbolo tiene que ser un solo carácter.")
    for symbol in automaton.alphabet:
        if len(symbol) != 1:
            result.errors.append(f"«{symbol}» no puede estar en el alfabeto: tiene que ser un solo carácter.")

    known = set(ids)
    for transition in automaton.transitions:
        if transition.from_state not in known or transition.to not in known:
            result.errors.append(
                f"La transición {transition.from_state} → {transition.to} usa un estado que no existe."
            )
            continue
        if transition.read == "":
            if automaton.deterministic:
                result.errors.append(
                    f"Un AFD no puede tener una transición épsilon de {transition.from_state} a {transition.to}."
                )
            continue
        if len(transition.read) != 1:
            result.errors.append(
                f"El símbolo «{transition.read}» de {transition.from_state} a {transition.to} tiene que ser un solo carácter."
            )
        elif transition.read not in automaton.alphabet:
            result.errors.append(
                f"«{transition.read}» no está en el alfabeto y aparece en {transition.from_state} → {transition.to}."
            )

    initials = [state.id for state in automaton.states if state.initial]
    if len(initials) != 1:
        result.errors.append("Tiene que haber exactamente un estado inicial.")

    if automaton.deterministic and not result.errors:
        grouped: dict[tuple[str, str], int] = {}
        for transition in automaton.transitions:
            if transition.read == "":
                continue
            key = (transition.from_state, transition.read)
            grouped[key] = grouped.get(key, 0) + 1
        for (state_id, symbol), count in grouped.items():
            if count > 1:
                result.errors.append(
                    f"En {state_id} el símbolo {symbol} sale por {count} transiciones. Un AFD solo puede tener una."
                )

    if not any(state.final for state in automaton.states):
        result.errors.append(
            "No hay estados finales: así el autómata rechaza todas las cadenas."
        )

    if result.errors:
        return result

    if automaton.deterministic:
        present = {(transition.from_state, transition.read) for transition in automaton.transitions}
        missing: list[str] = []
        for state in automaton.states:
            for symbol in automaton.alphabet:
                if (state.id, symbol) not in present:
                    missing.append(f"En {state.id} falta la transición con {symbol}.")
        result.warnings.extend(_cap(missing))

    used = {transition.read for transition in automaton.transitions if transition.read}
    unused = [f"El símbolo {symbol} no aparece en ninguna transición." for symbol in automaton.alphabet if symbol not in used]
    result.warnings.extend(_cap(unused))

    if len(initials) == 1:
        reached = _reachable(automaton, initials[0])
        unreachable = [state.id for state in automaton.states if state.id not in reached]
        if unreachable:
            result.warnings.append("Hay estados inalcanzables: " + ", ".join(unreachable) + ".")

    return result


def _reachable(automaton: FiniteAutomaton, start: str) -> set[str]:
    # Un índice por estado. Si cada estado recorre todas las flechas, un AFD
    # de unos miles de estados tarda medio segundo, y esto corre en cada
    # respuesta y en cada descarga.
    outgoing: dict[str, list[str]] = {}
    for transition in automaton.transitions:
        outgoing.setdefault(transition.from_state, []).append(transition.to)
    seen: set[str] = set()
    stack = [start]
    while stack:
        state_id = stack.pop()
        if state_id in seen:
            continue
        seen.add(state_id)
        stack.extend(outgoing.get(state_id, ()))
    return seen


def _cap(messages: list[str], limit: int = 8) -> list[str]:
    if len(messages) <= limit:
        return messages
    hidden = len(messages) - limit
    return messages[:limit] + [f"Hay {hidden} advertencias más del mismo tipo."]
