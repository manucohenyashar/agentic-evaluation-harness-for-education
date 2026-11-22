"""The teacher-text census (FR-UI-23, TC-CONSOLE-87): the patterns no display string of a
console answer may match, and the walk over an answer's string fields.

Lifted from `tests/integration/console/test_tc_console_87_92_teacher_text_census.py` so the
cases that reuse the census (TC-CONSOLE-110, issue #901) read the same patterns and cannot
drift from it.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

#: FR-UI-23's patterns, as TC-CONSOLE-87 states them.
CENSUS_PATTERNS: dict[str, re.Pattern[str]] = {
    "requirement or test id": re.compile(r"\b(FR|NFR|CT|TC|ADR|RS)-[A-Z0-9]+(-\d+)?\b"),
    "package-version hash": re.compile(r"@[0-9a-f]{12}\b"),
    "internal package ref": re.compile(r"\bpkg-"),
    "uuid": re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    "file path": re.compile(r"[\\/][^\s\\/'\"]*\.(sqlite|toml)\b"),
    "toml fragment": re.compile(r"\[\["),
}


def exempt(key: str) -> bool:
    """ID fields are exempt by name: `id`, `*_id`, `*_ids`."""
    return key == "id" or key.endswith("_id") or key.endswith("_ids")


def strings(value: Any, where: str = "") -> Iterator[tuple[str, str]]:
    """Every string field of a JSON answer as `(json path, text)`, ID fields skipped."""
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, dict):
        for key, item in value.items():
            if exempt(str(key)):
                continue
            yield from strings(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from strings(item, f"{where}[{index}]")


def census_findings(answer: Any) -> list[str]:
    """`path: pattern name: text` for every string field that matches a census pattern."""
    return [f"{where}: {name}: {text!r}" for where, text in strings(answer)
            for name, pattern in CENSUS_PATTERNS.items() if pattern.search(text)]


__all__ = ["CENSUS_PATTERNS", "census_findings", "exempt", "strings"]
