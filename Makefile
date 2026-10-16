PYTHON ?= python3
PYTHONPATH := src

.PHONY: test lint

test:
	NETWORK_DISABLED=1 PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest -q

lint:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests
