import logging
import os
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("comgen")

# El tamaño va en el tag (`:7b`, `:0.5b`), no en el nombre de la familia (`llama3.2`).
_PARAMETER_BILLIONS = re.compile(r"(?:^|[^0-9.])(\d+(?:\.\d+)?)b(?:[^a-z]|$)")
# Avisamos si el tag pasa de 3B. `3b` sigue en silencio; `4b`, `7b` y `8b` avisan.
LARGE_MODEL_BILLIONS = 3.0
_warned_models: set[str] = set()


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# gemma3:1b: alrededor de 1B, cuantizado, y el que mejor siguió el español en la medición.
DEFAULT_OLLAMA_MODEL = "gemma3:1b"


def model_parameter_billions(model: str) -> float | None:
    found = _PARAMETER_BILLIONS.findall(model.casefold())
    if not found:
        return None
    return float(found[-1])


def warn_if_model_is_large(model: str) -> None:
    billions = model_parameter_billions(model)
    if billions is None or billions <= LARGE_MODEL_BILLIONS or model in _warned_models:
        return
    _warned_models.add(model)
    shown = str(int(billions)) if billions == int(billions) else str(billions)
    logger.warning(
        "El modelo %s declara unos %sB, por encima de los 3 mil millones de parámetros. "
        "No se recomienda en una notebook modesta: el default es %s. "
        "La generación sigue con el modelo que configuraste.",
        model,
        shown,
        DEFAULT_OLLAMA_MODEL,
    )


class Settings:
    def __init__(self) -> None:
        self.ollama_host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        self.ollama_model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        self.ollama_timeout_seconds = float(os.environ.get("OLLAMA_TIMEOUT", "180"))
        warn_if_model_is_large(self.ollama_model)


@lru_cache
def get_settings() -> Settings:
    load_dotenv()
    return Settings()
