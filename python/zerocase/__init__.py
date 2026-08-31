r"""zerocase — a check with a zero denominator reports clean.

    from didrun import run
    from zerocase import reports

    result = run(["pytest", "tests/"], evidence=[reports.junit("reports/junit.xml")])
    result.state   # didrun's four states, unchanged

The report the runner already wrote has the number in a field with a name. A regex over
stdout has it in prose that moves with the locale and the minor version.
"""

from . import parse, reports
from .parse import KINDS, ParseError, Tally
from .reports import Report, read, verdict

__all__ = ["reports", "parse", "Report", "Tally", "ParseError", "KINDS", "read",
           "verdict"]
__version__ = "0.1.1"
