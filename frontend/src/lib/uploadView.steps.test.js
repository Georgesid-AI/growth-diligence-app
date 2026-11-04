import { steps } from "./uploadView";

const done = (over = {}) => ({ file: "a.xlsx", read_state: "done", read_elapsed: 40, ...over });

test("the two steps: Reading and checking files, Calculating results; no Checking figures", () => {
  const rows = steps([done()], [], { status: "idle" }, 0);
  expect(rows.map((r) => r.label)).toEqual(["Reading and checking files", "Calculating results"]);
});

test("reading is done as 'm:ss · n files processed', timed from the first upload to the last file processed", () => {
  const rows = steps([done(), done({ file_hash: "b" })], [{ deck_id: "d", ai_status: "read", read_elapsed: 5 }], { status: "idle" }, 0, { start: 1000, end: 124000 });
  expect(rows[0].second).toBe("2:03 · 3 files processed");
});

test("calculating runs as Elapsed m:ss and is done as 'Done m:ss'", () => {
  expect(steps([done()], [], { status: "running", seconds: 3 }, 0)[1].second).toBe("Elapsed 0:03");
  expect(steps([done()], [], { status: "done", seconds: 4 }, 0)[1].second).toBe("Done 0:04");
});

// ---- reading-step failure visibility ----
import { deckLine, readiness, sheetLine, sharedReadError } from "./uploadView";

const FAILED = "Failed – no file could be read";
const CREDIT = "Anthropic API: insufficient credit – add credit and re-run";
const deckOf = (over = {}) => ({ deck_id: "d", file: "deck.pdf", ai_status: "read", pages_read: 3, pages_rejected: 0, read_elapsed: 5, ...over });

test("a spreadsheet that mapped no row is not processed: with no other file the step fails in red and Run audit is held", () => {
  const sheet = done({ rows_mapped: 0 });
  expect(steps([sheet], [], { status: "idle" }, 0)[0]).toMatchObject({ tone: "bad", second: FAILED });
  expect(readiness([sheet], [])).toEqual({ held: true, text: FAILED });
});

test("a failed spreadsheet read is not processed either", () => {
  const sheet = done({ read_state: "failed", rows_mapped: 0 });
  expect(steps([sheet], [], { status: "idle" }, 0)[0]).toMatchObject({ tone: "bad", second: FAILED });
});

test("a deck with no accepted page is not processed: every page rejected fails the step", () => {
  const rejected = deckOf({ ai_status: "not_read", pages_read: 0, pages_rejected: 3 });
  expect(steps([], [rejected], { status: "idle" }, 0)[0]).toMatchObject({ tone: "bad", second: FAILED });
  expect(readiness([], [rejected])).toEqual({ held: true, text: FAILED });
});

test("one processed file keeps the step done and Run audit on; the count is of the files processed", () => {
  const rows = steps([done({ rows_mapped: 0 }), done({ file_hash: "b", rows_mapped: 12 })], [], { status: "idle" }, 0);
  expect(rows[0].tone).toBe("done");
  expect(rows[0].second).toBe("0:40 · 1 file processed");
  expect(readiness([done({ rows_mapped: 0 }), done({ file_hash: "b", rows_mapped: 12 })], [])).toEqual({ held: false, text: "Ready: 1 data file and 0 decks processed." });
});

test("a file with no rows_mapped on record (read before this change) still counts as processed when its read is done", () => {
  expect(steps([done()], [], { status: "idle" }, 0)[0].tone).toBe("done");
});

test("the same provider error on every file is shown once at the top of the step, and the files' own 'could not be read' lines give way to it", () => {
  const sheet = done({ read_state: "failed", rows_mapped: 0, read_error: CREDIT });
  const deck = deckOf({ ai_status: "not_read", pages_read: 0, read_error: CREDIT });
  const row = steps([sheet], [deck], { status: "idle" }, 0)[0];
  expect(row).toMatchObject({ tone: "bad", second: FAILED, error: CREDIT });
  expect(sharedReadError([sheet], [deck])).toBe(CREDIT);
  expect(sheetLine(sheet, 0, CREDIT).sub).toBeNull();
  expect(deckLine(deck, 0, CREDIT).summary).toBeNull();
});

test("different errors, or an error on only some files, stay per file", () => {
  const a = done({ read_state: "failed", rows_mapped: 0, read_error: CREDIT });
  const b = done({ file_hash: "b", read_state: "failed", rows_mapped: 0, read_error: null });
  expect(sharedReadError([a, b], [])).toBeNull();
  expect(steps([a, b], [], { status: "idle" }, 0)[0].error).toBeUndefined();
  expect(sheetLine(b, 0).sub).toBe("The file is stored but could not be read.");
});
