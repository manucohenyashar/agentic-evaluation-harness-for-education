"""`CT-INGEST-08` — the per-gate report (`TC-INGEST-C08`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — #40 landed the
gate columns and `IngestReport.gates`.

The clause: each gate records its own outcome in its own column, the gates are
NEVER collapsed into one boolean, and the outcome values are a closed vocabulary —
`pass` / `fail` / `not_run` / `unmatched` / `ambiguous` on V0-V3 and the
three-valued `match` / `uncertain` / `mismatch` on V4. `IngestReport.gates` (the
stage-level observability seam, CLAUDE.md seam 4) mirrors the stored columns
exactly.

Discriminator: a mutant that collapses the five gates into one boolean (one
column, `passed = 1`) fails the PRAGMA shape and the report-mirror sweep while
every FR case — which reads the report's own dict on a clean ingest — stays
green. The vocabulary sweep holds the closedness: a gate that starts writing
prose findings into its column (or a score-shaped value) turns the value sweep
red.
"""

from __future__ import annotations

import pytest

from tests.contract.ingest._doubles import (
    ISSUE,
    Contract,
    RefusingSanitizer,
    answer_text,
    student_answer,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract

#: The gate columns, in ladder order — five SEPARATE columns, never one.
GATE_COLUMNS = ("v0_integrity", "v1_pages", "v2_structure", "v3_identity",
                "v4_match")

#: The closed value vocabulary. The shipped routing's only writers are the
#: "pass"/"fail"/"not_run" initialisation and the quarantines, "unmatched"/
#: "ambiguous" on V3, and the three-valued V4 outcome.
GATE_VOCABULARY = frozenset({
    "pass", "fail", "not_run", "unmatched", "ambiguous",
    "match", "uncertain", "mismatch",
})

#: Boolean-shaped values that must never appear in a gate column.
BOOLEAN_SHAPES = frozenset({"true", "false", "yes", "no", "1", "0", "ok"})


def _stored_gates(fx: Contract, submission_id: str) -> dict:
    row = fx.handle.query(statement(
        "SELECT v0_integrity, v1_pages, v2_structure, v3_identity, v4_match "
        "FROM submission WHERE submission_id = :s", issue=ISSUE),
        s=submission_id)[0]
    return dict(zip(GATE_COLUMNS, tuple(row)))


def _ingest_clean(fx: Contract, body: bytes, name: str):
    source = fx.put(body)
    fx.script(source, {1: student_answer("hal", answer_text("Q1", "answer"))})
    return fx.ingestor.ingest_submission(
        [source], cohort_id="c-ingest-ct", package_version="v0",
        filenames={source: name})


def _check_row(fx: Contract, report, label: str) -> None:
    """The mirror sweep: the report's gates equal the stored columns, and every
    stored value is a closed-vocabulary string, never a boolean shape."""
    stored = _stored_gates(fx, report.submission_id)
    mirrored = {"v0_integrity": report.gates["v0"],
                "v1_pages": report.gates["v1"],
                "v2_structure": report.gates["v2"],
                "v3_identity": report.gates["v3"],
                "v4_match": report.gates["v4"]}
    assert set(stored) == set(GATE_COLUMNS), (
        f"TC-INGEST-C08: the stored gate columns are {set(stored)}."
    )
    assert mirrored == stored, (
        f"TC-INGEST-C08 ({label}): the report's gates {report.gates} do not "
        f"mirror the stored row {stored} — the observability seam and the "
        "record disagree."
    )
    for column, value in stored.items():
        assert value in GATE_VOCABULARY, (
            f"TC-INGEST-C08 ({label}): {column} holds {value!r} — outside the "
            f"closed vocabulary {sorted(GATE_VOCABULARY)}."
        )
        assert value.lower() not in BOOLEAN_SHAPES, (
            f"TC-INGEST-C08 ({label}): {column} holds the boolean-shaped "
            f"{value!r} — a gate outcome is never a boolean."
        )


def test_tc_ingest_c08_the_gates_are_five_separate_columns(tmp_data_dir):
    """`TC-INGEST-C08` (schema half) — the submission table carries exactly the
    five gate columns as TEXT beside the 0/1 quarantine flag: no single boolean
    column, no score-bearing column on the same row."""
    fx = Contract(tmp_data_dir, "c08-schema")
    columns = fx.handle.query(statement(
        "SELECT name, type FROM pragma_table_info('submission')", issue=ISSUE))
    by_name = {row["name"]: row["type"] for row in columns}
    for column in GATE_COLUMNS:
        assert by_name.get(column) == "TEXT", (
            f"TC-INGEST-C08: gate column {column} is {by_name.get(column)!r}, "
            "not TEXT — the gate outcome is a recorded value, not a boolean."
        )
    collapsed = [name for name in by_name
                 if name in ("passed", "gates", "gate_outcome", "valid")]
    assert not collapsed, (
        f"TC-INGEST-C08: the gates were collapsed into {collapsed} — one "
        "boolean over five gates is the silent-failure trap the clause names."
    )
    assert by_name.get("quarantined") == "INTEGER", (
        "TC-INGEST-C08: the quarantine flag is not a 0/1 INTEGER column."
    )
    fx.close()


def test_tc_ingest_c08_every_report_carries_exactly_the_five_gates(tmp_data_dir):
    """`TC-INGEST-C08` (report half) — every `IngestReport`, clean or
    quarantined, names exactly v0..v4 as string outcomes — never a boolean,
    never a missing gate — and each report's dict mirrors its stored row."""
    fx = Contract(tmp_data_dir, "c08-clean")
    clean = _ingest_clean(fx, b"c08 clean pdf", "a.pdf")
    bad = fx.put(b"c08 bad pdf")  # no transcript, no text layer: v0 refuses
    refused = fx.ingestor.ingest_submission(
        [bad], cohort_id="c-ingest-ct", package_version="v0",
        filenames={bad: "b.pdf"})
    assert set(clean.gates) == {"v0", "v1", "v2", "v3", "v4"}, (
        f"TC-INGEST-C08: the clean report's gates are {set(clean.gates)}."
    )
    assert set(refused.gates) == {"v0", "v1", "v2", "v3", "v4"}, (
        f"TC-INGEST-C08: the quarantined report's gates are {set(refused.gates)}."
    )
    for label, report in (("clean", clean), ("refused", refused)):
        assert all(isinstance(v, str) and v for v in report.gates.values()), (
            f"TC-INGEST-C08 ({label}): a gate value is not a recorded string: "
            f"{report.gates}."
        )
        _check_row(fx, report, label)
    fx.close()


def test_tc_ingest_c08_the_gate_values_are_the_closed_vocabulary(tmp_data_dir):
    """`TC-INGEST-C08` (vocabulary half) — across a clean ingest and a true V0
    refusal (the sanitizer refuses) the five columns only ever hold
    closed-vocabulary values, the failing gate is the one that flips to `fail`,
    and the row still carries every column. Shipped nuance, recorded here: the
    skipped V1-V3 columns keep their `pass` initialisation on a V0 refusal
    (only V4 carries a `not_run`) — the failing gate is unambiguous, which is
    what the clause holds."""
    fx = Contract(tmp_data_dir, "c08-vocabulary")
    _check_row(fx, _ingest_clean(fx, b"c08 v pdf", "a.pdf"), "clean")
    refuser = Contract(tmp_data_dir, "c08-v0",
                       sanitizer=RefusingSanitizer("unreadable source"))
    refused = refuser.ingestor.ingest_submission(
        [refuser.put(b"c08 bad pdf")], cohort_id="c-ingest-ct",
        package_version="v0", filenames={})
    assert refused.ingest_status == "unreadable" and refused.gates["v0"] == "fail", (
        f"TC-INGEST-C08: the sanitizer refusal did not quarantine: "
        f"{refused.ingest_status} / {refused.gates}."
    )
    _check_row(refuser, refused, "refused")
    assert _stored_gates(refuser, refused.submission_id)["v0_integrity"] == "fail", (
        "TC-INGEST-C08: the refused unit's v0 column did not flip to 'fail'."
    )
    fx.close()
    refuser.close()


def test_tc_ingest_c08_a_v4_not_run_is_recorded_not_hidden(tmp_data_dir):
    """`TC-INGEST-C08` (not_run half) — with no package bound, V4 records
    `not_run` in its own column on an otherwise-completed row: a gate that did
    not run is a recorded outcome, not a missing column or a silent pass."""
    fx = Contract(tmp_data_dir, "c08-notrun")
    fx.add_roster("hal")
    report = _ingest_clean(fx, b"c08 nr pdf", "a.pdf")
    assert report.ingest_status == "ok", (
        f"TC-INGEST-C08: the no-package ingest did not complete: "
        f"{report.ingest_status}."
    )
    stored = _stored_gates(fx, report.submission_id)
    assert stored["v4_match"] == "not_run", (
        f"TC-INGEST-C08: v4 recorded {stored['v4_match']!r} where nothing was "
        "bound — 'not_run' is the honest outcome."
    )
    assert stored["v0_integrity"] == "pass" and stored["v1_pages"] == "pass" \
        and stored["v2_structure"] == "pass" and stored["v3_identity"] == "pass", (
        f"TC-INGEST-C08: the early gates recorded {stored}."
    )
    fx.close()
