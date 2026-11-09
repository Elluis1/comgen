import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import ROOT
from app.sanitize import declared_alphabet

_LOCK = threading.Lock()
_OVERRIDE: Path | None = None
_STOPWORDS = {
    "un", "una", "el", "la", "los", "las", "que", "de", "del", "por", "con",
    "y", "en", "para", "me", "des", "quiero", "afd", "afn", "dfa", "nfa",
    "automata", "autómata", "finito", "finitos", "cadenas", "cadena",
    "acepte", "aceptar", "dame", "genera", "generar",
}


class MemoryStoreError(Exception):
    """El archivo de memoria existe pero no se puede interpretar."""


_DAMAGED = "La memoria compartida está dañada. No la pisé; revisá memory/solutions.json."
# Un curso entero entra holgado. Por encima de esto no se lee ni se pisa.
_MAX_MEMORY_BYTES = 2_000_000


def set_memory_path(path: Path | None) -> None:
    global _OVERRIDE
    _OVERRIDE = path


_FRAME_WORDS = {
    "comience", "empiece", "arranque", "inicie", "siga", "seguido", "seguida",
    "luego", "despues", "termine", "acaba", "acabe",
}


def search(text: str, limit: int = 3) -> list[dict]:
    query = _tokens(text)
    query_expr = _expression_tokens(query)
    query_body = query - _FRAME_WORDS
    if not query and not query_expr:
        return []
    allowed = _allowed_symbols(text)
    ranked: list[tuple[float, dict]] = []
    for entry in _read():
        if not isinstance(entry.get("request"), str):
            continue
        if allowed is not None and not _alphabet_fits(entry, allowed):
            continue
        known = _token_set(entry)
        known_expr = _expression_tokens(known)
        if query_expr or known_expr:
            if not query_expr or not known_expr:
                continue
            shared = query_expr & known_expr
            if not shared:
                continue
            score = len(shared) / len(query_expr | known_expr)
            if score < 0.8:
                continue
        else:
            shared = query_body & (known - _FRAME_WORDS)
            if len(shared) < 2:
                continue
            score = len(shared) / len(query_body | (known - _FRAME_WORDS))
            if score < 0.45:
                continue
        ranked.append((score, entry))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [entry for _score, entry in ranked[:limit]]


def save(request: str, explanation: str, automaton: dict, pattern: str = "") -> dict:
    cleaned = request.strip()
    if not cleaned:
        raise ValueError("No hay un enunciado para guardar.")
    entry = {
        "id": uuid.uuid4().hex,
        "request": cleaned,
        "tokens": sorted(_tokens(cleaned)),
        "pattern": pattern.strip(),
        "explanation": explanation.strip(),
        "automaton": automaton,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _LOCK:
        path = _path()
        # Si el archivo está dañado, no lo pisamos con una lista nueva.
        if path.exists() and not path.is_file():
            raise MemoryStoreError(_DAMAGED)
        entries = _load(path) if path.is_file() else []
        incoming = set(entry["tokens"])
        replaced = False
        for index, current in enumerate(entries):
            known = _token_set(current)
            if not incoming or not known:
                continue
            score = len(incoming & known) / len(incoming | known)
            if score >= 0.8:
                previous = current.get("id")
                if isinstance(previous, str) and previous:
                    entry["id"] = previous
                entries[index] = entry
                replaced = True
                break
        if not replaced:
            entries.append(entry)
        _write(entries)
    return entry


def count() -> int:
    return len(_read())


def recent(limit: int = 5) -> list[dict]:
    entries = _read()
    chosen = entries[-limit:]
    rows = []
    for entry in reversed(chosen):
        request = entry.get("request", "")
        pattern = entry.get("pattern", "")
        rows.append(
            {
                "request": request if isinstance(request, str) else "",
                "pattern": pattern if isinstance(pattern, str) else "",
            }
        )
    return rows


def _allowed_symbols(text: str) -> set[str] | None:
    declared = declared_alphabet(text)
    if not declared:
        return None
    return {symbol.casefold() for symbol in declared}


def _alphabet_fits(entry: dict, allowed: set[str]) -> bool:
    """Una solución guardada no puede traer símbolos que el enunciado no declara."""
    automaton = entry.get("automaton")
    if not isinstance(automaton, dict):
        return True
    alphabet = automaton.get("alphabet")
    if not isinstance(alphabet, list):
        return True
    for symbol in alphabet:
        cleaned = str(symbol).strip()
        if cleaned and cleaned.casefold() not in allowed:
            return False
    return True


def _expression_tokens(tokens: set[str]) -> set[str]:
    return {token for token in tokens if re.search(r"[*+?|()|]", token)}


def _tokens(text: str) -> set[str]:
    folded = text.casefold().translate(str.maketrans("áéíóúüñ", "aeiouun"))
    words = re.findall(r"[a-z0-9*+?|()]+", folded)
    return {word for word in words if word not in _STOPWORDS and len(word) > 1}


def _path() -> Path:
    if _OVERRIDE is not None:
        return _OVERRIDE
    return ROOT / "memory" / "solutions.json"


def _read() -> list[dict]:
    path = _path()
    if not path.is_file():
        return []
    try:
        return _load(path)
    except MemoryStoreError:
        return []


def _token_set(entry: dict) -> set[str]:
    tokens = entry.get("tokens", [])
    if not isinstance(tokens, list):
        return set()
    return {token for token in tokens if isinstance(token, str)}


def _entry_ok(entry: dict) -> bool:
    """False si un campo que después se recorre no tiene el tipo esperado."""
    tokens = entry.get("tokens", [])
    if not isinstance(tokens, list) or not all(isinstance(item, str) for item in tokens):
        return False
    for key in ("request", "pattern", "explanation", "id"):
        if key in entry and entry[key] is not None and not isinstance(entry[key], str):
            return False
    automaton = entry.get("automaton")
    if automaton is not None and not isinstance(automaton, dict):
        return False
    return True


def _load(path: Path) -> list[dict]:
    try:
        if path.stat().st_size > _MAX_MEMORY_BYTES:
            raise MemoryStoreError(
                "La memoria compartida es demasiado grande. No la pisé; revisá memory/solutions.json."
            )
        # utf-8-sig: el Bloc de notas guarda el BOM y json.loads no lo acepta.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except MemoryStoreError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise MemoryStoreError(_DAMAGED) from exc
    if not isinstance(data, dict):
        raise MemoryStoreError(_DAMAGED)
    entries = data.get("solutions", [])
    if not isinstance(entries, list) or not all(isinstance(item, dict) and _entry_ok(item) for item in entries):
        raise MemoryStoreError(_DAMAGED)
    return entries


def _write(entries: list[dict]) -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"solutions": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise MemoryStoreError(_DAMAGED) from exc
