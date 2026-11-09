from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import get_settings
from app.ollama_client import OllamaError, list_models
from app.service import (
    SessionNotFound,
    create_session,
    determinize_session,
    export_grammar_session,
    export_session,
    grammar_session,
    regex_session,
    handle_message,
    list_examples,
    load_example,
    remember_solution,
    export_turing_session,
    import_turing_session,
    reset_session,
    run_turing_session,
    run_word,
)
from app.turing_jflap import MAX_XML_BYTES, TuringJflapError
from app.memory import MemoryStoreError
from app.memory import count as memory_count
from app.memory import recent as memory_recent

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Al arrancar, si el modelo pasa de ~3B, el aviso queda en el log y el servidor sigue.
    get_settings()
    yield


app = FastAPI(title="Comgen", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class MessageIn(BaseModel):
    text: str = ""


class WordIn(BaseModel):
    word: str = Field(default="")


class TuringWordIn(BaseModel):
    word: str = Field(default="")
    trace: bool = False


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health() -> dict:
    settings = get_settings()
    try:
        names = await list_models(settings)
    except OllamaError:
        return {
            "online": False,
            "model": settings.ollama_model,
            "model_ready": False,
            "models": [],
        }
    ready = settings.ollama_model in names
    return {
        "online": True,
        "model": settings.ollama_model,
        "model_ready": ready,
        "models": names,
    }


@app.get("/api/examples")
def examples() -> list[dict]:
    return list_examples()


@app.get("/api/memory")
def stored_solutions() -> dict:
    return {"count": memory_count(), "recent": memory_recent()}


@app.post("/api/sessions/{session_id}/remember")
def post_remember(session_id: str) -> dict:
    try:
        return remember_solution(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except MemoryStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/sessions")
def open_session() -> dict:
    session = create_session()
    return {"id": session.id}


@app.post("/api/sessions/{session_id}/reset")
async def post_reset(session_id: str) -> dict:
    try:
        return await reset_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc


@app.post("/api/sessions/{session_id}/messages")
async def post_message(session_id: str, body: MessageIn) -> dict:
    try:
        return await handle_message(session_id, body.text)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/examples/{example_id}")
def post_example(session_id: str, example_id: str) -> dict:
    try:
        return load_example(session_id, example_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Ese ejemplo no existe.") from exc


@app.post("/api/sessions/{session_id}/simulate")
def post_simulate(session_id: str, body: WordIn) -> dict:
    try:
        return run_word(session_id, body.word)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/determinize")
def post_determinize(session_id: str) -> dict:
    try:
        return determinize_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/regex")
def post_regex(session_id: str) -> dict:
    try:
        return regex_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/grammar")
def post_grammar(session_id: str) -> dict:
    try:
        return grammar_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/grammar/export")
def get_grammar_export(session_id: str) -> Response:
    try:
        filename, xml = export_grammar_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _body_up_to(request: Request, limit: int) -> bytes:
    """Lee de a pedazos y corta en cuanto el cuerpo pasa el tope.

    Sirve también si no hay Content-Length, como en un cuerpo en chunks.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        # ¹, ² y ³ pasan isdigit() y int() tira. Solo entran dígitos ASCII.
        if not declared.isascii() or not declared.isdecimal():
            raise HTTPException(status_code=400, detail="El tamaño del archivo no es un número.")
        if len(declared) > 8 or int(declared) > limit:
            raise HTTPException(status_code=400, detail="El archivo es demasiado grande.")
    parts: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=400, detail="El archivo es demasiado grande.")
        parts.append(chunk)
    return b"".join(parts)


@app.post("/api/sessions/{session_id}/turing")
async def post_turing(session_id: str, request: Request) -> dict:
    raw = await _body_up_to(request, MAX_XML_BYTES)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="El archivo no es XML en UTF-8.") from exc
    try:
        return import_turing_session(session_id, text)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except TuringJflapError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/turing/run")
def post_turing_run(session_id: str, body: TuringWordIn) -> dict:
    try:
        return run_turing_session(session_id, body.word, trace=body.trace)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/turing/export")
def get_turing_export(session_id: str) -> Response:
    try:
        filename, xml = export_turing_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{session_id}/export")
def get_export(session_id: str) -> Response:
    try:
        filename, xml = export_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="La sesión no existe. Recargá la página.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
