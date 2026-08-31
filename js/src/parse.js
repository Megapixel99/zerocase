/**
 * The parsers: a report file in, a `Tally` out, or a stated reason it could not be read.
 *
 * THE ONE CLAIM THIS PACKAGE MAKES: a check with a zero denominator reports clean. A
 * suite that collected nothing, a lint whose glob matched nothing, a coverage run over
 * no statements — every one of them exits 0, and every one has a field that says `0` in
 * a document it already wrote.
 *
 * THREE ANSWERS, NEVER TWO. A report can be read and hold a number, or be read and hold
 * a zero, or not be readable at all — and the third must not collapse into either of the
 * others. An unparseable report is not a zero and it is certainly not a pass.
 *
 * COUNT THE ELEMENTS, NOT THE ATTRIBUTES, WHEREVER BOTH EXIST. `<testsuite tests="47">`
 * is a claim the writer made; forty-seven `<testcase>` elements are the thing itself.
 *
 * Kept word for word in step with `python/zerocase/parse.py`, including the regexes: the
 * two halves run the SAME scanner rather than two parsers, so a disagreement between
 * them is a question about one report and not about two engines.
 */

export const KINDS = ["junit", "tap", "lcov", "cobertura", "eslint", "json"];
export const UNITS = {
  junit: "tests", tap: "tests", lcov: "lines",
  cobertura: "lines", eslint: "files", json: "items",
};
export const VERBS = {
  junit: "ran", tap: "ran", lcov: "were covered",
  cobertura: "were covered", eslint: "were linted", json: "counted",
};
// What a non-zero `failed` count is called for each kind. INFORMATIONAL AND NEVER A
// VERDICT: whether a suite failed is the exit code's business and `didrun` already reads
// it. What this adds is that a reader looking at "4 of 4 tests ran" and wondering how it
// went does not have to open the file.
export const FAILED_LABELS = {
  junit: "failed", tap: "failed", eslint: "with problems",
  lcov: "failed", cobertura: "failed", json: "failed",
};

/** The report could not be read. Never silently a zero, never silently a pass. */
export class ParseError extends Error {}

/**
 * What one report says about its own denominator.
 *
 * `total` is what the report contains; `executed` is how much of it actually happened.
 * THE FLOOR APPLIES TO `executed`, AND THAT IS THE WHOLE POINT OF HAVING TWO NUMBERS. A
 * suite where every test is skipped writes `tests="50"`, and it is exactly as vacuous as
 * one that wrote `tests="0"`.
 */
export function tally(kind, total, executed, note = "", failed = 0) {
  return {
    kind, total, executed, note, failed,
    unit: UNITS[kind],
    verb: VERBS[kind],
    failedLabel: FAILED_LABELS[kind],
  };
}

// --------------------------------------------------------------------------- junit

// Comments and CDATA are stripped before anything is scanned. A failure message
// containing the text `<testcase>` is ordinary — assertion output quotes XML all the
// time — and a scanner that counted it would report tests that do not exist.
const strip = (text) =>
  text.replace(/<!\[CDATA\[[\s\S]*?\]\]>/g, "").replace(/<!--[\s\S]*?-->/g, "");

const TAG = /<\s*(\/?)\s*(testcase|skipped|failure|error)\b([^>]*?)(\/?)\s*>/gi;
const SUITE_ATTR = /<\s*testsuite\b([^>]*?)\/?\s*>/gi;
const ATTR = /([\w:.-]+)\s*=\s*"([^"]*)"|([\w:.-]+)\s*=\s*'([^']*)'/g;

function attrs(blob) {
  const out = {};
  for (const m of String(blob || "").matchAll(ATTR)) {
    const key = (m[1] || m[3]).toLowerCase();
    out[key] = m[1] === undefined ? m[4] : m[2];
  }
  return out;
}

export function junit(text) {
  const body = strip(text);
  let total = 0;
  let executed = 0;
  let failed = 0;
  let openCase = false;
  let caseSkipped = false;
  let caseFailed = false;
  for (const m of body.matchAll(TAG)) {
    const [, closing, rawName, , selfClosing] = m;
    const name = rawName.toLowerCase();
    if (name === "testcase") {
      if (closing) {
        if (openCase) {
          executed += caseSkipped ? 0 : 1;
          failed += caseFailed && !caseSkipped ? 1 : 0;
          openCase = false;
        }
        continue;
      }
      total += 1;
      if (selfClosing) {
        executed += 1; // a self-closed testcase holds no `<skipped/>`
      } else {
        openCase = true;
        caseSkipped = false;
        caseFailed = false;
      }
    } else if (!closing && openCase) {
      if (name === "skipped") caseSkipped = true;
      else caseFailed = true; // `<failure>` or `<error>`, counted once per case
    }
  }
  if (openCase) {
    executed += caseSkipped ? 0 : 1; // truncated file
    failed += caseFailed && !caseSkipped ? 1 : 0;
  }

  let claimed = 0;
  let seenAttr = false;
  for (const m of body.matchAll(SUITE_ATTR)) {
    const a = attrs(m[1]);
    if ("tests" in a) {
      const n = Number.parseInt(a.tests, 10);
      if (!Number.isFinite(n)) { seenAttr = false; break; }
      seenAttr = true;
      claimed += n;
    }
  }
  if (total === 0 && !seenAttr && !body.toLowerCase().includes("<testsuite")) {
    throw new ParseError(
      "no <testsuite> or <testcase> elements — this is not a JUnit report"
    );
  }
  let note = "";
  if (seenAttr && claimed !== total) {
    note =
      `the file claims tests="${claimed}" in its <testsuite> attributes and contains ` +
      `${total} <testcase> elements; the elements are what is counted`;
  }
  return tally("junit", total, executed, note, failed);
}

// ----------------------------------------------------------------------------- tap

const PLAN = /^[ \t]*1\.\.(\d+)[ \t]*(?:#[ \t]*(.*))?$/m;
const TEST = /^[ \t]*(not[ \t]+ok|ok)\b(.*)$/gim;
const SKIP = /#\s*(skip|todo)\b/i;

export function tap(text) {
  const lines = [...text.matchAll(TEST)];
  const ran = lines.reduce((n, m) => n + (SKIP.test(m[2] || "") ? 0 : 1), 0);
  const plan = text.match(PLAN);
  if (!plan && lines.length === 0) {
    throw new ParseError("no TAP plan (`1..N`) and no `ok` / `not ok` lines");
  }
  const total = plan ? Number.parseInt(plan[1], 10) : lines.length;
  const failed = lines.reduce(
    (n, m) =>
      n + (m[1].toLowerCase().startsWith("not") && !SKIP.test(m[2] || "") ? 1 : 0),
    0
  );
  let note = "";
  if (plan && lines.length !== total) {
    note =
      `the plan says ${total} and ${lines.length} result lines are present; ` +
      `the plan is what is counted`;
  }
  return tally("tap", total, plan ? Math.min(ran, total) : ran, note, failed);
}

// ---------------------------------------------------------------------------- lcov

export function lcov(text) {
  const found = [...text.matchAll(/^LF:\s*(\d+)\s*$/gm)].map((m) => Number(m[1]));
  const hit = [...text.matchAll(/^LH:\s*(\d+)\s*$/gm)].map((m) => Number(m[1]));
  if (found.length === 0 && hit.length === 0) {
    throw new ParseError("no `LF:` or `LH:` records — this is not an LCOV trace file");
  }
  const sum = (xs) => xs.reduce((a, b) => a + b, 0);
  return tally("lcov", sum(found), sum(hit));
}

// ----------------------------------------------------------------------- cobertura

export function cobertura(text) {
  const body = strip(text);
  const root = body.match(/<\s*coverage\b([^>]*?)\/?\s*>/i);
  if (!root) {
    throw new ParseError("no <coverage> element — this is not a Cobertura report");
  }
  const a = attrs(root[1]);
  const elements = [...body.matchAll(/<\s*line\b([^>]*?)\/?\s*>/gi)].map((m) =>
    attrs(m[1])
  );
  let hits = 0;
  for (const el of elements) {
    const n = Number.parseInt(el.hits ?? "0", 10);
    if (Number.isFinite(n) && n > 0) hits += 1;
  }
  if ("lines-valid" in a) {
    const total = Number.parseInt(a["lines-valid"], 10);
    const covered =
      "lines-covered" in a ? Number.parseInt(a["lines-covered"], 10) : hits;
    if (!Number.isFinite(total) || !Number.isFinite(covered)) {
      throw new ParseError("<coverage> has a non-numeric lines-valid or lines-covered");
    }
    let note = "";
    if (elements.length && total !== elements.length) {
      note =
        `the header claims lines-valid="${total}" and the body holds ` +
        `${elements.length} <line> elements`;
    }
    return tally("cobertura", total, covered, note);
  }
  if (elements.length === 0) {
    throw new ParseError(
      "<coverage> has no lines-valid attribute and no <line> elements"
    );
  }
  return tally("cobertura", elements.length, hits);
}

// -------------------------------------------------------------------------- eslint

/**
 * ESLint's JSON formatter: one entry per file it actually looked at.
 *
 * THE EMPTY GLOB IS `[]`. `npx eslint 'src/**\/*.ts'` on a repository whose sources moved
 * to `lib/` prints two characters, exits 0, and is indistinguishable in CI from a clean
 * lint of four hundred files.
 */
export function eslint(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (err) {
    throw new ParseError(`not valid JSON: ${err.message}`);
  }
  if (!Array.isArray(data)) {
    throw new ParseError(
      `the ESLint JSON formatter emits a list of file results; this is a ${typeof data}`
    );
  }
  const files = data.filter((d) => d && typeof d === "object" && "filePath" in d);
  if (data.length && files.length === 0) {
    throw new ParseError("the entries have no `filePath` — this is not ESLint JSON");
  }
  const problems = files.filter((d) => (d.errorCount || 0) || (d.warningCount || 0)).length;
  return tally("eslint", data.length, files.length, "", problems);
}

// ---------------------------------------------------------------------------- json

export function jsonAt(text, path) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (err) {
    throw new ParseError(`not valid JSON: ${err.message}`);
  }
  let cursor = data;
  const walked = [];
  for (const part of String(path).split(".")) {
    walked.push(part);
    if (Array.isArray(cursor)) {
      const idx = Number.parseInt(part, 10);
      if (Number.isFinite(idx) && idx >= 0 && idx < cursor.length) {
        cursor = cursor[idx];
        continue;
      }
      throw new ParseError(
        `\`${walked.join(".")}\` is not an index into a list of ${cursor.length}`
      );
    }
    if (cursor === null || typeof cursor !== "object" || !(part in cursor)) {
      throw new ParseError(`\`${walked.join(".")}\` is not present in the document`);
    }
    cursor = cursor[part];
  }
  if (typeof cursor !== "number" || !Number.isFinite(cursor)) {
    throw new ParseError(
      `\`${path}\` is ${JSON.stringify(cursor).slice(0, 40)}, which is not a number`
    );
  }
  const n = Math.trunc(cursor);
  return tally("json", n, n, `read from \`${path}\``);
}

export const PARSERS = { junit, tap, lcov, cobertura, eslint };

export function parse(kind, text) {
  const fn = PARSERS[kind];
  if (!fn) throw new ParseError(`no parser named '${kind}'`);
  return fn(text);
}
