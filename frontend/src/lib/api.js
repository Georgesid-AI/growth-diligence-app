import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export const listAudits = () => api.get("/audits").then((r) => r.data);
export const getAudit = (id) => api.get(`/audits/${id}`).then((r) => r.data);
export const createAudit = (payload) => api.post("/audits", payload).then((r) => r.data);
export const updateAudit = (id, payload) => api.put(`/audits/${id}`, payload).then((r) => r.data);
// The company name goes in the body, never the URL, so no access log holds it (chat-upload.md section 6.3).
export const deleteAudit = (id, confirm) => api.delete(`/audits/${id}`, { data: { confirm } }).then((r) => r.data);
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

// Chat upload (docs/specs/chat-upload.md): one file at a time, its type detected unless dtype is given; a loaded
// type with other bytes answers 409 unless replace is true.
export const uploadChatFile = (id, file, { dtype, replace } = {}) => {
  const fd = new FormData();
  fd.append("file", file);
  const params = {};
  if (dtype) params.dtype = dtype;
  if (replace) params.replace = true;
  return api
    .post(`/audits/${id}/datasets/upload`, fd, { params, headers: { "Content-Type": "multipart/form-data" } })
    .then((r) => r.data);
};
export const getDatasets = (id) => api.get(`/audits/${id}/datasets`).then((r) => r.data.datasets);
export const decideColumns = (id, dtype, decisions) =>
  api.post(`/audits/${id}/datasets/${dtype}/decisions`, decisions).then((r) => r.data);
export const getBlockers = (id) => api.get(`/audits/${id}/blockers`).then((r) => r.data.blockers);
// Usage counters: the screen the analyst is on, or the extension of a file the browser refused. Never a name or a value.
export const reportUsage = (id, event) => api.post(`/audits/${id}/usage`, event).then((r) => r.data).catch(() => null);
export const getUsageTotals = () => api.get("/usage/totals").then((r) => r.data);

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

// Claim register (docs/specs/claim-matching.md): rows tested and ranked by the server, the analyst's inputs, and the CSV baseline.
export const getClaimRegister = (id) => api.get(`/audits/${id}/claims`).then((r) => r.data);
export const updateClaimInputs = (id, claimId, payload) =>
  api.put(`/audits/${id}/claims/${encodeURIComponent(claimId)}`, payload).then((r) => r.data);
// One click, Revenue or Volume, with a reason code (docs/specs/claim-matching.md section 11).
export const answerTurnover = (id, claimId, payload) =>
  api.put(`/audits/${id}/claims/${encodeURIComponent(claimId)}/turnover`, payload).then((r) => r.data);
export const claimsCsvUrl = (id) => `${API}/audits/${id}/claims.csv`;

// Verdict, data gaps and the IC memo (docs/specs/verdict-and-memo.md): computed on read by the server from the register, the
// results and the analyst's inputs. No model is called.
export const getVerdict = (id) => api.get(`/audits/${id}/verdict`).then((r) => r.data);
export const putIcInputs = (id, payload) => api.put(`/audits/${id}/ic-inputs`, payload).then((r) => r.data);
export const getMemo = (id) => api.get(`/audits/${id}/memo.md`, { responseType: "text", transformResponse: (d) => d });

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
