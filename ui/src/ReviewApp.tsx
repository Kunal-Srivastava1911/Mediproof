import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import {
  BAND_CHIP,
  BAND_STYLES,
  SEVERITY_CHIP,
  band,
  displayValue,
  docLabel,
  evidenceMatrix,
  findingEvidence,
  flattenFields,
  originLabel,
  splitFindings,
  timelineGrid,
} from "./lib";
import type {
  AuditMeta,
  ClaimFile,
  ClaimSummary,
  DocumentRecord,
  Evidence,
  EvidenceCell,
  FieldRow,
  Finding,
  FindingDecision,
  TimelineEvent,
} from "./types";

type View = "document" | "timeline" | "map";
interface Highlight {
  page: number;
  boxes: Evidence[];
}

const DISMISS_REASONS = [
  "The documents are actually consistent",
  "Not relevant to this claim",
  "Duplicate of another item",
];

export default function ReviewApp() {
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [claimId, setClaimId] = useState<string>("");
  const [claim, setClaim] = useState<ClaimFile | null>(null);
  const [docIdx, setDocIdx] = useState(0);
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  const [view, setView] = useState<View>("document");
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    api.listClaims().then((c) => {
      setClaims(c);
      if (c.length && !claimId) setClaimId(c[0].claim_id);
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!claimId) return;
    setHighlight(null);
    setDocIdx(0);
    setSelected(null);
    setView("document");
    api.getClaim(claimId).then(setClaim).catch((e) => setError(String(e)));
  }, [claimId]);

  const doc = claim?.documents[docIdx];
  const shownPage = highlight?.page ?? doc?.page_range[0] ?? 0;
  const fields = useMemo(() => flattenFields(doc?.extracted ?? null), [doc]);
  const finding = claim?.findings.find((f) => f.id === selected) ?? null;

  function locate(boxes: Evidence[]) {
    if (!claim || !boxes.length) return;
    const page = boxes[0].page;
    const idx = claim.documents.findIndex((d) => d.page_range.includes(page));
    if (idx >= 0) setDocIdx(idx);
    setHighlight({ page, boxes: boxes.filter((b) => b.page === page) });
    setView("document");
  }

  function openFinding(f: Finding) {
    setSelected(f.id);
    locate(findingEvidence(f));
  }

  function openFindingById(id: string) {
    const f = claim?.findings.find((x) => x.id === id);
    if (f) openFinding(f);
  }

  async function saveCorrection(row: FieldRow, newValue: string) {
    if (!claim || !doc) return;
    const updated = await api.review(claim.claim_id, {
      document_id: doc.document_id,
      field_path: row.path,
      new_value: newValue,
      reviewer: "reviewer",
    });
    setClaim(updated);
  }

  async function decide(kind: "approve" | "deny") {
    if (!claim) return;
    try {
      const updated = kind === "approve"
        ? await api.approve(claim.claim_id)
        : await api.deny(claim.claim_id);
      setClaim(updated);
    } catch (e) {
      setError(String(e));
    }
  }

  async function decideFinding(f: Finding, decision: FindingDecision, reason?: string,
                               promote = false) {
    if (!claim) return;
    try {
      setClaim(await api.decide(claim.claim_id, f.id, {
        decision, reason, promote, reviewer: "reviewer",
      }));
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Header claim={claim} />
      {error && <div className="bg-red-100 text-band-red px-6 py-2 text-sm">{error} — is the API running on :8000?</div>}
      {claim && <AuditBanner audit={claim.audit} />}

      <div className="flex-1 grid grid-cols-12 gap-4 p-4 max-w-[1500px] w-full mx-auto">
        <Sidebar
          claims={claims}
          claimId={claimId}
          onPick={setClaimId}
          claim={claim}
          docIdx={docIdx}
          selected={selected}
          onDoc={(i) => { setDocIdx(i); setHighlight(null); setView("document"); }}
          onFinding={openFinding}
          onApprove={() => decide("approve")}
          onDeny={() => decide("deny")}
        />

        <main className="col-span-5 bg-white rounded-lg shadow-sm p-3 min-w-0">
          <div className="flex gap-1 mb-3" role="group" aria-label="Claim views">
            {(["document", "timeline", "map"] as View[]).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                aria-pressed={view === v}
                className={`text-sm px-3 py-1.5 rounded border ${
                  view === v ? "bg-slate-800 text-white border-slate-800" : "border-slate-300 hover:bg-slate-50"
                }`}
              >
                {v === "document" ? "Document" : v === "timeline" ? "Timeline" : "Evidence map"}
              </button>
            ))}
          </div>
          {!claim || !doc ? (
            <Empty />
          ) : view === "document" ? (
            <PageViewer
              src={api.pageImage(claim.claim_id, shownPage)}
              boxes={highlight && highlight.page === shownPage ? highlight.boxes : []}
              caption={`${docLabel(doc.doc_type)} · page ${shownPage + 1}`}
            />
          ) : view === "timeline" ? (
            <TimelineView events={claim.timeline ?? []} documents={claim.documents}
                          onFinding={openFindingById} />
          ) : (
            <EvidenceMapView cells={claim.evidence_map ?? []} onFinding={openFindingById} />
          )}
        </main>

        <section className="col-span-4 bg-white rounded-lg shadow-sm p-3 overflow-auto max-h-[calc(100vh-9rem)]">
          {finding && claim ? (
            <FindingPanel
              finding={finding}
              documents={claim.documents}
              threshold={claim.audit?.verifier_threshold ?? null}
              onLocate={locate}
              onDecide={(d, reason, promote) => decideFinding(finding, d, reason, promote)}
              onClose={() => setSelected(null)}
            />
          ) : (
            <>
              <h2 className="font-semibold text-slate-700 mb-2">
                Extracted fields{" "}
                <span className="text-xs font-normal text-slate-500">
                  (click a row to locate it · pencil to correct)
                </span>
              </h2>
              <div className="space-y-1">
                {fields.map((row) => (
                  <FieldRowView
                    key={row.path}
                    row={row}
                    onLocate={() => locate(row.field.evidence)}
                    onSave={(v) => saveCorrection(row, v)}
                    selected={highlight != null && row.field.evidence[0] === highlight.boxes[0]}
                  />
                ))}
                {!fields.length && <p className="text-sm text-slate-500">No extracted fields.</p>}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function Header({ claim }: { claim: ClaimFile | null }) {
  return (
    <header className="bg-slate-900 text-white px-6 py-3">
      <div className="max-w-[1500px] mx-auto flex items-center justify-between">
        <div>
          <span className="font-bold text-lg">MediProof</span>
          <span className="ml-3 text-slate-300 text-sm">claim-readiness review</span>
          <a href="/" className="ml-4 text-slate-300 hover:text-white text-xs">← Submitter site</a>
        </div>
        <div className="flex items-center gap-3">
          {claim && <StatusPill status={claim.status} />}
          <span className="text-[11px] text-slate-300 max-w-sm text-right">
            Documentation QA — not a clinical or payment decision. Findings are review items.
          </span>
        </div>
      </div>
    </header>
  );
}

function AuditBanner({ audit }: { audit: AuditMeta | null }) {
  if (!audit) return null;
  if (!audit.agents_run.length) {
    return (
      <div className="bg-amber-50 border-b border-amber-200 text-amber-900 px-6 py-2 text-sm">
        {audit.note ?? "Agent auditor did not run."} Rule checks ran as usual.
      </div>
    );
  }
  return (
    <div className="bg-slate-100 border-b border-slate-200 text-slate-700 px-6 py-2 text-sm">
      Agent auditor: {audit.agents_run.length} specialist agents + skeptic · {audit.llm_calls} AI
      calls{audit.model && <> · {audit.model}</>} · ${audit.llm_cost_usd.toFixed(3)} live spend
      {audit.verifier_threshold != null && <> · verifier threshold {audit.verifier_threshold.toFixed(2)}</>}
      {audit.note && <span className="ml-2 text-amber-800">{audit.note}</span>}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const cls = status === "approved" ? "bg-green-400 text-green-950"
    : status === "denied" ? "bg-red-400 text-red-950"
    : status === "needs_review" ? "bg-amber-400 text-amber-950"
    : status === "processed" ? "bg-green-400 text-green-950"
    : "bg-slate-500 text-white";
  return <span className={`text-xs font-semibold px-2 py-1 rounded ${cls}`}>{status.replace(/_/g, " ")}</span>;
}

function Sidebar(props: {
  claims: ClaimSummary[];
  claimId: string;
  onPick: (id: string) => void;
  claim: ClaimFile | null;
  docIdx: number;
  selected: string | null;
  onDoc: (i: number) => void;
  onFinding: (f: Finding) => void;
  onApprove: () => void;
  onDeny: () => void;
}) {
  const { claims, claimId, onPick, claim, docIdx, selected, onDoc, onFinding, onApprove, onDeny } = props;
  const decided = claim?.status === "approved" || claim?.status === "denied";
  const { shown, held } = splitFindings(claim?.findings ?? []);
  return (
    <aside className="col-span-3 space-y-4">
      <div className="bg-white rounded-lg shadow-sm p-3">
        <label htmlFor="claim-pick" className="text-xs font-semibold text-slate-500">Claim</label>
        <select
          id="claim-pick"
          className="w-full mt-1 border rounded px-2 py-1 text-sm"
          value={claimId}
          onChange={(e) => onPick(e.target.value)}
        >
          {claims.map((c) => (
            <option key={c.claim_id} value={c.claim_id}>
              {c.claim_id} ({c.n_findings} findings)
            </option>
          ))}
        </select>
        {claim && (
          decided ? (
            <div className={`mt-2 text-sm font-semibold ${claim.status === "approved" ? "text-band-green" : "text-band-red"}`}>
              {claim.status === "approved" ? "✓ Approved for filing" : "✗ Denied"}
            </div>
          ) : (
            <div className="mt-2 grid grid-cols-2 gap-2">
              <button onClick={onApprove} className="bg-green-700 hover:bg-green-800 text-white text-sm font-semibold rounded py-1.5">
                Approve
              </button>
              <button onClick={onDeny} className="bg-red-700 hover:bg-red-800 text-white text-sm font-semibold rounded py-1.5">
                Deny
              </button>
            </div>
          )
        )}
      </div>

      {claim && (
        <div className="bg-white rounded-lg shadow-sm p-3">
          <h3 className="text-xs font-semibold text-slate-500 mb-2">Documents</h3>
          <div className="space-y-1">
            {claim.documents.map((d, i) => (
              <button
                key={d.document_id}
                onClick={() => onDoc(i)}
                className={`block w-full text-left text-sm px-2 py-1 rounded ${
                  i === docIdx ? "bg-slate-800 text-white" : "hover:bg-slate-100"
                }`}
              >
                {docLabel(d.doc_type)}
              </button>
            ))}
          </div>
        </div>
      )}

      {claim?.completeness && (
        <div className="bg-white rounded-lg shadow-sm p-3">
          <h3 className="text-xs font-semibold text-slate-500 mb-2">Completeness</h3>
          {claim.completeness.missing.length === 0 ? (
            <p className="text-sm text-band-green">All required documents present.</p>
          ) : (
            <p className="text-sm text-band-red">
              Missing: {claim.completeness.missing.join(", ").replace(/_/g, " ")}
            </p>
          )}
        </div>
      )}

      {claim && (
        <div className="bg-white rounded-lg shadow-sm p-3">
          <h3 className="text-xs font-semibold text-slate-500 mb-2">Review items ({shown.length})</h3>
          <div className="space-y-2">
            {shown.map((f) => (
              <FindingCard key={f.id} f={f} selected={f.id === selected} onClick={() => onFinding(f)} />
            ))}
            {!shown.length && <p className="text-sm text-slate-500">No review items.</p>}
          </div>
          {held.length > 0 && (
            <div className="mt-3 border border-dashed border-slate-400 rounded p-2 bg-slate-50">
              <h4 className="text-xs font-semibold text-slate-600">Held back by verification ({held.length})</h4>
              <p className="text-[11px] text-slate-600 mb-2">
                Proposed by an agent but scored below the threshold — never shown to the patient.
              </p>
              <div className="space-y-2">
                {held.map((f) => (
                  <FindingCard key={f.id} f={f} selected={f.id === selected} onClick={() => onFinding(f)} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

function FindingCard({ f, selected, onClick }: { f: Finding; selected: boolean; onClick: () => void }) {
  const dismissed = f.decision === "dismissed";
  return (
    <button
      onClick={onClick}
      aria-pressed={selected}
      className={`block w-full text-left border rounded p-2 hover:bg-slate-50 ${selected ? "ring-2 ring-slate-500" : ""}`}
    >
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${SEVERITY_CHIP[f.severity]}`}>{f.severity}</span>
        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 text-slate-700">{originLabel(f)}</span>
        {f.decision !== "open" && (
          <span className="text-[10px] font-semibold text-slate-600">{f.decision}</span>
        )}
      </div>
      <div className={`text-sm font-medium mt-1 ${dismissed ? "line-through text-slate-500" : ""}`}>{f.title}</div>
      <p className="text-xs text-slate-600 mt-1 line-clamp-2">{f.detail}</p>
    </button>
  );
}

function FindingPanel(props: {
  finding: Finding;
  documents: DocumentRecord[];
  threshold: number | null;
  onLocate: (boxes: Evidence[]) => void;
  onDecide: (d: FindingDecision, reason?: string, promote?: boolean) => void;
  onClose: () => void;
}) {
  const { finding: f, documents, threshold, onLocate, onDecide, onClose } = props;
  const [dismissing, setDismissing] = useState(false);
  const docType = (id: string) => documents.find((d) => d.document_id === id)?.doc_type ?? "document";
  const visibility = f.held_back
    ? "Held back: reviewers only, never shown to the patient."
    : !f.patient_facing ? "Reviewer only: not shown to the patient."
    : f.decision === "dismissed" ? "Dismissed: removed from the patient's checklist."
    : "Shown to the patient in their checklist.";

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${SEVERITY_CHIP[f.severity]}`}>{f.severity}</span>
            <span className="text-xs text-slate-500 font-mono">{f.id}</span>
          </div>
          <h2 className="font-semibold text-slate-800 mt-1">{f.title}</h2>
        </div>
        <button onClick={onClose} className="text-xs text-slate-600 hover:text-slate-900 underline shrink-0">
          Back to fields
        </button>
      </div>

      <div className="flex flex-wrap gap-1.5 text-[11px]">
        <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 font-semibold">{originLabel(f)}</span>
        {f.verified_by.map((v) => (
          <span key={v} className="px-1.5 py-0.5 rounded bg-green-50 text-band-green font-semibold">✓ {v}</span>
        ))}
        {f.verifier_score != null && (
          <span className="px-1.5 py-0.5 text-slate-600">
            verifier {f.verifier_score.toFixed(2)}{threshold != null && ` · threshold ${threshold.toFixed(2)}`}
          </span>
        )}
      </div>

      <p className="text-sm text-slate-700">{f.detail}</p>
      <p className="text-xs font-semibold text-slate-600">{visibility}</p>

      <div className="space-y-2">
        {f.proof.length > 0 ? f.proof.map((q, i) => (
          <button
            key={i}
            onClick={() => onLocate(q.evidence)}
            disabled={!q.evidence.length}
            className="block w-full text-left border rounded p-2 hover:bg-slate-50 disabled:cursor-default"
          >
            <div className="text-[11px] text-slate-500 capitalize">
              {docLabel(docType(q.document_id))}
              {q.evidence[0] && ` · page ${q.evidence[0].page + 1}`}
              <span className={`ml-2 normal-case font-semibold ${q.grounded ? "text-band-green" : "text-band-red"}`}>
                {q.grounded ? "found on the page" : "not found in the document"}
              </span>
            </div>
            <div className="text-sm font-serif text-slate-800 mt-0.5">“{q.quote}”</div>
          </button>
        )) : f.evidence.map((ev, i) => (
          <button key={i} onClick={() => onLocate([ev])} className="block w-full text-left border rounded p-2 hover:bg-slate-50 text-sm">
            Evidence {i + 1} · page {ev.page + 1}
          </button>
        ))}
      </div>

      {f.trail.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer font-semibold text-slate-700">How was this found?</summary>
          <ol className="list-decimal pl-5 mt-2 space-y-1 text-slate-700 text-xs">
            {f.trail.map((t, i) => <li key={i}>{t}</li>)}
          </ol>
        </details>
      )}

      <div className="border-t pt-3 space-y-2">
        {f.held_back && (
          <button onClick={() => onDecide("confirmed", "promoted by reviewer", true)}
                  className="bg-slate-800 text-white text-sm font-semibold rounded px-3 py-1.5">
            Promote to review item
          </button>
        )}
        {!f.held_back && f.decision === "open" && !dismissing && (
          <div className="flex gap-2">
            <button onClick={() => onDecide("confirmed")} className="bg-slate-800 text-white text-sm font-semibold rounded px-3 py-1.5">
              Confirm
            </button>
            <button onClick={() => setDismissing(true)} className="border border-slate-300 text-sm font-semibold rounded px-3 py-1.5">
              Dismiss
            </button>
          </div>
        )}
        {dismissing && (
          <div className="space-y-1">
            <p className="text-xs font-semibold text-slate-700">Why dismiss it?</p>
            {DISMISS_REASONS.map((r) => (
              <button key={r} onClick={() => { onDecide("dismissed", r); setDismissing(false); }}
                      className="block w-full text-left border rounded px-2 py-1 text-sm hover:bg-slate-50">
                {r}
              </button>
            ))}
            <button onClick={() => setDismissing(false)} className="text-xs underline text-slate-600">Cancel</button>
          </div>
        )}
        {f.decision !== "open" && (
          <div className="text-sm text-slate-700">
            {f.decision === "confirmed" ? "Confirmed" : `Dismissed: ${f.decision_reason ?? ""}`}
            <button onClick={() => onDecide("open")} className="ml-2 text-xs underline text-slate-600">Undo</button>
          </div>
        )}
        <p className="text-[11px] text-slate-500">Every decision is saved as training data for the verifier.</p>
      </div>
    </div>
  );
}

function PageViewer({ src, boxes, caption }: { src: string; boxes: Evidence[]; caption: string }) {
  return (
    <div>
      <div className="text-xs text-slate-500 mb-2 capitalize">{caption}</div>
      <div className="relative inline-block w-full">
        <img src={src} alt={caption} className="w-full rounded border" />
        {boxes.map((ev, i) => (
          <div
            key={i}
            className="absolute border-2 border-band-red bg-red-500/20 rounded-sm transition-all"
            style={{
              left: `${ev.bbox.x0 * 100}%`,
              top: `${ev.bbox.y0 * 100}%`,
              width: `${(ev.bbox.x1 - ev.bbox.x0) * 100}%`,
              height: `${(ev.bbox.y1 - ev.bbox.y0) * 100}%`,
            }}
          />
        ))}
      </div>
    </div>
  );
}

function TimelineView({ events, documents, onFinding }: {
  events: TimelineEvent[];
  documents: DocumentRecord[];
  onFinding: (id: string) => void;
}) {
  const { days, rows } = timelineGrid(events);
  if (!days.length) return <p className="text-sm text-slate-500">No dated events.</p>;
  const label = (id: string) => docLabel(documents.find((d) => d.document_id === id)?.doc_type ?? "document");
  const cols = `150px repeat(${days.length}, minmax(34px, 1fr))`;
  return (
    <div>
      <p className="text-xs text-slate-600 mb-2">
        Every dated event from every document on one calendar. Orange cells belong to a review item —
        click one to open it.
      </p>
      <div className="overflow-x-auto">
        <div className="grid gap-1 text-[11px]" style={{ gridTemplateColumns: cols, minWidth: 150 + days.length * 34 }}>
          <div className="font-semibold text-slate-500">{days[0].slice(0, 7)}</div>
          {days.map((d) => <div key={d} className="text-center text-slate-500">{d.slice(8)}</div>)}
          {rows.map((r, ri) => (
            <TimelineRowView key={r.document_id} rowIndex={ri + 2} label={label(r.document_id)}
                             row={r} onFinding={onFinding} />
          ))}
        </div>
      </div>
    </div>
  );
}

function TimelineRowView({ rowIndex, label, row, onFinding }: {
  rowIndex: number;
  label: string;
  row: ReturnType<typeof timelineGrid>["rows"][number];
  onFinding: (id: string) => void;
}) {
  return (
    <>
      <div className="capitalize text-slate-700 font-medium self-center" style={{ gridRow: rowIndex, gridColumn: 1 }}>
        {label}
      </div>
      {row.cells.map(({ event, col, span }, i) => {
        const cls = event.conflict
          ? "bg-orange-100 border-2 border-orange-700 text-orange-950 font-semibold"
          : event.end ? "bg-sky-100 border border-sky-300 text-sky-950" : "bg-white border border-slate-300";
        const style = { gridRow: rowIndex, gridColumn: `${col + 2} / span ${span}` };
        return event.conflict && event.finding_ids[0] ? (
          <button key={i} style={style} onClick={() => onFinding(event.finding_ids[0])}
                  className={`rounded px-1 py-1 text-left leading-tight ${cls}`}>
            {event.label}
          </button>
        ) : (
          <div key={i} style={style} className={`rounded px-1 py-1 leading-tight ${cls}`}>{event.label}</div>
        );
      })}
    </>
  );
}

function EvidenceMapView({ cells, onFinding }: { cells: EvidenceCell[]; onFinding: (id: string) => void }) {
  const m = evidenceMatrix(cells);
  if (!m.facts.length) return <p className="text-sm text-slate-500">No shared facts extracted.</p>;
  return (
    <div>
      <p className="text-xs text-slate-600 mb-2">
        The claim evidence graph: each fact (row) as each document (column) states it. Orange =
        disagrees with the rest of its row; dashed = a report the file is missing.
      </p>
      <div className="overflow-x-auto">
        <table className="text-xs border-separate border-spacing-1">
          <thead>
            <tr>
              <th className="text-left text-slate-500 font-semibold">Fact</th>
              {m.docs.map((d) => (
                <th key={d.document_id} className="text-left text-slate-500 font-semibold capitalize">
                  {d.document_id === "(not in file)" ? "not in file" : docLabel(d.doc_type)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {m.facts.map((fact) => (
              <tr key={fact}>
                <th className="text-left font-medium text-slate-700 pr-2">{fact}</th>
                {m.docs.map((d) => {
                  const c = m.get(fact, d.document_id);
                  if (!c) return <td key={d.document_id} className="text-slate-400 text-center">—</td>;
                  const cls = c.status === "conflicts"
                    ? "bg-orange-100 border-2 border-orange-700 text-orange-950 font-semibold"
                    : c.status === "missing" ? "border-2 border-dashed border-orange-700 text-orange-900"
                    : "bg-white border border-slate-300";
                  return (
                    <td key={d.document_id} className={`rounded px-2 py-1 ${cls}`}>
                      {c.finding_ids[0] ? (
                        <button onClick={() => onFinding(c.finding_ids[0])} className="underline text-left">{c.value}</button>
                      ) : c.value}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FieldRowView({
  row,
  onLocate,
  onSave,
  selected,
}: {
  row: FieldRow;
  onLocate: () => void;
  onSave: (v: string) => void;
  selected: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(displayValue(row.field.value));
  const b = band(row.field.confidence);
  const corrected = row.field.flags.includes("reviewer_corrected");

  return (
    <div
      className={`border-l-4 rounded px-2 py-1.5 flex items-center gap-2 cursor-pointer ${BAND_STYLES[b]} ${
        selected ? "ring-2 ring-slate-400" : ""
      }`}
      onClick={onLocate}
    >
      <div className="flex-1 min-w-0">
        <div className="text-[11px] text-slate-500 capitalize truncate">{row.label}</div>
        {editing ? (
          <div className="flex gap-1 mt-1" onClick={(e) => e.stopPropagation()}>
            <input
              className="border rounded px-1 py-0.5 text-sm flex-1"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              autoFocus
            />
            <button
              className="text-xs bg-slate-800 text-white px-2 rounded"
              onClick={() => { onSave(draft); setEditing(false); }}
            >
              Save
            </button>
            <button className="text-xs px-2" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        ) : (
          <div className="text-sm font-medium truncate">{displayValue(row.field.value)}</div>
        )}
      </div>
      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${BAND_CHIP[b]}`}>
        {Math.round(row.field.confidence * 100)}%
      </span>
      {corrected && <span className="text-[10px] text-band-green" title="reviewer corrected">✓</span>}
      <button
        className="text-slate-500 hover:text-slate-700 text-sm"
        title="correct this field"
        aria-label="Correct this field"
        onClick={(e) => { e.stopPropagation(); setEditing(true); }}
      >
        ✎
      </button>
    </div>
  );
}

function Empty() {
  return (
    <div className="h-full flex items-center justify-center text-slate-500 text-sm">
      Select a claim to review.
    </div>
  );
}
