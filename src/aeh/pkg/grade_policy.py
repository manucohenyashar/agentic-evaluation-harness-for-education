"""`GradePolicy` and its rules, the default policy, and the canonical band-to-points mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .errors import GradePolicyError, PackageError


# --- the grade policy: a structured object from a closed vocabulary (FR-PKG-14/-15/-19) ---------
#
# The vocabulary is CLOSED by an explicit ADR: weighted sum, gate, best-k-of-n,
# drop-lowest-n, scale, rounding, boundary table. A free-text formula or an executable
# expression in a package is an arbitrary-code surface and an un-auditable grade, so the
# policy exists only as this structured object — validated at construction, at write and
# at read — and its `plain_language` wording is GENERATED from the object (`FR-PKG-15`),
# never accepted as input, so the approved wording and the executed policy cannot diverge.

#: The combination rules: how criterion scores become one total. Exactly one is in force.
COMBINATION_RULES: tuple[str, ...] = ("weighted_sum", "best_k_of_n", "drop_lowest_n")


#: The rounding modes. Rounding is declarative — `M-GRADE` executes it (FR-GRADE-02).
ROUNDING_MODES: tuple[str, ...] = ("nearest", "up", "down")


@dataclass(frozen=True)
class GateRule:
    """A gate: the named criterion must reach `minimum` for the computed grade to stand
    (FR-GRADE-02's "optional gate"). The policy records the rule; the consequence is
    M-GRADE's declared behaviour — the policy never encodes it a second way."""

    criterion_id: str
    minimum: float


@dataclass(frozen=True)
class ScaleRule:
    """A scale: the raw total is multiplied by `factor` (e.g. target-max / raw-max)."""

    factor: float


@dataclass(frozen=True)
class GradePolicy:
    """The grade policy as a structured object (`FR-PKG-14`).

    Fields are the closed vocabulary; everything not selected must be absent, so the
    object never carries a parameter no rule executes (a free parameter is how a formula
    re-enters through the back door). Validation runs in `__post_init__`: an
    out-of-vocabulary rule — including a formula string, an executable expression, or a
    lambda-shaped string — cannot become an object at all.

    The boundary-table vocabulary member has NO field here by design: `grade_boundary`
    rows are the single canonical representation of the grade resolution rule
    (`FR-PKG-16`), and a flag on the policy would be a second copy that can disagree
    with the table — the same ADR-1 reasoning as the answer key.

    `review_window_hours` is ADR-3's column: nullable, and null means finalize on run
    completion (`FR-PKG-19`) rather than wait indefinitely.
    """

    combination: str = "weighted_sum"
    weights: tuple[tuple[str, float], ...] = ()
    k: int | None = None
    drop: int | None = None
    gate: GateRule | None = None
    scale: ScaleRule | None = None
    rounding: str | None = None
    decimals: int | None = None
    review_window_hours: int | None = None

    def __post_init__(self) -> None:
        if self.combination not in COMBINATION_RULES:
            raise GradePolicyError(
                f"grade-policy rule {self.combination!r} is not in the closed "
                f"vocabulary {COMBINATION_RULES} (FR-PKG-14). A free-text formula, an "
                "executable expression or a lambda-shaped string is refused: the policy "
                "is a structured object a machine can execute and a teacher can read, "
                "never a formula."
            )
        if self.combination == "weighted_sum":
            if self.k is not None or self.drop is not None:
                raise GradePolicyError(
                    "a weighted_sum policy carries no k or drop — a parameter no rule "
                    "executes is a latent formula (FR-PKG-14)."
                )
            for criterion_id, weight in self.weights:
                if not criterion_id:
                    raise GradePolicyError(
                        "a weighted_sum weight names an empty criterion id."
                    )
                if not weight > 0:
                    raise GradePolicyError(
                        f"the weight for {criterion_id!r} is {weight!r}; weights are "
                        "positive — a zero or negative weight is a formula's job, not a "
                        "vocabulary member's."
                    )
        elif self.combination == "best_k_of_n":
            if self.k is None or self.k < 1:
                raise GradePolicyError(
                    "a best_k_of_n policy declares k >= 1 (FR-PKG-14)."
                )
            if self.weights or self.drop is not None:
                raise GradePolicyError(
                    "a best_k_of_n policy carries no weights or drop — a parameter no "
                    "rule executes is a latent formula (FR-PKG-14)."
                )
        else:  # drop_lowest_n
            if self.drop is None or self.drop < 1:
                raise GradePolicyError(
                    "a drop_lowest_n policy declares drop >= 1 (FR-PKG-14)."
                )
            if self.weights or self.k is not None:
                raise GradePolicyError(
                    "a drop_lowest_n policy carries no weights or k — a parameter no "
                    "rule executes is a latent formula (FR-PKG-14)."
                )
        if self.gate is not None and (not self.gate.criterion_id
                                      or self.gate.minimum < 0):
            raise GradePolicyError(
                "a gate names a criterion and a minimum >= 0 (FR-GRADE-02's optional "
                "gate, as a vocabulary member of FR-PKG-14)."
            )
        if self.scale is not None and not (self.scale.factor > 0):
            raise GradePolicyError(
                "a scale factor is positive — a zero or negative factor is not a "
                "scaling rule (FR-PKG-14)."
            )
        if self.rounding is not None:
            if self.rounding not in ROUNDING_MODES:
                raise GradePolicyError(
                    f"rounding mode {self.rounding!r} is not in {ROUNDING_MODES} "
                    "(FR-PKG-14)."
                )
            if self.decimals is None or self.decimals < 0:
                raise GradePolicyError(
                    "a rounding rule declares its decimals >= 0 (FR-PKG-14)."
                )
        elif self.decimals is not None:
            raise GradePolicyError(
                "decimals without a rounding mode is a parameter no rule executes "
                "(FR-PKG-14) — set rounding with it."
            )
        if self.review_window_hours is not None:
            if (isinstance(self.review_window_hours, bool)
                    or not isinstance(self.review_window_hours, int)
                    or self.review_window_hours < 0):
                raise GradePolicyError(
                    f"review_window_hours is {self.review_window_hours!r}; it is a "
                    "nullable INTEGER >= 0 (ADR-3, FR-PKG-19): null means finalize on "
                    "run completion, a negative window would end before it begins."
                )

    @property
    def plain_language(self) -> str:
        """The approved wording, GENERATED from the object (`FR-PKG-15`).

        A property, not a field: there is no constructor argument, no setter and no
        stored form, so independent wording cannot enter through any API and the
        approved wording and the executed policy cannot diverge. Regenerating from the
        same object is byte-stable (a pure function of the fields)."""
        if self.combination == "weighted_sum":
            if self.weights:
                listing = ", ".join(f"{criterion} x{weight:g}"
                                    for criterion, weight in self.weights)
                head = f"Weighted sum of criterion points ({listing})."
            else:
                head = "Sum of criterion points, summed into question and test totals."
        elif self.combination == "best_k_of_n":
            head = f"Best {self.k} of the criteria count toward the total."
        else:
            head = f"The lowest {self.drop} criterion scores are dropped before summing."
        parts = [head]
        if self.gate is not None:
            parts.append(f"Gate: {self.gate.criterion_id} must reach "
                         f"{self.gate.minimum:g} points.")
        if self.scale is not None:
            parts.append(f"The total is scaled by {self.scale.factor:g}.")
        if self.rounding is not None:
            word = {"nearest": "to the nearest", "up": "up", "down": "down"}[
                self.rounding]
            parts.append(f"Rounded {word} at {self.decimals} decimal place(s).")
        if self.review_window_hours is None:
            parts.append("Finalizes on run completion.")
        else:
            parts.append(f"Review window: {self.review_window_hours} hour(s) before "
                         "finalization.")
        return " ".join(parts)

    def to_dict(self) -> dict:
        """The structured content as stored. `review_window_hours` is absent on purpose:
        it lives in its own column (ADR-3), the single canonical place — writing it
        twice in one row would be two representations of one rule."""
        return {
            "combination": self.combination,
            "weights": [list(pair) for pair in self.weights],
            "k": self.k,
            "drop": self.drop,
            "gate": ({"criterion_id": self.gate.criterion_id,
                      "minimum": self.gate.minimum} if self.gate else None),
            "scale": ({"factor": self.scale.factor} if self.scale else None),
            "rounding": self.rounding,
            "decimals": self.decimals,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GradePolicy":
        """Rebuild from stored JSON — re-validating against the closed vocabulary, so a
        row hand-edited to hold a formula refuses on read too (`FR-PKG-14` holds at
        every door, not only at the write)."""
        fields = dict(data)
        if isinstance(fields.get("gate"), dict):
            fields["gate"] = GateRule(**fields["gate"])
        if isinstance(fields.get("scale"), dict):
            fields["scale"] = ScaleRule(**fields["scale"])
        if isinstance(fields.get("weights"), list):
            fields["weights"] = tuple((str(c), float(w)) for c, w in fields["weights"])
        try:
            return cls(**fields)
        except (TypeError, ValueError, KeyError) as error:
            # A stored row that is not a valid policy dict (hand-edited, corrupt) is a
            # vocabulary refusal, not a raw TypeError: FR-PKG-14 holds at read too.
            raise GradePolicyError(
                f"the stored grade policy is not a structured object from the closed "
                f"rule vocabulary (FR-PKG-14): {error}"
            ) from error


def default_grade_policy() -> GradePolicy:
    """`FR-SETUP-12`'s default: unweighted sum of criteria into question and test
    totals, raw points, no transforms, null review window (finalize on run completion).
    `grade_policy()` answers this for a version with no stored policy, so M-GRADE
    always finds a policy and never invents one (`CT-SETUP-10`); recording that the
    default was used is M-SETUP's obligation, discharged by storing the policy."""
    return GradePolicy()


# --- the single band→points mapping ---------------------------------------------------------------


def points_for_band(bands: Sequence[Any], band_name: str) -> float:
    """The canonical band→points mapping, module-level and pure (`CT-PKG-05`,
    `NFR-AGG-02`; issue #91's mapping stage).

    One definition, in M-PKG, of the only sanctioned reader of a band table's
    points: every consumer routes through this function rather than re-deriving a
    mapping — `M-AGG`'s aggregation maps the *aggregated* band through it exactly
    once, after the median is taken (`FR-AGG-02`), and a per-judge average of
    mapped points has no code path and may not gain one.

    `bands` is the declared band set in any row shape the module already produces
    — the store cache's mappings (`{"band": ..., "points": ...}`) or the declared
    value objects (`.band`/`.points`) a criterion carries (`CT-PKG-04`). The
    points are a **lookup**: the row's own value, returned untouched and never
    computed (`FR-PKG-06`'s monotone guarantee is the table's property, not this
    function's to enforce).
    """
    for row in bands:
        name = row["band"] if isinstance(row, dict) else getattr(row, "band")
        if name == band_name:
            points = row["points"] if isinstance(row, dict) else getattr(row, "points")
            return float(points)
    raise PackageError(f"the declared band set carries no band {band_name!r}.")
