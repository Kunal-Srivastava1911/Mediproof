"""HTML (Jinja) -> PDF rendering via headless Chromium (Playwright).

A rendered document is what the pipeline actually ingests. The renderer is deliberately
thin: pick a template by doc_type, fill it from a ground-truth model, print to A4 PDF.
"""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pypdf import PdfWriter

from schemas.common import DocType
from schemas.ground_truth import ClaimGroundTruth

_TEMPLATE_DIR = Path(__file__).parent / "templates"

# Only these doc types have templates today (plan W1). Others live in ground truth and get
# templates in W2; the renderer skips them cleanly rather than guessing a layout.
TEMPLATE_FOR: dict[DocType, str] = {
    DocType.hospital_bill: "hospital_bill.html",
    DocType.discharge_summary: "discharge_summary.html",
    DocType.pharmacy_bill: "pharmacy_bill.html",
}

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)
_CSS = (_TEMPLATE_DIR / "base.css").read_text(encoding="utf-8")


def _initials(org_name: str) -> str:
    words = [w for w in org_name.split() if w[:1].isalpha()]
    return ("".join(w[0] for w in words[:2]) or "M").upper()


def _org_name(doc) -> str:
    if hasattr(doc, "hospital"):
        return doc.hospital.name
    if hasattr(doc, "pharmacy_name"):
        return doc.pharmacy_name
    if hasattr(doc, "lab_name"):
        return doc.lab_name
    return "MediProof"


def render_html(doc) -> str:
    """Render one ground-truth document model to an HTML string."""
    template_name = TEMPLATE_FOR[doc.doc_type]
    template = _env.get_template(template_name)
    return template.render(
        doc=doc, css=_CSS, theme=doc.template_id, initials=_initials(_org_name(doc))
    )


class PdfRenderer:
    """Holds one Chromium instance so a whole claim renders on a single browser launch."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None

    def __enter__(self) -> PdfRenderer:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        return self

    def __exit__(self, *exc) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def html_to_pdf(self, html: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        page = self._browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(path=str(out_path), format="A4", print_background=True)
        page.close()
        return out_path

    def render_document(self, doc, out_path: Path) -> Path:
        return self.html_to_pdf(render_html(doc), out_path)


def render_claim(claim: ClaimGroundTruth, out_dir: Path) -> dict:
    """Render every templated document in a claim, write per-doc PDFs, a merged claim.pdf,
    and ground_truth.json. Returns a manifest of what was produced.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = out_dir / "docs"
    rendered: list[dict] = []

    with PdfRenderer() as renderer:
        for doc in claim.documents:
            if doc.doc_type not in TEMPLATE_FOR:
                continue
            pdf_path = docs_dir / f"{doc.document_id}.pdf"
            renderer.render_document(doc, pdf_path)
            rendered.append({
                "document_id": doc.document_id,
                "doc_type": doc.doc_type.value,
                "template_id": doc.template_id,
                "pdf": str(pdf_path.relative_to(out_dir)),
            })

    merged_path = out_dir / "claim.pdf"
    writer = PdfWriter()
    for r in rendered:
        writer.append(str(out_dir / r["pdf"]))
    with open(merged_path, "wb") as fh:
        writer.write(fh)

    gt_path = out_dir / "ground_truth.json"
    gt_path.write_text(claim.model_dump_json(indent=2), encoding="utf-8")

    manifest = {
        "claim_id": claim.claim_id,
        "seed": claim.seed,
        "merged_pdf": "claim.pdf",
        "ground_truth": "ground_truth.json",
        "documents": rendered,
        "doc_types_rendered": sorted({r["doc_type"] for r in rendered}),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
