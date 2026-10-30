# MediProof task runner for Windows (mirrors the Makefile). Usage: ./run.ps1 <target>
param([Parameter(Position = 0)][string]$Target = "help")

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$env:PYTHONPATH = $Root

# First Python >= 3.11 on PATH: the py launcher, then python / python3.
function Find-Python {
    foreach ($cand in @("py -3.13", "py -3.12", "py -3.11", "python", "python3")) {
        $parts = $cand.Split(" ")
        if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
        $rest = if ($parts.Count -gt 1) { $parts[1..($parts.Count - 1)] } else { @() }
        $ok = & $parts[0] @rest -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
        if ($ok -eq "True") { return , $parts }
    }
    return $null
}

function Need-Venv {
    if (-not (Test-Path $Py)) {
        Write-Host "No .venv found. Run: ./run.ps1 venv; ./run.ps1 install-dev" -ForegroundColor Yellow
        exit 1
    }
}

switch ($Target) {
    "help" {
        Write-Host "MediProof targets (./run.ps1 <target>):"
        "  venv            create .venv",
        "  install-dev     core + datagen + dev deps + playwright chromium",
        "  datagen-sample  render one sample claim -> data/sample (W1 DoD)",
        "  datagen-bulk    render the benchmark set -> data/bench",
        "  test            run the full pytest suite",
        "  test-datagen    run datagen tests",
        "  demo            build compose + seed a claim + open the dashboard",
        "  score-models    score Gemini models on tests/testpack, keep the accurate ones (key)",
        "  record-testpack race the kept models over the test pack + demo, record replies (key)",
        "  testpack-check  verify every test-pack AI feature replays with no key",
        "  ai-pack         score-models, then record-testpack, then testpack-check",
        "  lint / fmt      ruff check / format" | ForEach-Object { Write-Host $_ }
    }
    "venv"           {
        $sys = Find-Python
        if (-not $sys) { Write-Host "Python 3.11+ not found. Install it from python.org, then retry." -ForegroundColor Red; exit 1 }
        $rest = if ($sys.Count -gt 1) { $sys[1..($sys.Count - 1)] } else { @() }
        Write-Host "Creating .venv with: $($sys -join ' ')"
        & $sys[0] @rest -m venv (Join-Path $Root ".venv")
    }
    "install"        { Need-Venv; & $Py -m pip install -e $Root }
    "install-dev"    { Need-Venv; & $Py -m pip install -e "$Root[datagen,pipeline,api,dev]"; & $Py -m playwright install chromium }
    "install-pipeline" { Need-Venv; & $Py -m pip install -e "$Root[pipeline]" }
    "datagen-sample" { Need-Venv; & $Py -m datagen.cli sample --seed 42 --out data/sample }
    "datagen-bulk"   { Need-Venv; & $Py -m datagen.cli bulk --count 300 --start-seed 1000 --out data/bench }
    "test"           { Need-Venv; & $Py -m pytest }
    "test-fast"      { Need-Venv; & $Py -m pytest -m "not slow" }
    "test-datagen"   { Need-Venv; & $Py -m pytest tests/datagen -v }
    "test-schemas"   { Need-Venv; & $Py -m pytest tests/schemas -v }
    "test-pipeline"  { Need-Venv; & $Py -m pytest tests/pipeline -v }
    "test-m1"        { Need-Venv; & $Py -m pytest tests/pipeline/test_m1_ingest.py -v }
    "test-m2"        { Need-Venv; & $Py -m pytest tests/pipeline/test_m2_segment.py -v }
    "test-m3"        { Need-Venv; & $Py -m pytest tests/pipeline/test_m3_extract.py tests/pipeline/test_m3_grounding.py -v }
    "test-m4"        { Need-Venv; & $Py -m pytest tests/pipeline/test_m4_audit.py tests/pipeline/test_m4_agents.py -v }
    "bench"          { Need-Venv; & $Py -m datagen.cli bulk --count 240 --start-seed 5000 --fault-rate 0.5 --balanced --gt-only --out bench/mediclaim-bench-v2 }
    "calibrate"      { Need-Venv; & $Py -m evals.cli --out data/bench_eval --calibrate 20 --alpha 0.1 }
    "eval-live"      {
        Need-Venv
        $env:LLM_LIVE = "1"
        & $Py -m evals.cli --out data/bench_eval --calibrate 20 --alpha 0.1 --readme README.md --results evals/RESULTS.md
    }
    "test-m5"        { Need-Venv; & $Py -m pytest tests/pipeline/test_m5_complete.py -v }
    "eval"           { Need-Venv; & $Py -m evals.cli --out data/bench_eval --readme README.md --results evals/RESULTS.md }
    "api"            { Need-Venv; & $Py -m uvicorn api.app:app --reload }
    "demo"           {
        Need-Venv
        docker compose up -d --build
        & $Py scripts/demo_seed.py
        Start-Process "http://localhost:5173"
    }
    "score-models"   { Need-Venv; & $Py scripts/testpack.py score }
    "record-testpack" { Need-Venv; & $Py scripts/testpack.py record }
    "testpack-check" { Need-Venv; & $Py scripts/testpack.py check }
    "ai-pack"        {
        Need-Venv
        $env:PYTHONUTF8 = "1"
        & $Py scripts/testpack.py score;  if ($LASTEXITCODE) { exit $LASTEXITCODE }
        & $Py scripts/testpack.py record; if ($LASTEXITCODE) { exit $LASTEXITCODE }
        & $Py scripts/testpack.py check
    }
    "lint"           { Need-Venv; & $Py -m ruff check . }
    "fmt"            { Need-Venv; & $Py -m ruff format . }
    default          { Write-Host "Unknown target '$Target'. Try ./run.ps1 help" -ForegroundColor Red; exit 1 }
}
