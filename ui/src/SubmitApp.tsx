import { useState } from "react";
import { api } from "./api";
import { BUCKET_LABEL, BUCKET_STYLES, submitterBucket } from "./lib";

export default function SubmitApp() {
  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <header className="bg-slate-900 text-white px-6 py-3">
        <div className="max-w-3xl mx-auto">
          <span className="font-bold text-lg">MediProof</span>
          <span className="ml-3 text-slate-300 text-sm">submit a claim</span>
        </div>
      </header>

      <main className="flex-1 w-full max-w-3xl mx-auto p-4 space-y-6">
        <p className="text-sm text-slate-500">
          Upload your claim document and keep the Claim ID you receive — it is the only way to
          check your claim's status later.
        </p>
        <UploadCard />
        <StatusCard />
      </main>

      <footer className="w-full max-w-3xl mx-auto p-4 text-right">
        <a href="/review" className="text-sm text-slate-500 hover:text-slate-800">
          Reviewer sign-in →
        </a>
      </footer>
    </div>
  );
}

function UploadCard() {
  const [file, setFile] = useState<File | null>(null);
  const [claimId, setClaimId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");
  const [copied, setCopied] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    setClaimId("");
    try {
      const res = await api.uploadClaim(file);
      setClaimId(res.claim_id);
    } catch (err) {
      setError(`${err} — is the API running on :8000?`);
    } finally {
      setBusy(false);
    }
  }

  async function copyId() {
    try {
      await navigator.clipboard.writeText(claimId);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="bg-white rounded-lg shadow-sm p-4">
      <h2 className="font-semibold text-slate-700 mb-3">Submit a claim</h2>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <input
          type="file"
          accept="application/pdf,.pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm"
        />
        <button
          type="submit"
          disabled={!file || busy}
          className="self-start bg-slate-800 hover:bg-slate-900 disabled:opacity-40 text-white text-sm font-semibold rounded px-4 py-1.5"
        >
          {busy ? "Submitting…" : "Submit"}
        </button>
      </form>

      {error && <p className="mt-3 text-sm text-band-red">{error}</p>}

      {claimId && (
        <div className="mt-4 border border-green-300 bg-green-50 rounded p-3">
          <p className="text-sm text-slate-600">Your claim was received. Save this Claim ID:</p>
          <div className="mt-1 flex items-center gap-3">
            <code className="text-lg font-bold text-slate-900 select-all">{claimId}</code>
            <button
              type="button"
              onClick={copyId}
              className="text-xs text-slate-500 hover:text-slate-800 underline"
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function StatusCard() {
  const [query, setQuery] = useState("");
  const [bucket, setBucket] = useState<ReturnType<typeof submitterBucket> | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);

  async function check(e: React.FormEvent) {
    e.preventDefault();
    const id = query.trim();
    if (!id) return;
    setBusy(true);
    setBucket(null);
    setNotFound(false);
    try {
      const res = await api.getStatus(id);
      setBucket(submitterBucket(res.status));
    } catch {
      setNotFound(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white rounded-lg shadow-sm p-4">
      <h2 className="font-semibold text-slate-700 mb-3">Check your claim's status</h2>
      <form onSubmit={check} className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter your Claim ID"
          className="flex-1 border rounded px-2 py-1.5 text-sm"
        />
        <button
          type="submit"
          disabled={!query.trim() || busy}
          className="bg-slate-800 hover:bg-slate-900 disabled:opacity-40 text-white text-sm font-semibold rounded px-4"
        >
          {busy ? "Checking…" : "Check"}
        </button>
      </form>

      {notFound && (
        <p className="mt-3 text-sm text-slate-500">
          We couldn't find a claim with that ID. Double-check the Claim ID you were given.
        </p>
      )}

      {bucket && (
        <div className={`mt-3 inline-block border rounded px-3 py-1.5 text-sm font-semibold ${BUCKET_STYLES[bucket]}`}>
          {BUCKET_LABEL[bucket]}
        </div>
      )}
    </section>
  );
}
