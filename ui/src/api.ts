import type { ClaimFile, ClaimSummary } from "./types";

const API: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
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
};
