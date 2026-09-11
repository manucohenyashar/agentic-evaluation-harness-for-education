"""`TC-CALIB-01` — discovery identifies the per-criterion disagreements, and labels itself.

Test plan §5.17, `TC-CALIB-01` (FR-CALIB-01, Integration / rung 2).

The contract suite carries the label clause (`TC-CALIB-C03`: `kind == "ambiguity_discovery"`,
and the no-accuracy-figure field sweep) — but it asserts it over an **empty** report: no teacher
bands, no transport, the nothing-scored path. What no green test carried before this file is
discovery actually running over teacher-graded calibration samples and identifying the
disagreements — the `FR-CALIB-01` behaviour the plan case is about:

* the exact per-criterion disagreements (which criterion, which paper, the teacher's band against
  the panel's R₀ band), with **agreement appearing nowhere** — a criterion the two sides read the
  same way is not a finding;
* every disagreement arrives **uncategorized** — categorizing is triage's judgement, not
  discovery's guess, and a discovered disagreement that carried a model-assigned category would
  be the module triaging its own failures one step early;
* an absent model band is disclosed as unscored, **never read as agreement**;
* a deterministic criterion is kept out by name (`#89`'s separation) — scoring an answer key
  with a panel would be theatre, and disagreeing with an answer key is a key error, not a rubric
  ambiguity;
* the ambiguity-discovery label rides the **populated** report too — `TC-CALIB-C03`'s type half
  ran on the empty one, and the label must survive the report actually carrying findings.

The transport is the recorded-transport form (`model_bands` pre-scored under R₀, `CT-PROV-10`)
and the injected scorer seam — no network, no real upstream, so the socket guard is never
exercised. The module is complete (landed with #137), so this file runs green and unmarked;
nothing here needed `@pytest.mark.writtenahead`.
"""

from __future__ import annotations

from tests.support.impl import CALIB_MODULE, require


# --- the disagreements, exactly -------------------------------------------------------------------


def test_tc_calib_01_discovery_identifies_the_per_criterion_disagreements():
    """The exact disagreements over teacher-graded samples, and everything the report accounts
    for.

    Three calibration papers, two criteria. The teacher graded all three; the panel's pre-scored
    R₀ bands cover two. Exactly one comparison disagrees (s2/c1), the s3 row's missing model band
    is disclosed rather than read as agreement, and the label — ambiguity discovery, never a
    measurement of accuracy — rides the populated report.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "discover", "KIND_AMBIGUITY_DISCOVERY", issue="#140")

    report = calib.discover(
        package_version="pkg-v1-r0",
        calibration_papers=["s1", "s2", "s3"],
        teacher_bands={
            "s1": {"c1": "3", "c2": "2"},
            "s2": {"c1": "3", "c2": "2"},
            "s3": {"c1": "3"},
        },
        model_bands={
            "s1": {"c1": "3", "c2": "2"},
            "s2": {"c1": "2", "c2": "2"},
        },
    )

    # The disagreements, exactly: the teacher's band and the panel's R₀ band differ on s2/c1 and
    # nowhere else — s1 agrees on both criteria, s2 agrees on c2, and s3's c1 has no model band
    # to compare against.
    identified = [
        (d.criterion_id, d.sample_id, d.teacher_band, d.model_band)
        for d in report.disagreements
    ]
    assert identified == [("c1", "s2", "3", "2")], (
        f"discovery identified {identified} over a fixture whose single teacher-vs-panel "
        f"disagreement is s2/c1 (teacher '3' against the panel's R₀ '2'). FR-CALIB-01: "
        "per-criterion disagreements are what discovery identifies — a missed one hides an "
        "ambiguity from the triage conversation, an invented one fits the rubric to noise."
    )

    # Agreement is not a finding: c1 on s1 and c2 on every paper read the same, and appear
    # nowhere in the report.
    agreed = {(d.sample_id, d.criterion_id) for d in report.disagreements}
    assert ("s1", "c1") not in agreed and ("s1", "c2") not in agreed
    assert ("s2", "c2") not in agreed

    # Every disagreement arrives uncategorized: discovery identifies, triage categorizes
    # (FR-CALIB-02's boundary — the contract's TC-CALIB-C04 asserts the refusal; this is the
    # value that reaches it).
    assert all(d.category is None for d in report.disagreements), (
        "discovery assigned a triage category of its own — categorizing is the triage step's "
        "judgement, and a model that triages its own findings is the fitting the clause exists "
        "to prevent, one step early (FR-CALIB-02)"
    )

    # What each stage did, next to the status (seam 4): papers_scored and unscored_papers
    # account for every calibration paper, and the s3 row's missing model band is disclosed
    # in the notes — absence is never read as agreement.
    assert report.papers_scored == 2, (
        f"discovery scored {report.papers_scored} papers; s1 and s2 carried comparisons, s3 "
        "did not (its c1 row has no model band under R0)"
    )
    assert report.unscored_papers == ("s3",), (
        f"unscored_papers is {report.unscored_papers}; s3 the teacher graded but nothing was "
        "scored under R0 on any of its criteria, and the aggregate field must carry what the "
        "notes disclose"
    )
    assert any("unscored" in note.lower() or "no model band" in note.lower()
               for note in report.notes), (
        "the s3/c1 absence is not disclosed in the notes — absence read silently as agreement "
        "is the TC-REQ-68 shape this surface exists to refuse"
    )

    # The label rides the populated report: the value says what it is even when it carries
    # findings (TC-CALIB-C03's type half ran on an empty report; the label must survive one).
    assert report.kind == calib.KIND_AMBIGUITY_DISCOVERY, (
        f"a populated discovery report is labelled {report.kind!r}; FR-CALIB-01's output is "
        "ambiguity discovery, and the label is part of the value, not a property of the "
        "empty case"
    )
    assert not hasattr(report, "matched") and not hasattr(report, "total"), (
        "a populated report carries a matched/total pair — the division an accuracy figure "
        "falls out of invites itself the moment the fields exist (CT-CALIB-03)"
    )


def test_tc_calib_01_a_deterministic_criterion_is_not_a_calibration_subject():
    """`#89`'s separation, on the discovery path: a deterministic criterion is kept out by name.

    The teacher's band and the panel's band differ on c2 — and the disagreement must not exist,
    because a deterministic criterion has an answer key: scoring it with a panel would be
    theatre, and a disagreement with an answer key is a key error, not a rubric ambiguity. The
    exclusion is reported by name, so the criterion's silence is a fact about the exclusion and
    not a quiet agreement.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "discover", issue="#140")
    import aeh.det

    report = calib.discover(
        package_version="pkg-v1-r0",
        calibration_papers=["s1"],
        teacher_bands={"s1": {"c1": "3", "c2": "2"}},
        # c1 genuinely disagrees (teacher '3', panel '2'); c2 disagrees harder
        # ('2' against '4') but is the criterion the mode table declares
        # deterministic — the fixture fails unless the exclusion actually
        # removes it.
        model_bands={"s1": {"c1": "2", "c2": "4"}},
        evaluation_modes={"c2": aeh.det.EVALUATION_MODE_DETERMINISTIC},
    )

    assert [(d.criterion_id, d.sample_id) for d in report.disagreements] == [("c1", "s1")], (
        "a deterministic criterion whose bands differ was compared anyway. #89's separation "
        "keeps answer-key subjects out of calibration — a disagreement with an answer key is "
        "a key error, never a rubric ambiguity to triage."
    )
    assert report.deterministic_excluded == ("c2",), (
        f"the exclusion is not reported ({report.deterministic_excluded!r}); a criterion kept "
        "out by name must be visible as kept out, or its silence reads as agreement"
    )


def test_tc_calib_01_the_scorer_seam_is_the_other_transport():
    """The second transport: the panel's side arrives through the injected scorer callable — the
    seam a test binds to `RecordedFixtureProvider`-backed code and production binds to the panel
    (`CT-PROV-15`). The same teacher-graded samples identify the same disagreement through it,
    and the run's notes name the live path rather than passing quietly."""
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "discover", issue="#140")

    r0_bands = {("s1", "c1"): "3", ("s1", "c2"): "2", ("s2", "c1"): "2", ("s2", "c2"): "2"}

    def scorer(paper: str, criterion_id: str) -> str:
        return r0_bands[(paper, criterion_id)]

    report = calib.discover(
        package_version="pkg-v1-r0",
        calibration_papers=["s1", "s2"],
        teacher_bands={
            "s1": {"c1": "3", "c2": "2"},
            "s2": {"c1": "3", "c2": "2"},
        },
        scorer=scorer,
    )

    assert [
        (d.criterion_id, d.sample_id, d.teacher_band, d.model_band)
        for d in report.disagreements
    ] == [("c1", "s2", "3", "2")], (
        "the scorer seam identified a different disagreement set than the recorded bands did "
        "over the same samples — one transport per run, but the same disagreement either way "
        "(FR-CALIB-01)"
    )
    assert any("scorer seam" in note.lower() for note in report.notes), (
        "the run's notes do not name the transport that ran; a bare report over a live-looking "
        "path is the silent-failure shape the four seams exist to prevent"
    )