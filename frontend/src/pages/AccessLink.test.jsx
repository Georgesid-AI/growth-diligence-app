// docs/specs/access-links.md (plan section 6): the tester page, and the page for a bare or rejected link.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

const mockToken = "tester-token-123";
jest.mock("react-router-dom", () => ({ useParams: () => ({ token: mockToken }), useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("@/lib/api", () => ({ setToken: (t) => global.localStorage.setItem("access_token", t), clearToken: () => global.localStorage.removeItem("access_token"), listAudits: jest.fn() }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mount = async (el) => {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(el); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
};

test("the tester page states that the link is the login, and keeps the token for the API", async () => {
  require("@/lib/api").listAudits.mockResolvedValue([]);
  const AccessLink = require("./AccessLink").default;
  const { host, done } = await mount(<AccessLink />);
  try {
    expect(host.textContent).toContain("Your link is your login. Anyone with the link can open your audits.");
    expect(host.textContent).toContain("Welcome");
    expect(window.localStorage.getItem("access_token")).toBe("tester-token-123");
  } finally { await done(); }
});

test("a token the API rejects with 401 shows only the full-link page", async () => {
  require("@/lib/api").listAudits.mockRejectedValue({ response: { status: 401 } });
  const AccessLink = require("./AccessLink").default;
  const { host, done } = await mount(<AccessLink />);
  try {
    expect(host.querySelector("h1").textContent).toBe("Use your full access link");
    expect(host.textContent).toContain("Open the complete link you received by email or message; this page cannot be reached without it.");
    expect(host.textContent).not.toContain("Welcome");
    expect(window.localStorage.getItem("access_token")).toBeNull();
    expect(host.querySelector("input, form, a, button")).toBeNull();
  } finally { await done(); }
});

test("the bare /t/ path shows only the full-link page", async () => {
  const { FullLinkNeeded } = require("./AccessLink");
  const { host, done } = await mount(<FullLinkNeeded />);
  try {
    expect(host.querySelector("h1").textContent).toBe("Use your full access link");
    expect(host.textContent).toContain("this page cannot be reached without it.");
    expect(host.querySelector("input, form, a, button")).toBeNull();
  } finally { await done(); }
});
