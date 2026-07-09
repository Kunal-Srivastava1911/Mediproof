# MediProof task runner. On Windows without make, use ./run.ps1 <target> (mirrors this file).

ifeq ($(OS),Windows_NT)
    PYTHON ?= .venv/Scripts/python.exe
else
    PYTHON ?= .venv/bin/python
endif
export PYTHONPATH := $(CURDIR)

.PHONY: help venv install install-dev install-pipeline datagen-sample datagen-bulk \
        test test-fast test-datagen test-schemas test-pipeline test-m1 test-m2 test-m3 \
        test-m4 test-m5 eval demo lint fmt clean

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
	$(PYTHON) -m pip install -e ".[datagen,pipeline,api,dev]"
	$(PYTHON) -m playwright install chromium

install-pipeline:
	$(PYTHON) -m pip install -e ".[pipeline]"

datagen-sample:
	$(PYTHON) -m datagen.cli sample --seed 42 --out data/sample

datagen-bulk:
	$(PYTHON) -m datagen.cli bulk --count 300 --start-seed 1000 --out data/bench

test:
	$(PYTHON) -m pytest

test-fast:
	$(PYTHON) -m pytest -m "not slow"

test-datagen:
	$(PYTHON) -m pytest tests/datagen -v

test-schemas:
	$(PYTHON) -m pytest tests/schemas -v

test-pipeline:
	$(PYTHON) -m pytest tests/pipeline -v

test-m1:
	$(PYTHON) -m pytest tests/pipeline/test_m1_ingest.py -v

test-m2:
	$(PYTHON) -m pytest tests/pipeline/test_m2_segment.py -v

test-m3:
	$(PYTHON) -m pytest tests/pipeline/test_m3_extract.py tests/pipeline/test_m3_grounding.py -v

test-m4:
	$(PYTHON) -m pytest tests/pipeline/test_m4_audit.py -v

test-m5:
	$(PYTHON) -m pytest tests/pipeline/test_m5_complete.py -v

eval:
	$(PYTHON) -m evals.cli --out data/bench_eval --readme README.md --results evals/RESULTS.md

demo:
	$(PYTHON) -m datagen.cli sample --fault inflated_line_item --out data/demo
	docker compose up -d --build
	$(PYTHON) scripts/demo_seed.py
	@echo "Dashboard: http://localhost:5173   API: http://localhost:8000"

lint:
	$(PYTHON) -m ruff check .

fmt:
	$(PYTHON) -m ruff format .

clean:
	$(PYTHON) -c "import shutil,glob; [shutil.rmtree(p,ignore_errors=True) for p in glob.glob('**/__pycache__',recursive=True)]"
