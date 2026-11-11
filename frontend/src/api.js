const BASE = "/api";
const JSON_HEADERS = { "Content-Type": "application/json" };

async function req(path, options = {}) {
  const res = await fetch(BASE + path, options);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not json */
    }
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

const send = (method, path, body) =>
  req(path, { method, headers: JSON_HEADERS, body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => req("/health"),
  accounts: () => req("/accounts"),
  promptTemplate: () => req("/prompt-template"),

  companies: () => req("/companies"),
  company: (id) => req(`/companies/${id}`),
  createCompany: (body) => send("POST", "/companies", body),
  updateCompany: (id, body) => send("PUT", `/companies/${id}`, body),
  deleteCompany: (id) => send("DELETE", `/companies/${id}`),

  documents: (companyId) => req(`/companies/${companyId}/documents`),
  upload: (companyId, files) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return req(`/companies/${companyId}/documents`, { method: "POST", body: fd });
  },
  document: (id) => req(`/documents/${id}`),
  updateDocumentData: (id, data) => send("PUT", `/documents/${id}/data`, data),
  approve: (id) => send("POST", `/documents/${id}/approve`),
  reprocess: (id) => send("POST", `/documents/${id}/reprocess`),
  deleteDocument: (id) => send("DELETE", `/documents/${id}`),

  fileUrl: (id) => `${BASE}/documents/${id}/file`,
  xmlUrl: (id) => `${BASE}/documents/${id}/xml`,
  exportUrl: (companyId, { dateFrom, dateTo, includeUnreviewed }) => {
    const p = new URLSearchParams();
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    if (includeUnreviewed) p.set("include_unreviewed", "true");
    return `${BASE}/companies/${companyId}/export.xml?${p}`;
  },
};
