import { describe, expect, it } from "vitest";
import {
  band,
  evidenceMatrix,
  findingEvidence,
  flattenFields,
  originLabel,
  splitFindings,
  submitterBucket,
  timelineGrid,
} from "./lib";
import type { Finding } from "./types";

const finding = (id: string, over: Partial<Finding> = {}): Finding => ({
  id,
  type: "date_inconsistent",
  severity: "warning",
  title: id,
  detail: "",
  evidence: [],
  document_ids: [],
  origin: "rule",
  proof: [],
  verified_by: [],
  held_back: false,
  patient_facing: true,
  trail: [],
  decision: "open",
  ...over,
});

describe("review items", () => {
  it("separates held-back agent items and sorts worst first", () => {
    const { shown, held } = splitFindings([
      finding("F-001", { severity: "info" }),
      finding("F-002", { severity: "critical" }),
      finding("F-003", { held_back: true, origin: "agent" }),
    ]);
    expect(shown.map((f) => f.id)).toEqual(["F-002", "F-001"]);
    expect(held.map((f) => f.id)).toEqual(["F-003"]);
  });

  it("labels origin and prefers grounded quote evidence", () => {
    const box = { page: 2, bbox: { x0: 0, y0: 0, x1: 1, y1: 1 } };
    const f = finding("F-004", {
      origin: "agent",
      agent: "Timeline agent",
      proof: [{ document_id: "D", quote: "q", grounded: true, evidence: [box] }],
    });
    expect(originLabel(f)).toBe("Timeline agent");
    expect(originLabel(finding("F-005"))).toBe("Rule");
    expect(findingEvidence(f)).toEqual([box]);
  });
});

describe("timelineGrid", () => {
  it("places spans and points on a day grid, one row per document", () => {
    const grid = timelineGrid([
      { document_id: "BILL", doc_type: "hospital_bill", label: "Stay", start: "2024-09-09",
        end: "2024-09-12", conflict: false, finding_ids: [] },
      { document_id: "CF", doc_type: "claim_form", label: "Admission", start: "2024-09-06",
        conflict: true, finding_ids: ["F-001"] },
    ]);
    expect(grid.days[0]).toBe("2024-09-05");          // one padding day before
    expect(grid.days[grid.days.length - 1]).toBe("2024-09-13");  // one after
    const bill = grid.rows.find((r) => r.document_id === "BILL")!;
    expect(bill.cells[0]).toMatchObject({ col: 4, span: 4 });
    expect(grid.rows.find((r) => r.document_id === "CF")!.cells[0].col).toBe(1);
  });
});

describe("evidenceMatrix", () => {
  it("indexes facts by document", () => {
    const m = evidenceMatrix([
      { fact: "Patient name", document_id: "A", doc_type: "hospital_bill", value: "X",
        status: "agrees", finding_ids: [] },
      { fact: "Patient name", document_id: "B", doc_type: "pharmacy_bill", value: "Y",
        status: "conflicts", finding_ids: ["F-1"] },
    ]);
    expect(m.facts).toEqual(["Patient name"]);
    expect(m.docs.map((d) => d.document_id)).toEqual(["A", "B"]);
    expect(m.get("Patient name", "B")?.status).toBe("conflicts");
    expect(m.get("Patient name", "Z")).toBeUndefined();
  });
});

describe("confidence bands", () => {
  it("maps scores to bands like schemas.common.band_for", () => {
    expect(band(0.95)).toBe("green");
    expect(band(0.8)).toBe("green");
    expect(band(0.6)).toBe("amber");
    expect(band(0.3)).toBe("red");
  });
});

describe("flattenFields", () => {
  const field = (value: unknown, confidence = 0.9) => ({
    value,
    confidence,
    source: "rule",
    evidence: [],
    flags: [],
  });

  it("walks nested sub-models and lists into dotted paths", () => {
    const extracted = {
      doc_type: "hospital_bill",
      hospital_name: field("Acme"),
      patient: { name: field("Jane"), age: field(40) },
      line_items: [{ amount: field(100) }, { amount: field(200) }],
    };
    const rows = flattenFields(extracted as never);
    const paths = rows.map((r) => r.path);
    expect(paths).toContain("hospital_name");
    expect(paths).toContain("patient.name");
    expect(paths).toContain("line_items.0.amount");
    expect(paths).toContain("line_items.1.amount");
    // doc_type is a discriminator, not a field
    expect(paths).not.toContain("doc_type");
  });

  it("returns [] for a null document", () => {
    expect(flattenFields(null)).toEqual([]);
  });
});

describe("submitterBucket", () => {
  it("collapses every in-flight pipeline state to not_reviewed", () => {
    expect(submitterBucket("received")).toBe("not_reviewed");
    expect(submitterBucket("processing")).toBe("not_reviewed");
    expect(submitterBucket("processed")).toBe("not_reviewed");
    expect(submitterBucket("needs_review")).toBe("not_reviewed");
    // failed is an in-flight state to the claimant, not a fourth bucket
    expect(submitterBucket("failed")).toBe("not_reviewed");
  });

  it("surfaces the two reviewed decisions", () => {
    expect(submitterBucket("approved")).toBe("approved");
    expect(submitterBucket("denied")).toBe("denied");
  });
});
