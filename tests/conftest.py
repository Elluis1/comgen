import pytest

from app.memory import set_memory_path


@pytest.fixture(autouse=True)
def isolated_memory(tmp_path):
    """Cada test ve una memoria vacía y no el solutions.json del repositorio."""
    set_memory_path(tmp_path / "solutions.json")
    yield
    set_memory_path(None)
