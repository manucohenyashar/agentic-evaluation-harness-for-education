"""Each setup step rendered as a non-blocking prompt, with the cost of skipping it."""

from __future__ import annotations

from .html import _prompt_section


#: What each setup step asks, and the cost of skipping it, as the prompt renders both.
#: The keys are step names — the five §6.3 optional cards plus the aggregation routing
#: step `CT-AGG-14`'s consumer case renders. A name with no declared copy renders the
#: generic optional-step prompt, so a step added later degrades to a prompt with a skip
#: rather than to a blocking screen.
_SETUP_STEP_COPY: dict[str, tuple[str, str]] = {
    "Approve how the rubric was understood": (
        "Read back how the package understood each criterion, and approve it or correct "
        "it before the run starts.",
        "the read-back stands as the package wrote it, and the run starts on it "
        "unchanged; a correction after the run writes a rubric revision instead.",
    ),
    "Confirm decomposability classifications": (
        "Confirm, criterion by criterion, which are atomic (one judgment) and which are "
        "holistic (a single overall judgment).",
        "every criterion routes as the package classified it; a mis-classification "
        "costs escalation minutes later, when a panel disagrees that need not have "
        "been asked.",
    ),
    "Declare the grade policy and boundaries": (
        "Declare the grade policy and the boundaries the bands map onto.",
        "the declared defaults are used instead: boundaries land where the package's "
        "policy says they do, and the default is recorded as taken (not as your "
        "choice).",
    ),
    "Answer ambiguity-elicitation questions": (
        "This surface arrives in version 2 (Phase 4). It is rendered present-and-"
        "unavailable rather than silently absent.",
        "nothing changes: no question is pending in this version, and skipping a "
        "surface that cannot be worked records the skip in the telemetry like any "
        "other step.",
    ),
    "Mark 10 to 15 calibration papers": (
        "Mark 10 to 15 calibration papers so later versions have a fixed reference to "
        "re-read the rubric against.",
        "the papers stay stored with the package for a later version, and this "
        "administration runs without a fixed reference.",
    ),
    "aggregation": (
        "Aggregation routing runs on declared constants: the per-signal confidence "
        "caps, the disagreement threshold that widens a panel, and the random-arm "
        "sample rate are published with the package. They are declared assumptions, "
        "not findings — no accuracy claim is made for them, and the routing decision "
        "each one drives is recorded where the audit can read it.",
        "routing proceeds on the published constants either way; reading the "
        "declaration is not a gate, and every routing decision is recorded.",
    ),
}


_SETUP_STEP_GENERIC_BODY = (
    "This setup step is optional. Doing it now shapes how the run proceeds; the value "
    "it records can also be corrected after the run, at the cost of a revision."
)


_SETUP_STEP_GENERIC_COST = (
    "the step records that the default was taken, so the state is distinguishable "
    "from an explicit choice (`FR-SETUP-14`), and its cost shows up where the audit "
    "can read it."
)


def render_setup_step(step: str) -> str:
    """One setup step rendered as a non-blocking prompt (`FR-CONSOLE-06`, invariant 1):
    the step's ask and a first-class skip control whose cost renders **in the same view**
    (`R62`). Module-level so the headless driver can render one step without an app; the
    S5 cards render through this same function, so the page and the step renderer cannot
    drift into two consoles.

    The aggregation knobs are **declared** constants at Phase 1 (`CT-AGG-14`), and the
    copy says exactly that — presenting them as tuned, validated or otherwise
    empirically justified would borrow authority the label store has not granted
    (`FR-STATS-08`), so no such claim appears in any step's copy."""
    body, cost = _SETUP_STEP_COPY.get(
        step, (_SETUP_STEP_GENERIC_BODY, _SETUP_STEP_GENERIC_COST)
    )
    return _prompt_section(step, body, cost)
