/**
 * zerocase — a check with a zero denominator reports clean.
 *
 *     import { run } from "@megapixel99/didrun";
 *     import { reports } from "zerocase";
 *
 *     const result = await run(["pytest", "tests/"], {
 *       evidence: [reports.junit("reports/junit.xml")],
 *     });
 *     result.state;   // didrun's four states, unchanged
 *
 * The report the runner already wrote has the number in a field with a name. A regex over
 * stdout has it in prose that moves with the locale and the minor version.
 */

import * as reports from "./reports.js";
import * as parse from "./parse.js";

export { reports, parse };
export { ParseError, KINDS, UNITS, VERBS } from "./parse.js";
export { verdict, read } from "./reports.js";
export const VERSION = "0.1.0";
