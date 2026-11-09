import json
import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.familias import FamilyError, interpretation_from_spec
from app.regex_lang import RegexError, compile_pattern, pattern_in_field, pattern_literals, pattern_problems
from app.sanitize import (
    alphabet_symbol_issue,
    declared_alphabet,
    is_control_or_invisible,
    overflow_message,
    read_symbol_issue,
    is_epsilon_symbol,
    strip_prose,
    without_contradictory_alphabet_errors,
)
from app.schemas import FiniteAutomaton, ModelOutput, State, Transition
from app.validate import prepare_fa, validate_fa

_FA_KINDS = {"fa", "dfa", "nfa", "afd", "afn", "automata", "autómata"}
# Un JSON con miles de estados pasa por Pydantic y después por la minimización.
# Por encima de este tamaño se rechaza antes de armar el autómata.
MAX_REPLY_STATES = 200
MAX_REPLY_TRANSITIONS = 2000
_REGEX_KINDS = {"regex", "regexp", "er", "expresion", "expresión"}
_SPEC_KINDS = {"spec", "familia", "family"}


class ModelReplyError(Exception):
    def __init__(self, errors: list[str], raw: str) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors
        self.raw = raw


@dataclass
class Interpretation:
    explanation: str
    automaton: FiniteAutomaton | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    export_ready: bool = False
    unsupported: bool = False
    from_pattern: bool = False
    from_model_machine: bool = False
    samples_accept: list[str] = field(default_factory=list)
    samples_reject: list[str] = field(default_factory=list)


def interpret_text(raw: str, statement: str = "") -> Interpretation:
    data = _load_json(raw)
    try:
        draft = ModelOutput.model_validate(data)
    except RecursionError as exc:
        raise ModelReplyError(
            ["La respuesta está anidada demasiado y no se puede leer."],
            raw,
        ) from exc
    except ValidationError as exc:
        raise ModelReplyError(_format_validation(exc), raw) from exc
    draft = _sanitize_draft(draft, raw, statement)
    draft = _include_declared_reads(draft, statement)

    kind = draft.kind.strip().lower() or "fa"
    if kind in {"nfa", "afn"}:
        draft.deterministic = False
    elif kind in {"dfa", "afd"}:
        draft.deterministic = True

    if kind in _SPEC_KINDS:
        try:
            return interpretation_from_spec(draft)
        except FamilyError as exc:
            raise ModelReplyError([str(exc)], raw) from exc

    if kind in _REGEX_KINDS:
        pattern = draft.pattern.strip() or pattern_in_field(draft.description) or pattern_in_field(draft.explanation)
        return _with_samples(
            _from_pattern(pattern, draft.description, raw, statement),
            draft,
            from_model_machine=True,
        )

    if kind not in _FA_KINDS:
        explanation = draft.explanation.strip() or (
            "Por ahora solo construyo autómatas finitos. "
            "Gramáticas, autómatas de pila y máquinas de Turing quedan para más adelante."
        )
        return Interpretation(explanation=explanation, unsupported=True)

    if len(draft.states) > MAX_REPLY_STATES or len(draft.transitions) > MAX_REPLY_TRANSITIONS:
        raise ModelReplyError(
            [
                "El autómata que devolvió el modelo es demasiado grande "
                f"({len(draft.states)} estados y {len(draft.transitions)} transiciones). "
                f"El tope es {MAX_REPLY_STATES} estados y {MAX_REPLY_TRANSITIONS} transiciones."
            ],
            raw,
        )

    automaton, notes = prepare_fa(
        FiniteAutomaton(
            deterministic=draft.deterministic,
            alphabet=draft.alphabet,
            states=draft.states,
            transitions=draft.transitions,
            description=draft.description,
        )
    )
    check = validate_fa(automaton)
    if check.errors:
        if draft.pattern.strip():
            try:
                return _with_samples(
                    _from_pattern(draft.pattern, draft.description, raw, statement),
                    draft,
                    from_model_machine=True,
                )
            except ModelReplyError:
                pass
        raise ModelReplyError(without_contradictory_alphabet_errors(statement, check.errors), raw)

    automaton = _fit_declared_alphabet(automaton, statement, raw)
    check = validate_fa(automaton)
    if check.errors:
        raise ModelReplyError(without_contradictory_alphabet_errors(statement, check.errors), raw)
    explanation = draft.explanation.strip() or "Armé el autómata a partir del enunciado."
    return _with_samples(
        Interpretation(
            explanation=explanation,
            automaton=automaton,
            warnings=notes + check.warnings,
            export_ready=True,
        ),
        draft,
        from_model_machine=True,
    )


def _nfc_symbol(symbol: str) -> str:
    return unicodedata.normalize("NFC", symbol)


def _sanitize_draft(draft: ModelOutput, raw: str, statement: str) -> ModelOutput:
    """Saca controles del texto y rechaza símbolos o expresiones que no se pueden usar."""
    draft = draft.model_copy(
        update={
            "pattern": _nfc_symbol(draft.pattern),
            "alphabet": [_nfc_symbol(symbol) for symbol in draft.alphabet],
            "transitions": [
                transition.model_copy(update={"read": _nfc_symbol(transition.read)})
                for transition in draft.transitions
            ],
        }
    )
    problems: list[str] = []
    symbols: list[str] = []
    if draft.pattern.strip():
        problems.extend(pattern_problems(draft.pattern))
        symbols.extend(pattern_literals(draft.pattern))
    for symbol in draft.alphabet:
        issue = alphabet_symbol_issue(symbol)
        if issue and issue not in problems:
            problems.append(issue)
        if symbol not in symbols:
            symbols.append(symbol)
    for transition in draft.transitions:
        issue = read_symbol_issue(transition.read)
        if issue and issue not in problems:
            problems.append(issue)
        if transition.read and transition.read not in symbols:
            symbols.append(transition.read)
    for state in draft.states:
        if any(is_control_or_invisible(char) for char in state.id):
            message = "El nombre de un estado tiene un carácter de control o invisible."
            if message not in problems:
                problems.append(message)
            break
    for block in draft.blocks:
        if any(is_control_or_invisible(char) for char in block.symbol):
            message = "Hay un símbolo con un carácter de control o invisible."
            if message not in problems:
                problems.append(message)
            break
    overflow = overflow_message(statement, [symbol for symbol in symbols if not _is_epsilon_token(symbol)])
    if overflow and overflow not in problems:
        problems.append(overflow)
    if problems:
        raise ModelReplyError(without_contradictory_alphabet_errors(statement, problems), raw)

    description = strip_prose(draft.description)
    explanation = strip_prose(draft.explanation)
    if description == draft.description and explanation == draft.explanation:
        return draft
    return draft.model_copy(update={"description": description, "explanation": explanation})


def _is_epsilon_token(symbol: str) -> bool:
    return symbol.strip() == "" or is_epsilon_symbol(symbol)


def _from_pattern(pattern: str, _description: str, raw: str, statement: str = "") -> Interpretation:
    cleaned = pattern.strip()
    if not cleaned:
        raise ModelReplyError(["Falta pattern con la expresión regular."], raw)
    try:
        automaton, explanation = compile_pattern(cleaned)
    except RegexError as exc:
        raise ModelReplyError([str(exc)], raw) from exc
    automaton = _fit_declared_alphabet(automaton, statement, raw)
    check = validate_fa(automaton)
    return Interpretation(
        explanation=explanation,
        automaton=automaton,
        warnings=check.warnings,
        export_ready=check.ok,
        from_pattern=True,
    )


def _include_declared_reads(draft: ModelOutput, statement: str) -> ModelOutput:
    """Un símbolo que el enunciado declara y el modelo ya usó entra al alfabeto.

    Si no, la validación dice «0» no está en el alfabeto aunque el enunciado
    lo haya pedido. Los símbolos de más se rechazan antes, en el saneo.
    """
    declared = declared_alphabet(statement)
    if not declared:
        return draft
    allowed = set(declared)
    alphabet = list(draft.alphabet)
    changed = False
    for transition in draft.transitions:
        symbol = transition.read.strip()
        if len(symbol) != 1 or symbol in alphabet or symbol not in allowed:
            continue
        alphabet.append(symbol)
        changed = True
    if not changed:
        return draft
    return draft.model_copy(update={"alphabet": alphabet})


def _fit_declared_alphabet(automaton: FiniteAutomaton, statement: str, raw: str) -> FiniteAutomaton:
    """El alfabeto escrito en el enunciado manda: no se agregan símbolos, y los que faltan rechazan."""
    declared = declared_alphabet(statement)
    if not declared or not automaton.states:
        return automaton
    extras = [symbol for symbol in automaton.alphabet if symbol not in set(declared)]
    message = overflow_message(statement, extras)
    if message:
        raise ModelReplyError(without_contradictory_alphabet_errors(statement, [message]), raw)
    missing = [symbol for symbol in declared if symbol not in automaton.alphabet]
    if not missing:
        return automaton
    return _with_missing_symbols(automaton, list(declared), missing)


def _with_missing_symbols(
    automaton: FiniteAutomaton,
    alphabet: list[str],
    missing: list[str],
) -> FiniteAutomaton:
    present = {(item.from_state, item.read) for item in automaton.transitions}
    ids = [state.id for state in automaton.states]
    sink = _fresh_state_id(set(ids), "qs")
    transitions = list(automaton.transitions)
    needs_sink = False
    for state_id in ids:
        for symbol in missing:
            if (state_id, symbol) not in present:
                needs_sink = True
                transitions.append(Transition(from_state=state_id, to=sink, read=symbol))
                present.add((state_id, symbol))
    states = list(automaton.states)
    if needs_sink:
        for symbol in alphabet:
            if (sink, symbol) not in present:
                transitions.append(Transition(from_state=sink, to=sink, read=symbol))
        states.append(State(id=sink, initial=False, final=False))
    return automaton.model_copy(
        update={"alphabet": alphabet, "states": states, "transitions": transitions}
    )


def _fresh_state_id(used: set[str], base: str) -> str:
    if base not in used:
        return base
    number = 2
    while f"{base}{number}" in used:
        number += 1
    return f"{base}{number}"


def _with_samples(result: Interpretation, draft: ModelOutput, from_model_machine: bool) -> Interpretation:
    result.samples_accept = list(draft.accept)
    result.samples_reject = list(draft.reject)
    result.from_model_machine = from_model_machine
    return result


def _load_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except RecursionError as exc:
        raise ModelReplyError(
            ["La respuesta está anidada demasiado y no se puede leer."],
            raw,
        ) from exc
    except json.JSONDecodeError as exc:
        raise ModelReplyError([f"La respuesta no es JSON válido ({exc.msg})."], raw) from exc
    except ValueError as exc:
        # Un entero de miles de dígitos no es JSONDecodeError: json.loads tira ValueError.
        raise ModelReplyError(
            ["La respuesta trae un número demasiado grande y no se puede leer."],
            raw,
        ) from exc
    if not isinstance(data, dict):
        raise ModelReplyError(["La respuesta tiene que ser un objeto JSON."], raw)
    return data


def _format_validation(exc: ValidationError) -> list[str]:
    lines = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"])
        lines.append(f"{where}: {error['msg']}")
    return lines or ["El JSON no cumple el esquema."]
