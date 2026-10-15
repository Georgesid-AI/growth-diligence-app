import { api, uploadChatFile, UPLOAD_TIMEOUT_MS, ownerPrompts, downloadExport, setAccessToken, getAccessToken } from "./api";

test("a chat upload gives up after 120 s", async () => {
  let seen;
  api.defaults.adapter = async (config) => { seen = config; return { data: {}, status: 200, statusText: "OK", headers: {}, config }; };
  await uploadChatFile("a1", new File(["x"], "rev.csv"));
  expect(UPLOAD_TIMEOUT_MS).toBe(120000);
  expect(seen.timeout).toBe(120000);
});

function capture(response = {}) {
  const seen = [];
  api.defaults.adapter = async (config) => {
    seen.push(config);
    return { data: {}, status: 200, statusText: "OK", headers: {}, config, ...response };
  };
  return seen;
}

describe("the access token", () => {
  afterEach(() => window.localStorage.clear());

  test("every request carries the kept token as a bearer header, and none without one", async () => {
    const seen = capture();
    await api.get("/audits");
    expect(seen[0].headers.Authorization).toBeUndefined();
    expect(setAccessToken("tester-token")).toBe(true);
    expect(getAccessToken()).toBe("tester-token");
    await api.get("/audits");
    expect(seen[1].headers.Authorization).toBe("Bearer tester-token");
  });

  test("an owner call sends the owner token it was given, never the kept tester token", async () => {
    setAccessToken("tester-token");
    const seen = capture();
    await ownerPrompts("owner-token");
    expect(seen[0].headers.Authorization).toBe("Bearer owner-token");
    expect(seen[0].url).toBe("/admin/prompts");
    expect(window.localStorage.getItem("access_token")).toBe("tester-token");
    expect(JSON.stringify({ ...window.localStorage })).not.toContain("owner-token");
  });

  test("a file is fetched with the header and saved from memory, not opened as a link", async () => {
    setAccessToken("tester-token");
    window.URL.createObjectURL = jest.fn(() => "blob:x");
    window.URL.revokeObjectURL = jest.fn();
    const clicked = [];
    const click = jest.spyOn(window.HTMLAnchorElement.prototype, "click").mockImplementation(function () { clicked.push(this.download); });
    const seen = capture({ data: new Blob(["x"]), headers: { "content-disposition": 'attachment; filename="Co_growth_diligence.xlsx"' } });
    await downloadExport("a1");
    expect(seen[0].url).toBe("/audits/a1/export");
    expect(seen[0].responseType).toBe("blob");
    expect(seen[0].headers.Authorization).toBe("Bearer tester-token");
    expect(clicked).toEqual(["Co_growth_diligence.xlsx"]);
    click.mockRestore();
  });
});
