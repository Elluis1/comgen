import httpx

from app.config import Settings
from app.prompts import JSON_SCHEMA


class OllamaError(Exception):
    pass


class OllamaBadRequest(OllamaError):
    pass


class OllamaEmpty(OllamaError):
    pass


class OllamaBadPayload(OllamaError):
    """Llegó HTTP, pero el cuerpo no es el JSON de un mensaje."""


# Temperatura 0, contexto corto y un tope de tokens: un modelo chico
# se equivoca menos en el JSON, no reserva los 32K o 128K del Modelfile
# y no se queda generando transiciones sin cerrar el objeto.
GENERATION_OPTIONS = {"temperature": 0, "num_ctx": 4096, "num_predict": 768}


async def chat(settings: Settings, messages: list[dict]) -> str:
    base = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "options": dict(GENERATION_OPTIONS),
    }
    try:
        return await _post(settings, {**base, "format": JSON_SCHEMA})
    except (OllamaBadRequest, OllamaEmpty, OllamaBadPayload):
        return await _post(settings, {**base, "format": "json"})


async def list_models(settings: Settings) -> list[str]:
    url = f"{settings.ollama_host}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OllamaError(str(exc)) from exc
    try:
        payload = response.json()
    except RecursionError as exc:
        raise OllamaError("Ollama no devolvió JSON.") from exc
    except ValueError as exc:
        raise OllamaError("Ollama no devolvió JSON.") from exc
    return _model_names(payload)


async def _post(settings: Settings, payload: dict) -> str:
    url = f"{settings.ollama_host}/api/chat"
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            response = await client.post(url, json=payload)
    except httpx.ConnectError as exc:
        raise OllamaError(
            f"No pude conectar con Ollama en {settings.ollama_host}. "
            "Instalalo, abrí la aplicación y descargá un modelo antes de generar desde texto."
        ) from exc
    except httpx.TimeoutException as exc:
        raise OllamaError("Ollama tardó demasiado en responder. Probá de nuevo o usá un modelo más chico.") from exc
    except httpx.HTTPError as exc:
        raise OllamaError(f"Ollama no respondió: {exc}") from exc

    if response.status_code == 400:
        raise OllamaBadRequest(response.text)
    if response.status_code == 404:
        raise OllamaError(
            f"Ollama no tiene el modelo {settings.ollama_model}. "
            f"Descargalo con: ollama pull {settings.ollama_model}"
        )
    if response.status_code >= 400:
        raise OllamaError(f"Ollama devolvió un error {response.status_code}.")

    return _message_content(response)


def _message_content(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except RecursionError as exc:
        raise OllamaBadPayload("Ollama no devolvió JSON.") from exc
    except ValueError as exc:
        raise OllamaBadPayload("Ollama no devolvió JSON.") from exc
    if not isinstance(payload, dict):
        raise OllamaBadPayload("Ollama no devolvió JSON.")
    message = payload.get("message")
    if not isinstance(message, dict):
        raise OllamaBadPayload("Ollama no devolvió un mensaje.")
    content = message.get("content", "")
    if not isinstance(content, str):
        raise OllamaBadPayload("Ollama no devolvió un mensaje.")
    if not content.strip():
        raise OllamaEmpty("Ollama respondió vacío.")
    return content


def _model_names(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        raise OllamaError("Ollama no devolvió JSON.")
    models = payload.get("models", [])
    if not isinstance(models, list):
        raise OllamaError("Ollama no devolvió JSON.")
    names: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        if isinstance(name, str) and name:
            names.append(name)
    return names
