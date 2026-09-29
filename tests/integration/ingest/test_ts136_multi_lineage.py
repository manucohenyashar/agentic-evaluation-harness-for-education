"""TS-136 (#547): multi-lineage semantic reference and proposal candidates (design 1.9 D4).

| Case | Requirement | Oracle |
|---|---|---|
| TC-INGEST-54 | FR-INGEST-38 | the semantic signal compares against the one head whose question inventory equals the package's; `absent` naming the count when zero or two qualify |
| TC-INGEST-55 | FR-INGEST-26 (amended), CT-INGEST-22 | among several heads, only structurally matching heads are candidates, each with a numeric `semantic`, ties ordered by document id; none matching → `candidates == []` |

Disclosed adaptations: the fixture's package declares Q1 and Q2 (the plan says q1..q3), so the
"package's inventory" is {Q1, Q2}; document ids are minted by the ingestor, so (b)'s tie order is
asserted as "ascending by assessment_document_id" rather than by the literal names `doc-a`/`doc-b`.
TC-INGEST-39's re-specified arm (two qualifying heads → `absent`, no proposal) is the existing
`test_tc_ingest_39_a_second_lineage_builds_no_proposal`, which holds under D4 unchanged.
"""

from __future__ import annotations

import json

import pytest

from tests.integration.ingest.test_ingest_v4_match import _V4

pytestmark = pytest.mark.integration

_TEXT = {
    "Q1": "Describe the causes of the first world war and the alliance system.",
    "Q2": "Explain the treaty of Versailles and its economic consequences.",
    "Q4": "Balance the chemical equation for the combustion of methane gas.",
    "Q5": "Name the noble gases and describe their electron configuration.",
    "Q7": "Sketch the graph of a quadratic function and mark its vertex.",
    "Q8": "Solve the simultaneous equations by elimination and check them.",
    "Q9": "Translate the passage into French using the past tense.",
}


class _Papers(_V4):
    def put_paper(self, printed: str, questions: tuple[str, ...], text=None) -> str:
        source = self.blobs.put(f"{printed}-{'-'.join(questions)}".encode())
        body = "\n".join(
            f"<!-- region: kind=transcribed_text question_id={q} -->\n"
            f"{(text or _TEXT)[q]}\n<!-- /region -->" for q in questions)
        self.provider.texts[(source, 1)] = f"Assessment: {printed}\n{body}"
        return self.ingestor.ingest_document([source], kind="assessment",
                                             filenames={source: f"{printed}.md"})


def _semantic(fx: _Papers) -> dict:
    source = fx.put_submission("Assessment Alpha", {"Q1": _TEXT["Q1"], "Q2": _TEXT["Q2"]},
                               tag="sem")
    return fx.signals_of(fx.submit(source).submission_id)["semantic"]


@pytest.mark.parametrize("papers, expect", [
    ((("Alpha", ("Q1", "Q2")),), "compared"),
    ((("Alpha", ("Q1", "Q2")), ("Beta", ("Q4", "Q5"))), "compared"),
    ((("Alpha", ("Q1", "Q2")), ("Gamma", ("Q1", "Q2"))), "2 of them match"),
    ((("Delta", ("Q4",)), ("Epsilon", ("Q5",))), "0 of them match"),
], ids=["a-one-head", "b-one-qualifying-of-two", "c-two-qualifying", "d-none-qualifying"])
def test_tc_ingest_54_the_semantic_reference_is_the_head_matching_the_package(
        tmp_data_dir, papers, expect):
    fx = _Papers(tmp_data_dir, f"ts136-54-{len(papers)}-{expect[:1]}")
    try:
        for printed, questions in papers:
            fx.put_paper(f"Assessment {printed}", questions)
        semantic = _semantic(fx)
        if expect == "compared":
            assert semantic["signal"] != "absent", (
                f"the semantic signal was absent although exactly one head matches the "
                f"package's questions (FR-INGEST-38): {semantic}")
            assert "score" in semantic, semantic
        else:
            assert semantic["signal"] == "absent", semantic
            assert expect in json.dumps(semantic), (
                f"the absent reason must name the qualifying count ({expect!r}): {semantic}")
    finally:
        fx.close()


def _mismatch(fx: _Papers) -> list:
    source = fx.put_submission("History Final", {"Q7": "the vertex sits at the minimum point",
                                                 "Q8": "eliminate x then substitute back"},
                               tag="mis")
    report = fx.submit(source)
    assert report.gates["v4"] == "mismatch", (report.gates["v4"], fx.signals_of(report.submission_id))
    proposals = fx.proposals()
    assert len(proposals) == 1
    return json.loads(proposals[0]["candidates"])


def test_tc_ingest_55_a_no_matching_head_gives_an_empty_candidate_list(tmp_data_dir):
    fx = _Papers(tmp_data_dir, "ts136-55a")
    try:
        fx.put_paper("Assessment Alpha", ("Q1", "Q2"))  # the run's own paper: the reference
        fx.put_paper("Assessment Nine", ("Q9",))
        assert _mismatch(fx) == [], "a head whose inventory is not the submission's was listed"
    finally:
        fx.close()


def test_tc_ingest_55_b_matching_heads_only_ordered_by_semantic_then_id(tmp_data_dir):
    fx = _Papers(tmp_data_dir, "ts136-55b")
    try:
        reference = fx.put_paper("Assessment Alpha", ("Q1", "Q2"))
        same = {"Q7": _TEXT["Q7"], "Q8": _TEXT["Q8"]}
        first = fx.put_paper("Assessment Seven", ("Q7", "Q8"), text=same)
        second = fx.put_paper("Assessment Seven", ("Q7", "Q8"), text=same)
        candidates = _mismatch(fx)
        ids = [c["assessment_document_id"] for c in candidates]
        assert set(ids) == {first, second} and reference not in ids, (
            f"only the two structurally matching heads are candidates: {ids}")
        assert all(isinstance(c["semantic"], (int, float)) for c in candidates), candidates
        assert candidates[0]["semantic"] == candidates[1]["semantic"], candidates
        assert ids == sorted(ids), f"equal semantic values must be ordered by id ascending: {ids}"
    finally:
        fx.close()
