"""Minimización de un AFD total por partición, la de la materia.

La partición es la misma que la del refinamiento clásico (aceptadores contra
el resto, y después se separa quien no llega al mismo bloque). El recorrido
es el de Hopcroft: solo se vuelve a mirar el bloque que se partió, así un
producto de unos miles de estados no deja colgada la notebook.
"""

from app.schemas import FiniteAutomaton, State, Transition

# Por encima de esto la tabla ya no entra en una notebook modesta.
# El producto de las familias corta en 4096, así que este tope queda por encima.
MAX_MINIMIZE_STATES = 8192


class MinimizeError(Exception):
    pass


def is_total_dfa(automaton: FiniteAutomaton) -> bool:
    if not automaton.deterministic or not automaton.states or not automaton.alphabet:
        return False
    initials = [state.id for state in automaton.states if state.initial]
    if len(initials) != 1:
        return False
    seen: dict[tuple[str, str], str] = {}
    for transition in automaton.transitions:
        if transition.read == "":
            return False
        key = (transition.from_state, transition.read)
        if key in seen:
            return False
        seen[key] = transition.to
    for state in automaton.states:
        for symbol in automaton.alphabet:
            if (state.id, symbol) not in seen:
                return False
    return True


def minimize_dfa(automaton: FiniteAutomaton) -> FiniteAutomaton:
    """Devuelve un AFD mínimo. Si no es total, lo deja como está."""
    if len(automaton.states) > MAX_MINIMIZE_STATES:
        raise MinimizeError(
            f"El autómata tiene {len(automaton.states)} estados. "
            f"La minimización se corta en {MAX_MINIMIZE_STATES} para no trabar el equipo. "
            "Partí el pedido en autómatas más chicos."
        )
    if not is_total_dfa(automaton):
        return automaton

    alphabet = list(automaton.alphabet)
    delta = {
        (transition.from_state, transition.read): transition.to
        for transition in automaton.transitions
    }
    initial = next(state.id for state in automaton.states if state.initial)
    finals = {state.id for state in automaton.states if state.final}
    reachable = _reachable(initial, alphabet, delta)
    states = [state.id for state in automaton.states if state.id in reachable]

    groups = _partition(states, finals, alphabet, delta)
    if len(states) == len(automaton.states) and all(len(group) == 1 for group in groups):
        return automaton
    return _rebuild(automaton, groups, delta, alphabet, initial, finals)


def _partition(
    states: list[str],
    finals: set[str],
    alphabet: list[str],
    delta: dict[tuple[str, str], str],
) -> list[set[str]]:
    accept = {state for state in states if state in finals}
    reject = {state for state in states if state not in accept}
    blocks = [group for group in (accept, reject) if group]
    block_of: dict[str, int] = {}
    for index, block in enumerate(blocks):
        for state in block:
            block_of[state] = index

    incoming: dict[tuple[str, str], list[str]] = {}
    for state in states:
        for symbol in alphabet:
            target = delta[(state, symbol)]
            incoming.setdefault((symbol, target), []).append(state)

    # Cada índice está a lo sumo una vez en la cola. Al partir un bloque,
    # el índice viejo se queda con la parte grande y el nuevo entra si toca.
    queued = [False] * len(blocks)
    work: list[int] = []

    def enqueue(index: int) -> None:
        if not queued[index]:
            queued[index] = True
            work.append(index)

    if len(blocks) == 2:
        smaller = 0 if len(blocks[0]) <= len(blocks[1]) else 1
        enqueue(smaller)

    while work:
        splitter_index = work.pop()
        queued[splitter_index] = False
        splitter = list(blocks[splitter_index])
        for symbol in alphabet:
            touched: dict[int, list[str]] = {}
            for target in splitter:
                for source in incoming.get((symbol, target), ()):
                    touched.setdefault(block_of[source], []).append(source)
            for block_index, sources in touched.items():
                block = blocks[block_index]
                move = set(sources)
                if len(move) == len(block):
                    continue
                stay = block - move
                # La parte chica es la que hay que volver a usar como splitter.
                if len(move) <= len(stay):
                    small, large = move, stay
                else:
                    small, large = stay, move
                blocks[block_index] = large
                new_index = len(blocks)
                blocks.append(small)
                queued.append(False)
                for state in small:
                    block_of[state] = new_index
                enqueue(new_index)
    return blocks


def _reachable(initial: str, alphabet: list[str], delta: dict[tuple[str, str], str]) -> set[str]:
    seen: set[str] = set()
    stack = [initial]
    while stack:
        state = stack.pop()
        if state in seen:
            continue
        seen.add(state)
        for symbol in alphabet:
            stack.append(delta[(state, symbol)])
    return seen


def _index_of(groups: list[set[str]]) -> dict[str, int]:
    index_of: dict[str, int] = {}
    for index, group in enumerate(groups):
        for state in group:
            index_of[state] = index
    return index_of


def _rebuild(
    automaton: FiniteAutomaton,
    groups: list[set[str]],
    delta: dict[tuple[str, str], str],
    alphabet: list[str],
    initial: str,
    finals: set[str],
) -> FiniteAutomaton:
    index_of = _index_of(groups)
    start = index_of[initial]
    order: list[int] = []
    seen: set[int] = set()
    pending = [start]
    while pending:
        current = pending.pop(0)
        if current in seen:
            continue
        seen.add(current)
        order.append(current)
        representative = min(groups[current])
        for symbol in alphabet:
            target = index_of[delta[(representative, symbol)]]
            if target not in seen:
                pending.append(target)

    names = {group_index: f"q{position}" for position, group_index in enumerate(order)}
    states: list[State] = []
    transitions: list[Transition] = []
    for group_index in order:
        representative = min(groups[group_index])
        states.append(
            State(
                id=names[group_index],
                initial=group_index == start,
                final=representative in finals,
            )
        )
        for symbol in alphabet:
            target = index_of[delta[(representative, symbol)]]
            transitions.append(
                Transition(from_state=names[group_index], to=names[target], read=symbol)
            )
    return FiniteAutomaton(
        deterministic=True,
        alphabet=alphabet,
        states=states,
        transitions=transitions,
        description=automaton.description,
    )
