/**
 * A pure function, for the parity suite to compare against.
 *
 * Reads `{tallies: [[kind, path, pointer]], verdicts: [[kind, total, executed, min]]}`
 * from stdin and prints what the JavaScript half makes of each. THE TABLE IS NOT HERE ON
 * PURPOSE: `python/tests/test_parity.py` owns it and sends it over, so the two halves
 * cannot drift by being asked different questions — which is the failure mode of a parity
 * suite that keeps a copy of the inputs on each side.
 *
 * Not published: `files` in package.json lists `js/src` and `js/bin`.
 */
import fs from "node:fs";
import { jsonAt, parse, ParseError } from "../src/parse.js";
import { verdict } from "../src/reports.js";

const input = JSON.parse(fs.readFileSync(0, "utf8"));

const tallies = (input.tallies || []).map(([kind, file, pointer]) => {
  let text;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch (err) {
    return { error: `unreadable: ${err.message}` };
  }
  try {
    const t = kind === "json" ? jsonAt(text, pointer) : parse(kind, text);
    return { kind: t.kind, total: t.total, executed: t.executed, unit: t.unit,
             verb: t.verb, note: t.note, failed: t.failed };
  } catch (err) {
    if (!(err instanceof ParseError)) throw err;
    return { error: err.message };
  }
});

const verdicts = (input.verdicts || []).map(([kind, total, executed, min]) => {
  const [satisfied, detail] = verdict(kind, total, executed, min);
  return { satisfied, detail };
});

process.stdout.write(JSON.stringify({ tallies, verdicts }, null, 2) + "\n");
