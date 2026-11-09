"""Familias de autómatas que se arman en código, sin pedirle las flechas al modelo.

También entra la posición: el k-ésimo símbolo desde el final o desde el principio
(último, penúltimo, antepenúltimo, «el tercero desde el final», «el segundo símbolo»).
Desde el final el AFD recuerda una ventana de k símbolos y, minimizado, queda en 2^k estados.

Y la secuencia: bloques pegados, cada uno una repetición fija o una estrella.
«infinitos 1, 3 0, infinitos 1, un 0» es 1*0001*0. El número es la cantidad
cuando no está en el alfabeto («3» sobre {0, 1}) o cuando está escrito como
palabra («tres ceros»). Si «3» también es un símbolo, «3 0» se explica y no se adivina.

Números. Se leen de izquierda a derecha, el dígito más significativo primero.
El estado es el resto acumulado: δ(r, d) = (base · r + d) módulo n.
La cadena vacía vale 0, porque no se leyó ningún dígito: se acepta solo cuando
el resto pedido es 0. Los ceros a la izquierda se permiten y no cambian el
valor: 0, 00 y 000 son el cero. Así, 0101 en base 2 es 5, no «un número mal formado».
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from app.minimize import MinimizeError, is_total_dfa, minimize_dfa
from app.sanitize import (
    ambiguous_repetition_message,
    repetition_reading,
    spanish_count,
    strip_invisibles,
    strip_marks_before_question,
    symbol_name,
)
from app.schemas import FiniteAutomaton, State, Transition
from app.simulate import Simulator
from app.validate import validate_fa

MAX_MODULUS = 128
MAX_WORD = 48
MAX_PRODUCT = 4096
# Desde el final hay un estado por cada subconjunto de la ventana: 2^k.
# 2^12 = 4096, el mismo tope que el producto. 2^13 = 8192 ya traba la notebook.
MAX_FROM_END = 12
# Desde el principio la cadena de estados es lineal. El tope evita un pedido absurdo.
MAX_FROM_START = 256
# Un bloque fijo de más de 32 símbolos, o más de 64 en toda la secuencia, no entra en la notebook.
MAX_SEQUENCE_REPEAT = 32
MAX_SEQUENCE_BLOCKS = 24
MAX_SEQUENCE_SYMBOLS = 64
# El control prueba una muestra, no todos los enteros hasta base·módulo·3.
# Pasado esto se corta: formatear el resto no cambia el resultado y, en base 36
# con módulo 128, son más de trece mil números.
MAX_CONTROL_WORDS = 1500
_ACCENTS = str.maketrans("áéíóúüñ", "aeiouun")

_CONVENTION = (
    "La cadena vacía vale 0, porque no se leyó ningún dígito: se acepta solo cuando el resto pedido es 0. "
    "Los ceros a la izquierda se permiten y no cambian el valor: 0, 00 y 000 son el cero."
)

_PREFIX = re.compile(
    r"^(un|una|el|la|los|las|afd|afn|automata|finito|finitos|que|acepte|acepten|"
    r"acepta|aceptan|reconozca|reconozcan|cadenas|cadena|palabras|palabra|lenguaje|"
    r"sobre|solo|solamente|exactamente|aquellas|aquellos|todas|todos|de|del|"
    r"me|dame|quiero|necesito|armame|arma|genera|generame|hacer|haced|por\s+favor|"
    r"numeros|numero|enteros|entero|con)\s+"
)

_STOP = {
    "en", "de", "la", "el", "los", "las", "un", "una", "que", "por", "con", "se", "su",
    "al", "del", "es", "son", "y", "o", "e", "u", "no", "par", "impar", "pares", "impares",
    "base", "modulo", "mod", "subcadena", "cadena", "cadenas", "palabra", "numero",
    "numeros", "cantidad", "longitud", "largo", "resto", "divisible", "divisibles",
    "multiplo", "multiplos", "binario", "binarios", "binaria", "binarias", "decimal",
    "decimales",     "sobre", "acepte", "acepta", "finito", "automata",
    "simbolo", "simbolos", "caracter", "caracteres", "letra", "letras",
    "digito", "digitos", "posicion", "ultimo", "penultimo", "antepenultimo",
    "final", "principio", "inicio", "esimo", "esima",
}


class FamilyError(Exception):
    pass


class _Invalid(FamilyError):
    pass


@dataclass(frozen=True)
class ValueSpec:
    base: int | None
    modulus: int
    remainder: int


@dataclass(frozen=True)
class CountSpec:
    symbol: str
    modulus: int
    remainder: int


@dataclass(frozen=True)
class LengthSpec:
    modulus: int
    remainder: int


@dataclass(frozen=True)
class AffixSpec:
    mode: str
    word: str


@dataclass(frozen=True)
class PositionSpec:
    """El símbolo k (desde 1) contado desde el final o desde el principio es `symbol`."""

    k: int
    symbol: str
    origin: str


@dataclass(frozen=True)
class BlockSpec:
    """Un símbolo repetido: exacto n veces, cero o más (star) o uno o más (plus)."""

    symbol: str
    kind: str
    count: int


@dataclass(frozen=True)
class SequenceSpec:
    """Concatenación de bloques. El lenguaje es exactamente esa secuencia, sin resto."""

    blocks: tuple[BlockSpec, ...]


@dataclass(frozen=True)
class NotSpec:
    inner: object


@dataclass(frozen=True)
class AndSpec:
    parts: tuple


@dataclass(frozen=True)
class OrSpec:
    parts: tuple


Spec = (
    ValueSpec
    | CountSpec
    | LengthSpec
    | AffixSpec
    | PositionSpec
    | SequenceSpec
    | NotSpec
    | AndSpec
    | OrSpec
)


@dataclass(frozen=True)
class _Request:
    spec: Spec
    explicit: tuple[str, ...] | None
    text: str


def recognize_family(text: str):
    """Arma el AFD si el enunciado es de una familia conocida. Si no, devuelve None."""
    from app.interpret import Interpretation

    if _regexish(text):
        return None
    normalized = _normalize(text)
    if not normalized:
        return None
    try:
        request = _parse_request(normalized)
        if request is None:
            return None
        return _build(request)
    except FamilyError as exc:
        return Interpretation(explanation=str(exc), errors=[str(exc)])


def interpretation_from_spec(draft):
    """Construye el AFD a partir del JSON chico de parámetros que devuelve el modelo."""
    from app.interpret import Interpretation

    family = _normalize(draft.family)
    known = {
        "divisible": "divisible",
        "divisibilidad": "divisible",
        "multiplo": "divisible",
        "remainder": "remainder",
        "resto": "remainder",
        "count": "count",
        "cuenta": "count",
        "cantidad": "count",
        "length": "length",
        "longitud": "length",
        "largo": "length",
        "ends": "ends",
        "termina": "ends",
        "sufijo": "ends",
        "starts": "starts",
        "empieza": "starts",
        "comienza": "starts",
        "prefijo": "starts",
        "contains": "contains",
        "contiene": "contains",
        "subcadena": "contains",
        "secuencia": "sequence",
        "bloques": "sequence",
        "sequence": "sequence",
        "patron": "sequence",
    }
    kind = known.get(family)
    if kind is None:
        raise FamilyError(
            "No reconozco la familia. Usá divisible, resto, cuenta, longitud, termina, empieza, contiene o secuencia."
        )
    alphabet = _explicit_symbols(draft.alphabet)
    spec = _spec_from_fields(kind, draft)
    request = _Request(spec=spec, explicit=alphabet, text=_normalize(draft.description))
    result = _build(request)
    if result.automaton is None:
        return result
    result.samples_accept = list(draft.accept)
    result.samples_reject = list(draft.reject)
    return result


def _spec_from_fields(kind: str, draft) -> Spec:
    modulus = draft.modulus
    remainder = 0 if draft.remainder is None else draft.remainder
    if kind == "divisible":
        if modulus is None:
            raise FamilyError("Falta modulus con el divisor.")
        return ValueSpec(base=draft.base, modulus=_modulus(modulus), remainder=0)
    if kind == "remainder":
        if modulus is None or draft.remainder is None:
            raise FamilyError("Para el resto hacen falta modulus y remainder.")
        mod = _modulus(modulus)
        return ValueSpec(base=draft.base, modulus=mod, remainder=_remainder(draft.remainder, mod))
    if kind == "count":
        symbol = _symbol_of(str(draft.symbol or "").strip().lower())
        if symbol is None:
            raise FamilyError("Falta symbol con el símbolo que se cuenta, de un solo carácter.")
        if modulus is None:
            raise FamilyError("Falta modulus para la cantidad.")
        mod = _modulus(modulus)
        return CountSpec(symbol=symbol, modulus=mod, remainder=_remainder(remainder, mod))
    if kind == "length":
        if modulus is None:
            raise FamilyError("Falta modulus para la longitud.")
        mod = _modulus(modulus)
        return LengthSpec(modulus=mod, remainder=_remainder(remainder, mod))
    if kind == "sequence":
        return _sequence_from_blocks(draft.blocks)
    word = str(draft.word or "").strip().lower()
    if not word or len(word) > MAX_WORD:
        raise FamilyError("Falta word con el prefijo, el sufijo o la subcadena.")
    mode = {"ends": "ends", "starts": "starts", "contains": "contains"}[kind]
    return AffixSpec(mode=mode, word=word)


def _explicit_symbols(alphabet) -> tuple[str, ...] | None:
    if not alphabet:
        return None
    symbols = []
    for symbol in alphabet:
        cleaned = str(symbol).strip().lower()
        if len(cleaned) != 1:
            raise FamilyError(f"«{symbol}» tiene que ser un solo carácter del alfabeto.")
        if cleaned not in symbols:
            symbols.append(cleaned)
    return tuple(symbols)


def _build(request: _Request):
    from app.interpret import Interpretation

    warnings: list[str] = []
    spec = _fill_bases(request.spec, request.explicit, request.text, warnings)
    alphabet = _resolve_alphabet(spec, request.explicit, request.text, warnings)
    _check_alphabet(spec, alphabet)
    automaton = _present(_minimized(_compile(spec, alphabet)))
    check = validate_fa(automaton)
    if not check.ok:
        message = " ".join(check.errors)
        return Interpretation(explanation=message, errors=check.errors, warnings=warnings)
    _check_controls(spec, automaton, alphabet)
    explanation = _explain(spec, automaton, alphabet)
    return Interpretation(
        explanation=explanation,
        automaton=automaton,
        warnings=warnings + check.warnings,
        export_ready=True,
    )


def _fill_bases(spec: Spec, explicit: tuple[str, ...] | None, text: str, warnings: list[str]) -> Spec:
    mentioned = _base_mentioned(text)
    if mentioned is None and explicit and _complete_base(explicit) is not None:
        mentioned = _complete_base(explicit)
    assumed = False

    def fill(node: Spec) -> Spec:
        nonlocal assumed
        if isinstance(node, ValueSpec):
            base = node.base if node.base is not None else mentioned
            if base is None:
                base = 2
                assumed = True
            base = _check_base(base)
            if node.remainder >= node.modulus:
                raise _Invalid(f"El resto {node.remainder} tiene que estar entre 0 y {node.modulus - 1}.")
            return ValueSpec(base=base, modulus=node.modulus, remainder=node.remainder)
        if isinstance(node, NotSpec):
            return NotSpec(fill(node.inner))
        if isinstance(node, AndSpec):
            return AndSpec(tuple(fill(part) for part in node.parts))
        if isinstance(node, OrSpec):
            return OrSpec(tuple(fill(part) for part in node.parts))
        return node

    filled = fill(spec)
    bases = {node.base for node in _walk(filled) if isinstance(node, ValueSpec)}
    if len(bases) > 1:
        raise _Invalid("Las propiedades numéricas no comparten la misma base.")
    if assumed:
        warnings.append("El enunciado no dice la base. Asumí base 2.")
    return filled


def _resolve_alphabet(spec: Spec, explicit: tuple[str, ...] | None, text: str, warnings: list[str]) -> list[str]:
    values = [node for node in _walk(spec) if isinstance(node, ValueSpec)]
    if explicit:
        alphabet = list(explicit)
    elif values:
        alphabet = list(_digits(values[0].base))
    else:
        symbols = _mentioned_symbols(spec)
        if symbols and symbols <= set("01"):
            alphabet = ["0", "1"]
        elif re.search(r"\bbinari", text):
            alphabet = ["0", "1"]
        elif re.search(r"\bdecim", text):
            alphabet = list(_digits(10))
        elif symbols and symbols <= set("ab"):
            alphabet = ["a", "b"]
        elif symbols:
            alphabet = sorted(symbols)
        else:
            alphabet = ["a", "b"]
            warnings.append("El enunciado no dice el alfabeto. Asumí {a, b}.")
    if values:
        digits = list(_digits(values[0].base))
        if set(alphabet) != set(digits) or len(alphabet) != len(digits):
            shown = ", ".join(alphabet)
            raise _Invalid(
                f"El alfabeto {{{shown}}} no son los dígitos de la base {values[0].base}."
            )
        alphabet = digits
    return alphabet


def _check_alphabet(spec: Spec, alphabet: list[str]) -> None:
    allowed = set(alphabet)
    for node in _walk(spec):
        if isinstance(node, CountSpec) and node.symbol not in allowed:
            raise _Invalid(f"«{node.symbol}» no está en el alfabeto {{{', '.join(alphabet)}}}.")
        if isinstance(node, AffixSpec) and any(symbol not in allowed for symbol in node.word):
            extra = next(symbol for symbol in node.word if symbol not in allowed)
            raise _Invalid(f"«{extra}» aparece en la palabra y no está en el alfabeto.")
        if isinstance(node, PositionSpec) and node.symbol not in allowed:
            raise _Invalid(f"«{node.symbol}» no está en el alfabeto {{{', '.join(alphabet)}}}.")
        if isinstance(node, SequenceSpec):
            for block in node.blocks:
                if block.symbol not in allowed:
                    raise _Invalid(f"«{block.symbol}» no está en el alfabeto {{{', '.join(alphabet)}}}.")


def _compile(spec: Spec, alphabet: list[str]) -> FiniteAutomaton:
    if isinstance(spec, ValueSpec):
        return _value_dfa(spec, alphabet)
    if isinstance(spec, CountSpec):
        return _count_dfa(spec, alphabet)
    if isinstance(spec, LengthSpec):
        return _length_dfa(spec, alphabet)
    if isinstance(spec, AffixSpec):
        return _affix_dfa(spec, alphabet)
    if isinstance(spec, PositionSpec):
        return _position_dfa(spec, alphabet)
    if isinstance(spec, SequenceSpec):
        return _sequence_dfa(spec, alphabet)
    if isinstance(spec, NotSpec):
        inner = _minimized(_compile(spec.inner, alphabet))
        return _complement(inner)
    if isinstance(spec, (AndSpec, OrSpec)):
        op = "and" if isinstance(spec, AndSpec) else "or"
        current = _minimized(_compile(spec.parts[0], alphabet))
        for part in spec.parts[1:]:
            nxt = _minimized(_compile(part, alphabet))
            current = _minimized(_product(current, nxt, op))
        return current
    raise FamilyError("No pude armar esa combinación.")


def _minimized(automaton: FiniteAutomaton) -> FiniteAutomaton:
    try:
        return minimize_dfa(automaton)
    except MinimizeError as exc:
        raise _Invalid(str(exc)) from exc


def _value_dfa(spec: ValueSpec, alphabet: list[str]) -> FiniteAutomaton:
    base = spec.base
    modulus = spec.modulus
    states = [f"q{index}" for index in range(modulus)]
    delta = {}
    for remainder in range(modulus):
        for symbol in alphabet:
            nxt = (base * remainder + _digit_value(symbol)) % modulus
            delta[(f"q{remainder}", symbol)] = f"q{nxt}"
    if spec.remainder == 0:
        title = f"Números en base {base} divisibles por {modulus}"
    else:
        title = f"Números en base {base} con resto {spec.remainder} módulo {modulus}"
    return _assemble(alphabet, states, "q0", {f"q{spec.remainder}"}, delta, title)


def _count_dfa(spec: CountSpec, alphabet: list[str]) -> FiniteAutomaton:
    states = [f"q{index}" for index in range(spec.modulus)]
    delta = {}
    for remainder in range(spec.modulus):
        for symbol in alphabet:
            nxt = (remainder + 1) % spec.modulus if symbol == spec.symbol else remainder
            delta[(f"q{remainder}", symbol)] = f"q{nxt}"
    return _assemble(alphabet, states, "q0", {f"q{spec.remainder}"}, delta, _count_title(spec))


def _length_dfa(spec: LengthSpec, alphabet: list[str]) -> FiniteAutomaton:
    states = [f"q{index}" for index in range(spec.modulus)]
    delta = {}
    for remainder in range(spec.modulus):
        for symbol in alphabet:
            delta[(f"q{remainder}", symbol)] = f"q{(remainder + 1) % spec.modulus}"
    return _assemble(alphabet, states, "q0", {f"q{spec.remainder}"}, delta, _length_title(spec))


def _affix_dfa(spec: AffixSpec, alphabet: list[str]) -> FiniteAutomaton:
    if spec.mode == "ends":
        delta, finals, size = _ends_delta(spec.word, alphabet), {len(spec.word)}, len(spec.word) + 1
        title = f"Cadenas que terminan en {spec.word}"
    elif spec.mode == "starts":
        delta, finals, size = _starts_delta(spec.word, alphabet)
        title = f"Cadenas que empiezan con {spec.word}"
    else:
        delta, finals, size = _contains_delta(spec.word, alphabet), {len(spec.word)}, len(spec.word) + 1
        title = f"Cadenas que contienen {spec.word}"
    states = [f"q{index}" for index in range(size)]
    named = {(f"q{index}", symbol): f"q{target}" for (index, symbol), target in delta.items()}
    return _assemble(alphabet, states, "q0", {f"q{state}" for state in finals}, named, title)


def _position_dfa(spec: PositionSpec, alphabet: list[str]) -> FiniteAutomaton:
    if spec.origin == "end":
        return _position_from_end(spec, alphabet)
    return _position_from_start(spec, alphabet)


def _position_from_end(spec: PositionSpec, alphabet: list[str]) -> FiniteAutomaton:
    """Ventana de los últimos k símbolos: solo importa si cada uno fue el pedido.

    El bit 0 es el más nuevo. El bit k-1 es el k-ésimo desde el final. Al leer,
    se corre la ventana y entra el símbolo nuevo. Son 2^k estados y, si el
    alfabeto tiene el símbolo y otro distinto, todos se alcanzan.
    """
    width = spec.k
    size = 1 << width
    mask = size - 1
    oldest = 1 << (width - 1)
    states = [f"q{index}" for index in range(size)]
    delta: dict[tuple[str, str], str] = {}
    for state in range(size):
        for symbol in alphabet:
            bit = 1 if symbol == spec.symbol else 0
            nxt = ((state << 1) | bit) & mask
            delta[(f"q{state}", symbol)] = f"q{nxt}"
    finals = {f"q{state}" for state in range(size) if state & oldest}
    return _assemble(alphabet, states, "q0", finals, delta, _position_title(spec))


def _position_from_start(spec: PositionSpec, alphabet: list[str]) -> FiniteAutomaton:
    """Cadena de k lecturas. Al llegar a la posición, el símbolo decide y el resto no cambia."""
    limit = spec.k
    others = any(symbol != spec.symbol for symbol in alphabet)
    sink = limit + 1
    size = sink + 1 if others else limit + 1
    delta: dict[tuple[str, str], str] = {}
    for count in range(limit - 1):
        for symbol in alphabet:
            delta[(f"q{count}", symbol)] = f"q{count + 1}"
    for symbol in alphabet:
        if symbol == spec.symbol:
            delta[(f"q{limit - 1}", symbol)] = f"q{limit}"
        else:
            delta[(f"q{limit - 1}", symbol)] = f"q{sink}"
    for symbol in alphabet:
        delta[(f"q{limit}", symbol)] = f"q{limit}"
        if others:
            delta[(f"q{sink}", symbol)] = f"q{sink}"
    states = [f"q{index}" for index in range(size)]
    return _assemble(alphabet, states, "q0", {f"q{limit}"}, delta, _position_title(spec))


def _check_position(k: int, origin: str) -> int:
    if k < 1:
        raise _Invalid("La posición tiene que ser un entero mayor que 0.")
    if origin == "end" and k > MAX_FROM_END:
        amount = f" ({2 ** k})" if k <= 20 else ""
        shown = _shown_int(k)
        raise _Invalid(
            f"El {shown}-ésimo símbolo desde el final arma 2^{shown} estados{amount}. "
            f"El tope es {MAX_FROM_END} para no trabar la notebook."
        )
    if origin == "start" and k > MAX_FROM_START:
        raise _Invalid(
            f"La posición {_shown_int(k)} desde el principio pasa el tope de {MAX_FROM_START}."
        )
    return k


def _position_name(k: int, origin: str) -> str:
    if origin == "end":
        names = {1: "último", 2: "penúltimo", 3: "antepenúltimo", 4: "trasantepenúltimo"}
        if k in names:
            return f"{names[k]} símbolo"
        return f"{k}-ésimo símbolo desde el final"
    names = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto", 5: "quinto"}
    if k in names:
        return f"{names[k]} símbolo"
    return f"{k}-ésimo símbolo desde el principio"


def _position_title(spec: PositionSpec) -> str:
    return f"El {_position_name(spec.k, spec.origin)} es {spec.symbol}"


def _ends_delta(word: str, alphabet: list[str]) -> dict[tuple[int, str], int]:
    pi = _prefix_table(word)
    limit = len(word)
    delta: dict[tuple[int, str], int] = {}
    for state in range(limit + 1):
        for symbol in alphabet:
            if state < limit and word[state] == symbol:
                delta[(state, symbol)] = state + 1
            elif state == 0:
                delta[(state, symbol)] = 0
            else:
                delta[(state, symbol)] = delta[(pi[state - 1], symbol)]
    return delta


def _contains_delta(word: str, alphabet: list[str]) -> dict[tuple[int, str], int]:
    delta = _ends_delta(word, alphabet)
    limit = len(word)
    for symbol in alphabet:
        delta[(limit, symbol)] = limit
    return delta


def _starts_delta(word: str, alphabet: list[str]) -> tuple[dict[tuple[int, str], int], set[int], int]:
    limit = len(word)
    dead = limit + 1
    delta: dict[tuple[int, str], int] = {}
    used_dead = False
    for state in range(limit):
        for symbol in alphabet:
            if word[state] == symbol:
                delta[(state, symbol)] = state + 1
            else:
                delta[(state, symbol)] = dead
                used_dead = True
    for symbol in alphabet:
        delta[(limit, symbol)] = limit
        if used_dead:
            delta[(dead, symbol)] = dead
    size = dead + 1 if used_dead else limit + 1
    return delta, {limit}, size


def _prefix_table(word: str) -> list[int]:
    table = [0] * len(word)
    length = 0
    for index in range(1, len(word)):
        while length and word[length] != word[index]:
            length = table[length - 1]
        if word[length] == word[index]:
            length += 1
        table[index] = length
    return table


def _complement(automaton: FiniteAutomaton) -> FiniteAutomaton:
    states = [
        State(id=state.id, initial=state.initial, final=not state.final) for state in automaton.states
    ]
    if not any(state.final for state in states):
        raise _Invalid("El complemento es el lenguaje vacío: ninguna cadena cumple la condición.")
    return FiniteAutomaton(
        deterministic=True,
        alphabet=list(automaton.alphabet),
        states=states,
        transitions=list(automaton.transitions),
        description=f"Complemento de {automaton.description[:1].lower()}{automaton.description[1:]}",
    )


def _product(left: FiniteAutomaton, right: FiniteAutomaton, op: str) -> FiniteAutomaton:
    if list(left.alphabet) != list(right.alphabet):
        raise FamilyError("Las propiedades no comparten el alfabeto.")
    if len(left.states) * len(right.states) > MAX_PRODUCT:
        raise _Invalid("La combinación arma demasiados estados. Partila en pedidos más chicos.")
    alphabet = list(left.alphabet)
    left_delta = {(item.from_state, item.read): item.to for item in left.transitions}
    right_delta = {(item.from_state, item.read): item.to for item in right.transitions}
    left_final = {state.id for state in left.states if state.final}
    right_final = {state.id for state in right.states if state.final}
    left_initial = next(state.id for state in left.states if state.initial)
    right_initial = next(state.id for state in right.states if state.initial)
    pairs = [(a.id, b.id) for a in left.states for b in right.states]
    names = {pair: f"p{index}" for index, pair in enumerate(pairs)}

    def accept(pair: tuple[str, str]) -> bool:
        left_ok = pair[0] in left_final
        right_ok = pair[1] in right_final
        return left_ok and right_ok if op == "and" else left_ok or right_ok

    delta = {}
    for pair in pairs:
        for symbol in alphabet:
            nxt = (left_delta[(pair[0], symbol)], right_delta[(pair[1], symbol)])
            delta[(names[pair], symbol)] = names[nxt]
    joiner = " y " if op == "and" else " o "
    title = joiner.join(item.description[:1].lower() + item.description[1:] for item in (left, right))
    title = title[:1].upper() + title[1:]
    return _assemble(
        alphabet,
        [names[pair] for pair in pairs],
        names[(left_initial, right_initial)],
        {names[pair] for pair in pairs if accept(pair)},
        delta,
        title,
    )


def _present(automaton: FiniteAutomaton) -> FiniteAutomaton:
    """Renombra en orden q0, q1, … desde el inicial. Si ya está así, no lo toca."""
    if not is_total_dfa(automaton):
        return automaton
    alphabet = list(automaton.alphabet)
    delta = {(item.from_state, item.read): item.to for item in automaton.transitions}
    initial = next(state.id for state in automaton.states if state.initial)
    order: list[str] = []
    seen: set[str] = set()
    pending = [initial]
    while pending:
        state = pending.pop(0)
        if state in seen:
            continue
        seen.add(state)
        order.append(state)
        for symbol in alphabet:
            nxt = delta[(state, symbol)]
            if nxt not in seen:
                pending.append(nxt)
    names = {old: f"q{index}" for index, old in enumerate(order)}
    if len(order) == len(automaton.states) and all(names[state.id] == state.id for state in automaton.states):
        return automaton
    finals = {state.id for state in automaton.states if state.final}
    return _assemble(
        alphabet,
        [names[state] for state in order],
        names[initial],
        {names[state] for state in finals if state in names},
        {(names[state], symbol): names[delta[(state, symbol)]] for state in order for symbol in alphabet},
        automaton.description,
    )


def _assemble(
    alphabet: list[str],
    states: list[str],
    initial: str,
    finals: set[str],
    delta: dict[tuple[str, str], str],
    description: str,
) -> FiniteAutomaton:
    return FiniteAutomaton(
        deterministic=True,
        alphabet=list(alphabet),
        description=description,
        states=[State(id=state, initial=state == initial, final=state in finals) for state in states],
        transitions=[
            Transition(from_state=state, to=delta[(state, symbol)], read=symbol)
            for state in states
            for symbol in alphabet
        ],
    )


def _explain(spec: Spec, automaton: FiniteAutomaton, alphabet: list[str]) -> str:
    letters = ", ".join(alphabet)
    lines = [_leaf_explanation(spec, automaton), f"Alfabeto {{{letters}}}."]
    if any(isinstance(node, ValueSpec) for node in _walk(spec)) and _CONVENTION not in lines[0]:
        lines.append(_CONVENTION)
    lines.append(f"Quedó un AFD mínimo de {len(automaton.states)} estados.")
    lines.append("Lo armé en código, sin pedirle las transiciones al modelo.")
    return "\n".join(line for line in lines if line)


def _leaf_explanation(spec: Spec, automaton: FiniteAutomaton) -> str:
    if isinstance(spec, ValueSpec):
        formula = (
            f"Cada estado guarda el resto de dividir por {spec.modulus} el número leído "
            f"de izquierda a derecha. δ(r, d) = ({spec.base}·r + d) módulo {spec.modulus}."
        )
        if _plain_remainder(automaton, spec):
            names = ", ".join(f"q{index} es el resto {index}" for index in range(spec.modulus))
            detail = f"q0 es el inicial. El único final es q{spec.remainder}. {names}."
        else:
            detail = (
                f"Había estados de resto equivalentes. Minimizado, queda en {len(automaton.states)} estados. "
                f"El resto que se acepta es {spec.remainder}."
            )
        return "\n".join((formula, _CONVENTION, detail))
    if isinstance(spec, CountSpec):
        empty = "se acepta" if spec.remainder == 0 else "se rechaza"
        return (
            f"Se cuenta la cantidad de «{spec.symbol}» módulo {spec.modulus}. "
            f"Los demás símbolos no cambian el resto. El final es el resto {spec.remainder}. "
            f"La cadena vacía tiene cantidad 0, así que {empty}."
        )
    if isinstance(spec, LengthSpec):
        empty = "se acepta" if spec.remainder == 0 else "se rechaza"
        return (
            f"Se cuenta la longitud módulo {spec.modulus}. Cada símbolo suma uno. "
            f"El final es el resto {spec.remainder}. La cadena vacía tiene longitud 0, así que {empty}."
        )
    if isinstance(spec, AffixSpec):
        if spec.mode == "ends":
            return (
                f"El estado recuerda el prefijo más largo de «{spec.word}» que es sufijo de lo leído. "
                "El único final es haber formado ese sufijo."
            )
        if spec.mode == "starts":
            return (
                f"Se avanza mientras el prefijo coincide con «{spec.word}». "
                "Si un símbolo se desvía, se cae a un pozo. Al completar el prefijo, todo lo que sigue se acepta."
            )
        return (
            f"Se busca la subcadena «{spec.word}». "
            "Al encontrarla, el estado final se queda ahí: lo que sigue también se acepta."
        )
    if isinstance(spec, SequenceSpec):
        pattern = _sequence_pattern(spec)
        return (
            f"La cadena es la concatenación {pattern}. "
            "Cada bloque es un solo símbolo: la estrella repite cero o más veces, "
            "XX* repite una o más, y un número delante del símbolo es la cantidad de veces. "
            "Ese número no es otro símbolo del alfabeto."
        )
    if isinstance(spec, PositionSpec):
        name = _position_name(spec.k, spec.origin)
        short = (
            "La cadena vacía se rechaza."
            if spec.k == 1
            else f"Con menos de {spec.k} símbolos se rechaza, porque esa posición no existe."
        )
        if spec.origin == "end":
            if spec.k == 1:
                window = f"si el último símbolo fue «{spec.symbol}»"
            else:
                window = f"si cada uno de los últimos {spec.k} símbolos fue «{spec.symbol}»"
            return (
                f"Cada estado recuerda {window}. "
                f"Hay 2^{spec.k} combinaciones. El estado es final cuando el {name} es «{spec.symbol}». {short}"
            )
        return (
            f"Se cuenta hasta el {name}. Si ese símbolo es «{spec.symbol}», lo que sigue también se acepta. "
            f"Si es otro, se rechaza de ahí en adelante. {short}"
        )
    if isinstance(spec, NotSpec):
        return (
            "Complemento: se niegan los estados finales de la propiedad y se vuelve a minimizar. "
            f"La propiedad era: {_short(spec.inner)}."
        )
    if isinstance(spec, AndSpec):
        parts = "\n".join(f"— {_short(part)}" for part in spec.parts)
        return (
            "Intersección por producto. Un estado es final solo si lo son las dos propiedades.\n" + parts
        )
    parts = "\n".join(f"— {_short(part)}" for part in spec.parts)
    return "Unión por producto. Un estado es final si lo es alguna de las propiedades.\n" + parts


def _short(spec: Spec) -> str:
    if isinstance(spec, ValueSpec):
        if spec.remainder == 0:
            return f"números en base {spec.base} divisibles por {spec.modulus}"
        return f"números en base {spec.base} con resto {spec.remainder} módulo {spec.modulus}"
    if isinstance(spec, CountSpec):
        return _count_title(spec).lower()
    if isinstance(spec, LengthSpec):
        return _length_title(spec).lower()
    if isinstance(spec, AffixSpec):
        label = {"ends": "terminan en", "starts": "empiezan con", "contains": "contienen"}[spec.mode]
        return f"cadenas que {label} {spec.word}"
    if isinstance(spec, PositionSpec):
        return f"el {_position_name(spec.k, spec.origin)} es {spec.symbol}"
    if isinstance(spec, SequenceSpec):
        return f"la secuencia {_sequence_pattern(spec)}"
    if isinstance(spec, NotSpec):
        return f"no ({_short(spec.inner)})"
    joiner = " y " if isinstance(spec, AndSpec) else " o "
    return joiner.join(_short(part) for part in spec.parts)


def _count_title(spec: CountSpec) -> str:
    if spec.modulus == 2 and spec.remainder == 0:
        return f"Cantidad par de {spec.symbol}"
    if spec.modulus == 2 and spec.remainder == 1:
        return f"Cantidad impar de {spec.symbol}"
    if spec.remainder == 0:
        return f"Cantidad de {spec.symbol} múltiplo de {spec.modulus}"
    return f"Cantidad de {spec.symbol} con resto {spec.remainder} módulo {spec.modulus}"


def _length_title(spec: LengthSpec) -> str:
    if spec.modulus == 2 and spec.remainder == 0:
        return "Longitud par"
    if spec.modulus == 2 and spec.remainder == 1:
        return "Longitud impar"
    if spec.remainder == 0:
        return f"Longitud múltiplo de {spec.modulus}"
    return f"Longitud con resto {spec.remainder} módulo {spec.modulus}"


def _plain_remainder(automaton: FiniteAutomaton, spec: ValueSpec) -> bool:
    if spec.base is None or len(automaton.states) != spec.modulus:
        return False
    if {state.id for state in automaton.states} != {f"q{index}" for index in range(spec.modulus)}:
        return False
    finals = [state.id for state in automaton.states if state.final]
    initials = [state.id for state in automaton.states if state.initial]
    if finals != [f"q{spec.remainder}"] or initials != ["q0"]:
        return False
    delta = {(item.from_state, item.read): item.to for item in automaton.transitions}
    for remainder in range(spec.modulus):
        for symbol in _digits(spec.base):
            expected = f"q{(spec.base * remainder + _digit_value(symbol)) % spec.modulus}"
            if delta.get((f"q{remainder}", symbol)) != expected:
                return False
    return True


def _check_controls(spec: Spec, automaton: FiniteAutomaton, alphabet: list[str]) -> None:
    # Una sola pasada por las flechas. El control corre cientos de palabras.
    runner = Simulator(automaton)
    bad = []
    for word in _control_words(spec, alphabet):
        expected = _semantics(spec, word)
        result = runner.run(word, trace=False)
        if not result.ok or result.accepted != expected:
            shown = word or "ε"
            verb = "aceptarse" if expected else "rechazarse"
            bad.append(f"«{shown}» debería {verb}")
        if len(bad) >= 6:
            break
    if bad:
        raise FamilyError("El autómata no pasa el control interno: " + "; ".join(bad))


def _control_words(spec: Spec, alphabet: list[str]) -> list[str]:
    """Muestra del control. Se corta en MAX_CONTROL_WORDS, sin armar el resto.

    Antes se formateaba cada entero hasta base·módulo·3 y recién después se
    descartaba lo que pasaba de 1500. En base 36 y módulo 128 eso eran más de
    trece mil números, y cada uno volvía a armar el alfabeto de dígitos.
    """
    allowed = set(alphabet)
    unique: list[str] = []
    seen: set[str] = set()

    def add(word: str) -> None:
        if len(unique) >= MAX_CONTROL_WORDS or word in seen:
            return
        for symbol in word:
            if symbol not in allowed:
                return
        seen.add(word)
        unique.append(word)

    add("")
    depth = 4 if len(alphabet) <= 2 else 2
    if alphabet and len(alphabet) ** depth <= 5000:
        frontier = [""]
        for _ in range(depth):
            nxt: list[str] = []
            for word in frontier:
                for symbol in alphabet:
                    formed = word + symbol
                    nxt.append(formed)
                    add(formed)
            frontier = nxt
            if len(unique) >= MAX_CONTROL_WORDS:
                break
    if len(unique) < MAX_CONTROL_WORDS:
        for node in _walk(spec):
            if len(unique) >= MAX_CONTROL_WORDS:
                break
            if isinstance(node, ValueSpec) and node.base is not None:
                span = node.base * node.modulus * 3 + 1
                for number in range(span):
                    if len(unique) >= MAX_CONTROL_WORDS:
                        break
                    rendered = _format_number(number, node.base)
                    add(rendered)
                    add("0" + rendered)
                    add("00" + rendered)
            if isinstance(node, AffixSpec):
                add(node.word)
                add(node.word + alphabet[0])
                add(alphabet[0] + node.word)
                add(alphabet[-1] + node.word + alphabet[0])
            if isinstance(node, PositionSpec):
                other = next((symbol for symbol in alphabet if symbol != node.symbol), node.symbol)
                add(node.symbol * node.k)
                add(other * node.k)
                add(other * (node.k - 1))
                if node.origin == "end":
                    add(node.symbol + other * (node.k - 1))
                    add(other * (node.k - 1) + node.symbol + other)
                else:
                    add(other * (node.k - 1) + node.symbol)
                    add(other * (node.k - 1) + node.symbol + other)
            if isinstance(node, SequenceSpec):
                for extra in (0, 1, 2):
                    add(_sequence_sample(node, extra))
    return unique


def _semantics(spec: Spec, word: str) -> bool:
    if isinstance(spec, ValueSpec):
        value = 0
        for symbol in word:
            value = spec.base * value + _digit_value(symbol)
        return value % spec.modulus == spec.remainder
    if isinstance(spec, CountSpec):
        return word.count(spec.symbol) % spec.modulus == spec.remainder
    if isinstance(spec, LengthSpec):
        return len(word) % spec.modulus == spec.remainder
    if isinstance(spec, AffixSpec):
        if spec.mode == "ends":
            return word.endswith(spec.word)
        if spec.mode == "starts":
            return word.startswith(spec.word)
        return spec.word in word
    if isinstance(spec, PositionSpec):
        if len(word) < spec.k:
            return False
        index = -spec.k if spec.origin == "end" else spec.k - 1
        return word[index] == spec.symbol
    if isinstance(spec, SequenceSpec):
        return _sequence_accepts(spec.blocks, word)
    if isinstance(spec, NotSpec):
        return not _semantics(spec.inner, word)
    if isinstance(spec, AndSpec):
        return all(_semantics(part, word) for part in spec.parts)
    return any(_semantics(part, word) for part in spec.parts)


def _parse_request(text: str) -> _Request | None:
    stripped, explicit = _take_alphabet(text)
    stripped = _strip_prefix(stripped)
    _reject_glued_negative(stripped)
    # La secuencia solo cuando el enunciado encadena bloques. Si no, «un 0»
    # se vuelve «0» y sigue el camino de termina / empieza / contiene.
    if _confident_sequence(stripped, explicit):
        spec = _parse_sequence(stripped, explicit)
        if spec is not None:
            return _Request(spec=spec, explicit=explicit, text=stripped)
    else:
        pair = _bare_ambiguity(stripped, explicit)
        if pair is not None:
            order, _alphabet = _reading_alphabet(explicit, stripped)
            raise _Invalid(ambiguous_repetition_message(pair[0], pair[1], order))
    expanded = _expand_counts(stripped, explicit)
    spec = _parse_expr(expanded)
    if spec is None:
        return None
    return _Request(spec=spec, explicit=explicit, text=expanded)


class _Unsure(Exception):
    """La lectura de secuencia no cierra. Sigue el camino de las otras familias."""


_CONTINUATION = re.compile(
    r"\b(?:continu\w*|sigue|siguen|sigan|siga|seguir|luego|despues)\b"
)
_PROPERTY_VERB = re.compile(
    r"\b(?:termin\w*|empiez\w*|comenz\w*|comienz\w*|contien\w*|conteng\w*|contener|"
    r"longitud|largo|divisib\w*|multipl\w*|prefijo|sufijo|subcadena)\b"
)
_POSITION_CUE = re.compile(
    r"\b(?:ultimo|penultimo|antepenultimo|trasantepenultimo|esim[oa]|"
    r"primer\w*|segund\w*|tercer\w*|desde el final|desde el principio)\b"
)


def _confident_sequence(text: str, explicit: tuple[str, ...] | None) -> bool:
    """True solo si el enunciado describe bloques en orden, no una propiedad suelta.

    Hace falta un «continúa / sigue / luego», o una lista de bloques con estrella,
    o un bloque suelto que no es «termina», «empieza», «contiene» ni la posición.
    Si no, se devuelve False y el enunciado sigue por las familias de antes.
    """
    stats = _block_stats(text, explicit)
    if stats == "too-big":
        return True
    found, kleene = stats
    if _CONTINUATION.search(text) and (kleene or found >= 1):
        return True
    if found >= 2 and kleene:
        return True
    if _PROPERTY_VERB.search(text) or _POSITION_CUE.search(text):
        return False
    return kleene or found >= 1


def _block_stats(text: str, explicit: tuple[str, ...] | None):
    tokens = _SEQUENCE_TOKEN.findall(text)
    _order, alphabet = _reading_alphabet(explicit, text)
    found = 0
    kleene = False
    index = 0
    while index < len(tokens):
        span = _kleene_end(tokens, index)
        if span is not None:
            _kind, end = span
            symbol_index = _symbol_at(tokens, end, alphabet)
            if symbol_index is not None:
                kleene = True
                found += 1
                index = symbol_index + 1
                continue
        try:
            counted = _count_span(tokens, index, alphabet)
        except _Invalid:
            return "too-big"
        if counted is not None:
            found += 1
            index = counted[1]
            continue
        index += 1
    return found, kleene


def _bare_ambiguity(text: str, explicit: tuple[str, ...] | None) -> tuple[str, str] | None:
    """«3 0» con el 3 en el alfabeto, cuando no hay una propiedad que lo explique."""
    if _PROPERTY_VERB.search(text) or _POSITION_CUE.search(text):
        return None
    tokens = _SEQUENCE_TOKEN.findall(text)
    _order, alphabet = _reading_alphabet(explicit, text)
    return _first_ambiguous(tokens, alphabet)


def _expand_counts(text: str, explicit: tuple[str, ...] | None) -> str:
    """«un 0» pasa a «0» y «tres ceros» a «000», para las familias que ya existían.

    Lo que no es una palabra latina se queda igual: una «а» cirílica no se pierde.
    """
    _order, alphabet = _reading_alphabet(explicit, text)
    token_re = re.compile(r"[0-9０-９a-záéíóúüñ]+|[,.;:]|\s+")
    parts: list[str] = []
    cursor = 0
    for match in token_re.finditer(text):
        if match.start() > cursor:
            parts.append(text[cursor : match.start()])
        parts.append(match.group())
        cursor = match.end()
    if cursor < len(text):
        parts.append(text[cursor:])
    out: list[str] = []
    index = 0
    while index < len(parts):
        token = parts[index]
        if token.isspace() or token in ",.;:":
            out.append(token)
            index += 1
            continue
        nxt = index + 1
        while nxt < len(parts) and parts[nxt].isspace():
            nxt += 1
        if nxt < len(parts) and repetition_reading(token, parts[nxt], alphabet) == "count":
            count = spanish_count(token)
            if count is None:
                count = _user_int(token)
            symbol = _sequence_tokens_symbol(parts[nxt], alphabet)
            if symbol is not None and 1 <= count <= MAX_SEQUENCE_REPEAT:
                out.append(symbol * count)
                index = nxt + 1
                continue
        out.append(token)
        index += 1
    return "".join(out)


_SEQUENCE_FILLER = {
    "un", "una", "el", "la", "los", "las", "afd", "afn", "dfa", "nfa",
    "automata", "finito", "finitos", "que", "acepte", "acepten", "acepta",
    "aceptan", "reconozca", "reconozcan", "reconoce", "cadenas", "cadena",
    "palabras", "palabra", "lenguaje", "sobre", "de", "del", "al", "por",
    "con", "en", "luego", "despues", "tambien", "ademas", "nuevo",
    "nuevamente", "otra", "vez", "solo", "solamente", "exactamente",
    "aquellas", "aquellos", "todas", "todos", "me", "dame", "quiero",
    "para", "se", "su", "empiecen", "empiece", "empiezan", "empieza",
    "empezar", "comiencen", "comience", "comienzan", "comienza", "comenzar",
    "continuan", "continua", "continuen", "continue", "continuar",
    "siguen", "sigue", "sigan", "siga", "seguir", "terminen", "termine",
    "terminan", "termina", "terminar", "final", "principio", "inicio",
    "veces", "seguidos", "seguidas", "seguido", "seguida", "repite",
    "repetido", "repetida", "repetidos", "repetidas", "repeticiones",
    "binario", "binarios", "binaria", "binarias", "decimal", "decimales",
    "numero", "numeros", "entero", "enteros", "digito", "digitos",
    "simbolo", "simbolos",
}
# El ３ de ancho completo es el mismo conteo que el 3. No se pliega una letra.
_SEQUENCE_TOKEN = re.compile(r"[0-9０-９a-záéíóúüñ]+|[,.;:]")
_GLUED_NEGATIVE = re.compile(r"(?<![\w])-([0-9０-９]+)\s+([0-9０-９a-záéíóúüñ]+)")
_SEQUENCE_META = set("*+|()?[]{}\\")


def _parse_sequence(text: str, explicit: tuple[str, ...] | None) -> SequenceSpec | None:
    """Concatenación de bloques. Si no cierra, devuelve None para no pisar otra familia.

    Si «3 0» puede ser símbolo o cantidad, explica el caso y no llama al modelo.
    """
    tokens = _SEQUENCE_TOKEN.findall(text)
    order, alphabet = _reading_alphabet(explicit, text)
    ambiguous = _first_ambiguous(tokens, alphabet)
    if ambiguous is not None:
        number, symbol_token = ambiguous
        raise _Invalid(ambiguous_repetition_message(number, symbol_token, order))
    if not _has_sequence_quantifier(tokens, alphabet):
        return None
    # findall se saltea ٠١٢. Si se ignora, «٢ 0» desaparece y la secuencia
    # queda más corta. No es una cantidad: se dice y no se arma el AFD.
    stray = _stray_digit(text)
    if stray is not None:
        raise _Invalid(f"No entiendo el número «{stray}».")
    try:
        blocks = _read_blocks(tokens, alphabet)
    except _Unsure:
        return None
    _check_sequence_budget(blocks)
    return SequenceSpec(tuple(blocks))


def _stray_digit(text: str) -> str | None:
    """Un dígito decimal que no es ASCII ni ancho completo, fuera de las llaves."""
    pieces = re.split(r"(\{[^{}]*\})", text)
    for piece in pieces:
        if piece.startswith("{"):
            continue
        for char in piece:
            if char.isdecimal() and not char.isascii() and char not in "０１２３４５６７８９":
                return char
    return None


def _reading_alphabet(
    explicit: tuple[str, ...] | None, text: str
) -> tuple[list[str] | None, set[str] | None]:
    if explicit:
        return list(explicit), set(explicit)
    if re.search(r"\bbinari", text):
        symbols = ["0", "1"]
        return symbols, set(symbols)
    if re.search(r"\bdecim", text):
        symbols = list("0123456789")
        return symbols, set(symbols)
    return None, None


def _sequence_tokens_symbol(token: str, alphabet: set[str] | None) -> str | None:
    if symbol_name(token):
        return symbol_name(token)
    if len(token) != 1 or not token.isalnum():
        return None
    if token in {"y", "e", "o", "u"} and (alphabet is None or token not in alphabet):
        return None
    return token


def _kleene_end(tokens: list[str], index: int) -> tuple[str, int] | None:
    if index >= len(tokens):
        return None
    head = tokens[index]
    if head in {"infinitos", "infinitas", "infinito", "infinita"}:
        return "star", index + 1
    if tokens[index : index + 3] == ["cualquier", "cantidad", "de"]:
        return "star", index + 3
    if tokens[index : index + 3] == ["cero", "o", "mas"]:
        return "star", index + 3
    if tokens[index : index + 3] == ["uno", "o", "mas"]:
        return "plus", index + 3
    return None


def _symbol_at(tokens: list[str], index: int, alphabet: set[str] | None) -> int | None:
    """Índice del símbolo, saltando un «de» o un «veces» que no es el símbolo."""
    if index < len(tokens) and tokens[index] in {"de", "veces"}:
        nxt = index + 1
        if nxt < len(tokens) and _sequence_tokens_symbol(tokens[nxt], alphabet):
            return nxt
        return None
    if index < len(tokens) and _sequence_tokens_symbol(tokens[index], alphabet):
        return index
    return None


def _first_ambiguous(tokens: list[str], alphabet: set[str] | None) -> tuple[str, str] | None:
    for index, token in enumerate(tokens):
        if not token.isdigit() or len(token) != 1:
            continue
        symbol_index = _symbol_at(tokens, index + 1, alphabet)
        if symbol_index is None:
            continue
        if repetition_reading(token, tokens[symbol_index], alphabet) == "ambiguous":
            return token, tokens[symbol_index]
    return None


def _has_sequence_quantifier(tokens: list[str], alphabet: set[str] | None) -> bool:
    index = 0
    while index < len(tokens):
        kleene = _kleene_end(tokens, index)
        if kleene is not None:
            _kind, end = kleene
            if _symbol_at(tokens, end, alphabet) is not None:
                return True
        if _count_span(tokens, index, alphabet) is not None:
            return True
        index += 1
    return False


def _count_span(tokens: list[str], index: int, alphabet: set[str] | None) -> tuple[BlockSpec, int] | None:
    symbol_index = _symbol_at(tokens, index + 1, alphabet)
    if symbol_index is None:
        return None
    reading = repetition_reading(tokens[index], tokens[symbol_index], alphabet)
    if reading != "count":
        return None
    count = spanish_count(tokens[index])
    if count is None:
        count = _user_int(tokens[index])
    symbol = _sequence_tokens_symbol(tokens[symbol_index], alphabet)
    if symbol is None:
        return None
    return _exact_block(symbol, count), symbol_index + 1


def _exact_block(symbol: str, count: int) -> BlockSpec:
    if count < 1:
        raise _Invalid(
            "La repetición tiene que ser al menos 1. Para cero o más, usá «infinitos» o «cero o más»."
        )
    if count > MAX_SEQUENCE_REPEAT:
        raise _Invalid(
            f"{_shown_int(count)} repeticiones arman un tramo demasiado largo. "
            f"El tope es {MAX_SEQUENCE_REPEAT}."
        )
    return BlockSpec(symbol=symbol, kind="exact", count=count)


def _is_sequence_filler(token: str, alphabet: set[str] | None) -> bool:
    if token in {"y", "e", "o", "u"}:
        return alphabet is None or token not in alphabet
    return token in _SEQUENCE_FILLER


def _read_blocks(tokens: list[str], alphabet: set[str] | None) -> list[BlockSpec]:
    blocks: list[BlockSpec] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in ",.;:":
            index += 1
            continue
        kleene = _kleene_end(tokens, index)
        if kleene is not None:
            kind, end = kleene
            symbol_index = _symbol_at(tokens, end, alphabet)
            if symbol_index is not None:
                symbol = _sequence_tokens_symbol(tokens[symbol_index], alphabet)
                if symbol is None:
                    raise _Invalid(_sequence_stuck(tokens[symbol_index]))
                _reject_operator(symbol)
                count = 1 if kind == "plus" else 0
                blocks.append(BlockSpec(symbol=symbol, kind=kind, count=count))
                index = symbol_index + 1
                continue
        counted = _count_span(tokens, index, alphabet)
        if counted is not None:
            block, index = counted
            _reject_operator(block.symbol)
            blocks.append(block)
            continue
        if _is_sequence_filler(token, alphabet):
            index += 1
            continue
        bare = _bare_blocks(token, alphabet)
        if bare is not None:
            blocks.extend(bare)
            index += 1
            continue
        raise _Unsure()
    if not blocks:
        raise _Unsure()
    return blocks


def _bare_blocks(token: str, alphabet: set[str] | None) -> list[BlockSpec] | None:
    named = symbol_name(token)
    if named:
        _reject_operator(named)
        return [BlockSpec(symbol=named, kind="exact", count=1)]
    if len(token) == 1 and token.isalnum():
        if token in {"y", "e", "o", "u"} and (alphabet is None or token not in alphabet):
            return None
        _reject_operator(token)
        return [BlockSpec(symbol=token, kind="exact", count=1)]
    if alphabet and len(token) > 1 and all(char in alphabet for char in token):
        blocks = []
        for char in token:
            _reject_operator(char)
            blocks.append(BlockSpec(symbol=char, kind="exact", count=1))
        return blocks
    return None


def _sequence_stuck(token: str) -> str:
    where = f" Me trabé en «{token}»." if token else ""
    return (
        "No pude leer toda la secuencia de bloques."
        + where
        + " Cada tramo puede ser «infinitos 1», «cualquier cantidad de 0», "
        "«cero o más 1», «uno o más 0», «3 0», «tres ceros», «dos unos» o «un 0»."
    )


def _reject_operator(symbol: str) -> None:
    if symbol in _SEQUENCE_META:
        raise _Invalid(
            f"«{symbol}» es un operador y no lo uso como símbolo de un bloque."
        )


def _check_sequence_budget(blocks: list[BlockSpec]) -> None:
    if len(blocks) > MAX_SEQUENCE_BLOCKS:
        raise _Invalid(
            f"La secuencia tiene {len(blocks)} bloques. El tope es {MAX_SEQUENCE_BLOCKS}."
        )
    total = sum(block.count if block.kind == "exact" else 1 for block in blocks)
    if total > MAX_SEQUENCE_SYMBOLS:
        raise _Invalid(
            f"La secuencia junta más de {MAX_SEQUENCE_SYMBOLS} símbolos. Partila en un pedido más chico."
        )


def _sequence_from_blocks(blocks) -> SequenceSpec:
    if not blocks:
        raise FamilyError("Falta blocks con los bloques de la secuencia, en orden.")
    parsed: list[BlockSpec] = []
    for item in blocks:
        symbol = _symbol_of(str(item.symbol or "").strip().lower())
        if symbol is None or len(symbol) != 1:
            raise FamilyError("Cada bloque necesita un símbolo de un solo carácter.")
        _reject_operator(symbol)
        parsed.append(_block_from_repeat(symbol, item.repeat))
    _check_sequence_budget(parsed)
    return SequenceSpec(tuple(parsed))


def _block_from_repeat(symbol: str, repeat) -> BlockSpec:
    text = str(repeat).strip().lower()
    if text in {"*", "star", "estrella", "infinitos", "infinito"}:
        return BlockSpec(symbol=symbol, kind="star", count=0)
    if text in {"+", "plus", "mas"}:
        return BlockSpec(symbol=symbol, kind="plus", count=1)
    if text.isdigit():
        return _exact_block(symbol, _user_int(text))
    raise FamilyError(f"No entiendo la repetición «{repeat}». Usá *, + o un número.")


def _sequence_pattern(spec: SequenceSpec) -> str:
    parts: list[str] = []
    for block in spec.blocks:
        _reject_operator(block.symbol)
        if block.kind == "star":
            parts.append(block.symbol + "*")
        elif block.kind == "plus":
            parts.append(block.symbol + block.symbol + "*")
        else:
            parts.append(block.symbol * block.count)
    return "".join(parts)


def _sequence_dfa(spec: SequenceSpec, alphabet: list[str]) -> FiniteAutomaton:
    from app.regex_lang import RegexError, compile_pattern

    pattern = _sequence_pattern(spec)
    try:
        automaton, _ignored = compile_pattern(pattern)
    except RegexError as exc:
        raise _Invalid(str(exc)) from exc
    automaton = _expand_alphabet(automaton, alphabet)
    return automaton.model_copy(update={"description": f"Secuencia {pattern}"})


def _expand_alphabet(automaton: FiniteAutomaton, alphabet: list[str]) -> FiniteAutomaton:
    wanted = list(alphabet)
    have = set(automaton.alphabet)
    missing = [symbol for symbol in wanted if symbol not in have]
    extra = [symbol for symbol in automaton.alphabet if symbol not in set(wanted)]
    if extra:
        raise _Invalid(f"«{extra[0]}» no está en el alfabeto.")
    if not missing:
        if list(automaton.alphabet) == wanted:
            return automaton
        return automaton.model_copy(update={"alphabet": wanted})
    ids = [state.id for state in automaton.states]
    sink = _fresh_sink(set(ids))
    transitions = list(automaton.transitions)
    for state_id in ids:
        for symbol in missing:
            transitions.append(Transition(from_state=state_id, to=sink, read=symbol))
    for symbol in wanted:
        transitions.append(Transition(from_state=sink, to=sink, read=symbol))
    states = list(automaton.states)
    states.append(State(id=sink, initial=False, final=False))
    return automaton.model_copy(
        update={"alphabet": wanted, "states": states, "transitions": transitions}
    )


def _fresh_sink(used: set[str]) -> str:
    if "qs" not in used:
        return "qs"
    number = 2
    while f"qs{number}" in used:
        number += 1
    return f"qs{number}"


def _sequence_sample(spec: SequenceSpec, extra: int) -> str:
    parts: list[str] = []
    for block in spec.blocks:
        if block.kind == "exact":
            parts.append(block.symbol * block.count)
        elif block.kind == "plus":
            parts.append(block.symbol * (1 + extra))
        else:
            parts.append(block.symbol * extra)
    return "".join(parts)


def _sequence_accepts(blocks: tuple[BlockSpec, ...], word: str) -> bool:
    """True si la palabra es exactamente esa secuencia.

    No se prueba cada reparto con recursión: veinte «uno o más» del mismo
    símbolo, sobre una palabra que no entra, recorría todas las composiciones
    y no volvía. Acá cada bloque mira el tramo de una vez.
    """
    length = len(word)
    reachable = [False] * (length + 1)
    reachable[0] = True
    for block in blocks:
        nxt = [False] * (length + 1)
        symbol = block.symbol
        if block.kind == "exact":
            piece = symbol * block.count
            piece_length = len(piece)
            for pos, here in enumerate(reachable):
                if here and word.startswith(piece, pos):
                    nxt[pos + piece_length] = True
        else:
            minimum = 1 if block.kind == "plus" else 0
            for pos, here in enumerate(reachable):
                if not here:
                    continue
                end = pos
                while end < length and word[end] == symbol:
                    end += 1
                start = pos + minimum
                if start > end:
                    continue
                for at in range(start, end + 1):
                    nxt[at] = True
        reachable = nxt
        if not any(reachable):
            return False
    return reachable[length]


def _parse_expr(text: str) -> Spec | None:
    parts = _split_ops(text, (" o ", " u "))
    if parts:
        return _combine(parts, OrSpec, _parse_and)
    return _parse_and(text)


def _parse_and(text: str) -> Spec | None:
    parts = _split_ops(text, (" y ", " e "))
    if parts:
        return _combine(parts, AndSpec, _parse_clause)
    return _parse_clause(text)


def _combine(parts: list[str], kind, parse_part) -> Spec | None:
    parsed = [parse_part(part) for part in parts]
    if all(item is not None for item in parsed):
        return kind(tuple(parsed))
    if len(parts) == 2:
        inherited = _inherit(parts[0], parts[1].strip())
        if inherited:
            left = parse_part(parts[0])
            right = parse_part(inherited)
            if left is not None and right is not None:
                return kind((left, right))
    return None


def _parse_clause(text: str) -> Spec | None:
    text = _strip_prefix(text)
    if not text or re.search(r"\b(pero|aunque)\b", text):
        return None
    negated, inner = _peel_negation(text)
    spec = _parse_positive(inner)
    if spec is None:
        return None
    return NotSpec(spec) if negated else spec


def _parse_positive(text: str) -> Spec | None:
    position = _parse_position(text)
    if position is not None:
        return position
    if re.search(r"\b(longitud|largo|cantidad de simbolos|cantidad de caracteres)\b", text):
        return _parse_length(text)
    if re.search(r"\b(cantidad|par de|pares de|impar de|impares de|numero de)\b", text):
        return _parse_count(text)
    number = _parse_number(text)
    if number is not None:
        return number
    return _parse_affix(text)


def _parse_length(text: str) -> LengthSpec | None:
    if re.search(r"\b(?:longitud|largo)\s+par\b", text) or re.search(r"\bcantidad de simbolos par\b", text):
        return LengthSpec(2, 0)
    if re.search(r"\b(?:longitud|largo)\s+impar\b", text):
        return LengthSpec(2, 1)
    match = re.search(r"\b(?:longitud|largo|cantidad de simbolos|cantidad de caracteres)\s+multiplos?\s+de\s+([0-9０-９]+)\b", text)
    if match:
        return LengthSpec(_modulus(match.group(1)), 0)
    match = re.search(
        r"\b(?:longitud|largo)\s+(?:modulo|mod)\s+([0-9０-９]+)\s+(?:resto|igual a)\s+([0-9０-９]+)\b",
        text,
    )
    if match:
        modulus = _modulus(match.group(1))
        return LengthSpec(modulus, _remainder(match.group(2), modulus))
    match = re.search(r"\b(?:longitud|largo)\s+con\s+resto\s+([0-9０-９]+)\s+(?:modulo|mod)\s+([0-9０-９]+)\b", text)
    if match:
        modulus = _modulus(match.group(2))
        return LengthSpec(modulus, _remainder(match.group(1), modulus))
    return None


def _parse_count(text: str) -> CountSpec | None:
    match = re.search(r"\b(?:cantidad|numero)\s+de\s+([0-9a-záéíóúüñ]+)\s+multiplos?\s+de\s+([0-9０-９]+)\b", text)
    if match:
        return _finish_count(match.group(1), _modulus(match.group(2)), 0)
    match = re.search(
        r"\b(?:cantidad|numero)\s+de\s+([0-9a-záéíóúüñ]+)\s+congruentes?\s+con\s+([0-9０-９]+)\s+(?:modulo|mod)\s+([0-9０-９]+)\b",
        text,
    )
    if match:
        modulus = _modulus(match.group(3))
        return _finish_count(match.group(1), modulus, _remainder(match.group(2), modulus))
    match = re.search(
        r"\b(?:cantidad|numero)\s+de\s+([0-9a-záéíóúüñ]+)\s+resto\s+([0-9０-９]+)\s+(?:modulo|mod)\s+([0-9０-９]+)\b",
        text,
    )
    if match:
        modulus = _modulus(match.group(3))
        return _finish_count(match.group(1), modulus, _remainder(match.group(2), modulus))
    match = re.search(
        r"\b(?:cantidad|numero)\s+de\s+([0-9a-záéíóúüñ]+)\s+(?:modulo|mod)\s+([0-9０-９]+)(?:\s+(?:resto|igual a)\s+([0-9０-９]+))?\b",
        text,
    )
    if match:
        modulus = _modulus(match.group(2))
        remainder = 0 if match.group(3) is None else _remainder(match.group(3), modulus)
        return _finish_count(match.group(1), modulus, remainder)
    match = re.search(r"\b(?:cantidad|numero)\s+par\s+de\s+([0-9a-záéíóúüñ]+)\b", text)
    if match:
        return _finish_count(match.group(1), 2, 0)
    match = re.search(r"\b(?:cantidad|numero)\s+impar\s+de\s+([0-9a-záéíóúüñ]+)\b", text)
    if match:
        return _finish_count(match.group(1), 2, 1)
    match = re.search(r"\b(?:cantidad|numero)\s+de\s+([0-9a-záéíóúüñ]+)\s+impares?\b", text)
    if match:
        return _finish_count(match.group(1), 2, 1)
    match = re.search(r"\b(?:cantidad|numero)\s+de\s+([0-9a-záéíóúüñ]+)\s+pares?\b", text)
    if match:
        return _finish_count(match.group(1), 2, 0)
    match = re.search(r"\b(?:impares|impar)\s+de\s+([0-9a-záéíóúüñ]+)\b", text)
    if match:
        return _finish_count(match.group(1), 2, 1)
    match = re.search(r"\b(?:pares|par)\s+de\s+([0-9a-záéíóúüñ]+)\b", text)
    if match:
        return _finish_count(match.group(1), 2, 0)
    match = re.search(r"\b([0-9a-záéíóúüñ])\s+multiplos?\s+de\s+([0-9０-９]+)\b", text)
    if match:
        return _finish_count(match.group(1), _modulus(match.group(2)), 0)
    return _count_outside_latin(text)


def _count_outside_latin(text: str) -> CountSpec | None:
    """«par de а» no es «par de a»: la letra cirílica no entra en la clase latina.

    Solo corre si las reglas de arriba no armaron nada. Una palabra latina
    («él», «aes») no se reinterpreta acá.
    """
    patterns = (
        (r"\b(?:cantidad|numero)\s+par\s+de\s+(\S+)", 2, 0),
        (r"\b(?:cantidad|numero)\s+impar\s+de\s+(\S+)", 2, 1),
        (r"\b(?:pares|par)\s+de\s+(\S+)", 2, 0),
        (r"\b(?:impares|impar)\s+de\s+(\S+)", 2, 1),
    )
    for pattern, modulus, remainder in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        token = unicodedata.normalize("NFC", match.group(1).strip(".,;:"))
        if re.fullmatch(r"[0-9a-záéíóúüñ]+", token):
            continue
        symbol = _symbol_of(token)
        if symbol is None:
            continue
        return CountSpec(symbol=symbol, modulus=modulus, remainder=remainder)
    return None


def _finish_count(token: str, modulus: int, remainder: int) -> CountSpec | None:
    symbol = _symbol_of(token)
    if symbol is None:
        return None
    return CountSpec(symbol=symbol, modulus=modulus, remainder=remainder)


def _parse_number(text: str) -> ValueSpec | None:
    base = _base_mentioned(text)
    match = re.search(r"\bcongruentes?\s+con\s+([0-9０-９]+)\s+(?:modulo|mod)\s+([0-9０-９]+)\b", text)
    if match:
        modulus = _modulus(match.group(2))
        return ValueSpec(base, modulus, _remainder(match.group(1), modulus))
    match = re.search(r"\bresto\s+([0-9０-９]+)\s+(?:modulo|mod)\s+([0-9０-９]+)\b", text)
    if match:
        modulus = _modulus(match.group(2))
        return ValueSpec(base, modulus, _remainder(match.group(1), modulus))
    match = re.search(r"\bresto\s+([0-9０-９]+)\s+al\s+dividir\s+por\s+([0-9０-９]+)\b", text)
    if match:
        modulus = _modulus(match.group(2))
        return ValueSpec(base, modulus, _remainder(match.group(1), modulus))
    match = re.search(r"\bresto\s+al\s+dividir\s+por\s+([0-9０-９]+)\s+es\s+([0-9０-９]+)\b", text)
    if match:
        modulus = _modulus(match.group(1))
        return ValueSpec(base, modulus, _remainder(match.group(2), modulus))
    match = re.search(r"\bal\s+dividir\s+por\s+([0-9０-９]+)\s+(?:el\s+)?resto\s+es\s+([0-9０-９]+)\b", text)
    if match:
        modulus = _modulus(match.group(1))
        return ValueSpec(base, modulus, _remainder(match.group(2), modulus))
    match = re.search(r"\b(?:divisibles?|multiplos?)\s+(?:por|de)\s+([0-9０-９]+)\b", text)
    if match:
        return ValueSpec(base, _modulus(match.group(1)), 0)
    return None


_WORD_ORDINALS = (
    ("decimoprimero", 11),
    ("decimosegundo", 12),
    ("decimotercero", 13),
    ("decimotercer", 13),
    ("primero", 1),
    ("primera", 1),
    ("primer", 1),
    ("segundo", 2),
    ("segunda", 2),
    ("tercero", 3),
    ("tercera", 3),
    ("tercer", 3),
    ("cuarto", 4),
    ("cuarta", 4),
    ("quinto", 5),
    ("quinta", 5),
    ("sexto", 6),
    ("sexta", 6),
    ("septimo", 7),
    ("septima", 7),
    ("octavo", 8),
    ("octava", 8),
    ("noveno", 9),
    ("novena", 9),
    ("decimo", 10),
    ("decima", 10),
    ("undecimo", 11),
    ("duodecimo", 12),
)

_POSITION_NOUN = r"(?:simbolo|caracter|letra|digito|posicion)"
_NOT_A_SYMBOL = {
    "simbolo", "simbolos", "caracter", "caracteres", "letra", "letras", "digito",
    "digitos", "posicion", "posiciones", "final", "principio", "inicio", "fin",
    "ultimo", "penultimo", "antepenultimo", "trasantepenultimo", "desde", "sea",
    "es", "un", "una", "el", "la", "igual", "vale",
}


def _parse_position(text: str) -> Spec | None:
    found = _position_index(text)
    if found is None:
        return None
    k, origin = found
    symbol = _position_symbol(text)
    if symbol is None:
        return None
    spec = PositionSpec(k=_check_position(k, origin), symbol=symbol, origin=origin)
    if re.search(r"\bno\s+(?:sea|es|sean|vale)\b", text):
        return NotSpec(spec)
    return spec


def _position_index(text: str) -> tuple[int, str] | None:
    folded = (
        text.replace("ante-penultimo", "antepenultimo")
        .replace("ante penultimo", "antepenultimo")
        .replace("pen-ultimo", "penultimo")
        .replace("pen ultimo", "penultimo")
        .replace("tras-antepenultimo", "trasantepenultimo")
    )
    for word, index in (
        ("trasantepenultimo", 4),
        ("antepenultimo", 3),
        ("penultimo", 2),
    ):
        if re.search(rf"\b{word}\b", folded):
            return index, "end"
    if re.search(r"\bultimo\b", folded) and (
        re.search(rf"\b{_POSITION_NOUN}\b", folded) or _has_symbol_verb(folded)
    ):
        return 1, "end"
    ordinal = _ordinal_in(folded)
    if ordinal is None:
        return None
    origin = _origin_in(folded)
    if origin is None:
        if not re.search(rf"\b{_POSITION_NOUN}\b", folded):
            return None
        origin = "start"
    return ordinal, origin


def _ordinal_in(text: str) -> int | None:
    found: list[tuple[int, int]] = []
    for word, index in _WORD_ORDINALS:
        match = re.search(rf"\b{word}\b", text)
        if match:
            found.append((match.start(), index))
    # El ° no es letra: un \b detrás no corta, y «2° símbolo» se iba al modelo.
    for match in re.finditer(
        r"\b([0-9０-９]+)\s*(?:-\s*)?(?:esim[oa]\b|er\b|ro\b|do\b|to\b|ta\b|mo\b|ra\b|da\b|[ºª°](?!\w))",
        text,
    ):
        found.append((match.start(), _user_int(match.group(1))))
    for match in re.finditer(rf"\b([0-9０-９]+)\s+{_POSITION_NOUN}\b", text):
        found.append((match.start(), _user_int(match.group(1))))
    if not found:
        return None
    found.sort()
    return found[0][1]


def _origin_in(text: str) -> str | None:
    marks: list[tuple[int, str]] = []
    end = (
        r"desde\s+(?:el\s+|la\s+)?(?:final|fin|atras)|"
        r"por\s+la\s+derecha|"
        r"contando\s+desde\s+(?:el\s+)?(?:final|atras)|"
        r"hacia\s+atras"
    )
    start = (
        r"desde\s+(?:el\s+|la\s+)?(?:principio|inicio|comienzo|adelante)|"
        r"por\s+la\s+izquierda|"
        r"contando\s+desde\s+(?:el\s+)?(?:principio|inicio|comienzo)"
    )
    for match in re.finditer(end, text):
        marks.append((match.start(), "end"))
    for match in re.finditer(start, text):
        marks.append((match.start(), "start"))
    if not marks:
        return None
    marks.sort()
    return marks[-1][1]


def _has_symbol_verb(text: str) -> bool:
    return re.search(r"\b(?:sea|sean|es|vale|igual\s+a)\b", text) is not None


def _position_symbol(text: str) -> str | None:
    patterns = (
        r"\b(?:sea|sean|es|vale)\s+(?:un|una|el|la)?\s*([0-9a-záéíóúüñ]+)\b",
        r"\bigual\s+a\s+(?:un|una|el|la)?\s*([0-9a-záéíóúüñ]+)\b",
        rf"\b{_POSITION_NOUN}\s+([0-9a-záéíóúüñ])\b",
    )
    ordinals = {word for word, _index in _WORD_ORDINALS}
    found: list[tuple[int, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            token = match.group(1)
            if token in _NOT_A_SYMBOL or token in ordinals:
                continue
            symbol = _symbol_of(token)
            if symbol is None:
                continue
            found.append((match.start(), symbol))
    if not found:
        return None
    found.sort()
    return found[-1][1]


def _parse_affix(text: str) -> AffixSpec | None:
    patterns = (
        ("ends", r"\b(?:terminan|termina|terminen|termine|terminar)\s+(?:en|con)\s+([0-9a-záéíóúüñ]+)\b"),
        ("starts", r"\b(?:empiezan|empieza|empezar|comienzan|comienza|comenzar)\s+(?:con|por)\s+([0-9a-záéíóúüñ]+)\b"),
        ("contains", r"\b(?:contienen|contiene|contener|contenga|contengan)\s+(?:la\s+|una\s+)?(?:subcadena|cadena|palabra|factor)\s+([0-9a-záéíóúüñ]+)\b"),
        ("contains", r"\b(?:contienen|contiene|contener|contenga|contengan)\s+([0-9a-záéíóúüñ]+)\b"),
        ("starts", r"\bprefijo\s+([0-9a-záéíóúüñ]+)\b"),
        ("ends", r"\bsufijo\s+([0-9a-záéíóúüñ]+)\b"),
    )
    for mode, pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        word = match.group(1)
        if word in _STOP or len(word) > MAX_WORD:
            continue
        return AffixSpec(mode=mode, word=word)
    return None


def _peel_negation(text: str) -> tuple[bool, str]:
    match = re.match(r"^(?:que\s+)?no\s+(?:sean\s+|sea\s+|son\s+|es\s+|se\s+)?(.+)$", text)
    if match:
        return True, _strip_prefix(match.group(1))
    match = re.match(r"^(.+?)\s+que\s+no\s+(?:sean\s+|sea\s+|son\s+|es\s+)?(.+)$", text)
    if match:
        return True, _strip_prefix(f"{match.group(1)} {match.group(2)}")
    return False, text


def _inherit(left: str, right: str) -> str | None:
    if re.fullmatch(r"[0-9０-９]+", right):
        return _replace_last_number(left, right)
    match = re.fullmatch(r"(?:por|de)\s+([0-9０-９]+)", right)
    if match:
        return _replace_last_number(left, match.group(1))
    match = re.fullmatch(r"(?:en|con|por)\s+([0-9a-záéíóúüñ]+)", right)
    if match and re.search(r"\b(?:en|con|por)\s+[0-9a-záéíóúüñ]+\s*$", left):
        return re.sub(r"\b(?:en|con|por)\s+[0-9a-záéíóúüñ]+\s*$", right, left)
    match = re.fullmatch(r"de\s+([0-9a-záéíóúüñ]+)", right)
    if match and re.search(r"\bde\s+[0-9a-záéíóúüñ]+\s*$", left):
        return re.sub(r"\bde\s+[0-9a-záéíóúüñ]+\s*$", right, left)
    return None


def _replace_last_number(text: str, number: str) -> str | None:
    if not re.search(r"[0-9０-９]", text):
        return None
    return re.sub(r"[0-9０-９]+(?!.*[0-9０-９])", number, text, count=1)


def _split_ops(text: str, separators: tuple[str, ...]) -> list[str] | None:
    pattern = "|".join(re.escape(item) for item in separators)
    parts = [part.strip() for part in re.split(pattern, text) if part.strip()]
    if len(parts) < 2:
        return None
    return parts


def _strip_prefix(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        match = _PREFIX.match(text)
        if match is None:
            break
        word = match.group(1)
        rest = text[match.end() :].strip()
        # «un 0» y «una a» son una repetición, no el artículo del enunciado.
        if word in {"un", "una", "uno"} and _starts_with_symbol(rest):
            break
        text = rest
    return text


def _starts_with_symbol(text: str) -> bool:
    match = re.match(r"[0-9a-záéíóúüñ]+", text)
    if match is None:
        return False
    token = match.group(0)
    if symbol_name(token):
        return True
    return len(token) == 1 and token.isalnum()


def _take_alphabet(text: str) -> tuple[str, tuple[str, ...] | None]:
    match = re.search(r"\{([^{}]+)\}", text)
    if not match:
        return text, None
    parts = [part for part in re.split(r"[\s,]+", match.group(1).strip()) if part]
    if not parts or any(len(part) != 1 for part in parts):
        return text, None
    symbols = tuple(dict.fromkeys(parts))
    text = f"{text[:match.start()]} {text[match.end():]}"
    text = re.sub(r"\s+", " ", text).strip()
    return text, symbols


def _normalize(text: str) -> str:
    # NFC primero: «e» + acento es «é», un símbolo. Las palabras de la prosa
    # (tres letras o más) pierden el acento para matchear; un símbolo de una
    # o dos letras, y lo que está entre llaves, se queda.
    # El invisible se saca antes, para que «0» + ancho cero + «1» siga siendo 01.
    # La marca pegada al ? se saca antes del NFC, para que no se coma la s.
    text = strip_marks_before_question(strip_invisibles(text.strip()))
    text = unicodedata.normalize("NFC", text.lower())
    text = _map_outside_braces(text, _drop_question_marks)
    text = _fold_prose(text)
    return re.sub(r"\s+", " ", text).strip()


def _drop_question_marks(part: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(part):
        if part[index] in {"?", "？", "¿", "¡"}:
            index += 1
            while index < len(part) and unicodedata.category(part[index]) == "Mn":
                index += 1
            out.append(" ")
            continue
        out.append(part[index])
        index += 1
    return "".join(out)


def _map_outside_braces(text: str, fn) -> str:
    pieces = re.split(r"(\{[^{}]*\})", text)
    return "".join(piece if piece.startswith("{") else fn(piece) for piece in pieces)


def _reject_glued_negative(text: str) -> None:
    """«-3 ceros» no es tres ceros. El menos pegado al número no se tira."""
    for match in _GLUED_NEGATIVE.finditer(text):
        token = match.group(2)
        if symbol_name(token) or (len(token) == 1 and token.isalnum()):
            raise _Invalid(
                "La repetición no puede ser negativa. "
                "Para cero o más, usá «infinitos» o «cero o más»."
            )


def _fold_prose(text: str) -> str:
    pieces = re.split(r"(\{[^{}]*\})", text)
    return "".join(piece if piece.startswith("{") else _fold_words(piece) for piece in pieces)


def _fold_words(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        word = match.group(0)
        if len(word) < 3:
            return word
        return word.translate(_ACCENTS)

    return re.sub(r"[0-9a-záéíóúüñ]+", repl, text)


def _regexish(text: str) -> bool:
    """La misma noción que el reintento del modelo: bb? es expresión, «unos?» no."""
    from app.service import _looks_like_regex_request

    return _looks_like_regex_request(text)


def _base_mentioned(text: str) -> int | None:
    match = re.search(r"\bbase\s+([0-9０-９]+)\b", text)
    if match:
        return _user_int(match.group(1))
    if re.search(r"\bbinari", text):
        return 2
    if re.search(r"\bdecim", text):
        return 10
    return None


def _complete_base(symbols: tuple[str, ...]) -> int | None:
    for base in range(2, 37):
        digits = _digits(base)
        if len(symbols) == base and set(symbols) == set(digits):
            return base
    return None


def _digit_tuple(base: int) -> tuple[str, ...]:
    symbols = []
    for index in range(base):
        if index < 10:
            symbols.append(str(index))
        else:
            symbols.append(chr(ord("a") + index - 10))
    return tuple(symbols)


# Bases 2 a 36. Se arma una vez: formatear un número no vuelve a recorrer los dígitos.
_DIGITS = tuple(_digit_tuple(base) for base in range(37))


def _digits(base: int) -> tuple[str, ...]:
    if 2 <= base <= 36:
        return _DIGITS[base]
    return _digit_tuple(base)


def _digit_value(symbol: str) -> int:
    # ¹ es dígito pero int() lo rechaza. Los decimales sí entran.
    if symbol.isdecimal():
        return int(symbol)
    return ord(symbol) - ord("a") + 10


def _format_number(number: int, base: int) -> str:
    if number == 0:
        return "0"
    digits = _digits(base)
    rendered = []
    while number:
        rendered.append(digits[number % base])
        number //= base
    return "".join(reversed(rendered))


def _shown_int(number: int) -> str:
    text = str(number)
    if len(text) <= 12:
        return text
    return text[:12] + "…"


def _user_int(value) -> int:
    """Entero de un enunciado o de un bloque. No llama a int() con miles de dígitos."""
    text = str(value).strip()
    sign = 1
    if text.startswith("+"):
        text = text[1:]
    elif text.startswith("-"):
        sign = -1
        text = text[1:]
    if not text.isdigit():
        shown = text if len(text) <= 12 else text[:12] + "…"
        raise _Invalid(f"No entiendo el número «{shown}».")
    # int("٢") es 2 e int("３") es 3. El ancho completo sí es el dígito;
    # el arábigo-índico no se pliega, igual que no se pliega dentro de {}.
    if any(not char.isascii() and char not in "０１２３４５６７８９" for char in text):
        shown = text if len(text) <= 12 else text[:12] + "…"
        raise _Invalid(f"No entiendo el número «{shown}».")
    # int() de más de ~4300 dígitos tira ValueError. Un módulo de 80 nueves
    # sigue siendo un entero de verdad, para que el mensaje lo corte con «…».
    if len(text) > 1000:
        raise _Invalid(f"El número {text[:12]}… es demasiado grande.")
    return sign * int(text)


def _modulus(value) -> int:
    number = _user_int(value)
    if number < 1:
        raise _Invalid("El módulo tiene que ser un entero mayor que 0.")
    if number > MAX_MODULUS:
        raise _Invalid(f"El módulo {_shown_int(number)} es demasiado grande. El tope es {MAX_MODULUS}.")
    return number


def _remainder(value, modulus: int) -> int:
    number = _user_int(value)
    if number < 0 or number >= modulus:
        raise _Invalid(
            f"El resto {_shown_int(number)} tiene que estar entre 0 y {modulus - 1}."
        )
    return number


def _check_base(base: int) -> int:
    if base < 2 or base > 36:
        raise _Invalid("La base tiene que estar entre 2 y 36.")
    return base


def _symbol_of(token: str) -> str | None:
    named = symbol_name(token)
    if named:
        return named
    if len(token) == 1 and token.isalnum():
        return token
    return None


def _mentioned_symbols(spec: Spec) -> set[str]:
    if isinstance(spec, CountSpec):
        return {spec.symbol}
    if isinstance(spec, AffixSpec):
        return set(spec.word)
    if isinstance(spec, PositionSpec):
        return {spec.symbol}
    if isinstance(spec, SequenceSpec):
        return {block.symbol for block in spec.blocks}
    if isinstance(spec, NotSpec):
        return _mentioned_symbols(spec.inner)
    if isinstance(spec, (AndSpec, OrSpec)):
        found: set[str] = set()
        for part in spec.parts:
            found |= _mentioned_symbols(part)
        return found
    return set()


def _walk(spec: Spec):
    yield spec
    if isinstance(spec, NotSpec):
        yield from _walk(spec.inner)
    elif isinstance(spec, (AndSpec, OrSpec)):
        for part in spec.parts:
            yield from _walk(part)


def sounds_like_family(text: str) -> bool:
    if _regexish(text):
        return False
    normalized = _normalize(text)
    return re.search(
        r"divisib|multipl|modulo|congruen|\bresto\b|par de|cantidad de|longitud|termina|empieza|contiene|contenga|"
        r"antepenultimo|penultimo|\bultimo\b|esim[oa]|desde el final|desde el principio|"
        r"infinit|cualquier cantidad|cero o mas|uno o mas",
        normalized,
    ) is not None
