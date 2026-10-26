# ui/ — React front end (submitter + reviewer)

React + Vite + Tailwind. One Vite app serves **two sites** by client-side path routing (no
router library): `main.tsx` renders `ReviewApp` when the path starts with `/review`, else
`SubmitApp`. Both are no-login.

## Submitter site (`/`)

For claimants, in **English or Hindi** (header toggle):

1. **check a claim** — upload a single claim PDF → `POST /claims`. The **Claim ID** is shown
   prominently, then the page polls the status while the claim is checked.
2. **fix-it checklist** — `GET /claims/{id}/checklist?lang=` — only verified, patient-facing
   items: a plain-language title, the detail, *what to do*, and the evidence (document · page ·
   quote, with **View page** opening the page with the box highlighted). Items can be marked
   done. If the AI cross-checks didn't run on the file, the page says only standard checks ran.
3. **claim chat** — `POST /claims/{id}/ask`: answers come only from the file, with the quoted
   source; "Ask about this" on an item pre-fills the question. If Claude isn't configured on the
   server, the chat says so.
4. **look up a claim** — enter a Claim ID → `GET /claims/{id}/status`, and reopen its checklist.
   The pipeline's granular states are hidden from claimants and collapsed into exactly **three
   buckets** (`lib.submitterBucket`):
   - **Not reviewed** (received / processing / processed / needs_review / **failed**)
   - **Reviewed — denied**
   - **Reviewed — approved**

## Reviewer site (`/review`)

The HITL dashboard. Scope is capped at the **four core interactions** on purpose
(plan §10a cut-line 5):

1. **view** — the page image beside the extracted fields, each coloured by its confidence
   band (🟢 green ≥ 0.8 · 🟡 amber 0.5–0.8 · 🔴 red < 0.5).
2. **click-to-evidence** — click a field (or a review item) → its grounded bounding box is
   highlighted on the page image. Powered by M3.5's `{page, bbox}` evidence.
3. **correct** — edit a field inline → `POST /claims/{id}/review`; the field is marked
   human-verified and the edit logged as training data.
4. **approve / deny** — record the review decision. Unlike the old client-only button, these now
   **persist** via `POST /claims/{id}/approve` and `POST /claims/{id}/deny`, which set the claim's
   status (`approved` / `denied`). Reviewer-site-only.

Plus the agent-auditor views:

- **review items** show who raised them (rule or which agent), what verified them, the verifier
  score; clicking one opens its **proof** (each quote, found-on-page or not — click to jump to
  its box), **How was this found?** (the trail), and **Confirm / Dismiss (reason) / Promote**
  (`POST /claims/{id}/findings/{fid}/decision`).
- **held back by verification** — agent items below the calibrated threshold, reviewer-only.
- **Timeline** tab — every dated event from every document on one calendar; disagreeing cells
  open their item. **Evidence map** tab — the claim evidence graph as facts × documents.
- a banner states what the agent auditor ran (agents, Claude calls, spend, threshold) or why
  it was skipped.

## Run it

```bash
cd ui
npm install
VITE_API_BASE=http://localhost:8000 npm run dev     # dev server on :5173
npm run build       # production build -> dist/
npm test            # vitest (band mapping + field flattener + submitter buckets)
npm run lint        # tsc -b --noEmit
```

The API base defaults to `http://localhost:8000`; override with `VITE_API_BASE`.

## Layout

| File | Role |
|------|------|
| `src/main.tsx` | path router: `/review*` → `ReviewApp`, else `SubmitApp` |
| `src/SubmitApp.tsx` | submitter site: upload + Claim-ID display, status lookup (three buckets) |
| `src/ReviewApp.tsx` | reviewer dashboard: claim/document pickers, page viewer + bbox overlay, fields panel, findings, approve/deny |
| `src/lib.ts` | confidence→band styling, `submitterBucket` mapping, and the `flattenFields` walker |
| `src/api.ts` | typed fetch wrappers over the API |
| `src/types.ts` | loose mirrors of `schemas/` |

The page image comes from `GET /claims/{id}/pages/{n}.png` (the API rasterizes the uploaded
PDF with pypdfium2); bboxes are normalized 0–1, so the overlay is positioned by percentage.
