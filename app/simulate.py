import unicodedata
from dataclasses import dataclass, field

from app.sanitize import is_epsilon_symbol
from app.schemas import FiniteAutomaton

# Una cadena más larga no aporta en la materia y hace lenta la simulación de un AFN.
MAX_WORD_LENGTH = 500
# Mismo orden que la minimización: un autómata más grande no se simula.
MAX_SIMULATION_STATES = 8192


def word_too_long_message() -> str:
    return (
        f"La cadena tiene más de {MAX_WORD_LENGTH} símbolos. "
        "Probá con una más corta."
    )


@dataclass
class Step:
    symbol: str
    states: list[str]


@dataclass
class Simulation:
    ok: bool
    accepted: bool
    steps: list[Step] = field(default_factory=list)
    message: str = ""

    def dump(self) -> dict:
        return {
            "ok": self.ok,
            "accepted": self.accepted,
            "message": self.message,
            "steps": [{"symbol": step.symbol, "states": step.states} for step in self.steps],
        }


def _nfc(value: str) -> str:
    # El NFC de un texto ASCII es el mismo texto. Normalizarlo igual es caro
    # cuando se recorren miles de flechas.
    if value.isascii():
        return value
    return unicodedata.normalize("NFC", value)


def _hangul_kind(char: str) -> str:
    """L, V o T si el jamo entra en la sílaba del NFC. El jamo de compatibilidad no."""
    code = ord(char)
    if 0x1100 <= code <= 0x1112:
        return "L"
    if 0x1161 <= code <= 0x1175:
        return "V"
    if 0x11A8 <= code <= 0x11C2:
        return "T"
    return ""


def _mark_kept(char: str, alphabet: set[str]) -> bool:
    return unicodedata.category(char) == "Mn" and _nfc(char) in alphabet


def _jamo_kept(char: str, alphabet: set[str]) -> bool:
    return bool(_hangul_kind(char)) and _nfc(char) in alphabet


def _hangul_syllable(chars: list[str], index: int, alphabet: set[str]) -> tuple[str, int] | None:
    """L+V(+T) que no son símbolos se leen como la sílaba, igual que «e» + acento."""
    if index + 1 >= len(chars):
        return None
    lead, vowel = chars[index], chars[index + 1]
    if _hangul_kind(lead) != "L" or _hangul_kind(vowel) != "V":
        return None
    if _nfc(lead) in alphabet or _nfc(vowel) in alphabet:
        return None
    end = index + 2
    if end < len(chars):
        trail = chars[end]
        if _hangul_kind(trail) == "T" and _nfc(trail) not in alphabet:
            end += 1
    return _nfc("".join(chars[index:end])), end - index


def _word_symbols(word: str, alphabet: set[str]) -> list[str]:
    """Parte la palabra en símbolos, sin fundir una pieza que el alfabeto nombra.

    Si ninguna marca ni ningún jamo del texto está en el alfabeto, se normaliza
    toda la palabra: «e» + acento sigue siendo «é», y ᄀ + ᅡ es 가. Si la pieza
    es un símbolo, queda aparte y no se la traga la sílaba ni la letra de atrás.
    """
    # Una cadena ASCII no tiene marcas ni jamo, y el NFC no la cambia.
    if word.isascii():
        return list(word)
    chars = list(word)
    if not any(_mark_kept(char, alphabet) or _jamo_kept(char, alphabet) for char in chars):
        return list(_nfc(word))
    symbols: list[str] = []
    index = 0
    while index < len(chars):
        char = chars[index]
        if _mark_kept(char, alphabet) or _jamo_kept(char, alphabet):
            symbols.append(_nfc(char))
            index += 1
            continue
        taken = _hangul_syllable(chars, index, alphabet) if _hangul_kind(char) == "L" else None
        if taken is not None:
            text, consumed = taken
            symbols.append(text)
            index += consumed
            continue
        cluster = [char]
        index += 1
        while index < len(chars):
            nxt = chars[index]
            if unicodedata.category(nxt) != "Mn" or _mark_kept(nxt, alphabet):
                break
            cluster.append(nxt)
            index += 1
        symbols.append(_nfc("".join(cluster)))
    return symbols


def _read(symbol: str) -> str:
    # Un carácter ASCII no es ε, λ ni la palabra «epsilon».
    if len(symbol) == 1 and symbol.isascii():
        return symbol
    cleaned = _nfc(symbol)
    if cleaned == "" or is_epsilon_symbol(cleaned):
        return ""
    return cleaned


def _plain_edge(from_state: str, to_state: str, read: str) -> bool:
    """True si la flecha no necesita NFC ni el reconocimiento de épsilon."""
    return (
        from_state.isascii()
        and to_state.isascii()
        and (read == "" or (len(read) == 1 and read.isascii()))
    )


class Simulator:
    """Índice de flechas para correr varias cadenas sobre el mismo autómata.

    El control de una familia prueba cientos de palabras. Rearmar el índice
    y normalizar cada flecha en cada una dejaba ese control en más de una
    décima, aunque la cadena fuera de unos pocos símbolos. El índice se arma
    en la primera palabra que de verdad se corre.
    """

    def __init__(self, automaton: FiniteAutomaton) -> None:
        self._automaton = automaton
        self._ready = False
        self._blocked: str | None = None
        if len(automaton.states) > MAX_SIMULATION_STATES:
            self._blocked = (
                f"El autómata tiene {len(automaton.states)} estados. "
                f"La simulación se corta en {MAX_SIMULATION_STATES} para no trabar el equipo."
            )
        self._alphabet: set[str] | None = None
        self._outgoing: dict[tuple[str, str], list[str]] = {}
        self._initial: str | None = None
        self._finals: set[str] = set()
        self._has_epsilon = False
        self._initial_error: str | None = None

    def run(self, word: str, *, trace: bool = True) -> Simulation:
        if self._blocked is not None:
            return Simulation(ok=False, accepted=False, message=self._blocked)
        if len(word) > MAX_WORD_LENGTH:
            return Simulation(ok=False, accepted=False, message=word_too_long_message())
        alphabet = self._alphabet_of()
        symbols = _word_symbols(word, alphabet)
        for symbol in symbols:
            if symbol not in alphabet:
                return Simulation(
                    ok=False,
                    accepted=False,
                    message=f"«{symbol}» no está en el alfabeto.",
                )
        self._ensure_index()
        if self._initial_error is not None:
            return Simulation(ok=False, accepted=False, message=self._initial_error)
        return self._walk(symbols, trace)

    def _alphabet_of(self) -> set[str]:
        if self._alphabet is None:
            symbols = self._automaton.alphabet
            if all(symbol.isascii() for symbol in symbols):
                self._alphabet = set(symbols)
            else:
                self._alphabet = {_nfc(symbol) for symbol in symbols}
        return self._alphabet

    def _ensure_index(self) -> None:
        if self._ready:
            return
        self._ready = True
        automaton = self._automaton
        plain = all(state.id.isascii() for state in automaton.states) and all(
            _plain_edge(transition.from_state, transition.to, transition.read)
            for transition in automaton.transitions
        )
        outgoing: dict[tuple[str, str], list[str]] = {}
        if plain:
            for transition in automaton.transitions:
                outgoing.setdefault((transition.from_state, transition.read), []).append(transition.to)
            initials = [state.id for state in automaton.states if state.initial]
            finals = {state.id for state in automaton.states if state.final}
        else:
            for transition in automaton.transitions:
                outgoing.setdefault(
                    (_nfc(transition.from_state), _read(transition.read)),
                    [],
                ).append(_nfc(transition.to))
            initials = [_nfc(state.id) for state in automaton.states if state.initial]
            finals = {_nfc(state.id) for state in automaton.states if state.final}
        self._outgoing = outgoing
        self._finals = finals
        self._has_epsilon = any(symbol == "" for _state, symbol in outgoing)
        if len(initials) != 1:
            self._initial_error = "Tiene que haber exactamente un estado inicial."
            return
        self._initial = initials[0]

    def _walk(self, symbols: list[str], trace: bool) -> Simulation:
        initial = self._initial
        if initial is None:
            return Simulation(
                ok=False,
                accepted=False,
                message="Tiene que haber exactamente un estado inicial.",
            )
        current = self._closure({initial})
        steps: list[Step] = []
        if trace:
            steps.append(Step(symbol="", states=sorted(current)))
        for symbol in symbols:
            nxt: set[str] = set()
            for state_id in current:
                nxt.update(self._outgoing.get((state_id, symbol), ()))
            current = self._closure(nxt)
            if trace:
                steps.append(Step(symbol=symbol, states=sorted(current)))
        accepted = bool(current & self._finals)
        return Simulation(
            ok=True,
            accepted=accepted,
            steps=steps,
            message="Acepta" if accepted else "Rechaza",
        )

    def _closure(self, states: set[str]) -> set[str]:
        if not self._has_epsilon:
            return states
        seen = set(states)
        stack = list(states)
        while stack:
            state_id = stack.pop()
            for nxt in self._outgoing.get((state_id, ""), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen


def simulate(automaton: FiniteAutomaton, word: str) -> Simulation:
    return Simulator(automaton).run(word)
