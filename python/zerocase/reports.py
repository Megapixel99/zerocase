"""Evidence predicates that read the report the runner already wrote.

These are `didrun` predicates. Not "compatible with", not "shaped like" — they subclass
`didrun.evidence.Predicate` and are handed to `didrun.run()`, which does the running, the
four states, the exit codes and the timeout classification. None of that is reimplemented
here, and the reason is the one `canfail` gave when it deleted its inline `_Guard`: a
second copy of a guarantee is a second thing to get wrong, and the copy is the one that
does not get the upstream's tests.

WHAT IS ACTUALLY NEW IS TWO NUMBERS INSTEAD OF ONE.

    <testsuite tests="50" skipped="50">

is a green run of nothing wearing a total. `--expect-count "(\\d+) tests"` reads the
fifty and is satisfied, exactly as it would be by fifty tests that ran. So every parser
here returns `total` AND `executed`, and the floor applies to the second.

FRESHNESS IS NOT OPTIONAL BY DEFAULT. A `junit.xml` from yesterday parses beautifully and
says four hundred tests passed; a runner that never started leaves it exactly where it
was. The single-path case delegates to `didrun.evidence.Wrote` rather than restating it,
so "a stale artefact from an earlier run looks exactly like this" is one sentence in one
package.

AND IT IS PER FILE, NOT PER PATTERN. A glob is asked which of its matches THIS run wrote,
and only those are summed. Asking whether anything under `reports/*.xml` changed and then
counting everything under `reports/*.xml` lets a run that is over carry the floor for the
run in front of you, which is this package's own thesis pointed the wrong way.
"""

from __future__ import annotations

import glob as globmod
import hashlib
import os

from didrun.evidence import Check, Predicate, Wrote

from . import parse as parsers
from .parse import ParseError

GLOB_CHARS = "*?["


def _stat(path):
    """Size, mtime and digest — the three things `didrun.evidence.Wrote` compares.

    The same three, deliberately: a runner that writes a byte-identical report DID run,
    and `Wrote` says so by looking at the mtime when the digest matches. A glob branch
    that compared digests alone called that same run stale, so the two paths disagreed
    about one file depending on whether the pattern had a `*` in it.
    """
    try:
        st = os.stat(path)
        with open(path, "rb") as fh:
            data = fh.read()
        return {"size": st.st_size, "mtime": st.st_mtime,
                "digest": hashlib.sha256(data).hexdigest()}
    except OSError:
        return None


def _is_fresh(now, was):
    """Did THIS run touch this one file? The rule `Wrote` uses, per matched path."""
    if now is None:
        return False        # it matched the pattern and then could not be read
    if was is None:
        return True         # it was not there before the run
    if now["digest"] != was["digest"]:
        return True
    return now["mtime"] > was["mtime"]      # rewritten with the same content


class _GlobFreshness:
    """The freshness rule for a pattern that matches a SET of files.

    `didrun.evidence.Wrote` answers this for one path, and one path is the common case,
    so that branch is delegated rather than restated. A pattern cannot be: the files may
    not exist yet when `before()` runs, which is the ordinary case for a report the
    command is about to write. The rule generalises the same way — a matched file
    appeared, or one that was already there changed.

    IT ANSWERS PER FILE AND NOT ONLY FOR THE SET. Asking "did anything here change?" and
    then summing everything the pattern matched is how the count of a run that is over
    gets added to the count of the run in front of you.
    """

    def __init__(self, pattern):
        self.pattern = pattern

    def snapshot(self):
        return {p: _stat(p) for p in sorted(globmod.glob(self.pattern))}

    def check(self, before):
        """-> (ok, detail, the files this run wrote, the files it did not).

        The last two are the point. `zerocase 0.1.1` returned a verdict for the set and
        let the caller sum every match, so a second run into a directory nobody cleaned
        was carried by the first: `unittest-xml-reporting` names its files
        `TEST-<Class>-<timestamp>.xml`, which never collide, so run two ADDED six files
        to run one's six and reported `42 of 42 tests ran (floor 20)` for a run that
        collected a single test. A green run of nothing wearing somebody else's total is
        the exact shape this package exists to report, and it was doing it.
        """
        after = self.snapshot()
        if not after:
            return False, (f"{self.pattern} matched no files"
                           + (" — and it matched %d before the run" % len(before)
                              if before else "")), [], []
        fresh = [p for p in after if _is_fresh(after[p], before.get(p))]
        ignored = [p for p in after if p not in fresh]
        if not fresh:
            return False, (f"every file matching {self.pattern} is byte for byte what it "
                           f"was before the run — a stale artefact from an earlier run "
                           f"looks exactly like this"), [], ignored
        appeared = [p for p in fresh if p not in before]
        if appeared:
            return True, f"{len(appeared)} file(s) appeared, first {appeared[0]}", fresh, ignored
        return True, f"{len(fresh)} file(s) changed", fresh, ignored


class Report(Predicate):
    """One report file (or glob), parsed, with a floor on what actually happened."""

    def __init__(self, kind, path, minimum=1, allow_stale=False, json_path=None):
        if minimum < 1:
            # A floor of zero is satisfied by a zero, which is the state this package
            # exists to report. Refusing beats accepting an argument that turns the tool
            # into an expensive no-op somebody will read as coverage.
            raise ValueError(
                "minimum must be at least 1; a floor of 0 is satisfied by the empty "
                "report this predicate exists to catch"
            )
        self.kind = kind
        self.path = path
        self.minimum = minimum
        self.json_path = json_path
        self.allow_stale = allow_stale
        self.name = (f"{path} reports at least {minimum} "
                     f"{parsers.UNITS[kind]} that {parsers.VERBS[kind]}")
        self.is_glob = any(c in path for c in GLOB_CHARS)
        self.tally = None
        if allow_stale:
            self.freshness = None
        else:
            self.freshness = _GlobFreshness(path) if self.is_glob else Wrote(path)

    # -- the predicate protocol ------------------------------------------------
    def before(self):
        if self.freshness is None:
            return None
        return (self.freshness.snapshot() if self.is_glob else self.freshness.before())

    def check(self, result, before):
        # THE FILES THIS RUN WROTE, not every file the pattern matched. A glob whose
        # freshness is enforced tallies only what came out of the command in front of it;
        # anything left over from an earlier run is named in the detail and left out of
        # the sum. `--allow-stale` is the one way to add them back, which is what it says.
        paths, ignored = None, []
        if self.freshness is not None:
            if self.is_glob:
                ok, detail, paths, ignored = self.freshness.check(before)
                if not ok:
                    return Check(self.name, False, detail)
            else:
                fresh = self.freshness.check(result, before)
                if not fresh.satisfied:
                    return Check(self.name, False, fresh.detail)

        if paths is None:
            paths = sorted(globmod.glob(self.path)) if self.is_glob else [self.path]
        if not paths:
            return Check(self.name, False, f"{self.path} matched no files")

        total = executed = failed = 0
        notes = []
        for path in paths:
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError as exc:
                return Check(self.name, False, f"{path} could not be read: {exc}")
            try:
                if self.kind == "json":
                    tally = parsers.json_at(text, self.json_path)
                else:
                    tally = parsers.parse(self.kind, text)
            except ParseError as exc:
                # NEVER A ZERO AND NEVER A PASS. An unreadable report is a third answer,
                # and collapsing it into either of the other two is how a tool teaches
                # people to ignore it.
                return Check(self.name, False,
                             f"could not read {path} as {self.kind}: {exc} — an "
                             f"unreadable report is not a zero, and it is not a pass")
            total += tally.total
            executed += tally.executed
            failed += tally.failed
            if tally.note:
                notes.append(f"{path}: {tally.note}")

        satisfied, detail = verdict(self.kind, total, executed, self.minimum)
        if len(paths) > 1:
            detail += f" — across {len(paths)} files"
        if ignored:
            # SAID OUT LOUD, because a number that quietly got smaller is the thing this
            # package objects to. A reader who expected the leftovers counted needs to be
            # told they were not, and told which ones.
            detail += (f"; {len(ignored)} stale file(s) this run did not write, left out "
                       f"of the count, first {ignored[0]}")
        if failed:
            # INFORMATIONAL, NEVER A VERDICT. Whether a suite failed is the exit code's
            # business and `didrun` already reads it. This is here so that a reader
            # looking at "4 of 4 tests ran" and wondering how it went does not have to
            # open the file.
            detail += f"; {failed} {parsers.FAILED_LABELS[self.kind]}"
        for note in notes:
            detail += f"; {note}"
        # Kept so `--json-out` can report the numbers rather than only the sentence about
        # them. One run, one predicate, one tally.
        self.tally = {"kind": self.kind, "path": self.path, "files": len(paths),
                      "stale": len(ignored), "total": total, "executed": executed,
                      "failed": failed, "minimum": self.minimum}
        return Check(self.name, satisfied, detail)


def verdict(kind, total, executed, minimum):
    """The four sentences. Shared word for word with `js/src/reports.js`.

    Kept in one function in each half rather than inline at four call sites, because the
    parity suite can then assert the strings themselves — and the strings are what a
    person reads at 2am when CI has gone red.
    """
    unit, verb = parsers.UNITS[kind], parsers.VERBS[kind]
    if executed >= minimum:
        return True, f"{executed} of {total} {unit} {verb} (floor {minimum})"
    if total == 0:
        return False, (f"0 {unit} in the report — the denominator is zero, so there was "
                       f"nothing here this check could have objected to")
    if executed == 0:
        return False, (f"0 of {total} {unit} {verb} — the report is not empty, and "
                       f"nothing in it happened")
    return False, (f"{executed} of {total} {unit} {verb}, below the floor of {minimum}")


# Short constructors, so a caller writes `reports.junit(...)` in either language.
def junit(path, minimum=1, allow_stale=False):
    return Report("junit", path, minimum, allow_stale)


def tap(path, minimum=1, allow_stale=False):
    return Report("tap", path, minimum, allow_stale)


def lcov(path, minimum=1, allow_stale=False):
    return Report("lcov", path, minimum, allow_stale)


def cobertura(path, minimum=1, allow_stale=False):
    return Report("cobertura", path, minimum, allow_stale)


def eslint(path, minimum=1, allow_stale=False):
    return Report("eslint", path, minimum, allow_stale)


def json_at(path, pointer, minimum=1, allow_stale=False):
    return Report("json", path, minimum, allow_stale, json_path=pointer)


def read(kind, path, json_path=None):
    """Parse a report that is already on disk and return its `Tally`.

    A glob is summed, the same way the predicate sums one — five reports and one report
    are not the same result, and a `read` that silently took the first would say they
    were.

    NO FRESHNESS CHECK HAPPENS HERE, and that is the point of it existing separately: a
    stale report reads identically to a fresh one, which is the whole reason `run` takes
    a command instead of a filename. Use this to see what a parser makes of a file, not
    to gate a build.
    """
    paths = sorted(globmod.glob(path)) if any(c in path for c in GLOB_CHARS) else [path]
    if not paths:
        raise OSError(f"{path} matched no files")
    total = executed = failed = 0
    notes = []
    kinds = set()
    for one in paths:
        with open(one, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        tally = (parsers.json_at(text, json_path) if kind == "json"
                 else parsers.parse(kind, text))
        total += tally.total
        executed += tally.executed
        failed += tally.failed
        kinds.add(tally.kind)
        if tally.note:
            notes.append(f"{one}: {tally.note}" if len(paths) > 1 else tally.note)
    return parsers.Tally(kind, total, executed, "; ".join(notes), failed)


__all__ = ["Report", "verdict", "read", "junit", "tap", "lcov", "cobertura", "eslint",
           "json_at", "ParseError"]
