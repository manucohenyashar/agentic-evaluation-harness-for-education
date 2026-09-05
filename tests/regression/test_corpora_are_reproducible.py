"""The corpora are what the committed generators emit, and they are what §4.4 describes.

Not `TC-*`-traced: these cover the part of TS-01's Goal that sits underneath the six
`TC-REG-*` cases — *"the synthetic corpora and golden baselines exist, are generated from
committed scripts, and are reproducible rather than archaeological"*. Like TS-00's
`test_harness.py`, this file tests code that exists now, so it is **green**.

The word that needed a test is *reproducible*. A corpus is a claim about provenance, and the
claim decays in three ways nothing else here would catch: somebody edits a fixture by hand,
somebody edits a generator without rebuilding, or a checkout rewrites the line endings and
every declared content hash silently stops describing the bytes on disk. `--check` regenerates
into a scratch directory and diffs, which fails on all three.

The composition assertions are the second half. `reproducible` is satisfied by an empty
directory too, so the counts, the spans and the element kinds §4.4 states are asserted
directly — otherwise the corpora could go green while being the wrong corpora.
"""

from __future__ import annotations

import hashlib
import json

from harness.corpora import build as corpora_build
from harness.corpora import graphic, reference_package, synth
from tests.support import corpora


def test_the_committed_corpora_are_exactly_what_the_generators_emit(repo_root):
    """`python -m harness.corpora.build --check`, as a test.

    This is the assertion behind §8.1's word *reproducible*. It also covers the line-ending
    trap: `.gitattributes` pins `fixtures/**` to LF, and a checkout that ignored it would fail
    here rather than in whichever manifest a reader happened to open first.
    """
    problems = corpora_build.check(repo_root / "fixtures")
    assert not problems, (
        "fixtures/ is not what the generators emit:\n  "
        + "\n  ".join(problems[:20])
        + "\n\nThe corpora are generated from committed scripts (test-plan §8.1). Rebuild with "
        "`python -m harness.corpora.build` rather than editing fixtures/ by hand."
    )


def test_every_manifest_hash_still_describes_the_bytes_on_disk():
    """Content addressing that can disagree with the content is not content addressing.

    `TC-CONFORM-10` recomputes this for `F-FROZEN` and `F-DEV` because a stale hash there would
    let a copied submission pass a disjointness check. The same reasoning applies to every
    corpus: `NFR-CONFORM-01`'s point is that a result can *name* the fixtures that produced it.
    """
    for name in ("F-SYNTH", "F-FROZEN", "F-DEV", "F-GRAPHIC", "F-STATS"):
        corpus = corpora.load(name)
        for member in corpus.members:
            actual = "sha256:" + hashlib.sha256(member.path.read_bytes()).hexdigest()
            assert actual == member.content_hash, (
                f"{name}/{member.id}: the manifest declares {member.content_hash} and the file "
                f"hashes to {actual}"
            )


def test_f_synth_is_the_cohort_section_4_4_describes():
    corpus = corpora.load("F-SYNTH")
    assert len(corpus.members) == 350, (
        f"§4.4: F-SYNTH is 350 generated submissions, found {len(corpus.members)}"
    )

    package = corpora.reference_package()
    assert len(package["questions"]) == 5
    open_criteria = [c for c in package["criteria"] if c["kind"] == "open"]
    mcq_criteria = [c for c in package["criteria"] if c["kind"] == "mcq"]
    assert (len(open_criteria), len(mcq_criteria)) == (12, 3), (
        f"§4.4: a 5-question, 15-criterion package with 12 open and 3 MCQ criteria; found "
        f"{len(open_criteria)} open and {len(mcq_criteria)} MCQ"
    )

    # CT-PKG-04: bands ordered by ordinal ascending, contiguous from 0, points non-decreasing,
    # band_count even and in 2..6. Asserted on the corpus rather than left to M-PKG, because a
    # fixture package that violated it would fail M-PKG's own cases for the wrong reason.
    for criterion in package["criteria"]:
        bands = criterion["bands"]
        assert 2 <= len(bands) <= 6 and len(bands) % 2 == 0, (
            f"{criterion['criterion_id']}: band_count {len(bands)} is not even and in 2..6"
        )
        assert [b["ordinal"] for b in bands] == list(range(len(bands)))
        points = [b["points"] for b in bands]
        assert points == sorted(points), (
            f"{criterion['criterion_id']}: points are not non-decreasing in ordinal"
        )


def test_the_submission_corpora_span_the_score_range_including_the_middle():
    """`FR-CONFORM-01`: the frozen set spans the score range *including mid-range partial credit*.

    Asserted on the reference points the manifest carries, and the mid-range band is asserted
    separately from the span: a corpus of nothing but zeroes and full marks spans the range on
    a min/max check and contains not one partial-credit case, which is precisely the corpus the
    requirement's second clause exists to rule out.
    """
    max_points = reference_package.MAX_POINTS
    for name, expected_count in (("F-SYNTH", 350), ("F-FROZEN", 36), ("F-DEV", 8)):
        corpus = corpora.load(name)
        assert len(corpus.members) == expected_count
        points = [m.attributes["reference_points"] for m in corpus.members]
        assert min(points) < 0.25 * max_points, f"{name} has no low-scoring submission"
        assert max(points) > 0.75 * max_points, f"{name} has no high-scoring submission"
        middle = [p for p in points if 0.35 * max_points <= p <= 0.65 * max_points]
        assert middle, (
            f"{name} contains no mid-range submission. FR-CONFORM-01 names mid-range "
            f"partial-credit cases explicitly; a set of extremes spans the range and tests "
            f"nothing about the middle, which is where routing and escalation actually live."
        )


def test_every_submission_carries_a_student_ref_and_no_name_shaped_field():
    """§4.4's PII rule, on corpora that are synthetic by construction.

    Cheap now, and the corpus is the thing later stories copy when they need a fixture — so a
    name-shaped field here would propagate into every one of them.
    """
    for name in ("F-SYNTH", "F-FROZEN", "F-DEV"):
        corpus = corpora.load(name)
        assert corpus.manifest["consent_class"] == "synthetic"
        for member in corpus.members:
            assert member.attributes["student_ref"], f"{name}/{member.id} has no student_ref"
            text = member.text().lower()
            for forbidden in ("student_name", "first_name", "surname", "full name"):
                assert forbidden not in text, (
                    f"{name}/{member.id} carries a {forbidden!r} field (FR-STORE-12, §4.4)"
                )


def test_f_graphic_has_one_page_per_element_kind_plus_the_confusable_page():
    """§4.4 and `FR-INGEST-10`/`-11`."""
    corpus = corpora.load("F-GRAPHIC")
    kinds = {m.attributes["element_kind"] for m in corpus.members}
    assert kinds == set(graphic.ELEMENT_KINDS), (
        f"F-GRAPHIC covers {sorted(kinds)}; FR-INGEST-10 names {sorted(graphic.ELEMENT_KINDS)}"
    )

    for member in corpus.members:
        assert member.attributes["required_fields"], (
            f"{member.id} declares no required fields. FR-INGEST-10's stated acceptance form is "
            f"a page per kind 'whose description is asserted to contain each named field' — "
            f"without the list there is nothing to assert."
        )

    confusable = [m for m in corpus.members if m.attributes.get("confusable_with_verdict")]
    assert len(confusable) == 1, (
        f"FR-INGEST-11 requires the fixture set to include a page whose correct description is "
        f"easily confusable with a verdict; found {len(confusable)}"
    )
    page = confusable[0]
    acceptable = page.attributes["acceptable_description"].lower()
    evaluative = page.attributes["evaluative_description"].lower()
    assert not any(term in acceptable for term in graphic.EVALUATIVE_TERMS), (
        "the confusable page's *acceptable* description contains an evaluative term, so "
        "TC-INGEST-14's differential would not discriminate — both renderings would be rejected "
        "and a module that blanket-rejects would pass."
    )
    assert any(term in evaluative for term in graphic.EVALUATIVE_TERMS), (
        "the confusable page's *evaluative* description contains no term from FR-INGEST-11's "
        "list, so there is nothing for the module to reject"
    )


def test_f_stats_carries_every_degenerate_case_nfr_stats_01_names():
    cases = {case["case_id"]: case for case in corpora.stats_cases()}
    expected = {
        "STATS-SINGLE-LABEL",
        "STATS-UNANIMOUS-ONE-CATEGORY",
        "STATS-UNANIMOUS-TWO-CATEGORIES",
        "STATS-TWO-BAND-95-BASE-RATE",
        "STATS-EMPTY-BLIND-POPULATION",
        "STATS-MAXIMAL-DISAGREEMENT",
    }
    assert set(cases) == expected, (
        f"F-STATS holds {sorted(cases)}; NFR-STATS-01 names a single label, unanimous "
        f"agreement, a two-band criterion and an empty blind population, and §4.4 adds a "
        f"maximally-disagreeing panel"
    )

    for case_id, case in cases.items():
        for figure_name, figure in case["figures"].items():
            if figure["value"] is None:
                assert figure.get("undefined_reason"), (
                    f"{case_id}/{figure_name} is null with no stated reason. CT-STATS-03 makes "
                    f"rendering absence as a number a permanent regression entry; an unexplained "
                    f"null is how it becomes a zero."
                )

    # The undefined ones are undefined, and the defined ones are not zero-by-accident.
    assert cases["STATS-UNANIMOUS-ONE-CATEGORY"]["figures"]["cohens_kappa"]["value"] is None
    assert cases["STATS-UNANIMOUS-TWO-CATEGORIES"]["figures"]["cohens_kappa"]["value"] == 1.0
    assert cases["STATS-TWO-BAND-95-BASE-RATE"]["figures"]["cohens_kappa"]["exact"] == "7/52"
    assert cases["STATS-MAXIMAL-DISAGREEMENT"]["figures"]["ordinal_alpha"]["exact"] == "-3/4"
    assert cases["STATS-EMPTY-BLIND-POPULATION"]["expected_result_type"] == "NoValidationData"


def test_pages_materialize_in_printed_order_and_not_in_directory_order(tmp_path):
    """The helper the ingestion cases will use gives `FR-INGEST-06` something to discriminate.

    A page corpus whose only order signal is `iterdir()` cannot test a requirement whose whole
    content is *"directory iteration order shall never be used"*.
    """
    member = corpora.load("F-DEV").members[0]
    pages = corpora.materialize_pages(member, tmp_path / member.id)

    assert len(pages) == synth.PAGES_PER_SUBMISSION
    for index, path in enumerate(pages, start=1):
        text = path.read_text(encoding="utf-8")
        assert text.startswith(f"Page {index} of {synth.PAGES_PER_SUBMISSION} - {member.id}"), (
            f"{path.name} does not carry its printed page number and submission id, so "
            f"FR-INGEST-06's second-preference assembly source is absent from the fixture"
        )
    assert [p.name for p in pages] == sorted(p.name for p in pages), (
        "filename ordering and printed order disagree, so the fixture cannot tell which source "
        "an implementation used"
    )


def test_a_marker_less_page_materializes_as_one_page_rather_than_none(tmp_path):
    """`F-GRAPHIC` members carry no page marker, and are one-page documents.

    Regression: `CorpusMember.pages()` split on the marker and returned `()` for them, so
    `TC-REG-01`'s `F-GRAPHIC` half would have assembled an empty page list the moment #37
    landed — failing for a reason with nothing to do with `FR-INGEST-04` or `-06`, which is the
    kind of failure someone "fixes" by dropping the corpus from the case.
    """
    for member in corpora.load("F-GRAPHIC").members:
        assert len(member.pages()) == 1, f"{member.id} split into {len(member.pages())} pages"
        pages = corpora.materialize_pages(member, tmp_path / member.id)
        assert len(pages) == 1
        assert member.attributes["element_kind"] in pages[0].read_text(encoding="utf-8")


def test_check_tolerates_a_recorded_baseline_but_still_catches_a_hand_edit(tmp_path):
    """`--check` distinguishes a recorded golden from a hand-edited corpus.

    Both directions, because they pull against each other. Every `TC-REG-*` docstring tells the
    implementing story to record its baseline under `fixtures/baselines/`, and a check that
    reported any unexpected file would go red on the first story that did so — while a check
    that ignored *everything* under `fixtures/` would stop being the reproducibility assertion
    it exists to be.
    """
    root = tmp_path / "fixtures"
    corpora_build.build(root)
    assert corpora_build.check(root) == []

    recorded = root / "baselines" / "TC-REG-01" / "F-SYNTH.canonical.md"
    recorded.parent.mkdir(parents=True, exist_ok=True)
    recorded.write_bytes(b"a baseline some producer recorded\n")
    assert corpora_build.check(root) == [], (
        "a recorded golden baseline was reported as an unexpected file; the first story to "
        "follow its own instructions would turn this suite red"
    )

    edited = root / "F-DEV" / "submissions" / "DEV-1.md"
    edited.write_bytes(edited.read_bytes() + b"edited by hand\n")
    problems = corpora_build.check(root)
    assert any("F-DEV/submissions/DEV-1.md" in p for p in problems), (
        f"a hand-edited corpus file was not reported: {problems}"
    )


def test_the_generators_are_deterministic_across_two_runs_in_one_process():
    """Same seed, same corpus. The `--check` test covers the committed bytes; this covers the
    generator itself, so a generator that reached for the module-global `random` (§4.6 forbids
    it) fails here rather than as an unexplained diff on somebody else's machine."""
    assert [s.as_document() for s in synth.frozen_set()] == [
        s.as_document() for s in synth.frozen_set()
    ]
    assert json.dumps(reference_package.as_json()) == json.dumps(reference_package.as_json())
