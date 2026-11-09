# Corto a propósito: el default es gemma3:1b y el contexto que pedimos es de 4096 tokens.
SYSTEM_PROMPT = """
Convertís un enunciado en español al JSON de un autómata finito. Devolvé solo el objeto.

Claves: kind, pattern, description, explanation, deterministic, alphabet, states, transitions. En un spec también family, base, modulus, remainder, word, symbol, blocks.

- kind "regex": hay una expresión o bloques (a*, bbb*, cc*, ab+, (a|b)*abb, "comience por", "siga con", "termine con"). pattern es obligatorio y no va vacío: concatená los bloques en orden, sin espacios ni palabras. "comience por c, siga por aa* y termine con b*" → "caa*b*". "a* siga con bbb* y termine con cc*" → "a*bbb*cc*". Con paréntesis o barra, copiá el bloque igual: "(ab|ba)*" + "aaa*" + "(c|bb)*" → "(ab|ba)*aaa*(c|bb)*". states y transitions van en [].
- kind "spec": divisibilidad, resto, cantidad, longitud, termina, empieza, contiene o secuencia. No dibujes flechas. family y los parámetros; states y transitions van en []. Secuencia: family "secuencia", blocks con symbol y repeat ("*", "+" o "3"). «3 0» y «tres ceros» repiten el símbolo: el número no entra al alfabeto.
- kind "fa": no es una expresión ni una de esas familias. pattern va "". Armá los estados de ese lenguaje. Si el enunciado no es el del ejemplo, no copies sus transiciones.
- kind "unsupported": gramática, autómata de pila o máquina de Turing.

description: frase corta. explanation: qué representa cada estado, en español y breve.
deterministic: true si es un AFD. alphabet: símbolos de un carácter.
states: {id, initial, final}. Exactamente uno con initial true. ids q0, q1, q2…
transitions: {from, to, read}. read vacío es épsilon. En un AFD, una transición por símbolo y sin épsilon.
Si piden modificar el autómata actual, partí de ese JSON. Si no dicen el alfabeto, asumí uno y decilo en explanation.

Ejemplo. "comience por c siga por aa* y luego termine con b*":
{"kind":"regex","pattern":"caa*b*","description":"Cadenas de caa*b*","explanation":"c es obligatoria. aa* exige al menos una a. b* agrega bes o ninguna.","deterministic":true,"alphabet":[],"states":[],"transitions":[]}

Ejemplo fa (si el enunciado es otro, cambiá estados y flechas). "cadenas binarias con cantidad par de unos":
{"kind":"fa","pattern":"","description":"Cadenas binarias con cantidad par de unos","explanation":"q0 es par y final. q1 es impar. 0 no cambia; 1 alterna.","deterministic":true,"alphabet":["0","1"],"states":[{"id":"q0","initial":true,"final":true},{"id":"q1","initial":false,"final":false}],"transitions":[{"from":"q0","to":"q0","read":"0"},{"from":"q0","to":"q1","read":"1"},{"from":"q1","to":"q1","read":"0"},{"from":"q1","to":"q0","read":"1"}]}
""".strip()

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["regex", "spec", "fa", "unsupported"]},
        "pattern": {"type": "string"},
        "description": {"type": "string"},
        "explanation": {"type": "string"},
        "deterministic": {"type": "boolean"},
        "family": {"type": "string"},
        "base": {"type": "integer"},
        "modulus": {"type": "integer"},
        "remainder": {"type": "integer"},
        "word": {"type": "string"},
        "symbol": {"type": "string"},
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "repeat": {"type": "string"},
                },
                "required": ["symbol", "repeat"],
            },
        },
        "accept": {"type": "array", "items": {"type": "string"}},
        "reject": {"type": "array", "items": {"type": "string"}},
        "alphabet": {"type": "array", "items": {"type": "string"}},
        "states": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "initial": {"type": "boolean"},
                    "final": {"type": "boolean"},
                },
                "required": ["id", "initial", "final"],
            },
        },
        "transitions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "read": {"type": "string"},
                },
                "required": ["from", "to", "read"],
            },
        },
    },
    "required": [
        "kind",
        "pattern",
        "description",
        "explanation",
        "deterministic",
        "alphabet",
        "states",
        "transitions",
    ],
}


def memory_context(entries: list[dict]) -> str:
    if not entries:
        return ""
    blocks = [
        "Memoria compartida. Otras personas guardaron estas soluciones porque les funcionaron.",
        "Analizá el enunciado nuevo igual. Usá una solución guardada solo si el pedido es el mismo lenguaje.",
    ]
    for entry in entries:
        request = entry.get("request")
        if not isinstance(request, str) or not request:
            continue
        blocks.append(f"Pedido guardado: {request}")
        pattern = entry.get("pattern")
        if isinstance(pattern, str) and pattern:
            blocks.append(f"Expresión: {pattern}")
        explanation = entry.get("explanation") or ""
        if isinstance(explanation, str) and explanation.strip():
            blocks.append(explanation.strip()[:700])
    return "\n".join(blocks)


def repair_prompt(errors: list[str], original: str = "") -> str:
    listed = "\n".join(f"- {error}" for error in errors)
    enunciado = f"Enunciado original: {original}\n" if original else ""
    return (
        "Ese JSON no se puede exportar a JFLAP.\n"
        f"{enunciado}"
        f"Errores:\n{listed}\n"
        "Si hay bloques (comience por, siga por, siga con, termine con), "
        'devolvé kind "regex" y pattern concatenado, sin palabras. '
        'Ejemplo: comience por c, siga por aa* y termine con b* → {"kind":"regex","pattern":"caa*b*","states":[],"transitions":[]}. '
        'Con paréntesis o barras, copialos: (ab|ba)* luego aaa* y (c|bb)* es "(ab|ba)*aaa*(c|bb)*". '
        "states y transitions van vacíos. "
        "Si es divisibilidad, resto, cantidad, longitud, termina, empieza, contiene o una secuencia, "
        'devolvé kind "spec" con family y los parámetros, sin states. '
        'Secuencia: family "secuencia" y blocks [{symbol, repeat}]. '
        'infinitos X es "*", uno o más X es "+", «3 0» o «tres ceros» es repeat "3". '
        "Ese número no va en el alfabeto. "
        "Si no es una expresión, corregí el autómata y devolvé el JSON completo. "
        "No uses caracteres de control ni una barra invertida suelta. "
        "Si el enunciado declara un alfabeto, no agregues símbolos."
    )
