/**
 * Turn a failed request into text a person can act on: the HTTP status and what the server
 * said, or why there was no response at all. Never the request itself.
 *
 * An axios error carries the whole request in `err.config`, headers included. Nothing here
 * reads, shows or logs it, and every string that is shown is scrubbed for anything shaped like
 * a credential first, so a key cannot reach the page or the console even if a server echoes one.
 */
const SECRET_PATTERNS = [
  /sk-ant-[A-Za-z0-9_-]{6,}/g,
  /\bsk-[A-Za-z0-9_-]{16,}/g,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{8,}/gi,
];
const NAMED_SECRET = /(x-api-key|api[_-]?key|authorization|auth[_-]?token)(["']?\s*[:=]\s*["']?)([^\s"',}]+)/gi;

export function redactSecrets(text) {
  let out = String(text ?? "");
  for (const p of SECRET_PATTERNS) out = out.replace(p, "[redacted]");
  return out.replace(NAMED_SECRET, (_m, name, sep) => `${name}${sep}[redacted]`);
}

const MAX_TEXT = 300;
const clip = (s) => (s.length > MAX_TEXT ? `${s.slice(0, MAX_TEXT)}…` : s);

// FastAPI sends {"detail": "text"} or {"detail": [{"msg": ...}]}; a proxy sends an HTML page.
function serverText(data) {
  if (data == null || data === "") return "";
  if (typeof data === "string") {
    return data.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  }
  const detail = data.detail ?? data.message ?? data.error;
  if (detail == null) return "";
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? JSON.stringify(d)).join("; ");
  return typeof detail === "string" ? detail : JSON.stringify(detail);
}

/** -> { kind: "http" | "timeout" | "network", status: number | null, message: string } */
export function describeRequestError(err, { timeoutMs } = {}) {
  const res = err?.response;
  if (res) {
    const text = clip(redactSecrets(serverText(res.data)));
    const head = `HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ""}`;
    return { kind: "http", status: res.status, message: text ? `${head} — ${text}` : head };
  }
  if (err?.code === "ECONNABORTED" || err?.code === "ETIMEDOUT") {
    const seconds = timeoutMs ? ` after ${Math.round(timeoutMs / 1000)} seconds` : "";
    return {
      kind: "timeout", status: null,
      message: `No response from the server${seconds}. It may still be working; check again shortly.`,
    };
  }
  return {
    kind: "network", status: null,
    message: `No response from the server (${clip(redactSecrets(err?.message || "network error"))}). ` +
      "The backend may be down or unreachable from this page.",
  };
}

/** Log the description only - never the error object, which holds the request and its headers. */
export function logRequestFailure(context, described) {
  // eslint-disable-next-line no-console
  console.error(`[${context}] ${described.message}`);
}
