"""`TC-CONFORM-03` — the fixture set exercises transcription on the real medium.

Case: test plan §5.18, `FR-CONFORM-03`. Oracle: **composition assertion**.

    | The fixture set's composition | Contains real scanned handwriting spanning legible to
    | marginal and at least one mixed-format paper, so transcription and mark-reading are
    | exercised rather than assumed |

**This case cannot be fully satisfied in this repository, and the honest thing is to say which
half is missing and why rather than to make the other half look like all of it.**

`FR-CONFORM-03` asks for *real* scanned handwriting. That corpus is `F-HAND`, and §4.4's PII rules
make it the one corpus that is *"never committed, never exported"* — it is consented real student
work under Tier C handling. §8.1 lists arranging that consent among the **external prerequisites
to arrange, not to discover later**, and it has not been arranged. So:

* **The committed half runs in the fast tier and is green.** It asserts the things that are
  checkable without the corpus: `F-HAND`'s composition requirement is declared, its Tier C rules
  are recorded, and — the load-bearing one — **no synthetic corpus in this repository claims to be
  a real medium**. That last assertion is the one worth having. Stamping
  `media_kind: "scanned_handwriting"` onto generated Markdown would make `CT-CONFORM-02`'s
  composition assertion pass against a clean-typed-text corpus, which is verbatim the measurement
  §6.11.18 says the clause exists to prevent. An absent attribute is second-best; a wrong one is
  worse than none.
* **The corpus half is `live`, and skips with the prerequisite named** when `HARNESS_F_HAND_DIR`
  is unset. `live` rather than `writtenahead`: the RTM row for `FR-CONFORM-03` reads
  *Integration(live)* and its sibling `TC-INGEST-45` is `live / 3, nightly` against the same
  corpus, so §5.18's rung 2 is the outlier. It is deliberately **not** in
  `WRITTEN_AHEAD_BLOCKERS` either — that registry's question is *which single blocker, resolved,
  makes this test runnable*, and no `aeh.*` symbol does. The blocker is a consent arrangement.

Both points are reported on the PR, naming `TC-CONFORM-03`, so the RTM does not claim coverage
that does not exist.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from harness.corpora import hand
from tests.support import corpora
from tests.support.adversarial import COMMITTED_SUBMISSION_CORPORA

CASE = "TC-CONFORM-03"


def test_tc_conform_03_the_real_medium_requirement_is_declared_with_its_span_and_its_rules():
    """The committed declaration: what `F-HAND` must contain, and under what rules."""
    registry = corpora.hand_registry()
    composition = registry["required_composition"]

    assert composition["requirement"] == "FR-CONFORM-03"
    assert hand.REAL_MEDIA_KIND in composition["media_kinds"], (
        "the declaration does not require real scanned handwriting"
    )
    assert hand.MIXED_FORMAT_MEDIA_KIND in composition["media_kinds"], (
        "the declaration does not require a mixed-format paper, which FR-CONFORM-03 names "
        "explicitly and separately"
    )
    # The span, both ends. A declaration naming only `legible` would describe a corpus that
    # satisfies "includes real scanned handwriting" while measuring transcription only where
    # transcription is easy — `marginal` is where two backends' transcribers actually differ.
    assert tuple(composition["legibility_span"]) == hand.REQUIRED_LEGIBILITY
    assert composition["min_mixed_format_papers"] >= 1

    for rule in hand.TIER_C_RULES:
        assert rule in registry["tier_c_rules"], f"the Tier C rule {rule!r} is not recorded"

    assert registry["corpus_dir_env"] == hand.CORPUS_DIR_ENV, (
        "the registry does not name the environment knob a machine that has the corpus sets, so "
        "the live half below has nothing to read"
    )


def test_tc_conform_03_no_committed_corpus_claims_to_be_a_real_medium():
    """The assertion that keeps `CT-CONFORM-02` honest while `F-HAND` is unarranged.

    This is the whole reason the synthetic corpora declare `media_kind` at all. Without the
    attribute, a later story looking for real-medium coverage finds an absence and might add the
    label rather than the corpus; with the *wrong* attribute, the composition assertions upstream
    go green and nobody looks again. `synthetic_markdown` is the third option: present, checkable
    and true.
    """
    for corpus_name in COMMITTED_SUBMISSION_CORPORA:
        corpus = corpora.load(corpus_name)
        for member in corpus.members:
            declared = member.attributes.get("media_kind")
            assert declared == hand.SYNTHETIC_MEDIA_KIND, (
                f"{corpus_name}/{member.id} declares media_kind {declared!r}. Every committed "
                f"corpus here is generated Markdown and must say so: a synthetic member "
                f"claiming {hand.REAL_MEDIA_KIND!r} makes CT-CONFORM-02's composition assertion "
                f"pass against a clean-typed-text corpus (FR-CONFORM-03, R37)."
            )


@pytest.mark.live
def test_tc_conform_03_the_consented_corpus_spans_legible_to_marginal_and_carries_mixed_format():
    """The corpus half. Nightly (E2/E3), against the Tier C directory.

    Skipped rather than failed when the corpus is absent, and the skip message names the
    prerequisite: §8.1 lists `F-HAND` consent as something to *arrange*, and a red test cannot be
    fixed by anybody reading this file. A skip that names what is missing is the honest report; a
    green test over an empty directory would not be.

    Composition is read from a `manifest.json` the corpus owner maintains beside the scans, in the
    same shape every other corpus here uses — so the Tier C directory is citable the same way, and
    this test never reads a scan's bytes.

    The rules themselves live in `hand.composition_problems` and are exercised in the fast tier by
    the two controls below. Without those, this check would arrive at the day the consent lands
    having never run, and whoever ran it then could not tell an incomplete corpus from a rule that
    never fired.
    """
    configured = os.environ.get(hand.CORPUS_DIR_ENV)
    if not configured:
        pytest.skip(
            f"{hand.CORPUS_DIR_ENV} is unset. F-HAND is consented real student work under Tier C "
            f"handling and is never committed (§4.4); arranging the consent and the storage is "
            f"an external prerequisite (§8.1). TC-CONFORM-03's corpus half cannot run until it "
            f"is arranged."
        )

    root = Path(configured)
    manifest_path = root / "manifest.json"
    assert manifest_path.is_file(), (
        f"{hand.CORPUS_DIR_ENV} points at {root}, which has no manifest.json. The corpus must "
        f"declare its own composition — this test never reads a scan."
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = hand.composition_problems(manifest)
    assert not problems, (
        f"the F-HAND corpus at {root} does not satisfy FR-CONFORM-03: {problems}. "
        f"'no_marginal_handwriting' is the one to expect and the one that matters — a corpus of "
        f"clean legible scans contains real handwriting and measures transcription only where "
        f"transcription is easy (R37)."
    )


# --- controls: the live rules above, shown to fire ------------------------------------------
#
# `hand.composition_problems` is the only rule set in this suite whose subject cannot exist here.
# So it gets what every unexercisable rule in this repo gets: a complete manifest that must
# produce no problems, and a broken one that must produce **every** problem by name. Containment
# is not enough — a check asserted only for "something was found" stays green when five of its six
# rules are deleted, which is the failure TS-57 measured.


def _complete_hand_manifest() -> dict:
    """The smallest `F-HAND` manifest that satisfies `FR-CONFORM-03`.

    Synthetic metadata describing a corpus that does not exist: no bytes, no scan, no student
    work. It is a shape, and writing one here is the only way to show the rules accept a correct
    corpus as well as reject an incorrect one.
    """
    return {
        "corpus": "F-HAND",
        "consent_class": "consented",
        "submissions": [
            {"id": "H-01", "student_ref": "H-0001", "media_kind": hand.REAL_MEDIA_KIND,
             "legibility": "legible"},
            {"id": "H-02", "student_ref": "H-0002", "media_kind": hand.REAL_MEDIA_KIND,
             "legibility": "marginal"},
            {"id": "H-03", "student_ref": "H-0003",
             "media_kind": hand.MIXED_FORMAT_MEDIA_KIND, "legibility": "legible"},
        ],
    }


def test_tc_conform_03_the_composition_rules_accept_a_corpus_that_satisfies_the_requirement():
    assert hand.composition_problems(_complete_hand_manifest()) == []


@pytest.mark.parametrize(
    "problem, break_it",
    [
        ("no_submissions", lambda m: m.update(submissions=[])),
        ("corpus_not_marked_consented", lambda m: m.update(consent_class="real")),
        (
            "no_scanned_handwriting",
            lambda m: [s.update(media_kind=hand.MIXED_FORMAT_MEDIA_KIND) for s in m["submissions"]],
        ),
        ("no_legible_handwriting", lambda m: m["submissions"][0].update(legibility="marginal")),
        ("no_marginal_handwriting", lambda m: m["submissions"][1].update(legibility="legible")),
        (
            "too_few_mixed_format_papers",
            lambda m: m["submissions"][2].update(media_kind=hand.REAL_MEDIA_KIND),
        ),
        ("member_without_student_ref", lambda m: m["submissions"][0].update(student_ref="")),
    ],
)
def test_tc_conform_03_each_composition_rule_fires_by_name(problem, break_it):
    """One row per rule, so a rule that stopped firing names itself rather than thinning a count."""
    manifest = _complete_hand_manifest()
    break_it(manifest)
    assert problem in hand.composition_problems(manifest), (
        f"breaking the corpus in the way {problem!r} describes produced "
        f"{hand.composition_problems(manifest)} instead"
    )
