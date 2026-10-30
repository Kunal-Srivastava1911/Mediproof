"""Patient-facing views of a processed claim: the fix-it checklist and claim chat.

The checklist shows only what a patient should act on: verified items (never held back),
patient-facing (no payability notes), not dismissed by a reviewer. Titles and actions are
fixed, reviewed templates per finding type in English and Hindi; the item's detail is the
finding's own text, translated by Claude when Hindi is asked for (record/replay — offline,
the English detail is shown and marked untranslated).

Claim chat answers only from the file: Claude must cite verbatim quotes, every quote is
checked against the documents' text, and uncited or unverifiable answers are not shown.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from pipeline.m3_extract.llm_client import LLMClient, quotes_found
from schemas.claim import ClaimFile
from schemas.findings import FindingDecision, FindingType

LANGS = ("en", "hi")

SEVERITY_LABEL = {
    "en": {"critical": "Important", "warning": "Worth checking", "info": "For your information"},
    "hi": {"critical": "ज़रूरी", "warning": "जाँच लें", "info": "जानकारी के लिए"},
}

DOC_LABEL = {
    "en": {"claim_form": "Claim form", "hospital_bill": "Hospital bill",
           "discharge_summary": "Discharge summary", "pharmacy_bill": "Pharmacy bill",
           "lab_report": "Lab / radiology report", "prescription": "Prescription",
           "other": "Document", "page": "page"},
    "hi": {"claim_form": "क्लेम फॉर्म", "hospital_bill": "अस्पताल का बिल",
           "discharge_summary": "डिस्चार्ज समरी", "pharmacy_bill": "फ़ार्मेसी बिल",
           "lab_report": "लैब / रेडियोलॉजी रिपोर्ट", "prescription": "पर्चा",
           "other": "दस्तावेज़", "page": "पेज"},
}

# (title, action) per finding type, per language.
_BILL = ("The hospital bill doesn't add up", "Ask the billing desk for a corrected final bill.",
         "अस्पताल का बिल जोड़ में मेल नहीं खाता", "बिलिंग डेस्क से सही अंतिम बिल माँगें।")
_MED = ("A medicine on a bill doesn't match your prescription or diagnosis",
        "Ask the hospital or pharmacy to check this medicine line.",
        "बिल की एक दवा आपके पर्चे या निदान से मेल नहीं खाती",
        "अस्पताल या फ़ार्मेसी से इस दवा की जाँच करवाएँ।")
_MISSING = ("A report is missing from your file",
            "Ask the hospital for the missing report and upload it.",
            "आपकी फ़ाइल में एक रिपोर्ट नहीं है", "अस्पताल से वह रिपोर्ट लेकर अपलोड करें।")
_TEMPLATES: dict[FindingType, tuple[str, str, str, str]] = {
    FindingType.date_inconsistent: (
        "Dates don't match across your documents",
        "Get the document with the wrong date corrected (or correct your claim form) "
        "before you file.",
        "आपके दस्तावेज़ों में तारीखें मेल नहीं खातीं",
        "फ़ाइल करने से पहले गलत तारीख वाला दस्तावेज़ ठीक करवाएँ (या अपना क्लेम फॉर्म ठीक करें)।"),
    FindingType.temporal_inconsistency: (
        "A bill is dated outside your hospital stay",
        "Check that this bill belongs to this stay, and keep the related prescription with it.",
        "एक बिल आपकी भर्ती की अवधि से बाहर की तारीख का है",
        "जाँच लें कि यह बिल इसी भर्ती से जुड़ा है, और उससे जुड़ा पर्चा साथ रखें।"),
    FindingType.unsupported_by_documentation: (
        "A billed charge doesn't match your medical record",
        "Ask the hospital billing desk to confirm this charge.",
        "बिल का एक शुल्क आपके मेडिकल रिकॉर्ड से मेल नहीं खाता",
        "अस्पताल के बिलिंग डेस्क से इस शुल्क की पुष्टि करवाएँ।"),
    FindingType.missing_report: _MISSING,
    FindingType.missing_lab_report: _MISSING,
    FindingType.name_inconsistent: (
        "Your name is written differently on one document",
        "Ask for a corrected copy with your name spelled as on your ID.",
        "एक दस्तावेज़ पर आपका नाम अलग तरह से लिखा है",
        "अपने पहचान पत्र जैसी स्पेलिंग वाली सही कॉपी माँगें।"),
    FindingType.age_gender_inconsistent: (
        "Your age or sex differs on one document", "Ask for a corrected copy.",
        "एक दस्तावेज़ पर आपकी उम्र या लिंग अलग लिखा है", "सही कॉपी माँगें।"),
    FindingType.bill_arithmetic_mismatch: _BILL,
    FindingType.inflated_line_item: _BILL,
    FindingType.duplicate_line_item: _BILL,
    FindingType.unmatched_medication: _MED,
    FindingType.prescription_pharmacy_mismatch: _MED,
    FindingType.drug_diagnosis_implausible: _MED,
    FindingType.missing_document: (
        "A required document is missing", "Add the missing document to your file.",
        "एक ज़रूरी दस्तावेज़ नहीं है", "वह दस्तावेज़ अपनी फ़ाइल में जोड़ें।"),
}
_DEFAULT = ("Two documents disagree", "Ask the hospital to confirm which one is correct.",
            "दो दस्तावेज़ आपस में मेल नहीं खाते", "अस्पताल से पूछें कि कौन सा सही है।")

TRANSLATE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["translations"],
    "properties": {"translations": {"type": "array", "items": {"type": "string"}}},
}
TRANSLATE_SYSTEM = (
    "Translate each English sentence into simple, polite Hindi (Devanagari) for a patient. "
    "Keep names, numbers, dates, document titles and quoted text exactly as written. Return "
    "the translations in the same order, one per input sentence.")


def patient_items(claim: ClaimFile):
    return [f for f in claim.findings
            if not f.held_back and f.patient_facing and f.decision != FindingDecision.dismissed]


def _sources(claim: ClaimFile, finding, lang: str) -> list[dict]:
    labels = DOC_LABEL[lang]
    docs = {d.document_id: d for d in claim.documents}
    out = []
    if finding.proof:
        for q in finding.proof:
            doc = docs.get(q.document_id)
            ev = q.evidence[0] if q.evidence else None
            out.append({"document_id": q.document_id,
                        "label": labels.get(doc.doc_type.value if doc else "other"),
                        "page": ev.page if ev else (doc.page_range[0] if doc else None),
                        "bbox": ev.bbox.model_dump() if ev else None, "quote": q.quote})
    else:
        for doc_id, ev in zip(finding.document_ids, finding.evidence, strict=False):
            doc = docs.get(doc_id)
            out.append({"document_id": doc_id,
                        "label": labels.get(doc.doc_type.value if doc else "other"),
                        "page": ev.page, "bbox": ev.bbox.model_dump(), "quote": None})
    return out


def _translation_ok(reply: dict, details: list[str]) -> bool:
    """Race check for the Hindi checklist: one translation per detail, and every number in
    a detail (amounts, dates, counts) survives unchanged in its translation."""
    out = reply.get("translations", [])
    if len(out) != len(details):
        return False
    return all(set(re.findall(r"\d[\d,.]*\d|\d", d)) <= set(re.findall(r"\d[\d,.]*\d|\d", t))
               for d, t in zip(details, out, strict=True))


def checklist(claim: ClaimFile, lang: str = "en", client: LLMClient | None = None) -> dict:
    lang = lang if lang in LANGS else "en"
    items = patient_items(claim)
    details = [f.detail for f in items]
    translated = lang == "en"
    if lang == "hi" and details:
        try:
            reply = (client or LLMClient()).complete_json(
                TRANSLATE_SYSTEM, "\n".join(f"{i + 1}. {d}" for i, d in enumerate(details)),
                TRANSLATE_SCHEMA, accept=lambda r: _translation_ok(r, details))
            if len(reply.get("translations", [])) == len(details):
                details, translated = reply["translations"], True
        except Exception:  # noqa: BLE001 - offline / no fixture: keep the English detail
            pass
    out = []
    for f, detail in zip(items, details, strict=True):
        t = _TEMPLATES.get(f.type, _DEFAULT)
        title, action = (t[0], t[1]) if lang == "en" else (t[2], t[3])
        out.append({
            "id": f.id, "severity": f.severity.value,
            "severity_label": SEVERITY_LABEL[lang][f.severity.value],
            "title": title, "detail": detail, "action": action,
            "sources": _sources(claim, f, lang),
            "verified_by": f.verified_by, "origin": f.origin.value,
        })
    return {"claim_id": claim.claim_id, "lang": lang, "detail_translated": translated,
            "items": out}


# ------------------------------------------------------------------------- claim chat

ASK_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["answer", "sources"],
    "properties": {
        "answer": {"type": "string"},
        "sources": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["document_id", "quote"],
            "properties": {"document_id": {"type": "string"}, "quote": {"type": "string"}},
        }},
    },
}
ASK_SYSTEM = """\
You answer a patient's questions about their own health-insurance claim file, using only
the documents provided. Cite every fact with a verbatim quote (at most 25 words) and the id
of the document it comes from. If the documents don't contain the answer, say so plainly.
Never give medical advice and never predict whether the insurer will pay: say that
MediProof only checks that the documents are complete and consistent, and the insurer
decides on payment. Answer in the language of the question, briefly."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def ask(question: str, dossier: str, doc_texts: dict[str, str], client: LLMClient) -> dict:
    """Answer from the file. Quotes that can't be found in their document are dropped; an
    answer with facts but no verifiable source is replaced by a refusal to guess."""
    reply = client.complete_json(ASK_SYSTEM, [
        {"type": "text", "text": dossier, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"Question: {question.strip()}"},
    ], ASK_SCHEMA, accept=lambda r: quotes_found(r, "\n".join(doc_texts.values())))
    sources = []
    for s in reply.get("sources", []):
        text = doc_texts.get(str(s.get("document_id")), "")
        if s.get("quote") and fuzz.partial_ratio(_norm(s["quote"]), _norm(text)) >= 90:
            sources.append({"document_id": s["document_id"], "quote": s["quote"]})
    answer = str(reply.get("answer", "")).strip()
    if reply.get("sources") and not sources:
        answer = ("I couldn't find support for an answer in your documents, so I won't guess. "
                  "Please ask the hospital directly.")
    out = {"answer": answer, "sources": sources}
    last = getattr(client, "last_answer", None)
    if getattr(client, "racing", False) and callable(last) and last():
        out["answered_by"] = last()
    return out
