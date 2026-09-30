"""The errors M-CALIB raises. None is transient, so none is retried."""

from __future__ import annotations


# --- errors ----------------------------------------------------------------------------------------


class CalibrationError(Exception):
    """Base for every `M-CALIB` refusal. Nothing here is transient; no caller
    should retry, so there is deliberately no retry taxonomy."""


class TriageCategoryRequired(CalibrationError):
    """A disagreement arrived at the triage boundary without its required
    category (`FR-CALIB-02`, `CT-CALIB-04`).

    This is the required-field design's enforcement point: an uncategorized
    disagreement would default into *some* path, and the editable path is the
    dangerous default — the module would fit the rubric to a disagreement
    nobody classified. The refusal is the field's "required", not a
    convention that a category is usually present."""


class SideBySideRequired(CalibrationError):
    """A `teacher_inconsistency` verdict was constructed without exactly two
    examples (`FR-CALIB-03`).

    Both examples side by side is the finding's whole shape: one example
    accuses the teacher, two let the teacher compare their own judgments and
    resolve the inconsistency themselves. A one-example verdict is the
    accusation wearing the finding's name, so it is unconstructible rather
    than discouraged."""


class EditNotEligible(CalibrationError):
    """An edit was attached to a verdict whose category cannot carry one
    (`FR-CALIB-02`, `CT-CALIB-04`).

    Only `rubric_ambiguity` is eligible to produce a proposed edit, and the
    rule is structural: the constructor refuses the violating shape, so no
    caller — and no future code path in this module — can attach an edit to a
    `model_failure` or `teacher_inconsistency` verdict. A policy check beside
    the constructor would be a second implementation of one rule, and two
    implementations of one rule drift."""


# --- phasing: the §6.2 lock is a dependency, declared not inferred (CT-CALIB-15) --------------------
#
# "Triage, dual-scoring non-inferiority and back-translation are Phase 3; elicitation is
# Phase 4; the §6.2 lock they depend on is Phase 1 and belongs to M-PKG." The lock is what
# makes CT-CALIB-06 structural: every calibration edit routes through M-PKG, so the lock
# applies to calibration output without this module implementing a check of its own. An
# edit attempted against a package version created BEFORE the lock existed would bypass
# that guarantee — so the vintage is a declared fact, not an inferred one (see the module
# docstring), and `apply_answers` refuses it.


class PhaseDependencyError(CalibrationError):
    """An edit was attempted against a package version whose schema predates the §6.2
    lock the edit's route depends on (`CT-CALIB-15`).

    The lock is a Phase 1 fact about the schema a version was born under, and a version
    born before it cannot carry the guarantee that makes calibration's write route
    structural: the catalog would apply the edit, but the lock that every accumulated
    validation record leans on was not yet in the file. The refusal names the version
    and the dependency; the fix is a version created under the current schema."""


class ThresholdNotDeclared(CalibrationError):
    """The non-inferiority gate was asked to run with no threshold declared for it
    (`FR-CALIB-08`, `CT-CALIB-13`).

    The threshold is an **owned decision**: 0.10 is the HLD's *example*, not a validated
    value, and the design says it "must be declared per institution before use". A gate
    that fell back to a default would let an unowned number decide whether a rubric
    changes — the institution that inherits it never chose it. Declare one (an explicit
    argument, `declare_institutional_threshold`, or the deployment's env) and the gate
    runs; with neither, this is the refusal."""


class InsufficientPopulation(CalibrationError):
    """The gate was asked to run on a population that cannot carry its verdict
    (`NFR-CALIB-02`, `CT-CALIB-07`).

    The gate operates on the **full class** and refuses the calibration set, which lacks
    the sample size to mean anything. A refusal rather than a warning, because a gate run
    on twenty papers returns a number — and a number that means nothing is a passed gate
    somebody will cite."""


class OffPanelConfigurationError(CalibrationError):
    """The off-panel model is **in the scoring panel** (`CT-CALIB-08`, `NFR-CALIB-04`).

    Refused when the *build* matches, not merely the label — two entries naming the same
    served build are the same model, which is the identity `M-CONF`'s
    `compute_panel_build_ref` hashes (and what `RunConfig.__post_init__` refuses at
    configuration time). A shared build would let the panel's own blind spots define the
    adversarial search: the model looking for a response on which R₀ and R₁ differ would
    be the same model that produced the scores, so the responses it cannot imagine are
    exactly the ones it will not construct, and the gate would pass by construction."""


class OffPanelUnavailable(CalibrationError):
    """The off-panel build has no bound construction transport (`CT-CALIB-02`'s
    "off_panel_model_unavailable" mode).

    The gate never invents a construction: the session for the off-panel build is bound
    at wiring time — the same recorded-transport form discovery's bands arrive in
    (`CT-PROV-10`) — and a build with none bound is *unavailable*, which ends at R₀ like
    every other failure mode."""
