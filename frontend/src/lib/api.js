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
