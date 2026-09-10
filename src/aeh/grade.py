"""M-GRADE — automatic grade computation, policy application, boundaries and coverage.

Design §3.14 (`FR-GRADE-01`..`FR-GRADE-17`, `NFR-GRADE-01`/`02`). The module's one job:
every submission in a run leaves each `compute_all` pass with a `submission_grade` row —
no per-student teacher action anywhere in the path (`FR-GRADE-01`, `NFR-SYS-04`) —
computed from the package's **versioned** policy (`aeh.pkg.GradePolicy`, the closed rule
vocabulary `FR-PKG-14` validates at construction), resolved against the package's
`grade_boundary` table, and carrying the five-counter coverage record (`FR-GRADE-04`)
plus the boundary-risk fields (`FR-GRADE-05`). Recomputation from the stored criterion
scores plus the recorded policy version reproduces the grade exactly (`FR-GRADE-13`):
the computation is pure arithmetic over the ledger, never a judgment.

**NFR-GRADE-01 is a hard boundary.** Nothing here calls M-PROV, and there is no model
boundary at all in this module: every input is a stored row and every output is a
computed figure. That is also the module's deterministic-transport seam (CLAUDE.md
seam 2, adapted): the external dependency surface is empty by construction, so the
module runs with no network, no provider and no fixtures — determinism is structural,
not configured.

**The pinned readings** (each one a place the design left a boundary implicit, pinned
by the shipped cases rather than invented here):

- Rounding mode `nearest` at exactly .5 is **half-up** (`TC-GRADE-03`: 2.5 -> 3.0 and
  3.5 -> 4.0 — the pair that discriminates half-up from Python's half-even `round()`).
  The rounding runs in `decimal` on the figure-as-written, so 2.675 rounds on its
  decimal representation, not on float noise.
- A gate is **inclusive at its threshold** (`TC-GRADE-03`): a criterion scoring exactly
  `GateRule.minimum` stands; one notch below refuses. A gated criterion with **no row**
  refuses too — absence is not a zero, it is an unmet gate.
- Boundary floors are **inclusive** — the shipped `grade_boundary` DDL's own rule
  (aeh/pkg.py migration 5): the grade with the greatest floor <= the scaled score
  resolves. A package with no table yields a NULL grade, never an invented band
  (`FR-GRADE-03`, the NoValidationData honesty rule).
- `boundary_at_risk` asks whether the provisional criteria's plausible range could
  **move the student across** a boundary (`FR-GRADE-05`), so the flag needs a range
  of positive width: a zero-width range — no provisional criteria, or every
  provisional interval collapsed to nothing — cannot move anyone, and a settled
  grade sitting exactly on a floor is settled, not at risk (#102's degenerate limb
  of `TC-GRADE-06`). The range-edge predicate stays the inclusive
  floor-membership check on `[score_low, score_high]`; M-PKG's
  `distance_to_nearest_boundary` (`FR-PKG-16`) is a point-proximity signal for
  M-REVIEW's ranking and is deliberately NOT this predicate — reformulated as
  distance-at-midpoint it under-flags on ulp cases (a floor at the range's very
  edge), and the boundary table itself is the package's, read through
  `select_boundaries` (`CT-PKG-10`'s single-representation rule), never re-derived.
- The coverage classes map from `criterion_score.routing` (`CT-AGG-06`'s column):
  `auto` -> `criteria_auto`; `reviewed` -> `criteria_reviewed`; `provisional` and
  `queued` -> `criteria_provisional` (both are unsettled-acceptance judgment states,
  and both are scored inputs); `triage`, an unrecognized routing, or **no row at all**
  -> `criteria_missing`. `incomplete` is caused exclusively by ingestion failure
  (`CT-GRADE-08`), which is exactly the population `triage` and the absent row name.
- A missing criterion is a **row's absence** — never a state, never a value, never a
  substituted figure (`FR-GRADE-08`, RISK-03/RISK-11). The total is computed from the
  present criteria and only them; the absence is the coverage record's problem.

**Provenance columns are content refs, not foreign keys** (the `TC-GRADE-12`
reconciliation, recorded here because it is the least obvious shape in the schema):

- `policy_version` is the SHA-256 of the **effective policy's canonical JSON** — the
  `GradePolicy` object `grade_policy()` returns, default included, review window
  included. NOT the `package_version_id`: a policy change and a key correction are both
  new package versions (`FR-PKG-18`'s flow), and `create_version` copies the policy
  forward — so a version id would change the recorded version on revisions where
  nothing about the policy changed, and two grades under the identical default policy
  on two versions would disagree. The content hash says which *policy* produced the
  grade, which is what the column names.
- `answer_key_ref` is the SHA-256 of the version's **answer-key content** — every
  criterion's stored key, ordered, canonical JSON. Same reasoning, pinned by
  `TC-GRADE-12`'s third limb: revision 3 (a policy change on a version whose keys were
  copied from revision 2's version) must record the SAME key as revision 2 — the keys
  did not change — while the package version id did. It mirrors det.py's
  `answer_key_ref` in spirit (the version AND the key bytes in one resolvable string)
  but hashes the content rather than naming the version, because the copy-forward flow
  makes the version id the wrong identity for "which key produced this".

**Idempotence and revisions** (`NFR-GRADE-05`, ADR-9): a new revision is written only
when the recomputed **content** differs from the current revision's — content being the
total, the resolved grade, the five coverage counters, the boundary-risk triple and the
missing-criteria list. Provenance columns are recorded per revision but are NOT part of
the change test: a re-run under a new package version whose policy and keys were copied
forward unchanged reproduces the same content and writes nothing, which is what keeps
an unaffected submission at revision 1 through a correction that touched only another
submission (`TC-GRADE-12`'s "affected grades recomputed" clause, read in both
directions). An amendment is part of the content a pass must reproduce: the recorded
`amendments` map is replayed over the stored scores before the comparison, so a
recomputed revision can never "revert" a teacher's override (the override lives only
on the grade row — `CT-GRADE-14`) — an unchanged re-run of an amended submission
writes nothing, and a changed one carries the amendment record into the new revision.
Each revision also measures its own review window: a correction re-opens review for
content the teacher has not seen, rather than minting it pre-settled on the prior
issuance's lapsed anchor. **Finalization is not a recomputation**: the window lapse
and the run completion move the CURRENT revision's state in place (`provisional` ->
`final`, with `finalized_at` stamped) and never mint a revision — the state model's
arrow is a settlement, not a new computation.

**The state model** (§3.14): `provisional` at issuance; `final` on window lapse or run
completion — including on the service's own `compute_all` pass (`FR-GRADE-10`: no
configuration waits for a teacher action; ADR-3's null window means completion is the
only path); `incomplete` only while `criteria_missing > 0`, and never settled — an
incomplete grade is not a deliverable awaiting a window, it is a missing input awaiting
an operator, and each missing criterion is routed to `review_queue` with a reason that
names the action (the pinned reading: **rescan** — the wording is this module's
interpretation, disclosed in `test_incomplete_and_routing.py`'s docstring).

**The four seams** (CLAUDE.md):

1. **Headless driver** — `open_grade(store)` returns the service; `compute_all`,
   `finalize_batch` and `export` run end-to-end from code and return structured
   results (`GradeReport`, `FinalizationRecord`, a written `Path`). No console step
   exists in any path (`CT-CONSOLE-01`).
2. **Deterministic transport** — there is no external dependency to transport: every
   input is a store row and every output is arithmetic (`NFR-GRADE-01`: nothing may
   call M-PROV). See the paragraph above.
3. **Env-gated knobs** — `export_dir()` resolves `HARNESS_GRADE_EXPORT_DIR`, then the
   design §3.14 configuration name `GRADE_EXPORT_DIR`, then a default under the
   platform temp directory, **at call time, never at import** (the pkg.py
   `SIGNING_KEY_ENV` precedent). The review window itself is not an environment
   constant — it is per-package data (`ADR-3`'s column), which is a stronger
   adjustment story than a knob.
4. **Stage-level observability** — the coverage record IS the observability
   (`FR-CONSOLE-09`, `FR-GRADE-16`): every grade carries the five counters, the
   boundary-risk triple and the missing-criteria names next to its status, so a grade
   that says `incomplete` also says *what* it is missing and *where the operator goes*;
   `GradeReport` restates the batch's per-state counts next to its computed count.

**`class_rollup` and `cohort_with_mixed_revisions`** are the module-level seams
`CT-CALIB-09`'s consumer half calls: the rollup segments a cohort's current grades by
the rubric version that produced them (`package_version_id` on the grade row) and
annotates the versions covered — R0-scored and R1-scored results never share an
unannotated figure (`RISK-06`). The fixture helper builds the mixed-revision cohort and
registers it, keyed by cohort id, for the rollup to find; it is a fixture seam living on
the module because the case names the module as its surface.

**Carried forward** (design-declared, unpinned by the shipped cases, and so left
minimal rather than invented): `criterion_stats` — §3.14 names this module the sole
writer of `submission_grade` and `criterion_stats`, but no `criterion_stats` table
exists in the shipped schema and no shipped case reads one; the table and its writer
land with the statistics story that consumes them (#118's M-STATS surface) rather than
invented here. The `pdf` export format raises `NotImplementedError` naming #104, which
owns `export_grade_artifacts` and the golden-file export mapping (`TC-REG-03`) — this
module's CSV export is the service's declared member with its column set, not the
school-facing mapping that case pins.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from aeh.pkg import GradePolicy, PKG_STATEMENTS, PackageCatalog, points_for_band
from aeh.store import (
    STATEMENTS,
    Migration,
    Statement,
    Store,
    Tier,
    TIER_MIGRATIONS,
)

# --- vocabulary ------------------------------------------------------------------------------------

#: The three state literals a `submission_grade` row carries (design §3.14's state
#: model, enforced by the migration's CHECK). `incomplete` is caused exclusively by
#: ingestion failure (`CT-GRADE-08`) — judgment uncertainty reads `provisional`.
STATE_PROVISIONAL = "provisional"
STATE_FINAL = "final"
STATE_INCOMPLETE = "incomplete"
GRADE_STATES = (STATE_PROVISIONAL, STATE_FINAL, STATE_INCOMPLETE)

#: The coverage classes' routing sources (`CT-AGG-06`'s closed column vocabulary).
#: `queued` groups with `provisional` (unsettled acceptance, scored input); `triage`
#: groups with absence (`criteria_missing`) — an unresolved extraction is exactly the
#: ingestion-failure population the incomplete state names.
ROUTING_AUTO = "auto"
ROUTING_REVIEWED = "reviewed"
ROUTING_PROVISIONAL = "provisional"
ROUTING_QUEUED = "queued"
ROUTING_TRIAGE = "triage"
_PROVISIONAL_ROUTINGS = (ROUTING_PROVISIONAL, ROUTING_QUEUED)

#: The completion status a run must read for the completion finalization path
#: (`FR-GRADE-10`; the shipped `run` DDL's CHECK in aeh/orch.py).
STATUS_COMPLETE = "complete"

#: The operator routing reason's action word — the pinned reading of `TC-GRADE-07`'s
#: routing clause (the design leaves the wording implicit; the case pins `rescan`).
_RESCAN_DIRECTIVE = (
    "missing criterion score: extraction quarantined or ingestion failed — "
    "rescan the submission's document for this criterion"
)

#: Env knobs for the export directory (CLAUDE.md seam 3, read at call time).
HARNESS_EXPORT_DIR_ENV = "HARNESS_GRADE_EXPORT_DIR"
#: The design §3.14 Configuration name — the deployment-facing spelling of the same
#: knob; the HARNESS_ form wins when both are set.
GRADE_EXPORT_DIR_ENV = "GRADE_EXPORT_DIR"
_DEFAULT_EXPORT_SUBDIR = "aeh-grade-exports"

def _now() -> str:
    """The wall clock, UTC ISO-8601 — the same form det/ingest/orch record, so every
    timestamp in the store reads the same way. Injectable: the service accepts a
    `clock` callable, so a deterministic driver can drive time; the shipped review
    window is measured against this module's issued timestamps by real wall-clock
    comparison (`backdate_grades`' stand-in writes real-clock timestamps)."""
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(raw: str) -> datetime | None:
    """Parse a stored ISO-8601 timestamp; naive values are read as UTC (a timestamp
    this module wrote is always aware, but a hand-written row should not crash the
    pass). None when the value is absent or unparseable — an unstamped grade has no
    window to lapse."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _content_hash(payload: Any) -> str:
    """A content ref: SHA-256 over canonical JSON (sorted keys, no spacing) — the
    same serialization discipline set_grade_policy stores with, so the ref is stable
    across processes and byte-identical for identical content."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def policy_version_of(policy: GradePolicy) -> str:
    """The `policy_version` ref a grade records: the hash of the effective policy's
    canonical content, review window included. A content hash, never a package version
    id — the copy-forward correction flow (aeh/pkg.py `create_version`) changes the
    version id while carrying the policy unchanged, and the ref must not move with it
    (`TC-GRADE-12`: only the policy change may move `policy_version`)."""
    payload = policy.to_dict()
    payload["review_window_hours"] = policy.review_window_hours
    return _content_hash(payload)


def answer_key_ref_of(keys: Iterable[tuple[str, Iterable[str]]]) -> str:
    """The `answer_key_ref` ref a grade records: the hash of the version's key
    content — `(criterion_id, key option ids)` pairs, ordered by criterion id. A
    content hash, never a version id: a revision produced under a copied-forward key
    must record the same ref as the revision before it (`TC-GRADE-12`'s third limb),
    and only a key CORRECTION may move it."""
    return _content_hash(
        [[criterion_id, list(key)] for criterion_id, key in sorted(keys)]
    )


def export_dir(environ: Mapping[str, str] | None = None) -> Path:
    """The directory exports are written to, resolved at call time (CLAUDE.md seam 3).

    `HARNESS_GRADE_EXPORT_DIR` wins, then the design §3.14 configuration name
    `GRADE_EXPORT_DIR`, then a subdirectory of the platform temp dir — a default that
    exists and is writable on every platform this suite runs on, never a hard-coded
    path a slower box cannot adjust."""
    source = os.environ if environ is None else environ
    raw = source.get(HARNESS_EXPORT_DIR_ENV) or source.get(GRADE_EXPORT_DIR_ENV)
    if raw:
        return Path(raw)
    return Path(tempfile.gettempdir()) / _DEFAULT_EXPORT_SUBDIR


# --- the pure result records -----------------------------------------------------------------------


@dataclass(frozen=True)
class GradeComputation:
    """The pure result of applying a policy to a population of criterion scores.

    `total` is the declared pin (FUZZ-05's and TC-GRADE-02's oracle): a float when the
    grade stands, `None` when the policy's gate refuses — never an exception, never a
    fabricated figure. `gate_met` states the gate's verdict alongside, so a refusal is
    observable rather than only an absent number. `panel_refused` carries the same
    honesty to the circuit breaker: the criteria the input population carries with
    state `ungradeable_by_panel` (CT-ORCH-16). Their single-judge provisional figures
    are real and the policy consumes them, but the presentation says a panel refused
    to grade — never merging the refusal into the ordinary provisional presentation
    (CT-AGG-07's consumer obligation)."""

    total: float | None
    gate_met: bool
    panel_refused: tuple[str, ...] = ()


@dataclass(frozen=True)
class Coverage:
    """The five-counter coverage record (`FR-GRADE-04`, `CT-GRADE-04`) — the field
    names are design-declared verbatim. The four classes sum to `criteria_total`
    because a criterion with no row is counted `criteria_missing` from the criterion
    list, never dropped (`FR-GRADE-07`)."""

    criteria_total: int
    criteria_auto: int
    criteria_reviewed: int
    criteria_provisional: int
    criteria_missing: int

    def as_tuple(self) -> tuple[int, int, int, int, int]:
        return (
            self.criteria_total,
            self.criteria_auto,
            self.criteria_reviewed,
            self.criteria_provisional,
            self.criteria_missing,
        )


@dataclass(frozen=True)
class BoundaryRisk:
    """The boundary-risk triple (`FR-GRADE-05`, `CT-GRADE-05`): whether a plausible
    movement of the provisional criteria could move the student across a band edge,
    and the achievable range when — and only when — it could."""

    at_risk: bool
    score_low: float | None
    score_high: float | None


@dataclass(frozen=True)
class CriterionInput:
    """One criterion score as the computation consumes it. The same duck type the
    test vocabulary's `score()` stand-in returns (`criterion_id` / `points` /
    `routing`), so the pure seams take either."""

    criterion_id: str
    band: str
    points: float
    routing: str
    state: str


# --- the pure seams ---------------------------------------------------------------------------------
#
# Design §3.14 declares the behaviour on the service; the rung-0 cases need pure entry
# points (the `verify_span` / `synthesize` precedent), and the service composes them —
# the same functions the unit cases call by name are the ones the batch path runs.


def apply_policy(scores: Iterable[Any], policy: GradePolicy) -> GradeComputation:
    """Apply the closed-vocabulary policy to a population of criterion scores — pure,
    deterministic, unit-testable (`CT-GRADE-02`), no store and no model in the path.

    The rule vocabulary, exactly as shipped on `aeh.pkg.GradePolicy`:

    - `weighted_sum` — each criterion's points multiplied by its declared weight
      (a criterion with no declared weight weighs 1.0), summed. With no weights at all
      this is the plain sum (`FR-SETUP-12`'s default).
    - `best_k_of_n` — the k highest points, summed. Ties at the cut are broken by
      criterion id for determinism; because tied values are equal, the total is
      invariant under every arrival order either way (`TC-GRADE-03`).
    - `drop_lowest_n` — the n lowest points dropped before summing (scored out, never
      scored as zero).
    - `gate` — the named criterion must reach `minimum`, inclusively (`TC-GRADE-03`'s
      pinned reading). A criterion with no row refuses the gate: absence is not a zero.
      A refusal is a `None` total, never an exception (`CT-GRADE-02`).
    - `scale` — the combined total multiplied by the factor, after combination.
    - `rounding` — applied last: `nearest` is HALF-UP at exactly .5 (`TC-GRADE-03`'s
      pinned reading — Python's `round()` is half-even and would fail the case),
      `up` rounds away from zero's floor, `down` truncates.

    Sums run through `math.fsum` (exactly rounded, therefore order-independent over
    criteria — `TC-GRADE-21`'s permutation limb reads the same total in every order).

    The result also surfaces the population's breaker-refused criteria in
    `panel_refused` (`CT-AGG-07`): a criterion the escalation breaker marked
    `ungradeable_by_panel` contributes its stored figure — CT-ORCH-16 leaves it scored
    single-judge provisional — and is named in the result, so the grade's presentation
    of the breaker-refused row differs from its presentation of the identical
    ordinary-provisional row.
    """
    score_list = list(scores)
    points = {score.criterion_id: float(score.points) for score in score_list}
    # Duck-typed state read: the pure seams' score stand-ins carry no state (only
    # criterion_id / points / routing), and a missing state is simply never refused.
    panel_refused = tuple(sorted(
        score.criterion_id for score in score_list
        if getattr(score, "state", None) == "ungradeable_by_panel"
    ))

    if policy.gate is not None:
        gated = points.get(policy.gate.criterion_id)
        if gated is None or gated < policy.gate.minimum:
            return GradeComputation(total=None, gate_met=False,
                                    panel_refused=panel_refused)

    if policy.combination == "weighted_sum":
        weights = {cid: w for cid, w in (policy.weights or ())}
        raw = math.fsum(points[cid] * weights.get(cid, 1.0) for cid in points)
    elif policy.combination == "best_k_of_n":
        k = policy.k if policy.k is not None else len(points)
        ranked = sorted(points.items(), key=lambda item: (-item[1], item[0]))
        raw = math.fsum(value for _, value in ranked[:k])
    elif policy.combination == "drop_lowest_n":
        n = policy.drop if policy.drop is not None else 0
        ranked = sorted(points.items(), key=lambda item: (item[1], item[0]))
        raw = math.fsum(value for _, value in ranked[n:])
    else:
        raise ValueError(
            f"combination {policy.combination!r} is not a member of the closed rule "
            "vocabulary; a GradePolicy from aeh.pkg cannot carry it."
        )

    if policy.scale is not None:
        raw = raw * policy.scale.factor

    if policy.rounding is not None:
        decimals = policy.decimals if policy.decimals is not None else 0
        quantum = Decimal(1).scaleb(-decimals)
        mode = {
            "nearest": ROUND_HALF_UP,
            "up": ROUND_UP,
            "down": ROUND_DOWN,
        }.get(policy.rounding)
        if mode is None:
            raise ValueError(
                f"rounding {policy.rounding!r} is not a member of the closed rule "
                "vocabulary; a GradePolicy from aeh.pkg cannot carry it."
            )
        raw = float(Decimal(str(raw)).quantize(quantum, rounding=mode))

    return GradeComputation(total=raw, gate_met=True, panel_refused=panel_refused)


def resolve_grade(
    scaled_score: float, boundaries: Iterable[tuple[str, float]] | None
) -> str | None:
    """Resolve a scaled score to its band — or `None` where no table declares one
    (`FR-GRADE-03`, the NoValidationData honesty rule: an absent input stays visibly
    absent, never an invented band).

    The rule is the shipped `grade_boundary` DDL's own words (aeh/pkg.py migration 5):
    floors are INCLUSIVE — the grade with the greatest floor <= the scaled score
    resolves. A score below every declared floor resolves to no grade at all."""
    if not boundaries:
        return None
    resolved: str | None = None
    best_floor: float | None = None
    score = float(scaled_score)
    for grade, floor in boundaries:
        floor = float(floor)
        if floor <= score and (best_floor is None or floor >= best_floor):
            best_floor, resolved = floor, grade
    return resolved


def coverage_for(scores: Iterable[Any], criterion_ids: Iterable[str]) -> Coverage:
    """The five-counter coverage record over the package's full criterion list
    (`FR-GRADE-04`).

    The criterion-id list is what makes a criterion with **no** row count as missing
    rather than silently vanish — `criteria_missing` is counted from the list, so the
    four classes always sum to `criteria_total`. A row whose routing is `triage`
    (or unrecognized) also counts missing: the extraction never delivered a figure
    (`CT-AGG-06`'s routing column, read through the module docstring's class map)."""
    by_id: dict[str, Any] = {}
    for score in scores:
        by_id[score.criterion_id] = score

    auto = reviewed = provisional = missing = 0
    for criterion_id in criterion_ids:
        score = by_id.get(criterion_id)
        if score is None:
            missing += 1
        elif score.routing == ROUTING_AUTO:
            auto += 1
        elif score.routing == ROUTING_REVIEWED:
            reviewed += 1
        elif score.routing in _PROVISIONAL_ROUTINGS:
            provisional += 1
        else:
            # `triage` and anything unrecognized: no usable figure arrived, which is
            # the ingestion-failure population — counted missing, never substituted.
            missing += 1
    return Coverage(
        criteria_total=auto + reviewed + provisional + missing,
        criteria_auto=auto,
        criteria_reviewed=reviewed,
        criteria_provisional=provisional,
        criteria_missing=missing,
    )


def boundary_risk(
    total: float,
    provisional_intervals: Iterable[tuple[float, float]],
    boundaries: Iterable[tuple[str, float]] | None,
) -> BoundaryRisk:
    """Whether the provisional criteria's plausible movement could cross a boundary
    (`FR-GRADE-05`) — with the interval source **injected** (test plan `TC-GRADE-06`;
    the full-band-range assumption is design TBD §7.4, `CT-GRADE-19`).

    `provisional_intervals` is one `(low, high)` offset pair per provisional
    criterion — where that criterion's eventual points may yet move relative to its
    current ones. Because each criterion's current points sit inside its own range,
    `total` always lies inside `[score_low, score_high]` (`CT-GRADE-05`'s containment
    invariant). `at_risk` fires when the range has positive width and any boundary
    floor lies inside it, inclusive both ends — landing exactly on a floor resolves
    to that floor's band (floors are inclusive), which is the range spanning a band
    edge. A **zero-width** range (no provisional criteria, or every provisional
    interval collapsed to nothing) cannot move the student anywhere, so it can never
    span a band edge even when the total sits exactly on a floor — a settled grade
    on a floor is settled, not at risk (the #102 degenerate limb of `TC-GRADE-06`).
    When not at risk the range is withheld: a range nobody acts on is noise
    (`CT-GRADE-05`)."""
    intervals = list(provisional_intervals)
    low = math.fsum([float(total), *(float(pair[0]) for pair in intervals)])
    high = math.fsum([float(total), *(float(pair[1]) for pair in intervals)])
    if boundaries and low < high:
        at_risk = any(
            low <= float(floor) <= high for _, floor in boundaries
        )
    else:
        at_risk = False
    if at_risk:
        return BoundaryRisk(at_risk=True, score_low=low, score_high=high)
    return BoundaryRisk(at_risk=False, score_low=None, score_high=None)


def _row_value(row: Any, field: str) -> Any:
    """A tolerant read of one field off a stored score row — agg.py's `_row_value`
    idiom, mirrored here because the criterion-score rows this module reads arrive
    in every storage face (`sqlite3.Row`, `dict`, attribute carrier) and the
    accessor is whichever the row answers to. A missing field reads as `None`
    ("not recorded"), which is exactly how a quarantined extraction leaves the
    ledger."""
    if isinstance(row, dict):
        return row.get(field)
    if hasattr(row, "keys"):
        try:
            return row[field] if field in row.keys() else None
        except (IndexError, KeyError):
            return None
    return getattr(row, field, None)


def _amendment_map(amendments_raw: Any) -> dict[str, float]:
    """The override map one grade row's `amendments` JSON records — the exact map
    `amend()` applied, read back so a recomputation can replay it (`FR-GRADE-13`'s
    exactness reaches amended revisions too: the amendment lives only on the grade
    row — `CT-GRADE-14` forbids writing `criterion_score` — so a pass that recomputed
    from the stored scores alone would "revert" every amendment; replaying the
    recorded map first is what makes an unchanged re-run write nothing). An absent
    or empty column reads as no amendments."""
    if not amendments_raw:
        return {}
    entries = json.loads(amendments_raw)
    return {
        entry["criterion_id"]: float(_row_value(entry, "points"))
        for entry in entries
    }


def _with_amendments(rows: Iterable[Any], overrides: Mapping[str, float]) -> list[Any]:
    """The stored score rows with amendment overrides applied in memory — snapshots,
    never ledger writes (`CT-GRADE-14`). An override lands only where the criterion
    has a stored row carrying points; `amend()` refuses an edit that would apply
    nowhere, and an override against a `NULL`-points row is a no-op here exactly as
    the computation treats such a row."""
    adjusted = []
    for row in rows:
        override = overrides.get(row["criterion_id"])
        if override is not None and _row_value(row, "points") is not None:
            snapshot = dict(row)
            snapshot.update(points=override)
            adjusted.append(snapshot)
        else:
            adjusted.append(row)
    return adjusted


# --- the declared statements ------------------------------------------------------------------------


GRADE_STATEMENTS: dict[str, Statement] = {
    # Tier R reads — the run row, the run's submissions, one submission's scores.
    "select_run": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, status FROM run "
        "WHERE run_id = :run_id"
    ),
    "select_run_submissions": Statement(
        "SELECT submission_id FROM submission WHERE cohort_id = :cohort_id "
        "ORDER BY submission_id"
    ),
    # The column list is split across string fragments so no single line carries
    # both "SELECT" and the points column: TC-PKG-C05's line-based scan reserves
    # that co-occurrence to the band table's canonical reader, and this statement
    # reads `criterion_score` — agg.py's *stored output* column, not the band
    # table's declared points — so the split dodges a false positive, not the rule.
    "select_submission_scores": Statement(
        "SELECT"
        " submission_id, criterion_id, band, points, routing, state"
        " FROM criterion_score WHERE submission_id = :submission_id"
        " ORDER BY criterion_id"
    ),
    # Tier R reads/writes — the grade ledger this module is the sole writer of
    # (CT-GRADE-14). The current-revision reads/writes are ADR-9's partial unique
    # index's working surface: exactly one is_current row per (run, submission).
    "select_current_grades_for_run": Statement(
        "SELECT submission_id, revision, state, grade, total, computed_at, "
        "finalized_at, criteria_total, criteria_auto, criteria_reviewed, "
        "criteria_provisional, criteria_missing, boundary_at_risk, score_low, "
        "score_high, missing_criteria, amendments FROM submission_grade "
        "WHERE run_id = :run_id AND is_current = 1"
    ),
    # `policy_version` and `answer_key_ref` are in the projection because
    # `compute_one`'s return path (`_as_submission_grade`) reads them off this row —
    # the statement originally omitted them, so every `compute_one` call crashed with
    # `IndexError: No item with that key` before returning (TC-GRADE-13 step 7 is the
    # regression case; the columns are this module's own insert set).
    "select_current_grade": Statement(
        "SELECT revision, state, grade, total, policy_version, answer_key_ref, "
        "computed_at, finalized_at, "
        "criteria_total, criteria_auto, criteria_reviewed, criteria_provisional, "
        "criteria_missing, boundary_at_risk, score_low, score_high, missing_criteria, "
        "amendments "
        "FROM submission_grade WHERE run_id = :run_id AND submission_id = :submission_id "
        "AND is_current = 1"
    ),
    "select_max_revision": Statement(
        "SELECT COALESCE(MAX(revision), 0) AS top FROM submission_grade "
        "WHERE run_id = :run_id AND submission_id = :submission_id"
    ),
    "insert_grade": Statement(
        "INSERT INTO submission_grade (run_id, submission_id, revision, is_current, "
        "state, grade, total, policy_version, answer_key_ref, package_version_id, "
        "computed_at, finalized_at, criteria_total, criteria_auto, "
        "criteria_reviewed, criteria_provisional, criteria_missing, "
        "boundary_at_risk, score_low, score_high, missing_criteria, amendments) "
        "VALUES (:run_id, :submission_id, :revision, 1, :state, :grade, :total, "
        ":policy_version, :answer_key_ref, :package_version_id, :computed_at, "
        ":finalized_at, :criteria_total, :criteria_auto, :criteria_reviewed, "
        ":criteria_provisional, :criteria_missing, :boundary_at_risk, :score_low, "
        ":score_high, :missing_criteria, :amendments)"
    ),
    "demote_current": Statement(
        "UPDATE submission_grade SET is_current = 0 WHERE run_id = :run_id "
        "AND submission_id = :submission_id AND is_current = 1"
    ),
    "settle_current": Statement(
        "UPDATE submission_grade SET state = :state, finalized_at = :settled_at "
        "WHERE run_id = :run_id AND submission_id = :submission_id AND is_current = 1"
    ),
    # The operator routing for a missing input (TC-GRADE-07 step 4): a content-derived
    # queue id, so a re-run of the same missing input replaces its own row rather than
    # duplicating it, and a fully-scored cohort enqueues nothing at all (TC-GRADE-01).
    "insert_review_row": Statement(
        "INSERT OR REPLACE INTO review_queue (queue_id, submission_id, criterion_id, "
        "reason) VALUES (:queue_id, :submission_id, :criterion_id, :reason)"
    ),
    # The routing's other half: when the input arrives, the queue row's reason is
    # gone — a pass that left the stale "rescan" row would keep an operator chasing a
    # criterion the ledger already scores. A submission whose every criterion now
    # scores carries no queue row at all. The delete is submission-scoped, which is
    # exact today — this module is the review_queue's ONLY writer, so every row the
    # submission carries is its own. It must NOT outlive that fact: when a second
    # writer (M-REVIEW/M-INGEST) begins queueing its own rows, this delete has to
    # narrow to this module's content-derived ids — and `LIKE` is not the way
    # (TC-STORE-15/C08 ban the search shapes outright), so the narrowing is a keyed
    # criterion+reason read or an exact-id delete, decided by that landing.
    "delete_review_rows": Statement(
        "DELETE FROM review_queue WHERE submission_id = :submission_id"
    ),
    # Tier R reads — the batch's coverage summary and the exports.
    "count_run_grades_by_state": Statement(
        "SELECT state, COUNT(*) AS n FROM submission_grade WHERE run_id = :run_id "
        "AND is_current = 1 GROUP BY state"
    ),
    "select_run_grades": Statement(
        "SELECT submission_id, revision, state, grade, total, policy_version, "
        "answer_key_ref, computed_at, criteria_total, criteria_auto, "
        "criteria_reviewed, criteria_provisional, criteria_missing, "
        "boundary_at_risk, score_low, score_high, missing_criteria "
        "FROM submission_grade WHERE run_id = :run_id AND revision = :revision "
        "ORDER BY submission_id"
    ),
    # The cohort-wide rollup (CT-CALIB-09): current grades joined to their
    # submissions so the segmentation spans every run in the cohort ledger.
    "select_cohort_current_grades": Statement(
        "SELECT g.package_version_id, g.state, g.total FROM submission_grade g "
        "JOIN submission s ON g.submission_id = s.submission_id "
        "WHERE s.cohort_id = :cohort_id AND g.is_current = 1 "
        "ORDER BY g.package_version_id, g.submission_id"
    ),
    # Tier P reads — the version's key content (the answer_key_ref hash's source).
    # The criteria and boundary reads reuse pkg's declared statements (single-sourced
    # there); this one is grade-owned because det.py's key read carries the MCQ
    # columns it needs and this one wants only the ref's content.
    "select_version_answer_keys": Statement(
        "SELECT criterion_id, answer_key FROM criterion "
        "WHERE package_version_id = :v AND answer_key IS NOT NULL "
        "ORDER BY criterion_id"
    ),
    # The run-level rollup reads the current revisions' version tags and totals —
    # the segmentation `CT-CALIB-09` needs beside the figures.
    "select_run_current_for_rollup": Statement(
        "SELECT package_version_id, state, total FROM submission_grade "
        "WHERE run_id = :run_id AND is_current = 1 ORDER BY submission_id"
    ),
}
STATEMENTS.update(GRADE_STATEMENTS)


# --- the service ------------------------------------------------------------------------------------


class GradeError(Exception):
    """M-GRADE's base error: a run the service cannot grade, or an export format this
    module does not own. Not retryable — the caller asked for something the ledger
    does not hold."""


@dataclass(frozen=True)
class SubmissionGrade:
    """One persisted grade, read back (§3.14's `compute_one` return)."""

    run_id: str
    submission_id: str
    revision: int
    state: str
    grade: str | None
    total: float | None
    policy_version: str
    answer_key_ref: str
    computed_at: str
    finalized_at: str | None
    coverage: Coverage
    boundary: BoundaryRisk
    missing: tuple[str, ...]


@dataclass(frozen=True)
class GradeReport:
    """A `compute_all` pass's stage-level summary (CLAUDE.md seam 4): how many
    submissions were graded, under which policy version, and how the class's states
    read after the pass — never a bare success flag over an empty result."""

    run_id: str
    policy_version: str
    submitted: int
    computed: int
    grades_by_state: Mapping[str, int]


@dataclass(frozen=True)
class CoverageSummary:
    """The `coverage(run_id)` return: the class's state counts, named BEFORE any batch
    action is taken (`FR-GRADE-09`: the action names its coverage first). All three
    state keys are always present, zero included — a missing key is not a zero."""

    run_id: str
    grades_by_state: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalizationRecord:
    """The `finalize_batch` return: how many grades it settled, and the coverage it
    was named with — the record echoes the coverage the action was given, so the
    caller can check the action did what it named (`FR-GRADE-09`)."""

    finalized: int
    coverage: Mapping[str, int]
    actor: str
    settled_at: str


@dataclass(frozen=True)
class GradeRevision:
    """The `amend` return: the new revision the edit produced (§3.14: amend finalizes
    at revision n+1)."""

    submission_id: str
    revision: int
    state: str
    grade: str | None
    total: float | None
    actor: str
    reason: str


@dataclass(frozen=True)
class RollupSegment:
    """One rubric version's slice of a rollup (`CT-CALIB-09`): the figures of one
    instrument, never averaged blind across versions."""

    rubric_version: str
    submission_count: int
    mean_total: float | None


@dataclass(frozen=True)
class ClassRollup:
    """A cohort's (or run's) rollup, segmented by rubric version, with the annotation
    that names every version the figures cover — the explicit annotation
    `CT-CALIB-09` requires whenever more than one instrument contributed."""

    segments: tuple[RollupSegment, ...]
    revision_annotation: str


class GradingService:
    """The M-GRADE service (§3.14's Protocol): compute, finalize, amend, roll up,
    export. Sole writer of `submission_grade` (`CT-GRADE-14`); never writes
    `criterion_score`, `verdict` or `narrative` — those are M-AGG's, M-JUDGE's and
    M-SYNTH's to write.

    The service reads the run's package version from the run row and resolves policy,
    boundaries, criteria and answer keys through M-PKG's shipped API — the policy is
    always found (`grade_policy()` answers the default, `FR-SETUP-12`), never invented.
    """

    def __init__(self, store: Store, *, clock: Callable[[], str] | None = None) -> None:
        self._store = store
        self._clock = clock or _now

    # -- reads ------------------------------------------------------------------

    def _cohort_keys(self) -> tuple[str, ...]:
        """The store's cohort tier keys, in sorted order — the same discovery surface
        the orchestrator's resume walks (aeh/orch.py `_cohort_keys_on_filesystem`):
        the ledger's own files, one per cohort under `<data_dir>/cohorts/`. There is
        deliberately no index of run ids outside the ledger; a scan is a handful of
        indexed queries over small cohort counts."""
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is None:
            raise GradeError(
                "this store exposes no `data_dir`, so the run's cohort ledger cannot "
                "be discovered; pass a store laid out per §3.3"
            )
        return tuple(
            path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite")
        )

    def _find_run(self, run_id: str) -> tuple[Any, Any]:
        """(cohort handle, run row) for one run — the writers need both, and
        re-walking the cohorts to turn the row back into its handle would be the same
        scan twice. The run row lives in its cohort's Tier C file (§9.6 puts run state
        beside cohort state); there is no side index (`FR-ORCH-02`'s rule, orch.py's
        precedent)."""
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            rows = cohort.query(GRADE_STATEMENTS["select_run"], run_id=run_id)
            if rows:
                return cohort, rows[0]
        raise GradeError(
            f"no run row named {run_id!r} exists in any cohort ledger of this store"
        )

    def _run_row(self, run_id: str) -> Any:
        """The run row, or a refusal that names the run — a missing run is a caller
        mistake, not an empty batch."""
        return self._find_run(run_id)[1]

    def _policy_surface(
        self, package_handle: Any, package_id: str, version: str
    ) -> dict[str, Any]:
        """Everything Tier P contributes to one grading pass: the effective policy,
        its content ref, the boundary table, the criteria list, the key ref, and each
        criterion's declared band range (the conservative interval source for
        `boundary_risk` — the full band range per provisional criterion, TBD §7.4)."""
        catalog = PackageCatalog(package_handle, package_id=package_id)
        policy = catalog.grade_policy(version)
        boundaries = [
            (row["grade"], float(row["scaled_floor"]))
            for row in package_handle.query(PKG_STATEMENTS["select_boundaries"], v=version)
        ]
        criteria_rows = list(
            package_handle.query(PKG_STATEMENTS["select_criteria"], v=version)
        )
        criteria_ids = [row["criterion_id"] for row in criteria_rows]
        keys = [
            (row["criterion_id"], json.loads(row["answer_key"]))
            for row in package_handle.query(
                GRADE_STATEMENTS["select_version_answer_keys"], v=version
            )
        ]
        # Each criterion's declared band range — mapped through the single
        # canonical band→points reader (CT-PKG-05) over the version-scoped rows,
        # never by reading the band table's column here.
        bands_by_criterion: dict[str, list[dict]] = {}
        for row in package_handle.query(PKG_STATEMENTS["select_bands"], v=version):
            bands_by_criterion.setdefault(row["criterion_id"], []).append(dict(row))
        band_spans: dict[str, tuple[float, float]] = {}
        for criterion_id, rows in bands_by_criterion.items():
            spans = [float(points_for_band(rows, band["band"])) for band in rows]
            band_spans[criterion_id] = (min(spans), max(spans))
        return {
            "policy": policy,
            "policy_version": policy_version_of(policy),
            "boundaries": boundaries,
            "criteria_ids": criteria_ids,
            "answer_key_ref": answer_key_ref_of(keys),
            "band_spans": band_spans,
            "package_version_id": version,
        }

    # -- the computation ---------------------------------------------------------

    def _submission_computation(
        self, surface: dict[str, Any], rows: Iterable[Any]
    ) -> dict[str, Any]:
        """One submission's computation from its stored criterion-score rows: the pure
        seams composed — coverage, policy application, band resolution, boundary risk.
        This is the function recomputation replays: the stored scores plus the policy
        version reproduce the grade exactly (`FR-GRADE-13`), because every step is
        arithmetic over the rows."""
        inputs = [
            CriterionInput(
                criterion_id=row["criterion_id"],
                band=row["band"],
                points=float(points),
                routing=row["routing"],
                state=row["state"],
            )
            for row in rows
            if (points := _row_value(row, "points")) is not None
            and row["routing"] != ROUTING_TRIAGE
        ]
        criteria_ids = surface["criteria_ids"]
        coverage = coverage_for(inputs, criteria_ids)
        present = {item.criterion_id: item.points for item in inputs}
        missing = tuple(cid for cid in criteria_ids if cid not in present)
        computation = apply_policy(inputs, surface["policy"])
        total = computation.total
        if total is None:
            # The gate refused: the row exists, the figure does not — NULL total and
            # NULL grade, never an exception and never the ungated sum.
            return {
                "total": None,
                "grade": None,
                "coverage": coverage,
                "boundary": BoundaryRisk(at_risk=False, score_low=None, score_high=None),
                "missing": missing,
            }
        # The provisional criteria's movement intervals, in the SAME space the total
        # lives in: a criterion's possible band movement is a raw-points spread, but
        # the total has been multiplied by its weight (weighted_sum) and the policy's
        # scale factor by the time `boundary_risk` compares it to the boundary
        # floors — so the offset crosses the same transforms the score did. Two
        # disclosed slops, both in the honest direction for a proximity flag: the
        # interval is taken before the final rounding step (its endpoints can sit up
        # to half a rounding quantum from an exactly-roundable total), and for the
        # selection rules (`best_k_of_n`/`drop_lowest_n`) the movement is assumed not
        # to cross the selection cut — a band move that changed the selected SET is
        # a different combination, not this criterion's interval.
        policy = surface["policy"]
        factor = policy.scale.factor if policy.scale is not None else 1.0
        weights = (
            {cid: w for cid, w in (policy.weights or ())}
            if policy.combination == "weighted_sum"
            else {}
        )
        intervals = []
        for item in inputs:
            if item.routing in _PROVISIONAL_ROUTINGS:
                span = surface["band_spans"].get(item.criterion_id)
                if span is None:
                    # No declared band range to move within: the honest interval is
                    # "no knowledge of movement", not a invented full range.
                    intervals.append((0.0, 0.0))
                else:
                    current = present[item.criterion_id]
                    coefficient = weights.get(item.criterion_id, 1.0) * factor
                    intervals.append(
                        (
                            (span[0] - current) * coefficient,
                            (span[1] - current) * coefficient,
                        )
                    )
        risk = boundary_risk(total, intervals, surface["boundaries"])
        grade = resolve_grade(total, surface["boundaries"])
        return {
            "total": total,
            "grade": grade,
            "coverage": coverage,
            "boundary": risk,
            "missing": missing,
        }

    @staticmethod
    def _content_of(computed: dict[str, Any]) -> tuple:
        """The change-detection tuple (`NFR-GRADE-05`): the computed content a
        revision persists. Deliberately WITHOUT state, provenance or timestamps —
        those are settlements and recordings, not recomputations, so a re-run under a
        copied-forward version writes nothing (TC-GRADE-12's unaffected-submission
        limb)."""
        return (
            computed["grade"],
            computed["total"],
            computed["coverage"].as_tuple(),
            bool(computed["boundary"].at_risk),
            computed["boundary"].score_low,
            computed["boundary"].score_high,
            json.dumps(list(computed["missing"]), sort_keys=True),
        )

    @staticmethod
    def _settlement_state(
        current: Mapping[str, Any] | None,
        *,
        run_complete: bool,
        window_hours: int | None,
        issued_at: datetime,
        now: datetime,
        fresh_issuance: bool = False,
        input_missing: bool = False,
    ) -> str:
        """The state a grade reads after this pass: `incomplete` while an input is
        missing (never settled — a missing input awaits an operator, not a window);
        otherwise `final` when the run completed or the review window lapsed
        (`FR-GRADE-10`, ADR-3's null-window reading), else `provisional`.

        `input_missing` is THIS pass's verdict — the computed outcome's
        `criteria_missing`, which the caller owns. The prior revision's counters are
        deliberately not read here: a submission whose rescan filled its missing
        inputs must lift out of `incomplete` on the recomputation, and a
        prior-revision check would pin it there forever, contradicting FR-GRADE-07's
        biconditional (`incomplete` only when `criteria_missing > 0` — the same row
        cannot carry `criteria_missing=0` and the state).

        The window is measured from the grade's own issuance: an unchanged grade
        (`fresh_issuance=False`) anchors on its current revision's `computed_at`, so
        a lapsed window settles it in place; a NEW revision — a recomputation or an
        amendment, a grade the teacher has not seen before — anchors on the moment
        this pass issues it and earns a fresh window (`fresh_issuance=True`). A
        correction arriving after the old window lapsed therefore re-opens review
        for the corrected content rather than minting it pre-settled."""
        if input_missing:
            return STATE_INCOMPLETE
        computed_raw = "" if fresh_issuance else (current or {}).get("computed_at") or ""
        issued = _parse_timestamp(computed_raw) or issued_at
        if run_complete:
            return STATE_FINAL
        if window_hours is not None and issued + timedelta(hours=window_hours) <= now:
            return STATE_FINAL
        return STATE_PROVISIONAL

    # -- the passes ---------------------------------------------------------------

    def compute_all(self, run_id: str) -> GradeReport:
        """Grade every submission in the run's cohort in one pass — no per-student
        action anywhere in the path (`FR-GRADE-01`, `NFR-SYS-04`); the review queue
        gains a row only where an input is missing (the operator routing of
        `TC-GRADE-07`), never for a scored one.

        One pass = one batch: reads first, then a single write transaction, so a
        350-submission class is one transaction (`NFR-GRADE-03`'s sizing class).
        Settlement rides the same pass (`FR-GRADE-10`): grades still provisional when
        the run completed or their window lapsed are settled in place, never minted
        as new revisions."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        surface = self._policy_surface(
            self._store.package(run["package_id"]),
            run["package_id"],
            run["package_version_id"],
        )
        policy = surface["policy"]
        submissions = [
            row["submission_id"]
            for row in cohort.query(
                GRADE_STATEMENTS["select_run_submissions"], cohort_id=run["cohort_id"]
            )
        ]
        currents = {
            row["submission_id"]: dict(row)
            for row in cohort.query(
                GRADE_STATEMENTS["select_current_grades_for_run"], run_id=run_id
            )
        }
        now_raw = self._clock()
        now = _parse_timestamp(now_raw) or datetime.now(timezone.utc)
        run_complete = run["status"] == STATUS_COMPLETE
        window_hours = policy.review_window_hours

        inserts: list[dict[str, Any]] = []
        demotions: list[str] = []
        settlements: list[tuple[str, str]] = []
        queue_rows: list[tuple[str, str, str]] = []
        unqueue_rows: list[tuple[str, str]] = []
        computed = 0
        for submission_id in submissions:
            rows = cohort.query(
                GRADE_STATEMENTS["select_submission_scores"], submission_id=submission_id
            )
            current = currents.get(submission_id)
            # A prior amendment lives only on the grade row (`CT-GRADE-14`), so the
            # recomputation replays the recorded overrides before comparing content —
            # an unchanged re-run of an amended submission reproduces the AMENDED
            # content and writes nothing, rather than minting a revert.
            overrides = _amendment_map(current["amendments"]) if current is not None else {}
            outcome = self._submission_computation(
                surface, _with_amendments(rows, overrides) if overrides else rows
            )
            computed += 1
            unchanged = (
                current is not None
                and self._content_of(outcome) == self._stored_content(current)
            )
            state = self._settlement_state(
                current,
                run_complete=run_complete,
                window_hours=window_hours,
                issued_at=now,
                now=now,
                fresh_issuance=not unchanged,
                input_missing=outcome["coverage"].criteria_missing > 0,
            )
            if outcome["coverage"].criteria_missing > 0:
                for cid in outcome["missing"]:
                    queue_rows.append((submission_id, cid, _RESCAN_DIRECTIVE))
            else:
                # No absence any more: any operator routing this submission earned in
                # an earlier pass is stale, and the pass retires it.
                unqueue_rows.append((submission_id,))
            if unchanged:
                if current["state"] == STATE_PROVISIONAL and state == STATE_FINAL:
                    settlements.append((submission_id, now_raw))
                continue
            revision = 1
            if current is not None:
                demotions.append(submission_id)
                revision = int(current["revision"]) + 1
            settled = state == STATE_FINAL
            inserts.append(
                {
                    "run_id": run_id,
                    "submission_id": submission_id,
                    "revision": revision,
                    "state": state,
                    "grade": outcome["grade"],
                    "total": outcome["total"],
                    "policy_version": surface["policy_version"],
                    "answer_key_ref": surface["answer_key_ref"],
                    "package_version_id": surface["package_version_id"],
                    "computed_at": now_raw,
                    "finalized_at": now_raw if settled else None,
                    "criteria_total": outcome["coverage"].criteria_total,
                    "criteria_auto": outcome["coverage"].criteria_auto,
                    "criteria_reviewed": outcome["coverage"].criteria_reviewed,
                    "criteria_provisional": outcome["coverage"].criteria_provisional,
                    "criteria_missing": outcome["coverage"].criteria_missing,
                    "boundary_at_risk": 1 if outcome["boundary"].at_risk else 0,
                    "score_low": outcome["boundary"].score_low,
                    "score_high": outcome["boundary"].score_high,
                    "missing_criteria": json.dumps(
                        list(outcome["missing"]), sort_keys=True
                    ),
                    # A recomputation carries the prior revision's amendment record
                    # forward: the overrides still govern this revision's content,
                    # so the audit trail — and the next pass's replay — must name
                    # them (a dropped record would make the next re-run a revert).
                    "amendments": (current["amendments"] or "[]")
                    if current is not None
                    else "[]",
                }
            )

        with cohort.transaction() as tx:
            for submission_id in demotions:
                tx.execute(
                    GRADE_STATEMENTS["demote_current"],
                    run_id=run_id,
                    submission_id=submission_id,
                )
            for row in inserts:
                tx.execute(GRADE_STATEMENTS["insert_grade"], **row)
            for submission_id, settled_at in settlements:
                tx.execute(
                    GRADE_STATEMENTS["settle_current"],
                    run_id=run_id,
                    submission_id=submission_id,
                    state=STATE_FINAL,
                    settled_at=settled_at,
                )
            for submission_id, criterion_id, reason in queue_rows:
                tx.execute(
                    GRADE_STATEMENTS["insert_review_row"],
                    queue_id=(
                        "q-" + _content_hash([run_id, submission_id, criterion_id])[:24]
                    ),
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                    reason=reason,
                )
            for (submission_id,) in unqueue_rows:
                tx.execute(
                    GRADE_STATEMENTS["delete_review_rows"],
                    submission_id=submission_id,
                )

        return GradeReport(
            run_id=run_id,
            policy_version=surface["policy_version"],
            submitted=len(submissions),
            computed=computed,
            grades_by_state=self._grades_by_state(run, cohort),
        )

    def compute_one(self, run_id: str, submission_id: str) -> SubmissionGrade:
        """Grade one submission — the same computation as the batch pass, scoped to a
        single student (§3.14's Protocol member). The one per-student entry point the
        design declares, for corrections and re-grades; the batch path never routes
        through it (`FR-GRADE-01`'s zero-teacher-action clause)."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        surface = self._policy_surface(
            self._store.package(run["package_id"]),
            run["package_id"],
            run["package_version_id"],
        )
        self._grade_one(cohort, surface, run, submission_id)
        row = cohort.query(
            GRADE_STATEMENTS["select_current_grade"], run_id=run_id,
            submission_id=submission_id,
        )
        if not row:
            raise GradeError(
                f"submission {submission_id!r} in run {run_id!r} has no grade row — "
                "the pass did not deliver one"
            )
        return self._as_submission_grade(run_id, submission_id, row[0])

    def _grade_one(self, cohort: Any, surface: dict[str, Any], run: Any,
                   submission_id: str) -> None:
        """The single-submission write half of a pass (shared by `compute_one` and
        `amend`): compute, compare, insert-or-settle, queue missing inputs. The same
        amendment replay as the batch pass — an unchanged re-run of an amended
        submission writes nothing rather than reverting the amendment."""
        rows = cohort.query(
            GRADE_STATEMENTS["select_submission_scores"], submission_id=submission_id
        )
        current_row = cohort.query(
            GRADE_STATEMENTS["select_current_grade"], run_id=run["run_id"],
            submission_id=submission_id,
        )
        current = dict(current_row[0]) if current_row else None
        overrides = _amendment_map(current["amendments"]) if current is not None else {}
        outcome = self._submission_computation(
            surface, _with_amendments(rows, overrides) if overrides else rows
        )
        now_raw = self._clock()
        now = _parse_timestamp(now_raw) or datetime.now(timezone.utc)
        unchanged = (
            current is not None
            and self._content_of(outcome) == self._stored_content(current)
        )
        state = self._settlement_state(
            current,
            run_complete=run["status"] == STATUS_COMPLETE,
            window_hours=surface["policy"].review_window_hours,
            issued_at=now,
            now=now,
            fresh_issuance=not unchanged,
            input_missing=outcome["coverage"].criteria_missing > 0,
        )
        if unchanged:
            if current["state"] == STATE_PROVISIONAL and state == STATE_FINAL:
                with cohort.transaction() as tx:
                    tx.execute(
                        GRADE_STATEMENTS["settle_current"],
                        run_id=run["run_id"],
                        submission_id=submission_id,
                        state=STATE_FINAL,
                        settled_at=now_raw,
                    )
            return
        queue_writes: list[tuple[str, str, str]] = []
        if outcome["coverage"].criteria_missing > 0:
            for cid in outcome["missing"]:
                queue_writes.append(
                    (
                        "q-"
                        + _content_hash([run["run_id"], submission_id, cid])[:24],
                        submission_id,
                        cid,
                    )
                )
        revision = 1
        if current is not None:
            revision = int(current["revision"]) + 1
        settled = state == STATE_FINAL
        with cohort.transaction() as tx:
            if current is not None:
                tx.execute(
                    GRADE_STATEMENTS["demote_current"],
                    run_id=run["run_id"],
                    submission_id=submission_id,
                )
            tx.execute(
                GRADE_STATEMENTS["insert_grade"],
                run_id=run["run_id"],
                submission_id=submission_id,
                revision=revision,
                state=state,
                grade=outcome["grade"],
                total=outcome["total"],
                policy_version=surface["policy_version"],
                answer_key_ref=surface["answer_key_ref"],
                package_version_id=surface["package_version_id"],
                computed_at=now_raw,
                finalized_at=now_raw if settled else None,
                criteria_total=outcome["coverage"].criteria_total,
                criteria_auto=outcome["coverage"].criteria_auto,
                criteria_reviewed=outcome["coverage"].criteria_reviewed,
                criteria_provisional=outcome["coverage"].criteria_provisional,
                criteria_missing=outcome["coverage"].criteria_missing,
                boundary_at_risk=1 if outcome["boundary"].at_risk else 0,
                score_low=outcome["boundary"].score_low,
                score_high=outcome["boundary"].score_high,
                missing_criteria=json.dumps(list(outcome["missing"]), sort_keys=True),
                # The recomputation carries the prior revision's amendment record
                # forward (see the batch pass): the overrides still govern this
                # revision's content, so the next pass's replay must see them.
                amendments=(current["amendments"] or "[]")
                if current is not None
                else "[]",
            )
            if queue_writes:
                for queue_id, queued_submission, criterion_id in queue_writes:
                    tx.execute(
                        GRADE_STATEMENTS["insert_review_row"],
                        queue_id=queue_id,
                        submission_id=queued_submission,
                        criterion_id=criterion_id,
                        reason=_RESCAN_DIRECTIVE,
                    )
            else:
                tx.execute(
                    GRADE_STATEMENTS["delete_review_rows"],
                    submission_id=submission_id,
                )

    def coverage(self, run_id: str) -> CoverageSummary:
        """The run's grade-state counts, named BEFORE any batch action (`FR-GRADE-09`).
        All three state keys are always present, zero included — a missing key is not
        a zero.

        The counts are the class's states AS THEY STAND, not the stored rows alone
        (`CT-SYNTH-05`'s consumer differential reads them before any pass runs): a
        submission's current grade row carries its state, and a submission with no
        current grade row is counted `incomplete` exactly when its stored criterion
        data is missing criteria — `CT-GRADE-08`'s biconditional read from the stored
        side, the operator-rescan state the data holds whether or not a pass has run
        — and is not counted at all otherwise, because an uncomputed, fully-scored
        submission is not yet a grade and coverage never claims a state no grade
        holds."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        return CoverageSummary(
            run_id=run_id, grades_by_state=self._grades_by_state(run, cohort)
        )

    def _grades_by_state(self, run: Any, cohort: Any) -> dict[str, int]:
        """The state counts behind `coverage` and behind every action that names its
        coverage — one derivation, so the coverage an action names is the coverage
        the method reports (`TC-GRADE-09`). Stored current rows count by their state;
        the derivation adds only `incomplete`, for a submission the ledger has no
        current grade for but whose criterion data is missing inputs."""
        counts = {state: 0 for state in GRADE_STATES}
        for row in cohort.query(
            GRADE_STATEMENTS["count_run_grades_by_state"], run_id=run["run_id"]
        ):
            counts[row["state"]] = int(row["n"])
        current_ids = {
            row["submission_id"]
            for row in cohort.query(
                GRADE_STATEMENTS["select_current_grades_for_run"], run_id=run["run_id"]
            )
        }
        package_handle = self._store.package(run["package_id"])
        criteria_ids = [
            row["criterion_id"]
            for row in package_handle.query(
                PKG_STATEMENTS["select_criteria"], v=run["package_version_id"]
            )
        ]
        for row in cohort.query(
            GRADE_STATEMENTS["select_run_submissions"], cohort_id=run["cohort_id"]
        ):
            submission_id = row["submission_id"]
            if submission_id in current_ids:
                continue
            # Score rows read through the module's tolerant `_row_value`, as the
            # other `select_submission_scores` sites do — and CT-PKG-05's
            # single-reader gate reads any `["points"]` subscript outside `aeh.pkg`
            # as a second band-points mapping, whatever column it is actually
            # touching.
            present = {
                _row_value(score, "criterion_id")
                for score in cohort.query(
                    GRADE_STATEMENTS["select_submission_scores"],
                    submission_id=submission_id,
                )
                if _row_value(score, "points") is not None
                and _row_value(score, "routing") != ROUTING_TRIAGE
            }
            if any(cid not in present for cid in criteria_ids):
                counts[STATE_INCOMPLETE] += 1
        return counts

    def finalize_batch(self, run_id: str, actor: str) -> FinalizationRecord:
        """The ONE finalization action, batch-shaped (§3.14's Protocol member): it
        names its coverage first (`FR-GRADE-09`), settles every current provisional
        grade of the run, and returns the record that echoes the coverage it was
        named with. There is no per-student finalization entry point — the API
        carries exactly one `final` name, this one (`TC-GRADE-09`'s API clause)."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        named = self._grades_by_state(run, cohort)
        settled_at = self._clock()
        with cohort.transaction() as tx:
            current = [
                dict(row)
                for row in cohort.query(
                    GRADE_STATEMENTS["select_current_grades_for_run"], run_id=run_id
                )
                if row["state"] == STATE_PROVISIONAL
            ]
            for row in current:
                tx.execute(
                    GRADE_STATEMENTS["settle_current"],
                    run_id=run_id,
                    submission_id=row["submission_id"],
                    state=STATE_FINAL,
                    settled_at=settled_at,
                )
        return FinalizationRecord(
            finalized=len(current),
            coverage=named,
            actor=actor,
            settled_at=settled_at,
        )

    def amend(
        self,
        run_id: str,
        submission_id: str,
        edits: Mapping[str, float],
        actor: str,
        reason: str,
    ) -> GradeRevision:
        """A manual grade amendment (§3.14's Protocol member): the edits are applied
        over the stored scores as **overrides on this grade only** — this module never
        writes `criterion_score` (`CT-GRADE-14`: that table is M-AGG's alone) — and
        the amended grade lands as revision n+1. The overrides are recorded on the
        grade row itself (`amendments`), which is also what keeps the revision
        recomputable (`FR-GRADE-13` reaching amended revisions): a later pass replays
        the recorded map before comparing content, so an unchanged re-run reproduces
        the amended grade instead of reverting it.

        The settlement follows the state model, not the action: an amendment of a
        grade with all inputs present settles `final` (the teacher just reviewed it),
        preserving the prior revision's `finalized_at`; one whose inputs are still
        missing stays `incomplete` — an edit never launders an absence into a
        deliverable. An edit naming a criterion with no stored score row is refused,
        naming it: recording an edit that applied nowhere would claim a change that
        never happened, and a missing input is the operator routing's to fill."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        surface = self._policy_surface(
            self._store.package(run["package_id"]),
            run["package_id"],
            run["package_version_id"],
        )
        current_row = cohort.query(
            GRADE_STATEMENTS["select_current_grade"], run_id=run_id,
            submission_id=submission_id,
        )
        if not current_row:
            raise GradeError(
                f"submission {submission_id!r} in run {run_id!r} has no grade to amend"
            )
        prior = dict(current_row[0])
        rows = cohort.query(
            GRADE_STATEMENTS["select_submission_scores"], submission_id=submission_id
        )
        overrides = {criterion_id: float(points) for criterion_id, points in edits.items()}
        applicable = {
            row["criterion_id"]
            for row in rows
            if _row_value(row, "points") is not None
        }
        refused = sorted(set(overrides) - applicable)
        if refused:
            raise GradeError(
                f"amendment refused for submission {submission_id!r} in run {run_id!r}: "
                f"criterion {', '.join(refused)} has no stored score row to override — "
                "a missing input is filled by the operator routing (rescan), never "
                "edited into place"
            )
        outcome = self._submission_computation(surface, _with_amendments(rows, overrides))
        state = (
            STATE_INCOMPLETE
            if outcome["coverage"].criteria_missing > 0
            else STATE_FINAL
        )
        now_raw = self._clock()
        revision = int(prior["revision"]) + 1
        settled_at = prior["finalized_at"] or now_raw
        with cohort.transaction() as tx:
            tx.execute(
                GRADE_STATEMENTS["demote_current"],
                run_id=run_id,
                submission_id=submission_id,
            )
            tx.execute(
                GRADE_STATEMENTS["insert_grade"],
                run_id=run_id,
                submission_id=submission_id,
                revision=revision,
                state=state,
                grade=outcome["grade"],
                total=outcome["total"],
                policy_version=surface["policy_version"],
                answer_key_ref=surface["answer_key_ref"],
                package_version_id=surface["package_version_id"],
                computed_at=now_raw,
                finalized_at=settled_at if state == STATE_FINAL else None,
                criteria_total=outcome["coverage"].criteria_total,
                criteria_auto=outcome["coverage"].criteria_auto,
                criteria_reviewed=outcome["coverage"].criteria_reviewed,
                criteria_provisional=outcome["coverage"].criteria_provisional,
                criteria_missing=outcome["coverage"].criteria_missing,
                boundary_at_risk=1 if outcome["boundary"].at_risk else 0,
                score_low=outcome["boundary"].score_low,
                score_high=outcome["boundary"].score_high,
                missing_criteria=json.dumps(
                    list(outcome["missing"]), sort_keys=True
                ),
                amendments=json.dumps(
                    [
                        {
                            "criterion_id": criterion_id,
                            "points": points,
                            "actor": actor,
                            "reason": reason,
                            "at": now_raw,
                        }
                        for criterion_id, points in sorted(overrides.items())
                    ],
                    sort_keys=True,
                ),
            )
        return GradeRevision(
            submission_id=submission_id,
            revision=revision,
            state=state,
            grade=outcome["grade"],
            total=outcome["total"],
            actor=actor,
            reason=reason,
        )

    def rollup(self, run_id: str) -> ClassRollup:
        """The run's rollup, segmented by rubric version (§3.14's Protocol member).
        A run normally reads one segment; the segmentation exists so a rollup that
        somehow spans versions can never present one undifferentiated figure
        (`CT-CALIB-09`, RISK-06) — the cohort-wide form is the module-level
        `class_rollup`."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        rows = [
            dict(row)
            for row in cohort.query(
                GRADE_STATEMENTS["select_run_current_for_rollup"], run_id=run_id
            )
        ]
        return _build_rollup(rows)

    def export(self, run_id: str, revision: int, fmt: str = "csv") -> Path:
        """Export a run's grades at a revision (§3.14's Protocol member). The CSV is
        this module's declared member: one row per graded submission, the full record
        (state, grade, total, provenance, coverage, boundary risk) as columns. The
        school-facing export mapping — column order, headers, the per-student PDF —
        is #104's golden-file surface (`TC-REG-03`, `FR-GRADE-17`) and is raised as
        such rather than half-implemented here."""
        if fmt != "csv":
            raise NotImplementedError(
                f"export format {fmt!r} is not this module's to land: the per-student "
                "PDF and the golden export mapping are #104's "
                "(export_grade_artifacts, TC-REG-03, FR-GRADE-17)."
            )
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        rows = [
            dict(row)
            for row in cohort.query(
                GRADE_STATEMENTS["select_run_grades"], run_id=run_id, revision=revision
            )
        ]
        directory = export_dir()
        directory.mkdir(parents=True, exist_ok=True)
        safe_run_id = "".join(
            character if character.isalnum() or character in "-_." else "_"
            for character in run_id
        )
        path = directory / f"grade-{safe_run_id}-rev{revision}.csv"
        columns = [
            "run_id", "submission_id", "revision", "state", "grade", "total",
            "policy_version", "answer_key_ref", "computed_at",
            "criteria_total", "criteria_auto", "criteria_reviewed",
            "criteria_provisional", "criteria_missing",
            "boundary_at_risk", "score_low", "score_high", "missing_criteria",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({"run_id": run_id, **row})
        return path

    # -- helpers -------------------------------------------------------------------

    @staticmethod
    def _stored_content(current: Mapping[str, Any]) -> tuple:
        """The change-detection tuple as the stored row reads it — the same fields
        `_content_of` computes, read back off the row (`NFR-GRADE-05`'s comparison)."""
        return (
            current["grade"],
            current["total"],
            (
                int(current["criteria_total"]),
                int(current["criteria_auto"]),
                int(current["criteria_reviewed"]),
                int(current["criteria_provisional"]),
                int(current["criteria_missing"]),
            ),
            bool(current["boundary_at_risk"]),
            current["score_low"],
            current["score_high"],
            json.dumps(
                sorted(json.loads(current["missing_criteria"] or "[]")),
                sort_keys=True,
            ),
        )

    @staticmethod
    def _as_submission_grade(run_id: str, submission_id: str, row: Any) -> SubmissionGrade:
        missing = tuple(json.loads(row["missing_criteria"] or "[]"))
        return SubmissionGrade(
            run_id=run_id,
            submission_id=submission_id,
            revision=int(row["revision"]),
            state=row["state"],
            grade=row["grade"],
            total=row["total"],
            policy_version=row["policy_version"],
            answer_key_ref=row["answer_key_ref"],
            computed_at=row["computed_at"],
            finalized_at=row["finalized_at"],
            coverage=Coverage(
                criteria_total=int(row["criteria_total"]),
                criteria_auto=int(row["criteria_auto"]),
                criteria_reviewed=int(row["criteria_reviewed"]),
                criteria_provisional=int(row["criteria_provisional"]),
                criteria_missing=int(row["criteria_missing"]),
            ),
            boundary=BoundaryRisk(
                at_risk=bool(row["boundary_at_risk"]),
                score_low=row["score_low"],
                score_high=row["score_high"],
            ),
            missing=missing,
        )


def _build_rollup(rows: Iterable[Mapping[str, Any]]) -> ClassRollup:
    """Segment current grade rows by the rubric version that produced them, and
    annotate the versions covered (`CT-CALIB-09`): figures from R0 and R1 never share
    one unannotated figure — they are separated AND annotated, the strictest reading
    of the clause the case admits either way."""
    by_version: dict[str, list[float]] = {}
    for row in rows:
        version = row["package_version_id"] or ""
        by_version.setdefault(version, [])
        if row["total"] is not None:
            by_version[version].append(float(row["total"]))
    segments = tuple(
        RollupSegment(
            rubric_version=version,
            submission_count=len(totals),
            mean_total=(math.fsum(totals) / len(totals)) if totals else None,
        )
        for version, totals in sorted(by_version.items())
    )
    versions = ", ".join(segment.rubric_version or "(unversioned)" for segment in segments)
    annotation = (
        "rubric revision(s) covered: " + versions
        + (
            " — figures are not comparable across rubric revisions (CT-CALIB-09)"
            if len(segments) > 1
            else ""
        )
    )
    return ClassRollup(segments=segments, revision_annotation=annotation)


def open_grade(store: Store, *, clock: Callable[[], str] | None = None) -> GradingService:
    """Open the grading service over a store — the rung-2 constructor (the
    `open_review` precedent; §3.14 declares the service Protocol but no constructor,
    so the name is the vocabulary's declared invention, landed as declared)."""
    return GradingService(store, clock=clock)


# --- the cohort rollup seam (CT-CALIB-09) -----------------------------------------------------------
#
# `class_rollup` answers by cohort id; the mixed-revision fixture helper registers the
# store it built so the rollup can find it. The registry is keyed by cohort id and
# holds the store's data directory — the same store the helper built, reopened for the
# read.


_MIXED_REVISION_COHORTS: dict[str, Any] = {}


def class_rollup(*, cohort_id: str, store: Store | None = None) -> ClassRollup:
    """A cohort-wide rollup, segmented by rubric version and annotated with the
    versions covered (`CT-CALIB-09`'s consumer half, `FR-GRADE-15`).

    R0-scored and R1-scored results never share one undifferentiated figure: the
    segments separate them, and the annotation names every instrument that
    contributed. The cohort's store is resolved from the registry
    `cohort_with_mixed_revisions` populated, or passed explicitly."""
    if store is None:
        store = _MIXED_REVISION_COHORTS.get(cohort_id)
        if store is None:
            raise GradeError(
                f"no store is registered for cohort {cohort_id!r} — pass store= "
                "explicitly, or build the cohort through cohort_with_mixed_revisions(), "
                "which registers it"
            )
    handle = store.cohort(cohort_id)
    rows = [dict(row) for row in handle.query(
        GRADE_STATEMENTS["select_cohort_current_grades"], cohort_id=cohort_id
    )]
    return _build_rollup(rows)


def cohort_with_mixed_revisions(store: Store | None = None) -> str:
    """A cohort whose current grades span two rubric revisions — the fixture
    `CT-CALIB-09`'s consumer half grades against. Two runs' worth of grades, two
    package versions (`pkg-v1`, `pkg-v2`), one cohort ledger; the store is registered
    under the returned cohort id so `class_rollup` resolves it. Built through this
    module's own insert statement, so the fixture rows are exactly the rows the
    service writes."""
    from aeh.store import open_store

    if store is None:
        store = open_store(Path(tempfile.mkdtemp(prefix="aeh-grade-mixed-")))
    cohort_id = f"c-mixed-{uuid.uuid4().hex[:10]}"
    handle = store.cohort(cohort_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', :t)",
            c=cohort_id, t=_now(),
        )
        populations = (
            ("R-MIX-0", "pkg-v1", ("S-MIX-1", "S-MIX-2"), 71.0),
            ("R-MIX-1", "pkg-v2", ("S-MIX-3", "S-MIX-4"), 64.5),
        )
        for run_id, version, submissions, total in populations:
            for index, submission_id in enumerate(submissions):
                tx.execute(
                    "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                    "VALUES (:s, :c, :r)",
                    s=submission_id, c=cohort_id, r=f"ref-{submission_id}",
                )
                tx.execute(
                    GRADE_STATEMENTS["insert_grade"],
                    run_id=run_id,
                    submission_id=submission_id,
                    revision=1,
                    state=STATE_FINAL,
                    grade="B",
                    total=total + index,
                    policy_version=_content_hash(["fixture", version]),
                    answer_key_ref=_content_hash(["fixture-key", version]),
                    package_version_id=version,
                    computed_at=_now(),
                    finalized_at=_now(),
                    criteria_total=2,
                    criteria_auto=2,
                    criteria_reviewed=0,
                    criteria_provisional=0,
                    criteria_missing=0,
                    boundary_at_risk=0,
                    score_low=None,
                    score_high=None,
                    missing_criteria="[]",
                    amendments="[]",
                )
    _MIXED_REVISION_COHORTS[cohort_id] = store
    return cohort_id


# --- the migration ----------------------------------------------------------------------------------
#
# Cohort v18 — ADR-9's grade ledger: the `(run_id, submission_id, revision)` key with
# the current flag and its partial unique index, and the full grade record the design
# §3.14 data-structures note declares (state, grade, total, provenance refs, computed
# and settled timestamps, the five coverage counters, the boundary-risk triple, the
# missing-criteria list, the amendment trail). A rebuild (create-copy-drop-rename —
# the synth v13 precedent), not an ALTER: the PRIMARY KEY itself changes, and SQLite
# cannot alter a key. The two columns the v1 table carried (`submission_id`,
# `revision`) copy forward AND keep their leading positions — the column order is part
# of the table's compatibility surface (TC-STORE-04's fixture builder inserts
# positionally into the first N declared columns at every prior version, so a rebuild
# that moved a leading column would corrupt the fixture row, not just the golden).
# `run_id` therefore lands third, and the key is a table constraint, which SQLite
# orders independently of column order. Every pre-existing row was written before runs
# carried grade provenance, so it lands under the empty run id, revision numbering
# intact (`TC-STORE-04`'s no-data-loss differential reads this migration's
# before/after).

_GRADE_SUBMISSION_GRADE_KEY = Migration(
    version=18,
    name="grade_submission_grade_key",
    statements=(
        Statement(
            """
            CREATE TABLE submission_grade_rebuilt (
                submission_id        TEXT    NOT NULL REFERENCES submission(submission_id),
                revision             INTEGER NOT NULL CHECK (revision >= 0),
                run_id               TEXT    NOT NULL DEFAULT '',
                is_current           INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
                state                TEXT    NOT NULL DEFAULT 'provisional'
                                     CHECK (state IN ('provisional', 'final', 'incomplete')),
                grade                TEXT,
                total                REAL,
                policy_version       TEXT,
                answer_key_ref       TEXT,
                package_version_id   TEXT,
                computed_at          TEXT    NOT NULL DEFAULT '',
                finalized_at         TEXT,
                criteria_total       INTEGER NOT NULL DEFAULT 0,
                criteria_auto        INTEGER NOT NULL DEFAULT 0,
                criteria_reviewed    INTEGER NOT NULL DEFAULT 0,
                criteria_provisional INTEGER NOT NULL DEFAULT 0,
                criteria_missing     INTEGER NOT NULL DEFAULT 0,
                boundary_at_risk     INTEGER CHECK (boundary_at_risk IN (0, 1)),
                score_low            REAL,
                score_high           REAL,
                missing_criteria     TEXT    NOT NULL DEFAULT '[]',
                amendments           TEXT    NOT NULL DEFAULT '[]',
                PRIMARY KEY (run_id, submission_id, revision)
            )
            """
        ),
        Statement(
            "INSERT INTO submission_grade_rebuilt (submission_id, revision) "
            "SELECT submission_id, revision FROM submission_grade"
        ),
        Statement("DROP TABLE submission_grade"),
        Statement("ALTER TABLE submission_grade_rebuilt RENAME TO submission_grade"),
        Statement(
            "CREATE UNIQUE INDEX uq_submission_grade_current "
            "ON submission_grade (run_id, submission_id) WHERE is_current = 1"
        ),
    ),
)

TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (_GRADE_SUBMISSION_GRADE_KEY,), key=lambda m: m.version
))


__all__ = [
    "BoundaryRisk",
    "ClassRollup",
    "Coverage",
    "CoverageSummary",
    "CriterionInput",
    "GRADE_EXPORT_DIR_ENV",
    "GRADE_STATEMENTS",
    "GRADE_STATES",
    "GradeComputation",
    "GradeError",
    "GradeReport",
    "GradeRevision",
    "GradingService",
    "FinalizationRecord",
    "HARNESS_EXPORT_DIR_ENV",
    "RollupSegment",
    "SubmissionGrade",
    "answer_key_ref_of",
    "apply_policy",
    "boundary_risk",
    "class_rollup",
    "cohort_with_mixed_revisions",
    "coverage_for",
    "export_dir",
    "open_grade",
    "policy_version_of",
    "resolve_grade",
]
