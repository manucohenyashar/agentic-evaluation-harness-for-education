"""Read the markdown tables in the design documents as data.

Two `CT-CONFORM` clauses are about **configuration**, not about code:

* `CT-CONFORM-08` makes the two test tiers contract — the fast tier needs no live model, and the
  full suite is not run per commit. Test plan §6.11.18 says to assert that *"against the CI
  configuration rather than as an intention"*.
* `CT-CONFORM-11` says the time bound exists so the suite *"can gate a release rather than being
  deferred to a nightly nobody reads"*, and asks for a gate-wiring assertion alongside the
  measurement.

**In this repo, test plan §4.7's suite table *is* the CI configuration.** `.github/workflows/`
holds two deliberately `.disabled` files and `CLAUDE.md` states that GitHub runs no agents here —
so §4.7's table, one row per suite with its command and its trigger, is the only place the wiring
is written down. Asserting against it is asserting against the configuration; asserting against
the disabled workflows would be asserting against nothing.

That makes the parsing below load-bearing, so it is deliberately narrow: a pipe-delimited row
reader and a locator, with `find_row` **raising** rather than returning `None` when the row is
gone. A locator that returns `None` turns a renamed row into a vacuous pass, which is the failure
mode of every assertion built on top of it.
"""

from __future__ import annotations

from pathlib import Path


class DocRowMissing(AssertionError):
    """A row the suite asserts against is no longer in the document.

    `AssertionError` rather than `LookupError` so it lands as a test failure naming the needle,
    and so a reader sees "the row moved" instead of a traceback through a parser.
    """


def markdown_rows(text: str) -> list[list[str]]:
    """Every pipe-delimited row in `text`, as lists of stripped cells.

    Separator rows (`|---|---|`) are dropped; header rows are kept, since a caller looking for a
    column index needs them. No attempt is made to associate rows with the table they came from —
    the callers here locate by content, which survives a section being renumbered.
    """
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= {"-", ":", " "} and cell for cell in cells):
            continue  # the |---|---| separator
        rows.append(cells)
    return rows


def find_row(rows: list[list[str]], needle: str) -> list[str]:
    """The single row containing `needle` in any cell, or raise.

    Raises when **no** row matches and when **more than one** does. The second is not pedantry:
    an assertion written against "the conformance row" that silently picked the first of two would
    be asserting about whichever one happened to sort first, and a reader of the failure would
    have no way to tell.
    """
    matches = [row for row in rows if any(needle in cell for cell in row)]
    if not matches:
        raise DocRowMissing(
            f"no table row contains {needle!r}. The suite asserts against this row, so its "
            f"disappearance is a finding rather than a reason to skip: either the configuration "
            f"moved (update the locator) or the wiring was removed (that is the defect)."
        )
    if len(matches) > 1:
        raise DocRowMissing(
            f"{len(matches)} table rows contain {needle!r}; the locator must name exactly one. "
            f"Rows: {matches!r}"
        )
    return matches[0]


def read_repo_text(repo_root: Path, relative: str) -> str:
    """A repo file's text, or an assertion naming what was missing."""
    path = repo_root / relative
    if not path.exists():
        raise DocRowMissing(f"{relative} does not exist; the suite asserts against it.")
    return path.read_text(encoding="utf-8")
