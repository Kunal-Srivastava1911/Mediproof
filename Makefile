# MediProof task runner. On Windows without make, use ./run.ps1 <target> (mirrors this file).

ifeq ($(OS),Windows_NT)
    PYTHON ?= .venv/Scripts/python.exe
else
    PYTHON ?= .venv/bin/python
endif
export PYTHONPATH := $(CURDIR)

.PHONY: help venv install install-dev datagen-sample datagen-bulk \
        test test-datagen test-schemas eval demo lint fmt clean

help:
	@echo "MediProof targets:"
	@echo "  install         core deps into .venv"
	@echo "  install-dev     core + datagen + dev deps + playwright chromium"
	@echo "  datagen-sample  render one sample claim -> data/sample (W1 DoD)"
	@echo "  datagen-bulk    render the benchmark set -> data/bench"
	@echo "  test            run the full pytest suite"
	@echo "  test-<module>   run one module's tests (e.g. make test-datagen)"
	@echo "  eval            regenerate README benchmark tables"
	@echo "  demo            build compose + seed a claim + open the dashboard"

venv:
	python -m venv .venv

install:
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install -e ".[datagen,dev]"
	$(PYTHON) -m playwright install chromium

datagen-sample:
	$(PYTHON) -m datagen.cli sample --seed 42 --out data/sample

datagen-bulk:
	$(PYTHON) -m datagen.cli bulk --count 300 --start-seed 1000 --out data/bench

test:
	$(PYTHON) -m pytest

test-datagen:
	$(PYTHON) -m pytest tests/datagen -v

test-schemas:
	$(PYTHON) -m pytest tests/schemas -v

eval:
	@echo "eval harness lands in W3+ (see evals/README.md)"

demo:
	@echo "make demo lands in W7 (compose + seeded claim + dashboard)"

lint:
	$(PYTHON) -m ruff check .

fmt:
	$(PYTHON) -m ruff format .

clean:
	$(PYTHON) -c "import shutil,glob; [shutil.rmtree(p,ignore_errors=True) for p in glob.glob('**/__pycache__',recursive=True)]"
