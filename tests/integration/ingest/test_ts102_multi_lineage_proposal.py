"""TS-102 (#396): D-3's multi-lineage proposal — every structurally matching lineage, ranked.

| Case | Oracle |
|---|---|
| TC-INGEST-52 | Three stored papers whose question inventory matches the submission's, with low / middle / high vocabulary overlap: the proposal lists all three, ranked by their per-candidate semantic value (highest first), none `absent` |

Disclosed: the plan's 0.2 / 0.6 / 0.9 are illustrative similarity levels; the per-candidate value
is the lexical affinity of each whole paper with the submission, so the case builds three papers
with increasing shared vocabulary and asserts the ranking and that each value is numeric and
distinct. The run's own paper (the package's inventory) is stored too, as the semantic reference
FR-INGEST-38 needs for the outcome to be `mismatch`.
"""

from __future__ import annotations

import json

import pytest

from tests.integration.ingest.test_ts136_multi_lineage import _Papers

pytestmark = pytest.mark.integration

_ANSWER = "vertex parabola minimum axis symmetry elimination substitution coefficient"


def test_tc_ingest_52_every_matching_lineage_is_proposed_ranked_by_semantic(tmp_data_dir):
    fx = _Papers(tmp_data_dir, "ts102-52")
    try:
        reference = fx.put_paper("Assessment Alpha", ("Q1", "Q2"))
        words = _ANSWER.split()
        low = fx.put_paper("Assessment Low", ("Q7", "Q8"),
                           text={"Q7": "unrelated history text about kings", "Q8": words[0]})
        mid = fx.put_paper("Assessment Mid", ("Q7", "Q8"),
                           text={"Q7": " ".join(words[:3]), "Q8": " ".join(words[3:5])})
        high = fx.put_paper("Assessment High", ("Q7", "Q8"),
                            text={"Q7": " ".join(words[:5]), "Q8": " ".join(words[5:])})
        source = fx.put_submission("History Final", {"Q7": " ".join(words[:5]),
                                                     "Q8": " ".join(words[5:])}, tag="ts102")
        report = fx.submit(source)
        assert report.gates["v4"] == "mismatch", fx.signals_of(report.submission_id)
        candidates = json.loads(fx.proposals()[0]["candidates"])
        ids = [c["assessment_document_id"] for c in candidates]
        assert ids == [high, mid, low], (
            f"all three matching lineages must be listed, highest semantic first: {candidates}")
        values = [c["semantic"] for c in candidates]
        assert all(isinstance(v, (int, float)) for v in values), values
        assert values[0] > values[1] > values[2], values
        assert reference not in ids, "the reference paper (a different inventory) was listed"
    finally:
        fx.close()
