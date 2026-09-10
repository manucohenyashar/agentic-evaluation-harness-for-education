"""`TC-JUDGE-C08` — the batch's invariant prefix is byte-identical (§6.11.10).

`CT-JUDGE-08` (behaviour): *"Assert every submission in a `(judge, question,
criterion)` batch is judged against a **byte-identical** invariant prefix — system
prompt, judge instructions, question text, reference solution, criterion definition,
exemplars. Assemble the whole batch and compare prefixes **byte for byte**, which is
the clause's own stated acceptance form. This is simultaneously the fairness
guarantee and the prefix-cache precondition, so the case asserts both readings:
identical treatment across students, and the precondition `CT-JUDGE-13` depends on
(RISK-23)."* (plan §6.11.10, verbatim)

The case's own limb, over a REAL driven batch at the full panel depth: a
`holistic` criterion enumerates one score unit per panel arm (base depth 3), so one
drive carries nine requests — three judges, each judging the same three submissions.
Each captured payload is the request its dispatch actually sent
(`drive_score_captured`), and the differential compares:

- **within a judge** (its batch of three submissions): the fields before the last
  are byte-identical and the tails pairwise distinct — identical treatment across
  students, with per-submission material confined to the tail (`FR-JUDGE-06`,
  `FR-JUDGE-07`);
- **across judges** (the three judges' batches over the same question and
  criterion): the prefixes are byte-identical there too — the render carries no
  judge identity, so the whole batch is ONE prefix cohort, exactly the body the
  prefix cache (`CT-JUDGE-13`, RISK-23) reuses;
- **the tail varies only with the submission**: the same submission's tail is
  byte-identical across judges — the extraction is judge-independent
  (`CT-EXTRACT-03`), so nothing judge-shaped leaks into the tail either.

One exemplar rides the version so the prefix carries real rubric material; the
fixture runs question-less (the shipped convention), where the question element
renders as its constant "(no question: the criterion grades the submission
directly)" — still an invariant element of the prefix.

Cross-references, not duplicates: `TC-JUDGE-12`'s shipped file
(`tests/artifact/test_no_numerals_in_judge_prompt.py`) sweeps the render-level
prefix identity at the plan's precondition scale (350 × 15 batches); the live
token-share threshold is `TC-JUDGE-21`'s (the security suite, never executed in
the fast tier). This file is the clause's contract form — the byte-identity
differential over a driven batch at the real dispatch boundary, both readings.

Isolation: rung 2 — real store, real workers, transport double at the model
boundary (the payload identity is what the fixture key collapses, so the double
records what it was sent); the socket guard is autouse.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.contract.judge._drive import (
    RecordingTransport,
    drive_extract,
    drive_score_captured,
    seed_world,
)
from tests.support.extract_vocabulary import verdict_completion
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import fields_of

pytestmark = [pytest.mark.contract]

#: The story that owns the render (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

_SUBMISSIONS = ("SYN-001", "SYN-002", "SYN-003")

#: One document per submission — textually distinct, so the tail (which carries the
#: submission itself) is distinct per submission and the differential below is
#: non-vacuous: identical prefixes can only mean identical treatment, not identical
#: submissions. Numeral-free, per the suite's own prohibition (CT-JUDGE-03).
_TEXTS = (
    "The evidence supports the conclusion, with the caveats noted in section two "
    "of the cited report. The crate holds because static friction balances the "
    "along-slope pull; the diagram in section one shows the contact surface.",
    "The evidence supports the conclusion, with the caveats noted in section two "
    "of the cited report. The ramp's incline is what the free-body diagram must "
    "show, and the normal force is the balance the answer names.",
    "The evidence supports the conclusion, with the caveats noted in section two "
    "of the cited report. The measurement uncertainty is why the conclusion stays "
    "qualified, as the discussion of error in the final paragraph argues.",
)

#: The `holistic` spec that enumerates the panel's full base depth (one score unit
#: per judge arm) — the batch is per (judge, question, criterion), and this drive
#: carries all three judges' batches over the same question and criterion.
_HOLISTIC = [{
    "criterion_id": "C1", "kind": "open", "scoring_model": "holistic",
    "band_count": 2,
}]


def _fixed_completion() -> Any:
    """One valid verdict completion for every call — the transport's program is
    fixed, so the ONLY thing that varies across the batch's calls is the payload
    the render produced."""
    return verdict_completion(
        "secure", 0.9,
        build_id="build-judge-contract",
        cited_spans=None,
    )


def test_tc_judge_c08_the_batch_is_judged_against_a_byte_identical_prefix(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C08` (`CT-JUDGE-08`, byte-identity differential across a batch,
    rung 2, P0) — the whole driven batch's prefixes are byte-identical, within a
    judge and across judges, while the tails carry the per-submission material:
    the fairness guarantee and the cache precondition, both readings of the same
    bytes."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        orchestrator, _run_id, version = seed_world(
            store, submissions=_SUBMISSIONS, criterion_specs=_HOLISTIC,
            texts=_TEXTS,
        )
        # One exemplar so the prefix carries rubric material, through the shipped
        # catalog door (blob first, then the row).
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        blob_hash = store.blobs().put(
            "a worked answer naming the force at rest".encode("utf-8")
        )
        catalog.add_exemplar(version, "ex-C1", "C1", "secure", blob_hash=blob_hash)

        drive_extract(orchestrator, store, provider)
        transport = RecordingTransport(_fixed_completion())
        judged, captured = drive_score_captured(
            orchestrator, store, transport, record=False
        )
        assert judged == 9, (
            f"fixture bug: the drive judged {judged} units — the batch is three "
            "submissions across the panel's full base depth (nine requests)"
        )

        payload_fn = require(JUDGE_MODULE, "prompt_fields", issue=ISSUE)
        rendered = [
            (unit, judge_ref, fields_of(payload_fn, request))
            for unit, judge_ref, request in captured
        ]

        prefixes_by_judge: dict[str, list[tuple[str, str]]] = {}
        tails_by_judge: dict[str, list[str]] = {}
        tails_by_submission: dict[str, set[str]] = {}
        for unit, judge_ref, fields in rendered:
            prefixes_by_judge.setdefault(judge_ref.build_id, []).append(
                tuple(fields[:-1])
            )
            tails_by_judge.setdefault(judge_ref.build_id, []).append(fields[-1])
            tails_by_submission.setdefault(unit.submission_id, set()).add(
                fields[-1]
            )
        assert len(prefixes_by_judge) == 3, (
            f"fixture bug: the batch grouped into {len(prefixes_by_judge)} judge(s) "
            "— the differential needs the panel's three judges"
        )

        # The fairness reading: within a judge's batch, every submission is judged
        # against the SAME prefix bytes, and the per-submission material is the
        # tail's alone.
        for build_id, prefixes in prefixes_by_judge.items():
            assert len(set(prefixes)) == 1, (
                f"judge {build_id}'s batch carries {len(set(prefixes))} distinct "
                "prefix(es) — a submission judged against a different instruction "
                "set than its batch-mates is the fairness failure (CT-JUDGE-08)"
            )
            assert len(set(tails_by_judge[build_id])) == 3, (
                f"judge {build_id}'s batch carries "
                f"{len(set(tails_by_judge[build_id]))} distinct tail(s) for three "
                "submissions — per-submission material must reach the tail, or the "
                "batch cannot be told apart (CT-JUDGE-08, FR-JUDGE-07)"
            )

        # The cache-precondition reading: the prefix is byte-identical across the
        # WHOLE batch — the render carries no judge identity, so the three judges'
        # batches share one cache body (CT-JUDGE-13's precondition, RISK-23).
        cohort_prefixes = {
            prefix for prefixes in prefixes_by_judge.values() for prefix in prefixes
        }
        assert len(cohort_prefixes) == 1, (
            f"the batch carries {len(cohort_prefixes)} distinct prefix(es) across "
            "judges — the invariant prefix is the cache body the whole "
            "(judge, question, criterion) cohort shares (CT-JUDGE-08, RISK-23, "
            "CT-JUDGE-13)"
        )

        # The tail varies ONLY with the submission: three submissions, three tails,
        # and each submission's tail byte-identical across the judges that saw it.
        assert len(tails_by_submission) == 3, (
            f"the batch carried {len(tails_by_submission)} submission(s) — the "
            "differential is over the three-submission batch (CT-JUDGE-08)"
        )
        for submission_id, seen in tails_by_submission.items():
            assert len(seen) == 1, (
                f"submission {submission_id}'s tail differs across judges — the "
                "extraction is judge-independent, so nothing judge-shaped may "
                "leak into the tail (CT-JUDGE-08, CT-EXTRACT-03)"
            )
    finally:
        store.close()