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
        "Where your marks and the system's differed because the rubric may be unclear, "
        "answer a few short questions about how you meant it. Your answers "
        "make a clarified rubric that is checked on your next class before it is used.",
        "the test is marked with your rubric as written, and the parts a question was "
        "about are recorded as possibly unclear.",
    ),
    "Mark 10 to 15 calibration papers": (
        "Mark a few papers yourself so the system can check it reads your rubric the way "
        "you do. Upload unmarked copies (10 to 15 recommended, at most 25), enter your "
        "marks in the form, then check them. They are marked separately and never appear "
        "in a class's results; no percentage is given.",
        "the test is marked with your rubric as written; nothing else changes.",
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
    """One setup step as a non-blocking prompt (FR-CONSOLE-06, invariant 1): its question and a
    skip button with its cost in the same view (R62). The setup screen's cards use this same
    function, so the page and this renderer cannot drift apart; it is module-level so the headless
    driver can use it without an app.

    The aggregation knobs are **declared** constants at Phase 1 (`CT-AGG-14`), and the
    copy says exactly that — presenting them as tuned, validated or otherwise
    empirically justified would borrow authority the label store has not granted
    (`FR-STATS-08`), so no such claim appears in any step's copy."""
    body, cost = _SETUP_STEP_COPY.get(
        step, (_SETUP_STEP_GENERIC_BODY, _SETUP_STEP_GENERIC_COST)
    )
    if step in _CALIBRATION_STEPS:
        # FR-CONSOLE-86: the copy claims only what is served. With M-CALIB absent the step is
        # present and unavailable, naming the version it arrives in (FR-CONSOLE-25).
        from .examples_actions import examples_available

        if not examples_available():
            from .vocabulary import CALIBRATION_ARRIVES_IN

            body = (f"This step arrives in {CALIBRATION_ARRIVES_IN}. It is shown here, "
                    "unavailable, rather than left out.")
            cost = "nothing changes: the test is marked with your rubric as written."
    return _prompt_section(step, body, cost)


#: The two calibration steps, whose copy depends on M-CALIB being present.
_CALIBRATION_STEPS = frozenset({
    "Answer ambiguity-elicitation questions",
    "Mark 10 to 15 calibration papers",
})
