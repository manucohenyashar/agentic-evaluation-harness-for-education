"""`TC-JUDGE-C03` — one criterion, one submission, no numerals, no history (§6.11.10).

`CT-JUDGE-03`: *"Every request carries exactly one criterion and exactly one
submission. The prompt carries no points, no numeric scale, no prior-cohort data,
and no numeral denoting a score anywhere in the prompt."* — a §4.7 safety property
behind RISK-02 and RISK-04. The plan's steps, as implemented here:

1. **exact cardinality**, swept over a full run's assembled requests (three
   submissions at the edge-local base depth — one judged pair each): `criterion_id`
   exactly once and `submission_id` exactly once in every request's name tree;
2. **the numeral scan** over the fully assembled payload — the numeral's route
   into the prompt is through CONTENT, not through a named field, so the scan
   walks the request's string leaves under the TC-PKG-09 boundary this suite
   shares (`judge_vocabulary.offending_numeral`, verbatim-identical boundary);
   plus the named-field half: no `points`, no `max_points`, no `scale` name
   anywhere in the tree;
3. **two-sided discrimination**: the fixture set carries both kinds, so an
   over-broad scanner fails too — "solve 3x + 7 = 22" and "the mass was 12 kg"
   are the question's own numerals and MUST pass; "(4 marks)", a printed score
   and `max_points` leaked through criterion prose MUST fail. The boundary note
   in `judge_vocabulary` states why the two halves are one boundary (RISK-04 is
   one risk with two scan sites, not two risks);
4. **no history**: across criteria for the same submission and across submissions
   for the same judge — the world is planted with per-submission and
   per-criterion sentinels and every assembled request is scanned for the OTHER
   labels, after a full judged drive (a judged run is where a "helpful" carry-over
   would tempt an implementer, so the re-assembly happens after the verdicts exist).

Cross-references, not duplicates: the shipped rung-2 file
`tests/artifact/test_no_numerals_in_judge_prompt.py` sweeps the RENDER side at the
plan's precondition scale (TC-JUDGE-08's 350 × 15 batches); this file is the
plan's contract form — exact cardinality over a real run, the two-sided fixture
set through the REAL store-backed assembly, and the no-history limbs — over the
request VALUE (what `dispatch` sends, not only what the template renders).

Isolation: rung 2 — real store, real package, real workers; the socket guard is
autouse and the completions come from the recorded fixture provider.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.store import open_store
from tests.contract.judge._drive import (
    PANEL_REFS,
    drive_extract,
    judge_units,
    lease_score_units,
    offline_request,
    seed_world,
)
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import (
    field_names,
    offending_numeral,
    string_leaves,
)
from tests.support.orch_run import PLAIN_TRANSCRIPT

pytestmark = [pytest.mark.contract]

#: The story that owns the request schema and the numeral prohibition.
ISSUE = "#78"

#: The named fields the prohibition forbids — no points value can reach the prompt
#: through a field, because no such field exists (the schema half of RISK-04).
_FORBIDDEN_FIELD_NAMES: tuple[str, ...] = ("points", "max_points", "scale")

#: Per-submission document sentinels (step 4, across submissions for one judge):
#: each submission's own document carries its marker (AFTER the fixture
#: transcript, so the extraction spans' byte offsets stay valid), and no request
#: may carry the OTHER submission's marker.
_SUB_SENTINELS = {
    "SYN-001": "HISTORY-SENTINEL-ALPHA",
    "SYN-002": "HISTORY-SENTINEL-BETA",
}

#: Per-criterion exemplar sentinels (step 4, across criteria for one submission).
_CRITERION_SENTINELS = {
    "C1": "EXEMPLAR-SENTINEL-ONE",
    "C2": "EXEMPLAR-SENTINEL-TWO",
}


def _rubric_path(path: str) -> bool:
    """The TC-PKG-09 boundary, applied to a leaf path: rubric surfaces are the
    criterion's own text and the declared band labels/descriptors and exemplar
    band labels; everything else — the question, exemplar payloads, evidence,
    the submission, identity — is content."""
    if path.startswith(".criterion.text"):
        return True
    if path.startswith(".criterion.bands["):
        return path.endswith(".band") or path.endswith(".descriptor")
    if path.startswith(".criterion.exemplars["):
        return path.endswith(".band")
    return False


def _scan_request(request: Any, label: str) -> list[str]:
    """Every numeral the prohibition refuses in one assembled request, with the
    leaf's classification stated in the finding."""
    findings: list[str] = []
    for path, text in string_leaves(request):
        flagged = offending_numeral(text, rubric=_rubric_path(path))
        if flagged is not None:
            findings.append(f"{label}{path}: {flagged!r} in {text[:80]!r}")
    return findings


def test_tc_judge_c03_exact_cardinality_over_a_full_run(tmp_data_dir, make_fixture_provider):
    """`TC-JUDGE-C03` step 1 (`CT-JUDGE-03`, exact cardinality, P0) — every request
    assembled over a full three-submission run carries exactly one `criterion_id`
    and exactly one `submission_id`. Exact counts, not absence checks: two
    criteria in one prompt would carry two `criterion_id`s and read as one."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        orchestrator, _run_id, _version = seed_world(
            store, submissions=("SYN-001", "SYN-002", "SYN-003")
        )
        drive_extract(orchestrator, store, provider)
        units = lease_score_units(orchestrator)
        assert len(units) == 3, (
            f"fixture bug: the drive leased {len(units)} score units — the sweep "
            "below is over a full run's assembled requests (three submissions at "
            "the edge-local base depth: one judged pair per submission)"
        )
        refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
        for unit in units:
            worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                store, None, refs_by_build[unit.judge]
            )
            names = field_names(worker.assemble(unit))
            assert names.count("criterion_id") == 1, (
                f"{unit.work_id[:12]} carries criterion_id {names.count('criterion_id')} "
                "time(s) — exactly one criterion per request (CT-JUDGE-03, FR-JUDGE-02)"
            )
            assert names.count("submission_id") == 1, (
                f"{unit.work_id[:12]} carries submission_id {names.count('submission_id')} "
                "time(s) — exactly one submission per request (CT-JUDGE-03, FR-JUDGE-02)"
            )
    finally:
        store.close()


def test_tc_judge_c03_the_numeral_scan_and_the_named_field_half(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C03` step 2 (`CT-JUDGE-03`, artifact assertion over the assembled
    payload, P0) — the numeral scan over every string leaf of every request
    assembled over the real run, classified by the TC-PKG-09 boundary; plus the
    named-field half: no `points`, no `max_points`, no `scale` name exists in the
    tree at all."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        orchestrator, _run_id, _version = seed_world(
            store, submissions=("SYN-001", "SYN-002", "SYN-003")
        )
        drive_extract(orchestrator, store, provider)
        units = lease_score_units(orchestrator)
        refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
        findings: list[str] = []
        forbidden_names: list[str] = []
        for unit in units:
            worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                store, None, refs_by_build[unit.judge]
            )
            request = worker.assemble(unit)
            findings.extend(_scan_request(request, f"{unit.work_id[:12]}"))
            names = set(field_names(request))
            forbidden_names.extend(
                name for name in names
                if name in _FORBIDDEN_FIELD_NAMES
                or any(f in name for f in _FORBIDDEN_FIELD_NAMES)
            )
        assert findings == [], (
            "the assembled requests carry numeral(s) the prohibition refuses — "
            f"{findings} — a score numeral in a rubric or beside mark vocabulary "
            "anchors the judge's band choice (CT-JUDGE-03, RISK-04; HLD §5.10)"
        )
        assert forbidden_names == [], (
            f"the request tree carries points-scale field name(s) {forbidden_names} "
            "— no points, no max_points, no numeric scale reaches the prompt through "
            "a named field, because no such field exists (CT-JUDGE-03)"
        )
    finally:
        store.close()


def test_tc_judge_c03_two_sided_numeral_discrimination():
    """`TC-JUDGE-C03` step 3 (`CT-JUDGE-03`, two-sided fixture set, P0) — the scan's
    discrimination boundary, driven through the request VALUE under the shared
    TC-PKG-09 boundary: score-denoting numerals in rubric or mark-adjacent content
    are flagged, while the question's own numerals ("solve 3x + 7 = 22") and a
    student's measurement ("the mass was 12 kg") pass. An over-broad scanner would
    corrupt mathematics assessments — the naive case's real failure."""
    # The three routes RISK-04 names, each flagged:
    rubric_hits = {
        "band descriptor '4 marks'": _scan_request(
            offline_request(
                bands=(
                    ("emerging", 0, "the criterion is partly met"),
                    ("secure", 1, "worth 4 marks"),
                )
            ),
            "descriptor",
        ),
        "printed score in an exemplar": _scan_request(
            offline_request(
                exemplars=(("ex-1", "secure", "a strong answer, printed score: 4 out of 4"),),
            ),
            "exemplar",
        ),
        "max_points leaked through criterion prose": _scan_request(
            offline_request(criterion_text="Grade out of 4 marks. States the claim."),
            "criterion",
        ),
    }
    for label, findings in rubric_hits.items():
        assert findings, (
            f"{label} was NOT flagged — the scan cannot see the score numeral it "
            "exists for (CT-JUDGE-03 step 3: the score-numeral fixtures must fail)"
        )

    # The content numerals that are the QUESTION's own must pass.
    legal = _scan_request(
        offline_request(
            question_prompt="Solve 3x + 7 = 22 for x, showing each step.",
            submission_text=(
                "The mass was 12 kg and the crate does not slide because static "
                "friction balances the ramp's along-slope component."
            ),
        ),
        "legal",
    )
    assert legal == [], (
        f"the legal content numerals were flagged: {legal} — an over-broad scanner "
        "corrupts mathematics assessments (CT-JUDGE-03 step 3: content numerals "
        "must pass)"
    )


def test_tc_judge_c03_no_history_across_criteria_or_submissions(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C03` step 4 (`CT-JUDGE-03`, no-history, P0) — after a full judged
    drive (the state where a carry-over would tempt), every request re-assembled
    from the store carries none of the OTHER submission's or OTHER criterion's
    sentinel — and each carries its OWN, so the scan is not vacuous (the sentinel
    discipline TC-JUDGE-20's fixture states)."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        submissions = ("SYN-001", "SYN-002")
        texts = [
            f"{PLAIN_TRANSCRIPT} {_SUB_SENTINELS['SYN-001']} signs this work.",
            f"{PLAIN_TRANSCRIPT} {_SUB_SENTINELS['SYN-002']} signs this work.",
        ]
        criterion_specs = [
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
             "band_count": 2},
            {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic",
             "band_count": 2},
        ]
        orchestrator, _run_id, version = seed_world(
            store, submissions=submissions, criterion_specs=criterion_specs,
            texts=texts,
        )
        # The per-criterion exemplars carry the per-criterion sentinels — added
        # through the shipped catalog door (blobs first, then the row), which is
        # legal on the draft version the run was seeded on.
        from aeh.pkg import PackageCatalog

        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        for criterion_id, sentinel in _CRITERION_SENTINELS.items():
            blob_hash = store.blobs().put(
                f"{sentinel} worked example naming the force at rest.".encode("utf-8")
            )
            catalog.add_exemplar(version, f"ex-{criterion_id}", criterion_id,
                                 "secure", blob_hash=blob_hash)

        drive_extract(orchestrator, store, provider)
        units = lease_score_units(orchestrator)
        judged = judge_units(store, provider, units)
        assert judged == len(units), "fixture bug: the drive did not judge every unit"

        refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
        for unit in units:
            worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                store, None, refs_by_build[unit.judge]
            )
            request = worker.assemble(unit)
            leaves = "\n".join(text for _path, text in string_leaves(request))
            for other_sub, other_sentinel in _SUB_SENTINELS.items():
                if other_sub == unit.submission_id:
                    continue
                assert other_sentinel not in leaves, (
                    f"{unit.work_id[:12]} ({unit.submission_id}) carries the text of "
                    f"{other_sub} ({other_sentinel!r}) — a request assembled AFTER "
                    "judgment still carries no other submission's words (CT-JUDGE-03 "
                    "step 4: no state from a prior judgment, across submissions for "
                    "the same judge)"
                )
            for other_criterion, other_sentinel in _CRITERION_SENTINELS.items():
                if other_criterion == unit.criterion_id:
                    continue
                assert other_sentinel not in leaves, (
                    f"{unit.work_id[:12]} ({unit.criterion_id}) carries the rubric of "
                    f"{other_criterion} ({other_sentinel!r}) — no history across "
                    "criteria for the same submission (CT-JUDGE-03 step 4)"
                )
        # Positive control: the sentinels really ride the assembled requests, so
        # the absences above are over a payload that carries its own material.
        own_unit = next(
            unit for unit in units
            if unit.submission_id == "SYN-001" and unit.criterion_id == "C1"
        )
        own_request = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, None, refs_by_build[own_unit.judge]
        ).assemble(own_unit)
        own_leaves = "\n".join(text for _path, text in string_leaves(own_request))
        assert _SUB_SENTINELS["SYN-001"] in own_leaves, (
            "fixture bug: the submission sentinel never reached its own request — "
            "the cross-submission absence above would be vacuous"
        )
        assert _CRITERION_SENTINELS["C1"] in own_leaves, (
            "fixture bug: the exemplar sentinel never reached its own criterion's "
            "request — the cross-criterion absence above would be vacuous"
        )
    finally:
        store.close()