import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { BUCKET_LABEL, BUCKET_STYLES, submitterBucket } from "./lib";
import type { ChatAnswer, Checklist, ChecklistItem, ChecklistSource } from "./types";

type Lang = "en" | "hi";

const T = {
  en: {
    subtitle: "check your claim before you file",
    intro: "Upload your claim file (one PDF with every page). MediProof checks that your documents are complete and agree with each other, and tells you what to fix before you file. It does not decide your treatment or payment.",
    submitTitle: "Check a claim",
    choose: "Claim PDF",
    submit: "Check my claim",
    submitting: "Uploading…",
    idSaved: "Your Claim ID — keep it to come back later:",
    copy: "Copy",
    copied: "Copied",
    checking: "Checking your claim: reading every page, comparing the documents with each other, and double-checking each finding against the page. This can take a minute.",
    checklistTitle: (n: number) => n === 0 ? "No problems found in your documents" : `Before you file: ${n} thing${n === 1 ? "" : "s"} worth checking`,
    done: (d: number, n: number) => `${d} of ${n} done`,
    whatToDo: "What to do:",
    markDone: "Mark as done",
    undo: "Undo",
    ask: "Ask about this",
    viewPage: "View page",
    page: "page",
    notTranslated: "Details are shown in English for now.",
    rulesOnly: "Only the standard checks ran on this file; the AI cross-checks were not available.",
    statusTitle: "Look up a claim",
    statusLabel: "Claim ID",
    statusBtn: "Look up",
    notFound: "We couldn't find a claim with that ID. Double-check the Claim ID you were given.",
    show: "Show checklist",
    chatTitle: "Ask about your claim",
    chatIntro: "Answers come only from your own documents, with the source quoted.",
    chatLabel: "Your question",
    chatPlaceholder: "e.g. Why do my ICU charges need checking?",
    send: "Send",
    sources: "From your documents:",
    close: "Close",
  },
  hi: {
    subtitle: "फ़ाइल करने से पहले अपना क्लेम जाँचें",
    intro: "अपनी क्लेम फ़ाइल अपलोड करें (सभी पेजों वाली एक PDF)। MediProof जाँचता है कि आपके दस्तावेज़ पूरे हैं और आपस में मेल खाते हैं, और बताता है कि फ़ाइल करने से पहले क्या ठीक करना है। यह आपके इलाज या भुगतान के बारे में कोई फ़ैसला नहीं करता।",
    submitTitle: "क्लेम जाँचें",
    choose: "क्लेम PDF",
    submit: "मेरा क्लेम जाँचें",
    submitting: "अपलोड हो रहा है…",
    idSaved: "आपकी क्लेम ID — बाद में देखने के लिए इसे सँभालकर रखें:",
    copy: "कॉपी करें",
    copied: "कॉपी हो गया",
    checking: "आपका क्लेम जाँचा जा रहा है: हर पेज पढ़ा जा रहा है, दस्तावेज़ों को आपस में मिलाया जा रहा है, और हर बात को पेज से दोबारा जाँचा जा रहा है। इसमें एक मिनट लग सकता है।",
    checklistTitle: (n: number) => n === 0 ? "आपके दस्तावेज़ों में कोई समस्या नहीं मिली" : `फ़ाइल करने से पहले: जाँचने लायक ${n} बातें`,
    done: (d: number, n: number) => `${n} में से ${d} पूरी`,
    whatToDo: "क्या करें:",
    markDone: "हो गया",
    undo: "वापस लें",
    ask: "इसके बारे में पूछें",
    viewPage: "पेज देखें",
    page: "पेज",
    notTranslated: "विवरण अभी अंग्रेज़ी में दिखाया गया है।",
    rulesOnly: "इस फ़ाइल पर सिर्फ़ सामान्य जाँच हुई; AI से आपसी जाँच उपलब्ध नहीं थी।",
    statusTitle: "क्लेम खोजें",
    statusLabel: "क्लेम ID",
    statusBtn: "देखें",
    notFound: "इस ID का कोई क्लेम नहीं मिला। अपनी क्लेम ID दोबारा जाँचें।",
    show: "चेकलिस्ट दिखाएँ",
    chatTitle: "अपने क्लेम के बारे में पूछें",
    chatIntro: "जवाब सिर्फ़ आपके अपने दस्तावेज़ों से आते हैं, स्रोत के हवाले के साथ।",
    chatLabel: "आपका सवाल",
    chatPlaceholder: "जैसे: मेरे ICU शुल्क की जाँच क्यों ज़रूरी है?",
    send: "भेजें",
    sources: "आपके दस्तावेज़ों से:",
    close: "बंद करें",
  },
};

const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-orange-800 text-white",
  warning: "bg-amber-100 text-amber-900",
  info: "bg-blue-100 text-blue-900",
};

const IN_FLIGHT = new Set(["received", "processing"]);

export default function SubmitApp() {
  const [lang, setLang] = useState<Lang>("en");
  const [claimId, setClaimId] = useState("");
  const t = T[lang];
  return (
    <div className="min-h-screen flex flex-col bg-slate-50" lang={lang}>
      <header className="bg-slate-900 text-white px-6 py-3">
        <div className="max-w-5xl mx-auto flex flex-wrap items-center justify-between gap-3">
          <div>
            <span className="font-bold text-lg">MediProof</span>
            <span className="ml-3 text-slate-300 text-sm">{t.subtitle}</span>
          </div>
          <div className="flex gap-1" role="group" aria-label="Language">
            {(["en", "hi"] as Lang[]).map((l) => (
              <button
                key={l}
                onClick={() => setLang(l)}
                aria-pressed={lang === l}
                className={`text-sm font-semibold rounded px-3 py-1.5 border border-slate-600 ${
                  lang === l ? "bg-white text-slate-900" : "text-white"
                }`}
              >
                {l === "en" ? "English" : "हिन्दी"}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="flex-1 w-full max-w-5xl mx-auto p-4 space-y-6">
        <p className="text-sm text-slate-600">{t.intro}</p>
        <UploadCard lang={lang} onClaim={setClaimId} />
        {claimId && <ClaimResult key={claimId} claimId={claimId} lang={lang} />}
        <StatusCard lang={lang} onShow={setClaimId} />
      </main>

      <footer className="w-full max-w-5xl mx-auto p-4 text-right">
        <a href="/review" className="text-sm text-slate-600 hover:text-slate-900">Reviewer sign-in →</a>
      </footer>
    </div>
  );
}

function UploadCard({ lang, onClaim }: { lang: Lang; onClaim: (id: string) => void }) {
  const t = T[lang];
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.uploadClaim(file);
      onClaim(res.claim_id);
    } catch (err) {
      setError(`${err} — is the API running on :8000?`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white rounded-lg shadow-sm p-4">
      <h2 className="font-semibold text-slate-700 mb-3">{t.submitTitle}</h2>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="text-sm text-slate-700 flex flex-col gap-1">
          {t.choose}
          <input
            type="file"
            accept="application/pdf,.pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={!file || busy}
          className="self-start bg-slate-800 hover:bg-slate-900 disabled:opacity-40 text-white text-sm font-semibold rounded px-4 py-2"
        >
          {busy ? t.submitting : t.submit}
        </button>
      </form>
      {error && <p className="mt-3 text-sm text-band-red">{error}</p>}
    </section>
  );
}

function ClaimResult({ claimId, lang }: { claimId: string; lang: Lang }) {
  const t = T[lang];
  const [status, setStatus] = useState("processing");
  const [checklist, setChecklist] = useState<Checklist | null>(null);
  const [done, setDone] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);
  const [question, setQuestion] = useState("");
  const [viewing, setViewing] = useState<ChecklistSource | null>(null);

  // Poll status until processing finishes.
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const s = await api.getStatus(claimId);
        if (!alive) return;
        setStatus(s.status);
        if (IN_FLIGHT.has(s.status)) timer = window.setTimeout(tick, 1500);
      } catch {
        if (alive) setStatus("failed");
      }
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [claimId]);

  useEffect(() => {
    if (IN_FLIGHT.has(status) || status === "failed") return;
    api.checklist(claimId, lang).then(setChecklist).catch(() => setChecklist(null));
  }, [claimId, lang, status]);

  const items = checklist?.items ?? [];
  const nDone = items.filter((i) => done.has(i.id)).length;
  const toggle = (id: string) => setDone((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <div className="flex flex-wrap items-start gap-6">
      <div className="flex-[999_1_520px] min-w-0 space-y-4">
        <div className="bg-white rounded-lg shadow-sm p-3 flex flex-wrap items-center gap-3">
          <span className="text-sm text-slate-600">{t.idSaved}</span>
          <code className="text-base font-bold text-slate-900 select-all">{claimId}</code>
          <button
            type="button"
            onClick={() => navigator.clipboard?.writeText(claimId).then(() => setCopied(true)).catch(() => {})}
            className="text-xs text-slate-600 hover:text-slate-900 underline"
          >
            {copied ? t.copied : t.copy}
          </button>
        </div>

        {IN_FLIGHT.has(status) && (
          <div className="bg-white rounded-lg shadow-sm p-4 flex items-center gap-3" role="status">
            <span className="inline-block w-5 h-5 rounded-full border-[3px] border-slate-300 border-t-slate-700 animate-spin" />
            <span className="text-sm text-slate-700">{t.checking}</span>
          </div>
        )}

        {checklist?.ready && (
          <section className="space-y-3">
            <div>
              <h1 className="text-xl font-semibold text-slate-900">{t.checklistTitle(items.length)}</h1>
              {items.length > 0 && (
                <div className="flex items-center gap-3 mt-2">
                  <div className="flex-1 h-2 rounded-full bg-slate-200 overflow-hidden">
                    <div className="h-2 bg-teal-700" style={{ width: `${(100 * nDone) / items.length}%` }} />
                  </div>
                  <span className="text-sm font-semibold text-teal-800">{t.done(nDone, items.length)}</span>
                </div>
              )}
              {lang === "hi" && checklist.detail_translated === false && items.length > 0 && (
                <p className="text-xs text-slate-600 mt-1">{t.notTranslated}</p>
              )}
              {checklist.audit_note && <p className="text-xs text-slate-600 mt-1">{t.rulesOnly}</p>}
            </div>
            {items.map((item) => (
              <ChecklistCard
                key={item.id}
                item={item}
                lang={lang}
                done={done.has(item.id)}
                onToggle={() => toggle(item.id)}
                onAsk={() => setQuestion(item.title)}
                onView={setViewing}
              />
            ))}
            <div className={`inline-block border rounded px-3 py-1.5 text-sm font-semibold ${BUCKET_STYLES[submitterBucket(status)]}`}>
              {BUCKET_LABEL[submitterBucket(status)]}
            </div>
          </section>
        )}
      </div>

      {checklist?.ready && (
        <ChatPanel claimId={claimId} lang={lang} question={question} setQuestion={setQuestion} />
      )}
      {viewing && viewing.page != null && (
        <PageModal claimId={claimId} source={viewing} lang={lang} onClose={() => setViewing(null)} />
      )}
    </div>
  );
}

function ChecklistCard({ item, lang, done, onToggle, onAsk, onView }: {
  item: ChecklistItem;
  lang: Lang;
  done: boolean;
  onToggle: () => void;
  onAsk: () => void;
  onView: (s: ChecklistSource) => void;
}) {
  const t = T[lang];
  return (
    <article className={`rounded-lg border p-4 space-y-3 ${done ? "bg-slate-50" : "bg-white"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${SEVERITY_STYLE[item.severity]}`}>
          {item.severity_label}
        </span>
        <h2 className={`font-semibold ${done ? "text-slate-500 line-through" : "text-slate-900"}`}>{item.title}</h2>
      </div>
      <p className="text-sm text-slate-700">{item.detail}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {item.sources.map((s, i) => (
          <figure key={i} className="m-0 border rounded p-2 bg-white">
            <figcaption className="text-xs font-semibold text-slate-600">
              {s.label}{s.page != null && ` · ${t.page} ${s.page + 1}`}
            </figcaption>
            {s.quote && <p className="text-sm font-serif text-slate-900 mt-1 bg-orange-50 outline outline-2 outline-orange-700 rounded px-1.5 py-0.5">{s.quote}</p>}
            {s.page != null && s.bbox && (
              <button onClick={() => onView(s)} className="text-xs underline text-slate-700 mt-1">{t.viewPage}</button>
            )}
          </figure>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t pt-3">
        <p className="text-sm text-slate-900 flex-1 min-w-[220px]"><b>{t.whatToDo}</b> {item.action}</p>
        <button onClick={onAsk} className="border border-slate-300 text-sm font-semibold rounded px-3 py-1.5">{t.ask}</button>
        <button onClick={onToggle} className="border border-slate-300 text-sm font-semibold rounded px-3 py-1.5">
          {done ? t.undo : t.markDone}
        </button>
      </div>
    </article>
  );
}

function ChatPanel({ claimId, lang, question, setQuestion }: {
  claimId: string;
  lang: Lang;
  question: string;
  setQuestion: (q: string) => void;
}) {
  const t = T[lang];
  const [log, setLog] = useState<Array<{ q: string; a?: ChatAnswer; error?: string }>>([]);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { if (question) input.current?.focus(); }, [question]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setQuestion("");
    try {
      const a = await api.ask(claimId, q);
      setLog((l) => [...l, { q, a }]);
    } catch (err) {
      setLog((l) => [...l, { q, error: err instanceof Error ? err.message : String(err) }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="flex-[1_1_300px] min-w-0 bg-white rounded-lg shadow-sm p-4 space-y-3">
      <h2 className="font-semibold text-slate-800">{t.chatTitle}</h2>
      <p className="text-xs text-slate-600">{t.chatIntro}</p>
      <div className="space-y-2 max-h-[480px] overflow-y-auto">
        {log.map((m, i) => (
          <div key={i} className="space-y-1">
            <div className="ml-auto max-w-[90%] w-fit bg-slate-800 text-white text-sm rounded-lg px-3 py-2">{m.q}</div>
            {m.a && (
              <div className="max-w-[95%] bg-slate-100 text-slate-900 text-sm rounded-lg px-3 py-2 space-y-1">
                <p>{m.a.answer}</p>
                {m.a.sources.length > 0 && (
                  <div className="text-xs text-slate-700">
                    <span className="font-semibold">{t.sources}</span>
                    {m.a.sources.map((s, j) => <q key={j} className="block font-serif">{s.quote}</q>)}
                  </div>
                )}
              </div>
            )}
            {m.error && <div className="text-sm text-band-red">{m.error}</div>}
          </div>
        ))}
      </div>
      <form onSubmit={send} className="flex flex-wrap gap-2 items-end">
        <label className="flex-1 min-w-[160px] text-xs font-semibold text-slate-600 flex flex-col gap-1">
          {t.chatLabel}
          <input
            ref={input}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t.chatPlaceholder}
            className="border rounded px-2 py-2 text-sm font-normal text-slate-900"
          />
        </label>
        <button type="submit" disabled={busy || !question.trim()}
                className="bg-slate-800 disabled:opacity-40 text-white text-sm font-semibold rounded px-4 py-2">
          {t.send}
        </button>
      </form>
    </aside>
  );
}

function PageModal({ claimId, source, lang, onClose }: {
  claimId: string;
  source: ChecklistSource;
  lang: Lang;
  onClose: () => void;
}) {
  const t = T[lang];
  const b = source.bbox!;
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-10" role="dialog" aria-modal="true">
      <div className="bg-white rounded-lg max-w-3xl w-full max-h-[90vh] overflow-auto p-3 space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-sm font-semibold text-slate-700">{source.label} · {t.page} {source.page! + 1}</span>
          <button onClick={onClose} className="text-sm underline">{t.close}</button>
        </div>
        <div className="relative">
          <img src={api.pageImage(claimId, source.page!)} alt={source.label} className="w-full border rounded" />
          <div
            className="absolute border-2 border-orange-700 bg-orange-500/20 rounded-sm"
            style={{ left: `${b.x0 * 100}%`, top: `${b.y0 * 100}%`,
                     width: `${(b.x1 - b.x0) * 100}%`, height: `${(b.y1 - b.y0) * 100}%` }}
          />
        </div>
      </div>
    </div>
  );
}

function StatusCard({ lang, onShow }: { lang: Lang; onShow: (id: string) => void }) {
  const t = T[lang];
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);

  async function check(e: React.FormEvent) {
    e.preventDefault();
    const id = query.trim();
    if (!id) return;
    setBusy(true);
    setStatus(null);
    setNotFound(false);
    try {
      setStatus((await api.getStatus(id)).status);
    } catch {
      setNotFound(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white rounded-lg shadow-sm p-4">
      <h2 className="font-semibold text-slate-700 mb-3">{t.statusTitle}</h2>
      <form onSubmit={check} className="flex flex-wrap gap-2 items-end">
        <label className="flex-1 min-w-[200px] text-xs font-semibold text-slate-600 flex flex-col gap-1">
          {t.statusLabel}
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="border rounded px-2 py-1.5 text-sm font-normal"
          />
        </label>
        <button type="submit" disabled={!query.trim() || busy}
                className="bg-slate-800 hover:bg-slate-900 disabled:opacity-40 text-white text-sm font-semibold rounded px-4 py-1.5">
          {t.statusBtn}
        </button>
      </form>
      {notFound && <p className="mt-3 text-sm text-slate-600">{t.notFound}</p>}
      {status && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <span className={`inline-block border rounded px-3 py-1.5 text-sm font-semibold ${BUCKET_STYLES[submitterBucket(status)]}`}>
            {BUCKET_LABEL[submitterBucket(status)]}
          </span>
          <button onClick={() => onShow(query.trim())} className="text-sm underline text-slate-700">{t.show}</button>
        </div>
      )}
    </section>
  );
}
