import type { ExtractedField, FieldRow } from "./types";

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
