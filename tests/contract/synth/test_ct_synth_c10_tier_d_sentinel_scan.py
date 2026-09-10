"""`TC-SYNTH-C10` — no narrative prose anywhere in the permanent tier (§6.11.13).

`CT-SYNTH-10`'s security clause, the direction the leak actually takes: narratives
live in Tier R as student PII and are purged with it — and **no consumer copies
narrative text into Tier D**. The leak is not the narrative row (that purge is
`TC-SYNTH-11`'s); it is a promoted audit record, a stats figure, an exported blob —
any Tier D surface that quietly carries the prose the purge can never reach. The
oracle is a **sentinel scan over ALL of Tier D** after a full run plus promotion:
every table, every row, every column, none of the run's narrative sentinels.

The sentinels are the case's own distinctive tokens (`TIERD-SENTINEL-Q<n>` inside
each L1 text, `TIERD-SENTINEL-L2` in the L2 text): a fixture-only token cannot
occur in Tier D by accident, so the scan is decisive against anything that runs
through it — and honest cited-span promotion (which carries evidence, not the
narrative's own words) passes it.

Two halves, stated honestly:

- **The store half (rung 2, green).** The promotion here is the SYNTHETIC gate
  fixture (`_promote`: the `TC-SYNTH-11` mechanics) whose values carry no prose by
  construction — no consumer path is exercised by it. What it proves is where prose
  is ALLOWED to live: the run's own narrative rows were on disk, the cohort was
  purged, and the durable tier holds none of the prose. The green half alone cannot
  turn a careless consumer red.
- **The consumer half (rung 3, written ahead).** The trip wire for the promotion
  path itself: the REAL `M-STATS` promotion runs over the sentinel-bearing world,
  the same full-Tier-D scan sweeps what it wrote, and the promotion's own report
  carries figures, never narrative text. When `M-STATS.promote` (#118) lands and
  copies whole narratives rather than cited spans, THIS test goes red. Registered
  in `WRITTEN_AHEAD_BLOCKERS` under `"#100 promotion consumer (C10)"`.

Relationship to shipped cases: `tests/security/synth/test_narrative_tier_r_purge.py`
(`TC-SYNTH-11`) holds narratives-are-purged-with-the-cohort and the AUDIT RECORD's
prose absence. This case widens the scan to every Tier D table (a copy into any
other durable table — `label`, `criterion_stats`, a future consumer's table — is
the same leak) and asserts the narrative rows were on disk before the purge, so
the absence after it is a purge and not a never-stored.

Isolation: rung 2 for the store half (real SQLite; Tier D's promotion gates given
through the same independent-connection mechanics `TC-SYNTH-11` uses — raw `sqlite3`
DDL through `store.durable_path()`); rung 3 for the consumer half, written ahead of
`M-STATS`'s promotion.
"""

from __future__ import annotations

import sqlite3

import pytest

from aeh.store import open_store
from tests.support.impl import STATS_MODULE, SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.contract]

_SUBMISSION = "SYN-001"
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))

#: The distinctive prose the run stores — the sentinel tokens the Tier D scan
#: sweeps for. A Tier D surface carrying ANY of them carried the narrative.
_L1_TEXTS = {
    question: (
        f"TIERD-SENTINEL-{question}: the response states the hypothesis and cites "
        "the worked steps for this question."
    )
    for question in _QUESTIONS
}
_L2_TEXT = "TIERD-SENTINEL-L2: overall, the submission works through each question in turn."
SENTINELS = tuple(_L1_TEXTS.values()) + (_L2_TEXT,)

PROMOTE_DDL = (
    "ALTER TABLE audit_record ADD COLUMN cohort_id TEXT",
    "ALTER TABLE label ADD COLUMN cohort_id TEXT",
    "ALTER TABLE criterion_stats ADD COLUMN cohort_id TEXT",
)


def _promote(store, cohort_id: str) -> None:
    """Give Tier D the three promotion gates, through an independent connection —
    the `TC-SYNTH-11`/`test_tc_store_11` mechanics, verbatim in shape."""
    store.durable()
    with sqlite3.connect(store.durable_path()) as raw:
        for ddl in PROMOTE_DDL:
            try:
                raw.execute(ddl)
            except sqlite3.OperationalError as error:
                if "duplicate column" not in str(error).lower():
                    raise
        raw.execute(
            "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, "
            "profile_summary, cohort_id) VALUES (?, ?, 't', 'p', ?)",
            (f"a-{cohort_id}", "run-1", cohort_id),
        )
        raw.execute(
            "INSERT INTO label (label_id, run_id, student_ref, criterion_id, "
            "label_type, band, cohort_id) VALUES (?, 'run-1', 'ref-1', 'CRIT-1', "
            "'human', 'b1', ?)",
            (f"l-{cohort_id}", cohort_id),
        )
        raw.execute(
            "INSERT INTO criterion_stats (package_version_id, criterion_id, "
            "backend_profile, panel_build_ref, n, cohort_id) VALUES (?, 'c', 'bp', "
            "?, 5, ?)",
            (f"pv-{cohort_id}", f"pb-{cohort_id}", cohort_id),
        )


def _tier_d_hits(store) -> list[str]:
    """Every Tier D cell carrying one of the run's sentinels — the full scan, shared
    by both halves: every table, every row, every column."""
    with sqlite3.connect(store.durable_path()) as raw:
        tables = [
            row[0]
            for row in raw.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        if not tables:
            return ["<no tables: nothing was scanned>"]
        hits: list[str] = []
        for table in tables:
            columns = [info[1] for info in raw.execute(f"PRAGMA table_info({table})")]
            for row in raw.execute(f"SELECT * FROM {table}"):
                for value in row:
                    text = (
                        value.decode("utf-8", "ignore")
                        if isinstance(value, bytes)
                        else str(value)
                    )
                    for sentinel in SENTINELS:
                        if sentinel in text:
                            hits.append(f"{table}.{columns[0]}: {sentinel[:40]}")
        return hits


def test_tc_synth_c10_no_narrative_sentinel_survives_into_tier_d(tmp_data_dir):
    """`TC-SYNTH-C10` (P0) — a full run's narratives existed (stored on disk, then
    proven present), the cohort was promoted and purged, and a scan of EVERY Tier D
    table finds none of the run's prose: the permanent tier carries no narrative
    text, so no consumer can reach one the purge cannot delete."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(
            store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA
        )
        seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS))
        replies = [
            narrative_completion(_L1_TEXTS[q], (f"{q}C1", f"{q}C2")) for q in _QUESTIONS
        ] + [narrative_completion(_L2_TEXT)]
        Worker(store, CaptureProvider(replies), synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )

        # The prose was really on disk before the purge — the absence after is a
        # purge, not a never-stored.
        stored = store.cohort(COHORT_ID).query(
            "SELECT text FROM narrative WHERE run_id = :r", r=run_id
        )
        assert len(stored) == 6, (
            f"{len(stored)} narrative rows before the purge — the sentinel scan "
            "needs the run's prose actually stored first"
        )
        for row in stored:
            assert any(sentinel in row["text"] for sentinel in SENTINELS), (
                "fixture bug: a stored narrative carries no sentinel — the scan "
                "would pass vacuously"
            )

        _promote(store, COHORT_ID)
        store.purge_cohort(COHORT_ID)
    finally:
        store.close()

    # Post-purge, the durable tier is scanned IN FULL: every table, every row,
    # every column — the direction the leak would take is a consumer's copy, and
    # a copy can land in any table.
    store = open_store(tmp_data_dir)
    try:
        hits = _tier_d_hits(store)
        assert not hits, (
            f"narrative prose survives in Tier D at {hits[:4]} — NFR-SYNTH-04: "
            "only cited spans are promoted to the audit record, and NO consumer "
            "copies narrative text into the permanent tier; a surviving copy is "
            "student PII the purge can never reach (CT-SYNTH-10, CT-STORE-09)"
        )
    finally:
        store.close()


@pytest.mark.writtenahead
def test_tc_synth_c10_the_promotion_consumer_promotes_cited_spans_not_prose(
    tmp_data_dir,
):
    """`TC-SYNTH-C10` (P0, rung 3 consumer half) — the trip wire the synthetic
    promotion cannot be: the REAL `M-STATS` promotion runs over the sentinel-bearing
    world, and the same full-Tier-D scan finds none of the run's prose. Only cited
    spans (evidence, never the narrative's own words) may cross into the permanent
    tier (`NFR-SYNTH-04`), so a promotion that copies whole narratives — into
    `package_validation`, an audit record, or any figure it reports — goes red here,
    in the one direction the green half's gate fixture cannot observe.

    Written ahead of `M-STATS` (test plan §8.2); registered in
    `WRITTEN_AHEAD_BLOCKERS` under `"#100 promotion consumer (C10)"` (symbol
    `aeh.stats:promote`, the same #118-only key the shipped `"#118 stats"` entry
    uses — `promote` is a `ValidationStats` member in the design's interface, so
    the module-level stand-in is disclosed here and reconciles when the story
    lands). The stats surface is `open_stats(data_dir=..., cohort_id=...)`
    (`tests/support/stats_vocabulary.py`), and the promotion's return — the design's
    `ValidationUpdate` — is swept like the tier: figures, never prose.
    """
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    require(STATS_MODULE, "promote", issue="#118")  # the member this sweep drives

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(
            store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA
        )
        seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS))
        replies = [
            narrative_completion(_L1_TEXTS[q], (f"{q}C1", f"{q}C2")) for q in _QUESTIONS
        ] + [narrative_completion(_L2_TEXT)]
        Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
        Worker(store, CaptureProvider(replies), synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )
        stored = store.cohort(COHORT_ID).query(
            "SELECT text FROM narrative WHERE run_id = :r", r=run_id
        )
        assert len(stored) == 6, (
            f"{len(stored)} narrative rows before the promotion — the sweep needs "
            "the run's prose actually stored first, or it passes vacuously"
        )

        # The real promotion, over the sentinel-bearing world.
        stats = open_stats(data_dir=tmp_data_dir, cohort_id=COHORT_ID)
        update = stats.promote(COHORT_ID)

        # The promotion's own report surface: figures, never narrative prose.
        fields = vars(update) if hasattr(update, "__dict__") else dict(update)
        offenders = [
            name for name, value in fields.items()
            if any(sentinel in str(value) for sentinel in SENTINELS)
        ]
        assert not offenders, (
            f"the promotion report carries narrative prose in {offenders} — only "
            "cited spans are promoted to the audit record (NFR-SYNTH-04); a "
            "ValidationUpdate that quotes the narrative quotes student PII the "
            "purge can never reach (CT-SYNTH-10)"
        )
    finally:
        store.close()

    # And whatever the promotion wrote to the permanent tier: the same full scan
    # the green half runs — every table, every row, every column.
    store = open_store(tmp_data_dir)
    try:
        hits = _tier_d_hits(store)
        assert not hits, (
            f"the promotion copied narrative prose into Tier D at {hits[:4]} — "
            "only cited spans are promoted (NFR-SYNTH-04, CT-SYNTH-10): a "
            "consumer that copies whole narratives downstream publishes exactly "
            "the PII the purge can never reach"
        )
    finally:
        store.close()
