"""The parsers: a report file in, a `Tally` out, or a stated reason it could not be read.

THE ONE CLAIM THIS PACKAGE MAKES: **a check with a zero denominator reports clean.** A
suite that collected nothing, a lint whose glob matched nothing, a coverage run over no
statements — every one of them exits 0, and every one of them has a field that says `0`
in a document it already wrote.

`didrun` asks the same question of a command's stdout, with a regex you supply. This
half of the work is what its README declines to do: *"It does not parse junit/TAP."* A
regex over stdout is a claim about a runner's human-facing text, which changes between
minor versions and moves with the locale; `junit.xml` has the number in a field with a
name.

THREE ANSWERS, NEVER TWO. A report can be read and hold a number, or be read and hold a
zero, or not be readable at all — and the third must not collapse into either of the
others. An unparseable report is not a zero (that would fail runs for the wrong reason
and teach people to ignore this) and it is certainly not a pass. `ParseError` carries the
reason to the surface so the message names the file and the problem.

COUNT THE ELEMENTS, NOT THE ATTRIBUTES, WHEREVER BOTH EXIST. `<testsuite tests="47">`
is a claim the writer made; forty-seven `<testcase>` elements are the thing itself. They
disagree more often than anybody expects — a suite that crashed halfway leaves a header
from one run and a body from another — and when they disagree this reports the elements
and says the attribute differed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# The vocabulary. Shared with `js/src/parse.js` and asserted by the parity suite: a CI
# file that moves between the halves must not change meaning, and a `unit` or a `verb`
# that differs between them changes what the report SAYS while both agree on the number.
KINDS = ("junit", "tap", "lcov", "cobertura", "eslint", "json")
UNITS = {"junit": "tests", "tap": "tests", "lcov": "lines",
         "cobertura": "lines", "eslint": "files", "json": "items"}
VERBS = {"junit": "ran", "tap": "ran", "lcov": "were covered",
         "cobertura": "were covered", "eslint": "were linted", "json": "counted"}
# What a non-zero `failed` count is called for each kind. INFORMATIONAL AND NEVER A
# VERDICT: whether a suite failed is the exit code's business and `didrun` already reads
# it. What this adds is that a reader looking at "4 of 4 tests ran" and wondering how it
# went does not have to open the file. `lcov`, `cobertura` and `json` have no notion of a
# failure and always report zero.
FAILED_LABELS = {"junit": "failed", "tap": "failed", "eslint": "with problems",
                 "lcov": "failed", "cobertura": "failed", "json": "failed"}


class ParseError(Exception):
    """The report could not be read. Never silently a zero, never silently a pass."""


@dataclass
class Tally:
    """What one report says about its own denominator.

    `total` is what the report contains; `executed` is how much of it actually happened.
    THE FLOOR APPLIES TO `executed`, AND THAT IS THE WHOLE POINT OF HAVING TWO NUMBERS.
    A suite where every test is skipped writes `tests="50"`, and it is exactly as
    vacuous as one that wrote `tests="0"` — a counter that read only the total would
    call it fifty tests and be satisfied.
    """

    kind: str
    total: int
    executed: int
    note: str = ""
    failed: int = 0

    @property
    def unit(self):
        return UNITS[self.kind]

    @property
    def verb(self):
        return VERBS[self.kind]

    @property
    def failed_label(self):
        return FAILED_LABELS[self.kind]

    def as_dict(self):
        return {"kind": self.kind, "total": self.total, "executed": self.executed,
                "unit": self.unit, "verb": self.verb, "note": self.note,
                "failed": self.failed}


# --------------------------------------------------------------------------- junit

# Comments and CDATA are stripped before anything is scanned. A failure message
# containing the text `<testcase>` is ordinary — assertion output quotes XML all the
# time — and a scanner that counted it would report tests that do not exist.
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_CDATA = re.compile(r"<!\[CDATA\[.*?\]\]>", re.S)


def _strip(text):
    return _CDATA.sub("", _COMMENT.sub("", text))


# A tag ends at the first `>` OUTSIDE a quoted attribute value, which is why the
# attribute span consumes quoted runs whole rather than scanning to the next `>`. XML
# requires `<` and `&` to be escaped and leaves `>` alone, so a test named
# `--at <file>:<line>` is written `name="--at &lt;file>:&lt;line>"` and is well-formed.
# Stopping at that `>` drops the `/` of a self-closing `<testcase/>`; the case is then
# read as still open, the next one silently replaces it, and a test goes missing.
_TAG = re.compile(r"""<\s*(/?)\s*(testcase|skipped|failure|error)\b"""
                  r"""((?:"[^"]*"|'[^']*'|[^>"'])*?)(/?)\s*>""", re.I | re.S)
_SUITE_ATTR = re.compile(r"""<\s*testsuite\b((?:"[^"]*"|'[^']*'|[^>"'])*?)/?\s*>""",
                         re.I | re.S)
_ATTR = re.compile(r"([\w:.-]+)\s*=\s*\"([^\"]*)\"|([\w:.-]+)\s*=\s*'([^']*)'")


def _attrs(blob):
    out = {}
    for m in _ATTR.finditer(blob or ""):
        key = m.group(1) or m.group(3)
        out[key.lower()] = m.group(2) if m.group(1) else m.group(4)
    return out


def junit(text):
    """JUnit / xUnit XML: `<testcase>` elements, and which of them are `<skipped/>`.

    Deliberately NOT `xml.etree`, though the standard library has it and the standard
    library is correct. The JavaScript half has no XML parser in its own standard
    library, so using one here would put the two halves on different engines and make
    every disagreement between them a question about two parsers rather than about one
    report. The same scanner runs in both, and the parity suite compares them on the
    same files — including a comment and a CDATA block that each contain a fake
    `<testcase>`.
    """
    body = _strip(text)
    total = 0
    executed = 0
    failed = 0
    open_case = False
    case_skipped = False
    case_failed = False
    for m in _TAG.finditer(body):
        closing, name, blob, self_closing = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if name == "testcase":
            if closing:
                if open_case:
                    executed += 0 if case_skipped else 1
                    failed += 1 if case_failed and not case_skipped else 0
                    open_case = False
                continue
            total += 1
            if self_closing:
                executed += 1          # a self-closed testcase holds no `<skipped/>`
            else:
                open_case, case_skipped, case_failed = True, False, False
        elif not closing and open_case:
            if name == "skipped":
                case_skipped = True
            else:                       # `<failure>` or `<error>`, counted once per case
                case_failed = True
    if open_case:                       # unterminated `<testcase>`; the file is truncated
        executed += 0 if case_skipped else 1
        failed += 1 if case_failed and not case_skipped else 0

    claimed = 0
    seen_attr = False
    for m in _SUITE_ATTR.finditer(body):
        attrs = _attrs(m.group(1))
        if "tests" in attrs:
            seen_attr = True
            try:
                claimed += int(attrs["tests"])
            except ValueError:
                seen_attr = False
                break
    if total == 0 and not seen_attr and "<testsuite" not in body.lower():
        raise ParseError("no <testsuite> or <testcase> elements — this is not a JUnit report")

    note = ""
    if seen_attr and claimed != total:
        note = (f"the file claims tests=\"{claimed}\" in its <testsuite> attributes and "
                f"contains {total} <testcase> elements; the elements are what is counted")
    return Tally("junit", total, executed, note, failed)


# ----------------------------------------------------------------------------- tap

_PLAN = re.compile(r"^[ \t]*1\.\.(\d+)[ \t]*(?:#[ \t]*(.*))?$", re.M)
_TEST = re.compile(r"^[ \t]*(not[ \t]+ok|ok)\b(.*)$", re.M | re.I)
_SKIP = re.compile(r"#\s*(skip|todo)\b", re.I)


def tap(text):
    """TAP: the plan line if there is one, and the `ok` / `not ok` lines either way.

    `1..0` is TAP's own way of saying a run produced nothing, and it is conventionally
    accompanied by `# SKIP` and an exit code of zero. That combination is the entire
    subject of this package, spelled out by the protocol itself.
    """
    lines = [m for m in _TEST.finditer(text)]
    ran = sum(0 if _SKIP.search(m.group(2) or "") else 1 for m in lines)
    plan = _PLAN.search(text)
    if plan is None and not lines:
        raise ParseError("no TAP plan (`1..N`) and no `ok` / `not ok` lines")
    total = int(plan.group(1)) if plan else len(lines)
    failed = sum(1 for m in lines
                 if m.group(1).lower().startswith("not")
                 and not _SKIP.search(m.group(2) or ""))
    note = ""
    if plan and len(lines) != total:
        note = (f"the plan says {total} and {len(lines)} result lines are present; "
                f"the plan is what is counted")
    return Tally("tap", total, min(ran, total) if plan else ran, note, failed)


# ---------------------------------------------------------------------------- lcov

_LF = re.compile(r"^LF:\s*(\d+)\s*$", re.M)
_LH = re.compile(r"^LH:\s*(\d+)\s*$", re.M)


def lcov(text):
    """LCOV: `LF:` lines found, `LH:` lines hit, summed over every record.

    Both zeros matter and they are different failures. `LF:0` is an instrumenter that
    found nothing to instrument — the empty glob, one layer down. `LH:0` over a real
    `LF` is a suite that ran no code, which a coverage threshold of "0%" happily
    accepts because zero is not less than zero.
    """
    found = [int(m.group(1)) for m in _LF.finditer(text)]
    hit = [int(m.group(1)) for m in _LH.finditer(text)]
    if not found and not hit:
        raise ParseError("no `LF:` or `LH:` records — this is not an LCOV trace file")
    return Tally("lcov", sum(found), sum(hit))


# ----------------------------------------------------------------------- cobertura

_COVERAGE = re.compile(r"<\s*coverage\b([^>]*?)/?\s*>", re.I | re.S)
_LINE_EL = re.compile(r"<\s*line\b([^>]*?)/?\s*>", re.I | re.S)


def cobertura(text):
    """Cobertura XML: `lines-valid` / `lines-covered`, with the elements as the check."""
    body = _strip(text)
    root = _COVERAGE.search(body)
    if not root:
        raise ParseError("no <coverage> element — this is not a Cobertura report")
    attrs = _attrs(root.group(1))
    elements = [_attrs(m.group(1)) for m in _LINE_EL.finditer(body)]
    hits = 0
    for el in elements:
        try:
            hits += 1 if int(el.get("hits", "0")) > 0 else 0
        except ValueError:
            pass
    if "lines-valid" in attrs:
        try:
            total = int(attrs["lines-valid"])
            covered = int(attrs.get("lines-covered", hits))
        except ValueError:
            raise ParseError("<coverage> has a non-numeric lines-valid or lines-covered")
        note = ""
        if elements and total != len(elements):
            note = (f"the header claims lines-valid=\"{total}\" and the body holds "
                    f"{len(elements)} <line> elements")
        return Tally("cobertura", total, covered, note)
    if not elements:
        raise ParseError("<coverage> has no lines-valid attribute and no <line> elements")
    return Tally("cobertura", len(elements), hits)


# -------------------------------------------------------------------------- eslint

def eslint(text):
    """ESLint's JSON formatter: one entry per file it actually looked at.

    THE EMPTY GLOB IS `[]`. `npx eslint 'src/**/*.ts'` on a repository whose sources
    moved to `lib/` prints two characters, exits 0, and is indistinguishable in CI from
    a clean lint of four hundred files.
    """
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ParseError(f"not valid JSON: {exc}")
    if not isinstance(data, list):
        raise ParseError("the ESLint JSON formatter emits a list of file results; "
                         f"this is a {type(data).__name__}")
    files = [d for d in data if isinstance(d, dict) and "filePath" in d]
    if data and not files:
        raise ParseError("the entries have no `filePath` — this is not ESLint JSON")
    problems = sum(1 for d in files
                   if (d.get("errorCount") or 0) or (d.get("warningCount") or 0))
    return Tally("eslint", len(data), len(files), "", problems)


# ---------------------------------------------------------------------------- json

def json_at(text, path):
    """A number at a dotted path in any JSON document. The escape hatch, and it is one.

    Every parser above encodes what a format calls its denominator. This one makes you
    say it, which is worse documentation and better than not being able to ask.
    """
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ParseError(f"not valid JSON: {exc}")
    cursor = data
    walked = []
    for part in path.split("."):
        walked.append(part)
        if isinstance(cursor, list):
            try:
                cursor = cursor[int(part)]
                continue
            except (ValueError, IndexError):
                raise ParseError(f"`{'.'.join(walked)}` is not an index into a list of "
                                 f"{len(cursor)}")
        if not isinstance(cursor, dict) or part not in cursor:
            raise ParseError(f"`{'.'.join(walked)}` is not present in the document")
        cursor = cursor[part]
    if isinstance(cursor, bool) or not isinstance(cursor, (int, float)):
        raise ParseError(f"`{path}` is {json.dumps(cursor)[:40]}, which is not a number")
    return Tally("json", int(cursor), int(cursor), f"read from `{path}`")


PARSERS = {"junit": junit, "tap": tap, "lcov": lcov, "cobertura": cobertura,
           "eslint": eslint}


def parse(kind, text, path=None):
    """Dispatch by kind. `json` is not here because it needs a second argument."""
    if kind not in PARSERS:
        raise ParseError(f"no parser named {kind!r}")
    return PARSERS[kind](text)
