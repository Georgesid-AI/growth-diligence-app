import React, { act } from "react";
import { createRoot } from "react-dom/client";

import { ConsentBlock, AssumptionsSetup, ParkedBlocks, PATH_TO_PLAN_TEXT, QUARTERLY_TEXT } from "./AuditSetup";
import * as api from "@/lib/api";
import { CONSENT_LABEL, VERIFIED_LINE } from "@/lib/auditForm";

jest.mock("@/lib/api", () => ({ getAudit: jest.fn(), putIcInputs: jest.fn(), updateAudit: jest.fn() }));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const AUDIT = { id: "a1", company_name: "TestCo", reporting_currency: "EUR", target_arr: 0, fiscal_year_end: 12, structure_reading_consent: true };
const SERIES = { revenue: { months: { first: "2017-07", last: "2019-06" } } };
let root, host;

async function mount(node) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(node); });
}
const setup = (audit, asOf = "") => mount(<AssumptionsSetup audit={audit} setAudit={jest.fn()} asOf={asOf} setAsOf={jest.fn()} />);
const click = (el) => act(async () => { el.click(); });
beforeEach(() => {
  jest.resetAllMocks();
  api.updateAudit.mockResolvedValue({});
  api.getAudit.mockResolvedValue(AUDIT);
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

// docs/specs/chat-upload.md section 23
describe("the consent block", () => {
  const ZDR_ON = "Deck pages are processed by Anthropic under a zero-data-retention arrangement. Nothing is retained after the reply and nothing is used for training.";
  const ZDR_OFF = "Deck pages are sent to Anthropic's API for reading and are not used for training.";
  const block2 = (zdr) => "The model reads every column header and a masked sample to propose the mapping. When the rules cannot tell what a file holds, the AI also sees its sheet names and the title rows above each table. "
    + "In a revenue file the AI also sees the row labels when they are metric names such as revenue, ARR or customers; where the rows may be customers it sees Row 1, Row 2 instead, never a name. "
    + "The AI reads every page of uploaded decks, as printed, to find plan figures: the text of each page that carries a figure and one image of the whole page, with no redaction. "
    + `${zdr ? ZDR_ON : ZDR_OFF} Uploaded files are stored for this audit and deleted with it.`;

  test("block 1 is the two given paragraphs, word for word, with the tick under them", async () => {
    await mount(<ConsentBlock audit={AUDIT} setAudit={jest.fn()} />);
    expect(q("setup-consent-label").textContent).toBe(CONSENT_LABEL);
    expect(CONSENT_LABEL).toBe("Use AI to read deck tables, charts and the text of pages that carry a figure, and to suggest column matches. Names, contact details and customer names are masked in spreadsheet data before it is sent; deck pages are sent as printed, as text and as an image, with no redaction. Untick if the client requires code-based extraction only; this may find fewer figures. Narratives use AI on computed results either way.");
    expect(q("setup-verified-line").textContent).toBe("Every extracted number is checked by code against its source cell. Numbers that don't match are marked unverified for review.");
    expect(q("setup-verified-line").textContent).toBe(VERIFIED_LINE);
    expect(q("setup-consent-checkbox").checked).toBe(true);
    const follows = (a, b) => q(a).compareDocumentPosition(q(b)) & Node.DOCUMENT_POSITION_FOLLOWING;
    expect(follows("setup-verified-line", "setup-consent-checkbox")).toBeTruthy();
    expect(follows("setup-consent-checkbox", "chat-explainer")).toBeTruthy();
  });

  test.each([[true, "on"], [false, "off"]])("block 2 is word for word with PROVIDER_ZDR %s", async (zdr) => {
    await mount(<ConsentBlock audit={{ ...AUDIT, provider_zdr: zdr }} setAudit={jest.fn()} />);
    expect(q("chat-explainer").textContent).toBe(block2(zdr));
  });

  test("a flag that is missing reads as off", async () => {
    await mount(<ConsentBlock audit={AUDIT} setAudit={jest.fn()} />);
    expect(q("chat-explainer").textContent).toBe(block2(false));
    expect(q("chat-explainer").textContent).not.toContain("zero-data-retention");
  });

  test("the tick shows the audit's state: unticked, and an audit with no consent field, read as off", async () => {
    await mount(<ConsentBlock audit={{ ...AUDIT, structure_reading_consent: false }} setAudit={jest.fn()} />);
    expect(q("setup-consent-checkbox").checked).toBe(false);
    expect(q("chat-explainer").textContent).toBe("Mapping is done by rules only: AI-assisted reading is off for this audit. You map the columns the rules cannot decide.");
    await act(async () => { root.unmount(); }); host.remove();
    const { structure_reading_consent: _gone, ...old } = AUDIT;
    await mount(<ConsentBlock audit={old} setAudit={jest.fn()} />);
    expect(q("setup-consent-checkbox").checked).toBe(false);
  });

  test("ticking and unticking save the consent like the other set-up fields", async () => {
    await mount(<ConsentBlock audit={{ ...AUDIT, structure_reading_consent: false }} setAudit={jest.fn()} />);
    await click(q("setup-consent-checkbox"));
    expect(api.updateAudit).toHaveBeenLastCalledWith("a1", { structure_reading_consent: true });
    await act(async () => { root.unmount(); }); host.remove();
    await mount(<ConsentBlock audit={AUDIT} setAudit={jest.fn()} />);
    await click(q("setup-consent-checkbox"));
    expect(api.updateAudit).toHaveBeenLastCalledWith("a1", { structure_reading_consent: false });
  });
});

// docs/specs/chat-upload.md section 30, restructure of 2026-10-28
describe("the assumptions strip: the as-of month", () => {
  test("a detected month reads 'As-of month: Dec 2021 (detected from <file>)' with a Change link", async () => {
    await setup({ ...AUDIT, as_of_month: "2021-12-31", as_of_by: "detected", as_of_file: "pl.xlsx" }, "2021-12-31");
    expect(q("setup-as_of").textContent).toBe("As-of month: Dec 2021 (detected from pl.xlsx) Change");
    expect(q("asof-month-input")).toBeNull();
  });

  test("Change opens the typed month-and-year input with its help line; a typed month saves and reads '(set by analyst)'", async () => {
    const audit = { ...AUDIT, as_of_month: "2021-12-31", as_of_by: "detected", as_of_file: "pl.xlsx" };
    await setup(audit, "2021-12-31");
    await click(q("setup-as_of-change"));
    expect(q("asof-month-input").value).toBe("Dec 2021");
    expect(q("setup-help-as_of_month").textContent).toBe("Last month of actual figures. Months after it are read as plan.");
    const input = q("asof-month-input");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "Jun 2021");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { input.focus(); input.blur(); });
    expect(api.updateAudit).toHaveBeenLastCalledWith("a1", { as_of_month: "2021-06-30" });
    await act(async () => { root.unmount(); }); host.remove();
    await setup({ ...audit, as_of_month: "2021-06-30", as_of_by: "analyst" }, "2021-06-30");
    expect(q("setup-as_of").textContent).toBe("As-of month: Jun 2021 (set by analyst) Change");
  });

  test("no completeness tick text anywhere on the strip or the cards", async () => {
    await setup({ ...AUDIT, datasets: SERIES, as_of_month: "2019-06-30", as_of_by: "analyst" }, "2019-06-30");
    await click(q("setup-as_of-change"));
    expect(document.body.textContent).not.toMatch(/last month is\s+complete/i);
  });

  test("an as-of month later than the revenue file's last month gets a warning line", async () => {
    await setup({ ...AUDIT, datasets: SERIES, as_of_month: "2026-06-30" }, "2026-06-30");
    expect(q("setup-warning-as_of_month").textContent).toBe("The as-of month, June 2026, is later than the last month of the revenue file, "
      + "June 2019. The figures stop at June 2019; the months after it hold no revenue.");
  });

  test.each([["the last month itself", "2019-06-30"], ["an earlier month", "2019-03-31"], ["none set", ""]])("no warning for %s", async (_name, asOf) => {
    await setup({ ...AUDIT, datasets: SERIES, as_of_month: asOf || null }, asOf);
    expect(q("setup-warning-as_of_month")).toBeNull();
  });
});

describe("the assumptions strip: fiscal year-end", () => {
  test("hidden in December, shown when not December", async () => {
    await setup(AUDIT);
    expect(q("setup-fy")).toBeNull();
    await act(async () => { root.unmount(); }); host.remove();
    await setup({ ...AUDIT, fiscal_year_end: 3 });
    expect(q("setup-fy").textContent).toBe("Fiscal year-end: March Change");
  });

  test("a December audit can still set it; once opened it stays shown", async () => {
    await setup(AUDIT);
    await click(q("setup-fy-open"));
    expect(q("fiscal-year-end-select")).not.toBeNull();
    expect(q("setup-fy").textContent).toContain("Fiscal year-end: December");
  });
});

describe("the parked blocks", () => {
  const parked = (audit) => mount(<ParkedBlocks audit={audit} setAudit={jest.fn()} asOf="" />);

  test("two grey cards with their title and sentence, word for word", async () => {
    await parked(AUDIT);
    expect(q("parked-path-to-plan").querySelector("h3").textContent).toBe("Path to plan (needs more data)");
    expect(q("parked-path-to-plan-text").textContent).toBe("Calculates the growth rate the plan needs to reach the target. Needs a monthly revenue series (MRR or ARR) up to the as-of month. The expansion-adjusted version also needs revenue by customer and month.");
    expect(PATH_TO_PLAN_TEXT).toBe(q("parked-path-to-plan-text").textContent);
    expect(q("parked-quarterly").querySelector("h3").textContent).toBe("Quarterly review (parked)");
    expect(q("parked-quarterly-text").textContent).toBe("Used to date monitoring gates. Gates are parked; this date is stored and not shown elsewhere.");
    expect(QUARTERLY_TEXT).toBe(q("parked-quarterly-text").textContent);
  });

  test("Target ARR and Target date are disabled without a monthly series, active with one, and keep their stored values", async () => {
    const stored = { ...AUDIT, target_arr: 40000000, target_date: "2028-12-31" };
    await parked(stored);
    expect(q("setup-target-arr-input").disabled).toBe(true);
    expect(q("setup-target-date-input").disabled).toBe(true);
    expect(q("setup-target-arr-input").value).toBe("40,000,000");
    expect(q("setup-target-date-input").value).toBe("31 Dec 2028");
    await act(async () => { root.unmount(); }); host.remove();
    await parked({ ...stored, datasets: SERIES });
    expect(q("setup-target-arr-input").disabled).toBe(false);
    expect(q("setup-target-date-input").disabled).toBe(false);
  });

  test("the review date is disabled and shows the stored or default date", async () => {
    await parked({ ...AUDIT, datasets: SERIES, ic_inputs: { first_quarterly_review: "2026-01-09" } });
    expect(q("setup-review-date-input").disabled).toBe(true);
    expect(q("setup-review-date-input").value).toBe("9 Jan 2026");
  });
});
