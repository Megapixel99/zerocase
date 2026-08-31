"""The two halves agree about the numbers AND about the sentences.

A CI file that moves from `pip install zerocase` to `npm install zerocase` must not
change meaning. Agreeing on `satisfied` is the cheap half of that: two halves can both
call a report empty and describe it differently, and the description is what somebody
reads at 2am when the build has gone red. So the strings are compared too, character for
character.

THE TABLE LIVES HERE AND NOWHERE ELSE. It is sent to the JavaScript half over stdin
rather than kept in a second copy beside it — a parity suite whose two sides maintain
their own input lists drifts by being asked different questions, and then reports
agreement about that.

The suite SKIPS when `node` is absent, so a Python-only contributor can run everything
else. CI asserts it was not skipped: a skip and a pass are identical in a tally, which is
the thing `didrun` — this package's one dependency — exists to say.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FIXTURES = os.path.join(ROOT, "fixtures")
DUMP = os.path.join(ROOT, "js", "test", "dump.mjs")

import sys
sys.path.insert(0, os.path.join(ROOT, "python"))

from zerocase import parse as parsers          # noqa: E402
from zerocase.reports import verdict           # noqa: E402

# (kind, fixture, json pointer). Every fixture in the directory appears here, and
# `test_every_fixture_is_in_the_table` asserts it — a fixture nothing compares is a
# fixture that proves nothing, and it looks exactly like one that does.
TALLIES = [
    ("junit", "junit-empty.xml", None),
    ("junit", "junit-all-skipped.xml", None),
    ("junit", "junit-real.xml", None),
    ("junit", "junit-lying-header.xml", None),
    ("junit", "junit-comment-trap.xml", None),
    ("junit", "junit-skipped-with-failure.xml", None),
    ("junit", "junit-not.xml", None),
    ("tap", "tap-zero.tap", None),
    ("tap", "tap-real.tap", None),
    ("lcov", "lcov-nohits.info", None),
    ("lcov", "lcov-real.info", None),
    ("cobertura", "cobertura-empty.xml", None),
    ("cobertura", "cobertura-real.xml", None),
    ("eslint", "eslint-empty.json", None),
    ("eslint", "eslint-real.json", None),
    ("json", "summary.json", "summary.total"),
    ("json", "summary.json", "empty.total"),
    ("json", "summary.json", "summary.label"),
    ("json", "summary.json", "summary.missing"),
]

# The four sentences, and the boundaries between them.
VERDICTS = [
    ("junit", 0, 0, 1),
    ("junit", 3, 0, 1),
    ("junit", 4, 3, 1),
    ("junit", 4, 3, 4),
    ("lcov", 0, 0, 1),
    ("lcov", 32, 22, 1),
    ("lcov", 32, 22, 30),
    ("eslint", 0, 0, 1),
    ("eslint", 2, 2, 1),
    ("tap", 3, 2, 1),
    ("cobertura", 4, 3, 1),
    ("json", 12, 12, 1),
]

node = shutil.which("node")


def _python_side():
    tallies = []
    for kind, name, pointer in TALLIES:
        path = os.path.join(FIXTURES, name)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            tallies.append({"error": f"unreadable: {exc}"})
            continue
        try:
            tally = (parsers.json_at(text, pointer) if kind == "json"
                     else parsers.parse(kind, text))
            tallies.append(tally.as_dict())
        except parsers.ParseError as exc:
            tallies.append({"error": str(exc)})
    verdicts = []
    for kind, total, executed, minimum in VERDICTS:
        satisfied, detail = verdict(kind, total, executed, minimum)
        verdicts.append({"satisfied": satisfied, "detail": detail})
    return {"tallies": tallies, "verdicts": verdicts}


def _javascript_side():
    payload = {
        "tallies": [[k, os.path.join(FIXTURES, n), p] for k, n, p in TALLIES],
        "verdicts": [list(v) for v in VERDICTS],
    }
    out = subprocess.run([node, DUMP], input=json.dumps(payload), text=True,
                         capture_output=True, cwd=ROOT)
    if out.returncode != 0:
        raise AssertionError(f"the JavaScript half exited {out.returncode}:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(node, "node is not on PATH")
class TheHalvesAgree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.py = _python_side()
        cls.js = _javascript_side()

    def test_every_fixture_parses_to_the_same_tally(self):
        for (kind, name, pointer), mine, theirs in zip(TALLIES, self.py["tallies"],
                                                       self.js["tallies"]):
            with self.subTest(fixture=name, kind=kind, pointer=pointer):
                self.assertEqual(mine, theirs)

    def test_the_failure_counts_agree_and_are_not_all_zero(self):
        """A field both halves always report as 0 is a field neither half computes."""
        mine = [t.get("failed") for t in self.py["tallies"]]
        theirs = [t.get("failed") for t in self.js["tallies"]]
        self.assertEqual(mine, theirs)
        self.assertTrue(any(f for f in mine if f),
                        "no fixture in the table has a failure in it, so this compares "
                        "zero with zero")

    def test_the_refusals_agree_word_for_word(self):
        """A parse failure is a third answer, and both halves must give the same one."""
        refusals = [(t, j) for t, j in zip(self.py["tallies"], self.js["tallies"])
                    if "error" in t or "error" in j]
        self.assertGreaterEqual(len(refusals), 3,
                                "the table must contain refusals, or this asserts nothing")
        for mine, theirs in refusals:
            self.assertEqual(mine, theirs)

    def test_the_four_sentences_are_identical(self):
        for row, mine, theirs in zip(VERDICTS, self.py["verdicts"], self.js["verdicts"]):
            with self.subTest(row=row):
                self.assertEqual(mine, theirs)

    def test_the_verdict_table_reaches_all_four_sentences(self):
        """A parity table that only ever exercises one branch proves one branch.

        This is the divergence gate applied to the parity suite itself: the strings are
        only evidence of agreement if the halves had four different things to say.
        """
        details = {v["detail"] for v in self.py["verdicts"]}
        shapes = {
            "ok": any("floor" in d for d in details),
            "empty": any("the denominator is zero" in d for d in details),
            "none-executed": any("nothing in it happened" in d for d in details),
            "below": any("below the floor of" in d for d in details),
        }
        self.assertTrue(all(shapes.values()), f"unreached sentences: {shapes}")

    def test_the_vocabulary_is_shared(self):
        """`unit` and `verb` decide what the report SAYS while both agree on the number."""
        payload = {"tallies": [], "verdicts": [[k, 1, 1, 1] for k in parsers.KINDS]}
        out = subprocess.run([node, DUMP], input=json.dumps(payload), text=True,
                             capture_output=True, cwd=ROOT)
        self.assertEqual(out.returncode, 0, out.stderr)
        theirs = json.loads(out.stdout)["verdicts"]
        mine = [{"satisfied": s, "detail": d}
                for s, d in (verdict(k, 1, 1, 1) for k in parsers.KINDS)]
        self.assertEqual(mine, theirs)


class TheTableCoversTheFixtures(unittest.TestCase):
    def test_every_fixture_is_in_the_table(self):
        """A fixture nothing compares looks exactly like one that does."""
        on_disk = {n for n in os.listdir(FIXTURES) if not n.startswith(".")}
        named = {n for _, n, _ in TALLIES}
        self.assertEqual(on_disk - named, set(),
                         "these fixtures are in the directory and in no parity row")


if __name__ == "__main__":
    unittest.main()
