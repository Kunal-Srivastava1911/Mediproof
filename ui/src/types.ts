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

export interface Finding {
  id: string;
  type: string;
  severity: "info" | "warning" | "critical";
  title: string;
  detail: string;
  evidence: Evidence[];
  document_ids: string[];
  rule_id?: string | null;
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
