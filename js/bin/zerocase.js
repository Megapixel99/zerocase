#!/usr/bin/env node
/**
 * `zerocase` — the runner already wrote the number down. Read it.
 *
 *     zerocase --junit reports/junit.xml -- pytest tests/
 *     zerocase --lcov coverage/lcov.info --min 50 -- npm run coverage
 *     zerocase read --junit reports/junit.xml
 *
 * Exit codes are `didrun`'s, unchanged: 0 ran and passed · 3 DID NOT RUN · 4 failed the
 * wrong way · 2 this tool could not run at all · otherwise the command's own status. A CI
 * file that already branches on `didrun` does not have to learn a second table.
 *
 * THE FLAGS ARE THE PYTHON HALF'S, deliberately, and `python/tests/test_parity.py`
 * asserts the vocabulary the two share.
 */

import process from "node:process";
import { evidence, exitCodeFor, report, run } from "@megapixel99/didrun";
import * as rep from "../src/reports.js";
import { KINDS, ParseError } from "../src/parse.js";

const USAGE = `zerocase — a check with a zero denominator reports clean.

  zerocase [reports...] [evidence...] [options] -- COMMAND...
  zerocase read --KIND PATH

Reports (each may be repeated, and each may be a glob):
  --junit PATH        JUnit/xUnit XML — <testcase> elements, minus the skipped
  --tap PATH          TAP — the \`1..N\` plan, minus \`# SKIP\`
  --lcov PATH         LCOV — LF: lines found, LH: lines hit
  --cobertura PATH    Cobertura XML — lines-valid / lines-covered
  --eslint PATH       ESLint --format json — the files it actually looked at
  --json PATH:A.B.C   a number at a dotted path in any JSON document

Evidence, passed through to didrun (mix freely with the above):
  --expect REGEX          combined output must match
  --expect-count REGEX    first capture group is a count, >= --min
  --wrote PATH            the file must have been written during this run
  --took-at-least MS      a floor on the duration (weak; prefer a count)

Options:
  --min N                 the floor, applied to what EXECUTED (default 1)
  --min-KIND N            a floor for one kind only, e.g. --min-lcov 200
                          (--junit, --tap, --lcov, --cobertura, --eslint, --json)
  --allow-stale           do not require the report to be written by this run
  --expect-failure REGEX  when it fails, it must fail this way (else exit 4)
  --timeout SECONDS       kill the command and classify anyway
  --quiet                 only print on a bad verdict
  --json-out              print the result as JSON
  -h, --help

Exit: 0 ran and passed · 3 did not run · 4 failed the wrong way · 2 could not
      run · otherwise the command's own status.
`;

const FLAG_FOR = Object.fromEntries(
  KINDS.filter((k) => k !== "json").map((k) => [`--${k}`, k])
);
// A FLOOR PER KIND, because one number cannot mean two things. `--min 200` is sensible for
// `--lcov` and absurd for `--junit` in the same invocation, and the first version made you
// choose. `--min` remains the default for every kind that has no `--min-KIND`.
const MIN_FLAG_FOR = Object.fromEntries(KINDS.map((k) => [`--min-${k}`, k]));
// THE FLAGS THAT SWALLOW THE NEXT ARGUMENT. `-h` is only ours in FLAG POSITION: as the
// value of `--expect` it is a regex, as the value of `--junit` it is a path, and reading
// either as a request for help prints usage and returns 0 without running the command --
// the same gate-that-cannot-fail the `--` split closed, one argument further in.
const VALUED = new Set([
  ...Object.keys(FLAG_FOR),
  ...Object.keys(MIN_FLAG_FOR),
  "--json", "--expect", "--expect-stdout", "--expect-stderr", "--expect-count",
  "--wrote", "--took-at-least", "--min", "--expect-failure", "--timeout",
]);

/** Is `-h`/`--help` here as OUR flag, rather than as some other flag's value? */
function wantsUsage(ours) {
  for (let i = 0; i < ours.length; i += 1) {
    if (ours[i] === "-h" || ours[i] === "--help") return true;
    if (VALUED.has(ours[i])) i += 1;   // the next argument is a value, not a flag
  }
  return false;
}

function readMode(argv) {
  if (argv.length < 2) {
    process.stderr.write(
      "zerocase read: give a kind and a path, e.g. `zerocase read --junit reports/junit.xml`\n"
    );
    return 2;
  }
  // AND NOT ONE ARGUMENT MORE. Everything past `argv[1]` used to be dropped in silence,
  // which made `read --junit r.xml --min 4` a floor of 4 that enforced `> 0` — the exact
  // stale promise this package exists to catch, told about itself. Unquoted globs land
  // here too: the shell expands `reports/*.xml` into three arguments and only the first
  // was ever read. `read` takes ONE kind and ONE path; a floor belongs to the wrapper
  // form, which checks freshness and can therefore mean it.
  if (argv.length > 2) {
    process.stderr.write(
      `zerocase read: unexpected argument ${argv[2]} — read takes one kind and one path\n` +
        "               (quote a glob: --junit 'reports/*.xml'; --min applies to the\n" +
        "               wrapper form, which is the form that checks freshness)\n"
    );
    return 2;
  }
  const [flag, raw] = argv;
  let file = raw;
  let pointer = null;
  let kind;
  if (flag === "--json") {
    const at = raw.indexOf(":");
    if (at < 0) {
      process.stderr.write("zerocase read: --json takes PATH:dotted.path\n");
      return 2;
    }
    file = raw.slice(0, at);
    pointer = raw.slice(at + 1);
    kind = "json";
  } else if (flag in FLAG_FOR) {
    kind = FLAG_FOR[flag];
  } else {
    process.stderr.write(`zerocase read: unknown kind ${flag}\n`);
    return 2;
  }
  let t;
  try {
    t = rep.read(kind, file, pointer);
  } catch (err) {
    if (err instanceof ParseError) {
      process.stderr.write(`zerocase: could not read ${file} as ${kind}: ${err.message}\n`);
    } else {
      process.stderr.write(`zerocase: ${err.message}\n`);
    }
    return 2;
  }
  process.stdout.write(`${file}  [${kind}]\n`);
  process.stdout.write(
    `  ${t.executed} of ${t.total} ${t.unit} ${t.verb}` +
      (t.failed ? `; ${t.failed} ${t.failedLabel}` : "") +
      "\n"
  );
  if (t.note) process.stdout.write(`  note: ${t.note}\n`);
  process.stdout.write(
    "  (read does not check freshness — a stale report looks exactly like this)\n"
  );
  return t.executed > 0 ? 0 : 3;
}

export async function main(argv = process.argv.slice(2)) {
  const split = argv.indexOf("--");
  // ONLY THE ARGUMENTS BEFORE `--` ARE OURS. Scanning the whole of argv let a `-h` or a
  // `--help` belonging to the COMMAND UNDER TEST print zerocase's usage and return 0
  // without ever spawning it — a gate that cannot fail, which is the one thing this
  // package is for. `--help` needs a command that takes it; `-h` needs nothing unusual
  // at all, because `-h` is a hostname to `mysqldump`, `curl` and `ab`, so
  // `zerocase --json r.json:n --min 4 -- mysqldump -h db` reported clean forever.
  // `didrun` had the same scan and fixed it in 0.1.3; this is that fix, in its sibling.
  const ours = split < 0 ? argv : argv.slice(0, split);
  if (argv.length === 0 || wantsUsage(ours)) {
    process.stderr.write(USAGE);
    return argv.length === 0 ? 2 : 0;
  }
  if (argv[0] === "read") return readMode(argv.slice(1));
  if (split < 0) {
    process.stderr.write("zerocase: put the command after `--`\n");
    return 2;
  }
  const flags = argv.slice(0, split);
  const command = argv.slice(split + 1);
  if (command.length === 0) {
    process.stderr.write("zerocase: nothing to run after `--`\n");
    return 2;
  }

  const passthrough = [];
  const deferred = [];
  let expectFailure = null;
  let timeout;
  let min = 1;
  let quiet = false;
  let asJson = false;
  let allowStale = false;
  const perKind = {};

  // A MISSING VALUE IS COULD-NOT-RUN (2), NOT THE COMMAND'S OWN STATUS, and it is settled
  // HERE so that no predicate is built from half an argument list. `value()` used to throw
  // out of `main`: node printed an unhandled rejection and exited 1, the code reserved for
  // the wrapped command failing normally, so a CI file branching on didrun's table read a
  // zerocase usage error as a test failure. The walk is `wantsUsage`'s, over the same
  // table -- a flag that swallows the next argument needs one to swallow.
  for (let i = 0; i < flags.length; i += 1) {
    if (!VALUED.has(flags[i])) continue;
    if (i + 1 >= flags.length) {
      process.stderr.write(`zerocase: ${flags[i]} needs a value\n`);
      return 2;
    }
    i += 1;
  }
  for (let i = 0; i < flags.length; i += 1) {
    const flag = flags[i];
    const value = () => {
      i += 1;
      // Unreachable: the walk above proved every valued flag has one.
      if (i >= flags.length) throw new Error(`zerocase: ${flag} needs a value`);
      return flags[i];
    };
    if (flag in FLAG_FOR) deferred.push([FLAG_FOR[flag], value(), null]);
    else if (flag === "--json") {
      const raw = value();
      const at = raw.indexOf(":");
      if (at < 0) {
        process.stderr.write("zerocase: --json takes PATH:dotted.path\n");
        return 2;
      }
      deferred.push(["json", raw.slice(0, at), raw.slice(at + 1)]);
    } else if (flag === "--expect") passthrough.push(evidence.matches(value(), "output"));
    else if (flag === "--expect-stdout") passthrough.push(evidence.matches(value(), "stdout"));
    else if (flag === "--expect-stderr") passthrough.push(evidence.matches(value(), "stderr"));
    else if (flag === "--expect-count") deferred.push(["count", value(), null]);
    else if (flag === "--wrote") passthrough.push(evidence.wrote(value()));
    else if (flag === "--took-at-least") passthrough.push(evidence.tookAtLeast(Number(value())));
    else if (flag === "--min") min = Number.parseInt(value(), 10);
    else if (flag in MIN_FLAG_FOR) perKind[MIN_FLAG_FOR[flag]] = Number.parseInt(value(), 10);
    else if (flag === "--allow-stale") allowStale = true;
    else if (flag === "--expect-failure") expectFailure = value();
    else if (flag === "--timeout") timeout = Number(value()) * 1000;
    else if (flag === "--quiet") quiet = true;
    else if (flag === "--json-out") asJson = true;
    else {
      process.stderr.write(`zerocase: unknown option ${flag}\n`);
      return 2;
    }
  }

  // `--min`, `--min-KIND` and `--allow-stale` are applied after the loop, so they work
  // however they were ordered on the command line. `didrun` does the same with its own
  // `--min`, and for the same reason: a flag that means different things depending on
  // where you put it will be wrong in somebody's CI file, silently.
  const predicates = [...passthrough];
  for (const [kind, file, pointer] of deferred) {
    if (kind === "count") predicates.push(evidence.count(file, { min }));
    else {
      try {
        predicates.push(
          rep.report(kind, file, { min: perKind[kind] ?? min, allowStale, pointer })
        );
      } catch (err) {
        process.stderr.write(`zerocase: ${err.message}\n`);
        return 2;
      }
    }
  }

  if (predicates.length === 0) {
    process.stderr.write(
      "zerocase: name at least one report (--junit, --tap, --lcov, --cobertura,\n" +
        "          --eslint, --json) or one didrun predicate.\n" +
        "          Without one this can only report the exit code, which is the\n" +
        "          thing it exists to stop you trusting.\n"
    );
    return 2;
  }

  let result;
  try {
    // `inherit` streams the command's own output while it runs, exactly as the didrun
    // binary does. It is still captured, so the passthrough predicates see it.
    result = await run(command, {
      evidence: predicates, expectFailure, timeout, inherit: !asJson,
    });
  } catch (err) {
    process.stderr.write(`zerocase: cannot run '${command[0]}' (${err.message})\n`);
    return 2;
  }

  if (asJson) {
    process.stdout.write(
      JSON.stringify(
        {
          checks: result.checks,
          code: result.code,
          command: result.command,
          duration_ms: result.durationMs,
          killed: !!result.killed,
          // THE NUMBERS, not only the sentence about them. Something reading this wants
          // `executed` to put on a dashboard, and parsing it back out of the detail
          // string is how a downstream tool comes to depend on wording.
          reports: predicates.filter((p) => p.tally).map((p) => p.tally),
          state: result.state,
        },
        null,
        2
      ) + "\n"
    );
  } else if (!quiet || !result.ok) {
    process.stderr.write("\n[zerocase] " + report(result) + "\n");
  }
  return exitCodeFor(result);
}

Promise.resolve(main(process.argv.slice(2))).then((code) => {
  process.exitCode = code;
});
