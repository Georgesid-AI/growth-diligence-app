/**
 * A test committed before its code (docs/specs/*.md, CLAUDE.md rule 11): it must fail until the code PR turns `failing(...)` back
 * into `test(...)`. A pass is an error, as with pytest's strict xfail, so a test that passes before its code exists is caught.
 * Jest 27 (react-scripts 5) has no `test.failing`, hence this helper. Modules that do not exist yet are required inside `fn`, so the
 * test file always loads.
 */
export function failing(name, fn, timeout) {
  // eslint-disable-next-line no-undef
  test(`[fails until built] ${name}`, async () => {
    let passed = false;
    try {
      await fn();
      passed = true;
    } catch (e) {
      // the expected failure; SHOW_EXPECTED_FAILURES=1 prints why, to check it fails for the missing feature and not a test bug
      if (process.env.SHOW_EXPECTED_FAILURES) console.log(`[expected failure] ${name}\n${String(e && e.message).split("\n").slice(0, 4).join("\n")}`);
    }
    if (passed) throw new Error(`"${name}" passes: turn failing() into test()`);
  }, timeout);
}
