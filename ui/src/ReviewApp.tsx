import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import {
  BAND_CHIP,
  BAND_STYLES,
  SEVERITY_CHIP,
  band,
  displayValue,
  flattenFields,
} from "./lib";
import type { ClaimFile, ClaimSummary, Evidence, FieldRow } from "./types";

export default function ReviewApp() {
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [claimId, setClaimId] = useState<string>("");
  const [claim, setClaim] = useState<ClaimFile | null>(null);
  const [docIdx, setDocIdx] = useState(0);
  const [active, setActive] = useState<Evidence | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    api.listClaims().then((c) => {
      setClaims(c);
      if (c.length && !claimId) setClaimId(c[0].claim_id);
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!claimId) return;
    setActive(null);
    setDocIdx(0);
    api.getClaim(claimId).then(setClaim).catch((e) => setError(String(e)));
  }, [claimId]);

  const doc = claim?.documents[docIdx];
  const shownPage = active?.page ?? doc?.page_range[0] ?? 0;
  const fields = useMemo(() => flattenFields(doc?.extracted ?? null), [doc]);

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

  return (
    <div className="min-h-screen flex flex-col">
      <Header claim={claim} />
      {error && <div className="bg-red-100 text-band-red px-6 py-2 text-sm">{error} — is the API running on :8000?</div>}

      <div className="flex-1 grid grid-cols-12 gap-4 p-4 max-w-[1500px] w-full mx-auto">
        <Sidebar
          claims={claims}
          claimId={claimId}
          onPick={setClaimId}
          claim={claim}
          docIdx={docIdx}
          onDoc={(i) => { setDocIdx(i); setActive(null); }}
          onFinding={(ev) => setActive(ev)}
          onApprove={() => decide("approve")}
          onDeny={() => decide("deny")}
        />

        <main className="col-span-5 bg-white rounded-lg shadow-sm p-3">
          {claim && doc ? (
            <PageViewer
              src={api.pageImage(claim.claim_id, shownPage)}
              evidence={active && active.page === shownPage ? active : null}
              caption={`${doc.doc_type.replace(/_/g, " ")} · page ${shownPage + 1}`}
            />
          ) : (
            <Empty />
          )}
        </main>

        <section className="col-span-4 bg-white rounded-lg shadow-sm p-3 overflow-auto max-h-[calc(100vh-9rem)]">
          <h2 className="font-semibold text-slate-700 mb-2">
            Extracted fields{" "}
            <span className="text-xs font-normal text-slate-400">
              (click a row to locate it · pencil to correct)
            </span>
          </h2>
          <div className="space-y-1">
            {fields.map((row) => (
              <FieldRowView
                key={row.path}
                row={row}
                onLocate={() => setActive(row.field.evidence[0] ?? null)}
                onSave={(v) => saveCorrection(row, v)}
                selected={active != null && row.field.evidence[0] === active}
              />
            ))}
            {!fields.length && <p className="text-sm text-slate-400">No extracted fields.</p>}
          </div>
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
          <a href="/" className="ml-4 text-slate-400 hover:text-white text-xs">← Submitter site</a>
        </div>
        <div className="flex items-center gap-3">
          {claim && <StatusPill status={claim.status} />}
          <span className="text-[11px] text-slate-400 max-w-sm text-right">
            Documentation QA — not a clinical or payment decision. Findings are review items.
          </span>
        </div>
      </div>
    </header>
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
  onDoc: (i: number) => void;
  onFinding: (ev: Evidence) => void;
  onApprove: () => void;
  onDeny: () => void;
}) {
  const { claims, claimId, onPick, claim, docIdx, onDoc, onFinding, onApprove, onDeny } = props;
  const decided = claim?.status === "approved" || claim?.status === "denied";
  return (
    <aside className="col-span-3 space-y-4">
      <div className="bg-white rounded-lg shadow-sm p-3">
        <label className="text-xs font-semibold text-slate-500">Claim</label>
        <select
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
              <button
                onClick={onApprove}
                className="bg-green-700 hover:bg-green-800 text-white text-sm font-semibold rounded py-1.5"
              >
                Approve
              </button>
              <button
                onClick={onDeny}
                className="bg-red-700 hover:bg-red-800 text-white text-sm font-semibold rounded py-1.5"
              >
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
                {d.doc_type.replace(/_/g, " ")}
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
          <h3 className="text-xs font-semibold text-slate-500 mb-2">
            Review items ({claim.findings.length})
          </h3>
          <div className="space-y-2">
            {claim.findings.map((f) => (
              <button
                key={f.id}
                onClick={() => f.evidence[0] && onFinding(f.evidence[0])}
                className="block w-full text-left border rounded p-2 hover:bg-slate-50"
              >
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${SEVERITY_CHIP[f.severity]}`}>
                  {f.severity}
                </span>
                <span className="ml-2 text-sm font-medium">{f.title}</span>
                <p className="text-xs text-slate-500 mt-1">{f.detail}</p>
              </button>
            ))}
            {!claim.findings.length && <p className="text-sm text-slate-400">No review items.</p>}
          </div>
        </div>
      )}
    </aside>
  );
}

function PageViewer({ src, evidence, caption }: { src: string; evidence: Evidence | null; caption: string }) {
  return (
    <div>
      <div className="text-xs text-slate-400 mb-2 capitalize">{caption}</div>
      <div className="relative inline-block w-full">
        <img src={src} alt={caption} className="w-full rounded border" />
        {evidence && (
          <div
            className="absolute border-2 border-band-red bg-red-500/20 rounded-sm transition-all"
            style={{
              left: `${evidence.bbox.x0 * 100}%`,
              top: `${evidence.bbox.y0 * 100}%`,
              width: `${(evidence.bbox.x1 - evidence.bbox.x0) * 100}%`,
              height: `${(evidence.bbox.y1 - evidence.bbox.y0) * 100}%`,
            }}
          />
        )}
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
        className="text-slate-400 hover:text-slate-700 text-sm"
        title="correct this field"
        onClick={(e) => { e.stopPropagation(); setEditing(true); }}
      >
        ✎
      </button>
    </div>
  );
}

function Empty() {
  return (
    <div className="h-full flex items-center justify-center text-slate-400 text-sm">
      Select a claim to review.
    </div>
  );
}
