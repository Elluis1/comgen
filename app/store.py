import asyncio
import threading
import uuid
from dataclasses import dataclass, field

from app.schemas import FiniteAutomaton


@dataclass
class Session:
    id: str
    ui: list[dict] = field(default_factory=list)
    model_messages: list[dict] = field(default_factory=list)
    automaton: FiniteAutomaton | None = None
    warnings: list[str] = field(default_factory=list)
    last_request: str = ""
    current_statement: str = ""
    remembered: bool = False
    recalled: list[str] = field(default_factory=list)
    # .jff de Turing cargado en esta sesión. No es el autómata de la materia.
    machine: object | None = None


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._guards: dict[str, threading.RLock] = {}
        # create() corre en un hilo del pool; get() también. El dict no se toca suelto.
        self._registry = threading.Lock()

    def create(self) -> Session:
        session_id = uuid.uuid4().hex
        session = Session(id=session_id)
        with self._registry:
            self._sessions[session_id] = session
            self._locks[session_id] = asyncio.Lock()
            self._guards[session_id] = threading.RLock()
            self._evict_overflow()
        return session

    def _evict_overflow(self) -> None:
        extra = len(self._sessions) - MAX_SESSIONS
        if extra <= 0:
            return
        newest = next(reversed(self._sessions), None)
        candidates = [session_id for session_id in self._sessions if session_id != newest]
        empty = [
            session_id
            for session_id in candidates
            if self._sessions[session_id].automaton is None
            and self._sessions[session_id].machine is None
            and not self._sessions[session_id].ui
        ]
        victims: list[str] = []
        for session_id in empty:
            if len(victims) >= extra:
                break
            victims.append(session_id)
        if len(victims) < extra:
            for session_id in candidates:
                if session_id in victims:
                    continue
                victims.append(session_id)
                if len(victims) >= extra:
                    break
        for session_id in victims:
            self._sessions.pop(session_id, None)
            self._locks.pop(session_id, None)
            self._guards.pop(session_id, None)

    def get(self, session_id: str) -> Session:
        with self._registry:
            try:
                return self._sessions[session_id]
            except KeyError as exc:
                raise KeyError(session_id) from exc

    def lock(self, session_id: str) -> asyncio.Lock:
        with self._registry:
            try:
                return self._locks[session_id]
            except KeyError as exc:
                raise KeyError(session_id) from exc

    def guard(self, session_id: str) -> threading.RLock:
        """Candado de hilos. Los endpoints sync no ven el asyncio.Lock."""
        with self._registry:
            try:
                return self._guards[session_id]
            except KeyError as exc:
                raise KeyError(session_id) from exc


# Cada carga de la página abre una sesión y no la cierra. Sin un tope, un
# cliente que repite POST /api/sessions se queda con todos los candados.
# 128 alcanza para recargar la materia un rato. Primero se van las vacías,
# así el autómata que se está editando sobrevive a las recargas.
MAX_SESSIONS = 128


store = SessionStore()
