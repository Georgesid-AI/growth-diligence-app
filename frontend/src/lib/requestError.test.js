import { describeRequestError, redactSecrets, logRequestFailure } from "./requestError";

const KEY = "sk-ant-api03-ABCDEFGHIJKLMNOP1234567890";

test("an HTTP failure shows the status and the server's text", () => {
  const d = describeRequestError({ response: { status: 500, statusText: "Internal Server Error", data: { detail: "Unexpected server error (KeyError); the details are in the server log" } } });
  expect(d).toEqual({ kind: "http", status: 500, message: "HTTP 500 Internal Server Error — Unexpected server error (KeyError); the details are in the server log" });
});

test("404 and 409 show their own text", () => {
  expect(describeRequestError({ response: { status: 404, data: { detail: "Run not found" } } }).message).toBe("HTTP 404 — Run not found");
  expect(describeRequestError({ response: { status: 409, data: { detail: "Run not computed yet" } } }).message).toBe("HTTP 409 — Run not computed yet");
});

test("a validation error list is flattened", () => {
  const d = describeRequestError({ response: { status: 422, data: { detail: [{ msg: "field required" }, { msg: "bad value" }] } } });
  expect(d.message).toBe("HTTP 422 — field required; bad value");
});

test("a proxy's HTML error page becomes plain text", () => {
  const d = describeRequestError({ response: { status: 504, statusText: "Gateway Timeout", data: "<html><body><h1>504 Gateway Time-out</h1></body></html>" } });
  expect(d.message).toBe("HTTP 504 Gateway Timeout — 504 Gateway Time-out");
});

test("a timeout says no response arrived and after how long", () => {
  const d = describeRequestError({ code: "ECONNABORTED", message: "timeout of 150000ms exceeded" }, { timeoutMs: 150000 });
  expect(d.kind).toBe("timeout");
  expect(d.message).toContain("after 150 seconds");
});

test("no response at all is reported as such", () => {
  const d = describeRequestError({ message: "Network Error" });
  expect(d.kind).toBe("network");
  expect(d.message).toContain("No response from the server (Network Error)");
});

test("a key can never appear in the description, even if the server echoes it", () => {
  const d = describeRequestError({ response: { status: 401, data: { detail: `invalid x-api-key: ${KEY}` } }, config: { headers: { "x-api-key": KEY } } });
  expect(d.message).not.toContain(KEY);
  expect(d.message).not.toContain("ABCDEFGHIJKLMNOP");
  expect(JSON.stringify(d)).not.toContain(KEY);
});

test("the request config is never read into the message", () => {
  const d = describeRequestError({ message: "Network Error", config: { headers: { Authorization: `Bearer ${KEY}` } } });
  expect(JSON.stringify(d)).not.toContain(KEY);
});

test("redactSecrets masks keys, bearer tokens and named credentials", () => {
  expect(redactSecrets(`token ${KEY}`)).toBe("token [redacted]");
  expect(redactSecrets("Authorization: Bearer abcdefgh12345678")).not.toContain("abcdefgh12345678");
  expect(redactSecrets('{"x-api-key": "shhhhhhhhhh"}')).not.toContain("shhhhhhhhhh");
});

test("logging writes the description only", () => {
  const spy = jest.spyOn(console, "error").mockImplementation(() => {});
  logRequestFailure("generate narrative", { message: "HTTP 500 — boom" });
  expect(spy).toHaveBeenCalledWith("[generate narrative] HTTP 500 — boom");
  spy.mockRestore();
});
