"""Compare argparse output without depending on interpreter colour behaviour.

Python 3.14 colourizes argparse help and error output. Assertions that compare
literal help text therefore pass on 3.13 and fail on 3.14, and `requires-python`
declares `>=3.10` with no upper bound, so both are supported.

Stripping escapes rather than setting NO_COLOR or PYTHON_COLORS: the assertion then
holds whatever the interpreter version or the operator's colour settings do, instead
of depending on env plumbing reaching the test process.
"""

from __future__ import annotations

import re

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def without_ansi(text: str) -> str:
    """Return text with ANSI colour escapes removed."""
    return ANSI_ESCAPE.sub("", text)
