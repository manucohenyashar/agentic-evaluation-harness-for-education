"""The declared band scales, and the one-step band shift a silent build substitution produces."""

from __future__ import annotations

from typing import Mapping


# --- #134: the comparison, the gates, and the backend-scoped records -----------------------------
#
# The comparison runs the identical fixture set per backend and compares the five §7.4
# dimensions. On the recorded transport the derivation is a replay of what the corpora declare:
# each fixture's per-criterion reference bands are the source corpus's declared references
# (verified at load), so a clean run measures zero divergence — the honest recorded-transport
# result, since the live tier (TC-CONFORM-04, env-gated) is where real models diverge. What the
# recorded run must be honest about is identity (one input hash, the full stage list, resolved
# rather than requested builds), scoping (backend-keyed records, never merged), and
# classification (two gates, three findings, one gate that cannot fire). The judgment figures
# are the declared references replayed; the INGEST is not replayed: every fixture — text
# fixtures included — goes through the real ingest ladder (`ingest_one`), per backend, which
# is where `FR-CONFORM-04`'s *"no stubs for ingestion"* is a fact about the real gates rather
# than a claimed stage list, and where the malicious PDFs' quarantine at V0 with zero model
# calls is a fact about the real gates.
#
# Interpretations this code commits to (reported on the PR):
# - The self-agreement figure's `n` is the number of fixtures whose judgments were derived
#   twice and compared — the sample size the agreement rate is computed over.
# - `citation_verification_outcome` replays `verified`: the declared references carry no
#   citation failures to replay, so twin pairs compare equal, which is the recorded
#   transport's honest answer (the live tier is where forged citations diverge).
# - Chance-corrected agreement convention: a replay that agrees with the declared labels on
#   every scored fixture is kappa 1.0 by definition; the live tier computes the real statistic
#   against the same labels.
# - The unit band is the mode of the fixture's declared per-criterion bands (ties broken by
#   the declared scale order), and the unit confidence the share of its criteria at the top of
#   their declared scale — both pure functions of what the corpus declares.

#: The declared band scales the corpora carry: the open criteria are four-level, the MCQ
#: criteria two-valued. Read from the corpora's declared vocabulary rather than re-invented.
_DECLARED_OPEN_SCALE = ("absent", "emerging", "developing", "secure")


_DECLARED_MCQ_SCALE = ("not_met", "met")


#: The criterion the substitution shift moves: every source corpus that declares bands
#: declares `C-01`, so the shift always has a declared value to move.
_SUBSTITUTION_CRITERION = "C-01"


#: The marker a substituted backend config carries (`silent_build_substitution` sets it on the
#: copy it yields). A leading underscore keeps it out of any serialization a caller does.
_SUBSTITUTION_MARKER = "_conform_substituted_build"


_SUBSTITUTED_BUILD_SUFFIX = "+substituted"


def _band_scale(band: str) -> tuple[str, ...]:
    return _DECLARED_OPEN_SCALE if band in _DECLARED_OPEN_SCALE else _DECLARED_MCQ_SCALE


def _shift_bands_one_step(bands: Mapping[str, str]) -> dict[str, str]:
    """One criterion's band, one step up its declared scale — the substitution shift.

    A shift of exactly one declared step is the smallest change that is still a change: it
    moves the distribution, it is detectable against the frozen references, and it stays inside
    the scale the corpus declares rather than inventing a value no fixture carries. A band
    already at the top of its scale has no next step — a fixture may legitimately sit there
    (the corpus spans the score range), so that one fixture's shift is a no-op; the
    *simulation* as a whole refuses to have moved nothing (`FixtureSet.run`'s
    `simulate_build_change` half), because a caller must never measure an unchanged
    distribution in the belief a substitution was applied.
    """
    band = bands.get(_SUBSTITUTION_CRITERION)
    if band is None:
        return dict(bands)
    scale = _band_scale(band)
    index = scale.index(band)
    if index + 1 >= len(scale):
        return dict(bands)
    shifted = dict(bands)
    shifted[_SUBSTITUTION_CRITERION] = scale[index + 1]
    return shifted
