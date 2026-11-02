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
