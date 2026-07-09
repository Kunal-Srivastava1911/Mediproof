# ui/ — React reviewer dashboard (HITL)

React + Vite + Tailwind. Renders the `ClaimFile` graph the API serves. Scope is capped at the
**four core interactions** on purpose (plan §10a cut-line 5):

1. **view** — the page image beside the extracted fields, each coloured by its confidence
   band (🟢 green ≥ 0.8 · 🟡 amber 0.5–0.8 · 🔴 red < 0.5).
2. **click-to-evidence** — click a field (or a review item) → its grounded bounding box is
   highlighted on the page image. Powered by M3.5's `{page, bbox}` evidence.
3. **correct** — edit a field inline → `POST /claims/{id}/review`; the field is marked
   human-verified and the edit logged as training data.
4. **approve** — accept the claim for filing.

## Run it

```bash
cd ui
npm install
VITE_API_BASE=http://localhost:8000 npm run dev     # dev server on :5173
npm run build       # production build -> dist/
npm test            # vitest (band mapping + field flattener)
```

The API base defaults to `http://localhost:8000`; override with `VITE_API_BASE`.

## Layout

| File | Role |
|------|------|
| `src/App.tsx` | dashboard: claim/document pickers, page viewer + bbox overlay, fields panel, findings, approve |
| `src/lib.ts` | confidence→band styling and the `flattenFields` walker (extracted doc → dotted-path field rows) |
| `src/api.ts` | typed fetch wrappers over the API |
| `src/types.ts` | loose mirrors of `schemas/` |

The page image comes from `GET /claims/{id}/pages/{n}.png` (the API rasterizes the uploaded
PDF with pypdfium2); bboxes are normalized 0–1, so the overlay is positioned by percentage.
