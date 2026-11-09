"""Exporta e importa el .jff de una máquina de Turing de una cinta.

El archivo es el que abre JFLAP: `<type>turing</type>`, y cada transición
guarda lectura, escritura y movimiento (`L`, `R` o `S`). El blanco no se
escribe como carácter. Sale en `<read />` y `<write />` vacíos, que es el
blanco de JFLAP. Un comentario dice cuál es ese carácter para poder
recuperarlo. Si el archivo viene de JFLAP y no trae el comentario, el
blanco es `_` cuando ese símbolo no está escrito en otra flecha.

No se inventa un pozo. Una transición que falta no se completa: la
simulación se detiene igual que antes. No llama al modelo y no usa otra
librería de XML: alcanza la biblioteca estándar.

Un comentario antes de `<structure>`, como el de JFLAP 7.1, no es otro
elemento. El blanco es solo el primer comentario de `<automaton>`: una
descripción que dice lo mismo no lo pisa. Un DTD o una entidad se
rechazan en el parser y no se expanden.
"""

import math
import xml.etree.ElementTree as ET
from xml.parsers.expat import ExpatError, ParserCreate

from app.sanitize import xml_text
from app.turing import (
    MAX_ALPHABET,
    MAX_STATES,
    MAX_TRANSITIONS,
    TuringError,
    TuringMachine,
    TuringState,
    TuringTransition,
    _canon_symbol,
    _name_problem,
    _nfc,
    _show,
    validate_tm,
)

# Un .jff de 4096 flechas entra holgado. Por encima no se parsea.
MAX_XML_BYTES = 1_048_576
_DESCRIPTION_LIMIT = 400
_BLANK_MARKER = "El blanco de Comgen es "
_IGNORED_NOTES = (
    "The list of states.",
    "The list of transitions.",
    "Created with JFLAP",
)


class TuringJflapError(TuringError):
    """El archivo no se pudo leer. El mensaje ya está en español."""


def export_turing_jflap(machine: TuringMachine) -> str:
    """XML de JFLAP. No agrega flechas ni un pozo, y no toca la máquina."""
    if not isinstance(machine, TuringMachine):
        raise TuringError("La máquina no tiene el formato esperado.")
    errors = validate_tm(machine)
    if errors:
        raise TuringError(" ".join(errors))
    names = [_nfc(state.id) for state in machine.states]
    blank = _canon_symbol(machine.blank)
    if not isinstance(blank, str):
        raise TuringError("El blanco tiene que ser un solo carácter del alfabeto de la cinta.")
    index = {name: position for position, name in enumerate(names)}
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        "<structure>",
        "\t<type>turing</type>",
        "\t<automaton>",
        f"\t\t<!-- {_BLANK_MARKER}{blank} . -->",
    ]
    description = machine.description if isinstance(machine.description, str) else ""
    if description.strip():
        lines.append(f"\t\t<!--{_xml_comment(description)}-->")
    for state, (x, y) in zip(machine.states, _layout(len(names)), strict=True):
        name = _escape_attr(_nfc(state.id))
        lines.append(f'\t\t<state id="{index[_nfc(state.id)]}" name="{name}">')
        lines.append(f"\t\t\t<x>{x:.1f}</x>")
        lines.append(f"\t\t\t<y>{y:.1f}</y>")
        if state.initial:
            lines.append("\t\t\t<initial />")
        if state.final:
            lines.append("\t\t\t<final />")
        lines.append("\t\t</state>")
    for transition in machine.transitions:
        origin = _nfc(transition.state)
        dest = _nfc(transition.to)
        read = _canon_symbol(transition.read)
        write = _canon_symbol(transition.write)
        if origin not in index or dest not in index or not isinstance(read, str) or not isinstance(write, str):
            raise TuringError("La transición usa un estado o un símbolo que no existe.")
        lines.append("\t\t<transition>")
        lines.append(f"\t\t\t<from>{index[origin]}</from>")
        lines.append(f"\t\t\t<to>{index[dest]}</to>")
        lines.append(_symbol_line("read", read, blank))
        lines.append(_symbol_line("write", write, blank))
        lines.append(f"\t\t\t<move>{transition.move}</move>")
        lines.append("\t\t</transition>")
    lines.append("\t</automaton>")
    lines.append("</structure>")
    lines.append("")
    return "\n".join(lines)


def import_turing_jflap(xml: str) -> TuringMachine:
    """Lee el XML y devuelve la máquina. No completa las flechas que faltan."""
    root = _parsed(xml)
    automaton = _automaton(root)
    _reject_multitape(automaton)
    state_nodes = [child for child in automaton if child.tag == "state"]
    transition_nodes = [child for child in automaton if child.tag == "transition"]
    if len(state_nodes) > MAX_STATES or len(transition_nodes) > MAX_TRANSITIONS:
        raise TuringJflapError(
            f"La máquina se valida hasta {MAX_STATES} estados, {MAX_ALPHABET} símbolos "
            f"y {MAX_TRANSITIONS} transiciones para no trabar el equipo."
        )
    marked, description = _split_blank(automaton, root)
    id_to_name, states = _states(state_nodes)
    explicit: list[str] = []
    seen: set[str] = set()
    pending: list[tuple[str, str | None, str, str | None, str]] = []
    for node in transition_nodes:
        _reject_multitape(node)
        origin = _endpoint(node, "from", "A la transición le falta el origen.")
        dest = _endpoint(node, "to", "A la transición le falta el destino.")
        if origin not in id_to_name or dest not in id_to_name:
            missing = origin if origin not in id_to_name else dest
            raise TuringJflapError(f"La transición apunta al id «{_show(missing)}», que no está en el archivo.")
        move = _endpoint(node, "move", "A la transición le falta el movimiento.")
        if move not in {"L", "R", "S"}:
            raise TuringJflapError(f"El movimiento «{_show(move)}» no es L, R ni S.")
        read = _raw_symbol(node, "read", "A la transición le falta la lectura.", "La lectura")
        write = _raw_symbol(node, "write", "A la transición le falta la escritura.", "La escritura")
        for piece in (read, write):
            if piece is not None and piece not in seen:
                seen.add(piece)
                explicit.append(piece)
        pending.append((id_to_name[origin], read, id_to_name[dest], write, move))
    blank = marked if marked is not None else _default_blank(set(explicit))
    if blank not in seen:
        explicit.append(blank)
    transitions = [
        TuringTransition(
            origin,
            blank if read is None else read,
            dest,
            blank if write is None else write,
            move,
        )
        for origin, read, dest, write, move in pending
    ]
    machine = TuringMachine(
        states=states,
        tape_alphabet=explicit,
        blank=blank,
        transitions=transitions,
        description=description,
    )
    errors = validate_tm(machine)
    if errors:
        raise TuringJflapError(" ".join(errors))
    return machine


def dump_turing(machine: TuringMachine) -> dict:
    """Datos de la máquina, sin el cache de la simulación."""
    return {
        "states": [
            {"id": state.id, "initial": state.initial, "final": state.final}
            for state in machine.states
            if isinstance(state, TuringState)
        ],
        "tape_alphabet": [symbol for symbol in machine.tape_alphabet if isinstance(symbol, str)],
        "blank": machine.blank if isinstance(machine.blank, str) else "",
        "transitions": [
            {
                "state": item.state,
                "read": item.read,
                "to": item.to,
                "write": item.write,
                "move": item.move,
            }
            for item in machine.transitions
            if isinstance(item, TuringTransition)
        ],
        "description": machine.description if isinstance(machine.description, str) else "",
    }


def _parsed(xml: str) -> ET.Element:
    if not isinstance(xml, str) or "\x00" in xml:
        raise TuringJflapError("El archivo no es XML.")
    if len(xml) > MAX_XML_BYTES:
        raise TuringJflapError("El archivo es demasiado grande.")
    # El TreeBuilder mete el comentario en el elemento abierto. El de
    # JFLAP va antes de la raíz y no puede ser otro elemento. El DTD y
    # las entidades se cortan en expat, antes de expandirlas.
    target = ET.TreeBuilder(insert_comments=True)
    parser = ParserCreate()
    parser.buffer_text = True
    parser.StartElementHandler = lambda tag, attrs: target.start(tag, attrs)
    parser.EndElementHandler = target.end
    parser.CharacterDataHandler = target.data
    parser.CommentHandler = target.comment
    parser.StartDoctypeDeclHandler = _forbid_dtd
    parser.EntityDeclHandler = _forbid_dtd
    parser.UnparsedEntityDeclHandler = _forbid_dtd
    parser.ExternalEntityRefHandler = _forbid_dtd
    try:
        parser.Parse(xml, True)
        root = target.close()
    except TuringJflapError:
        raise
    except (ExpatError, AssertionError) as exc:
        raise TuringJflapError("El archivo no es XML.") from exc
    if not isinstance(root, ET.Element) or not isinstance(root.tag, str):
        raise TuringJflapError("El archivo no es XML.")
    return root


def _forbid_dtd(*_args: object) -> None:
    raise TuringJflapError("El archivo trae un DTD y no lo abro.")


def _automaton(root: ET.Element) -> ET.Element:
    if root.tag != "structure":
        raise TuringJflapError("El archivo no es una máquina de Turing: falta <type>turing</type>.")
    types = [child for child in root if child.tag == "type"]
    if len(types) != 1:
        raise TuringJflapError("El archivo no es una máquina de Turing: falta <type>turing</type>.")
    kind = (types[0].text or "").strip().casefold()
    if kind != "turing":
        if kind:
            raise TuringJflapError(f"El archivo declara el tipo «{_show(kind)}», no una máquina de Turing.")
        raise TuringJflapError("El archivo no es una máquina de Turing: falta <type>turing</type>.")
    machines = [child for child in root if child.tag == "automaton"]
    if len(machines) != 1:
        raise TuringJflapError("El archivo no trae la máquina.")
    return machines[0]


def _reject_multitape(node: ET.Element) -> None:
    blocked = {"tapes", "block", "read2", "write2", "move2"}
    if any(child.tag in blocked for child in node):
        raise TuringJflapError("Esta corrida abre una sola cinta, sin bloques.")


def _states(nodes: list[ET.Element]) -> tuple[dict[str, str], list[TuringState]]:
    id_to_name: dict[str, str] = {}
    states: list[TuringState] = []
    for node in nodes:
        file_id = node.get("id")
        if not isinstance(file_id, str) or file_id.strip() == "":
            raise TuringJflapError("Hay un estado sin id.")
        file_id = file_id.strip()
        if len(file_id) > 64:
            raise TuringJflapError("El id de un estado es demasiado largo.")
        if file_id in id_to_name:
            raise TuringJflapError(f"Hay dos estados con el mismo id «{_show(file_id)}».")
        raw_name = node.get("name")
        reason = _name_problem(raw_name)
        if reason:
            raise TuringJflapError(f"El estado no sirve: {reason}.")
        assert isinstance(raw_name, str)
        name = _nfc(raw_name)
        id_to_name[file_id] = name
        states.append(
            TuringState(
                name,
                initial=any(child.tag == "initial" for child in node),
                final=any(child.tag == "final" for child in node),
            )
        )
    return id_to_name, states


def _endpoint(node: ET.Element, tag: str, missing: str) -> str:
    found = [child for child in node if child.tag == tag]
    if not found:
        raise TuringJflapError(missing)
    if len(found) > 1:
        raise TuringJflapError(f"La transición tiene más de un <{tag}>.")
    text = found[0].text or ""
    return text.strip()


def _raw_symbol(node: ET.Element, tag: str, missing: str, label: str) -> str | None:
    """None si la etiqueta está vacía: ese es el blanco, todavía sin carácter."""
    found = [child for child in node if child.tag == tag]
    if not found:
        raise TuringJflapError(missing)
    if len(found) > 1:
        raise TuringJflapError(f"La transición tiene más de un <{tag}>.")
    element = found[0]
    if list(element):
        raise TuringJflapError(f"{label} tiene que ser un símbolo.")
    text = element.text
    if text is None or text == "":
        return None
    canon = _canon_symbol(text)
    if canon is None:
        raise TuringJflapError(f"{label} «{_show(text)}» tiene que ser un solo carácter.")
    return canon


def _split_blank(automaton: ET.Element, root: ET.Element) -> tuple[str | None, str]:
    """El blanco es el primer comentario de `<automaton>`, si tiene la marca.

    El que sigue puede decir lo mismo: es la descripción, no otro blanco.
    """
    comments = _comment_texts(automaton)
    marked: str | None = None
    if comments:
        marked = _blank_from_comment(comments[0])
        if marked is not None:
            comments = comments[1:]
    return marked, _description(comments + _comment_texts(root))


def _blank_from_comment(text: str) -> str | None:
    char = _blank_char(text)
    if char is None:
        return None
    canon = _canon_symbol(char)
    if canon is None:
        raise TuringJflapError("El blanco del archivo tiene que ser un solo carácter.")
    return canon


def _blank_char(text: str) -> str | None:
    left = text.lstrip()
    if not left.startswith(_BLANK_MARKER) or len(left) <= len(_BLANK_MARKER):
        return None
    rest = left[len(_BLANK_MARKER) :]
    # El comentario cierra con « .». Así un blanco que es un espacio no se pierde.
    after = rest[1:].lstrip()
    if not after.startswith(".") or after[1:].strip() != "":
        return None
    return rest[0]


def _default_blank(explicit: set[str]) -> str:
    for candidate in ("_", "□", "␣", "·"):
        if candidate not in explicit:
            return candidate
    for code in range(48, 127):
        candidate = chr(code)
        if candidate.isalnum() and candidate not in explicit:
            return candidate
    raise TuringJflapError(
        "El archivo no deja lugar para el blanco. "
        "Tiene que haber un símbolo que no esté en las transiciones."
    )


def _description(comments: list[str]) -> str:
    for text in comments:
        note = xml_text(text.strip())
        if not note or note == "Comgen":
            continue
        if note.startswith(_IGNORED_NOTES):
            continue
        if len(note) > _DESCRIPTION_LIMIT:
            raise TuringJflapError("La descripción del archivo es demasiado larga.")
        return note
    return ""


def _comment_texts(node: ET.Element) -> list[str]:
    texts: list[str] = []
    for child in node:
        if child.tag is ET.Comment and isinstance(child.text, str):
            texts.append(child.text)
    return texts


def _symbol_line(tag: str, symbol: str, blank: str) -> str:
    if symbol == blank:
        return f"\t\t\t<{tag} />"
    return f"\t\t\t<{tag}>{_escape_text(symbol)}</{tag}>"


def _escape_text(value: str) -> str:
    if "&" not in value and "<" not in value and ">" not in value:
        return value
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attr(value: str) -> str:
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


def _layout(count: int) -> list[tuple[float, float]]:
    if count <= 0:
        return []
    center_x, center_y, radius = 340.0, 210.0, 150.0
    if count == 1:
        return [(center_x, center_y)]
    coords: list[tuple[float, float]] = []
    for index in range(count):
        angle = math.pi + (2 * math.pi * index / count)
        coords.append((center_x + radius * math.cos(angle), center_y + radius * math.sin(angle)))
    return coords
