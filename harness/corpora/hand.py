"""`F-HAND` — the one corpus this repository declares and does not contain.

`FR-CONFORM-03` requires the conformance fixture set to include *"real scanned handwriting
spanning legible to marginal, and a mixed-format paper, so transcription and mark-reading are
exercised rather than assumed"* (R37). §4.4 is equally clear about what that means for the
repository:

    | **F-HAND** — real scanned handwriting | ... | **Consented real student work.** Handled under
    | Tier C rules: owner-only permissions, **never committed to the repo**, stored in a separate
    | consented-corpus directory, never transmitted to a remote provider except under the
    | `FR-CONF-08` consent gate |

and §4.4's PII rules repeat it: *"`F-HAND` is the only corpus containing real student work. It is
never committed, never exported..."*

So the two halves of `TC-CONFORM-03` are in different places, and this module is the first half:
a **committed declaration** of what the corpus must contain, where it lives, and the rules that
govern it. `fixtures/F-HAND/registry.json` holds it, and it holds no student work.

Why a declaration is worth committing at all
--------------------------------------------
Without one, "the corpus is not here" and "the corpus does not exist" look identical, and §8.1
lists `F-HAND` consent as an **external prerequisite to arrange, not to discover later** — the
failure mode is a release that ships having measured transcription on clean typed text. The
registry makes the absence explicit and checkable: the composition requirement is written down,
the environment knob that points at the real corpus is named, and
`tests/integration/conform/test_tc_conform_03_real_medium.py` reads both.

**What is deliberately *not* here.** No synthetic corpus in this repository carries
`media_kind: "scanned_handwriting"`. Stamping that attribute onto generated Markdown would make
`CT-CONFORM-02`'s composition assertion pass against a clean-typed-text corpus, which is verbatim
the measurement §6.11.18 says the clause exists to prevent. Every synthetic submission declares
`media_kind: "synthetic_markdown"` instead, and the honest consequence is that the real-medium
half of `FR-CONFORM-03` is unmet until the consent arrangement lands.
"""

from __future__ import annotations

from typing import Any, Mapping

#: Where the Tier C corpus lives on a machine that has it. Env-gated because the location is
#: environment-sensitive by nature -- it is outside the repository by requirement, and every
#: machine puts it somewhere different. Production value is "not configured", which is the honest
#: default for a corpus that most checkouts will not have.
CORPUS_DIR_ENV = "HARNESS_F_HAND_DIR"

#: The legibility span `FR-CONFORM-03` names, both ends. Membership is not enough: a corpus of
#: clean legible scans *"includes real scanned handwriting"* and measures transcription only where
#: transcription is easy. `marginal` is where two backends' transcribers actually differ.
REQUIRED_LEGIBILITY: tuple[str, ...] = ("legible", "marginal")

#: *"and a mixed-format paper"* -- at least one, per the requirement's own wording.
MIN_MIXED_FORMAT_PAPERS = 1

#: The media kind a real scan carries, and the one every synthetic corpus here must **not** claim.
REAL_MEDIA_KIND = "scanned_handwriting"
MIXED_FORMAT_MEDIA_KIND = "mixed_format"
SYNTHETIC_MEDIA_KIND = "synthetic_markdown"

#: §4.4's Tier C handling rules, transcribed. `tests/support/adversarial.py` asserts each phrase
#: still appears in the plan's `F-HAND` row, so a relaxed rule fails a test rather than quietly
#: becoming the new policy.
TIER_C_RULES: tuple[str, ...] = (
    "owner-only permissions",
    "never committed to the repo",
    "stored in a separate consented-corpus directory",
    "never transmitted to a remote provider except under the FR-CONF-08 consent gate",
)

#: The cases that need it, from the §4.4 row and §8.1's prerequisite list.
CONSUMERS: tuple[str, ...] = ("TC-INGEST-45", "TC-CONFORM-03", "PERF-10")


def composition_problems(manifest: Mapping[str, Any]) -> list[str]:
    """What is wrong with an `F-HAND` manifest, by name. Empty means it satisfies `FR-CONFORM-03`.

    A function rather than a block of assertions inside the test, for the reason TS-57 paid for:
    the only consumer of these rules is a `live` case that **cannot run in this repository** —
    the corpus is an unarranged external prerequisite (§8.1) — so without this the rules would
    arrive at the day the consent lands having never once been executed. Whoever ran them then
    would have no way to tell a corpus that is genuinely incomplete from a check that never fired.

    Returning **named** problems rather than a bool is what lets a fast-tier test run each rule
    against a deliberately broken manifest and assert every one of them fires by name. Containment
    is not enough there: a check asserted only for "some problem was found" stays green when five
    of its six rules are deleted.
    """
    problems: list[str] = []
    members = manifest.get("submissions")
    if not isinstance(members, list) or not members:
        return ["no_submissions"]

    if manifest.get("consent_class") != "consented":
        # `FR-CONFORM-02` admits synthetic or consented work. A *real* corpus that is not marked
        # consented is the one case where the fixture set itself is the violation.
        problems.append("corpus_not_marked_consented")

    handwriting = [m for m in members if m.get("media_kind") == REAL_MEDIA_KIND]
    if not handwriting:
        problems.append("no_scanned_handwriting")

    legibilities = {m.get("legibility") for m in handwriting}
    for end in REQUIRED_LEGIBILITY:
        if end not in legibilities:
            # Named per end, because the two ends fail for different reasons and mean different
            # things: no `legible` is an odd corpus, no `marginal` is the common one and is the
            # corpus that measures transcription only where transcription is easy.
            problems.append(f"no_{end}_handwriting")

    mixed = [m for m in members if m.get("media_kind") == MIXED_FORMAT_MEDIA_KIND]
    if len(mixed) < MIN_MIXED_FORMAT_PAPERS:
        problems.append("too_few_mixed_format_papers")

    if any(not m.get("student_ref") for m in members):
        # Tier D's rule (`FR-STORE-12`, §4.4) applies to the one corpus of real work most of all.
        problems.append("member_without_student_ref")

    return problems


def registry() -> dict[str, Any]:
    """The committed declaration. Contains no student work and never will."""
    return {
        "corpus": "F-HAND",
        "committed": False,
        "consent_class": "consented",
        "provenance": "Consented real student work (test plan §4.4).",
        "status": "external prerequisite -- not arranged in this repository (§8.1)",
        "corpus_dir_env": CORPUS_DIR_ENV,
        "required_composition": {
            "media_kinds": [REAL_MEDIA_KIND, MIXED_FORMAT_MEDIA_KIND],
            "legibility_span": list(REQUIRED_LEGIBILITY),
            "min_mixed_format_papers": MIN_MIXED_FORMAT_PAPERS,
            "requirement": "FR-CONFORM-03",
            "traces_to": "R37",
        },
        "tier_c_rules": list(TIER_C_RULES),
        "consumers": list(CONSUMERS),
        "note": (
            "No synthetic corpus in this repository declares media_kind "
            f"'{REAL_MEDIA_KIND}'. Stamping it onto generated Markdown would make the "
            "CT-CONFORM-02 composition assertion pass against a clean-typed-text corpus, "
            "which is the measurement that clause exists to prevent."
        ),
    }
