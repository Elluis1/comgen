"""Gramática lineal a derecha, la de la materia, enlazada con el autómata.

De un AFD sale una variable por estado. Cada flecha δ(q, a) = p es una
producción A → aB, y cada estado final agrega A → ε. No se minimiza y no
se agrega el pozo: la flecha que falta no tiene producción, y esa cadena
sigue rechazando. Un AFN no se convierte; primero hay que determinizarlo.

Al revés, cada variable es un estado. A → aB es una flecha, A → a va a un
estado final nuevo y A → ε marca el estado como final. El símbolo inicial
es el estado inicial.

Los nombres preferidos son letras mayúsculas que no están en el alfabeto.
El inicial se llama S cuando S no es un terminal: JFLAP abre el archivo
con S como inicio y trata cada mayúscula como variable. La producción
vacía deja `<right>` sin texto; JFLAP lo muestra como λ.
"""

import unicodedata
import xml.etree.ElementTree as ET

from app.sanitize import is_control_or_invisible, is_epsilon_symbol, xml_char_allowed, xml_text
from app.schemas import FiniteAutomaton, State, Transition
from app.validate import prepare_fa, validate_fa

# Por encima de esto la gramática no entra en la notebook chica. El caso de
# 4032 estados de las familias se niega acá, sin armar producciones.
MAX_STATES = 1024
MAX_PRODUCTIONS = 8192
_NAME_LIMIT = 32
_LETTERS = "SABCDEFGHIJKLMNOPQRSTUVWXYZ"


class GrammarError(Exception):
    pass


class Production:
    """A → aB, A → a, o A → ε.

    La vacía es terminal y right en None. A → a deja right en None.
    Un terminal vacío o un right vacío no son esas formas.
    """

    def __init__(self, left: str, terminal: str | None, right: str | None) -> None:
        self.left = left
        self.terminal = terminal
        self.right = right

    def form(self) -> str:
        if self.terminal is None and self.right is None:
            return "empty"
        if isinstance(self.terminal, str) and self.terminal != "" and self.right is None:
            return "terminal"
        if (
            isinstance(self.terminal, str)
            and self.terminal != ""
            and isinstance(self.right, str)
            and self.right != ""
        ):
            return "step"
        return "invalid"


class RegularGrammar:
    def __init__(
        self,
        terminals: list[str] | tuple[str, ...],
        nonterminals: list[str] | tuple[str, ...],
        start: str,
        productions: list[Production] | tuple[Production, ...],
        description: str = "",
    ) -> None:
        self.terminals = terminals
        self.nonterminals = nonterminals
        self.start = start
        self.productions = productions
        self.description = description

    def text(self) -> str:
        grouped: dict[str, list[Production]] = {}
        for production in self.productions:
            if not isinstance(production, Production):
                continue
            item = _canon_production(production)
            if isinstance(item.left, str):
                grouped.setdefault(item.left, []).append(item)
        lines: list[str] = []
        seen: set[str] = set()
        names = [self.start, *list(self.nonterminals)]
        for raw in names:
            if not isinstance(raw, str):
                continue
            name = _nfc(raw)
            if name in seen:
                continue
            seen.add(name)
            items = grouped.get(name, [])
            if not items:
                continue
            bodies = " | ".join(_piece(production) for production in items)
            lines.append(f"{_show_name(name)} → {bodies}")
        return "\n".join(lines)

    def dump(self) -> dict:
        errors = validate_grammar(self)
        problem = None if errors else jflap_problem(self)
        terminals = list(self.terminals) if isinstance(self.terminals, (list, tuple)) else []
        nonterminals = list(self.nonterminals) if isinstance(self.nonterminals, (list, tuple)) else []
        return {
            "start": self.start,
            "terminals": terminals,
            "nonterminals": nonterminals,
            "productions": [
                {
                    "left": production.left,
                    "terminal": production.terminal,
                    "right": production.right,
                }
                for production in self.productions
                if isinstance(production, Production)
            ],
            "text": "" if errors else self.text(),
            "jflap": not errors and problem is None,
            "jflap_note": problem or "",
        }


def validate_grammar(grammar: RegularGrammar) -> list[str]:
    """Errores en español. Vacío si la gramática es lineal a derecha."""
    errors: list[str] = []
    terminals = _symbol_list(grammar.terminals)
    nonterminals = _symbol_list(grammar.nonterminals)
    if terminals is None:
        errors.append("Los terminales tienen que ser una lista.")
    if nonterminals is None:
        errors.append("Los no terminales tienen que ser una lista.")
    if not isinstance(grammar.productions, (list, tuple)) or isinstance(grammar.productions, (str, bytes)):
        errors.append("Las producciones tienen que ser una lista.")
        return _cap(errors)
    if terminals is None or nonterminals is None:
        return _cap(errors)

    if len(nonterminals) > MAX_STATES or len(grammar.productions) > MAX_PRODUCTIONS:
        errors.append(
            f"La gramática se valida hasta {MAX_STATES} variables y {MAX_PRODUCTIONS} producciones "
            "para no trabar el equipo."
        )
        return _cap(errors)

    terminal_set: set[str] = set()
    for symbol in terminals:
        if isinstance(symbol, str):
            symbol = _nfc(symbol)
        reason = _terminal_problem(symbol)
        if reason:
            errors.append(reason)
            continue
        if symbol in terminal_set:
            errors.append(f"El terminal «{symbol}» está repetido.")
        terminal_set.add(symbol)

    nonterminal_set: set[str] = set()
    for name in nonterminals:
        if isinstance(name, str):
            name = _nfc(name)
        reason = _name_problem(name)
        if reason:
            errors.append(f"El no terminal no sirve: {reason}.")
            continue
        if name in nonterminal_set:
            errors.append(f"Hay dos no terminales con el mismo nombre: «{name}».")
        if name in terminal_set:
            errors.append(f"«{name}» no puede ser terminal y no terminal a la vez.")
        nonterminal_set.add(name)

    start = _nfc(grammar.start) if isinstance(grammar.start, str) else grammar.start
    if not isinstance(start, str) or start not in nonterminal_set:
        errors.append("Tiene que haber un solo símbolo inicial, y tiene que ser un no terminal.")

    for production in grammar.productions:
        if not isinstance(production, Production):
            errors.append(
                "Hay una producción que no es lineal a derecha. Tiene que ser A → aB, A → a o A → ε."
            )
            continue
        item = _canon_production(production)
        if item.form() == "invalid":
            errors.append(
                f"La producción de «{item.left}» no es lineal a derecha. "
                "Tiene que ser A → aB, A → a o A → ε."
            )
            continue
        if not isinstance(item.left, str) or item.left not in nonterminal_set:
            errors.append(f"El lado izquierdo «{item.left}» no es un no terminal.")
        if item.terminal is not None and item.terminal not in terminal_set:
            errors.append(f"«{item.terminal}» no está en el alfabeto de terminales.")
        if item.right is not None and item.right not in nonterminal_set:
            errors.append(f"El no terminal «{item.right}» del lado derecho no está en la gramática.")
    return _cap(errors)


def dfa_to_grammar(automaton: FiniteAutomaton) -> RegularGrammar:
    """Gramática equivalente. No modifica el autómata de entrada."""
    _reject_huge(automaton)
    prepared, _notes = prepare_fa(automaton)
    check = validate_fa(prepared.model_copy(update={"deterministic": False}))
    if not check.ok:
        raise GrammarError(" ".join(check.errors))
    if not _is_dfa(prepared):
        raise GrammarError("Este autómata no es determinista. Primero hay que determinizarlo.")
    flagged = prepared.model_copy(update={"deterministic": True})
    check_dfa = validate_fa(flagged)
    if not check_dfa.ok:
        raise GrammarError(" ".join(check_dfa.errors))
    for symbol in flagged.alphabet:
        reason = _terminal_problem(symbol)
        if reason:
            raise GrammarError(reason)

    initial = next(state.id for state in flagged.states if state.initial)
    ordered = [initial, *[state.id for state in flagged.states if state.id != initial]]
    names = _assign(ordered, set(flagged.alphabet))
    finals = {state.id for state in flagged.states if state.final}
    by_state: dict[str, list[Production]] = {state_id: [] for state_id in ordered}
    for transition in flagged.transitions:
        if not transition.read:
            continue
        by_state[transition.from_state].append(
            Production(names[transition.from_state], transition.read, names[transition.to])
        )
    productions: list[Production] = []
    for state_id in ordered:
        if state_id in finals:
            by_state[state_id].append(Production(names[state_id], None, None))
        productions.extend(by_state[state_id])

    grammar = RegularGrammar(
        terminals=tuple(flagged.alphabet),
        nonterminals=tuple(names[state_id] for state_id in ordered),
        start=names[initial],
        productions=tuple(productions),
        description=flagged.description,
    )
    errors = validate_grammar(grammar)
    if errors:
        raise GrammarError(" ".join(errors))
    return grammar


def grammar_to_nfa(grammar: RegularGrammar) -> FiniteAutomaton:
    """AFN equivalente. Una gramática inválida no se arma."""
    errors = validate_grammar(grammar)
    if errors:
        raise GrammarError(" ".join(errors))
    nonterminals: list[str] = []
    for name in grammar.nonterminals:
        if not isinstance(name, str):
            continue
        key = _nfc(name)
        if key not in nonterminals:
            nonterminals.append(key)
    start = _nfc(grammar.start) if isinstance(grammar.start, str) else grammar.start
    productions = [
        _canon_production(production)
        for production in grammar.productions
        if isinstance(production, Production)
    ]
    finals = {
        production.left
        for production in productions
        if production.form() == "empty" and isinstance(production.left, str)
    }
    extra: str | None = None
    if any(production.form() == "terminal" for production in productions):
        extra = _fresh_accept(set(nonterminals))
        finals.add(extra)

    states = [
        State(id=name, initial=name == start, final=name in finals)
        for name in nonterminals
    ]
    if extra is not None:
        states.append(State(id=extra, initial=False, final=True))

    transitions: list[Transition] = []
    seen: set[tuple[str, str, str]] = set()
    for production in productions:
        if production.terminal is None or not isinstance(production.left, str):
            continue
        if not isinstance(production.terminal, str):
            continue
        target = extra if production.right is None else production.right
        if not isinstance(target, str):
            continue
        key = (production.left, target, production.terminal)
        if key in seen:
            continue
        seen.add(key)
        transitions.append(Transition(from_state=production.left, to=target, read=production.terminal))

    used: set[tuple[str, str]] = set()
    deterministic = True
    for transition in transitions:
        key = (transition.from_state, transition.read)
        if key in used:
            deterministic = False
            break
        used.add(key)

    return FiniteAutomaton(
        deterministic=deterministic,
        alphabet=_nfc_symbols(grammar.terminals),
        states=states,
        transitions=transitions,
        description=grammar.description or "AFN de una gramática lineal a derecha",
    )


def jflap_problem(grammar: RegularGrammar) -> str | None:
    """None si JFLAP puede abrir el archivo sin cambiar el símbolo inicial."""
    start = _nfc(grammar.start) if isinstance(grammar.start, str) else grammar.start
    if start != "S":
        return (
            "JFLAP abre el archivo con S como símbolo inicial. "
            "Esta gramática no empieza en S, así que no exporto el .jff."
        )
    for terminal in grammar.terminals:
        if not isinstance(terminal, str):
            continue
        terminal = _nfc(terminal)
        if len(terminal) == 1 and terminal.isupper():
            return (
                f"JFLAP toma «{terminal}» como variable porque es mayúscula. "
                "No exporto el archivo."
            )
        if any(ord(char) > 0xFFFF for char in terminal):
            return (
                "JFLAP lee los símbolos de a uno en el plano básico. "
                "Este alfabeto no entra en el archivo."
            )
    for name in grammar.nonterminals:
        if isinstance(name, str):
            name = _nfc(name)
        if not isinstance(name, str) or len(name) != 1 or not name.isascii() or not name.isupper():
            return (
                "JFLAP solo admite variables de una letra mayúscula. "
                "Esta gramática no entra en el archivo."
            )
    return None


def export_jflap_grammar(grammar: RegularGrammar) -> str:
    """XML de gramática de JFLAP. La vacía es un `<right>` sin texto."""
    errors = validate_grammar(grammar)
    if errors:
        raise GrammarError(" ".join(errors))
    problem = jflap_problem(grammar)
    if problem:
        raise GrammarError(problem)

    structure = ET.Element("structure")
    type_node = ET.SubElement(structure, "type")
    type_node.text = "grammar"
    structure.append(ET.Comment(_xml_comment(grammar.description)))
    for production in grammar.productions:
        if not isinstance(production, Production):
            continue
        production = _canon_production(production)
        node = ET.SubElement(structure, "production")
        ET.SubElement(node, "left").text = xml_text(production.left if isinstance(production.left, str) else "")
        right = ET.SubElement(node, "right")
        if production.form() == "empty":
            body = ""
        elif production.form() == "terminal":
            body = production.terminal if isinstance(production.terminal, str) else ""
        else:
            body = f"{production.terminal}{production.right}"
        body = xml_text(body)
        if body:
            right.text = body

    ET.indent(structure, space="\t")
    document = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    document += ET.tostring(structure, encoding="unicode")
    document += "\n"
    return xml_text(document)


def _reject_huge(automaton: FiniteAutomaton) -> None:
    if len(automaton.states) > MAX_STATES:
        raise GrammarError(
            f"El autómata tiene {len(automaton.states)} estados. "
            f"La gramática se arma hasta {MAX_STATES} para no trabar el equipo."
        )
    if len(automaton.alphabet) > MAX_PRODUCTIONS or len(automaton.transitions) > MAX_PRODUCTIONS:
        raise GrammarError(
            f"La gramática se arma hasta {MAX_PRODUCTIONS} producciones para no trabar el equipo."
        )
    symbols: set[str] = set()
    for symbol in automaton.alphabet:
        symbols.add(symbol)
    if len(automaton.states) * (len(symbols) + 1) > MAX_PRODUCTIONS:
        raise GrammarError(
            f"La gramática se arma hasta {MAX_PRODUCTIONS} producciones para no trabar el equipo."
        )


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


def _assign(state_ids: list[str], terminals: set[str]) -> dict[str, str]:
    free = [letter for letter in _LETTERS if letter not in terminals]
    if len(state_ids) <= len(free):
        return {state_id: letter for state_id, letter in zip(state_ids, free)}
    used = set(terminals)
    mapping: dict[str, str] = {}
    for index, state_id in enumerate(state_ids):
        if index == 0 and "S" not in used:
            name = "S"
        else:
            name = f"N{index}"
            while name in used:
                name += "x"
        used.add(name)
        mapping[state_id] = name
    return mapping


def _fresh_accept(used: set[str]) -> str:
    if "qf" not in used:
        return "qf"
    number = 2
    while f"qf{number}" in used:
        number += 1
    return f"qf{number}"


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _nfc_symbols(symbols: list[str] | tuple[str, ...]) -> list[str]:
    ordered: list[str] = []
    for symbol in symbols:
        if not isinstance(symbol, str):
            continue
        key = _nfc(symbol)
        if key not in ordered:
            ordered.append(key)
    return ordered


def _canon_production(production: Production) -> Production:
    left = _nfc(production.left) if isinstance(production.left, str) else production.left
    terminal = _nfc(production.terminal) if isinstance(production.terminal, str) else production.terminal
    right = _nfc(production.right) if isinstance(production.right, str) else production.right
    if left == production.left and terminal == production.terminal and right == production.right:
        return production
    return Production(left, terminal, right)


def _show_name(name: str) -> str:
    # «A | B» como un solo nombre no puede partirse en dos alternativas.
    if (
        "|" in name
        or "→" in name
        or ", " in name
        or " y " in name
        or "«" in name
        or "»" in name
        or any(char.isspace() for char in name)
    ):
        visible = name.replace("«", "‹").replace("»", "›")
        return f"«{visible}»"
    return name


def _show_terminal(symbol: str) -> str:
    # El «|» suelto se lee como otra alternativa, y un espacio desaparece.
    # Una marca combinante se pega al carácter de atrás.
    if (
        any(char.isspace() for char in symbol)
        or "|" in symbol
        or "→" in symbol
        or any(unicodedata.category(char) == "Mn" for char in symbol)
    ):
        visible = symbol.replace("«", "‹").replace("»", "›")
        return f"«{visible}»"
    return symbol


def _piece(production: Production) -> str:
    if production.form() == "empty":
        return "ε"
    terminal = _nfc(production.terminal) if isinstance(production.terminal, str) else ""
    if production.form() == "terminal":
        return _show_terminal(terminal)
    right = _nfc(production.right) if isinstance(production.right, str) else ""
    shown = _show_terminal(terminal)
    right_shown = _show_name(right)
    glue = (
        shown == terminal
        and right_shown == right
        and len(terminal) == 1
        and len(right) == 1
        and not terminal.isupper()
        and _nfc(terminal + right) == terminal + right
    )
    if glue:
        return f"{terminal}{right}"
    return f"{shown} {right_shown}"


def _symbol_list(value: object) -> list[str] | None:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        return None
    return list(value)


def _terminal_problem(symbol: object) -> str | None:
    if isinstance(symbol, str):
        symbol = _nfc(symbol)
    if not isinstance(symbol, str) or len(symbol) != 1:
        shown = symbol if isinstance(symbol, str) and symbol else "vacío"
        if isinstance(shown, str) and len(shown) > 16:
            shown = shown[:16] + "…"
        return f"«{shown}» no puede ser un terminal: tiene que ser un solo carácter."
    if is_epsilon_symbol(symbol):
        return "La cadena vacía se escribe como A → ε, no como un terminal."
    if is_control_or_invisible(symbol) or not xml_char_allowed(symbol):
        return "Hay un carácter de control en el alfabeto y no puede ser un terminal."
    return None


def _name_problem(name: object) -> str | None:
    if not isinstance(name, str) or not name or name.strip() != name:
        return "está vacío o tiene espacios"
    if len(name) > _NAME_LIMIT:
        return "es demasiado largo"
    if any(is_control_or_invisible(char) or not xml_char_allowed(char) for char in name):
        return "tiene un carácter de control"
    if is_epsilon_symbol(name):
        return "no puede ser la cadena vacía"
    return None


def _xml_comment(description: str) -> str:
    note = xml_text(description)
    while "--" in note:
        note = note.replace("--", "—")
    note = note.strip()
    if len(note) > 180:
        note = note[:180].rstrip()
        while "--" in note:
            note = note.replace("--", "—")
    note = note or "Gramática lineal a derecha"
    if note.endswith("-"):
        note += " "
    return f" {note} "


def _cap(errors: list[str], limit: int = 8) -> list[str]:
    if len(errors) <= limit:
        return errors
    hidden = len(errors) - limit
    return errors[:limit] + [f"Hay {hidden} errores más del mismo tipo."]
