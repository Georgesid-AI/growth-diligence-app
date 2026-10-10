import { api, uploadChatFile, UPLOAD_TIMEOUT_MS } from "./api";

test("a chat upload gives up after 120 s", async () => {
  let seen;
  api.defaults.adapter = async (config) => { seen = config; return { data: {}, status: 200, statusText: "OK", headers: {}, config }; };
  await uploadChatFile("a1", new File(["x"], "rev.csv"));
  expect(UPLOAD_TIMEOUT_MS).toBe(120000);
  expect(seen.timeout).toBe(120000);
});
