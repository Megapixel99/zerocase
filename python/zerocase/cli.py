r"""`zerocase` — the runner already wrote the number down. Read it.

    zerocase --junit reports/junit.xml -- pytest tests/
    zerocase --lcov coverage/lcov.info --min 50 -- npm run coverage
    zerocase --eslint out.json -- npx eslint src --format json -o out.json
    zerocase read --junit reports/junit.xml

Exit codes are `didrun`'s, unchanged: 0 ran and passed · 3 DID NOT RUN · 4 failed the
wrong way · 2 this tool could not run at all · otherwise the command's own status. A CI
file that already branches on `didrun` does not have to learn a second table.
"""

from __future__ import annotations

import json
import sys

from didrun import evidence as ev
from didrun import exit_code_for, report, run

from . import reports as rep
from .parse import KINDS, ParseError

USAGE = """zerocase — a check with a zero denominator reports clean.

  zerocase [reports...] [evidence...] [options] -- COMMAND...
  zerocase read --KIND PATH

Reports (each may be repeated, and each may be a glob):
  --junit PATH        JUnit/xUnit XML — <testcase> elements, minus the skipped
  --tap PATH          TAP — the `1..N` plan, minus `# SKIP`
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
"""

FLAG_FOR = {f"--{kind}": kind for kind in KINDS if kind != "json"}
# A FLOOR PER KIND, because one number cannot mean two things. `--min 200` is sensible for
# `--lcov` and absurd for `--junit` in the same invocation, and the first version made you
# choose. `--min` remains the default for every kind that has no `--min-KIND`.
MIN_FLAG_FOR = {f"--min-{kind}": kind for kind in KINDS}


def _read_mode(argv):
    """`zerocase read --junit path` — parse a file that is already on disk.

    Separate from the gate, and named so, because it does NOT check freshness: a stale
    report reads identically to a fresh one, which is the entire reason the gate takes a
    command instead of a filename.
    """
    if len(argv) < 2:
        sys.stderr.write("zerocase read: give a kind and a path, e.g. "
                         "`zerocase read --junit reports/junit.xml`\n")
        return 2
    # AND NOT ONE ARGUMENT MORE. Everything past `argv[1]` used to be dropped in silence,
    # which made `read --junit r.xml --min 4` a floor of 4 that enforced `> 0` — the exact
    # stale promise this package exists to catch, told about itself. Unquoted globs land
    # here too: the shell expands `reports/*.xml` into three arguments and only the first
    # was ever read. `read` takes ONE kind and ONE path; a floor belongs to the wrapper
    # form, which checks freshness and can therefore mean it.
    if len(argv) > 2:
        sys.stderr.write(f"zerocase read: unexpected argument {argv[2]} — read takes "
                         "one kind and one path\n"
                         "               (quote a glob: --junit 'reports/*.xml'; "
                         "--min applies to the\n"
                         "               wrapper form, which is the form that checks "
                         "freshness)\n")
        return 2
    flag, path = argv[0], argv[1]
    pointer = None
    if flag == "--json":
        path, _, pointer = path.partition(":")
        if not pointer:
            sys.stderr.write("zerocase read: --json takes PATH:dotted.path\n")
            return 2
        kind = "json"
    elif flag in FLAG_FOR:
        kind = FLAG_FOR[flag]
    else:
        sys.stderr.write(f"zerocase read: unknown kind {flag}\n")
        return 2
    try:
        tally = rep.read(kind, path, pointer)
    except ParseError as exc:
        sys.stderr.write(f"zerocase: could not read {path} as {kind}: {exc}\n")
        return 2
    except OSError as exc:
        sys.stderr.write(f"zerocase: {exc}\n")
        return 2
    print(f"{path}  [{kind}]")
    line = f"  {tally.executed} of {tally.total} {tally.unit} {tally.verb}"
    if tally.failed:
        line += f"; {tally.failed} {tally.failed_label}"
    print(line)
    if tally.note:
        print(f"  note: {tally.note}")
    print("  (read does not check freshness — a stale report looks exactly like this)")
    return 0 if tally.executed > 0 else 3


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    split = argv.index("--") if "--" in argv else -1
    # ONLY THE ARGUMENTS BEFORE `--` ARE OURS. Scanning the whole of argv let a `-h` or a
    # `--help` belonging to the COMMAND UNDER TEST print zerocase's usage and return 0
    # without ever spawning it — a gate that cannot fail, which is the one thing this
    # package is for. `--help` needs a command that takes it; `-h` needs nothing unusual
    # at all, because `-h` is a hostname to `mysqldump`, `curl` and `ab`, so
    # `zerocase --json r.json:n --min 4 -- mysqldump -h db` reported clean forever.
    # `didrun` had the same scan and fixed it in 0.1.3; this is that fix, in its sibling.
    ours = argv if split < 0 else argv[:split]
    if not argv or "-h" in ours or "--help" in ours:
        sys.stderr.write(USAGE)
        return 0 if argv else 2
    if argv[0] == "read":
        return _read_mode(argv[1:])
    if split < 0:
        sys.stderr.write("zerocase: put the command after `--`\n")
        return 2
    flags, command = argv[:split], argv[split + 1:]
    if not command:
        sys.stderr.write("zerocase: nothing to run after `--`\n")
        return 2

    passthrough, deferred = [], []
    expect_failure = timeout = None
    minimum, quiet, as_json, allow_stale = 1, False, False, False
    per_kind = {}

    i = 0
    while i < len(flags):
        flag = flags[i]

        def value():
            nonlocal i
            i += 1
            if i >= len(flags):
                raise SystemExit(f"zerocase: {flag} needs a value")
            return flags[i]

        if flag in FLAG_FOR:
            deferred.append((FLAG_FOR[flag], value(), None))
        elif flag == "--json":
            raw = value()
            path, _, pointer = raw.partition(":")
            if not pointer:
                sys.stderr.write("zerocase: --json takes PATH:dotted.path\n")
                return 2
            deferred.append(("json", path, pointer))
        elif flag == "--expect":
            passthrough.append(ev.matches(value(), "output"))
        elif flag == "--expect-stdout":
            passthrough.append(ev.matches(value(), "stdout"))
        elif flag == "--expect-stderr":
            passthrough.append(ev.matches(value(), "stderr"))
        elif flag == "--expect-count":
            deferred.append(("count", value(), None))
        elif flag == "--wrote":
            passthrough.append(ev.wrote(value()))
        elif flag == "--took-at-least":
            passthrough.append(ev.took_at_least(int(value())))
        elif flag == "--min":
            minimum = int(value())
        elif flag in MIN_FLAG_FOR:
            per_kind[MIN_FLAG_FOR[flag]] = int(value())
        elif flag == "--allow-stale":
            allow_stale = True
        elif flag == "--expect-failure":
            expect_failure = value()
        elif flag == "--timeout":
            timeout = float(value())
        elif flag == "--quiet":
            quiet = True
        elif flag == "--json-out":
            as_json = True
        else:
            sys.stderr.write(f"zerocase: unknown option {flag}\n")
            return 2
        i += 1

    # `--min`, `--min-KIND` and `--allow-stale` are applied after the loop, so they work
    # however they were ordered on the command line. `didrun` does the same with its own
    # `--min`, and for the same reason: a flag that means different things depending on
    # where you put it will be wrong in somebody's CI file, silently.
    predicates = list(passthrough)
    for kind, path, pointer in deferred:
        if kind == "count":
            predicates.append(ev.count(path, minimum=minimum))
        else:
            try:
                predicates.append(rep.Report(kind, path,
                                             minimum=per_kind.get(kind, minimum),
                                             allow_stale=allow_stale, json_path=pointer))
            except ValueError as exc:
                sys.stderr.write(f"zerocase: {exc}\n")
                return 2

    if not predicates:
        sys.stderr.write(
            "zerocase: name at least one report (--junit, --tap, --lcov, --cobertura,\n"
            "          --eslint, --json) or one didrun predicate.\n"
            "          Without one this can only report the exit code, which is the\n"
            "          thing it exists to stop you trusting.\n"
        )
        return 2

    try:
        result = run(command, evidence=predicates, expect_failure=expect_failure,
                     timeout=timeout)
    except OSError as exc:
        sys.stderr.write(f"zerocase: cannot run {command[0]!r} ({exc})\n")
        return 2

    if as_json:
        json.dump({
            "command": result.command,
            "state": result.state,
            "code": result.code,
            "duration_ms": result.duration_ms,
            "killed": result.killed,
            "checks": [{"name": c.name, "satisfied": c.satisfied,
                        "detail": c.detail, "weak": c.weak} for c in result.checks],
            # THE NUMBERS, not only the sentence about them. Something reading this wants
            # `executed` to put on a dashboard, and parsing it back out of the detail
            # string is how a downstream tool comes to depend on wording.
            "reports": [p.tally for p in predicates
                        if isinstance(p, rep.Report) and p.tally],
        }, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if not quiet or not result.ok:
            sys.stderr.write("\n[zerocase] " + report(result) + "\n")
    return exit_code_for(result)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
