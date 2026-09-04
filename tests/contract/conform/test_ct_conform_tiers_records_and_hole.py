"""`CT-CONFORM-06`, `-08`, `-11`, `-12`, `-14` — where results go, when the suite runs, and the hole.

Test plan §6.11.18, TS-75 (issue #136). This file holds the clauses whose subject is not a
computation, and three of them are assertable **today**, which is unusual for a suite written two
stories ahead of its module:

* `-08` says the two test tiers are contract and §6.11.18 asks for that *"against the CI
  configuration rather than as an intention"*. Test plan §4.7's suite table **is** this repo's CI
  configuration — `.github/workflows/` holds two deliberately `.disabled` files and `CLAUDE.md`
  states GitHub runs no agents here — so the wiring half runs green.
* `-11`'s gate-wiring half is the same artifact, read for a trigger and a budget.
* `-14` asserts a limitation is **visible**, across three passages in two documents, and the case
  carries its own expiry: §6.11.18 says it *"should be deleted the day the statistic is
  declared"*. The detector is what makes that day arrive as a red test rather than as nobody
  noticing.

The behavioural halves — a fast-tier run under a hard network block, a measured duration, the
validation-record writes and the two consumer sweeps — are red behind `writtenahead`.

**One case could not be implemented as specified and is reported rather than weakened.**
`TC-CONFORM-C11` asks the suite to be asserted *"wired as a release gate rather than as an
advisory job"*. §4.8's twelve exit criteria name no conformance run; what they name is the
**exclusion** of `FR-CONFORM-06`'s divergence gate, *"not computable as written"* — which is
`CT-CONFORM-14`'s hole rather than a decision that conformance is advisory. So the assertion below
is that conformance is wired to a trigger and a budget, and that the only conformance-related
thing §4.8 excludes is the uncomputable gate. That no exit criterion names the run itself is a
finding about the plan and is in the PR.
"""

from __future__ import annotations

import pytest

from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg
from tests.support.conform_vocabulary import (
    CONFORMANCE_BUDGET_SECONDS,
    HARNESS_CONFORM_MODULE,
    divergence_hole_problems,
    equivalence_claims,
    tier_wiring_problems,
)
from tests.support.doc_tables import find_row, markdown_rows, read_repo_text
from tests.support.guards import recording_write_audit
from tests.support.impl import (
    CONFORM_MODULE,
    CONSOLE_MODULE,
    PKG_MODULE,
    require,
)

pytestmark = pytest.mark.contract

DESIGN = "docs/design/detailed-design.md"
PLAN = "docs/design/test-plan.md"


def _two_backends():
    return [edge_cfg(panel=EDGE_PANEL_3), hosted_cfg(panel=HOSTED_PANEL_3)]


def _synthetic_cohort():
    from aeh.conf import CohortRef

    return CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic")


# --- CT-CONFORM-06 — scoped, never merged ------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_conform_c06_every_written_record_carries_its_backend_profile_and_panel_build_ref():
    """`CT-CONFORM-06` — *"a consumer reading a validation record knows which backend produced it"*.

    Asserted over **every** record rather than over a sample, and on the values rather than on the
    fields: a record whose `backend_profile` is present and empty satisfies a schema check and
    tells the reader nothing, which is the same outcome as the field being absent. `panel_build_ref`
    is asserted alongside because `CT-CONF-07` makes it a primary-key component — two runs on one
    backend profile with different panels are different measurements (R30, RISK-08).
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    records = list(report.validation_records)
    assert len(records) == 2, (
        f"two backends produced {len(records)} validation record(s); FR-CONFORM-05 scopes the "
        f"result to each backend profile"
    )
    for record in records:
        assert record.backend_profile, "a validation record does not say which backend produced it"
        assert record.panel_build_ref, (
            "a validation record does not name its panel build ref, so two runs on one backend "
            "with different panels are indistinguishable (CT-CONF-07, R30)"
        )

    profiles = [r.backend_profile for r in records]
    assert len(set(profiles)) == 2, (
        f"both records claim the same backend profile ({profiles}); the scoping is nominal"
    )


@pytest.mark.writtenahead
def test_tc_conform_c06_a_write_merging_two_backends_into_one_record_is_refused():
    """`CT-CONFORM-06`'s decisive negative — *"never merged across them"*.

    Scoping every record correctly and *also* offering a merged write are not in tension; an
    implementation can do both, and the merged record is the one a consumer reaches for because it
    is the one that answers "how did we do". So the refusal is asserted directly by attempting the
    merge, rather than inferred from the two scoped records above.

    A merged record is not a convenience. It is a figure spanning two backends, which
    `CT-STATS-04` forbids for the same reason: there is no population it describes.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    MergeRefused = require(CONFORM_MODULE, "MergeRefused", issue="#134")

    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())
    first, second = list(report.validation_records)

    with pytest.raises(MergeRefused):
        report.write_merged_validation_record(first, second)


# --- CT-CONFORM-08 — the two tiers ----------------------------------------------------------------------


def test_tc_conform_c08_the_configuration_keeps_the_full_suite_off_the_per_commit_tier(repo_root):
    """`CT-CONFORM-08` — **green**, asserted against the configuration rather than an intention.

    *"The fast tier uses the recorded-fixture provider and needs no live model, so it can run on
    every commit; the full suite runs on every panel or model change and is not run per commit."*
    §6.11.18 is explicit that this is to be asserted *"against the CI configuration rather than as
    an intention"* — and in this repo that configuration is test plan §4.7's suite table plus
    `scripts/test.sh`, which is what `TEST_CMD` and the Stop hook actually run.

    Both places, not one. A table promising no live model while the script selected the live tier
    would be an intention, which is the word the case uses for what it will not accept.

    The rule's controls run in `test_ct_conform_vocabulary.py`: a table wired to every push
    produces every problem below by name, and a correct table produces none. Without those this
    assertion would be a green line that had never been shown capable of going red.
    """
    problems = tier_wiring_problems(
        read_repo_text(repo_root, PLAN), read_repo_text(repo_root, "scripts/test.sh")
    )
    assert problems == [], (
        f"the conformance tier wiring has drifted: {problems}. FR-CONFORM-07 is a constraint on "
        f"§4.7's table, not a suggestion — the fast tier must need no live model and the full "
        f"~23,000-call batch must not run per commit."
    )


@pytest.mark.writtenahead
def test_tc_conform_c08_the_fast_tier_runs_to_completion_with_the_network_hard_blocked(
    network_guard,
):
    """`CT-CONFORM-08`'s behavioural half — completion, not merely absence of a network call.

    The clause's claim is that the fast tier **needs no live model**, and the only way to see that
    is to hard-block the network and require the run to *finish*. A test asserting only
    `assert_no_network()` passes for a run that raised on its first fixture and made no call
    because it never got that far — which is "no network" and is not the claim.

    The boundary note is preserved as the clause states it: a fast-tier test that reaches the
    network has violated `CT-PROV-10`, and `TC-PROV-C10` is the case that catches it. The guard
    below is here so that failure is *visible* at this seam, not so this suite owns it.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    recorded = require(CONFORM_MODULE, "recorded_provider_for_fixture_set", issue="#134")

    outcome = build_suite(provider=recorded("v1")).run(
        "v1", _two_backends(), cohort=_synthetic_cohort(), tier="fast"
    )

    assert outcome.completed, (
        "the fast tier did not run to completion with the network blocked, so it needs a live "
        "model — which is what CT-CONFORM-08 says it must not"
    )
    assert outcome.fixtures_scored, "the fast tier completed having scored nothing"
    network_guard.assert_no_network()


# --- CT-CONFORM-11 — the bound, and what it is for -----------------------------------------------------


def test_tc_conform_c11_the_conformance_suite_is_wired_with_a_trigger_and_a_budget(repo_root):
    """`CT-CONFORM-11`'s gate-wiring half — **green**, and narrower than the case asks for.

    The clause's reason is the assertion: the bound exists *"so it can gate a release rather than
    being deferred to a nightly nobody reads"*, and §6.11.18 adds that *"a passing time budget
    with no gate is the same outcome as a slow suite"*.

    **§4.8's exit criteria name no conformance run.** What they name is the exclusion of
    `FR-CONFORM-06`'s divergence gate, *"not computable as written"* — which is `CT-CONFORM-14`'s
    hole, not a decision that conformance is advisory. So what is asserted is what the documents
    actually declare: a change trigger, a budget, and that the only conformance-related exclusion
    from the release gate is the uncomputable one. The gap is reported in the PR rather than
    papered over by calling a budget a gate.
    """
    plan = read_repo_text(repo_root, PLAN)
    row = find_row(markdown_rows(plan), HARNESS_CONFORM_MODULE)

    assert "min per backend" in " ".join(row), (
        "the conformance row has a trigger and no duration budget, which is an advisory job"
    )
    assert tier_wiring_problems(plan, read_repo_text(repo_root, "scripts/test.sh")) == []

    # The exclusion list, read as a whole rather than for one phrase: the assertion is that the
    # divergence gate is excluded **because it is uncomputable**, and that nothing else about
    # conformance has been quietly added beside it.
    # The paragraph, not a fixed character count: a window sized in characters silently starts
    # reading §4.9 the next time somebody adds a clause to the sentence, and the sweep below then
    # depends on what happens to be in the next section.
    marker = "**What explicitly does not gate a release**"
    start = plan.index(marker)
    excluded = plan[start : plan.index("\n\n", start)].lower()
    assert "fr-conform-06" in excluded and "not computable as written" in excluded, (
        "§4.8 no longer excludes the divergence gate on the grounds that it cannot be computed. "
        "Either the statistic was declared — in which case TC-CONFORM-C14 is due for deletion — "
        "or a gate that cannot fire is now inside the release gate."
    )
    assert "nfr-conform" not in excluded, (
        "a conformance **NFR** has been added to the list of things that do not gate a release. "
        "CT-CONFORM-11's whole point is that the time bound exists so the suite can gate one; "
        "excluding NFR-CONFORM-02 would make the bound decorative."
    )


@pytest.mark.writtenahead
@pytest.mark.slow
def test_tc_conform_c11_a_run_completes_within_the_declared_budget_on_each_backend():
    """`CT-CONFORM-11`'s measurement — **per backend**, and at the stated load.

    Per backend rather than in total: two backends inside one hour is a different claim from each
    backend inside one hour, and the clause makes the second. Summing them would let a fast edge
    run subsidise a hosted run that had quietly become unusable.

    *"Well under"* is asserted as the declared number (§4.7: `< 60 min per backend`), and the
    *"well"* is left unquantified because the design never quantified it — inventing a factor here
    would make it the requirement the first time somebody hit it.

    Marked `slow` as well as `writtenahead`: §4.7 budgets the contract tier at 60 s for all 330
    clause cases and gives conformance its own command and its own hour. A real measurement does
    not belong in that budget, so it is excluded from the fast tier by marker rather than by being
    quietly shrunk into one.
    """
    # #134 first, deliberately: this case is registered against #134 in `WRITTEN_AHEAD_BLOCKERS`,
    # and `require()` reports whichever blocker it reaches first. Resolving the fixture loader
    # first would print "blocked on #133" on a test that #133 landing does not unmark — a failure
    # message naming the wrong issue is how a gate stops being believed.
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    load_fixture_set = require(CONFORM_MODULE, "load_fixture_set", issue="#133")

    fixtures = load_fixture_set("v1")
    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    assert len(fixtures.submissions) >= 30, (
        "the bound is stated at 30–50 fixtures; measuring it at a smaller load measures something "
        "else"
    )
    for profile, result in report.per_backend.items():
        assert result.duration_seconds < CONFORMANCE_BUDGET_SECONDS, (
            f"{profile} took {result.duration_seconds:.0f}s against a budget of "
            f"{CONFORMANCE_BUDGET_SECONDS}s. NFR-CONFORM-02's bound exists so this suite can gate "
            f"a release rather than being deferred to a nightly nobody reads."
        )


# --- CT-CONFORM-12 — runs pipelines, owns none of their output -------------------------------------------


@pytest.mark.writtenahead
def test_tc_conform_c12_the_only_writes_this_module_makes_are_records_and_its_own_report():
    """`CT-CONFORM-12` — *"it runs pipelines but owns none of their output"*.

    Unusual enough to be worth stating: this module drives whole pipelines, so *something* writes
    a great deal during its run — grades, scores, ledger rows. The clause is that none of it is
    **this module's**. So the audit is read with attribution rather than as a total: writes
    attributed to `M-CONFORM` must be validation records through `M-PKG` and its own report
    artifacts, and nothing else.

    A recording audit rather than a blocking one, for the same reason `TC-CALIB-C06` needed one:
    a guard that raises on the first write cannot distinguish a permitted write from a forbidden
    one — it stops the run at whichever came first.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")

    with recording_write_audit() as writes:
        build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    assert writes, "nothing was written at all, so this audit would pass for a run that did nothing"

    ours = [w for w in writes if getattr(w, "attributed_to", None) == "M-CONFORM"]
    assert ours, (
        "no write was attributed to M-CONFORM, so either attribution is missing from the audit or "
        "the validation record CT-CONFORM-12 requires was never written"
    )
    stray = [w for w in ours if not _is_permitted_conform_write(w)]
    assert not stray, (
        f"M-CONFORM wrote {[w.target for w in stray]}. CT-CONFORM-12 permits backend-scoped "
        f"validation records through M-PKG and its own report artifacts: no grade, no score, no "
        f"package content."
    )


@pytest.mark.writtenahead
def test_tc_conform_c12_the_pipelines_own_writes_stay_attributed_to_their_owning_modules():
    """`CT-CONFORM-12`'s other half — the writes that happen and are **not** this module's.

    The complement matters. A module that re-attributed the pipeline's writes to itself would fail
    the case above; a module that *absorbed* them — writing grades under its own name because it
    was the one that started the run — would pass a check that only looked at its own writes and
    would have taken ownership of output it does not own.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")

    with recording_write_audit() as writes:
        build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    attributions = {getattr(w, "attributed_to", None) for w in writes}
    assert attributions - {"M-CONFORM", None}, (
        f"every write in the run is attributed to M-CONFORM ({attributions}). It runs pipelines "
        f"and owns none of their output — grades belong to M-GRADE, ledger rows to M-ORCH."
    )


def _is_permitted_conform_write(write) -> bool:
    """The two write kinds `CT-CONFORM-12` allows: a validation record, and a report artifact."""
    target = str(getattr(write, "target", "")).replace("\\", "/").lower()
    return "validation" in target or "/conformance-report" in target or "conform_report" in target


# --- CT-CONFORM-14 — the hole, and the consumers who must not fill it -------------------------------------


def test_tc_conform_c14_the_hole_is_still_open_in_all_three_places_that_record_it(repo_root):
    """`CT-CONFORM-14` — **green**, and it is a case with an expiry date.

    §6.11.18: *"this is a case that verifies a limitation is visible, and it should be deleted the
    day the statistic is declared."* A case that only asserted the report marks the gate
    unavailable would never notice that day — it would keep passing against a module that had been
    fixed, and would outlive its subject.

    So the assertion spans the three places the hole is recorded: the clause (design
    `CT-CONFORM-14`), the open question (design §4.6 item 2) and the plan's gap register (§7.4,
    *"**Accepted risk** until a statistic and threshold are declared"*), plus §4.8's exclusion of
    the gate from the release criteria. When any of them stops saying it, this goes red and the
    failure names which one — which is the signal to delete this case, not to weaken it.

    Each rule has its own control in `test_ct_conform_vocabulary.py`, so a rule that silently
    stopped firing is caught there rather than here.
    """
    problems = divergence_hole_problems(
        read_repo_text(repo_root, DESIGN), read_repo_text(repo_root, PLAN)
    )
    assert problems == [], (
        f"the CT-CONFORM-14 hole is no longer recorded consistently: {problems}.\n"
        f"If a statistic and threshold have been declared, CT-CONFORM-05's first gate is now "
        f"computable — **delete TC-CONFORM-C14** (§6.11.18 says so) and unmark the "
        f"score-distribution gate in EXPECTED_CLASSIFICATION. If they have not, one of the three "
        f"documents has drifted and the limitation has stopped being visible."
    )


@pytest.mark.writtenahead
def test_tc_conform_c14_m_pkg_records_no_backend_equivalence_claim():
    """`CT-CONFORM-14`'s consumer sweep, `M-PKG` half.

    *"A consumer must not report backend equivalence on the strength of a gate that cannot fire."*
    §6.11.18 asks for a sweep of `M-PKG` and `M-CONSOLE`, and the two are separated here because
    they land at different moments — #29 writes the scoped validation records, #122 builds the
    console — and keying both on the later would hold this one outside the gate for no reason.

    The sweep looks for an **affirmative** claim. The disclaimer a correct implementation prints
    contains the same words, which is the bug TS-74 shipped and had to fix twice; `equivalence_claims`
    filters negated sentences and its controls run green in `test_ct_conform_vocabulary.py`.
    """
    record_validation = require(PKG_MODULE, "record_validation", issue="#29")
    catalog = require(PKG_MODULE, "in_memory_catalog", issue="#29")()

    conformance = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")().run(
        "v1", _two_backends(), cohort=_synthetic_cohort()
    )
    for record in conformance.validation_records:
        record_validation(catalog, record)

    rendered = " ".join(
        str(catalog.render_validation_summary(r.backend_profile, r.panel_build_ref))
        for r in conformance.validation_records
    )
    claims = equivalence_claims(rendered)
    assert not claims, (
        f"M-PKG's validation summary claims the backends are equivalent: {claims}. The gate that "
        f"would justify that claim cannot fire (CT-CONFORM-14)."
    )


@pytest.mark.writtenahead
def test_tc_conform_c14_m_console_renders_no_backend_equivalence_claim():
    """`CT-CONFORM-14`'s consumer sweep, `M-CONSOLE` half.

    The console is where a release decision is actually read, so it is the surface on which an
    equivalence claim does damage. Both halves of the rendering are asserted: no affirmative claim,
    **and** the unavailable gate is shown as unavailable — a console that simply omitted the gate
    would pass a claim sweep while leaving the reader to assume it passed, which is the same
    outcome by a quieter route.
    """
    render = require(CONSOLE_MODULE, "render_conformance_surface", issue="#122")

    conformance = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")().run(
        "v1", _two_backends(), cohort=_synthetic_cohort()
    )
    rendered = render(conformance)
    text = str(rendered)

    claims = equivalence_claims(text)
    assert not claims, (
        f"the console reports backend equivalence: {claims}. CT-CONFORM-14 forbids the claim "
        f"because the gate behind it cannot fire."
    )
    assert "unavailable" in text.lower(), (
        "the console renders no unavailable gate at all. Omitting it leaves a reader to assume it "
        "passed, which is the claim by a quieter route."
    )
