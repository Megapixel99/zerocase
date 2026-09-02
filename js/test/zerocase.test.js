/**
 * What the parsers say, and what the predicates do with it.
 *
 * The parity suite proves the two halves agree; agreement is not correctness, and two
 * halves can be wrong in the same way. THIS suite is the oracle for the JavaScript half:
 * the expected numbers are written down beside fixtures whose contents a person can read.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

import {
  DID_NOT_RUN,
  EXIT_DID_NOT_RUN,
  RAN_AND_PASSED,
  run,
} from "@megapixel99/didrun";

import * as parsers from "../src/parse.js";
import { ParseError } from "../src/parse.js";
import * as reports from "../src/reports.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const FIXTURES = path.join(ROOT, "fixtures");
const BIN = path.join(ROOT, "js", "bin", "zerocase.js");
const run3 = promisify(execFile);

const fixture = (name) => fs.readFileSync(path.join(FIXTURES, name), "utf8");
const tmpdir = () => fs.mkdtempSync(path.join(os.tmpdir(), "zerocase-"));

// --------------------------------------------------------------- what they say

test("junit counts testcases and subtracts the skipped", () => {
  const t = parsers.junit(fixture("junit-real.xml"));
  assert.deepEqual([t.total, t.executed], [4, 3]);
});

test("a suite where everything is skipped executed nothing", () => {
  // THE CASE A TOTAL CANNOT SEE. `tests="3" skipped="3"` is a green run of nothing
  // wearing a total, and any counter reading only the total calls it three tests.
  const skipped = parsers.junit(fixture("junit-all-skipped.xml"));
  assert.deepEqual([skipped.total, skipped.executed], [3, 0]);
  const control = parsers.junit(fixture("junit-real.xml"));
  assert.ok(
    control.executed > 0,
    "if no fixture ever executes anything, the check above is satisfied by a parser " +
      "that always returns zero"
  );
});

test("the header is a claim and the elements are the thing", () => {
  const t = parsers.junit(fixture("junit-lying-header.xml"));
  assert.deepEqual([t.total, t.executed], [2, 2]);
  assert.match(t.note, /claims tests="47"/);
});

test("xml quoted inside a comment or CDATA is not a test", () => {
  const t = parsers.junit(fixture("junit-comment-trap.xml"));
  assert.deepEqual([t.total, t.executed], [1, 1]);
});

test("a raw `>` inside an attribute value does not end the tag", () => {
  // XML escapes `<` and leaves `>` alone, so a test named `--at <file>:<line>` reaches
  // the report as `name="--at &lt;file>:&lt;line>"` and is well-formed. A scanner that
  // ended the tag at that `>` drops the `/` of the self-closing element, reads the case
  // as still open, and loses it when the next one replaces it: one test short, on a
  // report that parsed and looked fine.
  const t = parsers.junit(fixture("junit-gt-in-attr.xml"));
  assert.deepEqual([t.total, t.executed], [4, 3]);
  // The same truncation in the `<testsuite>` tag hides the header's claim entirely,
  // and a header that cannot be read is a header that cannot be contradicted.
  assert.match(t.note, /claims tests="9"/);
});

test("tap reads the plan and the skip directive", () => {
  const zero = parsers.tap(fixture("tap-zero.tap"));
  assert.deepEqual([zero.total, zero.executed], [0, 0]);
  const real = parsers.tap(fixture("tap-real.tap"));
  assert.deepEqual([real.total, real.executed], [3, 2]);
});

test("lcov separates instrumented from hit", () => {
  const none = parsers.lcov(fixture("lcov-nohits.info"));
  assert.deepEqual([none.total, none.executed], [10, 0]);
  const real = parsers.lcov(fixture("lcov-real.info"));
  assert.deepEqual([real.total, real.executed], [32, 22]);
});

test("cobertura reads the header and checks the body", () => {
  const empty = parsers.cobertura(fixture("cobertura-empty.xml"));
  assert.deepEqual([empty.total, empty.executed], [0, 0]);
  const real = parsers.cobertura(fixture("cobertura-real.xml"));
  assert.deepEqual([real.total, real.executed], [4, 3]);
});

test("the empty eslint glob is an empty list", () => {
  assert.equal(parsers.eslint(fixture("eslint-empty.json")).total, 0);
  assert.equal(parsers.eslint(fixture("eslint-real.json")).total, 2);
});

test("the failure count is read and is never a verdict", () => {
  // Informational. Whether a suite failed is the exit code's business and `didrun`
  // already reads it — but a reader looking at "4 of 4 tests ran" should not have to open
  // the file to find out how it went.
  assert.equal(parsers.junit(fixture("junit-real.xml")).failed, 1);
  assert.equal(parsers.tap(fixture("tap-real.tap")).failed, 1);
  assert.equal(parsers.eslint(fixture("eslint-real.json")).failed, 1);
  assert.equal(parsers.junit(fixture("junit-all-skipped.xml")).failed, 0);
});

test("a skipped test carrying a failure is neither run nor failed", () => {
  // A quarantined flake is emitted as `<skipped/>` AND `<failure>` in one case. It did not
  // run, so it cannot have failed. The control is in the same file: the second case ran
  // and did not fail.
  const t = parsers.junit(fixture("junit-skipped-with-failure.xml"));
  assert.deepEqual([t.total, t.executed, t.failed], [2, 1, 0]);
});

test("an unreadable report throws rather than returning zero", () => {
  // The third answer. A zero and an unreadable file are different failures.
  assert.throws(() => parsers.junit(fixture("junit-not.xml")), ParseError);
  assert.throws(() => parsers.lcov("nothing here"), ParseError);
  assert.throws(() => parsers.eslint("{}"), ParseError);
});

test("a non-numeric json path is a refusal, not a zero", () => {
  assert.throws(() => parsers.jsonAt(fixture("summary.json"), "summary.label"), ParseError);
  assert.throws(() => parsers.jsonAt(fixture("summary.json"), "summary.missing"), ParseError);
});

// ---------------------------------------------------------------- the verdict

test("the four sentences are four different sentences", () => {
  const rows = [
    reports.verdict("junit", 4, 3, 1),
    reports.verdict("junit", 0, 0, 1),
    reports.verdict("junit", 3, 0, 1),
    reports.verdict("junit", 4, 3, 4),
  ];
  assert.deepEqual(rows.map((r) => r[0]), [true, false, false, false]);
  assert.equal(new Set(rows.map((r) => r[1])).size, 4);
});

test("a floor of zero is refused", () => {
  assert.throws(() => reports.junit("x.xml", { min: 0 }), RangeError);
});

// ------------------------------------------------------------- through didrun

const writer = (file, body) => [
  process.execPath,
  "-e",
  `require("fs").writeFileSync(${JSON.stringify(file)}, ${JSON.stringify(body)})`,
];

test("a report the run wrote with tests in it is evidence", async () => {
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const result = await run(writer(file, fixture("junit-real.xml")), {
    evidence: [reports.junit(file)],
  });
  assert.equal(result.state, RAN_AND_PASSED, result.checks[0].detail);
  assert.match(result.checks[0].detail, /3 of 4 tests ran/);
});

test("a report the run wrote with NOTHING in it is did-not-run", async () => {
  // The flagship, and the control for the test above. Both are asserted because a
  // predicate that always refused would satisfy this one alone.
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const result = await run(writer(file, fixture("junit-empty.xml")), {
    evidence: [reports.junit(file)],
  });
  assert.equal(result.state, DID_NOT_RUN);
  assert.match(result.checks[0].detail, /the denominator is zero/);
});

test("a suite that skipped everything is did-not-run", async () => {
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const result = await run(writer(file, fixture("junit-all-skipped.xml")), {
    evidence: [reports.junit(file)],
  });
  assert.equal(result.state, DID_NOT_RUN);
  assert.match(result.checks[0].detail, /0 of 3 tests ran/);
});

test("a stale report is not evidence however full it is", async () => {
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  fs.writeFileSync(file, fixture("junit-real.xml"));
  const result = await run([process.execPath, "-e", ""], {
    evidence: [reports.junit(file)],
  });
  assert.equal(result.state, DID_NOT_RUN);
  assert.match(result.checks[0].detail, /stale artefact/);
});

test("allowStale lifts it and the same file then passes", async () => {
  // The control for the test above: the file, not the freshness, is what changed.
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  fs.writeFileSync(file, fixture("junit-real.xml"));
  const result = await run([process.execPath, "-e", ""], {
    evidence: [reports.junit(file, { allowStale: true })],
  });
  assert.equal(result.state, RAN_AND_PASSED);
});

test("a report that cannot be parsed is neither a zero nor a pass", async () => {
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const result = await run(writer(file, fixture("junit-not.xml")), {
    evidence: [reports.junit(file)],
  });
  assert.equal(result.state, DID_NOT_RUN);
  const detail = result.checks[0].detail;
  assert.match(detail, /could not read/);
  assert.match(detail, /is not a zero, and it is not a pass/);
  assert.doesNotMatch(detail, /denominator is zero/);
});

test("a glob sums the reports it matched", async () => {
  const dir = tmpdir();
  const a = path.join(dir, "a.xml");
  const b = path.join(dir, "b.xml");
  const cmd = [
    process.execPath,
    "-e",
    `const fs=require("fs");` +
      `fs.writeFileSync(${JSON.stringify(a)}, ${JSON.stringify(fixture("junit-real.xml"))});` +
      `fs.writeFileSync(${JSON.stringify(b)}, ${JSON.stringify(fixture("junit-all-skipped.xml"))});`,
  ];
  const result = await run(cmd, { evidence: [reports.junit(path.join(dir, "*.xml"))] });
  assert.equal(result.state, RAN_AND_PASSED, result.checks[0].detail);
  assert.match(result.checks[0].detail, /3 of 7 tests ran/);
  assert.match(result.checks[0].detail, /across 2 files/);
});

test("a stale file the run did not write is left out of the sum", async () => {
  // THE COUNT OF A RUN THAT IS OVER IS NOT PART OF THIS ONE. `unittest-xml-reporting`
  // writes `TEST-<Class>-<timestamp>.xml`, and those names never collide — so a second
  // run into a directory nobody cleaned ADDS files rather than replacing them. Until
  // 0.1.2 the freshness rule asked only whether ONE match had changed and the tally then
  // summed every match, so yesterday's three passing tests carried today's floor for a
  // run that executed nothing.
  const dir = tmpdir();
  const old = path.join(dir, "TEST-old.xml");
  const fresh = path.join(dir, "TEST-new.xml");
  fs.writeFileSync(old, fixture("junit-real.xml")); // 3 executed, from a run that ended
  const result = await run(writer(fresh, fixture("junit-all-skipped.xml")), {
    evidence: [reports.junit(path.join(dir, "*.xml"), { min: 3 })],
  });
  assert.equal(result.state, DID_NOT_RUN);
  const detail = result.checks[0].detail;
  assert.match(detail, /0 of 3 tests ran/);
  assert.match(detail, /1 stale file\(s\) this run did not write/);
  assert.match(detail, /TEST-old\.xml/);
});

test("allowStale still sums every file the glob matched", async () => {
  // The control for the test above: the freshness rule, not the files, is what changed.
  // `allowStale` says the report may predate the command, and a glob under it counts
  // every match — which is the only reading of the flag that is honest.
  const dir = tmpdir();
  const old = path.join(dir, "TEST-old.xml");
  const fresh = path.join(dir, "TEST-new.xml");
  fs.writeFileSync(old, fixture("junit-real.xml"));
  const result = await run(writer(fresh, fixture("junit-all-skipped.xml")), {
    evidence: [reports.junit(path.join(dir, "*.xml"), { min: 3, allowStale: true })],
  });
  assert.equal(result.state, RAN_AND_PASSED, result.checks[0].detail);
  assert.match(result.checks[0].detail, /3 of 7 tests ran/);
  assert.doesNotMatch(result.checks[0].detail, /stale file/);
});

test("a glob match rewritten with the SAME bytes still counts", async () => {
  // A deterministic runner did run, and `didrun.evidence.wrote` says so by mtime. The
  // glob branch compared digests alone, so one file was fresh through a plain path and
  // stale through a pattern. The mtime is pushed into the past rather than slept over,
  // because a filesystem with one-second granularity would decide this test.
  const dir = tmpdir();
  const file = path.join(dir, "TEST-same.xml");
  const body = fixture("junit-real.xml");
  fs.writeFileSync(file, body);
  const was = new Date(Date.now() - 10_000);
  fs.utimesSync(file, was, was);
  const result = await run(writer(file, body), {
    evidence: [reports.junit(path.join(dir, "*.xml"))],
  });
  assert.equal(result.state, RAN_AND_PASSED, result.checks[0].detail);
  assert.match(result.checks[0].detail, /3 of 4 tests ran/);
});

test("a report where everything failed still satisfies the floor", async () => {
  // THE CONTROL FOR THE FAILURE COUNT. This package asks whether anything ran, not whether
  // it passed — folding the two together would make it a worse test runner instead of a
  // denominator check.
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const result = await run(writer(file, fixture("junit-real.xml")), {
    evidence: [reports.junit(file)],
  });
  assert.equal(result.state, RAN_AND_PASSED);
  assert.match(result.checks[0].detail, /1 failed/);
});

test("a floor can be set for one kind without setting it for all", async () => {
  const dir = tmpdir();
  const junitFile = path.join(dir, "junit.xml");
  const lcovFile = path.join(dir, "lcov.info");
  const cmd = [
    process.execPath,
    "-e",
    `const fs=require("fs");` +
      `fs.writeFileSync(${JSON.stringify(junitFile)}, ${JSON.stringify(fixture("junit-real.xml"))});` +
      `fs.writeFileSync(${JSON.stringify(lcovFile)}, ${JSON.stringify(fixture("lcov-real.info"))});`,
  ];
  const result = await run(cmd, {
    evidence: [reports.junit(junitFile, { min: 1 }), reports.lcov(lcovFile, { min: 200 })],
  });
  assert.equal(result.state, DID_NOT_RUN);
  assert.equal(result.checks[0].satisfied, true);
  assert.equal(result.checks[1].satisfied, false);
  assert.match(result.checks[1].detail, /below the floor of 200/);
});

test("the predicate keeps the numbers and not only the sentence", async () => {
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const predicate = reports.junit(file);
  assert.equal(predicate.tally, null);
  await run(writer(file, fixture("junit-real.xml")), { evidence: [predicate] });
  assert.equal(predicate.tally.executed, 3);
  assert.equal(predicate.tally.total, 4);
  assert.equal(predicate.tally.failed, 1);
});

test("read sums a glob rather than taking the first match", () => {
  const dir = tmpdir();
  fs.writeFileSync(path.join(dir, "a.xml"), fixture("junit-real.xml"));
  fs.writeFileSync(path.join(dir, "b.xml"), fixture("junit-all-skipped.xml"));
  const t = reports.read("junit", path.join(dir, "*.xml"));
  assert.deepEqual([t.total, t.executed], [7, 3]);
});

test("a glob that matched nothing is not a clean result", async () => {
  const dir = tmpdir();
  const result = await run([process.execPath, "-e", ""], {
    evidence: [reports.junit(path.join(dir, "*.xml"))],
  });
  assert.equal(result.state, DID_NOT_RUN);
  assert.match(result.checks[0].detail, /matched no files/);
});

test("a glob matching nothing is refused with the freshness check OFF too", async () => {
  // The control the mutation suite asked for. The test above reaches the same verdict
  // through the freshness gate, which fires first — so it left the second refusal
  // unexercised, and a mutation that scored an empty glob as evidence survived.
  const dir = tmpdir();
  const result = await run([process.execPath, "-e", ""], {
    evidence: [reports.junit(path.join(dir, "*.xml"), { allowStale: true })],
  });
  assert.equal(result.state, DID_NOT_RUN);
  assert.match(result.checks[0].detail, /matched no files/);
});

test("read accepts the very file the predicate rejects as stale", async () => {
  // `read` is the loaded gun, and it is loaded on purpose.
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  fs.writeFileSync(file, fixture("junit-real.xml"));
  const rejected = await run([process.execPath, "-e", ""], {
    evidence: [reports.junit(file)],
  });
  assert.equal(rejected.state, DID_NOT_RUN);
  assert.equal(reports.read("junit", file).executed, 3);
});

// -------------------------------------------------------------- the binary

async function zerocase(...args) {
  try {
    const { stdout, stderr } = await run3(process.execPath, [BIN, ...args], { cwd: ROOT });
    return { code: 0, stdout, stderr };
  } catch (err) {
    return { code: err.code, stdout: err.stdout || "", stderr: err.stderr || "" };
  }
}

test("no report and no predicate is exit 2", async () => {
  // Could-not-measure has its own exit code and never borrows a verdict's.
  const out = await zerocase("--", process.execPath, "-e", "");
  assert.equal(out.code, 2);
  assert.match(out.stderr, /name at least one report/);
});

test("an empty report from a zero-exit command is exit 3", async () => {
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const out = await zerocase("--junit", file, "--", ...writer(file, fixture("junit-empty.xml")));
  assert.equal(out.code, EXIT_DID_NOT_RUN);
});

test("a full report from the same shape of command is exit 0", async () => {
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const out = await zerocase("--junit", file, "--", ...writer(file, fixture("junit-real.xml")));
  assert.equal(out.code, 0, out.stderr);
});

test("read prints the tally and warns that it checked no freshness", async () => {
  const out = await zerocase("read", "--junit", path.join(FIXTURES, "junit-real.xml"));
  assert.equal(out.code, 0);
  assert.match(out.stdout, /3 of 4 tests ran/);
  assert.match(out.stdout, /does not check freshness/);
});

test("read on an empty report exits 3", async () => {
  const out = await zerocase("read", "--junit", path.join(FIXTURES, "junit-empty.xml"));
  assert.equal(out.code, EXIT_DID_NOT_RUN);
});

test("a `--help` in the command under test is not zerocase's own", async () => {
  // THE GATE THAT COULD NOT FAIL. `main` scanned the whole of argv for `-h`/`--help`
  // before it split on `--`, so a flag belonging to the wrapped command printed OUR
  // usage and returned 0 without ever spawning it. The report here is empty and the
  // floor is unmet, so the only way to exit 0 is to never look — and the marker file
  // proves the command was actually run rather than skipped into a pass.
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const runner = path.join(dir, "runner.js");
  fs.writeFileSync(
    runner,
    `require("fs").writeFileSync(${JSON.stringify(file)}, ${JSON.stringify(fixture("junit-empty.xml"))})`
  );
  const out = await zerocase("--junit", file, "--", process.execPath, runner, "--help");
  assert.equal(out.code, EXIT_DID_NOT_RUN);
  assert.ok(fs.existsSync(file), "the command under test never ran");
  assert.doesNotMatch(out.stderr, /a check with a zero denominator/);
});

test("`-h` in the command under test is a hostname, not our flag", async () => {
  // `--help` needs a command that takes it. `-h` needs nothing unusual at all: it is a
  // hostname to `mysqldump`, `curl` and `ab`, so this shape was a gate reporting clean
  // forever on a report it never opened.
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const runner = path.join(dir, "runner.js");
  fs.writeFileSync(
    runner,
    `require("fs").writeFileSync(${JSON.stringify(file)}, ${JSON.stringify(fixture("junit-empty.xml"))})`
  );
  const out = await zerocase(
    "--junit", file, "--", process.execPath, runner, "-h", "dbhost"
  );
  assert.equal(out.code, EXIT_DID_NOT_RUN);
  assert.ok(fs.existsSync(file), "the command under test never ran");
});

test("zerocase's own --help still prints usage and exits 0", async () => {
  // The flag has to keep working where it IS ours, or the fix above is a regression
  // wearing a test.
  for (const flag of ["-h", "--help"]) {
    const out = await zerocase(flag);
    assert.equal(out.code, 0, flag);
    assert.match(out.stderr, /a check with a zero denominator/);
  }
  const bare = await zerocase();
  assert.equal(bare.code, 2, "no arguments at all is could-not-run, not help");
});

test("read refuses a floor rather than silently ignoring it", async () => {
  // THE REGRESSION THIS EXISTS FOR. `read` used to drop everything past the path, so
  // `--min 4` beside a report holding 1 exited 0: a floor written down in a CI file, in
  // review and in the blame, that nothing on earth enforced. A promise nothing runs is
  // the defect this package is about, and shipping it inside `read` was the joke telling
  // itself. Exit 2 — could not run — is the honest answer, and `--min` still means what
  // it says in the wrapper form, which is the form that also checks freshness.
  const out = await zerocase(
    "read", "--junit", path.join(FIXTURES, "junit-real.xml"), "--min", "9"
  );
  assert.equal(out.code, 2);
  assert.match(out.stderr, /unexpected argument --min/);
  assert.match(out.stderr, /wrapper form/);
});

test("read refuses an unquoted glob rather than reading the first match", async () => {
  // The same silence wearing different clothes: the shell expands `*.xml` before the
  // process starts, so `read --junit reports/*.xml` arrives as three arguments and the
  // second and third used to vanish. `read` sums a glob when it is given ONE — and the
  // difference between "summed five reports" and "read one of five" is invisible in the
  // output, which is exactly the kind of quiet undercount this tool exists to refuse.
  const dir = tmpdir();
  for (const name of ["a.xml", "b.xml"]) {
    fs.writeFileSync(path.join(dir, name), fixture("junit-real.xml"));
  }
  const expanded = fs.readdirSync(dir).sort().map((n) => path.join(dir, n));
  assert.equal(expanded.length, 2, "the shell must have had two matches to expand");
  const out = await zerocase("read", "--junit", ...expanded);
  assert.equal(out.code, 2);
  assert.match(out.stderr, /quote a glob/);

  // And quoted, it is the sum — the behaviour the refusal is steering people toward.
  const quoted = await zerocase("read", "--junit", path.join(dir, "*.xml"));
  assert.equal(quoted.code, 0);
  assert.match(quoted.stdout, /6 of 8 tests ran/);
});

test("--json-out is machine readable and carries the numbers", async () => {
  const dir = tmpdir();
  const file = path.join(dir, "junit.xml");
  const out = await zerocase(
    "--junit", file, "--json-out", "--",
    ...writer(file, fixture("junit-real.xml"))
  );
  const payload = JSON.parse(out.stdout);
  assert.equal(payload.state, RAN_AND_PASSED);
  assert.equal(payload.checks[0].satisfied, true);
  assert.deepEqual(payload.reports[0], {
    kind: "junit", path: file, files: 1, stale: 0, total: 4, executed: 3, failed: 1,
    minimum: 1,
  });
});

test("--min-KIND sets a floor for one kind from the command line", async () => {
  const dir = tmpdir();
  const file = path.join(dir, "lcov.info");
  const out = await zerocase(
    "--lcov", file, "--min-lcov", "200", "--",
    ...writer(file, fixture("lcov-real.info"))
  );
  assert.equal(out.code, EXIT_DID_NOT_RUN);
  assert.match(out.stderr, /below the floor of 200/);
});
