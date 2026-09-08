"""`CT-SETUP-05` — a `holistic` criterion is written so no consumer needs a
special case at run time (`TC-SETUP-C05`).

Case of test plan §6.11.6; issue #56 (TS-63), green since #52+#51 landed, with
one half **disclosed-deferred** — the disposition follows what the design
actually pins, probed:

The clause (FR-SETUP-08): a criterion classified `holistic` is *written* with
base panel depth 3 rather than 1 and the lower auto-acceptance ceiling, so
`M-ORCH` and `M-AGG` need no special case at run time — panel depth is a
PACKAGE property by the time a run reads it. A run-time branch in a consumer
would be a second source of truth that drifts (the point of the clause).

**What is pinnable today, and what this file asserts** (the write half): the
package property consumers will read is the criterion's `scoring_model` column
(real, shipped, defaults "atomic") — detailed-design §1.2's consumer list reads
"panel depth per `scoring_model`" off M-PKG (line ~1255), and M-AGG's acceptance
rule is `confidence >= auto_threshold_for(scoring_model)`. So the assertion that
makes the clause hold *by construction*: the classification — not the consumer,
not a per-run heuristic — DETERMINES the written `scoring_model`. A criterion
the §5.3 table classifies `holistic` is written `holistic`; one that passes is
written `atomic`. With that, the depth-3-vs-1 and ceiling values are functions
of the stored column, and a consumer special case would be redundant rather
than merely absent.

Fails ONLY via `NotImplementedYet` (through `require_attr`) was its landing
state until both stories landed: the classification is #52's
(`classify_decomposability`, landed with it), and the criteria it classifies
come out of #51's read back (`read_back_rubric`, landed via PR #216) — the
same conjunction #54's pending files keyed on; marker and entry are gone.

**Disclosed deferrals** (on record here, not shipped red — the TC-INGEST-38
precedent: no assertion may invent storage):

1. **The 3-vs-1 values.** No panel-depth column, constant, or verdict field
   exists anywhere in the shipped schema or §3.6's `DecomposabilityVerdict`
   (classification, deciding_question, reasoning, needs_teacher_confirmation —
   nothing else). The VALUES (depth 3 vs 1; the ceiling delta) are asserted the
   moment #52 lands their storage; this case holds the chain that makes them
   package properties. #54's deferred TC-SETUP-11 notes the same columns.
2. **The consumer sweep (rung 3).** `M-ORCH` and `M-AGG` do not exist yet
   (`src/aeh/` carries conf, ingest, pkg, prov, setup, store — #57 lands the
   M-ORCH ledger). There is no consumer artifact to scan for a special case;
   the sweep lands when the consumers do, reading their run-time branch surface
   against the stored `scoring_model`.
"""
from __future__ import annotations

import json

from aeh.setup import SetupService
from tests.contract.setup._doubles import ingest_document, stage_chain
from tests.support.impl import require_attr

ISSUE_CLASSIFIER = "#52"
ISSUE_READBACK = "#51"


def _readback_reply(criteria: list[dict]) -> str:
    """One scripted read-back reply in the payload shape the oracles imply."""
    return json.dumps({"criteria": criteria})


def test_tc_setup_c05_classification_determines_the_written_scoring_model(
        tmp_data_dir):
    """The classification determines the written `scoring_model` — the package
    property every consumer reads — so panel depth and the auto-acceptance
    ceiling are functions of stored data, never of a run-time branch."""
    require_attr(SetupService, "read_back_rubric", issue=ISSUE_READBACK)
    require_attr(SetupService, "classify_decomposability",
                 issue=ISSUE_CLASSIFIER)

    chain = stage_chain(tmp_data_dir, package_id="pkg-c05")
    chain.doc = ingest_document(chain.store, kind="assessment")
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    version = proposal.package_version_id

    # Two criteria the §5.3 table decides OPPOSITELY. The provider replies
    # carry the ANSWERS, never a classification — the module owns the table, so
    # a module that echoed a scripted verdict cannot produce the pair below.
    # (The same payload bet as TC-SETUP-C04/C13: answers in the REPLY, drafts
    # carry only the criterion's identity.)
    holistic_reply = json.dumps({
        "criterion_id": "CRIT-HOL", "question_id": "Q1", "kind": "open",
        "construct": "the response shows integrated understanding",
        "answers": {"completeness": "yes", "non_interference": "yes",
                    "independence": "yes", "additivity": "no", "gates": "yes"},
    })
    atomic_reply = json.dumps({
        "criterion_id": "CRIT-ATO", "question_id": "Q2", "kind": "open",
        "construct": "the response states the definition",
        "answers": {"completeness": "yes", "non_interference": "yes",
                    "independence": "yes", "additivity": "yes", "gates": "yes"},
    })
    chain.provider.replies = [holistic_reply, atomic_reply]
    holistic_draft = {"criterion_id": "CRIT-HOL", "question_id": "Q1",
                      "kind": "open",
                      "construct": "the response shows integrated understanding"}
    atomic_draft = {"criterion_id": "CRIT-ATO", "question_id": "Q2",
                    "kind": "open",
                    "construct": "the response states the definition"}

    # The classifier's own table decides oppositely for the same shapes.
    holistic_verdict = chain.service.classify_decomposability(holistic_draft)
    atomic_verdict = chain.service.classify_decomposability(atomic_draft)
    assert holistic_verdict.classification == "holistic"
    assert atomic_verdict.classification == "atomic"

    # And the read back WRITES what the table decided: the stored criteria
    # carry the classification as their scoring_model — the package property
    # the consumers read, identical for every run that reads this package.
    chain.provider.replies = [
        _readback_reply([json.loads(holistic_reply), json.loads(atomic_reply)])
    ]
    chain.service.read_back_rubric(rubric, chain.doc)

    stored = {c["criterion_id"]: c for c in chain.catalog.criteria(version)}
    assert {"CRIT-HOL", "CRIT-ATO"} <= set(stored), (
        "the read back did not write the classified criteria — nothing for a "
        "consumer to read (CT-SETUP-C05)"
    )
    assert stored["CRIT-HOL"]["scoring_model"] == "holistic", (
        "a holistic-classified criterion was not written holistic — the "
        "package property consumers read would disagree with the table "
        "(CT-SETUP-C05, FR-SETUP-08)"
    )
    assert stored["CRIT-ATO"]["scoring_model"] == "atomic", (
        "an atomic-classified criterion was not written atomic — the write "
        "path is not driven by the classification (CT-SETUP-C05)"
    )
    # The differential survives in the PUBLISHED artifact: the two criteria
    # remain distinguishable from stored data alone, which is what makes a
    # consumer's per-model read (panel depth, ceiling) well-defined.
    chain.service.set_answer_keys(
        {cid: ["b0"] for cid in ("CRIT-HOL", "CRIT-ATO")})
    published = chain.service.publish("teacher-1")
    published_models = {c["criterion_id"]: c["scoring_model"]
                        for c in chain.catalog.criteria(published)}
    assert published_models["CRIT-HOL"] == "holistic"
    assert published_models["CRIT-ATO"] == "atomic"
