"""Test seams: cohorts with a band shift, off-panel and in-panel models, a counting provider."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import _FIXTURE_CRITERION_ID
from .errors import CalibrationError
from .off_panel import (
    _BackTranslationSession,
    _ConstructionAttempt,
    _OFF_PANEL_SESSIONS,
    OffPanelModelRef,
    _PANEL_BUILDS,
)
from .rosters import _CLASS_ROSTERS, _ClassRoster


# --- the guardrail gates' test seams (contract suite, §6.11.17) -------------------------------------
#
# The same pattern the #137/#138 seams above established: part of the module's surface,
# exported in `__all__`, so the contract cases drive exactly the surface a real caller would
# and no test-side double stands in for the module. The rosters and construction sessions are
# the recorded-transport form (`CT-PROV-10`) — production binds them at wiring time; these
# seams bind them in-process.


#: Monotonic counter minting unique registered cohort ids.
_COHORT_COUNTER = 0


def cohort_with_band_shift(*, fraction: float, class_size: int = 100) -> str:
    """Register a class roster in which ``fraction`` of the papers moved a full band
    under R₁, and return its cohort id — the recorded-transport form the
    non-inferiority gate consumes (`CT-PROV-10`).

    Single criterion, two bands: a shifted paper moves from band 1 under R₀ to band 0
    under R₁ (the conservative direction), every other paper keeps its band. The shift
    count is rounded half-up — the reading a class expresses — so a 100-student class
    carries every fraction a realistic sweep needs exactly (the boundary cases,
    0.10 against a 0.10 threshold, round to exactly ten papers)."""
    global _COHORT_COUNTER
    fraction = float(fraction)
    if not 0.0 <= fraction <= 1.0:
        raise CalibrationError(
            f"the shifted fraction is a fraction of the class, got {fraction!r}"
        )
    if isinstance(class_size, bool) or not isinstance(class_size, int) or class_size < 1:
        raise CalibrationError(f"class_size must be a positive integer, got {class_size!r}")
    shifted_count = int(class_size * fraction + 0.5)  # round-half-up, the class's reading
    scores = tuple(
        ((1, 0) if index < shifted_count else (1, 1),) for index in range(class_size)
    )
    _COHORT_COUNTER += 1
    cohort_id = f"cohort-band-shift-{_COHORT_COUNTER:04d}"
    _CLASS_ROSTERS[cohort_id] = _ClassRoster(
        cohort_id=cohort_id,
        class_size=class_size,
        criteria=(_FIXTURE_CRITERION_ID,),
        scores=scores,
        is_calibration_set=False,
    )
    return cohort_id


#: Counter minting unique off-panel build ids, so two registered refs never share a key.
_OFF_PANEL_COUNTER = 0


def _off_panel_model_ref(*, constructs: bool | None = True) -> OffPanelModelRef:
    """Register an off-panel build and return its ref.

    ``constructs=True`` binds a session whose attempts construct a divergent response
    (the CT-CALIB-08 construction); ``False`` binds one that probes several angles and
    constructs nothing (the pass case whose note holds §6.6's honest reading); ``None``
    binds nothing — the unavailable transport (`OffPanelUnavailable`'s path)."""
    global _OFF_PANEL_COUNTER
    _OFF_PANEL_COUNTER += 1
    ref = OffPanelModelRef(
        provider="fixture",
        build_id=f"off-panel-constructor-{_OFF_PANEL_COUNTER:03d}@sha256:"
        + ("beef" if constructs else "cafe"),
    )
    if constructs is not None:
        if constructs:
            session = _BackTranslationSession(
                attempts=(
                    _ConstructionAttempt(
                        angle="probing the top band's boundary", response=None
                    ),
                    _ConstructionAttempt(
                        angle="probing the bottom band's boundary", response=None
                    ),
                    _ConstructionAttempt(
                        angle="a response the clarified descriptor reads differently",
                        response=(
                            "The student restates the criterion accurately but stops "
                            "short of the worked example the clarified descriptor asks "
                            "for: R0 bands the response 1 ('meets it') and R1 — which "
                            "now requires the example — bands it 0 ('needs work'). One "
                            "response, two different scores: the divergence a changed "
                            "construct predicts."
                        ),
                        divergence_note="R0 bands 1, R1 bands 0 under the clarified descriptor",
                    ),
                )
            )
        else:
            session = _BackTranslationSession(
                attempts=(
                    _ConstructionAttempt(
                        angle="probing the top band's boundary", response=None
                    ),
                    _ConstructionAttempt(
                        angle="probing the bottom band's boundary", response=None
                    ),
                    _ConstructionAttempt(
                        angle="probing a mid-band response the clarifications touch",
                        response=None,
                    ),
                )
            )
        _OFF_PANEL_SESSIONS[ref.build_key] = session
    return ref


def model_ref_off_panel() -> OffPanelModelRef:
    """An off-panel build with a bound construction session whose attempts construct a
    response on which R₀ and R₁ would differ — the construction `CT-CALIB-08` treats as
    evidence the construct changed."""
    return _off_panel_model_ref(constructs=True)


def model_ref_in_panel() -> OffPanelModelRef:
    """A model ref registered as **in the scoring panel** (`CT-CALIB-08`): handing it to
    `back_translate` as the off-panel checker is the shared-build configuration
    `NFR-CALIB-04` refuses."""
    global _OFF_PANEL_COUNTER
    _OFF_PANEL_COUNTER += 1
    ref = OffPanelModelRef(
        provider="fixture",
        build_id=f"panel-shared-build-{_OFF_PANEL_COUNTER:03d}@sha256:aaaa",
    )
    _PANEL_BUILDS.add(ref.build_key)
    return ref


@dataclass(frozen=True)
class WorseButLowShiftRevision:
    """The `CT-CALIB-16` fixture: a revision that is genuinely worse yet shifts few
    students.

    ``is_genuinely_worse`` is the fixture's **declaration**, not a measurement — the gate
    cannot see worse-ness, and that is the non-promise: a pass means only that the class
    did not shift beyond the threshold and that an off-panel model constructed no
    divergence. Asserting the pass is what keeps the gate from being read as a quality
    check (§7.3's residual risk)."""

    r0: str
    r1: str
    cohort_id: str
    shifted_fraction: float
    is_genuinely_worse: bool
    note: str


def worse_but_low_shift_revision() -> WorseButLowShiftRevision:
    """A genuinely worse revision that shifts under the threshold, registered against a
    real roster (`CT-CALIB-16`).

    The revision narrows the top band's descriptor — a documented loss the fixture
    declares — while the roster it is registered against moves under a tenth of the
    class. The gate passes it: rejecting it would be the superiority claim the design
    explicitly does not make."""
    fraction = 0.03
    cohort_id = cohort_with_band_shift(fraction=fraction, class_size=100)
    return WorseButLowShiftRevision(
        r0="pkg-v1",
        r1="pkg-v2",
        cohort_id=cohort_id,
        shifted_fraction=fraction,
        is_genuinely_worse=True,
        note=(
            "the revision narrows the top band's descriptor, a documented loss the gate "
            "cannot see; the class shift stays under the declared threshold, which is "
            "the only thing a pass means (CT-CALIB-16)"
        ),
    )


class _CountingProvider:
    """The injected provider `CT-CALIB-12` counts calls on: the seam production binds to
    the panel's scoring worker and a test binds to a counter.

    ``score(paper, criterion)`` is the dual-scoring call shape — one call per
    (submission, criterion) pair — and ``calls`` is the observed count the contract
    asserts against, not a figure the provider authors."""

    def __init__(self) -> None:
        self.calls = 0

    def score(self, paper: int, criterion: int) -> str:
        self.calls += 1
        return f"band-{(paper + criterion) % 2}"


def counting_provider_for_test() -> _CountingProvider:
    """The injected provider `CT-CALIB-12`'s call-count assertion drives: every call is
    counted, so the disclosed estimate and the incurred cost are compared against what
    actually happened."""
    return _CountingProvider()
