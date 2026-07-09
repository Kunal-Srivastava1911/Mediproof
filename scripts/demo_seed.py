"""Wait for the demo API to come up, then upload the seeded sample claim.

Called by `make demo` / `./run.ps1 demo` after `docker compose up`. The sample PDF is
rendered by datagen just before this runs (see the demo target).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

API = "http://localhost:8000"
UI = "http://localhost:5173"
PDF = Path("data/demo/claim.pdf")
CLAIM_ID = "DEMO-0001"


def _wait_for_api(timeout_s: int = 120) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if httpx.get(f"{API}/healthz", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    sys.exit(f"[demo] API did not become healthy at {API} within {timeout_s}s")


def main() -> None:
    if not PDF.exists():
        sys.exit(f"[demo] {PDF} not found — run the datagen step first")
    print(f"[demo] waiting for API at {API} ...")
    _wait_for_api()

    print(f"[demo] uploading {PDF} as {CLAIM_ID} ...")
    files = {"file": ("claim.pdf", PDF.read_bytes(), "application/pdf")}
    httpx.post(f"{API}/claims", params={"claim_id": CLAIM_ID}, files=files, timeout=120)

    graph = httpx.get(f"{API}/claims/{CLAIM_ID}", timeout=30).json()
    n = len(graph.get("findings", []))
    print(f"[demo] processed: status={graph.get('status')}, {n} review items")
    print(f"\n[demo] ✔ open the dashboard:  {UI}\n")


if __name__ == "__main__":
    main()
