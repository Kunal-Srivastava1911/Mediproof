# MediProof task runner for Windows (mirrors the Makefile). Usage: ./run.ps1 <target>
param([Parameter(Position = 0)][string]$Target = "help")

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$env:PYTHONPATH = $Root

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
        "  lint / fmt      ruff check / format" | ForEach-Object { Write-Host $_ }
    }
    "venv"           { & (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe") -m venv (Join-Path $Root ".venv") }
    "install"        { Need-Venv; & $Py -m pip install -e $Root }
    "install-dev"    { Need-Venv; & $Py -m pip install -e "$Root[datagen,dev]"; & $Py -m playwright install chromium }
    "datagen-sample" { Need-Venv; & $Py -m datagen.cli sample --seed 42 --out data/sample }
    "datagen-bulk"   { Need-Venv; & $Py -m datagen.cli bulk --count 300 --start-seed 1000 --out data/bench }
    "test"           { Need-Venv; & $Py -m pytest }
    "test-datagen"   { Need-Venv; & $Py -m pytest tests/datagen -v }
    "test-schemas"   { Need-Venv; & $Py -m pytest tests/schemas -v }
    "lint"           { Need-Venv; & $Py -m ruff check . }
    "fmt"            { Need-Venv; & $Py -m ruff format . }
    default          { Write-Host "Unknown target '$Target'. Try ./run.ps1 help" -ForegroundColor Red; exit 1 }
}
