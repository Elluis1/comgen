import re
import unicodedata
from dataclasses import dataclass, field

from app.sanitize import (
    fold_fullwidth_digits,
    fold_fullwidth_question,
    is_control_or_invisible,
    strip_invisibles,
    strip_marks_before_question,
)
from app.schemas import FiniteAutomaton, State, Transition
from app.validate import prepare_fa, validate_fa

_QUANTIFIERS = {"*", "+", "?"}
_ATOM_STOP = {"*", "+", "?", "|", ")"}
_QUANT_SUFFIX = {"one": "", "star": "*", "plus": "+", "opt": "?"}
_ORDINALS = {1: "primera", 2: "segunda", 3: "tercera", 4: "cuarta", 5: "quinta"}
_COUNT_WORDS = {2: "dos", 3: "tres", 4: "cuatro", 5: "cinco"}
_EDIT = re.compile(
    r"\b(modific\w*|cambi\w*|agreg\w*|quit\w*|sac[aá]\w*|correg\w*|renombr\w*|hac[eé]\w*)\b",
    re.IGNORECASE,
)
_STRUCTURE = re.compile(
    r"\b(comience|empiece|arranque|inicie|siga|seguid\w*|luego|despu[eé]s|termine|acab\w*)\b",
    re.IGNORECASE,
)
_FILLER = {
    "quiero", "que", "me", "des", "un", "una", "afd", "afn", "dfa", "nfa",
    "automata", "autómata", "finito", "finitos", "determinista", "determinístico",
    "la", "el", "de", "del", "expresion", "expresión", "regular", "patron", "patrón",
    "lenguaje", "para", "por", "favor", "cadenas", "cadena", "genere", "genera",
    "generar", "armar", "arma", "dame", "sobre", "reconozca", "reconoce", "acepte",
}
# Palabras cortas de una oración. No son literales de una expresión escrita con espacios.
_SHORT_PROSE = {
    "al", "con", "en", "es", "ha", "he", "lo", "mi", "no", "o", "ok", "se",
    "si", "sí", "sin", "su", "sus", "tu", "u", "y", "ya", "yo",
}
# El AFN de posiciones puede crecer como 2^n antes de minimizar. Pasado este
# tamaño el pedido no termina en un tiempo razonable.
_MAX_SUBSETS = 512
# Cada paréntesis abre un llamado. Pasado este tope se rechaza antes de
# agotar la pila de Python.
_MAX_NESTING = 64


class RegexError(Exception):
    pass


@dataclass
class Meta:
    pos: int
    symbol: str
    kind: str = "one"
    index_in_run: int = 1
    run_length: int = 1
    run_pattern: str = ""


@dataclass
class Sym:
    symbol: str
    pos: int


@dataclass
class Concat:
    parts: list = field(default_factory=list)


@dataclass
class Union:
    parts: list = field(default_factory=list)


@dataclass
class Repeat:
    inner: object
    kind: str


@dataclass
class _Info:
    nullable: bool
    first: set[int]
    last: set[int]


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.depth = 0
        self.metas: dict[int, Meta] = {}

    def parse(self) -> object:
        if not self.text:
            raise RegexError("La expresión está vacía.")
        problems = pattern_problems(self.text)
        if problems:
            raise RegexError(" ".join(problems))
        node = self._expr()
        if self.i != len(self.text):
            raise RegexError(f"No entendí «{self.text[self.i:]}» en la expresión.")
        return node

    def _peek(self) -> str:
        if self.i >= len(self.text):
            return ""
        return self.text[self.i]

    def _expr(self) -> object:
        parts = [self._term()]
        while self._peek() == "|":
            self.i += 1
            if not self._peek():
                raise RegexError("Falta algo después de |.")
            parts.append(self._term())
        if len(parts) == 1:
            return parts[0]
        return Union(parts)

    def _term(self) -> object:
        parts = []
        while self._peek() and self._peek() not in ")|":
            parts.append(self._factor())
        if not parts:
            raise RegexError("Falta un símbolo en la expresión.")
        if len(parts) == 1:
            return parts[0]
        return Concat(parts)

    def _factor(self) -> object:
        node = self._atom()
        quantifier = self._peek()
        if quantifier not in _QUANTIFIERS:
            return node
        self.i += 1
        if self._peek() in _QUANTIFIERS:
            raise RegexError("No se pueden aplicar dos cuantificadores seguidos.")
        kind = {"*": "star", "+": "plus", "?": "opt"}[quantifier]
        if isinstance(node, Sym):
            self.metas[node.pos].kind = kind
        return Repeat(node, kind)

    def _atom(self) -> object:
        current = self._peek()
        if current == "(":
            self.depth += 1
            if self.depth > _MAX_NESTING:
                raise RegexError(
                    f"La expresión anida más de {_MAX_NESTING} paréntesis y no se puede compilar."
                )
            self.i += 1
            node = self._expr()
            if self._peek() != ")":
                raise RegexError("Falta cerrar un paréntesis.")
            self.i += 1
            self.depth -= 1
            return node
        if current in _ATOM_STOP:
            raise RegexError(f"«{current}» está fuera de lugar.")
        if not current:
            raise RegexError("La expresión está incompleta.")
        self.i += 1
        pos = len(self.metas) + 1
        self.metas[pos] = Meta(pos=pos, symbol=current, run_pattern=current)
        return Sym(current, pos)


_REGEX_SYNTAX = set("*+?|()")


def pattern_literals(text: str) -> list[str]:
    """Símbolos que la expresión usaría, aunque después no se pueda compilar."""
    literals: list[str] = []
    for char in _compact(text):
        if char in _REGEX_SYNTAX or char in literals:
            continue
        literals.append(char)
    return literals


def pattern_problems(text: str) -> list[str]:
    """Rechaza controles y una barra invertida. Este dialecto no usa escapes."""
    compact = _compact(text)
    if not compact:
        return []
    problems: list[str] = []
    if any(is_control_or_invisible(char) for char in compact):
        problems.append(
            "La expresión tiene un carácter de control o invisible y no se puede compilar."
        )
    if "\\" in compact:
        if compact.endswith("\\"):
            problems.append(
                "La expresión termina con una barra invertida suelta y no se puede compilar."
            )
        else:
            problems.append(
                "La expresión tiene una barra invertida mal puesta y no se puede compilar."
            )
    if "{" in compact or "}" in compact:
        problems.append(
            "La expresión usa llaves y no se puede compilar: este lenguaje no tiene repeticiones {n}."
        )
    if "[" in compact or "]" in compact:
        problems.append(
            "La expresión usa corchetes y no se puede compilar: este lenguaje no tiene clases de caracteres."
        )
    return problems


def compile_pattern(pattern: str) -> tuple[FiniteAutomaton, str]:
    compact = _compact(pattern)
    parser = _Parser(compact)
    try:
        root = parser.parse()
    except RecursionError as exc:
        raise RegexError(
            "La expresión está anidada demasiado y no se puede compilar."
        ) from exc
    _mark_runs(root, parser.metas)
    for meta in parser.metas.values():
        if meta.run_length == 1 and meta.run_pattern == meta.symbol:
            meta.run_pattern = meta.symbol + _QUANT_SUFFIX[meta.kind]
    follow: dict[int, set[int]] = {}
    info = _analyze(root, follow)
    automaton, explanation = _to_dfa(compact, parser.metas, info, follow)
    prepared, _notes = prepare_fa(automaton)
    check = validate_fa(prepared)
    if check.errors:
        raise RegexError(" ".join(check.errors))
    return prepared, explanation


def extract_regex(text: str) -> str | None:
    if _EDIT.search(text):
        return None
    normalized = fold_fullwidth_question(fold_fullwidth_digits(text))
    normalized = strip_marks_before_question(strip_invisibles(normalized))
    normalized = normalized.replace("∗", "*").replace("⋆", "*").replace("¿", "").replace("¡", "")
    normalized = re.sub(r"\s+([*+?])", r"\1", normalized)
    # «unos?» es una pregunta. «a?» y «01?» siguen siendo cuantificadores.
    normalized = re.sub(
        r"\b([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,})\?",
        r"\1",
        normalized,
    )
    words = [word.strip(".,;:") for word in re.findall(r"[A-Za-z0-9ε()*+?|]+", normalized)]
    words = [word for word in words if word]
    candidates = [word for word in words if _is_regex_token(word) and _parses(word)]
    if len(candidates) >= 2 and _STRUCTURE.search(normalized):
        pattern = "".join(candidates)
        if _parses(pattern):
            return pattern
        return None
    if len(candidates) == 1:
        token = candidates[0]
        others = [word for word in words if word != token and word.casefold() not in _FILLER]
        if not others:
            return token
    if _is_spaced_regex(normalized):
        compact = _compact(normalized)
        if _is_regex_token(compact) and _parses(compact):
            return compact
    return None


def pattern_in_field(text: str) -> str:
    stripped = text.strip().strip("`")
    if not stripped or re.search(r"\b(el|la|los|las|que|con|por|una|cadenas|empieza|termina|verifica)\b", stripped, re.IGNORECASE):
        return ""
    compact = _compact(stripped)
    if _is_regex_token(compact) and _parses(compact):
        return compact
    return ""


def _compact(pattern: str) -> str:
    text = unicodedata.normalize("NFC", pattern.replace("∗", "*").replace("⋆", "*"))
    return re.sub(r"\s+", "", text)


def _is_regex_token(token: str) -> bool:
    return bool(re.search(r"[*+?|()|]", token))


def _parses(pattern: str) -> bool:
    try:
        _Parser(_compact(pattern)).parse()
        return True
    except RegexError:
        return False


def _is_spaced_regex(text: str) -> bool:
    """True solo si el texto es una expresión escrita con espacios, no una oración."""
    pieces = [piece.strip(".,;:") for piece in text.strip().split()]
    pieces = [piece for piece in pieces if piece]
    if not pieces or not any(_is_regex_token(piece) for piece in pieces):
        return False
    for piece in pieces:
        folded = piece.casefold()
        if folded in _FILLER or folded in _SHORT_PROSE:
            return False
        if re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}", piece):
            return False
        if re.fullmatch(r"[A-Za-z0-9ε()*+?|.]+", piece) is None:
            return False
    return True


def _mark_runs(node: object, metas: dict[int, Meta]) -> None:
    if isinstance(node, Concat):
        buffer: list[Meta] = []

        def flush() -> None:
            _assign_runs(buffer)
            buffer.clear()

        for part in node.parts:
            leaf = _leaf_meta(part, metas)
            if leaf is None:
                flush()
                _mark_runs(part, metas)
            else:
                buffer.append(leaf)
        flush()
        return
    if isinstance(node, Union):
        for part in node.parts:
            _mark_runs(part, metas)
        return
    if isinstance(node, Repeat):
        _mark_runs(node.inner, metas)


def _leaf_meta(node: object, metas: dict[int, Meta]) -> Meta | None:
    if isinstance(node, Sym):
        return metas[node.pos]
    if isinstance(node, Repeat) and isinstance(node.inner, Sym):
        return metas[node.inner.pos]
    return None


def _assign_runs(buffer: list[Meta]) -> None:
    index = 0
    while index < len(buffer):
        end = index + 1
        while end < len(buffer) and buffer[end].symbol == buffer[index].symbol:
            end += 1
        run = buffer[index:end]
        pattern = "".join(item.symbol + _QUANT_SUFFIX[item.kind] for item in run)
        for number, item in enumerate(run, start=1):
            item.index_in_run = number
            item.run_length = len(run)
            item.run_pattern = pattern
        index = end


def _analyze(node: object, follow: dict[int, set[int]]) -> _Info:
    if isinstance(node, Sym):
        follow.setdefault(node.pos, set())
        return _Info(False, {node.pos}, {node.pos})
    if isinstance(node, Concat):
        infos = [_analyze(part, follow) for part in node.parts]
        nullable = all(item.nullable for item in infos)
        first: set[int] = set()
        for item in infos:
            first |= item.first
            if not item.nullable:
                break
        last: set[int] = set()
        for item in reversed(infos):
            last |= item.last
            if not item.nullable:
                break
        for index, item in enumerate(infos):
            upcoming: set[int] = set()
            for later in infos[index + 1 :]:
                upcoming |= later.first
                if not later.nullable:
                    break
            for pos in item.last:
                follow[pos] |= upcoming
        return _Info(nullable, first, last)
    if isinstance(node, Union):
        infos = [_analyze(part, follow) for part in node.parts]
        return _Info(
            any(item.nullable for item in infos),
            set().union(*(item.first for item in infos)),
            set().union(*(item.last for item in infos)),
        )
    if isinstance(node, Repeat):
        info = _analyze(node.inner, follow)
        if node.kind == "opt":
            return _Info(True, set(info.first), set(info.last))
        for pos in info.last:
            follow[pos] |= info.first
        # E+ contiene la cadena vacía cuando E la contiene: alcanza una copia.
        nullable = info.nullable if node.kind == "plus" else True
        return _Info(nullable, set(info.first), set(info.last))
    raise RegexError("No pude analizar la expresión.")


def _to_dfa(
    pattern: str,
    metas: dict[int, Meta],
    info: _Info,
    follow: dict[int, set[int]],
) -> tuple[FiniteAutomaton, str]:
    alphabet: list[str] = []
    for pos in sorted(metas):
        symbol = metas[pos].symbol
        if symbol not in alphabet:
            alphabet.append(symbol)

    nfa: dict[int, dict[str, set[int]]] = {}

    def add(source: int, symbol: str, target: int) -> None:
        nfa.setdefault(source, {}).setdefault(symbol, set()).add(target)

    for pos in info.first:
        add(0, metas[pos].symbol, pos)
    for source, targets in follow.items():
        for target in targets:
            add(source, metas[target].symbol, target)

    finals = set(info.last)
    if info.nullable:
        finals.add(0)

    start = frozenset({0})
    delta: dict[frozenset[int], dict[str, frozenset[int]]] = {}
    queued = {start}
    pending = [start]
    while pending:
        current = pending.pop(0)
        delta[current] = {}
        for symbol in alphabet:
            nxt: set[int] = set()
            for state in current:
                nxt |= nfa.get(state, {}).get(symbol, set())
            target = frozenset(nxt)
            delta[current][symbol] = target
            if target not in queued:
                if len(queued) >= _MAX_SUBSETS:
                    raise RegexError(
                        f"La expresión genera demasiados estados (más de {_MAX_SUBSETS}). "
                        "Simplificala o partila en bloques más chicos."
                    )
                queued.add(target)
                pending.append(target)

    groups = _minimize(delta, finals, alphabet)
    index_of = {state: index for index, group in enumerate(groups) for state in group}
    names, ordered = _name_groups(groups, index_of, start, delta, alphabet)
    ordered = _present(ordered, names)
    explanation = _explain(pattern, metas, groups, names, ordered, finals)
    states: list[State] = []
    transitions: list[Transition] = []
    for group_index in ordered:
        representative = next(iter(groups[group_index]))
        states.append(
            State(
                id=names[group_index],
                initial=group_index == index_of[start],
                final=any(subset & finals for subset in groups[group_index]),
            )
        )
        for symbol in alphabet:
            target = index_of[delta[representative][symbol]]
            transitions.append(
                Transition(from_state=names[group_index], to=names[target], read=symbol)
            )
    automaton = FiniteAutomaton(
        deterministic=True,
        alphabet=alphabet,
        states=states,
        transitions=transitions,
        description=f"Expresión {pattern}",
    )
    return automaton, explanation


def _minimize(
    delta: dict[frozenset[int], dict[str, frozenset[int]]],
    finals: set[int],
    alphabet: list[str],
) -> list[set[frozenset[int]]]:
    """Parte el AFD de la expresión. La partición es la de la materia.

    El recorrido es el de Hopcroft: solo se vuelve a mirar el bloque que se
    separó. El de antes, en cada vuelta, buscaba el bloque de cada destino
    recorriendo la lista entera. Con unos cientos de símbolos seguidos eso
    dejaba la compilación en más de medio segundo.
    """
    accept = {state for state in delta if state & finals}
    reject = {state for state in delta if state not in accept}
    blocks = [group for group in (accept, reject) if group]
    if not blocks:
        return []
    block_of: dict[frozenset[int], int] = {}
    for index, block in enumerate(blocks):
        for state in block:
            block_of[state] = index

    incoming: dict[tuple[str, frozenset[int]], list[frozenset[int]]] = {}
    for state, moves in delta.items():
        for symbol in alphabet:
            incoming.setdefault((symbol, moves[symbol]), []).append(state)

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
            touched: dict[int, list[frozenset[int]]] = {}
            for target in splitter:
                for source in incoming.get((symbol, target), ()):
                    touched.setdefault(block_of[source], []).append(source)
            for block_index, sources in touched.items():
                block = blocks[block_index]
                move = set(sources)
                if len(move) == len(block):
                    continue
                stay = block - move
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


def _name_groups(
    groups: list[set[frozenset[int]]],
    index_of: dict[frozenset[int], int],
    start: frozenset[int],
    delta: dict[frozenset[int], dict[str, frozenset[int]]],
    alphabet: list[str],
) -> tuple[dict[int, str], list[int]]:
    start_index = index_of[start]
    ordered: list[int] = []
    seen: set[int] = set()
    pending = [start_index]
    while pending:
        group_index = pending.pop(0)
        if group_index in seen:
            continue
        seen.add(group_index)
        ordered.append(group_index)
        representative = next(iter(groups[group_index]))
        for symbol in alphabet:
            target = index_of[delta[representative][symbol]]
            if target not in seen:
                pending.append(target)
    names: dict[int, str] = {}
    counter = 0
    for group_index in ordered:
        sink = all(len(subset) == 0 for subset in groups[group_index])
        if sink and group_index != start_index:
            names[group_index] = "qh"
            continue
        names[group_index] = f"q{counter}"
        counter += 1
    return names, ordered


def _present(ordered: list[int], names: dict[int, str]) -> list[int]:
    def key(group_index: int) -> tuple[int, int]:
        name = names[group_index]
        if name == "qh":
            return (1, 0)
        return (0, int(name[1:]))

    return sorted(ordered, key=key)


def _explain(
    pattern: str,
    metas: dict[int, Meta],
    groups: list[set[frozenset[int]]],
    names: dict[int, str],
    ordered: list[int],
    finals: set[int],
) -> str:
    pos_states: dict[int, list[str]] = {}
    blurbs: list[tuple[str, str]] = []
    for group_index in ordered:
        positions: list[int] = []
        for subset in groups[group_index]:
            for pos in sorted(subset):
                if pos > 0 and pos not in positions:
                    positions.append(pos)
                if pos > 0:
                    pos_states.setdefault(pos, [])
                    if names[group_index] not in pos_states[pos]:
                        pos_states[pos].append(names[group_index])
        sink = all(len(subset) == 0 for subset in groups[group_index])
        is_final = any(subset & finals for subset in groups[group_index])
        blurbs.append((names[group_index], _blurb(positions, metas, is_final, sink)))

    lines = [
        f"Expresión {pattern}.",
        "Cada símbolo obligatorio antes de una estrella tiene su propio estado de verificación. "
        "El bucle de la estrella queda en el último de esos estados.",
    ]
    seen_runs: set[str] = set()
    ordered_metas = [metas[pos] for pos in sorted(metas)]
    index = 0
    while index < len(ordered_metas):
        meta = ordered_metas[index]
        end = index + 1
        while end < len(ordered_metas) and ordered_metas[end].run_pattern == meta.run_pattern and ordered_metas[end].symbol == meta.symbol:
            end += 1
        run = ordered_metas[index:end]
        index = end
        if meta.run_pattern in seen_runs or meta.run_length < 2:
            continue
        seen_runs.add(meta.run_pattern)
        state_names: list[str] = []
        for item in run:
            for name in pos_states.get(item.pos, []):
                if name not in state_names and name != "qh":
                    state_names.append(name)
        if len(state_names) >= 2:
            word = _COUNT_WORDS.get(len(state_names), str(len(state_names)))
            joined = " y ".join(state_names) if len(state_names) == 2 else ", ".join(state_names)
            lines.append(
                f"{meta.run_pattern} usa {word} estados de verificación para {meta.symbol}: {joined}."
            )
    lines.append("")
    for name, blurb in blurbs:
        lines.append(f"{name}: {blurb}")
    return "\n".join(lines)


def _blurb(positions: list[int], metas: dict[int, Meta], is_final: bool, sink: bool) -> str:
    if sink:
        return "Pozo. Lo que se sale del patrón cae acá y la cadena se rechaza."
    if not positions:
        return "Estado inicial. Todavía no se leyó ningún símbolo."
    chunks: list[str] = []
    for pos in positions:
        text = _phrase(metas[pos])
        if text not in chunks:
            chunks.append(text)
    sentence = _join(chunks)
    if is_final:
        sentence += ". Es estado final."
    else:
        sentence += "."
    return sentence[0].upper() + sentence[1:]


def _phrase(meta: Meta) -> str:
    ordinal = _ORDINALS.get(meta.index_in_run, f"{meta.index_in_run}ª")
    if meta.kind == "one" and meta.run_length == 1:
        return f"lee la {meta.symbol}"
    if meta.kind == "one":
        return f"verifica la {ordinal} {meta.symbol} de {meta.run_pattern}"
    if meta.kind == "star" and meta.index_in_run == 1:
        return f"lee las {meta.symbol} de {meta.run_pattern}; puede no haber ninguna"
    if meta.kind == "star":
        return f"lee las {meta.symbol} de más de {meta.run_pattern}"
    if meta.kind == "plus":
        return f"lee las {meta.symbol} de {meta.run_pattern}"
    return f"lee la {meta.symbol} opcional de {meta.run_pattern}"


def _join(chunks: list[str]) -> str:
    if len(chunks) == 1:
        return chunks[0]
    return ", ".join(chunks[:-1]) + " y " + chunks[-1]
