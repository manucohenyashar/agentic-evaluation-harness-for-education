"""`CT-STATS-01` — agreement is computed exclusively over admissible labels.

Test plan §6.11.16, `TC-STATS-C01`, one of the two §4.7 **safety properties** in this suite, at the
path the plan names. §6.11.16's own framing of why this module is the dangerous one:

> The module that decides what the system is allowed to *claim*, and therefore the one where a
> defect is least detectable and most damaging: every bias available here makes the numbers look
> better (HLD §0.8), so nothing about a wrong figure prompts investigation.

The case has four steps and they are four different kinds of assertion, so they are four tests:
the filter's behaviour on each contaminated class (rung 0), the structural guarantee over the
whole surface, the single-source property in the source (`NFR-STATS-04`), and the population at
rung 2. Splitting them means a regression names which one broke; a single test asserting all four
reports one failure and hides three.

**The adversarial construction is asserted, not described.** `compute_agreement_all_labels()` is
correct in isolation and honestly labelled, and the last test in this file demonstrates that
adding it leaves every `FR-STATS-*` property intact while turning this case red — which is what
§6.11.16 asks a safety-property case to show, and it runs **green today** because it operates on
a fixture rather than on `aeh.stats`.
"""

from __future__ import annotations

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require, require_path

pytestmark = pytest.mark.contract


def _labels_for(class_name: str) -> list[broken.Label]:
    """One admissible label plus the named contaminated one.

    The admissible label is the **non-vacuity anchor**. Without it, every assertion below passes
    for a filter that returns nothing at all — which excludes each contaminated class perfectly
    and computes agreement over an empty population, the failure `CT-STATS-03` is about.
    """
    contamination = vocab.INADMISSIBLE_LABEL_CLASSES[class_name]
    return [
        broken.ADMISSIBLE_LABEL,
        broken.Label(label_id=f"lbl-{class_name}", **contamination),
    ]


# --- step 1: each contaminated class, excluded on its own ------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("class_name", sorted(vocab.INADMISSIBLE_LABEL_CLASSES))
def test_tc_stats_c01_each_contaminated_label_class_is_excluded(class_name):
    """Step 1 and step 4 — one row per contaminated class, RISK-07's two named routes among them.

    *"Seed the store with labels violating each condition alone and assert each is excluded."*
    Parametrized rather than looped so a regression names **which** class started getting in: an
    operational label and a deterministic MCQ result contaminate a validity claim in different
    ways and are excluded by different columns, and one test asserting both would report one
    failure and hide the other.

    `operational` violates `label_type` alone and `deterministic_mcq` violates `evaluation_mode`
    alone, which is what makes this sweep an assertion about the **conjunction**: a filter reading
    either column by itself passes three of these four rows and fails one.

    The columns are not this module's to define — `CT-REVIEW-08` owns `saw_system_output` and
    `CT-DET-06` owns `evaluation_mode`, *"so the exclusion is enforceable from the data rather
    than by convention"*. This case is the consumer half of both.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(labels=_labels_for(class_name))

    admissible = stats.admissible_labels()
    ids = [label.label_id for label in admissible]

    assert broken.ADMISSIBLE_LABEL.label_id in ids, (
        "the admissible label was excluded too. A filter that admits nothing satisfies every "
        "exclusion assertion in this file and computes agreement over an empty population."
    )
    assert f"lbl-{class_name}" not in ids, (
        f"a {class_name} label entered the population agreement is computed over. CT-STATS-01: "
        "admissible means label_type = 'blind' AND evaluation_mode = 'judged' (RISK-07, R20/R53)."
    )


@pytest.mark.writtenahead
def test_tc_stats_c01_the_predicate_is_a_conjunction_and_admits_only_the_blind_judged_label():
    """Step 1's oracle in its strongest form: all four contaminants present at once.

    A filter joining the two conditions with `or` — the plausible slip, and the one a per-class
    sweep can be read as tolerating — admits three of these four. The assertion is set **equality**
    against the single admissible label, so anything extra fails and an empty result fails too.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    labels = [broken.ADMISSIBLE_LABEL] + [
        broken.Label(label_id=f"lbl-{name}", **fields)
        for name, fields in sorted(vocab.INADMISSIBLE_LABEL_CLASSES.items())
    ]

    stats = build_stats(labels=labels)
    admitted = {label.label_id for label in stats.admissible_labels()}

    assert admitted == {broken.ADMISSIBLE_LABEL.label_id}, (
        f"the admissible population is {sorted(admitted)}; only "
        f"{broken.ADMISSIBLE_LABEL.label_id!r} carries label_type = 'blind' and "
        "evaluation_mode = 'judged' with no reach to system output"
    )


# --- step 2: the structural guarantee, over the surface rather than the entry points ----------


@pytest.mark.writtenahead
def test_tc_stats_c01_no_function_in_the_module_computes_agreement_over_another_population(
    repo_root,
):
    """Step 2 — *"Enumerate the module's surface rather than testing the known entry points."*

    The clause's real strength is the universal: *"There is no function in this module that
    computes agreement over any other label population, and none will be added."* A test that
    drove `agreement()` and stopped would go green for a module that had grown a second one, so
    this enumerates what the module actually exposes and applies both detectors:

    * the **name** rule, which catches the construction the clause names by hand;
    * the **structural** rule over the source, which catches the same violation under a name that
      says nothing — a function called `criterion_agreement` reading the label table directly.

    Neither alone is enough. The name rule cannot see an honest name and the source rule cannot
    see a function that never lands in this file, so both run and the case fails on either.
    """
    stats = require(STATS_MODULE, issue="#115")
    source_path = require_path(
        repo_root / "src" / "aeh" / "stats.py",
        "the M-STATS implementation module",
        issue="#115",
    )
    source = source_path.read_text(encoding="utf-8")

    exposed = [name for name in dir(stats) if not name.startswith("_")]
    assert "agreement" in exposed, (
        "the module exposes no `agreement`, so the sweep below is over the wrong surface"
    )

    by_name = vocab.surface_admitting_other_populations(exposed)
    assert by_name == [], (
        f"{by_name} compute agreement over a population other than the admissible one. "
        "CT-STATS-01 forbids the function, not the wrong answer: the second figure is correct in "
        "isolation and ends up on a screen beside a validity figure with nothing separating them."
    )

    filter_names = set(vocab.admissibility_definition_sites(source)) | {"admissible_labels"}
    bypassing = vocab.agreement_functions_bypassing_the_filter(source, filter_names)
    assert bypassing == [], (
        f"{bypassing} produce an agreement figure without routing through the admissibility "
        "filter (NFR-STATS-04)"
    )


# --- step 3: the filter exists once ------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c01_the_admissibility_filter_exists_once_in_the_source(repo_root):
    """Step 3 — an artifact assertion on **cardinality**, and the oracle is *exactly one*.

    `NFR-STATS-04`: *"The 'labels admissible to a validity claim' filter shall exist once in the
    source and be reused, so R20 and R53 cannot be violated by a new caller."* The clause's own
    justification for the single-source property is that it is what stops the next caller
    violating it, so the property itself is the thing under test rather than a consequence of it.

    Exactly one, in both directions. Two definitions is `NFR-STATS-04`'s violation — invisible at
    every call site, both copies correct on the day they were written, and the next change to what
    "admissible" means reaching only one of them. Zero is worse and an oracle written as "at most
    one" would pass it.
    """
    source_path = require_path(
        repo_root / "src" / "aeh" / "stats.py",
        "the M-STATS implementation module",
        issue="#115",
    )
    sites = vocab.admissibility_definition_sites(source_path.read_text(encoding="utf-8"))

    assert len(sites) == 1, (
        f"the admissibility predicate is defined at {len(sites)} sites ({sites}). NFR-STATS-04 "
        "requires exactly one — zero means no filter at all, and two means the next change to "
        "what 'admissible' means reaches one of them."
    )


# --- step 1 and 4 at rung 2: the real population -------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.integration
def test_tc_stats_c01_a_contaminated_population_in_a_real_store_is_excluded(tmp_data_dir):
    """Steps 1 and 4 at **rung 2** — real SQLite, labels written by `M-REVIEW`.

    The rung-0 sweep above tests the filter; this tests the *population*, which is a different
    claim: a filter that is correct in isolation still admits everything if the query behind it
    selects from the wrong table, or joins a view that pre-mixes the label types. §6.11.16 gives
    this case rung 0 **and** 2 for exactly that reason.

    Keyed on **#115** although it needs `M-STORE` and `M-REVIEW` too: #115 declares
    `Depends on: #110, #29`, so the label store lands before this module by construction and #115
    is the last of the three. Marked `integration` — it opens a real database, and §4.10 budgets
    the contract tier at 60 seconds.
    """
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")

    for name in sorted(vocab.INADMISSIBLE_LABEL_CLASSES):
        for label in _labels_for(name):
            record_label(data_dir=tmp_data_dir, label=label)

    stats = open_stats(data_dir=tmp_data_dir)
    figure = stats.agreement(
        package_version="pkg-v1",
        criterion_id="C-01",
        scope="y9-2026-spring",
        backend_profile="edge-local-q4",
        panel_build_ref="9f2a1c",
        scoring_model="atomic",
    )

    assert figure.n == 1, (
        f"the figure was computed over n = {figure.n}. One admissible label was written per "
        "contaminated class and they are the same label id, so a correct filter sees exactly one "
        "— any larger n means a contaminated row reached the validity claim from the store."
    )


# --- the adversarial construction, and it runs green ---------------------------------------------


def test_the_named_adversarial_construction_turns_this_case_red_and_leaves_the_fr_cases_green():
    """§6.11.16 requires a safety-property case to demonstrate its adversarial construction.

    *"Add `compute_agreement_all_labels()` for the operator dashboard, 'clearly labelled as an
    operational figure'."* The demonstration has two halves and the second is the one that makes
    the clause worth having:

    1. **The clause case goes red.** Both detectors fire on the added function.
    2. **Every `FR-STATS-*` property stays green.** The filter still exists exactly once, so
       `NFR-STATS-04` holds. `agreement` still routes through it, so `FR-STATS-01` holds of every
       function the requirements name. The addition is correct, its label is honest, and nothing
       below the clause level objects to it.

    That is why `CT-STATS-01` says *"and none will be added"* rather than "and every function
    filters correctly": within two releases the second figure is on a screen beside a validity
    figure with nothing distinguishing them, and no `FR` case can see it happen.

    Green today, deliberately: it operates on a fixture, so it is a demonstration that the
    detectors discriminate rather than a claim about `M-STATS`.
    """
    before = broken.CORRECT_STATS_SOURCE
    after = broken.CORRECT_SOURCE_PLUS_ADVERSARIAL_FUNCTION

    def surface(source: str) -> list[str]:
        import ast

        return [
            node.name
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef)
        ]

    assert vocab.surface_admitting_other_populations(surface(before)) == []
    assert vocab.surface_admitting_other_populations(surface(after)) == [
        "compute_agreement_all_labels"
    ], "the construction the clause names by hand was not caught"

    # Half two: every FR-level property still holds of the module that now violates the clause.
    assert vocab.admissibility_definition_sites(after) == ["admissible_labels"], (
        "the adversarial addition changed the filter's cardinality, so NFR-STATS-04 would have "
        "caught it and the demonstration is not showing what the clause claims"
    )
    assert "agreement" not in vocab.agreement_functions_bypassing_the_filter(
        after, filter_names={"admissible_labels"}
    ), "FR-STATS-01's own function stopped routing through the filter, which is a different bug"
