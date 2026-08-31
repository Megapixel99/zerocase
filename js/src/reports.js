/**
 * Evidence predicates that read the report the runner already wrote.
 *
 * These are `didrun` predicates — the same `{ name, before, check }` shape its own
 * `evidence` module produces, handed to `didrun.run()`, which does the running, the four
 * states, the exit codes and the timeout classification. None of that is reimplemented
 * here, for the reason `canfail` gave when it deleted its inline `_Guard`: a second copy
 * of a guarantee is a second thing to get wrong, and the copy is the one that does not
 * get the upstream's tests.
 *
 * WHAT IS ACTUALLY NEW IS TWO NUMBERS INSTEAD OF ONE.
 *
 *     <testsuite tests="50" skipped="50">
 *
 * is a green run of nothing wearing a total. `--expect-count "(\d+) tests"` reads the
 * fifty and is satisfied, exactly as it would be by fifty tests that ran. So every parser
 * returns `total` AND `executed`, and the floor applies to the second.
 *
 * FRESHNESS IS NOT OPTIONAL BY DEFAULT. A `junit.xml` from yesterday parses beautifully
 * and says four hundred tests passed. The single-path case delegates to
 * `didrun.evidence.wrote` rather than restating it, so "a stale artefact from an earlier
 * run looks exactly like this" is one sentence in one package.
 *
 * AND IT IS PER FILE, NOT PER PATTERN. A glob is asked which of its matches THIS run
 * wrote, and only those are summed. Asking whether anything under `reports/*.xml` changed
 * and then counting everything under `reports/*.xml` lets a run that is over carry the
 * floor for the run in front of you, which is this package's own thesis pointed the wrong
 * way.
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { evidence } from "@megapixel99/didrun";

import * as parsers from "./parse.js";
import { FAILED_LABELS, ParseError, UNITS, VERBS } from "./parse.js";

const GLOB_CHARS = /[*?[]/;

/**
 * Size, mtime and digest — the three things `didrun.evidence.wrote` compares.
 *
 * The same three, deliberately: a runner that writes a byte-identical report DID run, and
 * `wrote` says so by looking at the mtime when the digest matches. A glob branch that
 * compared digests alone called that same run stale, so the two paths disagreed about one
 * file depending on whether the pattern had a `*` in it.
 */
function stat(file) {
  try {
    const st = fs.statSync(file);
    const data = fs.readFileSync(file);
    return {
      size: st.size,
      mtime: st.mtimeMs,
      digest: crypto.createHash("sha256").update(data).digest("hex"),
    };
  } catch {
    return null;
  }
}

/** Did THIS run touch this one file? The rule `wrote` uses, per matched path. */
function isFresh(now, was) {
  if (now === null || now === undefined) return false; // matched, then unreadable
  if (was === null || was === undefined) return true; // it was not there before the run
  if (now.digest !== was.digest) return true;
  return now.mtime > was.mtime; // rewritten with the same content
}

/**
 * Expand a glob the way `python/zerocase/reports.py` does, with node's own matcher.
 *
 * `fs.globSync` landed in Node 22 and this package supports 20, so the fallback is a
 * directory read filtered by the same pattern compiled to a RegExp. Both are asserted
 * against the Python half's `glob.glob` in the parity suite rather than assumed equal.
 */
function expand(pattern) {
  if (!GLOB_CHARS.test(pattern)) return [pattern];
  if (typeof fs.globSync === "function") {
    try {
      return [...fs.globSync(pattern)].sort();
    } catch {
      /* fall through to the manual expansion */
    }
  }
  const dir = path.dirname(pattern);
  const base = path.basename(pattern);
  const re = new RegExp(
    "^" +
      base
        .replace(/[.+^${}()|\\]/g, "\\$&")
        .replace(/\*/g, "[^/]*")
        .replace(/\?/g, "[^/]") +
      "$"
  );
  try {
    return fs
      .readdirSync(dir)
      .filter((name) => re.test(name))
      .map((name) => path.join(dir, name))
      .sort();
  } catch {
    return [];
  }
}

/**
 * The freshness rule for a pattern that matches a SET of files.
 *
 * `didrun.evidence.wrote` answers this for one path, and one path is the common case, so
 * that branch is delegated rather than restated. A pattern cannot be: the files may not
 * exist when `before()` runs, which is the ordinary case for a report the command is
 * about to write. The rule generalises the same way — a matched file appeared, or one
 * that was already there changed.
 *
 * IT ANSWERS PER FILE AND NOT ONLY FOR THE SET. Asking "did anything here change?" and
 * then summing everything the pattern matched is how the count of a run that is over gets
 * added to the count of the run in front of you.
 */
function globFreshness(pattern) {
  const snapshot = () => {
    const out = {};
    for (const file of expand(pattern)) out[file] = stat(file);
    return out;
  };
  return {
    snapshot,
    /**
     * -> [ok, detail, the files this run wrote, the files it did not].
     *
     * The last two are the point. `zerocase 0.1.1` returned a verdict for the set and let
     * the caller sum every match, so a second run into a directory nobody cleaned was
     * carried by the first: `unittest-xml-reporting` names its files
     * `TEST-<Class>-<timestamp>.xml`, which never collide, so run two ADDED six files to
     * run one's six and reported `42 of 42 tests ran (floor 20)` for a run that collected
     * a single test. A green run of nothing wearing somebody else's total is the exact
     * shape this package exists to report, and it was doing it.
     */
    check(before) {
      const after = snapshot();
      const names = Object.keys(after).sort();
      if (names.length === 0) {
        return [
          false,
          `${pattern} matched no files` +
            (Object.keys(before).length
              ? ` — and it matched ${Object.keys(before).length} before the run`
              : ""),
          [],
          [],
        ];
      }
      const fresh = names.filter((n) => isFresh(after[n], before[n]));
      const ignored = names.filter((n) => !fresh.includes(n));
      if (fresh.length === 0) {
        return [
          false,
          `every file matching ${pattern} is byte for byte what it was before the run — ` +
            `a stale artefact from an earlier run looks exactly like this`,
          [],
          ignored,
        ];
      }
      const appeared = fresh.filter((n) => !(n in before));
      if (appeared.length) {
        return [
          true,
          `${appeared.length} file(s) appeared, first ${appeared[0]}`,
          fresh,
          ignored,
        ];
      }
      return [true, `${fresh.length} file(s) changed`, fresh, ignored];
    },
  };
}

/**
 * The four sentences. Shared word for word with `python/zerocase/reports.py`.
 *
 * In one function in each half rather than inline at four call sites, so the parity suite
 * can assert the strings themselves — and the strings are what a person reads at 2am when
 * CI has gone red.
 */
export function verdict(kind, total, executed, minimum) {
  const unit = UNITS[kind];
  const verb = VERBS[kind];
  if (executed >= minimum) {
    return [true, `${executed} of ${total} ${unit} ${verb} (floor ${minimum})`];
  }
  if (total === 0) {
    return [
      false,
      `0 ${unit} in the report — the denominator is zero, so there was nothing here ` +
        `this check could have objected to`,
    ];
  }
  if (executed === 0) {
    return [
      false,
      `0 of ${total} ${unit} ${verb} — the report is not empty, and nothing in it happened`,
    ];
  }
  return [
    false,
    `${executed} of ${total} ${unit} ${verb}, below the floor of ${minimum}`,
  ];
}

/** One report file (or glob), parsed, with a floor on what actually happened. */
export function report(kind, file, { min = 1, allowStale = false, pointer = null } = {}) {
  if (!(kind in UNITS)) throw new TypeError(`no report kind named '${kind}'`);
  if (min < 1) {
    // A floor of zero is satisfied by a zero, which is the state this package exists to
    // report. Refusing beats accepting an argument that turns the tool into an expensive
    // no-op somebody will read as coverage.
    throw new RangeError(
      "min must be at least 1; a floor of 0 is satisfied by the empty report this " +
        "predicate exists to catch"
    );
  }
  const isGlob = GLOB_CHARS.test(file);
  const freshness = allowStale
    ? null
    : isGlob
      ? globFreshness(file)
      : evidence.wrote(file);

  return {
    name: `${file} reports at least ${min} ${UNITS[kind]} that ${VERBS[kind]}`,
    // Kept so `--json-out` can report the numbers rather than only the sentence about
    // them. One run, one predicate, one tally.
    tally: null,
    before() {
      if (!freshness) return null;
      return isGlob ? freshness.snapshot() : freshness.before();
    },
    check(result, before) {
      // THE FILES THIS RUN WROTE, not every file the pattern matched. A glob whose
      // freshness is enforced tallies only what came out of the command in front of it;
      // anything left over from an earlier run is named in the detail and left out of the
      // sum. `allowStale` is the one way to add them back, which is what it says.
      let files = null;
      let ignored = [];
      if (freshness) {
        if (isGlob) {
          const [ok, detail, wrote, skipped] = freshness.check(before);
          if (!ok) return { satisfied: false, detail };
          files = wrote;
          ignored = skipped;
        } else {
          const fresh = freshness.check(result, before);
          if (!fresh.satisfied) return { satisfied: false, detail: fresh.detail };
        }
      }
      if (files === null) files = expand(file);
      if (files.length === 0) {
        return { satisfied: false, detail: `${file} matched no files` };
      }
      let total = 0;
      let executed = 0;
      let failed = 0;
      const notes = [];
      for (const one of files) {
        let text;
        try {
          text = fs.readFileSync(one, "utf8");
        } catch (err) {
          return { satisfied: false, detail: `${one} could not be read: ${err.message}` };
        }
        let t;
        try {
          t = kind === "json" ? parsers.jsonAt(text, pointer) : parsers.parse(kind, text);
        } catch (err) {
          if (!(err instanceof ParseError)) throw err;
          // NEVER A ZERO AND NEVER A PASS. An unreadable report is a third answer, and
          // collapsing it into either of the other two is how a tool teaches people to
          // ignore it.
          return {
            satisfied: false,
            detail:
              `could not read ${one} as ${kind}: ${err.message} — an unreadable ` +
              `report is not a zero, and it is not a pass`,
          };
        }
        total += t.total;
        executed += t.executed;
        failed += t.failed;
        if (t.note) notes.push(`${one}: ${t.note}`);
      }
      let [satisfied, detail] = verdict(kind, total, executed, min);
      if (files.length > 1) detail += ` — across ${files.length} files`;
      if (ignored.length) {
        // SAID OUT LOUD, because a number that quietly got smaller is the thing this
        // package objects to. A reader who expected the leftovers counted needs to be
        // told they were not, and told which ones.
        detail +=
          `; ${ignored.length} stale file(s) this run did not write, left out of the ` +
          `count, first ${ignored[0]}`;
      }
      if (failed) {
        // INFORMATIONAL, NEVER A VERDICT. Whether a suite failed is the exit code's
        // business and `didrun` already reads it.
        detail += `; ${failed} ${FAILED_LABELS[kind]}`;
      }
      for (const note of notes) detail += `; ${note}`;
      this.tally = { kind, path: file, files: files.length, stale: ignored.length,
                     total, executed, failed, minimum: min };
      return { satisfied, detail };
    },
  };
}

// Short constructors, so a caller writes `reports.junit(...)` in either language.
export const junit = (file, opts) => report("junit", file, opts);
export const tap = (file, opts) => report("tap", file, opts);
export const lcov = (file, opts) => report("lcov", file, opts);
export const cobertura = (file, opts) => report("cobertura", file, opts);
export const eslint = (file, opts) => report("eslint", file, opts);
export const jsonAt = (file, pointer, opts = {}) =>
  report("json", file, { ...opts, pointer });

/**
 * Parse a report that is already on disk and return its tally.
 *
 * A glob is summed, the same way the predicate sums one — five reports and one report are
 * not the same result, and a `read` that silently took the first would say they were.
 *
 * NO FRESHNESS CHECK HAPPENS HERE, and that is the point of it existing separately: a
 * stale report reads identically to a fresh one, which is the whole reason the gate takes
 * a command instead of a filename.
 */
export function read(kind, file, pointer = null) {
  const files = expand(file);
  if (files.length === 0) throw new Error(`${file} matched no files`);
  let total = 0;
  let executed = 0;
  let failed = 0;
  const notes = [];
  for (const one of files) {
    const text = fs.readFileSync(one, "utf8");
    const t = kind === "json" ? parsers.jsonAt(text, pointer) : parsers.parse(kind, text);
    total += t.total;
    executed += t.executed;
    failed += t.failed;
    if (t.note) notes.push(files.length > 1 ? `${one}: ${t.note}` : t.note);
  }
  return parsers.tally(kind, total, executed, notes.join("; "), failed);
}
