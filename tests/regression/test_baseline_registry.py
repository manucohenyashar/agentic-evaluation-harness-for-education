"""The baseline registry still says what §6.9 says.

Not `TC-*`-traced. This is drift detection over the fixture the six `TC-REG-*` cases read, in
the same spirit as `tests/contract/console/test_ct_console_vocabulary.py` — and like that
file, **it is green and it is not coverage**. It checks that a transcription still matches the
document it came from; it asserts nothing about any module.

It exists because the six cases put the reviewer and the grounds into their failure messages,
and a transcription that drifted would print a plausible-looking reviewer who is not the one
the plan names. A wrong reviewer on a golden diff is worse than none: it routes the decision to
somebody with no standing to make it, and it does so in the confident voice of a test failure.
"""

from __future__ import annotations

import json

from tests.support.doc_tables import DocRowMissing, markdown_rows, read_repo_text

from tests.support.baselines import REGISTRY_PATH, registry

TEST_PLAN = "docs/design/test-plan.md"

# §6.9's table, in order.
CASE_IDS = (
    "TC-REG-01",
    "TC-REG-02",
    "TC-REG-03",
    "TC-REG-04",
    "TC-REG-05",
    "TC-REG-06",
)


def _section_6_9_row(rows: list[list[str]], case_id: str) -> list[str]:
    """§6.9's row for one case, located on its **first cell**.

    `doc_tables.find_row` searches every cell and raises on ambiguity, which is the right rule
    and the wrong locator here: each `TC-REG-*` id also appears in two RTM rows and in §8.2's
    story table, so a whole-row search matches four times. Keyed on the first cell instead —
    §6.9's table is the only one whose leading column *is* the case id — and the raise-on-zero
    and raise-on-many discipline is kept, because a locator that silently picks one of four
    rows asserts against whichever sorted first.
    """
    matches = [row for row in rows if row and row[0] == case_id]
    if len(matches) != 1:
        raise DocRowMissing(
            f"{len(matches)} rows in {TEST_PLAN} lead with {case_id!r}; §6.9's baseline table "
            f"must have exactly one. Either the table moved (update this locator) or the "
            f"baseline was dropped (that is the finding)."
        )
    return matches[0]


def test_the_registry_covers_exactly_the_six_baselines_section_6_9_names():
    entries = registry()
    assert tuple(entries) == CASE_IDS, (
        f"the registry holds {tuple(entries)}; §6.9's table names {CASE_IDS}. A baseline "
        f"without a registry entry has no named reviewer, which is the whole point of the "
        f"table."
    )


def test_every_entry_names_a_reviewer_grounds_an_oracle_and_at_least_one_golden_file():
    for case_id, entry in registry().items():
        assert entry.reviewer.strip(), f"{case_id} names no reviewer"
        assert entry.grounds.strip(), f"{case_id} states no grounds for accepting a diff"
        assert entry.oracle.strip(), f"{case_id} states no oracle"
        assert entry.golden, f"{case_id} declares no golden file, so there is nothing to freeze"
        assert entry.blocked_on.startswith("#"), (
            f"{case_id} does not name the issue that produces its baseline; without it, a "
            f"missing golden file is indistinguishable from a deleted one"
        )
        assert entry.requirements, f"{case_id} traces to no requirement"


def test_each_registry_entry_still_matches_its_row_in_the_test_plan(repo_root):
    """The transcription check.

    Compared on the distinctive phrases rather than on the whole cell: §6.9's cells carry
    Markdown emphasis and backticks that the registry stores as plain text, and a whole-cell
    equality assertion would fail on a typo fix and teach everyone to skip this file.
    """
    rows = markdown_rows(read_repo_text(repo_root, TEST_PLAN))
    entries = registry()

    for case_id in CASE_IDS:
        row = _section_6_9_row(rows, case_id)
        _, requirements_cell, baseline_cell, reviewer_cell = row[:4]
        entry = entries[case_id]

        for requirement in entry.requirements:
            assert requirement in requirements_cell, (
                f"{case_id}: the registry traces to {requirement}, §6.9's row lists "
                f"{requirements_cell!r}"
            )
        assert entry.baseline.strip("`") in baseline_cell or baseline_cell in entry.baseline, (
            f"{case_id}: the registry's baseline is {entry.baseline!r}, §6.9's is "
            f"{baseline_cell!r}"
        )
        # The reviewer and the grounds share one cell in the plan. Both must be recognisable in
        # it, since both go into the failure message a golden diff produces.
        assert entry.reviewer.rstrip(".").lower() in reviewer_cell.lower(), (
            f"{case_id}: the registry names reviewer {entry.reviewer!r}; §6.9's cell reads "
            f"{reviewer_cell!r}"
        )
        # Case-folded: §6.9 runs the reviewer and the grounds together as one sentence, so the
        # registry's grounds start mid-sentence in the plan and sentence-initial in the entry.
        # That difference is a split point, not drift.
        distinctive = entry.grounds.split(";")[0].split("(")[0].strip().rstrip(".").lower()
        reviewer_cell = reviewer_cell.lower()
        assert distinctive[:40] in reviewer_cell, (
            f"{case_id}: the registry's grounds start {distinctive[:40]!r}, which does not "
            f"appear in §6.9's cell {reviewer_cell!r}"
        )


def test_the_registry_is_valid_json_and_carries_the_no_regenerate_policy():
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert raw["source"].startswith("docs/design/test-plan.md")
    assert "regenerate until green" in raw["policy"], (
        "the registry does not carry §6.9's policy sentence. The sentence is what a reader "
        "opening the file to refresh a baseline is supposed to hit first."
    )
