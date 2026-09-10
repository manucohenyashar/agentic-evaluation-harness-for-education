"""`TC-SYNTH-C14` — prose is not reproducible, and nothing downstream diffs it (§6.11.13).

`CT-SYNTH-14` is a **non-promise**: narrative text is not reproducible across runs.
The case makes it vary — the same verdicts, synthesized twice, returning different
but valid prose — and asserts the pipeline **still behaves**: both drives complete
with well-formed reports, nothing normalizes or rejects the variation, and no
golden file pins the prose. Then the misuse the clause names, at rung 3: neither
`M-STATS` nor `M-CONFORM` **diffs narratives to detect a change in scoring**. A
narrative diff would report a scoring change on every run — prose varies by
construction — and would be abandoned as noisy, taking the real signal with it.

Three oracles:

- **Varied prose is valid prose** — two identically-seeded submissions driven under
  different providers produce disjoint prose sets, both reports well-formed, both
  stored. Any normalization, rejection, or failure counting on prose difference
  turns this red.
- **No golden file** — the repo holds no checked-in file mentioning the varied
  prose: an artifact assertion over every repository file (this module's own source
  excepted — it names the sentinels to scan for). Paired with the drive above
  (arbitrary prose stores cleanly), this is what "no golden file pins narrative
  prose" can honestly assert.
- **The comparison consumers** (`M-STATS`, `M-CONFORM`, rung 3, written ahead) —
  `M-STATS`'s scoring input surface (`admissible_labels`, the single filter every
  figure routes through) is byte-identical across prose-variant stores, and
  `M-CONFORM`'s divergence axes are exactly the five declared verdict/score
  dimensions: no narrative-prose axis exists to diff, and a prose-only difference
  blocks nothing.

Relationship to shipped cases: `tests/contract/prov/test_nonpromise_determinism.py`
owns the provider-level determinism non-promise; `TC-SYNTH-C10` owns the sentinel
scan over the STORE tier. This case owns the CONSUMER tier: the same variation,
asserted harmless downstream.

Isolation: rung 2 for the drives (real SQLite, `CaptureProvider` at the model
boundary) and a repository artifact scan; rung 3 for the consumer sweep, written
ahead of both consumers and registered in `WRITTEN_AHEAD_BLOCKERS` under
`"#100 comparison consumers (C14)"`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aeh.store import open_store
from tests.support import stats_vocabulary as stats_vocab
from tests.support.impl import CONFORM_MODULE, STATS_MODULE, SYNTH_MODULE, require
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

_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))

#: The two prose variants — the same five verdicts, two valid renderings. The
#: sentinels double as the golden-file scan's tokens: distinctive enough that no
#: checked-in file carries them, so a scan hit is a file that pins THIS prose.
_PROSE_A = {
    question: (
        f"PROSE-VARIANT-A-{question}: the response states the hypothesis and "
        "cites the worked steps for this question."
    )
    for question in _QUESTIONS
}
_PROSE_B = {
    question: (
        f"PROSE-VARIANT-B-{question}: the derivation is set out clearly and the "
        "working is shown for this question."
    )
    for question in _QUESTIONS
}
_SENTINELS = ("PROSE-VARIANT-A", "PROSE-VARIANT-B")

#: The directories an artifact scan skips: VCS internals, caches, and the virtualenv
#: hold no golden files, and reading .venv's thousands of files is waste.
_SCAN_SKIP_DIRS = {".git", "__pycache__", ".venv", ".pytest_cache", "node_modules", ".claude"}


def _replies(variant: dict[str, str], l2_text: str) -> list:
    replies = [
        narrative_completion(variant[q], (f"{q}C1", f"{q}C2")) for q in _QUESTIONS
    ]
    replies.append(narrative_completion(l2_text))
    return replies


def _variant_a_replies() -> list:
    return _replies(
        _PROSE_A, "PROSE-VARIANT-A-L2: overall, the submission works through each question in turn."
    )


def _variant_b_replies() -> list:
    return _replies(
        _PROSE_B, "PROSE-VARIANT-B-L2: overall, the submission addresses every question in sequence."
    )


def _seeded_store(tmp_data_dir, submission_id: str):
    """A store with ONE submission's verdicts, seeded identically every time — the
    two drives below differ only in the prose their providers return."""
    store = open_store(tmp_data_dir)
    _, run_id, _ = seed_run(store, submissions=(submission_id,), criteria=FIVE_QUESTION_CRITERIA)
    seed_scored_submission(store, run_id, submission_id, complete_questions=set(_QUESTIONS))
    return store, run_id


def _l1_texts(store, run_id: str, submission_id: str) -> set[str]:
    rows = store.cohort(COHORT_ID).query(
        "SELECT text FROM narrative WHERE run_id = :r AND submission_id = :s "
        "AND level = 'l1_question'",
        r=run_id, s=submission_id,
    )
    return {row["text"] for row in rows}


def test_tc_synth_c14_the_same_verdicts_admit_different_valid_prose(tmp_data_dir):
    """`TC-SYNTH-C14` (P1) — the same verdict evidence synthesized under two
    providers returns disjoint, valid prose: both drives complete (6 calls, 6
    narratives, zero failures, zero rejections), and the stored L1 prose sets are
    disjoint. Nothing normalized the prose toward one canon and nothing treated the
    variation as a failure — the non-promise, held open."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store_a, run_a = _seeded_store(tmp_data_dir / "a", "SYN-001")
    store_b, run_b = _seeded_store(tmp_data_dir / "b", "SYN-001")
    try:
        report_a = Worker(
            store_a, CaptureProvider(_variant_a_replies()), synth_ref()
        ).synthesize_submission(run_a, "SYN-001")
        report_b = Worker(
            store_b, CaptureProvider(_variant_b_replies()), synth_ref()
        ).synthesize_submission(run_b, "SYN-001")

        for label, report in (("A", report_a), ("B", report_b)):
            assert report.model_calls == 6 and report.narratives == 6 and report.failures == 0, (
                f"variant {label}'s drive is {report.model_calls} calls / "
                f"{report.narratives} narratives / {report.failures} failures — the "
                "second rendering must be as valid as the first: narrative "
                "non-reproducibility (CT-SYNTH-14) means varied prose is normal "
                "operation, not an error to count"
            )
            assert report.rejected_score_claims == 0, (
                f"variant {label}'s prose was rejected as score-claiming — a "
                "normalization that pushes varied prose toward a canonical text "
                "would surface exactly here, as a rejection the report counts"
            )
            assert report.sample and report.sample_size >= 1, (
                "the quality sample ran on the varied-prose drive too — the "
                "measurement does not depend on the prose matching anything"
            )

        texts_a = _l1_texts(store_a, run_a, "SYN-001")
        texts_b = _l1_texts(store_b, run_b, "SYN-001")
        assert texts_a and texts_b, "both drives must store their prose"
        assert texts_a.isdisjoint(texts_b), (
            "the two runs' prose sets overlap — normalization (or a shared canned "
            "text) collapsed the variation the case exists to make; the same "
            "verdicts must admit different valid prose"
        )
    finally:
        store_a.close()
        store_b.close()


def test_tc_synth_c14_no_golden_file_pins_the_narrative_prose(repo_root):
    """`TC-SYNTH-C14` (P1, artifact half) — no checked-in file mentions the varied
    prose: scanned over every repository file (this module excepted — it names the
    sentinels), neither variant token appears anywhere. A golden file that pinned
    narrative prose would carry the prose a run must reproduce; the varied-prose
    drive above stores cleanly, and this scan asserts no such file exists to be
    diffed against. Paired, the two halves hold the non-promise from both sides."""
    this_file = Path(__file__).resolve()
    hits: list[str] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file() or path == this_file:
            continue
        if any(part in _SCAN_SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_bytes().decode("utf-8", "ignore")
        except OSError:
            continue
        for sentinel in _SENTINELS:
            if sentinel in text:
                hits.append(str(path.relative_to(repo_root)))
    assert not hits, (
        f"these repository files mention the varied-prose sentinels {hits} — a "
        "golden file pinning narrative prose: narrative text is NOT reproducible "
        "across runs (CT-SYNTH-14), and a file the prose is diffed against would "
        "report a change on every run and be abandoned as noisy, taking the real "
        "signal with it"
    )


@pytest.mark.writtenahead
def test_tc_synth_c14_the_comparison_consumers_do_not_diff_narratives(tmp_data_dir):
    """`TC-SYNTH-C14` (P1, rung 3 consumer sweep) — neither `M-STATS` nor
    `M-CONFORM` diffs narratives to detect a change in scoring:

    - `M-STATS`: two prose-variant stores (identical verdicts/scores, disjoint
      narrative prose) yield byte-identical `admissible_labels` — the single filter
      every figure routes through (`NFR-STATS-04`) — and identical figures built
      from them. If a label record carried narrative text, the fingerprints would
      split and a scoring figure would move with the prose.
    - `M-CONFORM`: the divergence report's axes are exactly the five declared
      verdict/score dimensions — there is no narrative-prose axis to diff — and a
      full two-backend run over the fixture corpus (whose canned prose varies by
      construction) reports no gate failure.

    Written ahead of both consumers (test plan §8.2); registered in
    `WRITTEN_AHEAD_BLOCKERS` under `"#100 comparison consumers (C14)"` (symbols
    `aeh.stats:open_stats`, `aeh.conform:detect_build_substitution` — the #134-only
    symbol, per the shipped `"#134"` entry's keying, since the suite constructor is
    the one both conform stories need and an early unmark would precede #134).
    """
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")

    # --- the two prose-variant stores ------------------------------------------------
    store_a, run_a = _seeded_store(tmp_data_dir / "a", "SYN-001")
    store_b, run_b = _seeded_store(tmp_data_dir / "b", "SYN-001")
    try:
        Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
        Worker(store_a, CaptureProvider(_variant_a_replies()), synth_ref()).synthesize_submission(
            run_a, "SYN-001"
        )
        Worker(store_b, CaptureProvider(_variant_b_replies()), synth_ref()).synthesize_submission(
            run_b, "SYN-001"
        )
        texts_a = _l1_texts(store_a, run_a, "SYN-001")
        texts_b = _l1_texts(store_b, run_b, "SYN-001")
        assert texts_a and texts_b and texts_a.isdisjoint(texts_b), (
            "precondition: the two stores must carry disjoint narrative prose over "
            "identical verdicts, or the consumer sweep below proves nothing"
        )
    finally:
        store_a.close()
        store_b.close()

    # --- M-STATS: the scoring input surface is invariant to prose --------------------
    stats_a = open_stats(data_dir=tmp_data_dir / "a", cohort_id=COHORT_ID)
    stats_b = open_stats(data_dir=tmp_data_dir / "b", cohort_id=COHORT_ID)
    labels_a = stats_a.admissible_labels()
    labels_b = stats_b.admissible_labels()
    assert labels_a, (
        "open_stats found no admissible labels in the driven store — the sweep "
        "needs the scoring surface populated; if the figure is NoValidationData "
        "here, this case's keying needs the criterion the store actually holds"
    )
    assert _fingerprint(labels_a) == _fingerprint(labels_b), (
        "M-STATS's admissible-label surface differs between two stores whose only "
        "difference is narrative prose — a label record is carrying narrative text, "
        "which is the misuse CT-SYNTH-14 names: a narrative diff would report a "
        "scoring change on every run and be abandoned as noisy"
    )

    figure_a = build_stats_from_labels(labels_a)
    figure_b = build_stats_from_labels(labels_b)
    assert figure_a == figure_b, (
        f"the figures differ across prose-variant stores ({figure_a!r} vs "
        f"{figure_b!r}) — the figures must be a function of the labels alone; a "
        "narrative-similarity term moves a scoring figure with the prose"
    )

    # --- M-CONFORM: the comparison axes are the five declared, never prose -----------
    from aeh.conf import CohortRef
    from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg
    from tests.support.conform_vocabulary import DIVERGENCE_DIMENSIONS

    report = build_suite().run(
        "v1",
        [edge_cfg(panel=EDGE_PANEL_3), hosted_cfg(panel=HOSTED_PANEL_3)],
        cohort=CohortRef(cohort_id="c-synth-c14", consent_class="synthetic"),
    )
    divergence = report.divergence
    assert set(divergence.dimensions) == DIVERGENCE_DIMENSIONS, (
        f"the divergence report compares on {sorted(divergence.dimensions)} — "
        "CT-CONFORM-04's five verdict/score dimensions are the only axes, and a "
        "narrative-prose axis (or a prose-diff smuggled into a declared one) is "
        "exactly the misuse CT-SYNTH-14 forbids: the comparison sources from "
        "verdicts and scores, never from narrative text"
    )
    assert not report.blocked, (
        "the two-backend run over prose-bearing fixtures reported a gate failure — "
        "varied narrative prose must not read as a conformance finding"
    )


def build_stats_from_labels(labels):
    """The figures, from the extracted labels alone — the in-memory rung (#115)."""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    return build_stats(labels=labels).agreement(**stats_vocab.EMPTY_DATA_CALL["agreement"])


def _fingerprint(labels) -> tuple:
    """Every label record's FULL field set, sorted — a fingerprint that changes if
    any field, narrative text included, changes between the two stores."""
    records = []
    for label in labels:
        fields = label if isinstance(label, dict) else vars(label)
        records.append(tuple(sorted((str(key), repr(value)) for key, value in fields.items())))
    return tuple(sorted(records))
