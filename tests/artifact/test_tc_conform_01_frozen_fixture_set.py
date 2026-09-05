"""`TC-CONFORM-01` — the frozen fixture set is a corpus that can tell two backends apart.

Case: test plan §5.18, `FR-CONFORM-01`, `NFR-CONFORM-01`. Oracle: **composition assertion plus
content hash**.

    | The frozen fixture set | 30-50 submissions spanning the score range, **including mid-range
    | partial-credit cases**, each with a known reference score; the set is content-addressed and
    | version-pinned, and a conformance result names exactly which fixture version produced it |

**Level.** §5.18 specifies Integration / rung 2. That rung is not achievable and not meaningful
here, and saying so is better than substituting a weaker thing silently: rung 2 means *real
dependency* — real SQLite, a real blob directory, `RecordedFixtureProvider` — and this case has no
dependency to make real. It is an assertion about committed bytes, which is what §4.3 calls an
artifact assertion, so it lives beside `TC-CONFORM-10` in `tests/artifact/` and runs in the fast
tier. The rung-2 rendering of the same requirement is TS-75's
`test_tc_conform_c01_*`, which drives `aeh.conform.load_fixture_set` and is correctly red.
Reported on the PR for `/create-test-plan`.

**Green, and that is not a mistake.** The issue says a red suite is expected, and for TS-02 that
holds for the behavioural half (`tests/integration/conform/`). The corpus half is green because
the corpus is this story's deliverable: the assertion is that `fixtures/F-FROZEN/` is what
`FR-CONFORM-01` requires, and a red one would mean the corpus is wrong rather than that the code
is missing.
"""

from __future__ import annotations

import hashlib

from tests.support import corpora
from tests.support.adversarial import (
    FROZEN_MAX,
    FROZEN_MIN,
    MID_RANGE_HIGH,
    MID_RANGE_LOW,
    SPAN_HIGH_FRACTION,
    SPAN_LOW_FRACTION,
)

CASE = "TC-CONFORM-01"


def _fractions(corpus) -> list[float]:
    max_points = corpus.manifest["max_points"]
    return [m.attributes["reference_points"] / max_points for m in corpus.members]


def test_tc_conform_01_the_frozen_set_holds_30_to_50_submissions_with_known_reference_scores():
    """Size and labels. Both halves, because either alone passes against a useless corpus."""
    corpus = corpora.load("F-FROZEN")

    assert FROZEN_MIN <= len(corpus.members) <= FROZEN_MAX, (
        f"F-FROZEN holds {len(corpus.members)} submissions; FR-CONFORM-01 requires "
        f"{FROZEN_MIN}-{FROZEN_MAX}. Below the floor the agreement figures have no power; "
        f"above the ceiling NFR-CONFORM-02's per-backend hour stops holding."
    )

    unlabelled = [
        m.id
        for m in corpus.members
        if not m.attributes.get("reference_bands") or m.attributes.get("reference_points") is None
    ]
    assert not unlabelled, (
        f"these fixtures carry no known reference score: {unlabelled}. `FR-CONFORM-04`'s "
        f"chance-corrected agreement *with the fixture labels* cannot be computed without them, "
        f"so an unlabelled fixture is a fixture that contributes nothing to a conformance run."
    )

    # A reference score is only a label if it is one the package can produce. A band outside the
    # declared set would give the corpus a score no grading run could ever match, and every
    # agreement figure computed against it would be measuring the corpus's mistake.
    package = corpora.reference_package()
    declared = {
        criterion["criterion_id"]: {band["band"] for band in criterion["bands"]}
        for criterion in package["criteria"]
    }
    for member in corpus.members:
        for criterion_id, band in member.attributes["reference_bands"].items():
            assert criterion_id in declared, f"{member.id} labels unknown criterion {criterion_id}"
            assert band in declared[criterion_id], (
                f"{member.id} labels {criterion_id} {band!r}, which is not one of "
                f"{sorted(declared[criterion_id])}"
            )


def test_tc_conform_01_the_frozen_set_spans_the_score_range():
    """*"Spanning the score range"* — asserted at both ends, not as a spread."""
    fractions = _fractions(corpora.load("F-FROZEN"))
    assert min(fractions) < SPAN_LOW_FRACTION, (
        f"the weakest fixture scores {min(fractions):.2f} of the maximum; nothing in the corpus "
        f"is below {SPAN_LOW_FRACTION}, so the bottom of the score range is unmeasured"
    )
    assert max(fractions) > SPAN_HIGH_FRACTION, (
        f"the strongest fixture scores {max(fractions):.2f} of the maximum; nothing in the corpus "
        f"is above {SPAN_HIGH_FRACTION}"
    )


def test_tc_conform_01_the_frozen_set_includes_mid_range_partial_credit_cases():
    """The clause the requirement puts in bold, asserted **separately** from the span.

    A corpus holding one zero and one full-marks paper spans the score range by any reasonable
    reading of the words, and §6.11.18 names it as the failure: *"a corpus of clear passes and
    clear failures would make every backend look equivalent."* Two backends disagree where the
    answer is arguable, so the corpus has to contain arguable work — and only a separate
    assertion can tell the two corpora apart.

    The middle third is this suite's reading; `FR-CONFORM-01` names no fraction. It matches the
    reading TS-75's clause case already committed to, so the two cannot disagree about what
    passes.
    """
    fractions = _fractions(corpora.load("F-FROZEN"))
    mid = [f for f in fractions if MID_RANGE_LOW <= f <= MID_RANGE_HIGH]
    assert mid, (
        f"no F-FROZEN fixture scores between {MID_RANGE_LOW:.2f} and {MID_RANGE_HIGH:.2f} of the "
        f"maximum. The distribution is {sorted(round(f, 2) for f in fractions)}."
    )
    # More than one, because a single mid-range paper is a sample of one on the only part of the
    # range where the backends actually differ.
    assert len(mid) >= 3, (
        f"only {len(mid)} fixture(s) carry mid-range partial credit. FR-CONFORM-01 says "
        f"*cases*, plural, and one arguable paper cannot distinguish two backends from noise."
    )


def test_tc_conform_01_every_declared_content_hash_is_the_hash_of_the_bytes_on_disk():
    """`NFR-CONFORM-01`, member level: recomputed, never trusted."""
    corpus = corpora.load("F-FROZEN")
    for member in corpus.members:
        actual = "sha256:" + hashlib.sha256(member.path.read_bytes()).hexdigest()
        assert actual == member.content_hash, (
            f"{member.id} declares {member.content_hash} and hashes to {actual}. A manifest that "
            f"disagrees with its bytes makes every provenance claim built on it false."
        )


def test_tc_conform_01_the_set_is_version_pinned_and_addressed_by_its_content_not_its_label():
    """`NFR-CONFORM-01`, set level — *"a conformance result names exactly which fixtures produced
    it"* — with the half that can be faked asserted as a **differential**.

    A version string is content addressing only if changing a fixture changes it. An
    implementation that hashed the version *label* satisfies "the result names its fixture set"
    and reports the same identity for a corpus somebody edited, which is how a six-month-old
    conformance result stops being citable without anyone noticing.

    So the set digest is recomputed here from the members, and then recomputed again with one
    member's hash perturbed, and the two must differ. Perturbing the *input to the digest* rather
    than editing the corpus on disk, because a test that rewrote `fixtures/` would leave the
    working tree dirty on failure and would be checking the filesystem rather than the rule.
    """
    from harness.corpora.manifest import ManifestEntry, fixture_set_id, set_content_hash

    corpus = corpora.load("F-FROZEN")
    manifest = corpus.manifest

    assert manifest.get("version"), "F-FROZEN is not version-pinned"
    assert manifest.get("generator"), (
        "F-FROZEN names no generator, so nobody can regenerate it and check (§8.1)"
    )

    entries = tuple(
        ManifestEntry(id=m.id, path=str(m.path.name), content_hash=m.content_hash)
        for m in corpus.members
    )
    declared = manifest["set_content_hash"]
    assert set_content_hash(entries) == declared, (
        "the declared set hash is not the hash of the members it lists"
    )
    assert manifest["fixture_set_id"] == fixture_set_id(
        manifest["corpus"], manifest["version"], declared
    ), "the citable fixture-set id disagrees with the corpus, version and digest it is built from"

    edited = (
        ManifestEntry(entries[0].id, entries[0].path, entries[0].content_hash[:-1] + "0"),
        *entries[1:],
    )
    assert set_content_hash(edited) != declared, (
        "changing one member's content left the set's identity unchanged, so F-FROZEN is "
        "addressed by its label rather than by its content (NFR-CONFORM-01)"
    )

    # And renaming a member changes it too. A digest over concatenated bytes alone would not
    # notice, and a conformance result is keyed by submission id — two corpora that differ only in
    # which submission is called what are two different corpora to every consumer.
    renamed = (
        ManifestEntry(entries[0].id + "-x", entries[0].path, entries[0].content_hash),
        *entries[1:],
    )
    assert set_content_hash(renamed) != declared, (
        "renaming a fixture left the set's identity unchanged, so a result citing that identity "
        "does not name which fixtures produced it"
    )
