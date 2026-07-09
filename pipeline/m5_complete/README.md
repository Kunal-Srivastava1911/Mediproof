# M5 — Completeness Checker (W6)

**In:** the `ClaimFile` + its `claim_type`. **Out:** `CompletenessReport`
(`required` / `present` / `missing` doc types).

Map each claim type to its required-document checklist and emit the present/missing matrix.
Missing required documents surface as `FindingType.missing_document`.

**DoD:** present/missing matrix produced for the sample claim; a missing-doc fault is caught.
