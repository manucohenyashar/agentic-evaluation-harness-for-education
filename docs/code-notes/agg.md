# `aeh.agg`: design notes

These notes were the docstring of `src/aeh/agg.py` before it was split into the `aeh/agg/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

M-AGG — the aggregation core: median band, the single band→points mapping and
ordinal α (detailed-design.md §3.12; issue #91).

A panel's verdicts become one criterion score in three pure steps, in this order
and no other (`FR-AGG-01`, `FR-AGG-02`, R41):

1. **Aggregate on the ordinal band scale** — the score's band is the panel's
   **median band ordinal**, never a mean of bands and never a mean of points. The
   scale has no metric, so a mean of bands is meaningless, and a mean of points
   imported from bands is worse: it would produce a value no judge gave and no band
   describes (HLD §9.9's worked example: 3.33 from three verdicts of which none
   said it). The modal band and `band_spread` — the ordinal distance between the
   panel's lowest and highest valuations — are recorded beside the median (`FR-AGG-01`).
2. **Map once** — points are derived from the *aggregated* band through M-PKG's
   canonical `points_for_band`, exactly once, *after* aggregation. There is no code
   path that maps per-judge bands to points and averages them, and none may be
   added (`FR-AGG-02`, `NFR-AGG-02`, CT-AGG-02): the mapping is applied in exactly
   one place in the source, `aeh.pkg:points_for_band`, the only sanctioned reader
   of the band table's points (`CT-PKG-05`).
3. **Agree ordinally** — agreement is Krippendorff's α **with an ordinal metric**
   (`FR-AGG-04`), under the convention `tests/unit/agg/test_ordinal_alpha.py`
   declares (see `ordinal_alpha` below). A raw "2 of 3 agreed" count is never the
   agreement figure.

Everything here is a pure function — no store access, no model call, no clock, no
configuration read beyond the values passed in (`CT-AGG-01`, `NFR-AGG-01`). That
purity is what makes the whole confidence and escalation policy unit-testable
(NFR-ORCH-04) and what keeps this module's write set empty (`CT-AGG-11`): the
caller owns the transaction; this module returns a value.

**The four seams** (CLAUDE.md code conventions), for what this module adds:

1. *Headless driver* — `aggregate`/`ordinal_alpha`/`describe_agreement` are plain
   code-level entry points; nothing here requires the console or a run.
2. *Deterministic transport* — the module takes on **no external dependency**:
   no network, no store, no clock. There is nothing to fake, which is the point
   of keeping M-AGG pure.
3. *Env-gated knobs* — nothing here reads the environment (`CT-AGG-01`): the
   thresholds, caps and multipliers the design names (`AGG_AUTO_THRESHOLD_*`,
   `AGG_CAP_TABLE`, the multipliers) are **module constants as production
   defaults**, and every one of them arrives injected at the call —
   `aggregate(..., config=...)` — so a different environment or a test tunes by
   passing values, never by reaching for `os.environ` (Q-04: injected as
   configuration, never test literals).
4. *Stage-level observability* — `CriterionScore` carries every stage's output as
   a named field next to the result: the panel's size (`judge_count`), the chosen
   band (`band`/`ordinal`), the mapped value (`points`), the modal band
   and spread, the agreement figure with its degeneracy marker, and the band
   histogram the aggregation stage saw (`CT-AGG-15`'s per-criterion band
   histogram). Nothing is folded into a bare status.

Design interpretations this implementation commits to (recorded for review, the
det.py precedent):

- **The α convention** (the design's own `TBD`, resolved the only way the test
  plan's differential can hold): α = 1 − D_o / D_e, where D_o is the mean
  pairwise ordinal distance among the panel's valuations and D_e is the mean
  pairwise ordinal distance over all ordered pairs of *distinct declared bands*
  of the criterion — a property of the criterion alone, identical for two panels
  of equal shape, so the differential is carried entirely by D_o. Distances are
  normalized `|i − j| / (K − 1)` over the criterion's declared band scale. See
  `ordinal_alpha`.
- **The modal tie-break** (the design pins none; `TC-AGG-02`'s declared
  assumption makes it #91's to declare): among bands tied for the mode, the band
  whose ordinal is **closest to the median band's ordinal** wins; still tied, the
  lower ordinal wins. The modal band is always one the panel actually gave — the
  tie-break only ever chooses *among* the tied bands, never outside the
  histogram.
- **The degeneracy marker**: `agreement_degenerate` is True exactly when the
  criterion's band scale has fewer than three bands — the two-band case
  (`CT-AGG-17`), where the ordinal and nominal metrics coincide and a unanimous
  panel yields α = 1 by construction. The figure is still returned (the number is
  the promise; the marker is the honesty — `TC-AGG-19`).
- **Single-verdict panels** aggregate honestly (the panel's own band, spread 0,
  judge_count 1) and carry `agreement = None`: with no pairs, ordinal α is
  *undefined*, and `CT-AGG-04` forbids a substitute number. The confidence prior
  for a single judge is #92's surface and is not pretended here.
- **An empty verdict list is a programming error** and raises `EmptyVerdictsError`
  before anything else is looked at (`CT-AGG-12`) — never a zero, a lowest band,
  or a null score. An even panel raises `EvenPanelError` (`FR-AGG-03`): a failed
  computation, not a rounded verdict — the store's odd-`judge_count` CHECK
  (`det` migration v9) is the second half of that refusal, and this module never
  hands it an even row.

Scope: #91 landed the aggregation core above plus `describe_agreement`, the
module's own honest description of an agreement figure (`CT-STATS-21`'s M-AGG
consumer limb). #92 landed the confidence surface on that core: the integrity
inversion (`FR-AGG-05`, ADR-10 — a cap is a `min`, never a penalty term, so
unanimity cannot outrun bad evidence), the four integrity inputs recorded on
the score row (`FR-AGG-13`), the from-the-row-alone re-derivation
(`recompute_confidence`, `NFR-AGG-04`), and the cohort migration that carries
the columns. #93 completes the module: the closed routing set with the
`triage`/`queued` split (`FR-AGG-07` — an ingestion-caused state is the
operator's rescan, never a teacher's marking decision), the four score states
assigned per cause with the breaker's `ungradeable_by_panel` (`FR-AGG-11`),
the two-verdict discard composed with `EvenPanelError` (`FR-AGG-12` — the
module never adjudicates between two), the deterministic pass-through
(`FR-AGG-10`), and the escalation policy `should_escalate` (`FR-AGG-08/09`):
observable signals only, model self-confidence one weighted input and never
the sole trigger (R22's failure mode), one judge to three and never to two.
The decision is returned to `M-ORCH`, which enqueues (`FR-ORCH-09`) — this
module imports no orchestrator and offers no enqueue; the dependency stays
one-way. The write set is unchanged and stays empty of SQL (`CT-AGG-11`):
every value here is returned for the caller's transaction, so `M-AGG` has no
write path to `narrative` and none to anything else.

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.agg`. Each section is named after the file and the function or class it describes.

### aggregate.py: aggregate

Pure (`CT-AGG-01`): the verdicts, the criterion's declared band set, the
integrity signals and the configuration are values; nothing here reads a
store, a clock, or any configuration beyond its arguments — `config` is
`None` (the module constants above are the production defaults) or a value
carrying any of `auto_threshold_atomic`, `auto_threshold_holistic`,
`uncited_multiplier`, `holistic_multiplier` and `caps` (a mapping from each
of the six signal names to its hard cap; absent it entirely, `AGG_CAP_TABLE`
applies).

The aggregation is the **median band ordinal**, mapped to points exactly
once through M-PKG's canonical `points_for_band` (`CT-PKG-05`,
`NFR-AGG-02`) — never a mean of bands, never a mean of points, and never a
per-judge average (RISK-05).

The confidence (`FR-AGG-05`, ADR-10) is §3.12's computation in three steps:

1. **Base** — the panel's own agreement figure (`ordinal_alpha(verdicts)`,
   criterion-free) for a panel of three or more; the band-position prior
   for a single judge ("extreme bands score higher").
2. **Multipliers** — `× uncited_multiplier` when any verdict is uncited,
   `× holistic_multiplier` for a holistic criterion. Multipliers shape the
   base; they never touch a cap.
3. **Caps** — each adverse integrity signal's cap is a hard `min` (ADR-10:
   a cap is a `min`, never a penalty term, so no amount of panel agreement
   can lift the figure past the worst adverse signal — R19). Fail-closed:
   `None` ("not measured") is adverse, never favourable, never absent, and
   binds the same cap as a measured-adverse value (`NFR-INTEG-03`); a
   signal with no entry in the injected table binds nothing. One cap is
   conditional (§3.12): `evidence_present` binds only where the criterion
   requires evidence — read fail-closed when the criterion does not
   declare the flag.

Routing and state (`#93`) are assigned **per cause**, in precedence order —
breaker, then panel size, then the threshold:

* `breaker_tripped=True` — the criterion's `M-ORCH` circuit breaker tripped
  (`CT-ORCH-16`): the score is routed `provisional` and its state is
  `ungradeable_by_panel`. It is surfaced, never treated as an ordinary
  provisional, and never auto-accepted — no confidence can lift it.
* a single-judge panel — routed `provisional`, state
  `provisional_unreviewed`: one judge's word awaits its panel
  (`FR-ORCH-13`'s "scored single-judge provisional"), never auto-accepted.
* otherwise — `auto` iff `confidence >= auto_threshold_for(scoring_model)`
  (§3.12), else `queued`; state `final`.

The four integrity inputs `FR-AGG-13` records are carried on the score
exactly as received, beside the pre-cap base — the fields that make the
figure reconstructible from the stored row alone (`recompute_confidence`).
`notes` records what this call did, one clause per cause (`FR-AGG-12`'s
discard, the single-judge mark, the breaker mark, the pass-through).

The two marked alternative entries (`#93`):

* `deterministic_score=` (`FR-AGG-10`) — an M-DET row judged without a
  panel (`judge_count` 0). It is its own entry and is checked first,
  because an empty panel is exactly how such a row arrives. The row is
  **echoed, never re-aggregated**: band, points, ordinal, judge_count,
  agreement and the recorded signals are carried as received, and
  `routing`/`state` are taken off the row (`unresolved_selection` arrives
  routed `triage`), with `auto`/`final` as the fallbacks when a row omits
  them. A non-empty panel alongside a row is a contradictory call and
  raises `ValueError`.
* `fallback=True` (`FR-AGG-12`) — the one even case with a declared
  fallback: a panel **left at exactly two** by an unrecoverable judge
  failure. The second verdict is discarded — never adjudicated between,
  since a tie broken by rule is a coin flip presented as a judgement
  (R48) — and the base single-judge band is kept, provisional. Any other
  even size still raises `EvenPanelError`; an odd panel aggregates
  normally regardless of the mark.

An empty panel with no deterministic row raises `EmptyVerdictsError` (a
programming error, `CT-AGG-12`); any other even panel raises
`EvenPanelError` before any median is taken (`FR-AGG-03`).

### agreement.py: ordinal_alpha

The design requires the ordinal metric but records a `TBD`: the textbook
coincidence-matrix α is degenerate here, because a criterion's panel is a
**single unit** — over one unit, observed and expected disagreement are the
same pair population, so the textbook α collapses to 0 for any disagreeing
panel and 1 for a unanimous one, under *any* per-pair distance. No convention
built on the observed marginal alone can satisfy the plan's requirement that
adjacent-band disagreement score **higher** than distant disagreement at
equal raw agreement. The convention this module commits to is the one that
can, and it is the one `tests/unit/agg/test_ordinal_alpha.py` pins by hand:

    alpha  = 1 - D_o / D_e
    D_o    = mean pairwise distance among the panel's valuations
    delta  = |i - j| / (K - 1)     over the criterion's *declared* band scale
    D_e    = mean pairwise distance over all ordered pairs of distinct
             declared bands

`D_e` is a property of the criterion alone, so two panels of equal raw
agreement differ only through `D_o` — which is exactly the differential the
requirement is: a `[B0, B1, B1, B1, B2]` panel and a `[B0, B1, B1, B1, B3]`
panel agree at the same raw rate (3 of 5 modal, three agreeing and seven
disagreeing pairs of ten) and score 0.52 against 0.28 on the four-band scale.

Returns `None` where α is **undefined** rather than a substitute number
(`CT-AGG-04`): fewer than two verdicts (no pairs), or a scale with fewer than
two declared bands carrying actual disagreement (`D_e` would be zero). A
unanimous panel is *defined*, not degenerate-by-absence: D_o = 0 gives α = 1
exactly — including the two-band case, where the design's `TBD` pins α = 1
**by construction** (`TC-AGG-19`) and the score carries
`agreement_degenerate` so no consumer renders that 1 as if it were
information (`CT-AGG-17`) — and including the criterion-free call on a panel
whose valuations all sit at one ordinal, where the inferred scale is one
band and unanimity is still defined.

When `criterion` is omitted the declared scale is inferred from the panel's
own highest ordinal (`K = max(ordinal) + 1`) — the reading a caller can take
holding nothing but the verdicts. `aggregate` always passes the criterion, so
every score row's agreement is computed on the full declared scale.

The convention bounds nothing below: unlike `aggregate`, this function does
not refuse an even panel, and a panel spread across the full scale (or using
ordinals outside any declared scale) can score below −1. Only the
fewer-than-two and one-band cases are `None`; callers needing a figure from
a legal panel should route through `aggregate`, whose odd panels stay within
the familiar range on a declared scale.

### escalation.py: should_escalate

Pure (`NFR-ORCH-04`, `CT-AGG-01`): the score row, the criterion, the
criterion's override history and the package baseline are values; no
store, no clock, no model call, no network, and no configuration beyond
the arguments — `config` may carry any of `escalation_threshold`,
`escalation_signal_weight`, `escalation_no_data_weight`,
`escalation_self_confidence_weight`, `escalation_anomaly_sigma` and
`escalation_override_rate` (each defaulting to its module constant).

The decision is a concern level against the threshold. Each observable
signal contributes `AGG_ESCALATION_SIGNAL_WEIGHT` when it fires (§7.1's
enumeration, in order):

1. **Interior band position** — the score sits in a declared band that is
   neither the top nor the bottom of the criterion's scale: the panel did
   not reach a scale edge, where bands are best discriminated. Read off
   the row's `ordinal` against `band_count` (the row's, else the
   criterion's); a row carrying neither is not making the claim, and the
   limb is skipped.
2. **Adverse integrity signals** — each of the six M-INTEG fields read
   off the row: adverse (the opposite polarity, or a recorded `None` =
   not measured, fail-closed) fires; an absent field is no claim and
   skips its limb.
3. **Uncited verdict** — the row's `uncited` mark.
4. **Criterion override history** — `history.override_rate` above
   `AGG_ESCALATION_OVERRIDE_RATE` (more than half of the criterion's
   reviewed scores were overridden, the breaker's strict "more than
   half"), or the criterion already escalated before
   (`history.escalations`). A recorded no-data rate contributes
   `AGG_ESCALATION_NO_DATA_WEIGHT` — not a zero (CT-STATS-09), but not a
   trigger either.
5. **Distributional anomaly** — the score's ordinal sits
   `AGG_ESCALATION_ANOMALY_SIGMA` standard deviations or further from the
   package baseline's expected band position. A baseline without a usable
   `std` is unmeasurable, not anomalous.

Model self-confidence (`score.self_confidence`) enters once, weighted:
`AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT × (1 − self_confidence)`. It is
never appended to `reasons` — a decision escalated on self-confidence
alone is structurally impossible (its full-sweep contribution stays below
the threshold, R22), so every reason is an observable a reviewer can go
and look at. Absent, it contributes nothing: absence is no claim.

Returns the `EscalationDecision`: `escalate`, the target panel depth (the
next odd at least two above the current panel — 1 → 3, never 2,
`FR-AGG-09`; `validate_escalation_plan` in `aeh.orch` is the consumer's
odd-plan check) and `reasons`. Under the production constants a decision
not to escalate carries the current panel depth unchanged and no reasons
(every weight is sub-threshold alone, so nothing fires without escalating);
an injected sub-threshold signal weight can fire a reason without reaching
the threshold — the fired observables are recorded either way.

### recompute.py: recompute_confidence

The reconstruction contract: what `FR-AGG-13` records is enough. The four
integrity inputs ride the row itself (`spans_verified`, `evidence_present`,
`sufficiency_flag`, `ocr_overlap_risk` — each as received, `NULL` = not
measured = adverse), and the pre-cap base rides `confidence_base`. So the
figure is re-derived by replaying the same computation the aggregator ran,
from fields a reader of the database can see:

1. **Base** — `confidence_base` (the post-multiplier, pre-cap figure the
   aggregator consumed) when the row carries it; else `agreement` for a
   panel of three or more, exact whenever the panel touched the declared
   top band (where the criterion-free and criterion-declared alpha readings
   coincide); else the band-position prior for a single-judge row, from the
   row's own `ordinal`.
2. **Caps** — the recorded signals' caps, fail-closed, as hard `min`s
   (ADR-10), exactly as `aggregate` applied them.

`None` is returned, never zero, when the row cannot support a re-derivation:
no panel (a deterministic row's `judge_count` is 0), an even panel (a failed
write), or no base derivable at all. The four recorded signals cap the
figure exactly as before. A row `write_score` wrote (#360: its `caps_fired`
is recorded) carries `described_evidence` and `extractor_disagreement` too,
and their caps are re-applied the same way, so the residual `TC-AGG-C15`
disclosed closes for such rows; an older row without them re-derives from
the four. The multipliers' inputs (the uncited mark) ride `confidence_base`,
which already has them applied.
`config` carries an injected cap table the same way `aggregate`'s does.
