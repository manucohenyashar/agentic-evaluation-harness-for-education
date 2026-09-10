"""`TC-AGG-C11` — `criterion_score` and nothing else, in both directions (§6.11.12).

`CT-AGG-11`: "Writes `criterion_score` and nothing else. It has **no** write path to
`narrative`, and `M-SYNTH` has none to `criterion_score`: the two write sets are
disjoint (`FR-AGG-14`, §7.2 Rule 3)." The clause pairs with `CT-SYNTH-07` and both
stay, because the failure is the two write sets MERGING, and each clause only sees
half of it. This file carries the `M-AGG` half in both of the case's limbs:

- **the bidirectional artifact assertion** (static): `aeh.agg`'s text carries no
  write statement against `narrative`, and `aeh.synth`'s carries none against
  `criterion_score` — normalized over the whole module text, so a statement split
  across lines cannot evade the scan. The scanner is validated against a positive
  control first: a synthetic write to each forbidden table must be flagged;
  cross-referenced, not duplicated: the shipped artifact sibling
  `tests/artifact/test_agg_synth_write_sets.py` (`TC-AGG-16`, #95) is the
  structural guard over ALL of `src/aeh`, statement-literal-scoped; this limb
  re-asserts the same disjointness from the contract side over the WHOLE module
  text (a write assembled outside a string literal evades a literal scan) and
  runs both directions in one place, which is the contract case's named shape;
- **the rung-3 write audit** (dynamic): under `install_audit` over a real driven
  run, the whole pure surface — aggregate over the run's stored verdict rows,
  `recompute_confidence`, `should_escalate`, `ordinal_alpha`,
  `describe_agreement` — logs zero writes attributed to `aeh.agg`, and no write
  against `narrative` at all. The positive control: the sanctioned persistence of
  the module's own output (the test's `criterion_score` INSERT) IS recorded —
  attributed to the caller, `tests:` — proving the audit was watching while the
  negative held.

Isolation: rung 3 — real store, real workers; the socket guard is autouse.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.agg._drive import (
    criterion_bands,
    drive_scored_run,
    stored_verdicts,
)
from tests.contract.orch._doubles import install_audit
from tests.support.agg_vocabulary import (
    criterion,
    criterion_history,
    expected_distribution,
    signals,
    agg_config,
)
from tests.support.impl import AGG_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract]

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C11"
_CRITERION = "C1"

_INSERT = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing, confidence, confidence_base, "
    "spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk) "
    "VALUES (:sid, :cid, :band, :points, :judge_count, :agreement, :state, "
    ":routing, :confidence, :confidence_base, :spans_verified, "
    ":evidence_present, :sufficiency_flag, :ocr_overlap_risk)"
)


def _write_paths(module_text: str, table: str) -> list[str]:
    """The write statements against `table` in one module's text, found over the
    whitespace-normalized text so a statement wrapped across lines cannot evade
    the scan. Reads (`SELECT`) never match: the clause forbids write paths, and
    an over-broad scan would go red against a compliant module."""
    normalized = " ".join(module_text.split())
    upper = normalized.upper()
    return [
        statement for statement in (
            f"INSERT INTO {table}",
            f"INSERT OR REPLACE INTO {table}",
            f"UPDATE {table} SET",
            f"DELETE FROM {table}",
        ) if statement.upper() in upper
    ]


def test_tc_agg_c11_the_write_sets_are_disjoint_in_both_directions_statically():
    """`TC-AGG-C11` (`CT-AGG-11`, `FR-AGG-14`, §7.2 Rule 3, artifact assertion,
    P0) — `aeh.agg` declares no write against `narrative`, and `aeh.synth` none
    against `criterion_score`: the two write sets are disjoint, asserted in both
    directions, because the failure is the merge and each clause only sees half of
    it."""
    from pathlib import Path

    import aeh

    src = Path(aeh.__file__).parent
    agg_text = (src / "agg.py").read_text(encoding="utf-8")
    synth_text = (src / "synth.py").read_text(encoding="utf-8")

    # Positive controls: the scanner flags the defect in each direction.
    assert _write_paths("INSERT INTO narrative (narrative_id) VALUES ('x')",
                        "narrative"), (
        "fixture bug: the scanner no longer detects a write to the forbidden table"
    )
    assert _write_paths("UPDATE criterion_score SET confidence = 0.5", "criterion_score"), (
        "fixture bug: the scanner no longer detects a write to the forbidden table"
    )
    assert _write_paths("SELECT narrative FROM x", "narrative") == [], (
        "fixture bug: the scanner flags reads — the clause forbids write paths, "
        "and an over-broad scan would go red against a compliant module"
    )

    from_agg = _write_paths(agg_text, "narrative")
    from_synth = _write_paths(synth_text, "criterion_score")
    assert from_agg == [], (
        f"aeh.agg declares write path(s) to narrative: {from_agg} — the score "
        "and the story are different tables (CT-AGG-11, §7.2 Rule 3); a narrative "
        "that could write a score would be a second, competing grade (RISK-19)"
    )
    assert from_synth == [], (
        f"aeh.synth declares write path(s) to criterion_score: {from_synth} — "
        "M-SYNTH has no write path to the score table: the two write sets are "
        "disjoint in this direction too (CT-AGG-11's reciprocal arm; pairs with "
        "CT-SYNTH-07)"
    )


def test_tc_agg_c11_the_pure_surface_writes_nothing_under_a_rung3_audit(
    tmp_data_dir, make_fixture_provider
):
    """`TC-AGG-C11` (`CT-AGG-11`, contract / rung 3, write-audit log, P0) — under
    the audit over a real driven run's ledger, the whole pure surface evaluated
    over real stored rows logs zero writes attributed to `aeh.agg` and zero writes
    against `narrative`; the positive control — the sanctioned persistence of the
    module's output — IS recorded, to the caller's frame."""
    aggregate, should_escalate, recompute_confidence, ordinal_alpha, describe_agreement = (
        require(AGG_MODULE, "aggregate", "should_escalate", "recompute_confidence",
                "ordinal_alpha", "describe_agreement", issue="#92")
    )

    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = drive_scored_run(store, provider, submissions=(_SUBMISSION,))
        rows = stored_verdicts(store, run_id, _SUBMISSION, _CRITERION)
        crit = criterion(criterion_bands(store, _CRITERION), criterion_id=_CRITERION)
        cohort_audit, durable_audit = install_audit(store, _COHORT)

        score = aggregate(rows, crit, signals(), config=agg_config())
        decision = should_escalate(
            score=score, criterion=crit, history=criterion_history(),
            baseline=expected_distribution(), config=agg_config(),
        )
        figure = ordinal_alpha(rows)
        text = describe_agreement(
            figure={"ordinal_alpha": figure, "band_count": crit.band_count,
                    "degenerate_band_shape": crit.band_count < 3},
            population="y9-2026-spring",
        )
        assert score.band and decision is not None and text, (
            "fixture bug: the pure surface did not run, so the audit below "
            "guarded nothing"
        )

        cohort = store.cohort(_COHORT)
        with cohort_audit.transaction() as tx:
            # The sanctioned persistence of the module's output — the write the
            # clause's sole-writership names, from the caller's frame.
            tx.execute(
                _INSERT,
                sid=_SUBMISSION, cid=_CRITERION, band=score.band, points=score.points,
                judge_count=score.judge_count, agreement=score.agreement,
                state=score.state, routing=score.routing, confidence=score.confidence,
                confidence_base=score.confidence_base,
                spans_verified=score.spans_verified,
                evidence_present=score.evidence_present,
                sufficiency_flag=score.sufficiency_flag,
                ocr_overlap_risk=score.ocr_overlap_risk,
            )

        writes = cohort_audit.writes + durable_audit.writes
        assert writes, (
            "the audit logged no writes at all — the positive control failed, so "
            "the negative assertions below would be vacuous"
        )
        assert any(w.module.startswith("tests:") for w in writes), (
            f"the audit attributed {sorted({w.module for w in writes})} — the test's "
            "own INSERT must be visible for the exclusion below to mean anything"
        )
        offenders = [w for w in writes if w.module == "aeh.agg"]
        assert offenders == [], (
            f"the aggregation surface wrote {offenders} — `aeh.agg` computes "
            "values; the persistence of `criterion_score` is its consumer's "
            "write, and the module itself enqueues nothing (CT-AGG-11)"
        )
        narrators = [w for w in writes if w.table == "narrative"]
        assert narrators == [], (
            f"the aggregation path wrote to narrative: {narrators} — the write "
            "sets have merged (CT-AGG-11, RISK-19)"
        )
    finally:
        store.close()
