import { describe, expect, it } from "vitest";
import { band, flattenFields, submitterBucket } from "./lib";

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
