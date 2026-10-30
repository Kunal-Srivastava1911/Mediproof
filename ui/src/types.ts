// Loose types mirroring schemas/ (the API returns the ClaimFile graph as JSON).

export interface BBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Evidence {
  page: number;
  bbox: BBox;
  ocr_confidence?: number | null;
}

export interface ExtractedField {
  value: unknown;
  confidence: number;
  source: string;
  evidence: Evidence[];
  flags: string[];
}

export interface DocumentRecord {
  document_id: string;
  doc_type: string;
  page_range: number[];
  classifier_confidence: number;
  extracted: Record<string, unknown> | null;
}

export interface ProofQuote {
  document_id: string;
  quote: string;
  grounded: boolean;
  evidence: Evidence[];
}

export type FindingDecision = "open" | "confirmed" | "dismissed";

export interface Finding {
  id: string;
  type: string;
  severity: "info" | "warning" | "critical";
  title: string;
  detail: string;
  evidence: Evidence[];
  document_ids: string[];
  rule_id?: string | null;
  origin: "rule" | "agent" | "reviewer";
  agent?: string | null;
  proof: ProofQuote[];
  verified_by: string[];
  verifier_score?: number | null;
  held_back: boolean;
  patient_facing: boolean;
  trail: string[];
  decision: FindingDecision;
  decision_reason?: string | null;
}

export interface TimelineEvent {
  document_id: string;
  doc_type: string;
  label: string;
  start: string; // ISO date
  end?: string | null;
  conflict: boolean;
  finding_ids: string[];
}

export interface EvidenceCell {
  fact: string;
  document_id: string;
  doc_type: string;
  value: string;
  status: "agrees" | "conflicts" | "missing";
  finding_ids: string[];
}

export interface AuditMeta {
  agents_run: string[];
  model?: string | null; // provider:model, or the Gemini race and who won it
  llm_calls: number;
  llm_cost_usd: number;
  verifier_threshold?: number | null;
  note?: string | null;
}

export interface Completeness {
  claim_type: string;
  required: string[];
  present: string[];
  missing: string[];
}

export interface ClaimFile {
  claim_id: string;
  status: string;
  pages: Array<{ page: number; readability: number; unreadable: boolean }>;
  documents: DocumentRecord[];
  findings: Finding[];
  completeness: Completeness | null;
  corrections: Array<Record<string, unknown>>;
  timeline: TimelineEvent[];
  evidence_map: EvidenceCell[];
  audit: AuditMeta | null;
}

export interface ChecklistSource {
  document_id: string;
  label: string;
  page: number | null;
  bbox: BBox | null;
  quote: string | null;
}

export interface ChecklistItem {
  id: string;
  severity: "info" | "warning" | "critical";
  severity_label: string;
  title: string;
  detail: string;
  action: string;
  sources: ChecklistSource[];
  verified_by: string[];
  origin: string;
}

export interface Checklist {
  claim_id: string;
  lang: "en" | "hi";
  status: string;
  ready: boolean;
  detail_translated?: boolean;
  audit_note?: string | null;
  items: ChecklistItem[];
}

export interface ChatAnswer {
  answer: string;
  sources: Array<{ document_id: string; quote: string }>;
  answered_by?: string; // model race winner, e.g. "gemini-3.8-flash, 4.1s"
}

export interface ClaimSummary {
  claim_id: string;
  status: string;
  claim_type: string;
  n_findings: number;
  n_documents: number;
}

// A flattened extracted field, ready to render as a row.
export interface FieldRow {
  path: string;
  label: string;
  field: ExtractedField;
}
