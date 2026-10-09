import {
  DOWNLOAD_LABEL, EDITABLE_FIELDS, GATE_BUDGET_MAX, NOT_IN_DATA, NO_METRIC, READ_ONLY_FIELDS, REGISTER_COLUMNS, REGISTER_HEADING, WHOLE_COMPANY,
  claimFigure, claimText, claimUnit, csvUrl, evidenceLines, gateContext, needsMetricName, overlapsText, valueAtStakeText, dataSegments, gapText, gateEdit, metricOptions, observedText, readingText, registerRows, segmentOptions,
} from "./claimRegister";

const ARR_ROW = {
  claim_id: "c01", claim_type: "revenue", claimed_value: 200000, claimed_high: null, unit: null, currency: "EUR",
  period: "Feb 2024", period_note: null, segment: "Whole company", segment_set_by: "python", metric: "ARR", metric_set_by: "python",
  direction: "higher", observed_value: 202125.48, observed_at: "2024-02", observed_source: { file: "revenue.csv", sheet: "CSV", rows: "rows 2–71", rule: "ARR" },
  gap: -2125.48, gap_normalised: -0.010627, gap_kind: "beat", gloss: "€2,125 higher (beat)", evidence_label: "Verified",
  reason: "within ±5% of the claim", tolerance: "±5%", rank: 11, gate_sentence: null,
  gate_threshold: null, gate_budget_decision: null, gate_date: null, gate_saved: false, deck_reading: "parser", page_ref: "slide 4", shortfall: null, overlaps_with: [],
  evidence_analysis: "Monthly MRR by Segment", evidence_source_key: "mrr_series.data.total", gate_metric_name: null, gate_direction: null,
  key_gate: false, gate_needed: false,
};
const WIN_ROW = { ...ARR_ROW, claim_id: "c03", claim_type: "sales", claimed_value: 41, unit: "%", currency: null, metric: "Win rate", gap: 1.0,
  gap_normalised: 0.02439, gap_kind: "miss", observed_value: 40.0, period: null, period_note: "no period stated" };

describe("the Claim register section of the Dashboard (spec section 8)", () => {
  test("its title, its download button and its columns are those of the spec", () => {
    expect(REGISTER_HEADING).toBe("Claim register");
    expect(DOWNLOAD_LABEL).toBe("Download baseline (CSV)");
    expect(REGISTER_COLUMNS).toEqual(["#", "Claim", "Period", "Segment", "Page", "Read from deck", "Observed", "Gap", "Gloss", "Value at stake",
      "Overlaps with", "Evidence", "Gate"]);
  });

  test("the segment, the metric and the gate are editable; everything else is read-only", () => {
    expect(EDITABLE_FIELDS).toEqual(["segment", "metric", "gate_threshold", "gate_budget_decision", "gate_date", "gate_metric_name",
      "gate_direction", "key_gate"]);
    expect(READ_ONLY_FIELDS).toEqual(expect.arrayContaining(["rank", "claim", "period", "page", "deck_reading", "observed", "gap", "gloss",
      "value_at_stake", "overlaps_with", "evidence"]));
    expect(READ_ONLY_FIELDS.some((f) => EDITABLE_FIELDS.includes(f))).toBe(false);
  });

  test("the CSV button points at the audit's claims.csv", () => {
    expect(csvUrl("http://api/api", "abc")).toBe("http://api/api/audits/abc/claims.csv");
  });

  test("rows keep the order the server sent: rank order", () => {
    expect(registerRows({ register: [{ rank: 1 }, { rank: 2 }] }).map((r) => r.rank)).toEqual([1, 2]);
    expect(registerRows({}).length).toBe(0);
    expect(registerRows(null).length).toBe(0);
  });
});

describe("what a row shows", () => {
  test("the claim: its type and its figure in its own unit", () => {
    expect(claimText(ARR_ROW)).toBe("Revenue · 200,000 EUR");
    expect(claimText({ ...ARR_ROW, claimed_high: 210000, claimed_value: 190000 })).toBe("Revenue · 190,000–210,000 EUR");
    expect(claimText(WIN_ROW)).toBe("Sales · 41%");
    expect(claimText({ ...ARR_ROW, claim_type: "customers", claimed_value: 4, unit: "customers", currency: null })).toBe("Customers · 4 customers");
    expect(claimText({ ...ARR_ROW, claim_type: "sales", claimed_value: 8, unit: "weeks", currency: null })).toBe("Sales · 8 weeks");
  });

  test("the observed value with its date, or a dash with the reason it is missing", () => {
    expect(observedText(ARR_ROW, "EUR")).toEqual({ value: "202,125 EUR", at: "2024-02" });
    expect(observedText(WIN_ROW, "EUR")).toEqual({ value: "40%", at: "2024-02" });
    expect(observedText({ ...ARR_ROW, metric: "Median sales cycle", observed_value: 58.5 }, "EUR").value).toBe("58.5 days");
    expect(observedText({ ...ARR_ROW, metric: "CAC payback", observed_value: 14 }, "EUR").value).toBe("14.0 months");
    expect(observedText({ ...ARR_ROW, metric: "Customer count", observed_value: 5 }, "EUR").value).toBe("5");
    expect(observedText({ ...ARR_ROW, observed_value: null, observed_at: null }, "EUR")).toEqual({ value: "—", at: null });
  });

  test("the gap in native units and as a share of the claim, Verified rows included", () => {
    expect(gapText(ARR_ROW, "EUR")).toBe("beat 2,125 EUR · 1.1%");
    expect(gapText(WIN_ROW, "EUR")).toBe("1.0 pp · 2.4%");
    expect(gapText({ ...ARR_ROW, gap: 41857.32, gap_normalised: 0.174405, gap_kind: "miss" }, "EUR")).toBe("41,857 EUR · 17.4%");
    expect(gapText({ ...ARR_ROW, gap: 4797874.52, gap_normalised: 0.959575, gap_kind: "to go" }, "EUR")).toBe("to go 4,797,875 EUR · 96.0%");
    expect(gapText({ ...ARR_ROW, gap: 0, gap_normalised: 0, gap_kind: null }, "EUR")).toBe("0 EUR · 0.0%");
    expect(gapText({ ...ARR_ROW, gap: null, gap_normalised: null, gap_kind: null }, "EUR")).toBe("—");
    expect(gapText({ ...ARR_ROW, metric: "Median sales cycle", gap: 13.5, gap_normalised: 0.3, gap_kind: "miss" }, "EUR")).toBe("13.5 days · 30.0%");
    expect(gapText({ ...ARR_ROW, metric: "Customer count", gap: -1, gap_normalised: -0.25, gap_kind: "beat" }, "EUR")).toBe("beat 1 · 25.0%");
    expect(gapText({ ...ARR_ROW, metric: "CAC payback", gap: 2, gap_normalised: 0.1667, gap_kind: "miss" }, "EUR")).toBe("2.0 months · 16.7%");
  });

  test("the claimed figure alone, and the gate cell: claimed and observed beside an empty field, no proposed threshold", () => {
    expect(claimFigure(ARR_ROW)).toBe("200,000 EUR");
    expect(claimFigure({ ...ARR_ROW, unit: "years", currency: null, claimed_value: 1 })).toBe("1 years");
    expect(gateContext(ARR_ROW, "EUR")).toBe("Claimed 200,000 EUR (Feb 2024) · Observed 202,125 EUR (2024-02)");
    expect(gateContext(WIN_ROW, "EUR")).toBe("Claimed 41% (no period stated) · Observed 40% (2024-02)");
    expect(gateContext({ ...ARR_ROW, observed_value: null }, "EUR")).toBe("Claimed 200,000 EUR (Feb 2024)");
  });

  test("what the deck reading says", () => {
    expect(readingText("parser")).toBe("Read by the parser");
    expect(readingText("Verified")).toBe("Verified");
    expect(readingText("AI suggestion, not verified")).toBe("AI suggestion, not verified");
    expect(readingText("edited")).toBe("Edited by the analyst");
  });
});

describe("what the analyst may set", () => {
  test("a metric in the claim's unit, or none", () => {
    expect(claimUnit(ARR_ROW)).toBe("currency");
    expect(metricOptions(ARR_ROW)).toEqual(["Revenue", "ARR", "MRR", "New MRR", "ACV", "Transaction volume", NO_METRIC]);
    expect(metricOptions(WIN_ROW)).toEqual(["NRR (12-month)", "Gross revenue churn", "Win rate", "Gross margin", NO_METRIC]);
    expect(metricOptions({ ...ARR_ROW, unit: "customers", currency: null })).toEqual(["Customer count", NO_METRIC]);
    expect(metricOptions({ ...ARR_ROW, unit: "weeks", currency: null })).toEqual(["Median sales cycle", "CAC payback", NO_METRIC]);
    expect(metricOptions({ ...ARR_ROW, unit: "years", currency: null })).toEqual(["Median sales cycle", "CAC payback", NO_METRIC]);
    expect(metricOptions({ ...ARR_ROW, unit: "hours", currency: null })).toEqual([NO_METRIC]);
    expect(metricOptions({ ...ARR_ROW, unit: null, currency: null })).toEqual(["Customer count", NO_METRIC]);
  });

  test("a segment of the data, the whole company or not in the data", () => {
    const results = { mrr_series: { segments: ["Enterprise", "SMB", "Unsegmented"] }, sales_cycle: { by_segment: { Enterprise: {}, "Mid-Market": {} } },
      acv_path: { by_segment: { SMB: {} } }, nrr: { by_segment: { Enterprise: {} } } };
    expect(dataSegments(results)).toEqual(["Enterprise", "Mid-Market", "SMB"]);
    expect(segmentOptions(results)).toEqual([WHOLE_COMPANY, "Enterprise", "Mid-Market", "SMB", NOT_IN_DATA]);
    expect(segmentOptions(results)).toEqual([WHOLE_COMPANY, "Enterprise", "Mid-Market", "SMB", NOT_IN_DATA]);
    expect(dataSegments(null)).toEqual([]);
  });

  test("a gate edit sends only the fields that changed, blank as null, the threshold as a number", () => {
    const row = { ...ARR_ROW, gate_threshold: 195000, gate_budget_decision: "the hiring plan", gate_date: "2024-03-31" };
    expect(gateEdit(row, { threshold: "195000", budget: "the hiring plan", date: "2024-03-31" })).toEqual({});
    expect(gateEdit(row, { threshold: "180000.5", budget: "the hiring plan", date: "2024-03-31" })).toEqual({ gate_threshold: 180000.5 });
    expect(gateEdit(row, { threshold: "", budget: "  ", date: "" })).toEqual({ gate_threshold: null, gate_budget_decision: null, gate_date: null });
    expect(gateEdit(ARR_ROW, { threshold: "1", budget: "Series B", date: "2024-06-30" }))
      .toEqual({ gate_threshold: 1, gate_budget_decision: "Series B", gate_date: "2024-06-30" });
    expect(gateEdit(ARR_ROW, { threshold: "", budget: "", date: "" })).toEqual({});      // the date starts empty: nothing is proposed
  });

  test("a gate date outside 2000 to 2100 or not real is not sent", () => {
    for (const bad of ["0001-01-01", "1999-12-31", "2101-01-01", "2026-02-30"]) {
      expect(() => gateEdit(ARR_ROW, { threshold: "", budget: "", date: bad })).toThrow(/gate date/i);
    }
  });

  test("a claim in another currency shows both figures; a direction with no figure says so", () => {
    const gbp = { ...ARR_ROW, currency: "GBP", claimed_value: 150000, claimed_converted: 171000, fx_rate: 1.14, fx_date: "2026-06-30" };
    expect(claimFigure(gbp, "EUR")).toBe("150,000 GBP (171,000 EUR at 1.14, 30 Jun 2026)");
    expect(claimText(gbp, "EUR")).toBe("Revenue · 150,000 GBP (171,000 EUR at 1.14, 30 Jun 2026)");
    expect(claimFigure({ ...gbp, claimed_high: 160000, claimed_converted_high: 182400 }, "EUR"))
      .toBe("150,000–160,000 GBP (171,000–182,400 EUR at 1.14, 30 Jun 2026)");
    expect(claimFigure({ ...gbp, claimed_converted: null, fx_rate: null, fx_date: "2026-06-30" }, "EUR")).toBe("150,000 GBP");
    expect(claimFigure({ ...ARR_ROW, claimed_value: null, currency: null, claim_direction: "negative" })).toBe("negative (no figure)");
    expect(gateContext(gbp, "EUR")).toContain("Claimed 150,000 GBP (171,000 EUR at 1.14, 30 Jun 2026)");
  });

  test("a threshold that is not a number is not sent, and a budget decision stops at 200 characters", () => {
    expect(() => gateEdit(ARR_ROW, { threshold: "lots", budget: "", date: "" })).toThrow(/number/);
    expect(GATE_BUDGET_MAX).toBe(200);
    expect(() => gateEdit(ARR_ROW, { threshold: "", budget: "x".repeat(201), date: "" })).toThrow(/200/);
    expect(gateEdit(ARR_ROW, { threshold: "", budget: "x".repeat(200), date: "" })).toEqual({ gate_budget_decision: "x".repeat(200) });
  });
});

describe("the columns and the gate of verdict-and-memo.md sections 2 and 3", () => {
  test("W1: value at stake reads not yet computed, with the shortfall when the claim missed", () => {
    expect(valueAtStakeText(ARR_ROW)).toBe("not yet computed");
    expect(valueAtStakeText({ ...ARR_ROW, shortfall: 0.183 })).toBe("not yet computed · shortfall 18.3%");
  });

  test("W2: overlaps show the ranks of the rows, a dash when none", () => {
    const rows = [{ claim_id: "a", rank: 7 }, { claim_id: "b", rank: 3 }, { claim_id: "c", rank: 9 }];
    expect(overlapsText({ overlaps_with: ["a", "b"] }, rows)).toBe("#3, #7");
    expect(overlapsText({ overlaps_with: [] }, rows)).toBe("—");
    expect(overlapsText({}, rows)).toBe("—");
  });

  test("W3: the label and reason, then the analysis and source key with the month it was read at", () => {
    expect(evidenceLines(ARR_ROW)).toEqual({ first: "Verified · within ±5% of the claim", second: "Monthly MRR by Segment · mrr_series.data.total (2024-02)" });
    expect(evidenceLines({ ...ARR_ROW, evidence_analysis: null }).second).toBeNull();
  });

  test("a row with no metric of the app also takes the analyst's metric and its direction", () => {
    const none = { ...ARR_ROW, metric: null, reason: "no metric", observed_value: null, gate_metric_name: "Pipeline cover", gate_direction: "at least" };
    expect(needsMetricName(none)).toBe(true);
    expect(needsMetricName({ ...none, reason: "metric does not fit the claim's unit" })).toBe(true);
    expect(needsMetricName(ARR_ROW)).toBe(false);
    expect(gateEdit(none, { threshold: "5", budget: "the plan", date: "2024-06-30", metricName: "Pipeline cover", direction: "at most" }))
      .toEqual({ gate_threshold: 5, gate_budget_decision: "the plan", gate_date: "2024-06-30", gate_direction: "at most" });
    expect(() => gateEdit(none, { threshold: "", budget: "", date: "", metricName: "x".repeat(101), direction: "" })).toThrow("at most 100");
    expect(gateEdit(ARR_ROW, { threshold: "", budget: "", date: "", metricName: "ignored", direction: "at most" })).toEqual({});
  });
});
