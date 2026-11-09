"""De un AFN con épsilon a un AFD, por subconjuntos.

El estado inicial del AFD es la clausura épsilon del inicial. Con un símbolo
se avanza y se vuelve a cerrar por épsilon. Solo entran los subconjuntos
alcanzables. El conjunto vacío no se agrega: la flecha que falta rechaza,
y el pozo sigue entrando recién en la descarga del .jff.

Si el autómata ya es determinista, no se renombran los estados.
"""

from collections import deque

from app.schemas import FiniteAutomaton, State, Transition
from app.validate import prepare_fa, validate_fa

# El mismo tope que el compilador de expresiones: más subconjuntos no entran
# en la tabla de una notebook modesta.
MAX_SUBSETS = 512


class DeterminizeError(Exception):
    pass


class Determinized:
    def __init__(self, automaton: FiniteAutomaton, already: bool, notes: list[str]) -> None:
        self.automaton = automaton
        self.already = already
        self.notes = notes


def nfa_to_dfa(automaton: FiniteAutomaton) -> Determinized:
    """Devuelve un AFD equivalente. No modifica el autómata de entrada."""
    prepared, notes = prepare_fa(automaton)
    as_nfa = prepared.model_copy(update={"deterministic": False})
    check = validate_fa(as_nfa)
    if not check.ok:
        detail = " ".join(check.errors)
        raise DeterminizeError(f"No pude determinizar el autómata. {detail}")

    if _is_dfa(prepared):
        dfa = prepared.model_copy(update={"deterministic": True})
        return Determinized(dfa, already=True, notes=notes)

    alphabet = list(prepared.alphabet)
    outgoing: dict[tuple[str, str], list[str]] = {}
    for transition in prepared.transitions:
        outgoing.setdefault((transition.from_state, transition.read), []).append(transition.to)

    def closure(seeds: frozenset[str]) -> frozenset[str]:
        seen = set(seeds)
        stack = list(seeds)
        while stack:
            state_id = stack.pop()
            for nxt in outgoing.get((state_id, ""), []):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return frozenset(seen)

    order = [state.id for state in prepared.states]
    rank = {state_id: index for index, state_id in enumerate(order)}
    finals = {state.id for state in prepared.states if state.final}
    initial = next(state.id for state in prepared.states if state.initial)

    start = closure(frozenset({initial}))
    delta: dict[frozenset[str], dict[str, frozenset[str]]] = {}
    seen: set[frozenset[str]] = {start}
    pending: deque[frozenset[str]] = deque([start])
    while pending:
        current = pending.popleft()
        moves: dict[str, frozenset[str]] = {}
        for symbol in alphabet:
            arrived: set[str] = set()
            for state_id in current:
                arrived.update(outgoing.get((state_id, symbol), []))
            if not arrived:
                continue
            target = closure(frozenset(arrived))
            if not target:
                continue
            moves[symbol] = target
            if target not in seen:
                if len(seen) >= MAX_SUBSETS:
                    raise DeterminizeError(
                        f"El AFN genera más de {MAX_SUBSETS} subconjuntos. "
                        "No lo convierto en AFD para no trabar el equipo. "
                        "Achicá el AFN o partilo."
                    )
                seen.add(target)
                pending.append(target)
        delta[current] = moves

    names = _names(delta, rank)
    states = [
        State(
            id=names[subset],
            initial=subset == start,
            final=bool(subset & finals),
        )
        for subset in delta
    ]
    transitions = [
        Transition(from_state=names[subset], to=names[target], read=symbol)
        for subset, moves in delta.items()
        for symbol, target in moves.items()
    ]
    dfa = FiniteAutomaton(
        deterministic=True,
        alphabet=alphabet,
        states=states,
        transitions=transitions,
        description=_description(prepared.description),
    )
    return Determinized(dfa, already=False, notes=notes)


def _is_dfa(automaton: FiniteAutomaton) -> bool:
    seen: set[tuple[str, str]] = set()
    for transition in automaton.transitions:
        if transition.read == "":
            return False
        key = (transition.from_state, transition.read)
        if key in seen:
            return False
        seen.add(key)
    initials = [state.id for state in automaton.states if state.initial]
    return len(initials) == 1


def _names(delta: dict[frozenset[str], dict[str, frozenset[str]]], rank: dict[str, int]) -> dict[frozenset[str], str]:
    used: set[str] = set()
    names: dict[frozenset[str], str] = {}
    for subset in delta:
        members = sorted(subset, key=lambda state_id: rank.get(state_id, 0))
        base = "{" + ",".join(members) + "}"
        name = base
        suffix = 2
        while name in used:
            name = f"{base}#{suffix}"
            suffix += 1
        used.add(name)
        names[subset] = name
    return names


def _description(description: str) -> str:
    base = description.strip() or "Autómata finito"
    if base.casefold().endswith("(determinizado)"):
        return base
    return f"{base} (determinizado)"
