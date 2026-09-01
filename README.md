# `zerocase`

[![npm](https://img.shields.io/npm/v/zerocase)](https://www.npmjs.com/package/zerocase)
[![PyPI](https://img.shields.io/pypi/v/zerocase)](https://pypi.org/project/zerocase/)
[![CI](https://github.com/Megapixel99/zerocase/actions/workflows/ci.yml/badge.svg)](https://github.com/Megapixel99/zerocase/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A check with a zero denominator reports clean.**

A suite in which every test was skipped, a lint whose glob matched nothing, a coverage
run over no statements; every one of them exits 0, and every one of them has already
written the number down in a file with a field name on it.

```sh
pip install zerocase            # the Python half
npm install zerocase            # the JavaScript half

zerocase --junit reports/junit.xml -- pytest tests/
zerocase --lcov coverage/lcov.info --min 50 -- npm run coverage
zerocase --eslint out.json -- npx eslint src --format json -o out.json
```

```
$ zerocase --junit reports/junit.xml -- pytest --junitxml=reports/junit.xml tests/
============================= 214 skipped in 0.14s =============================

[zerocase] DID NOT RUN — there is no evidence this command did anything  (exit 0, 461ms)
  --  reports/junit.xml reports at least 1 tests that ran: 0 of 214 tests ran — the
      report is not empty, and nothing in it happened

  It exited 0. That is the failure: a check that stopped checking reports exactly this.
$ echo $?
3
```

## What this adds to `didrun`, which is its one dependency

[`didrun`](https://github.com/Megapixel99/didrun) asks the same question of a command's
stdout with a regex you supply, and its README names this gap in its own Limits section:
*"It does not parse junit/TAP. `--wrote` plus `--expect-count` covers most of what that
would buy."* Most, not all. Two things are in the residue.

**A regex over stdout is a claim about a runner's human-facing text.** It moves with the
locale, with the reporter plugin and with the minor version. `junit.xml` has the number in
a field with a name.

**And a total is not a denominator.**

```xml
<testsuite name="pytest" tests="50" skipped="50">
```

That is a green run of nothing wearing a total, and `--expect-count "(\d+) tests"` reads
the fifty and is satisfied: exactly as it would be by fifty tests that ran. So every
parser here returns **two** numbers, `total` and `executed`, and **the floor applies to
`executed`**.

| report | `total` | `executed` | `failed` |
|---|---|---|---|
| JUnit / xUnit XML | `<testcase>` elements | minus those holding `<skipped/>` | cases with `<failure>` or `<error>` |
| TAP | the `1..N` plan | minus `# SKIP` and `# TODO` | `not ok` lines |
| LCOV | `LF:` lines found | `LH:` lines hit | n/a |
| Cobertura | `lines-valid` | `lines-covered` | n/a |
| ESLint `--format json` | entries in the array | those with a `filePath` | files with errors or warnings |
| any JSON | the number at a dotted path | the same number | n/a |

**`failed` is informational and is never a verdict.** Whether a suite passed is the exit
code's business and `didrun` already reads it; this is here so a reader looking at
`4 of 4 tests ran` and wondering how it went does not have to open the file. A report in
which every test failed still satisfies the floor, and there is a test that says so.

A `<testcase>` carrying **both** `<skipped/>` and `<failure>` (a quarantined flake, an
xfail, a rerun that gave up) did not run, so it cannot have failed. Counting it as both is
how a suite that skips everything comes to look like a suite that broke everything.

Everything else is `didrun`'s and is not reimplemented here: the four states, the exit
codes, `expect_failure`, the timeout classification, and the sentence *"a stale artefact
from an earlier run looks exactly like this"*. That is the argument `canfail` made when it
deleted its inline `_Guard`: a second copy of a guarantee is a second thing to get wrong,
and the copy is the one that does not get the upstream's tests.

## Three answers, never two

A report can be read and hold a number, or be read and hold a zero, or **not be readable
at all**, and the third must not collapse into either of the others.

```
  --  out.json reports at least 1 files that were linted: could not read out.json as
      eslint: not valid JSON: Unexpected token 'E' — an unreadable report is not a zero,
      and it is not a pass
```

An unparseable report scored as a zero fails builds for the wrong reason and teaches
people to ignore this tool. Scored as a pass it is the defect the tool exists to report,
wearing the tool's own badge.

## Freshness is not optional by default

A `junit.xml` from yesterday parses beautifully and says four hundred tests passed. A
runner that never started leaves it exactly where it was.

Every report must have been **written during this run**: created, changed, or rewritten.
`--allow-stale` lifts it for the case where a separate step produced the file, and the
name is deliberately unpleasant.

**A glob is asked that per file, and only the files this run wrote are summed.** Runners
that stamp a timestamp into the filename: `unittest-xml-reporting` writes
`TEST-<Class>-<timestamp>.xml`, never overwrite, so a second run into a directory nobody
cleaned *adds* reports beside the old ones. Counting every match would let a run that is
already over carry the floor for the run in front of you. Leftovers are named in the
detail and left out of the count:

```
0 of 3 tests ran — the report is not empty, and nothing in it happened;
1 stale file(s) this run did not write, left out of the count, first reports/TEST-old.xml
```

Under `--allow-stale` there is no "this run" to compare against, so every match counts.

`zerocase read --junit reports/junit.xml` parses a file already on disk and **does not**
check freshness. It says so on every run, because that is the whole reason the gate takes
a command instead of a filename.

## Count the elements, not the attributes

`<testsuite tests="47">` is a claim the writer made. Forty-seven `<testcase>` elements are
the thing itself. They disagree more often than anyone expects: a runner killed halfway
leaves a header from one run and a body from another, and when they disagree this counts
the elements and says the attribute differed:

```
  ok  reports/junit.xml reports at least 1 tests that ran: 2 of 2 tests ran (floor 1);
      reports/junit.xml: the file claims tests="47" in its <testsuite> attributes and
      contains 2 <testcase> elements; the elements are what is counted
```

## Read this first: some runners already answer this

Let them. Checked, not assumed, and this is `didrun`'s table, unchanged, because it is
the same question one layer up:

| | answers "did anything run"? |
|---|---|
| `pytest` | **yes**: exits 5 when it collects nothing |
| `jest`, `vitest` | **yes**: fail by default when no test matches |
| `go test ./...` | **no**: prints `[no test files]` and exits **0** |
| `eslint` given a glob that matched nothing | **no**: prints `[]` and exits 0 |
| a coverage step whose instrumenter found nothing | **no** |
| any shell step in any CI file | no notion of the question at all |

And one row in the other direction: **for a coverage *percentage* threshold, use your
coverage tool.** `nyc --check-coverage --lines 80`, `pytest --cov-fail-under=80` and
`coverage report --fail-under` all do it properly and know about branches, functions and
per-file thresholds. `--min-lcov` puts a floor under the *number of lines covered*, which
is the different question of whether the instrumenter and the suite met at all: `LF:0` is
an instrumenter that found nothing, and `LH:0` over a real `LF` passes a threshold of zero
percent every time.

The rows where this earns its keep are the ones that produce a machine-readable report
*and* have no opinion about its being empty. If your runner is in the first two rows, you
probably do not need this, though `pytest` answers only for collection: deselecting
everything exits 5 as well, but a suite in which every test is skipped prints
`214 skipped`, exits 0, and is the first row failing at the second question.

## API

```python
from didrun import run
from zerocase import reports

result = run(["pytest", "tests/"], evidence=[
    reports.junit("reports/junit.xml", minimum=1),
    reports.lcov("coverage/lcov.info", minimum=200),
])
result.state    # didrun's four states, unchanged
```

```js
import { run } from "@megapixel99/didrun";
import { reports } from "zerocase";

const result = await run(["pytest", "tests/"], {
  evidence: [reports.junit("reports/junit.xml"), reports.lcov("coverage/lcov.info", { min: 200 })],
});
```

Every predicate must hold: `didrun`'s rule, `every` and not `some`. Reports may be globs
(`--junit 'reports/*.xml'`), in which case the tallies are summed and the file count is
printed, because five reports and one report are not the same result. `zerocase read` sums
a glob the same way, rather than quietly taking the first match.

**One floor per kind, because one number cannot mean two things.** `--min 200` is sensible
for `--lcov` and absurd for `--junit` in the same invocation, so each kind takes its own:

```sh
zerocase --junit reports/junit.xml --lcov coverage/lcov.info \
         --min-junit 20 --min-lcov 200 -- npm run ci
```

`--min` stays as the default for every kind without a `--min-KIND`, and both are applied
after the whole command line is read, so neither depends on where you put it.

`--json-out` carries the numbers as well as the sentences:

```json
"reports": [
  {"kind": "junit", "path": "reports/junit.xml", "files": 1, "stale": 0,
   "total": 4, "executed": 3, "failed": 1, "minimum": 1}
]
```

Something building a dashboard wants `executed`, and parsing it back out of the detail
string is how a downstream tool comes to depend on wording.

## Prior art

Swept across **both registries** on 2026-08-31, on problem nouns and on format names,
because round 1 of this line of work retracted four proposals to keyword variants alone.

On npm, `keywords:junit` returns **349 packages** and every one inspected is a *reporter*
(writes the file), a *merger*, or a *viewer*: none asserts a floor on what is in it.
`keywords:test-count` returns **0**. `keywords:zero-tests` and `keywords:empty-glob`
return exactly one package each, and it is `@megapixel99/didrun`.

Two neighbours are real and neither is this:

- **[`@testmuai/evidence-cli`](https://www.npmjs.com/package/@testmuai/evidence-cli)**
  (LambdaTest) defines a framework-agnostic `.evidence` pack and validates and seals its
  *shape*. It asks whether the document is well-formed; this asks whether the number in it
  is greater than zero.
- **[`evidence-gate`](https://pypi.org/project/evidence-gate/)** (PyPI) audits GitHub
  Actions evidence bundles after the fact: whether an audit trail is complete and
  temporally bounded. A different question, downstream of this one.

Nothing found gates a run on the denominator of the report the runner already wrote.

## Limits

- **The parsers are scanners, not XML parsers.** Comments and CDATA are stripped first:
  a failure message quoting `<testcase>` is ordinary and counting it would invent tests:
  and the fixture that proves it is in `fixtures/junit-comment-trap.xml`. A deliberately
  hostile document could still fool them. The same scanner runs in **both halves**, on
  purpose: Python has `xml.etree` and JavaScript has nothing in its standard library, and
  using a real parser on one side would make every disagreement between the halves a
  question about two engines rather than about one report.
- **It cannot tell a suite that ran from a suite that reported.** A runner that writes a
  full `junit.xml` and then does nothing satisfies this. It moves the claim from the exit
  code to the report, which is a much harder thing to fake by accident, and not an
  impossible one.
- **A floor is per KIND, not per report.** `--min` is the default for every kind and
  `--min-KIND` overrides one of them, but name two `--junit` reports in the same
  invocation and they share whatever floor `junit` has; there is no way to say "at least
  20 from this one and at least 5 from that one". A per-path floor would need a syntax
  nobody would remember, and the kinds are where the numbers actually differ: `200` is
  sensible for `--lcov` and absurd for `--junit`.
- **One dependency, `didrun`, and nothing else** in either half. Node ≥ 20, Python ≥ 3.9.

## Tests

```sh
npm test                                                   # 38
PYTHONPATH=python python3 -m unittest discover -s python/tests   # 44, seven of them parity
```

The parity suite sends **one** table of fixtures and verdict rows to both halves and
compares the tallies *and the sentences*, character for character: a CI file that moves
from `pip install` to `npm install` must not change meaning, and two halves can agree on a
number while describing it differently. The table lives in the Python suite and is sent
over stdin rather than kept in a second copy, because a parity suite whose sides maintain
their own inputs drifts by being asked different questions and then reports agreement
about that.

**Thirteen mutations were applied to the source and all thirteen were caught**: the floor read
from the total instead of from what executed, a skipped testcase counted as one that ran,
an unreadable report scored as evidence, the freshness check skipped, a floor of zero
accepted, comments left unstripped before the scan, an empty glob scored as clean, a
skipped test counted as a failure, the failure count never reported, a failing suite scored
as no evidence, the predicate keeping no tally, and `read` taking the first match of a glob
instead of summing it, and a glob counting every file it matched rather than only the ones
the run wrote.

**The thirteenth was not hypothetical; it shipped.** `zerocase 0.1.1` asked its freshness
rule whether *any* file under a pattern had changed and then summed *every* file the
pattern matched, so a second run into an uncleaned directory was carried by the first.
Reverting 0.1.2's glob to that behaviour now fails two tests in each half; before 0.1.2
there was nothing for it to fail. A mutation you can only invent after the release is a
test you did not have.

**Two of them survived their first run**, and both were worth more than the fix.

The empty-glob mutation survived because the test that covers an empty glob reaches its
verdict through the *freshness* gate, which fires first and returns before the second
refusal is ever reached. The branch was live, reachable through `--allow-stale`, and
exercised by nothing.

The skipped-counted-as-failed mutation survived because no fixture had a `<testcase>`
carrying *both* a `<skipped/>` and a `<failure>`, so `case_failed` was never true where it
mattered, and the guard was untested by construction.
`fixtures/junit-skipped-with-failure.xml` exists because of that, and it is a shape real
runners emit.

A third mutation was **wrong rather than surviving**: `self.tally = self.tally or {...}` is
a no-op on the first run, so it changed nothing and proved nothing. A mutation that cannot
alter behaviour scores as SURVIVED and reads as a test gap, which is a way for a mutation
suite to lie in the flattering direction as well as the other one.

## License

MIT
