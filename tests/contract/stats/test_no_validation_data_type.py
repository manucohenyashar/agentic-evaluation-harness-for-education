"""`CT-STATS-03` — `NoValidationData` is a distinct type, never a number.

Test plan §6.11.16, `TC-STATS-C03`, the second §4.7 safety property in this suite, at the path the
plan names. The clause's own framing, which is unusually strong for a design document:

> Returning a plausible-looking number instead of this value would be the most damaging possible
> failure in the system, which is why the distinction lives in the type system rather than in a
> convention.

The damage is specific and it is portable. A package with no validation evidence that advertises
`0.00` reads as *measured and bad* rather than *never measured* — and `CT-PKG-13` then exports it
to another school, where nobody can tell the difference either.

Four steps, four kinds of assertion, four tests: the type and its reasons, the coercion refusals,
the entry-point sweep, and the rendering at rung 3. The last one is `M-CONSOLE`'s behaviour and is
keyed on #125 rather than on #115 — keying it on the module would hold `M-CONSOLE`'s half outside
the gate until a story it does not depend on lands.
"""

from __future__ import annotations

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import CONSOLE_MODULE, STATS_MODULE, require

pytestmark = pytest.mark.contract


# --- step 1: a distinct type, carrying one of three reasons ------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("reason", vocab.NO_VALIDATION_DATA_REASONS)
def test_tc_stats_c03_is_a_distinct_type_carrying_each_declared_reason(reason):
    """Step 1 — *"not a null, not a zero, not a sentinel float"*, swept over all three reasons.

    The three reasons are not decoration: they are the difference between *nobody has collected
    blind labels yet*, *this population has never been administered*, and *this backend has never
    been measured*. A consumer that receives one absence value for all three cannot say which,
    and `FR-CONSOLE-24` and `FR-CONSOLE-26` require the console to render two of them differently.

    Asserted against the numeric types by name rather than by behaviour, because the adversarial
    construction is precisely a `float` subclass: `isinstance(value, float)` is what catches it,
    and every behavioural probe it would pass.
    """
    NoValidationData = require(STATS_MODULE, "NoValidationData", issue="#115")
    value = NoValidationData(reason=reason)

    assert value is not None, "absence is a value; None is the null this clause forbids"
    assert not isinstance(value, (float, int, str, bool)), (
        f"NoValidationData is a {type(value).__name__}. CT-STATS-03 puts the distinction in the "
        "type system: a float subclass keeps every call site working and advertises 0.00 for a "
        "package that was never measured."
    )
    assert value.reason == reason


@pytest.mark.writtenahead
def test_tc_stats_c03_refuses_a_reason_outside_the_declared_literal():
    """The `Literal` is part of the type, so a reason outside it is not representable.

    Without this, `reason` is a free-text field and the three-way distinction the console renders
    is a convention again — which is the thing this clause exists to stop being.
    """
    NoValidationData = require(STATS_MODULE, "NoValidationData", issue="#115")

    with pytest.raises((ValueError, TypeError)):
        NoValidationData(reason="probably_fine")


# --- step 2: not numerically coercible ------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c03_is_not_numerically_coercible_by_any_route():
    """Step 2 — `float()`, arithmetic, comparison and format-as-percentage must **each** raise.

    Each, not one. The construction the clause names keeps *every* call site working, so a probe
    that only tried `float()` would understate what shipping it costs and would pass a value that
    still formats itself as `0.00%` into a report.

    The probe itself is controlled in both directions in `test_ct_stats_vocabulary.py`: it reports
    nothing for a compliant absence value and reports all five for the float subclass.
    """
    NoValidationData = require(STATS_MODULE, "NoValidationData", issue="#115")
    value = NoValidationData(reason="no_blind_labels")

    permitted = vocab.numeric_coercions(value)
    assert permitted == [], (
        f"NoValidationData permits {permitted}. CT-STATS-03 puts the distinction in the type "
        "system rather than in a convention, and every coercion that succeeds is a call site "
        "where the convention is all that is left."
    )


# --- step 3: every path that can lack data returns it ----------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize(
    "member", sorted(vocab.FIGURE_MEMBERS), ids=sorted(vocab.FIGURE_MEMBERS)
)
def test_tc_stats_c03_every_entry_point_returns_the_value_rather_than_a_substitute(member):
    """Step 3 — the sweep, *"since one path returning `0.0` is the whole failure"*.

    One row per member of `ValidationStats`, each **keyed on the story that delivers it**.
    `require()` reports whichever blocker resolves first, so a sweep keyed entirely on #115 would
    report all seven rows as runnable the moment the filter lands, five of them against functions
    that do not exist — and whoever acted on that would unmark a P0 case that cannot pass.

    Driven with an empty label set, which is the state every one of these can be in: a cohort
    whose blind sample was skipped has no admissible labels and every figure over it is absent.

    `promote` is swept in `TC-STATS-C16` instead. Its no-data outcome is `CT-STATS-05`'s *"no new
    validation evidence for this administration"*, a first-class value of a different kind —
    asserting `NoValidationData` here would demand a return type the contract does not promise and
    would contradict `TC-STATS-C05`.
    """
    issue = vocab.MEMBER_ISSUE[member]
    require(STATS_MODULE, member, issue=issue)  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    NoValidationData = require(STATS_MODULE, "NoValidationData", issue="#115")

    stats = build_stats(labels=[])
    result = getattr(stats, member)(**vocab.EMPTY_DATA_CALL[member])

    assert isinstance(result, NoValidationData), (
        f"{member}() returned {result!r} for an empty label population. CT-STATS-16: insufficient "
        "data is a value, not an exception — and CT-STATS-03: not a substitute figure either."
    )


@pytest.mark.writtenahead
@pytest.mark.parametrize("reason", vocab.NO_VALIDATION_DATA_REASONS)
def test_tc_stats_c03_agreement_reports_which_kind_of_absence_it_found(reason):
    """Step 3's other half: the three reasons are **reachable**, not merely declarable.

    A module that returns `no_blind_labels` for every absence satisfies the type assertion above
    and still leaves the console unable to tell "never administered here" from "administered, no
    blind sample" — two different things to tell a teacher, and `FR-CONSOLE-24`/`-26` require
    different messages for them.

    Each reason is provoked by the condition that produces it: no admissible labels, a population
    the package was never administered to, a backend never measured.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")

    known_scope, known_backend = "y9-2026-spring", "edge-local-q4"
    labels = [] if reason == "no_blind_labels" else [broken.ADMISSIBLE_LABEL]
    scope = "never-administered" if reason == "no_data_for_population" else known_scope
    backend = "never-measured" if reason == "no_data_for_backend" else known_backend

    stats = build_stats(
        labels=labels, population_scopes=[known_scope], backend_profiles=[known_backend]
    )
    result = stats.agreement(
        package_version="pkg-v1",
        criterion_id="C-01",
        scope=scope,
        backend_profile=backend,
        panel_build_ref="9f2a1c",
        scoring_model="atomic",
    )

    assert result.reason == reason, (
        f"the absence was reported as {result.reason!r} rather than {reason!r}; the three reasons "
        "are what let a consumer say which absence it is looking at"
    )


# --- step 4: the rendering, at rung 3 ----------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c03_the_console_renders_the_absence_and_never_a_zero_or_a_blank():
    """Step 4 at **rung 3** — *"never as `0.00` and never as a blank"*.

    Two failure modes and the second is quieter. `0.00` is a wrong claim a reader can at least
    see; a blank cell is the §2.1 error itself, an empty space that reads as *fine*. So an empty
    rendering fails this case as hard as a zero does.

    `M-CONSOLE`'s behaviour, so keyed on **#125** — invariant 21, honest absence (`FR-CONSOLE-24`)
    — rather than on `M-STATS`. Keying it on #115 would report it runnable while the console that
    has to render it is three stories away.
    """
    # `M-CONSOLE` first: this case is registered under #125, and `require()` reports
    # whichever blocker resolves first -- so the console's renderer is what names it.
    render_agreement_block = require(
        CONSOLE_MODULE, "render_agreement_block", issue="#125"
    )
    NoValidationData = require(STATS_MODULE, "NoValidationData", issue="#115")

    rendered = render_agreement_block(
        figure=NoValidationData(reason="no_blind_labels"), population="y9-2026-spring"
    )
    text = rendered if isinstance(rendered, str) else rendered.text

    assert text.strip(), (
        "the agreement block rendered blank for an absence of evidence. A blank cell reads as "
        "'fine' — it is the §2.1 error, and it is the one nobody reports as a bug."
    )
    assert "0.00" not in text and "0.0%" not in text, (
        f"the console rendered a zero for an absence of evidence: {text!r}. A reader takes that "
        "as measured-and-bad rather than never-measured, and CT-PKG-13 exports it."
    )
    assert vocab.NO_NEW_VALIDATION_EVIDENCE in text.lower() or "no validation" in text.lower(), (
        f"the rendering says nothing about the absence: {text!r}"
    )


# --- the adversarial construction, and it runs green -------------------------------------------------


def test_the_float_subclass_construction_turns_this_case_red_and_leaves_the_fr_cases_green():
    """§6.11.16 requires the named adversarial construction to be demonstrated, not described.

    *"Make `NoValidationData` a `float` subclass valued `0.0` so existing formatting code doesn't
    need to change."* Both halves:

    1. **This case goes red.** It is an instance of `float`, and every one of the five coercions
       succeeds.
    2. **Every `FR-STATS-*` case stays green.** `FR-STATS-04` asks for *"an explicit
       `NoValidationData` value rather than a substitute figure"* — and this **is** a
       `NoValidationData` value carrying a declared reason. It is returned rather than raised, so
       `CT-STATS-16` is satisfied too. Every call site keeps working; every template renders.

    That is the shape of the failure: nothing below the clause level objects, and a package with
    no evidence ships advertising an agreement of 0.00.

    Green today — it operates on a fixture, so it demonstrates that the probe discriminates rather
    than claiming anything about `M-STATS`.
    """
    adversarial = broken.FloatSubclassNoValidationData(reason="no_blind_labels")

    # Half one: the clause case fails on it.
    assert isinstance(adversarial, float)
    assert vocab.numeric_coercions(adversarial), "the probe did not fire on the float subclass"
    assert f"{adversarial:.2f}" == "0.00", (
        "the construction no longer formats as 0.00, which is the whole reason it is tempting"
    )

    # Half two: the FR-level properties it still satisfies.
    assert adversarial.reason in vocab.NO_VALIDATION_DATA_REASONS, (
        "FR-STATS-04 asks for an explicit value carrying a reason, and this construction provides "
        "one — which is why no FR case can see the violation"
    )
    assert vocab.numeric_coercions(
        broken.CompliantNoValidationData("no_blind_labels")
    ) == [], "the compliant control now permits a coercion, so the probe proves nothing"
