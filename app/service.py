import re
from contextlib import asynccontextmanager, contextmanager

from app import memory
from app.determinize import DeterminizeError, nfa_to_dfa
from app.grammar import GrammarError, dfa_to_grammar, export_jflap_grammar
from app.regex_from_fa import RegexFromFaError, fa_to_regex
from app.examples import EXAMPLES, Example
from app.familias import recognize_family
from app.interpret import Interpretation, ModelReplyError, interpret_text
from app.minimize import MinimizeError, is_total_dfa, minimize_dfa
from app.ollama_client import OllamaError, chat
from app.prompts import SYSTEM_PROMPT, memory_context, repair_prompt
from app.sanitize import (
    declared_alphabet,
    fold_fullwidth_digits,
    fold_fullwidth_question,
    overflow_message,
    question_tail,
    repetition_digits,
    strip_invisibles,
    strip_marks_before_question,
    without_contradictory_alphabet_errors,
)
from app.sanity import review_model_result
from app.schemas import FiniteAutomaton
from app.config import get_settings
from app.simulate import MAX_WORD_LENGTH, simulate, word_too_long_message
from app.store import Session, store
from app.turing import MAX_TRACE_STEPS, TuringError, TuringMachine
from app.turing import run as run_turing
from app.turing_jflap import dump_turing, export_turing_jflap, import_turing_jflap
from app.validate import prepare_fa, validate_fa


class SessionNotFound(Exception):
    pass


@contextmanager
def _hold(session_id: str):
    """Candado de hilos. Si la sesión se borró en el medio, es un 404."""
    try:
        lock = store.guard(session_id)
    except KeyError as exc:
        raise SessionNotFound(session_id) from exc
    with lock:
        yield


@asynccontextmanager
async def _hold_turn(session_id: str):
    """Candado del turno. El mismo 404 si la sesión ya no está."""
    try:
        lock = store.lock(session_id)
    except KeyError as exc:
        raise SessionNotFound(session_id) from exc
    async with lock:
        yield


def create_session() -> Session:
    return store.create()


def require_session(session_id: str) -> Session:
    try:
        return store.get(session_id)
    except KeyError as exc:
        raise SessionNotFound(session_id) from exc


async def handle_message(session_id: str, text: str) -> dict:
    session = require_session(session_id)
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Escribí un enunciado.")
    if len(cleaned) > 4000:
        raise ValueError("El enunciado es demasiado largo.")

    async with _hold_turn(session_id):
        with _hold(session_id):
            if _should_start_fresh(session, cleaned):
                _drop_carried_work(session)
            session.current_statement = cleaned
            session.recalled = []
            session.ui.append({"role": "user", "content": cleaned})
        try:
            result = await _generate(session, cleaned)
        except OllamaError as exc:
            with _hold(session_id):
                session.ui.append({"role": "assistant", "content": str(exc), "tone": "error"})
                return payload(session, errors=[str(exc)])

        with _hold(session_id):
            if result.automaton is not None:
                session.automaton = result.automaton
                session.warnings = result.warnings
                session.last_request = cleaned
                session.remembered = False
                session.model_messages.append({"role": "user", "content": cleaned})
                session.model_messages.append(
                    {"role": "assistant", "content": result.automaton.model_dump_json(by_alias=True)}
                )
                session.ui.append({"role": "assistant", "content": result.explanation})
            else:
                session.model_messages.append({"role": "user", "content": cleaned})
                session.model_messages.append({"role": "assistant", "content": result.explanation})
                tone = "error" if result.errors else None
                message = {"role": "assistant", "content": result.explanation}
                if tone:
                    message["tone"] = tone
                session.ui.append(message)
            return payload(session, errors=result.errors)


def load_example(session_id: str, example_id: str) -> dict:
    session = require_session(session_id)
    try:
        example = EXAMPLES[example_id]
    except KeyError as exc:
        raise KeyError(example_id) from exc
    with _hold(session_id):
        _install_example(session, example)
        return payload(session)


def run_word(session_id: str, word: str) -> dict:
    session = require_session(session_id)
    with _hold(session_id):
        automaton = session.automaton
    if automaton is None:
        raise ValueError("Todavía no hay un autómata para simular.")
    if len(word) > MAX_WORD_LENGTH:
        raise ValueError(word_too_long_message())
    return simulate(automaton, word).dump()


async def reset_session(session_id: str) -> dict:
    session = require_session(session_id)
    async with _hold_turn(session_id):
        with _hold(session_id):
            _drop_carried_work(session)
            session.ui.clear()
            session.current_statement = ""
            return payload(session)


def remember_solution(session_id: str) -> dict:
    session = require_session(session_id)
    with _hold(session_id):
        if session.automaton is None or not validate_fa(session.automaton).ok:
            raise ValueError("Todavía no hay una solución válida para guardar.")
        request = session.last_request or session.automaton.description
        pattern = ""
        if session.automaton.description.startswith("Expresión "):
            pattern = session.automaton.description.removeprefix("Expresión ").strip()
        explanation = ""
        for message in reversed(session.ui):
            if message.get("role") == "assistant" and message.get("tone") != "error":
                explanation = message.get("content", "")
                break
        memory.save(
            request=request,
            explanation=explanation,
            automaton=session.automaton.dump(),
            pattern=pattern,
        )
        session.remembered = True
        session.ui.append(
            {
                "role": "assistant",
                "content": (
                    "Guardé esta solución en la memoria compartida. "
                    "No se va a responder sola: cuando alguien pida un lenguaje parecido, "
                    "el modelo la va a ver y tiene que analizar el pedido de nuevo."
                ),
            }
        )
        return payload(session)


def determinize_session(session_id: str) -> dict:
    session = require_session(session_id)
    with _hold(session_id):
        if session.automaton is None:
            raise ValueError("Todavía no hay un autómata para determinizar.")
        try:
            result = nfa_to_dfa(session.automaton)
        except DeterminizeError as exc:
            raise ValueError(str(exc)) from exc
        session.automaton = result.automaton
        session.warnings = [*result.notes, *validate_fa(result.automaton).warnings]
        if result.already:
            message = (
                "Ya es un AFD: no hay épsilon ni dos flechas con el mismo símbolo. "
                "No cambié los estados."
            )
        else:
            session.remembered = False
            message = (
                "Pasé el AFN a un AFD por subconjuntos. "
                "Hay un solo estado inicial, no quedan transiciones épsilon "
                "y el lenguaje es el mismo. Podés simular o descargar el .jff."
            )
        session.ui.append({"role": "assistant", "content": message})
        return payload(session)


def regex_session(session_id: str) -> dict:
    session = require_session(session_id)
    with _hold(session_id):
        if session.automaton is None:
            raise ValueError("Todavía no hay un autómata para sacar la expresión.")
        try:
            pattern = fa_to_regex(session.automaton)
        except RegexFromFaError as exc:
            raise ValueError(str(exc)) from exc
        session.ui.append(
            {
                "role": "assistant",
                "content": f"La expresión regular es:\n{pattern}",
            }
        )
        body = payload(session)
        body["pattern"] = pattern
        return body


def grammar_session(session_id: str) -> dict:
    session = require_session(session_id)
    with _hold(session_id):
        if session.automaton is None:
            raise ValueError("Todavía no hay un autómata para armar la gramática.")
        try:
            grammar = dfa_to_grammar(session.automaton)
        except GrammarError as exc:
            raise ValueError(str(exc)) from exc
        session.ui.append(
            {
                "role": "assistant",
                "content": "La gramática lineal a derecha es:\n" + _grammar_chat(grammar.text()),
            }
        )
        body = payload(session)
        body["grammar"] = grammar.dump()
        return body


def export_grammar_session(session_id: str) -> tuple[str, str]:
    session = require_session(session_id)
    with _hold(session_id):
        if session.automaton is None:
            raise ValueError("Todavía no hay un autómata para exportar la gramática.")
        try:
            grammar = dfa_to_grammar(session.automaton)
            xml = export_jflap_grammar(grammar)
        except GrammarError as exc:
            raise ValueError(str(exc)) from exc
        description = session.automaton.description
    return _grammar_filename(description), xml


def import_turing_session(session_id: str, xml: str) -> dict:
    require_session(session_id)
    machine = import_turing_jflap(xml)
    with _hold(session_id):
        session = require_session(session_id)
        session.machine = machine
        dumped = dump_turing(machine)
    return {
        "machine": dumped,
        "message": "Cargué la máquina de Turing. Se puede simular en esta sesión.",
    }


def run_turing_session(session_id: str, word: str, *, trace: bool = False) -> dict:
    require_session(session_id)
    with _hold(session_id):
        session = require_session(session_id)
        machine = session.machine
    if not isinstance(machine, TuringMachine):
        raise ValueError("Todavía no hay una máquina de Turing para simular.")
    if not isinstance(trace, bool):
        raise ValueError("La traza tiene que ser sí o no.")
    try:
        # Sin traza no se copia la cinta. Con traza, el tope guarda el
        # arranque y la última: no se copian 4096 cintas.
        if trace:
            result = run_turing(machine, word, trace=True, trace_cap=MAX_TRACE_STEPS)
        else:
            result = run_turing(machine, word, trace=False)
    except TuringError as exc:
        raise ValueError(str(exc)) from exc
    return result.dump()


def export_turing_session(session_id: str) -> tuple[str, str]:
    require_session(session_id)
    with _hold(session_id):
        session = require_session(session_id)
        machine = session.machine
        if not isinstance(machine, TuringMachine):
            raise ValueError("Todavía no hay una máquina de Turing para exportar.")
        try:
            xml = export_turing_jflap(machine)
        except TuringError as exc:
            raise ValueError(str(exc)) from exc
        description = machine.description if isinstance(machine.description, str) else ""
    return _turing_filename(description), xml


def export_session(session_id: str) -> tuple[str, str]:
    session = require_session(session_id)
    with _hold(session_id):
        if session.automaton is None:
            raise ValueError("Todavía no hay un autómata para exportar.")
        check = validate_fa(session.automaton)
        if check.errors:
            raise ValueError("El autómata tiene errores y no se puede exportar.")
        automaton = session.automaton
    if is_total_dfa(automaton):
        try:
            minimized = minimize_dfa(automaton)
        except MinimizeError as exc:
            raise ValueError(str(exc)) from exc
        if len(minimized.states) < len(automaton.states):
            automaton = minimized
    filename = _filename(automaton.description)
    return filename, export_xml(automaton)


def list_examples() -> list[dict]:
    return [
        {"id": example.id, "title": example.title, "probes": list(example.probes)}
        for example in EXAMPLES.values()
    ]


def payload(session: Session, errors: list[str] | None = None) -> dict:
    # Copia: FastAPI serializa después de soltar el candado, y otro hilo
    # puede estar agregando mensajes.
    with _hold(session.id):
        messages = [dict(item) for item in session.ui]
        warnings = list(session.warnings)
        recalled = list(session.recalled)
        automaton = session.automaton.dump() if session.automaton else None
        export_ready = bool(session.automaton is not None and validate_fa(session.automaton).ok)
        can_remember = bool(session.last_request and export_ready and not session.remembered)
        remembered = session.remembered
        count = memory.count()
    return {
        "messages": messages,
        "automaton": automaton,
        "warnings": warnings,
        "errors": errors or [],
        "export_ready": export_ready,
        "can_remember": can_remember,
        "remembered": remembered,
        "recalled": recalled,
        "memory_count": count,
    }


# El ? suelto es la pregunta del español («unos?», «termine en 01?»).
# Es cuantificador si va pegado a un símbolo, a un literal o a un grupo:
# «a?», «bb?», «01?», «)?».
_REGEX_MARK = re.compile(r"[*+|()]")
_OPTIONAL_LITERAL = re.compile(
    r"(?:^|[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ])([0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\?"
)
# «termine en 01?» y «empiece con bb?»: la preposición cierra la pregunta.
_PROPERTY_PREPOSITION = re.compile(
    r"(?:^|[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ])(?:en|con|de)\s+$",
    re.IGNORECASE,
)
_LONG_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}")
# Palabras cortas que cierran una pregunta. «bb» y «01» no están: son literales.
_QUESTION_WORDS = frozenset(
    {
        "ah", "al", "ay", "eh", "el", "en", "es", "ha", "he", "la", "le", "lo",
        "me", "mi", "no", "oh", "ok", "os", "se", "si", "sí", "su", "te", "ti",
        "tu", "uf", "un", "va", "ve", "ya", "yo",
        "afd", "afn", "con", "del", "dfa", "era", "esa", "ese", "eso", "fue",
        "hay", "hoy", "las", "los", "mal", "mas", "más", "muy", "nfa", "nos",
        "por", "que", "qué", "ser", "son", "sus", "tan", "una", "van", "vas",
        "ven", "ver", "vez", "voy",
    }
)
_TRAILING_PUNCTUATION = " \t.,;:!?¡¿»«\"'"
# gemma3:1b pide num_ctx 4096. El historial completo no entra: se mandan
# las últimas cuatro vueltas (ocho mensajes) y el autómata actual compacto.
MAX_MODEL_HISTORY = 8
# Si el JSON fallido es enorme, reenviarlo se come el contexto del reintento.
MAX_REPAIR_ECHO = 4000


def _looks_like_regex_request(text: str) -> bool:
    """True si el enunciado trae una expresión y el ? no cierra una pregunta."""
    folded = fold_fullwidth_question(fold_fullwidth_digits(text))
    folded = strip_marks_before_question(strip_invisibles(folded))
    folded = re.sub(r"\s+\?", "?", folded)
    if _REGEX_MARK.search(folded):
        return True
    return any(not _closes_a_question(folded, match) for match in _OPTIONAL_LITERAL.finditer(folded))


def _closes_a_question(text: str, match: re.Match[str]) -> bool:
    """True si este ? es el de la oración, no el opcional de la expresión."""
    if question_tail(text[match.end() :]):
        return False
    literal = match.group(1)
    # «a?» y «1?» siguen siendo cuantificador, también adentro de una oración.
    if len(literal) == 1:
        return False
    if "¿" in text:
        return True
    if literal.casefold() in _QUESTION_WORDS:
        return True
    if len(literal) >= 4 and literal.isalpha():
        return True
    before = text[: match.start(1)]
    return _PROPERTY_PREPOSITION.search(before) is not None and _LONG_WORD.search(before) is not None


async def _generate(session: Session, text: str) -> Interpretation:
    recognized = recognize_family(text)
    if recognized is not None:
        return _without_foreign_symbols(text, recognized)

    settings = get_settings()
    with _hold(session.id):
        messages = _model_messages(session, text)
    raw = await chat(settings, messages)
    try:
        result = _checked(text, raw)
    except ModelReplyError as first:
        messages = messages + [
            {"role": "assistant", "content": _echo_for_repair(first.raw)},
            {"role": "user", "content": _repair_content(text, first.errors)},
        ]
        second_raw = await chat(settings, messages)
        try:
            result = _checked(text, second_raw)
        except ModelReplyError as second:
            errors = without_contradictory_alphabet_errors(text, second.errors)
            detail = "\n".join(f"— {error}" for error in errors)
            return Interpretation(
                explanation="No pude armar un autómata válido.\n" + detail,
                errors=errors,
            )
    return review_model_result(text, result)


def _repair_content(text: str, errors: list[str]) -> str:
    """Si el modelo metió un 3 que era una cantidad, el reintento pide los bloques."""
    content = repair_prompt(errors, text)
    if repetition_digits(text):
        content += (
            " Si hay una secuencia (infinitos, «3 0», «tres ceros», «un 0»), "
            'devolvé kind "spec", family "secuencia" y blocks [{symbol, repeat}]. '
            "El número no es un símbolo."
        )
    return content


def _checked(text: str, raw: str) -> Interpretation:
    result = interpret_text(raw, text)
    if _looks_like_regex_request(text) and result.automaton is not None and not result.from_pattern:
        raise ModelReplyError(
            [
                "El enunciado ya trae la expresión. No armes las transiciones. "
                'Devolvé kind "regex" y pattern con los bloques copiados y concatenados.'
            ],
            raw,
        )
    if result.automaton is not None:
        symbols = list(result.automaton.alphabet)
        for transition in result.automaton.transitions:
            if transition.read and transition.read not in symbols:
                symbols.append(transition.read)
        message = overflow_message(text, symbols)
        if message:
            raise ModelReplyError([message], raw)
    return result


def _without_foreign_symbols(text: str, result: Interpretation) -> Interpretation:
    """Una familia armada en código tampoco puede inventar símbolos."""
    if result.automaton is None:
        return result
    message = overflow_message(text, list(result.automaton.alphabet))
    if not message:
        return result
    return Interpretation(explanation=message, errors=[message])


def _should_start_fresh(session: Session, text: str) -> bool:
    """Otro enunciado, u otro alfabeto declarado, no sigue sobre lo anterior."""
    has_prior = bool(
        session.current_statement or session.model_messages or session.automaton is not None
    )
    if not has_prior:
        return False
    if text != session.current_statement:
        return True
    return _declared_alphabet_rejects_current(session, text)


def _declared_alphabet_rejects_current(session: Session, text: str) -> bool:
    declared = declared_alphabet(text)
    if not declared or session.automaton is None:
        return False
    allowed = {symbol.casefold() for symbol in declared}
    return any(symbol.casefold() not in allowed for symbol in session.automaton.alphabet)


def _drop_carried_work(session: Session) -> None:
    session.model_messages.clear()
    session.automaton = None
    session.machine = None
    session.warnings = []
    session.last_request = ""
    session.remembered = False
    session.recalled = []


def _model_messages(session: Session, text: str) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(session.model_messages[-MAX_MODEL_HISTORY:])
    recalled = memory.search(text)
    session.recalled = [
        entry["request"] for entry in recalled if isinstance(entry.get("request"), str)
    ]
    content = text
    context = memory_context(recalled)
    if context:
        content += "\n\n" + context
    if session.automaton is not None and not _declared_alphabet_rejects_current(session, text):
        content += "\n\nAutómata actual, en JSON:\n" + session.automaton.model_dump_json(by_alias=True)
    messages.append({"role": "user", "content": content})
    return messages


def _echo_for_repair(raw: str) -> str:
    if len(raw) <= MAX_REPAIR_ECHO:
        return raw
    return (
        raw[:MAX_REPAIR_ECHO]
        + "\n…(respuesta cortada: era demasiado larga para el contexto del modelo chico)"
    )


def _install_example(session: Session, example: Example) -> None:
    automaton, notes = prepare_fa(example.automaton)
    check = validate_fa(automaton)
    session.machine = None
    session.automaton = automaton
    session.warnings = notes + check.warnings
    session.last_request = automaton.description
    session.remembered = False
    session.recalled = []
    session.ui.append(
        {
            "role": "assistant",
            "content": f"{automaton.description}\n\n{example.blurb}",
        }
    )
    session.model_messages.append({"role": "user", "content": "Tomá este autómata como el actual."})
    session.model_messages.append(
        {"role": "assistant", "content": automaton.model_dump_json(by_alias=True)}
    )


# El chat no lista cientos de variables. El recuadro muestra las primeras y el .jff trae todas.
_GRAMMAR_CHAT_LINES = 24


def _grammar_chat(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= _GRAMMAR_CHAT_LINES:
        return text
    rest = len(lines) - _GRAMMAR_CHAT_LINES
    return "\n".join(lines[:_GRAMMAR_CHAT_LINES]) + f"\n… y {rest} variables más."


def _turing_filename(description: str) -> str:
    stem = _filename(description).removesuffix(".jff")
    if stem == "automata":
        return "maquina.jff"
    return f"maquina-{stem}.jff"


def _grammar_filename(description: str) -> str:
    stem = _filename(description).removesuffix(".jff")
    if stem == "automata":
        return "gramatica.jff"
    return f"gramatica-{stem}.jff"


def _filename(description: str) -> str:
    allowed = []
    for char in description.lower():
        if char.isascii() and char.isalnum():
            allowed.append(char)
        elif char in {" ", "-", "_"}:
            allowed.append("-")
    slug = "".join(allowed).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"{slug or 'automata'}.jff"


def export_xml(automaton: FiniteAutomaton) -> str:
    from app.export_jflap import export_jflap

    return export_jflap(automaton)
