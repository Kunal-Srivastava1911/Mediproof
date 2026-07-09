# ui/ — React dashboard (W7)

React + Vite + Tailwind reviewer dashboard (HITL). **Four core interactions only** (scope
is capped here on purpose — plan §10a cut line 5):

1. **view** — doc image beside extracted fields, confidence colours (green/amber/red)
2. **click-to-evidence** — click a field → highlight its source bounding box
3. **correct** — edit a field; the correction is stored as training data
4. **approve** — accept the claim / a field

Talks to the `api/` service. Scaffolding lands in W7 alongside `make demo`.
