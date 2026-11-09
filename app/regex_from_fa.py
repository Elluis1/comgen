"""De un AFD a una expresión regular, por eliminación de estados.

Se agrega un origen y un único final, unidos por la cadena vacía. Cada
estado del AFD se saca con la fórmula de la materia: si el lazo es L y
hay α hasta el estado y β hacia afuera, el tramo que queda es α L* β.
Un AFD total se minimiza en una copia, para no arrastrar estados de más.
El autómata de la sesión no se toca.

Un AFN no se convierte: primero hay que determinizarlo. Así no se arma
una expresión enorme a partir de los subconjuntos.
"""

import unicodedata

from app.minimize import MinimizeError, is_total_dfa, minimize_dfa
from app.regex_lang import _compact, pattern_problems
from app.sanitize import is_control_or_invisible
from app.schemas import FiniteAutomaton
from app.validate import prepare_fa, validate_fa

# Por encima de esto la expresión crece demasiado para una notebook chica.
MAX_STATES = 16
# Tamaño del árbol, no de la cadena. Corta antes de que el armado se dispare.
MAX_EXPRESSION = 320
MAX_OPS = 100000

_META = set("*+?|()[]{}\\")
_EPS = ("e",)
_EMPTY = ("z",)
_START = ("start",)
_ACCEPT = ("accept",)


class RegexFromFaError(Exception):
    pass


def fa_to_regex(automaton: FiniteAutomaton) -> str:
    """Devuelve una expresión equivalente. No modifica el autómata de entrada."""
    if len(automaton.states) > MAX_STATES:
        raise RegexFromFaError(
            f"El autómata tiene {len(automaton.states)} estados. "
            f"La expresión se arma hasta {MAX_STATES} para no trabar el equipo."
        )
    # Un espacio se iba en el strip y volvía como épsilon. Hay que decirlo antes.
    _reject_blank_reads(automaton)
    prepared, _notes = prepare_fa(automaton)
    check = validate_fa(prepared)
    if not check.ok:
        raise RegexFromFaError(" ".join(check.errors))
    if _nondeterministic(prepared):
        raise RegexFromFaError(
            "Este autómata no es determinista. Primero hay que determinizarlo."
        )
    if is_total_dfa(prepared):
        try:
            prepared = minimize_dfa(prepared)
        except MinimizeError as exc:
            raise RegexFromFaError(str(exc)) from exc
    try:
        return _eliminate(prepared)
    except RecursionError as exc:
        raise RegexFromFaError("La expresión queda demasiado anidada y no la armo.") from exc


def _nondeterministic(automaton: FiniteAutomaton) -> bool:
    seen: set[tuple[str, str]] = set()
    for transition in automaton.transitions:
        if transition.read == "":
            return True
        key = (transition.from_state, transition.read)
        if key in seen:
            return True
        seen.add(key)
    return False


def _eliminate(automaton: FiniteAutomaton) -> str:
    initial = next(state.id for state in automaton.states if state.initial)
    finals = {state.id for state in automaton.states if state.final}
    if not finals:
        raise RegexFromFaError(
            "El autómata no acepta ninguna cadena, así que no hay expresión regular."
        )

    forward: dict[str, set[str]] = {state.id: set() for state in automaton.states}
    backward: dict[str, set[str]] = {state.id: set() for state in automaton.states}
    for transition in automaton.transitions:
        if not transition.read:
            continue
        forward[transition.from_state].add(transition.to)
        backward[transition.to].add(transition.from_state)
    reachable = _walk(initial, forward)
    to_final: set[str] = set()
    for final in finals:
        to_final |= _walk(final, backward)
    useful = reachable & to_final
    if not useful:
        raise RegexFromFaError(
            "El autómata no acepta ninguna cadena, así que no hay expresión regular."
        )

    _reject_unwritable(automaton, useful)
    algebra = _Algebra()
    edges: dict[tuple, tuple] = {}
    algebra.add(edges, _START, initial, _EPS)
    for final in finals:
        if final in useful:
            algebra.add(edges, final, _ACCEPT, _EPS)
    for transition in automaton.transitions:
        if transition.from_state in useful and transition.to in useful and transition.read:
            algebra.add(
                edges,
                transition.from_state,
                transition.to,
                algebra.sym(transition.read),
            )

    remaining = set(useful)
    while remaining:
        state_id = min(remaining, key=lambda sid: _rank(sid, edges, initial, finals))
        remaining.remove(state_id)
        _drop_state(state_id, edges, algebra)

    result = edges.get((_START, _ACCEPT), _EMPTY)
    if result == _EMPTY:
        raise RegexFromFaError(
            "El autómata no acepta ninguna cadena, así que no hay expresión regular."
        )
    if result == _EPS:
        raise RegexFromFaError(
            "El lenguaje es solo la cadena vacía y este dialecto no puede escribirla sola."
        )
    pattern = algebra.emit(result)
    if not pattern:
        raise RegexFromFaError("No pude escribir la expresión.")
    problems = pattern_problems(pattern)
    if problems:
        raise RegexFromFaError(problems[0])
    # El compilador normaliza la expresión entera. 가 o «e» + acento
    # dejarían de ser dos símbolos y el lenguaje ya no sería el del AFD.
    if _joins_another_character(pattern):
        raise RegexFromFaError(
            "Esos símbolos, uno al lado del otro, se juntan en otro carácter "
            "y la expresión diría otro lenguaje."
        )
    return pattern


def _walk(start: str, graph: dict[str, set[str]]) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        current = stack.pop()
        for nxt in graph.get(current, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _rank(state_id: str, edges: dict, initial: str, finals: set[str]) -> tuple:
    incoming = 0
    outgoing = 0
    for src, dst in edges:
        if src == dst:
            continue
        if dst == state_id and src != _START:
            incoming += 1
        if src == state_id and dst != _ACCEPT:
            outgoing += 1
    if state_id == initial:
        kind = 2
    elif state_id in finals:
        kind = 1
    else:
        kind = 0
    return (kind, incoming * outgoing, state_id)


def _drop_state(state_id: str, edges: dict, algebra: "_Algebra") -> None:
    loop = edges.pop((state_id, state_id), None)
    starred = _EPS if loop is None else algebra.star(loop)
    incoming: list[tuple] = []
    outgoing: list[tuple] = []
    for (src, dst), label in list(edges.items()):
        if dst == state_id and src != state_id:
            incoming.append((src, label))
        elif src == state_id and dst != state_id:
            outgoing.append((dst, label))
    for src, _label in incoming:
        edges.pop((src, state_id), None)
    for dst, _label in outgoing:
        edges.pop((state_id, dst), None)
    for src, alpha in incoming:
        for dst, beta in outgoing:
            algebra.add(edges, src, dst, algebra.concat((alpha, starred, beta)))


def _joins_another_character(pattern: str) -> bool:
    apart = "".join(unicodedata.normalize("NFC", char) for char in pattern)
    return unicodedata.normalize("NFC", pattern) != apart


def _reject_blank_reads(automaton: FiniteAutomaton) -> None:
    symbols = list(automaton.alphabet)
    symbols.extend(transition.read for transition in automaton.transitions)
    for symbol in symbols:
        if symbol and symbol.isspace():
            raise RegexFromFaError(
                "Hay un espacio en una transición y no entra en la expresión: "
                "este dialecto no tiene escapes."
            )


def _reject_unwritable(automaton: FiniteAutomaton, useful: set[str]) -> None:
    for transition in automaton.transitions:
        if transition.from_state not in useful or transition.to not in useful:
            continue
        symbol = transition.read
        if not symbol:
            continue
        if symbol.isspace():
            raise RegexFromFaError(
                "Hay un espacio en una transición y no entra en la expresión: "
                "este dialecto no tiene escapes."
            )
        if is_control_or_invisible(symbol):
            raise RegexFromFaError(
                "Hay un carácter de control en una transición y no entra en la expresión."
            )
        # El compilador pliega ∗ y ⋆ a «*» y borra espacios. Si el símbolo
        # cambia al compactar, la expresión diría otro lenguaje.
        if symbol in _META or _compact(symbol) != symbol:
            raise RegexFromFaError(
                f"El símbolo «{symbol}» no entra en la expresión: este dialecto no tiene escapes."
            )


def _size(node: tuple, memo: dict) -> int:
    if node in memo:
        return memo[node]
    stack = [(node, False)]
    while stack:
        current, seen = stack.pop()
        if current in memo:
            continue
        if not seen:
            stack.append((current, True))
            tag = current[0]
            if tag in {"|", "."}:
                for child in current[1]:
                    if child not in memo:
                        stack.append((child, False))
            elif tag in {"*", "+", "?"}:
                if current[1] not in memo:
                    stack.append((current[1], False))
            continue
        tag = current[0]
        if tag in {"z", "e", "s"}:
            memo[current] = 1
        elif tag in {"*", "+", "?"}:
            memo[current] = 1 + memo[current[1]]
        else:
            memo[current] = 1 + sum(memo[child] for child in current[1])
    return memo[node]


class _Algebra:
    def __init__(self) -> None:
        self.memo: dict = {}
        self.ops = 0
        self.depth = 0

    def sym(self, char: str) -> tuple:
        return ("s", char)

    def add(self, edges: dict, src, dst, label: tuple) -> None:
        key = (src, dst)
        if key in edges:
            edges[key] = self.union((edges[key], label))
        else:
            edges[key] = label

    def union(self, nodes) -> tuple:
        self._tick()
        self._enter()
        try:
            return self._union(nodes)
        finally:
            self._leave()

    def concat(self, nodes) -> tuple:
        self._tick()
        self._enter()
        try:
            return self._concat(nodes)
        finally:
            self._leave()

    def star(self, node: tuple) -> tuple:
        self._tick()
        self._enter()
        try:
            return self._star(node)
        finally:
            self._leave()

    def plus(self, node: tuple) -> tuple:
        self._tick()
        self._enter()
        try:
            return self._plus(node)
        finally:
            self._leave()

    def optional(self, node: tuple) -> tuple:
        self._tick()
        self._enter()
        try:
            return self._optional(node)
        finally:
            self._leave()

    def emit(self, node: tuple) -> str:
        return self._emit(node, 0)

    def nullable(self, node: tuple) -> bool:
        tag = node[0]
        if tag in {"e", "*", "?"}:
            return True
        if tag in {"z", "s"}:
            return False
        if tag == "+":
            return self.nullable(node[1])
        if tag == "|":
            return any(self.nullable(child) for child in node[1])
        if tag == ".":
            return all(self.nullable(child) for child in node[1])
        return False

    def _union(self, nodes) -> tuple:
        parts: list[tuple] = []
        for node in nodes:
            if node == _EMPTY:
                continue
            if node[0] == "|":
                parts.extend(node[1])
            else:
                parts.append(node)
        unique: list[tuple] = []
        seen: set[tuple] = set()
        for part in parts:
            if part not in seen:
                seen.add(part)
                unique.append(part)
        if not unique:
            return _EMPTY
        has_eps = _EPS in unique
        others = [part for part in unique if part != _EPS]
        if has_eps:
            if not others:
                return _EPS
            if any(self.nullable(part) for part in others):
                return self.union(others)
            rest = others[0] if len(others) == 1 else self.union(others)
            return self.optional(rest)
        if len(unique) == 1:
            return unique[0]
        absorbed = self._absorb(unique)
        if len(absorbed) == 1:
            return absorbed[0]
        factored = self._factor(absorbed)
        if factored is not None:
            return factored
        ordered = tuple(sorted(absorbed))
        return self._limit(("|", ordered))

    def _concat(self, nodes) -> tuple:
        flat: list[tuple] = []
        for node in nodes:
            if node == _EMPTY:
                return _EMPTY
            if node == _EPS:
                continue
            if node[0] == ".":
                flat.extend(node[1])
            else:
                flat.append(node)
        if not flat:
            return _EPS
        merged = self._merge_concat(flat)
        if len(merged) == 1:
            return merged[0]
        return self._limit((".", tuple(merged)))

    def _star(self, node: tuple) -> tuple:
        if node == _EMPTY or node == _EPS:
            return _EPS
        tag = node[0]
        if tag == "*":
            return node
        if tag in {"+", "?"}:
            return self.star(node[1])
        if tag == "|":
            bodies: list[tuple] = []
            changed = False
            for child in node[1]:
                if child == _EPS:
                    changed = True
                    continue
                if child[0] in {"*", "+", "?"}:
                    bodies.append(child[1])
                    changed = True
                else:
                    bodies.append(child)
            if changed:
                return self.star(self.union(bodies))
        return self._limit(("*", node))

    def _plus(self, node: tuple) -> tuple:
        if node == _EMPTY:
            return _EMPTY
        if node == _EPS or self.nullable(node) or node[0] == "*":
            return self.star(node)
        if node[0] == "+":
            return node
        return self._limit(("+", node))

    def _optional(self, node: tuple) -> tuple:
        if node == _EMPTY or node == _EPS:
            return _EPS
        if node[0] == "*":
            return node
        if node[0] == "?":
            return node
        if node[0] == "+":
            return self.star(node[1])
        if self.nullable(node):
            return node
        return self._limit(("?", node))

    def _merge_concat(self, parts: list[tuple]) -> list[tuple]:
        merged: list[tuple] = []
        for part in parts:
            if not merged:
                merged.append(part)
                continue
            folded = self._fold_pair(merged[-1], part)
            if folded is None:
                merged.append(part)
            else:
                merged[-1] = folded
        return merged

    def _fold_pair(self, left: tuple, right: tuple):
        left_k = _kleene(left)
        right_k = _kleene(right)
        if left_k and right_k and left_k[1] == right_k[1]:
            if left_k[0] == "+" and right_k[0] == "+":
                return None
            if left_k[0] == "*" and right_k[0] == "*":
                return left
            return self.plus(left_k[1])
        if right_k and right_k[0] == "*" and right_k[1] == left:
            return self.star(left) if self.nullable(left) else self.plus(left)
        if left_k and left_k[0] == "*" and left_k[1] == right:
            return self.star(right) if self.nullable(right) else self.plus(right)
        return None

    def _absorb(self, parts: list[tuple]) -> list[tuple]:
        covered: set[tuple] = set()
        for outer in parts:
            for inner in parts:
                if outer == inner:
                    continue
                if _covers(outer, inner):
                    covered.add(inner)
        kept = [part for part in parts if part not in covered]
        return kept or parts

    def _factor(self, parts: list[tuple]):
        right = self._peel(parts, from_right=True)
        if right is not None:
            return right
        return self._peel(parts, from_right=False)

    def _peel(self, parts: list[tuple], from_right: bool):
        lists = [list(_seq_of(part)) for part in parts]
        peeled: list[tuple] = []
        while all(lists):
            heads = [lst[-1] if from_right else lst[0] for lst in lists]
            if any(head != heads[0] for head in heads):
                break
            peeled.append(heads[0])
            for lst in lists:
                lst.pop() if from_right else lst.pop(0)
            if any(not lst for lst in lists):
                break
        if not peeled:
            return None
        if from_right:
            peeled.reverse()
            side = self._seq(peeled)
            other = [self._seq(lst) for lst in lists]
            return self.concat((self.union(other), side))
        side = self._seq(peeled)
        other = [self._seq(lst) for lst in lists]
        return self.concat((side, self.union(other)))

    def _seq(self, items: list[tuple]) -> tuple:
        if not items:
            return _EPS
        if len(items) == 1:
            return items[0]
        return self.concat(items)

    def _emit(self, node: tuple, min_prec: int) -> str:
        tag = node[0]
        if tag == "s":
            return node[1]
        if tag == "*":
            text = f"{self._emit(node[1], 3)}*"
            prec = 3
        elif tag == "+":
            text = f"{self._emit(node[1], 3)}+"
            prec = 3
        elif tag == "?":
            text = f"{self._emit(node[1], 3)}?"
            prec = 3
        elif tag == ".":
            text = "".join(self._emit(child, 2) for child in node[1])
            prec = 2
        elif tag == "|":
            text = "|".join(self._emit(child, 1) for child in node[1])
            prec = 1
        else:
            raise RegexFromFaError("No pude escribir la expresión.")
        if prec < min_prec:
            return f"({text})"
        return text

    def _limit(self, node: tuple) -> tuple:
        if _size(node, self.memo) > MAX_EXPRESSION:
            raise RegexFromFaError(
                "La expresión queda demasiado grande y no la armo, para no trabar el equipo."
            )
        return node

    def _tick(self) -> None:
        self.ops += 1
        if self.ops > MAX_OPS:
            raise RegexFromFaError(
                "La expresión queda demasiado grande y no la armo, para no trabar el equipo."
            )

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > 200:
            raise RegexFromFaError("La expresión queda demasiado anidada y no la armo.")

    def _leave(self) -> None:
        self.depth -= 1


def _kleene(node: tuple):
    if node[0] in {"*", "+"}:
        return node[0], node[1]
    return None


def _covers(outer: tuple, inner: tuple) -> bool:
    tag = outer[0]
    if tag == "*":
        body = outer[1]
        if inner == body:
            return True
        return inner[0] in {"*", "+", "?"} and inner[1] == body
    if tag == "+":
        body = outer[1]
        if inner == body:
            return True
        return inner[0] == "+" and inner[1] == body
    if tag == "?":
        return inner == outer[1]
    return False


def _seq_of(node: tuple) -> tuple:
    if node[0] == ".":
        return node[1]
    return (node,)
