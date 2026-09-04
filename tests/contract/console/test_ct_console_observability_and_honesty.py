"""`CT-CONSOLE-22`, `-23`, `-24` — what the console measures, what it must not claim, and the
limitation it must not hide.

Test plan §6.11.19, TS-77 (issue #132). The last three clauses are the honesty ones, and none of
them is about the console working:

* `-22` — the skip rates are *"the pilot's actual instrument for HLD §11.9's six questions, which
  is why they are contract rather than incidental telemetry"*. Emitted in aggregate they answer
  none of the six, and the pilot's job — deciding what version 2 is — loses its evidence.
* `-23` — **AuthN/AuthZ: none, deliberately.** So the case asserts the *boundary* of that
  decision, and the obligation it puts on consumers: no console action is attributable to a
  person beyond the actor string a form supplied. A `finalized_by` presented as proof of who acted
  would be a false claim in a dispute (RISK-12).
* `-24` — **a non-promise.** English and left-to-right only, *"stated as a deliberate limitation
  rather than an oversight"*. The case asserts the limitation is honest rather than latent.

`-22` and `-23` are keyed on **#122**, which builds the console's observability and its audit
surface; `-24` on **#127**, which is where `NFR-CONSOLE-07` is traced.
"""

from __future__ import annotations

import pytest

from tests.support.console_vocabulary import (
    CONTROL_ACTION_METRIC,
    MOJIBAKE_MARKERS,
    NON_ENGLISH_LTR_PROBE,
    OBSERVABILITY_METRICS,
    OPTIONAL_SETUP_STEPS,
    REVIEW_BUDGET_METRIC,
    RTL_PROBE,
    SKIP_RATE_METRIC,
    authenticated_identity_claims,
    visible_text,
    visibly_degraded,
)
from tests.support.impl import CONSOLE_MODULE, require

pytestmark = pytest.mark.contract


# --- CT-CONSOLE-22 — the instrument, not the telemetry -------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c22_the_console_emits_all_four_declared_metrics():
    """Design §3.19's Observability line, asserted by set equality over the emitted names.

    Four metrics, and the pairing in the fourth is the measurement: **review budget requested
    versus used**. Either number alone says nothing — a budget of twenty minutes tells you what the
    teacher intended, twelve minutes used tells you what happened, and only the pair says whether
    the budget framing works at all, which is HLD §11.9's first pilot question.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    emitted = build_console().telemetry()

    missing = OBSERVABILITY_METRICS - set(emitted)
    assert not missing, (
        f"the console emits {sorted(emitted)}; design §3.19 declares {sorted(OBSERVABILITY_METRICS)}"
    )

    budget = emitted[REVIEW_BUDGET_METRIC]
    assert {"requested", "used"} <= set(budget), (
        f"the review-budget metric carries {sorted(budget)}; the clause says requested **versus** "
        f"used, and either figure on its own answers none of §11.9's questions"
    )
    assert "type" in emitted[CONTROL_ACTION_METRIC], (
        "control actions are not dimensioned by type, so a total count of actions is all anyone "
        "can read — which cannot distinguish a group accept from 200 individual ones"
    )


@pytest.mark.writtenahead
def test_tc_console_c22_skip_rates_are_emitted_per_setup_step_not_in_aggregate():
    """The clause's own reason, asserted directly: *per step*, because the six questions are per step.

    §6.11.19 is explicit — *"an aggregate skip rate cannot answer any of the six"*. A single
    "42% of optional steps were skipped" tells the pilot nothing it can act on: the decision it
    feeds is which prompts to keep, and that requires knowing that the rubric read-back was
    always completed while decomposability was always skipped.

    So the assertion is over the **dimensionality**: every optional setup step appears, by name.
    Asserted against the transcribed list rather than against whatever the console emits, since a
    console that emitted one step would otherwise satisfy "per step".
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    emitted = build_console().telemetry()
    skip = emitted[SKIP_RATE_METRIC]

    assert "setup_step" in skip, (
        f"the skip-rate metric carries dimensions {sorted(skip)} and none of them is the step. "
        f"An aggregate skip rate is incidental telemetry; CT-CONSOLE-22 makes this one contract "
        f"because it is the pilot's instrument for §11.9's six questions."
    )

    observed = set(build_console().telemetry_values(SKIP_RATE_METRIC, dimension="setup_step"))
    missing = set(OPTIONAL_SETUP_STEPS) - observed
    assert not missing, (
        f"no skip rate is emitted for {sorted(missing)}. Every optional setup step needs one, "
        f"because the question the pilot answers is which prompts to keep — and a step with no "
        f"rate is a prompt nobody can argue about."
    )


# --- CT-CONSOLE-23 — the boundary of a deliberate absence --------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c23_the_absence_of_auth_holds_only_within_the_loopback_bound():
    """`CT-CONSOLE-23` — the case asserts the **boundary**, not a capability.

    *"AuthN/AuthZ: none, deliberately, bounded by `CT-CONSOLE-05`. Single user, one machine,
    loopback."* There is nothing to test about having no authentication; what is testable is that
    the decision stays inside the bound that makes it acceptable. Design §3.19 says so in as many
    words: *"Spoofing and Elevation of privilege are out of scope because there are no accounts,
    which is exactly why network exposure is refused."*

    So: no auth surface exists, **and** the console does not run anywhere the absence would be
    indefensible. Asserting only the first half would be asserting the thing the clause concedes.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")
    start_console = require(CONSOLE_MODULE, "start_console", issue="#122")

    app = build_console()
    routes = {route for routes in app.routes().values() for route in routes}
    auth_routes = [r for r in routes if any(w in r for w in ("login", "signin", "auth", "session"))]
    assert not auth_routes, (
        f"the console exposes {auth_routes}. AuthN is absent deliberately (§3.19); a half-built "
        f"auth surface is worse than none, because it reads as a boundary that is not there."
    )

    assert app.bind_address.startswith("127.") or app.bind_address == "::1", (
        f"the console bound to {app.bind_address}. The absence of authentication is bounded by "
        f"loopback, and outside that bound this is an unauthenticated student-record system (R68)."
    )
    assert start_console is not None


@pytest.mark.writtenahead
def test_tc_console_c23_no_audit_surface_presents_an_actor_string_as_an_identity():
    """The consumer obligation, which is the part that could be got wrong.

    §6.11.19: *"sweep the audit surface and assert nothing presents an actor string as an
    authenticated identity — a `finalized_by` rendered as proof of who acted would be a false claim
    in a dispute (RISK-12)"*.

    **A correct console still renders `finalized_by`.** It must: the audit record exists and the
    string is what the form supplied. What it may not do is present that string as verified. So the
    sweep filters negated sentences, and the honest rendering — the field plus a line saying it is
    self-declared — passes. Both directions have controls in `test_ct_console_vocabulary.py`; a
    sweep that forbade the field outright would fail the correct implementation, which is how a
    scanner gets switched off.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    app = build_console()
    app.finalize_batch(run_id="r-1", actor="r.mensah")

    surfaces = [app.render(route, id="r-1") for route in app.audit_routes()]
    assert surfaces, "the console exposes no audit surface, so this sweep has nothing to sweep"

    for rendered in surfaces:
        text = visible_text(rendered.html)
        claims = authenticated_identity_claims(text)
        assert not claims, (
            f"an audit surface presents the actor string as an authenticated identity: {claims}. "
            f"The console has no accounts; in a dispute this is a claim it cannot support "
            f"(RISK-12)."
        )

    joined = " ".join(visible_text(r.html) for r in surfaces).lower()
    assert "r.mensah" in joined, (
        "the actor string is not rendered anywhere, so the sweep above passed by there being "
        "nothing to present — the audit record is supposed to be visible, just not overclaimed"
    )


# --- CT-CONSOLE-24 — the non-promise ---------------------------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize(
    "probe, label",
    [(RTL_PROBE, "right-to-left"), (NON_ENGLISH_LTR_PROBE, "non-English left-to-right")],
)
def test_tc_console_c24_non_english_and_rtl_content_fails_or_degrades_visibly(probe, label):
    """`NFR-CONSOLE-07` — the limitation is honest rather than latent.

    A non-promise case needs an assertion about **visibility**, not about capability. The clause
    concedes that the MVP is English and left-to-right; what it does not concede is silence.
    §6.11.19: the system must *"fail or degrade visibly rather than rendering mojibake or silently
    reversing text in a way a monolingual operator would not notice"*.

    That last clause is the whole case. An operator who does not read Arabic cannot tell correctly
    ordered text from reversed text, so a page that renders RTL content confidently and says
    nothing has produced an error only the student will find — and §0.2's deployment context makes
    that a realistic submission rather than a hypothetical one.

    So `visibly_degraded` enumerates the three outcomes the clause allows — raised, refused, or a
    rendering that names the limitation — and the silent render satisfies none. Phrasing the test
    as "no mojibake" would have passed on exactly the outcome the clause is about, which is why
    the predicate has its own control.
    """
    ingest_and_render = require(CONSOLE_MODULE, "render_submission_text", issue="#127")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    raised: BaseException | None = None
    outcome = None
    try:
        outcome = ingest_and_render(build_console(), text=probe)
    except Exception as exc:  # noqa: BLE001 — any failure counts, and the clause allows failing
        raised = exc

    rendered = "" if outcome is None else visible_text(outcome.html)
    refused = bool(outcome is not None and getattr(outcome, "refused", False))

    assert visibly_degraded(rendered, raised, refused), (
        f"{label} content rendered with no error, no refusal and no statement of the limitation. "
        f"NFR-CONSOLE-07 makes English/LTR a **deliberate** limitation, and a limitation the "
        f"operator cannot see is an oversight whatever the design calls it. Rendered: {rendered!r}"
    )

    present = [marker for marker in MOJIBAKE_MARKERS if marker in rendered]
    assert not present, (
        f"{label} content rendered as mojibake ({present}). The clause permits failing and permits "
        f"degrading visibly; it does not permit corrupting the text and displaying it."
    )
