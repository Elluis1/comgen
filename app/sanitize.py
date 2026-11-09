"""Caracteres que no pueden entrar a un autómata ni a un .jff.

Hay dos filtros distintos. El de la salida del modelo saca controles e
invisibles (U+0008, ancho cero, etc.) de expresiones, símbolos y textos.
El del XML es más chico: solo los code points que XML 1.0 no admite.
"""

import re
import unicodedata

# En una descripción se pueden dejar saltos y tabulaciones. En un símbolo, no.
_PROSE_WHITESPACE = {"\t", "\n", "\r"}
_EPSILON_NAMES = {"ε", "λ", "lambda", "epsilon", "eps"}
_QUESTION_MARKS = {"?", "？"}
# Dígitos de ancho completo. No es un NFKC general: el jamo de compatibilidad
# sigue siendo otro carácter. Acá solo el 0–9 que un teclado ancho escribe igual.
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _folded_epsilon(text: str) -> bool:
    return text.casefold() in _EPSILON_NAMES


def is_epsilon_symbol(symbol: str) -> bool:
    """True si el texto es épsilon, no un símbolo del alfabeto.

    Entra la palabra (epsilon, lambda, eps), la épsilon lunada —su casefold
    ya es ε— y los glifos de compatibilidad: la épsilon matemática (U+1D6C6
    y familia) y la épsilon con acento (έ). No se pliegan letras de otro
    alfabeto que solo se parecen: «ɛ» y la ucraniana «є» siguen siendo símbolos.
    """
    # ASCII no trae ε, λ ni marcas. El caso común (0, 1, a) no pasa por NFKC.
    if symbol.isascii():
        cleaned = symbol.strip()
        if not cleaned:
            return False
        return cleaned.casefold() in _EPSILON_NAMES
    cleaned = unicodedata.normalize("NFC", symbol.strip())
    if not cleaned:
        return False
    if _folded_epsilon(cleaned):
        return True
    compatible = unicodedata.normalize("NFKC", cleaned)
    if compatible != cleaned and _folded_epsilon(compatible):
        return True
    base = "".join(
        char
        for char in unicodedata.normalize("NFKD", cleaned)
        if unicodedata.category(char) != "Mn"
    )
    return bool(base) and base != cleaned and _folded_epsilon(base)


_ALPHABET_CUE = re.compile(
    r"(?:sobre|alfabeto|s[ií]mbolos|sigma|Σ)\b",
    re.IGNORECASE,
)
_BRACE_SET = re.compile(r"\{([^{}]*)\}")


def is_control_or_invisible(char: str) -> bool:
    """True para controles, formatos invisibles, surrogates y no-caracteres."""
    if len(char) != 1:
        return False
    if unicodedata.category(char) in {"Cc", "Cf", "Cs"}:
        return True
    code = ord(char)
    if 0xFDD0 <= code <= 0xFDEF:
        return True
    return code & 0xFFFE == 0xFFFE


def xml_char_allowed(char: str) -> bool:
    """Char de XML 1.0: tab, LF, CR y el resto del plano que el estándar deja."""
    code = ord(char)
    return (
        code in (0x9, 0xA, 0xD)
        or 0x20 <= code <= 0xD7FF
        or 0xE000 <= code <= 0xFFFD
        or 0x10000 <= code <= 0x10FFFF
    )


def xml_text(value: str) -> str:
    return "".join(char for char in value if xml_char_allowed(char))


def strip_invisibles(text: str) -> str:
    """Saca controles, formatos y surrogates. Deja el espacio, el salto y el tab."""
    return "".join(
        char
        for char in text
        if char in _PROSE_WHITESPACE or char == " " or not is_control_or_invisible(char)
    )


def strip_marks_before_question(text: str) -> str:
    """Un acento pegado al ? no es parte de la expresión ni de la palabra.

    «unos» + acento + «?» se componía en «unoś» y la familia dejaba de ser
    paridad. La marca que está justo antes del signo de pregunta se tira.
    """
    chars = list(text)
    out: list[str] = []
    index = 0
    total = len(chars)
    while index < total:
        if unicodedata.category(chars[index]) == "Mn":
            end = index
            while end < total and unicodedata.category(chars[end]) == "Mn":
                end += 1
            if end < total and chars[end] in _QUESTION_MARKS:
                index = end
                continue
        out.append(chars[index])
        index += 1
    return "".join(out)


def fold_fullwidth_digits(text: str) -> str:
    return text.translate(_FULLWIDTH_DIGITS)


def fold_fullwidth_question(text: str) -> str:
    return text.replace("？", "?")


def question_tail(text: str) -> str:
    """Lo que sigue a un ?, sin marcas, invisibles ni la puntuación de cierre."""
    index = 0
    while index < len(text):
        char = text[index]
        if unicodedata.category(char) in {"Mn", "Cf", "Cc"} or char in " \t.,;:!?¡¿»«\"'？":
            index += 1
            continue
        break
    return text[index:].strip(" \t.,;:!?¡¿»«\"'？")


def strip_prose(value: str) -> str:
    kept: list[str] = []
    for char in value:
        if char in _PROSE_WHITESPACE or not is_control_or_invisible(char):
            kept.append(char)
    return "".join(kept)


def alphabet_symbol_issue(symbol: str) -> str | None:
    if any(is_control_or_invisible(char) for char in symbol):
        return "Hay un símbolo con un carácter de control o invisible."
    if symbol.strip() == "":
        return "Hay un símbolo vacío o invisible en el alfabeto."
    if is_epsilon_symbol(symbol):
        return None
    return None


def read_symbol_issue(symbol: str) -> str | None:
    if symbol.strip() == "" or is_epsilon_symbol(symbol):
        return None
    if any(is_control_or_invisible(char) for char in symbol):
        return "Hay un símbolo con un carácter de control o invisible."
    return None


def declared_alphabet(text: str) -> list[str] | None:
    """El alfabeto escrito en el enunciado, si hay un conjunto de símbolos.

    `sobre {0, 1}` y `alfabeto {a, b}` cuentan. Un `{5}` suelto no: puede ser
    el módulo, no el alfabeto. Un conjunto de dos o más símbolos de un
    carácter también cuenta, aunque no diga «sobre».
    """
    for match in _BRACE_SET.finditer(text):
        symbols = _symbols_in_set(match.group(1))
        if not symbols:
            continue
        prefix = text[max(0, match.start() - 48) : match.start()]
        if _ALPHABET_CUE.search(prefix) or len(symbols) >= 2:
            return symbols
    return None


_NOT_IN_ALPHABET = re.compile(r"«([^»]+)» no está en el alfabeto")


def without_contradictory_alphabet_errors(statement: str, errors: list[str]) -> list[str]:
    """Si el enunciado declara un símbolo, no se dice que ese símbolo no existe.

    El caso que se vio con gemma3:1b: primero «a» no está declarado en {0, 1}
    y, en el mismo pedido, «0» no está en el alfabeto. Las dos frases no pueden
    convivir: 0 sí está en el enunciado.
    """
    declared = declared_alphabet(statement)
    if not declared:
        return errors
    allowed = set(declared)
    mentions_extra = any("no declara" in error for error in errors)
    kept: list[str] = []
    for error in errors:
        match = _NOT_IN_ALPHABET.search(error)
        if match and match.group(1) in allowed:
            if mentions_extra:
                continue
            symbol = match.group(1)
            rewritten = (
                f"El enunciado incluye «{symbol}» en el alfabeto "
                f"{{{', '.join(declared)}}}. El resultado tiene que leerlo."
            )
            if rewritten not in kept:
                kept.append(rewritten)
            continue
        if error not in kept:
            kept.append(error)
    return kept


def overflow_message(statement: str, symbols: list[str]) -> str | None:
    declared = declared_alphabet(statement)
    if not declared:
        return None
    allowed = set(declared)
    extras: list[str] = []
    for symbol in symbols:
        if symbol in allowed or symbol in extras:
            continue
        extras.append(symbol)
    if not extras:
        return None
    pedido = "{" + ", ".join(declared) + "}"
    shown = ", ".join(_symbol_label(symbol) for symbol in extras)
    note = ""
    if any(symbol in repetition_digits(statement) for symbol in extras):
        note = " El número delante de un símbolo es una repetición, no un símbolo del alfabeto."
    return (
        f"El alfabeto del resultado no puede pasar de {pedido}. "
        f"Hay símbolos que el enunciado no declara: {shown}."
        + note
    )


# «tres», «un», «una»: la cantidad. «cero» no entra: es el símbolo 0.
SPANISH_COUNTS = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "treinta": 30,
}

# El nombre del símbolo, en singular o plural. «es» no entra: es el verbo.
SYMBOL_NAMES = {
    "cero": "0",
    "ceros": "0",
    "uno": "1",
    "unos": "1",
    "aes": "a",
    "bes": "b",
    "ces": "c",
    "des": "d",
}

_CONJUNCTIONS = {"y", "e", "o", "u"}
# «2º» y «2ª» son ordinales, no el símbolo repetido dos veces.
_ORDINAL_SIGNS = {"º", "ª", "°"}
_FOLD_ACCENTS = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunaeiouun")


def spanish_count(token: str) -> int | None:
    return SPANISH_COUNTS.get(token)


def symbol_name(token: str) -> str | None:
    return SYMBOL_NAMES.get(token)


def repetition_reading(number: str, symbol_token: str, alphabet: set[str] | None) -> str:
    """'count', 'ambiguous' o 'no'.

    Un dígito o una palabra («3», «tres», «un») delante de un símbolo es una
    repetición cuando ese número no está en el alfabeto, o cuando el contexto
    lo dice («tres ceros», «3 ceros», «dos unos»). Si el dígito sí es un
    símbolo declarado, «3 0» es ambiguo: puede ser el símbolo 3 y después 0.
    """
    if symbol_token in _ORDINAL_SIGNS:
        return "no"
    if symbol_token in _CONJUNCTIONS and (alphabet is None or symbol_token not in alphabet):
        return "no"
    named = symbol_token in SYMBOL_NAMES
    if not named and not (len(symbol_token) == 1 and symbol_token.isalnum()):
        return "no"
    if number in SPANISH_COUNTS:
        return "count"
    if not number.isdigit():
        return "no"
    if named or len(number) != 1:
        return "count"
    if alphabet is not None and number not in alphabet:
        return "count"
    return "ambiguous"


def repetition_digits(statement: str) -> list[str]:
    """Dígitos del enunciado que se leen como cantidad, no como símbolo."""
    declared = declared_alphabet(statement)
    alphabet = set(declared) if declared else None
    text = unicodedata.normalize("NFC", statement.strip().lower()).translate(_FOLD_ACCENTS)
    text = _BRACE_SET.sub(" ", text)
    tokens = re.findall(r"[0-9０-９a-z]+", text)
    found: list[str] = []
    for index, token in enumerate(tokens[:-1]):
        token = fold_fullwidth_digits(token)
        if not token.isdigit():
            continue
        if repetition_reading(token, tokens[index + 1], alphabet) != "count":
            continue
        if token not in found:
            found.append(token)
    return found


def ambiguous_repetition_message(number: str, symbol_token: str, alphabet: list[str] | None) -> str:
    """Aviso en español cuando «3 0» puede ser símbolo o cantidad."""
    if alphabet:
        pedido = "{" + ", ".join(alphabet) + "}"
        return (
            f"«{number} {symbol_token}» es ambiguo: «{number}» está en el alfabeto {pedido}, "
            f"así que puede ser el símbolo {number} seguido de {symbol_token}, o una repetición. "
            "Para la repetición escribí la cantidad en palabras, por ejemplo «tres ceros»."
        )
    return (
        f"«{number} {symbol_token}» es ambiguo: no está declarado el alfabeto y «{number}» "
        "puede ser un símbolo o una cantidad. Declará el alfabeto, como {0, 1}, "
        "o escribí «tres ceros» si querés la repetición."
    )


def _symbols_in_set(body: str) -> list[str] | None:
    parts = [unicodedata.normalize("NFC", part.strip()) for part in body.split(",")]
    if not parts or any(part == "" for part in parts):
        return None
    if any(len(part) != 1 or is_control_or_invisible(part) for part in parts):
        return None
    symbols: list[str] = []
    for part in parts:
        if part not in symbols:
            symbols.append(part)
    return symbols


def _symbol_label(symbol: str) -> str:
    if symbol == "\\":
        return "«\\»"
    if symbol == "" or symbol.strip() == "" or all(
        is_control_or_invisible(char) or char.isspace() for char in symbol
    ):
        return "un símbolo vacío o invisible"
    visible = "".join(char for char in symbol if not is_control_or_invisible(char))
    if not visible:
        return "un símbolo vacío o invisible"
    return f"«{visible}»"
