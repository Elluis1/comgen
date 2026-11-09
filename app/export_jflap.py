import math

from app.sanitize import xml_char_allowed, xml_text
from app.schemas import FiniteAutomaton, State, Transition
from app.validate import validate_fa


def export_jflap(automaton: FiniteAutomaton) -> str:
    """Escribe el .jff directo, sin armar un árbol de XML.

    Un AFD de unos miles de estados genera cerca de un megabyte. Filtrar
    ese texto carácter por carácter, después de crear un nodo por etiqueta,
    trababa la descarga. Los nombres, los símbolos y el comentario ya
    pasan por xml_text. El esqueleto es ASCII y no hay que revisarlo.
    """
    automaton = complete_partial_dfa(automaton)
    index = {state.id: position for position, state in enumerate(automaton.states)}
    names = _xml_names(automaton.states)
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        "<structure>",
        "\t<type>fa</type>",
        "\t<automaton>",
        f"\t\t<!--{_xml_comment(automaton.description)}-->",
    ]
    for state, (x, y) in zip(automaton.states, _layout(automaton), strict=True):
        name = _escape_attr(names[state.id])
        lines.append(f'\t\t<state id="{index[state.id]}" name="{name}">')
        lines.append(f"\t\t\t<x>{x:.1f}</x>")
        lines.append(f"\t\t\t<y>{y:.1f}</y>")
        if state.initial:
            lines.append("\t\t\t<initial />")
        if state.final:
            lines.append("\t\t\t<final />")
        lines.append("\t\t</state>")
    for transition in automaton.transitions:
        symbol = _escape_text(_xml_piece(transition.read))
        lines.append("\t\t<transition>")
        lines.append(f"\t\t\t<from>{index[transition.from_state]}</from>")
        lines.append(f"\t\t\t<to>{index[transition.to]}</to>")
        if symbol:
            lines.append(f"\t\t\t<read>{symbol}</read>")
        else:
            lines.append("\t\t\t<read />")
        lines.append("\t\t</transition>")
    lines.append("\t</automaton>")
    lines.append("</structure>")
    lines.append("")
    return "\n".join(lines)


def _xml_piece(value: str) -> str:
    for char in value:
        if not xml_char_allowed(char):
            return xml_text(value)
    return value


def _escape_text(value: str) -> str:
    # El mismo escape que ElementTree usa en el texto de una etiqueta.
    if "&" not in value and "<" not in value and ">" not in value:
        return value
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attr(value: str) -> str:
    # CR, LF y tab van como entidad: si quedan crudos, un parser los pliega.
    if (
        "&" not in value
        and "<" not in value
        and ">" not in value
        and '"' not in value
        and "\r" not in value
        and "\n" not in value
        and "\t" not in value
    ):
        return value
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\r", "&#13;")
        .replace("\n", "&#10;")
        .replace("\t", "&#09;")
    )


def _xml_comment(description: str) -> str:
    note = xml_text(description)
    while "--" in note:
        note = note.replace("--", "—")
    note = note.strip() or "Comgen"
    if note.endswith("-"):
        note += " "
    return f" {note} "


def _xml_names(states: list[State]) -> dict[str, str]:
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for index, state in enumerate(states):
        base = xml_text(state.id).strip() or f"q{index}"
        name = base
        suffix = 2
        while name in used:
            name = f"{base}{suffix}"
            suffix += 1
        used.add(name)
        mapping[state.id] = name
    return mapping


def complete_partial_dfa(automaton: FiniteAutomaton) -> FiniteAutomaton:
    """Si es un AFD al que le faltan flechas, devuelve uno total con un pozo.

    El pozo no es final. Cada hueco apunta al pozo y el pozo vuelve a sí mismo
    con cada símbolo, así el lenguaje no cambia. Un AFN, un AFD que ya es total
    o un autómata con errores se devuelve igual: el aviso de la pantalla sigue
    saliendo de la validación del original.
    """
    if not automaton.deterministic or not automaton.states or not automaton.alphabet:
        return automaton
    if validate_fa(automaton).errors:
        return automaton

    present = {(transition.from_state, transition.read) for transition in automaton.transitions}
    missing = [
        (state.id, symbol)
        for state in automaton.states
        for symbol in automaton.alphabet
        if (state.id, symbol) not in present
    ]
    if not missing:
        return automaton

    sink_id = _fresh_sink_id({state.id for state in automaton.states})
    states = [*automaton.states, State(id=sink_id, initial=False, final=False)]
    transitions = [
        *automaton.transitions,
        *[Transition(from_state=state_id, to=sink_id, read=symbol) for state_id, symbol in missing],
        *[Transition(from_state=sink_id, to=sink_id, read=symbol) for symbol in automaton.alphabet],
    ]
    return automaton.model_copy(update={"states": states, "transitions": transitions})


def _fresh_sink_id(taken: set[str]) -> str:
    if "pozo" not in taken:
        return "pozo"
    number = 2
    while f"pozo{number}" in taken:
        number += 1
    return f"pozo{number}"


def _layout(automaton: FiniteAutomaton) -> list[tuple[float, float]]:
    states = automaton.states
    count = len(states)
    if count == 0:
        return []
    center_x, center_y, radius = 340.0, 210.0, 150.0
    if count == 1:
        return [(center_x, center_y)]
    initial_at = next((index for index, state in enumerate(states) if state.initial), 0)
    coords: list[tuple[float, float]] = []
    for index in range(count):
        angle = math.pi + (2 * math.pi * ((index - initial_at) % count) / count)
        coords.append((center_x + radius * math.cos(angle), center_y + radius * math.sin(angle)))
    return coords
