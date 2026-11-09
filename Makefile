# Corre la suite sin Ollama y sin atarse a GitHub Actions.
#   make install
#   make test

PYTHON ?= python3
PY := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo $(PYTHON); fi)

.PHONY: install test

install:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -r requirements.txt

test:
	$(PY) -m pytest
