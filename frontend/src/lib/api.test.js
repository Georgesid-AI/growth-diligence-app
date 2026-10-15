import { api, uploadChatFile, UPLOAD_TIMEOUT_MS } from "./api";

test("a chat upload gives up after 120 s", async () => {
  let seen;
  api.defaults.adapter = async (config) => { seen = config; return { data: {}, status: 200, statusText: "OK", headers: {}, config }; };
  await uploadChatFile("a1", new File(["x"], "rev.csv"));
  expect(UPLOAD_TIMEOUT_MS).toBe(120000);
  expect(seen.timeout).toBe(120000);
});

test("every request carries the tester's token as a bearer header, and none is sent without one", async () => {
  const { setToken, TOKEN_KEY } = require("./api");
  let seen;
  api.defaults.adapter = async (config) => { seen = config; return { data: {}, status: 200, statusText: "OK", headers: {}, config }; };
  window.localStorage.removeItem(TOKEN_KEY);
  await api.get("/audits");
  expect(seen.headers.Authorization).toBeUndefined();
  setToken("tester-token-123");
  await api.get("/audits");
  expect(seen.headers.Authorization).toBe("Bearer tester-token-123");
  window.localStorage.removeItem(TOKEN_KEY);
});

test("an owner call sends the owner token it was given, never the kept tester token, and the owner token is never kept", async () => {
  const { setToken, TOKEN_KEY, ownerPrompts } = require("./api");
  setToken("tester-token-123");
  let seen;
  api.defaults.adapter = async (config) => { seen = config; return { data: {}, status: 200, statusText: "OK", headers: {}, config }; };
  await ownerPrompts("owner-token");
  expect(seen.headers.Authorization).toBe("Bearer owner-token");
  expect(seen.url).toBe("/admin/prompts");
  expect(window.localStorage.getItem(TOKEN_KEY)).toBe("tester-token-123");
  expect(JSON.stringify({ ...window.localStorage })).not.toContain("owner-token");
  window.localStorage.removeItem(TOKEN_KEY);
});
