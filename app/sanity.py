"""Revisión de un autómata que armó el modelo: minimizar, medir y contrastar cadenas."""

from app.familias import sounds_like_family
from app.interpret import Interpretation
from app.minimize import MinimizeError, is_total_dfa, minimize_dfa
from app.regex_lang import extract_regex
from app.simulate import Simulator

WARN_STATES = 24
REJECT_STATES = 48


def review_model_result(text: str, result: Interpretation) -> Interpretation:
    if result.automaton is None or not result.from_model_machine:
        return result

    automaton = result.automaton
    warnings = list(result.warnings)
    if is_total_dfa(automaton):
        try:
            minimized = minimize_dfa(automaton)
        except MinimizeError as exc:
            message = str(exc)
            return Interpretation(explanation=message, errors=[message])
        if len(minimized.states) < len(automaton.states):
            warnings.append(
                f"Minimicé el AFD: pasó de {len(automaton.states)} a {len(minimized.states)} estados. "
                "Si la explicación nombra estados, puede haber quedado vieja."
            )
        automaton = minimized

    count = len(automaton.states)
    if count >= REJECT_STATES and not _user_wrote_pattern(text, automaton.description):
        message = (
            f"El modelo armó un autómata de {count} estados "
            "que no sale de una expresión escrita en el enunciado. No lo uso: "
            "con un modelo chico ese resultado suele estar mal."
        )
        return Interpretation(explanation=message, errors=[message])

    mismatches = _mismatches(automaton, result.samples_accept, result.samples_reject)
    if mismatches:
        shown = "; ".join(mismatches[:6])
        warnings.append(
            "Estas cadenas de prueba no coinciden con el autómata: "
            f"{shown}. Conviene revisarlo antes de exportarlo."
        )
    if count >= WARN_STATES:
        warnings.append(
            f"El autómata tiene {count} estados. Es mucho para un enunciado corto "
            "y puede estar mal. Revisalo antes de exportarlo."
        )
    if sounds_like_family(text):
        warnings.append(
            "El enunciado parece de una familia que se arma en código "
            "(divisibilidad, cuentas, longitud, termina, empieza, contiene, la posición de un símbolo "
            "o una secuencia de bloques), "
            "pero no pude leer los parámetros. Este autómata salió del modelo: revisalo."
        )

    result.automaton = automaton
    result.warnings = warnings
    return result


def _user_wrote_pattern(text: str, description: str) -> bool:
    pattern = ""
    if description.startswith("Expresión "):
        pattern = description.removeprefix("Expresión ").strip()
    compact = pattern.replace(" ", "")
    if compact and compact in "".join(text.split()):
        return True
    extracted = extract_regex(text)
    return bool(extracted and compact and extracted.replace(" ", "") == compact)


def _mismatches(automaton, accept: list[str], reject: list[str]) -> list[str]:
    runner = Simulator(automaton)
    lines = []
    for word in accept:
        result = runner.run(word, trace=False)
        if not result.ok or not result.accepted:
            lines.append(f"«{word or 'ε'}» debería aceptarse")
    for word in reject:
        result = runner.run(word, trace=False)
        if not result.ok or result.accepted:
            lines.append(f"«{word or 'ε'}» debería rechazarse")
    return lines
