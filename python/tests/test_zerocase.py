"""What the parsers say, and what the predicates do with it.

The parity suite proves the two halves agree; agreement is not correctness, and two
halves can be wrong in the same way. THIS suite is the oracle: the expected numbers are
written down beside fixtures whose contents a person can read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FIXTURES = os.path.join(ROOT, "fixtures")
sys.path.insert(0, os.path.join(ROOT, "python"))

from didrun import DID_NOT_RUN, EXIT_DID_NOT_RUN, RAN_AND_PASSED, run   # noqa: E402

from zerocase import parse as parsers                                    # noqa: E402
from zerocase import reports                                            # noqa: E402
from zerocase.parse import ParseError                                   # noqa: E402


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


class WhatTheParsersSay(unittest.TestCase):
    """The numbers, written down beside fixtures a person can read."""

    def test_junit_counts_testcases_and_subtracts_the_skipped(self):
        t = parsers.junit(fixture("junit-real.xml"))
        self.assertEqual((t.total, t.executed), (4, 3))

    def test_a_suite_where_everything_is_skipped_executed_nothing(self):
        """THE CASE A TOTAL CANNOT SEE.

        `tests="3" skipped="3"` is a green run of nothing wearing a total, and any
        counter reading only the total calls it three tests.
        """
        t = parsers.junit(fixture("junit-all-skipped.xml"))
        self.assertEqual((t.total, t.executed), (3, 0))
        control = parsers.junit(fixture("junit-real.xml"))
        self.assertEqual(control.total, 4)
        self.assertGreater(control.executed, 0,
                           "if no fixture ever executes anything, the check above is "
                           "satisfied by a parser that always returns zero")

    def test_the_header_is_a_claim_and_the_elements_are_the_thing(self):
        t = parsers.junit(fixture("junit-lying-header.xml"))
        self.assertEqual((t.total, t.executed), (2, 2))
        self.assertIn('claims tests="47"', t.note)

    def test_xml_quoted_inside_a_comment_or_cdata_is_not_a_test(self):
        """A failure message that quotes XML is ordinary. Counting it invents tests."""
        t = parsers.junit(fixture("junit-comment-trap.xml"))
        self.assertEqual((t.total, t.executed), (1, 1))

    def test_a_raw_gt_inside_an_attribute_value_does_not_end_the_tag(self):
        """XML escapes `<` and leaves `>` alone, and a test name may contain one.

        `--at <file>:<line>` reaches the report as `name="--at &lt;file>:&lt;line>"` and
        is well-formed. A scanner that ended the tag at that `>` drops the `/` of the
        self-closing element, reads the case as still open, and loses it when the next
        one replaces it: one test short, on a report that parsed and looked fine.
        """
        t = parsers.junit(fixture("junit-gt-in-attr.xml"))
        self.assertEqual((t.total, t.executed), (4, 3))
        # The same truncation in the `<testsuite>` tag hides the header's claim
        # entirely, and a header that cannot be read cannot be contradicted.
        self.assertIn('claims tests="9"', t.note)

    def test_tap_reads_the_plan_and_the_skip_directive(self):
        zero = parsers.tap(fixture("tap-zero.tap"))
        self.assertEqual((zero.total, zero.executed), (0, 0))
        real = parsers.tap(fixture("tap-real.tap"))
        self.assertEqual((real.total, real.executed), (3, 2))

    def test_lcov_separates_instrumented_from_hit(self):
        none = parsers.lcov(fixture("lcov-nohits.info"))
        self.assertEqual((none.total, none.executed), (10, 0))
        real = parsers.lcov(fixture("lcov-real.info"))
        self.assertEqual((real.total, real.executed), (32, 22))

    def test_cobertura_reads_the_header_and_checks_the_body(self):
        empty = parsers.cobertura(fixture("cobertura-empty.xml"))
        self.assertEqual((empty.total, empty.executed), (0, 0))
        real = parsers.cobertura(fixture("cobertura-real.xml"))
        self.assertEqual((real.total, real.executed), (4, 3))

    def test_the_empty_eslint_glob_is_an_empty_list(self):
        self.assertEqual(parsers.eslint(fixture("eslint-empty.json")).total, 0)
        self.assertEqual(parsers.eslint(fixture("eslint-real.json")).total, 2)

    def test_the_failure_count_is_read_and_is_never_a_verdict(self):
        """Informational. Whether a suite failed is the exit code's business, and `didrun`
        already reads it — but a reader looking at "4 of 4 tests ran" should not have to
        open the file to find out how it went."""
        self.assertEqual(parsers.junit(fixture("junit-real.xml")).failed, 1)
        self.assertEqual(parsers.tap(fixture("tap-real.tap")).failed, 1)
        self.assertEqual(parsers.eslint(fixture("eslint-real.json")).failed, 1)
        # ...and a report with nothing wrong in it says zero rather than saying nothing.
        self.assertEqual(parsers.junit(fixture("junit-all-skipped.xml")).failed, 0)

    def test_a_skipped_test_carrying_a_failure_is_neither_run_nor_failed(self):
        """A quarantined flake is emitted as `<skipped/>` AND `<failure>` in one case.

        It did not run, so it cannot have failed, and counting it as both is how a suite
        that skips everything comes to look like a suite that broke everything. The
        control is in the same file: the second case ran and did not fail.
        """
        tally = parsers.junit(fixture("junit-skipped-with-failure.xml"))
        self.assertEqual((tally.total, tally.executed, tally.failed), (2, 1, 0))

    def test_an_unreadable_report_raises_rather_than_returning_zero(self):
        """The third answer. A zero and an unreadable file are different failures."""
        with self.assertRaises(ParseError):
            parsers.junit(fixture("junit-not.xml"))
        with self.assertRaises(ParseError):
            parsers.lcov("nothing here")
        with self.assertRaises(ParseError):
            parsers.eslint("{}")

    def test_a_non_numeric_json_path_is_a_refusal_not_a_zero(self):
        with self.assertRaises(ParseError):
            parsers.json_at(fixture("summary.json"), "summary.label")
        with self.assertRaises(ParseError):
            parsers.json_at(fixture("summary.json"), "summary.missing")


class WhatTheVerdictSays(unittest.TestCase):
    def test_the_four_sentences_are_four_different_sentences(self):
        rows = [reports.verdict("junit", 4, 3, 1),
                reports.verdict("junit", 0, 0, 1),
                reports.verdict("junit", 3, 0, 1),
                reports.verdict("junit", 4, 3, 4)]
        self.assertEqual([r[0] for r in rows], [True, False, False, False])
        self.assertEqual(len({r[1] for r in rows}), 4)

    def test_a_floor_of_zero_is_refused(self):
        """A floor of 0 is satisfied by the report this package exists to catch."""
        with self.assertRaises(ValueError):
            reports.junit("x.xml", minimum=0)


class ThroughDidrun(unittest.TestCase):
    """The predicates in the tool that consumes them, on real subprocesses."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _writer(self, name, body):
        """A command that writes `body` to `name` and exits 0 — a runner, in miniature."""
        path = os.path.join(self.tmp, name)
        return path, [sys.executable, "-c",
                      f"open({path!r}, 'w').write({body!r})"]

    def test_a_report_the_run_wrote_with_tests_in_it_is_evidence(self):
        path, cmd = self._writer("junit.xml", fixture("junit-real.xml"))
        result = run(cmd, evidence=[reports.junit(path)])
        self.assertEqual(result.state, RAN_AND_PASSED, result.checks[0].detail)
        self.assertIn("3 of 4 tests ran", result.checks[0].detail)

    def test_a_report_the_run_wrote_with_NOTHING_in_it_is_did_not_run(self):
        """The flagship, and the control for the test above.

        Both are asserted because a predicate that always refused would satisfy this one
        alone, and a predicate that never refused would satisfy the other alone.
        """
        path, cmd = self._writer("junit.xml", fixture("junit-empty.xml"))
        result = run(cmd, evidence=[reports.junit(path)])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertIn("the denominator is zero", result.checks[0].detail)

    def test_a_suite_that_skipped_everything_is_did_not_run(self):
        path, cmd = self._writer("junit.xml", fixture("junit-all-skipped.xml"))
        result = run(cmd, evidence=[reports.junit(path)])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertIn("0 of 3 tests ran", result.checks[0].detail)

    def test_a_stale_report_is_not_evidence_however_full_it_is(self):
        """Four hundred passing tests from yesterday are not a run today."""
        path = os.path.join(self.tmp, "junit.xml")
        with open(path, "w") as fh:
            fh.write(fixture("junit-real.xml"))
        time.sleep(0.01)
        result = run([sys.executable, "-c", "pass"], evidence=[reports.junit(path)])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertIn("stale artefact", result.checks[0].detail)

    def test_allow_stale_lifts_it_and_the_same_file_then_passes(self):
        """The control for the test above: the file, not the freshness, is what changed."""
        path = os.path.join(self.tmp, "junit.xml")
        with open(path, "w") as fh:
            fh.write(fixture("junit-real.xml"))
        result = run([sys.executable, "-c", "pass"],
                     evidence=[reports.junit(path, allow_stale=True)])
        self.assertEqual(result.state, RAN_AND_PASSED)

    def test_a_report_that_cannot_be_parsed_is_neither_a_zero_nor_a_pass(self):
        path, cmd = self._writer("junit.xml", fixture("junit-not.xml"))
        result = run(cmd, evidence=[reports.junit(path)])
        self.assertEqual(result.state, DID_NOT_RUN)
        detail = result.checks[0].detail
        self.assertIn("could not read", detail)
        self.assertIn("is not a zero, and it is not a pass", detail)
        self.assertNotIn("denominator is zero", detail)

    def test_a_glob_sums_the_reports_it_matched(self):
        body_a = fixture("junit-real.xml")
        body_b = fixture("junit-all-skipped.xml")
        a = os.path.join(self.tmp, "a.xml")
        b = os.path.join(self.tmp, "b.xml")
        cmd = [sys.executable, "-c",
               f"open({a!r},'w').write({body_a!r}); open({b!r},'w').write({body_b!r})"]
        result = run(cmd, evidence=[reports.junit(os.path.join(self.tmp, "*.xml"))])
        self.assertEqual(result.state, RAN_AND_PASSED)
        self.assertIn("3 of 7 tests ran", result.checks[0].detail)
        self.assertIn("across 2 files", result.checks[0].detail)

    def test_a_stale_file_the_run_did_not_write_is_left_out_of_the_sum(self):
        """THE COUNT OF A RUN THAT IS OVER IS NOT PART OF THIS ONE.

        `unittest-xml-reporting` writes `TEST-<Class>-<timestamp>.xml`, and those names
        never collide — so a second run into a directory nobody cleaned ADDS files rather
        than replacing them. Until 0.1.2 the freshness rule asked only whether ONE match
        had changed and the tally then summed every match, so yesterday's three passing
        tests carried today's floor for a run that executed nothing. That is a green run
        of nothing wearing somebody else's total, in the package that exists to say so.
        """
        old = os.path.join(self.tmp, "TEST-old.xml")
        new = os.path.join(self.tmp, "TEST-new.xml")
        with open(old, "w") as fh:
            fh.write(fixture("junit-real.xml"))          # 3 executed, from a run that ended
        cmd = [sys.executable, "-c",
               f"open({new!r},'w').write({fixture('junit-all-skipped.xml')!r})"]
        result = run(cmd, evidence=[reports.junit(os.path.join(self.tmp, "*.xml"),
                                                  minimum=3)])
        self.assertEqual(result.state, DID_NOT_RUN)
        detail = result.checks[0].detail
        self.assertIn("0 of 3 tests ran", detail)
        self.assertIn("1 stale file(s) this run did not write", detail)
        self.assertIn("TEST-old.xml", detail)

    def test_allow_stale_still_sums_every_file_the_glob_matched(self):
        """The control for the test above: the freshness rule, not the files, is what
        changed. `--allow-stale` says the report may predate the command, and a glob under
        it counts every match — which is the only reading of the flag that is honest."""
        old = os.path.join(self.tmp, "TEST-old.xml")
        new = os.path.join(self.tmp, "TEST-new.xml")
        with open(old, "w") as fh:
            fh.write(fixture("junit-real.xml"))
        cmd = [sys.executable, "-c",
               f"open({new!r},'w').write({fixture('junit-all-skipped.xml')!r})"]
        result = run(cmd, evidence=[reports.junit(os.path.join(self.tmp, "*.xml"),
                                                  minimum=3, allow_stale=True)])
        self.assertEqual(result.state, RAN_AND_PASSED)
        self.assertIn("3 of 7 tests ran", result.checks[0].detail)
        self.assertNotIn("stale file(s)", result.checks[0].detail)

    def test_a_glob_match_rewritten_with_the_SAME_bytes_still_counts(self):
        """A deterministic runner did run, and `didrun.evidence.Wrote` says so by mtime.

        The glob branch compared digests alone, so one file was fresh through a plain path
        and stale through a pattern — the two paths disagreeing about the same file for no
        reason a user could see. The mtime is pushed into the past rather than slept over,
        because a filesystem with one-second granularity would decide this test.
        """
        path = os.path.join(self.tmp, "TEST-same.xml")
        body = fixture("junit-real.xml")
        with open(path, "w") as fh:
            fh.write(body)
        was = time.time() - 10
        os.utime(path, (was, was))
        cmd = [sys.executable, "-c", f"open({path!r},'w').write({body!r})"]
        result = run(cmd, evidence=[reports.junit(os.path.join(self.tmp, "*.xml"))])
        self.assertEqual(result.state, RAN_AND_PASSED, result.checks[0].detail)
        self.assertIn("3 of 4 tests ran", result.checks[0].detail)

    def test_a_report_where_everything_failed_still_satisfies_the_floor(self):
        """THE CONTROL FOR THE FAILURE COUNT. This package asks whether anything ran, not
        whether it passed — folding the two together would make it a worse test runner
        instead of a denominator check."""
        body = fixture("junit-real.xml")
        path, cmd = self._writer("junit.xml", body)
        result = run(cmd, evidence=[reports.junit(path)])
        self.assertEqual(result.state, RAN_AND_PASSED)
        self.assertIn("1 failed", result.checks[0].detail)

    def test_a_floor_can_be_set_for_one_kind_without_setting_it_for_all(self):
        """`--min 200` is sensible for lcov and absurd for junit in the same run."""
        junit_path, junit_cmd = self._writer("junit.xml", fixture("junit-real.xml"))
        lcov_path = os.path.join(self.tmp, "lcov.info")
        body = fixture("lcov-real.info")
        cmd = [sys.executable, "-c",
               f"open({junit_path!r},'w').write({fixture('junit-real.xml')!r}); "
               f"open({lcov_path!r},'w').write({body!r})"]
        result = run(cmd, evidence=[reports.junit(junit_path, minimum=1),
                                    reports.lcov(lcov_path, minimum=200)])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertTrue(result.checks[0].satisfied)
        self.assertFalse(result.checks[1].satisfied)
        self.assertIn("below the floor of 200", result.checks[1].detail)

    def test_the_predicate_keeps_the_numbers_and_not_only_the_sentence(self):
        """Something reading `--json-out` wants `executed` for a dashboard, and parsing
        it back out of the detail string is how a tool comes to depend on wording."""
        path, cmd = self._writer("junit.xml", fixture("junit-real.xml"))
        predicate = reports.junit(path)
        self.assertIsNone(predicate.tally)
        run(cmd, evidence=[predicate])
        self.assertEqual(predicate.tally["executed"], 3)
        self.assertEqual(predicate.tally["total"], 4)
        self.assertEqual(predicate.tally["failed"], 1)

    def test_read_sums_a_glob_rather_than_taking_the_first_match(self):
        a = os.path.join(self.tmp, "a.xml")
        b = os.path.join(self.tmp, "b.xml")
        for path, name in ((a, "junit-real.xml"), (b, "junit-all-skipped.xml")):
            with open(path, "w") as fh:
                fh.write(fixture(name))
        tally = reports.read("junit", os.path.join(self.tmp, "*.xml"))
        self.assertEqual((tally.total, tally.executed), (7, 3))

    def test_a_glob_that_matched_nothing_is_not_a_clean_result(self):
        result = run([sys.executable, "-c", "pass"],
                     evidence=[reports.junit(os.path.join(self.tmp, "*.xml"))])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertIn("matched no files", result.checks[0].detail)

    def test_a_glob_matching_nothing_is_refused_with_the_freshness_check_OFF_too(self):
        """The control the mutation suite asked for.

        The test above reaches the same verdict through the freshness gate, which fires
        first — so it left the second refusal unexercised, and a mutation that scored an
        empty glob as evidence survived. `--allow-stale` is the door to that branch, and
        it is exactly the configuration where the branch matters: freshness off, nothing
        matched, and nothing else left to object.
        """
        result = run([sys.executable, "-c", "pass"],
                     evidence=[reports.junit(os.path.join(self.tmp, "*.xml"),
                                             allow_stale=True)])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertIn("matched no files", result.checks[0].detail)

    def test_read_accepts_the_very_file_the_predicate_rejects_as_stale(self):
        """`read` is the loaded gun, and it is loaded on purpose.

        The same file, untouched by any command: the predicate calls it stale and `read`
        hands back its contents. That is the difference between looking at a report and
        gating a build on one, and it is why the gate takes a command.
        """
        path = os.path.join(self.tmp, "junit.xml")
        with open(path, "w") as fh:
            fh.write(fixture("junit-real.xml"))
        rejected = run([sys.executable, "-c", "pass"], evidence=[reports.junit(path)])
        self.assertEqual(rejected.state, DID_NOT_RUN)
        self.assertEqual(reports.read("junit", path).executed, 3)


class TheCommandLine(unittest.TestCase):
    def _zerocase(self, *args):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [os.path.join(ROOT, "python"), env.get("PYTHONPATH", "")])
        return subprocess.run([sys.executable, "-m", "zerocase.cli", *args],
                              capture_output=True, text=True, env=env, cwd=ROOT)

    def test_no_report_and_no_predicate_is_exit_2(self):
        """Could-not-measure has its own exit code and never borrows a verdict's."""
        out = self._zerocase("--", sys.executable, "-c", "pass")
        self.assertEqual(out.returncode, 2)
        self.assertIn("name at least one report", out.stderr)

    def test_an_empty_report_from_a_zero_exit_command_is_exit_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "junit.xml")
            body = fixture("junit-empty.xml")
            out = self._zerocase("--junit", path, "--",
                                 sys.executable, "-c",
                                 f"open({path!r},'w').write({body!r})")
        self.assertEqual(out.returncode, EXIT_DID_NOT_RUN)

    def test_a_full_report_from_the_same_shape_of_command_is_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "junit.xml")
            body = fixture("junit-real.xml")
            out = self._zerocase("--junit", path, "--",
                                 sys.executable, "-c",
                                 f"open({path!r},'w').write({body!r})")
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_read_prints_the_tally_and_warns_that_it_checked_no_freshness(self):
        out = self._zerocase("read", "--junit", os.path.join(FIXTURES, "junit-real.xml"))
        self.assertEqual(out.returncode, 0)
        self.assertIn("3 of 4 tests ran", out.stdout)
        self.assertIn("does not check freshness", out.stdout)

    def test_read_on_an_empty_report_exits_3(self):
        out = self._zerocase("read", "--junit", os.path.join(FIXTURES, "junit-empty.xml"))
        self.assertEqual(out.returncode, EXIT_DID_NOT_RUN)

    def test_a_help_in_the_command_under_test_is_not_zerocases_own(self):
        """THE GATE THAT COULD NOT FAIL.

        `main` scanned the whole of argv for `-h`/`--help` before it split on `--`, so a
        flag belonging to the wrapped command printed OUR usage and returned 0 without
        ever spawning it. The report here is empty and the floor is unmet, so the only
        way to exit 0 is to never look — and the marker file proves the command was
        actually run rather than skipped into a pass.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "junit.xml")
            runner = os.path.join(tmp, "runner.py")
            with open(runner, "w", encoding="utf-8") as fh:
                fh.write(f"open({path!r}, 'w').write({fixture('junit-empty.xml')!r})")
            out = self._zerocase("--junit", path, "--", sys.executable, runner, "--help")
            self.assertEqual(out.returncode, EXIT_DID_NOT_RUN)
            self.assertTrue(os.path.exists(path), "the command under test never ran")
            self.assertNotIn("a check with a zero denominator", out.stderr)

    def test_dash_h_in_the_command_under_test_is_a_hostname_not_our_flag(self):
        """`--help` needs a command that takes it. `-h` needs nothing unusual at all.

        It is a hostname to `mysqldump`, `curl` and `ab`, so this shape was a gate
        reporting clean forever on a report it never opened.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "junit.xml")
            runner = os.path.join(tmp, "runner.py")
            with open(runner, "w", encoding="utf-8") as fh:
                fh.write(f"open({path!r}, 'w').write({fixture('junit-empty.xml')!r})")
            out = self._zerocase("--junit", path, "--",
                                 sys.executable, runner, "-h", "dbhost")
            self.assertEqual(out.returncode, EXIT_DID_NOT_RUN)
            self.assertTrue(os.path.exists(path), "the command under test never ran")

    def test_a_dash_h_belonging_to_another_flag_is_that_flags_value(self):
        """The `--` split settled which arguments are the command's, not which of ours
        are flags.

        `--expect -h` is a regex and `--junit -h` is a path, and reading either as a
        request for help was the same exit-0-without-running, one argument further in.
        """
        for flag, val in (("--expect", "-h"), ("--expect-failure", "--help")):
            with self.subTest(flag=flag):
                with tempfile.TemporaryDirectory() as tmp:
                    path = os.path.join(tmp, "junit.xml")
                    runner = os.path.join(tmp, "runner.py")
                    with open(runner, "w", encoding="utf-8") as fh:
                        fh.write(f"open({path!r}, 'w').write("
                                 f"{fixture('junit-empty.xml')!r})")
                    out = self._zerocase("--junit", path, flag, val, "--",
                                         sys.executable, runner)
                    self.assertEqual(out.returncode, EXIT_DID_NOT_RUN)
                    self.assertTrue(os.path.exists(path), "the command never ran")
                    self.assertNotIn("a check with a zero denominator", out.stderr)

    def test_a_valued_flag_with_no_value_is_could_not_run(self):
        """`value()` raised `SystemExit` and exited 1, the code reserved for THE WRAPPED
        COMMAND failing normally, so a CI file branching on didrun's table read a zerocase
        usage error as a test failure.
        """
        # The `--` has to be there, or "put the command after `--`" answers first.
        out = self._zerocase("--junit", os.path.join(FIXTURES, "junit-real.xml"),
                             "--expect", "--", "echo", "hi")
        self.assertEqual(out.returncode, 2)
        self.assertEqual(out.stderr, "zerocase: --expect needs a value\n")

    def test_zerocases_own_help_still_prints_usage_and_exits_0(self):
        """The flag has to keep working where it IS ours, or the fix is a regression."""
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                out = self._zerocase(flag)
                self.assertEqual(out.returncode, 0)
                self.assertIn("a check with a zero denominator", out.stderr)
        bare = self._zerocase()
        self.assertEqual(bare.returncode, 2,
                         "no arguments at all is could-not-run, not help")

    def test_read_refuses_a_floor_rather_than_silently_ignoring_it(self):
        """THE REGRESSION THIS EXISTS FOR.

        `read` used to drop everything past the path, so `--min 4` beside a report
        holding 1 exited 0: a floor written down in a CI file, in review and in the
        blame, that nothing on earth enforced. A promise nothing runs is the defect this
        package is about, and shipping it inside `read` was the joke telling itself.
        Exit 2 — could not run — is the honest answer, and `--min` still means what it
        says in the wrapper form, which is the form that also checks freshness.
        """
        out = self._zerocase("read", "--junit", os.path.join(FIXTURES, "junit-real.xml"),
                             "--min", "9")
        self.assertEqual(out.returncode, 2)
        self.assertIn("unexpected argument --min", out.stderr)
        self.assertIn("wrapper form", out.stderr)

    def test_read_refuses_an_unquoted_glob_rather_than_reading_the_first_match(self):
        """The same silence wearing different clothes.

        The shell expands `*.xml` before the process starts, so `read --junit
        reports/*.xml` arrives as three arguments and the second and third used to
        vanish. `read` sums a glob when it is given ONE — and the difference between
        "summed five reports" and "read one of five" is invisible in the output, which is
        exactly the kind of quiet undercount this tool exists to refuse.
        """
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a.xml", "b.xml"):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                    fh.write(fixture("junit-real.xml"))
            expanded = sorted(os.path.join(tmp, n) for n in os.listdir(tmp))
            self.assertEqual(len(expanded), 2,
                             "the shell must have had two matches to expand")
            out = self._zerocase("read", "--junit", *expanded)
            self.assertEqual(out.returncode, 2)
            self.assertIn("quote a glob", out.stderr)

            # And quoted, it is the sum — the behaviour the refusal steers people toward.
            quoted = self._zerocase("read", "--junit", os.path.join(tmp, "*.xml"))
            self.assertEqual(quoted.returncode, 0)
            self.assertIn("6 of 8 tests ran", quoted.stdout)

    def test_json_out_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "junit.xml")
            body = fixture("junit-real.xml")
            out = self._zerocase("--junit", path, "--json-out", "--",
                                 sys.executable, "-c",
                                 f"open({path!r},'w').write({body!r})")
        payload = json.loads(out.stdout)
        self.assertEqual(payload["state"], RAN_AND_PASSED)
        self.assertTrue(payload["checks"][0]["satisfied"])
        # THE SHAPE, not only the state — `--json-out` is a contract with something that
        # is not a person, and the JavaScript suite pins the same keys. A field that
        # appears in one half's payload and not the other's is a CI file that means two
        # things, which is the thing the parity suite exists to stop.
        self.assertEqual(payload["reports"][0],
                         {"kind": "junit", "path": path, "files": 1, "stale": 0,
                          "total": 4, "executed": 3, "failed": 1, "minimum": 1})


if __name__ == "__main__":
    unittest.main()
