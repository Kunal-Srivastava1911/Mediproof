import type { EvidenceCell, ExtractedField, FieldRow, Finding, TimelineEvent } from "./types";

// ------------------------------------------------------------------ review items

const SEVERITY_RANK: Record<string, number> = { critical: 0, warning: 1, info: 2 };

/** Shown items (what reviewers and patients see) and held-back agent items, worst first. */
export function splitFindings(findings: Finding[]): { shown: Finding[]; held: Finding[] } {
  const bySeverity = (a: Finding, b: Finding) =>
    (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3) || a.id.localeCompare(b.id);
  return {
    shown: findings.filter((f) => !f.held_back).sort(bySeverity),
    held: findings.filter((f) => f.held_back).sort(bySeverity),
  };
}

/** Who raised an item, for its badge. */
export function originLabel(f: Finding): string {
  if (f.origin === "reviewer") return "Promoted by reviewer";
  if (f.origin === "agent") return f.agent ?? "Agent";
  return "Rule";
}

/** Every evidence box of a finding: its own boxes plus each grounded quote's. */
export function findingEvidence(f: Finding) {
  const fromProof = f.proof.flatMap((q) => q.evidence);
  return fromProof.length ? fromProof : f.evidence;
}

export function docLabel(docType: string): string {
  return docType.replace(/_/g, " ");
}

// ------------------------------------------------------------------ timeline grid

const DAY = 24 * 60 * 60 * 1000;
const toDay = (iso: string) => Math.round(Date.parse(`${iso}T00:00:00Z`) / DAY);

export interface TimelineRow {
  document_id: string;
  doc_type: string;
  cells: Array<{ event: TimelineEvent; col: number; span: number }>;
}

/**
 * Lay events out on a day grid: one column per calendar day from the earliest to the latest
 * event (plus one day either side), one row per document. `col` is 0-based.
 */
export function timelineGrid(events: TimelineEvent[]): { days: string[]; rows: TimelineRow[] } {
  if (!events.length) return { days: [], rows: [] };
  const starts = events.map((e) => toDay(e.start));
  const ends = events.map((e) => toDay(e.end ?? e.start));
  const first = Math.min(...starts) - 1;
  const last = Math.max(...ends) + 1;
  const days: string[] = [];
  for (let d = first; d <= last; d++) days.push(new Date(d * DAY).toISOString().slice(0, 10));
  const rows: TimelineRow[] = [];
  for (const e of events) {
    let row = rows.find((r) => r.document_id === e.document_id);
    if (!row) {
      row = { document_id: e.document_id, doc_type: e.doc_type, cells: [] };
      rows.push(row);
    }
    const s = toDay(e.start) - first;
    const span = toDay(e.end ?? e.start) - toDay(e.start) + 1;
    row.cells.push({ event: e, col: s, span });
  }
  return { days, rows };
}

// ------------------------------------------------------------------ evidence map

/** Facts × documents matrix of the claim evidence graph. */
export function evidenceMatrix(cells: EvidenceCell[]) {
  const facts = [...new Set(cells.map((c) => c.fact))];
  const docs: Array<{ document_id: string; doc_type: string }> = [];
  for (const c of cells) {
    if (!docs.some((d) => d.document_id === c.document_id)) {
      docs.push({ document_id: c.document_id, doc_type: c.doc_type });
    }
  }
  const lookup = new Map(cells.map((c) => [`${c.fact}\u0000${c.document_id}`, c]));
  return {
    facts,
    docs,
    get: (fact: string, documentId: string) => lookup.get(`${fact}\u0000${documentId}`),
  };
}

// Confidence bands mirror schemas.common.band_for (green >= 0.8, amber 0.5–0.8, red < 0.5).
export type Band = "green" | "amber" | "red";

export function band(confidence: number): Band {
  if (confidence >= 0.8) return "green";
  if (confidence >= 0.5) return "amber";
  return "red";
}

export const BAND_STYLES: Record<Band, string> = {
  green: "border-l-band-green bg-green-50",
  amber: "border-l-band-amber bg-amber-50",
  red: "border-l-band-red bg-red-50",
};

export const BAND_CHIP: Record<Band, string> = {
  green: "bg-green-100 text-band-green",
  amber: "bg-amber-100 text-band-amber",
  red: "bg-red-100 text-band-red",
};

export const SEVERITY_CHIP: Record<string, string> = {
  info: "bg-slate-100 text-slate-600",
  warning: "bg-amber-100 text-band-amber",
  critical: "bg-red-100 text-band-red",
};

// Submitter-facing status. The pipeline's granular states are hidden from claimants: anything
// still in flight (received/processing/processed/needs_review/failed) collapses to "not reviewed".
export type SubmitterBucket = "not_reviewed" | "denied" | "approved";

export function submitterBucket(status: string): SubmitterBucket {
  if (status === "approved") return "approved";
  if (status === "denied") return "denied";
  return "not_reviewed";
}

export const BUCKET_LABEL: Record<SubmitterBucket, string> = {
  not_reviewed: "Not reviewed",
  denied: "Reviewed — denied",
  approved: "Reviewed — approved",
};

export const BUCKET_STYLES: Record<SubmitterBucket, string> = {
  not_reviewed: "bg-slate-100 text-slate-700 border-slate-300",
  denied: "bg-red-100 text-band-red border-red-300",
  approved: "bg-green-100 text-band-green border-green-300",
};

function isField(node: unknown): node is ExtractedField {
  return (
    typeof node === "object" &&
    node !== null &&
    "confidence" in node &&
    "evidence" in node &&
    "value" in node
  );
}

function prettify(path: string): string {
  return path
    .split(".")
    .map((p) => (/^\d+$/.test(p) ? `#${Number(p) + 1}` : p.replace(/_/g, " ")))
    .join(" · ");
}

// Walk an extracted document into a flat list of renderable field rows. Paths use the same
// dotted form the API's review endpoint expects (e.g. "patient.name", "line_items.0.amount").
export function flattenFields(extracted: Record<string, unknown> | null): FieldRow[] {
  const rows: FieldRow[] = [];
  const walk = (node: unknown, path: string) => {
    if (isField(node)) {
      rows.push({ path, label: prettify(path), field: node });
    } else if (Array.isArray(node)) {
      node.forEach((item, i) => walk(item, path ? `${path}.${i}` : `${i}`));
    } else if (typeof node === "object" && node !== null) {
      for (const [k, v] of Object.entries(node)) {
        if (k === "doc_type") continue;
        walk(v, path ? `${path}.${k}` : k);
      }
    }
  };
  walk(extracted, "");
  return rows;
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}
