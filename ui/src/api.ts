import type { ClaimFile, ClaimSummary } from "./types";

// VITE_API_BASE may arrive as a bare host (e.g. Render injects "mediproof-api.onrender.com"
// via fromService); prepend https so fetch treats it as an absolute origin, not a path.
function resolveApiBase(): string {
  const raw = (import.meta.env.VITE_API_BASE as string | undefined)?.trim();
  if (!raw) return "http://localhost:8000";
  return /^https?:\/\//.test(raw) ? raw.replace(/\/$/, "") : `https://${raw}`;
}

const API: string = resolveApiBase();

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export interface ClaimStatusResponse {
  claim_id: string;
  status: string;
}

export const api = {
  listClaims: () => fetch(`${API}/claims`).then((r) => json<ClaimSummary[]>(r)),

  getClaim: (id: string) => fetch(`${API}/claims/${id}`).then((r) => json<ClaimFile>(r)),

  pageImage: (id: string, page: number) => `${API}/claims/${id}/pages/${page}.png`,

  review: (id: string, body: { document_id: string; field_path: string; new_value: string; reviewer?: string }) =>
    fetch(`${API}/claims/${id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => json<ClaimFile>(r)),

  uploadClaim: (file: File, claimType?: string) => {
    const body = new FormData();
    body.append("file", file);
    const qs = claimType ? `?claim_type=${encodeURIComponent(claimType)}` : "";
    return fetch(`${API}/claims${qs}`, { method: "POST", body }).then((r) =>
      json<ClaimStatusResponse>(r),
    );
  },

  getStatus: (id: string) =>
    fetch(`${API}/claims/${id}/status`).then((r) => json<ClaimStatusResponse>(r)),

  approve: (id: string) =>
    fetch(`${API}/claims/${id}/approve`, { method: "POST" }).then((r) => json<ClaimFile>(r)),

  deny: (id: string) =>
    fetch(`${API}/claims/${id}/deny`, { method: "POST" }).then((r) => json<ClaimFile>(r)),
};
