import axios from "axios";
import { READ_TIMEOUT_MS } from "@/lib/requestError";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

// Access links (docs/specs/access-links.md): the token from the tester's link is kept in the browser and sent on every request.
export const TOKEN_KEY = "access_token";
export const getToken = () => { try { return window.localStorage.getItem(TOKEN_KEY); } catch (e) { return null; } };
export const setToken = (token) => { try { window.localStorage.setItem(TOKEN_KEY, token); } catch (e) { /* the link then works for this page only */ } };
export const clearToken = () => { try { window.localStorage.removeItem(TOKEN_KEY); } catch (e) { /* nothing stored */ } };
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token && !(config.headers && config.headers.Authorization)) {     // an owner call carries its own token
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/** A file download that carries the token (a plain link cannot): the response is saved under the server's file name. */
export const downloadFile = async (path, fallbackName) => {
  const r = await api.get(path, { responseType: "blob" });
  const name = /filename="?([^";]+)"?/.exec(r.headers?.["content-disposition"] || "")?.[1] || fallbackName;
  const url = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
};

export const listAudits = () => api.get("/audits").then((r) => r.data);
export const getAudit = (id) => api.get(`/audits/${id}`, { timeout: READ_TIMEOUT_MS }).then((r) => r.data);
export const createAudit = (payload) => api.post("/audits", payload).then((r) => r.data);
export const updateAudit = (id, payload) => api.put(`/audits/${id}`, payload).then((r) => r.data);
// The company name goes in the body, never the URL, so no access log holds it (chat-upload.md section 6.3).
export const deleteAudit = (id, confirm) => api.delete(`/audits/${id}`, { data: { confirm } }).then((r) => r.data);
export const getResults = (id) => api.get(`/audits/${id}/results`).then((r) => r.data);
export const exportUrl = (id) => `${API}/audits/${id}/export`;
export const computeAudit = (id) => api.post(`/audits/${id}/compute`).then((r) => r.data);
// Upload (docs/design/read-check-review.md section 3): one file at a time, stored and read by the sheet reader; no type, no mapping.
// A read that gets no answer for UPLOAD_TIMEOUT_MS is given up, so the file can be attached again (a hung request left it stuck).
export const UPLOAD_TIMEOUT_MS = 120000;
export const uploadChatFile = (id, file) => {
  const fd = new FormData();
  fd.append("file", file);
  return api
    .post(`/audits/${id}/datasets/upload`, fd, { timeout: UPLOAD_TIMEOUT_MS, headers: { "Content-Type": "multipart/form-data" } })
    .then((r) => r.data);
};
export const getDatasets = (id) => api.get(`/audits/${id}/datasets`, { timeout: READ_TIMEOUT_MS }).then((r) => r.data.datasets);
export const getBlockers = (id) => api.get(`/audits/${id}/blockers`).then((r) => r.data.blockers);
// Usage counters: the screen the analyst is on, or the extension of a file the browser refused. Never a name or a value.
export const reportUsage = (id, event) => api.post(`/audits/${id}/usage`, event).then((r) => r.data).catch(() => null);
// The tester's monthly AI allowance and use (docs/specs/usage-and-allowance.md section 4); 404 for the owner token.
export const getAllowance = () => api.get("/allowance").then((r) => r.data);

// Board decks: upload parses the file and lists candidate claims; Python enters the ones no check asks about, the analyst keeps,
// rejects or edits the others (docs/design/simplified-flow.md).
export const uploadDeck = (id, file) => {
  const fd = new FormData();
  fd.append("file", file);
  return api
    .post(`/audits/${id}/decks/upload`, fd, { headers: { "Content-Type": "multipart/form-data" } })
    .then((r) => r.data);
};
export const getDecks = (id) => api.get(`/audits/${id}/decks`, { timeout: READ_TIMEOUT_MS }).then((r) => r.data);
export const removeDeck = (id, deckId) => api.delete(`/audits/${id}/decks/${deckId}`).then((r) => r.data);
export const addClaim = (id, payload) => api.post(`/audits/${id}/decks/candidates`, payload).then((r) => r.data);
export const updateCandidate = (id, candidateId, payload) =>
  api.put(`/audits/${id}/decks/candidates/${candidateId}`, payload).then((r) => r.data);
/** A correction a check applied before the register ({index, action: "undo"}), or the candidate chosen for one that waits
 *  ({index, action: "choose", option}); claim-matching.md section 33. */
export const answerCorrection = (id, candidateId, payload) =>
  api.post(`/audits/${id}/decks/candidates/${candidateId}/correction`, payload).then((r) => r.data);
/** "Is 'Sales' in this deck revenue or bookings?": answer is "revenue" or "bookings", for every Sales claim of the deck. */
// "Keep undated" (George, 2026-10-27): the claims stay without a period and ask nothing more.
export const keepUndated = (id, claimIds) => api.put(`/audits/${id}/undated-periods`, { claim_ids: claimIds }).then((r) => r.data);
export const answerSales = (id, deckId, answer) => api.put(`/audits/${id}/decks/${encodeURIComponent(deckId)}/sales`, { as: answer }).then((r) => r.data);
// Add from deck (docs/specs/claim-types-and-correction.md section 5): a stored page's lines, and a claim from one of them by reference.
export const getDeckPage = (id, deckId, page) => api.get(`/audits/${id}/decks/${deckId}/pages/${page}`).then((r) => r.data);
export const addFromDeck = (id, deckId, { page, ref }) => api.post(`/audits/${id}/decks/${deckId}/add-from-deck`, { page, ref }).then((r) => r.data);

// Claim register (docs/specs/claim-matching.md): rows tested and ranked by the server, the analyst's inputs, and the CSV baseline.
export const getClaimRegister = (id) => api.get(`/audits/${id}/claims`).then((r) => r.data);
export const updateClaimInputs = (id, claimId, payload) =>
  api.put(`/audits/${id}/claims/${encodeURIComponent(claimId)}`, payload).then((r) => r.data);
// The audit's FX rates: they apply to the uploaded files and to the deck claims alike.
export const saveFx = (id, fx) => api.put(`/audits/${id}/fx`, { fx }).then((r) => r.data);

// One click, Revenue or Volume, with a reason code (docs/specs/claim-matching.md section 11).
export const answerTurnover = (id, claimId, payload) =>
  api.put(`/audits/${id}/claims/${encodeURIComponent(claimId)}/turnover`, payload).then((r) => r.data);
/** "Same metric and period?" for a gap beyond 50% of the claim (claim-matching.md section 4.1): answer is "yes" or "no". */
export const answerDefinitionCheck = (id, claimId, answer) =>
  api.put(`/audits/${id}/claims/${encodeURIComponent(claimId)}/definition-check`, { answer }).then((r) => r.data);
export const claimsCsvUrl = (id) => `${API}/audits/${id}/claims.csv`;
// The question a group raises (docs/specs/claim-groups.md section 5): which annual figure, or which set of parts. The choice is the candidate's
// identity (or the name of a set); Undo asks the question again. Both give the register and the groups back.
export const chooseGroup = (id, reviewId, choice) => api.put(`/audits/${id}/claim-groups/${reviewId}`, { choice }).then((r) => r.data);
export const undoGroupChoice = (id, reviewId) => api.delete(`/audits/${id}/claim-groups/${reviewId}`).then((r) => r.data);

// Verdict, data gaps and the IC memo (docs/specs/verdict-and-memo.md): computed on read by the server from the register, the
// results and the analyst's inputs. No model is called.
export const getVerdict = (id) => api.get(`/audits/${id}/verdict`).then((r) => r.data);
// Data integrity: results of the completed checks, assessment coverage and the conclusion (docs/specs/integrity-coverage.md).
export const getIntegrity = (id) => api.get(`/audits/${id}/integrity`).then((r) => r.data);
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
// AI-provenance block (model + generation time) for the foot of the analysis.
// Read-only; the same text is written into the exports.
export const getDisclosure = (id) => api.get(`/runs/${id}/disclosure`).then((r) => r.data.disclosure);

// Run audit (one button): three stages in order, each answering done, waiting, running or failed with a plain-English
// message; and what the Audit page opens with. The files themselves go through the endpoints above.
export const runStage = (id, stage) => api.post(`/audits/${id}/run/${stage}`, null, { timeout: 120000 }).then((r) => r.data);
export const getReview = (id) => api.get(`/audits/${id}/review`, { timeout: READ_TIMEOUT_MS }).then((r) => r.data);
// What "Write all narratives" would run and its upper-bound cost; reads only, no provider call.
export const getNarrativeEstimate = (id) => api.get(`/runs/${id}/narratives/estimate`).then((r) => r.data);

// Owner page (docs/specs/prompt-store.md): the owner token is passed per call, from memory, and replaces any tester token.
// Prompt text goes up and never comes back: the list holds name, version, date and hash. Tester links use the admin routes of
// docs/specs/access-links.md section 2.
const asOwner = (token) => ({ headers: { Authorization: `Bearer ${token}` } });
export const ownerPrompts = (token) => api.get("/admin/prompts", asOwner(token)).then((r) => r.data);
export const ownerUploadPrompt = (token, name, text) => api.post("/admin/prompts", { name, text }, asOwner(token)).then((r) => r.data);
export const ownerTesters = (token) => api.get("/admin/testers", asOwner(token)).then((r) => r.data);
export const ownerIssueTester = (token, label) => api.post("/admin/testers", { label }, asOwner(token)).then((r) => r.data);
export const ownerRevokeTester = (token, id) => api.post(`/admin/testers/${id}/revoke`, null, asOwner(token)).then((r) => r.data);
export const ownerReissueTester = (token, id) => api.post(`/admin/testers/${id}/reissue`, null, asOwner(token)).then((r) => r.data);
export const ownerUsage = (token) => api.get("/admin/usage", asOwner(token)).then((r) => r.data);
export const ownerAuditCosts = (token) => api.get("/admin/audit-costs", asOwner(token)).then((r) => r.data);
export const ownerSetAllowance = (token, id, allowance_usd) => api.post(`/admin/testers/${id}/allowance`, { allowance_usd }, asOwner(token)).then((r) => r.data);

// The reading screen (docs/design/read-check-review.md section 11; PR 3): the register, the cards, the analyst's Change, the cell a Source cites.
export const getReading = (id) => api.get(`/audits/${id}/reading`).then((r) => r.data);
export const decideCard = (id, cardId, body) => api.post(`/audits/${id}/cards/${cardId}`, body).then((r) => r.data);
export const changeReading = (id, fileHash, body) => api.post(`/audits/${id}/readings/${fileHash}/change`, body).then((r) => r.data);
export const getCell = (id, fileHash, sheet, cell) => api.get(`/audits/${id}/readings/${fileHash}/cell`, { params: { sheet, cell } }).then((r) => r.data);
export const downloadReading = (id, fileHash, format) => downloadFile(`/audits/${id}/readings/${fileHash}/export?format=${format}`, `reading.${format}`);
