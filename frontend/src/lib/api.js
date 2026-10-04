import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export const listAudits = () => api.get("/audits").then((r) => r.data);
export const getAudit = (id) => api.get(`/audits/${id}`).then((r) => r.data);
export const createAudit = (payload) => api.post("/audits", payload).then((r) => r.data);
export const updateAudit = (id, payload) => api.put(`/audits/${id}`, payload).then((r) => r.data);
export const deleteAudit = (id) => api.delete(`/audits/${id}`).then((r) => r.data);
export const getResults = (id) => api.get(`/audits/${id}/results`).then((r) => r.data);
export const exportUrl = (id) => `${API}/audits/${id}/export`;
export const getFields = () => api.get("/fields").then((r) => r.data);
export const computeAudit = (id) => api.post(`/audits/${id}/compute`).then((r) => r.data);
export const saveMapping = (id, dtype, payload) =>
  api.put(`/audits/${id}/datasets/${dtype}/mapping`, payload).then((r) => r.data);

export const getRevenueCustomers = (id, customerCol) =>
  api.get(`/audits/${id}/datasets/revenue/customers`, { params: customerCol ? { customer_col: customerCol } : {} }).then((r) => r.data);

export const uploadDataset = (id, dtype, file) => {
  const fd = new FormData();
  fd.append("file", file);
  return api
    .post(`/audits/${id}/datasets/${dtype}/upload`, fd, { headers: { "Content-Type": "multipart/form-data" } })
    .then((r) => r.data);
};

// Board decks: upload parses the file and lists candidate claims; the analyst approves,
// rejects or edits each one.
export const uploadDeck = (id, file) => {
  const fd = new FormData();
  fd.append("file", file);
  return api
    .post(`/audits/${id}/decks/upload`, fd, { headers: { "Content-Type": "multipart/form-data" } })
    .then((r) => r.data);
};
export const getDecks = (id) => api.get(`/audits/${id}/decks`).then((r) => r.data);
export const removeDeck = (id, deckId) => api.delete(`/audits/${id}/decks/${deckId}`).then((r) => r.data);
export const updateCandidate = (id, candidateId, payload) =>
  api.put(`/audits/${id}/decks/candidates/${candidateId}`, payload).then((r) => r.data);

// Narrative gateway. GET is read-only — it returns an existing narrative or
// narrative_status "not_generated", and can never call the model provider.
// POST is the only path that spends an AI request.
export const readNarrative = (id, step) =>
  api.get(`/runs/${id}/narrative/${step}`).then((r) => r.data);
// A generation takes about 33 seconds uncached. The client gives up at 150 s: well above that, and
// above the server's own worst case for one retry (provider timeout 60 s plus backoff), so a slow
// call is not cut short and a hung one is still reported rather than spinning forever.
export const NARRATIVE_EXPECTED_SECONDS = 33;
export const NARRATIVE_TIMEOUT_MS = 150_000;
export const generateNarrative = (id, step) =>
  api.post(`/runs/${id}/narrative/${step}`, null, { timeout: NARRATIVE_TIMEOUT_MS }).then((r) => r.data);
export const getLlmUsage = (id) => api.get(`/runs/${id}/llm-usage`).then((r) => r.data);
// AI-provenance block (model + generation time) for the foot of the analysis.
// Read-only; the same text is written into the exports.
export const getDisclosure = (id) => api.get(`/runs/${id}/disclosure`).then((r) => r.data.disclosure);
