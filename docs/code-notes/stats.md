# `aeh.stats`: design notes

These notes were the docstring of `src/aeh/stats.py` before it was split into the `aeh/stats/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

M-STATS — the admissible-label filter, chance-corrected agreement and scoped
results (§3.16, issue #115).

The module that decides what the system is allowed to *claim*. Every figure
here is a validity claim about one criterion, one population, one backend
profile, one panel build and one scoring model — and the whole design of this
file exists to make the wider claim unrepresentable rather than merely
discouraged (`CT-STATS-02` puts the scope inside the figure's own value;
`TC-STATS-C02` asserts that by construction refusal).

**The single filter (`NFR-STATS-04`).** Admissible to a validity claim means
``label_type = 'blind'`` AND ``evaluation_mode = 'judged'`` (R20/R53), and the
predicate lives exactly once in this source (``_is_admissible``) and is reused
by every path — `NFR-STATS-04`: *"The 'labels admissible to a validity claim'
filter shall exist once in the source and be reused, so R20 and R53 cannot be
violated by a new caller."* ``TC-STATS-C01`` asserts the cardinality of one on
the source, so the third copy is the one that fails the suite, not the next
caller who never learns the rule. The conjunction also reads the visibility
column (`CT-REVIEW-08`'s): a label may carry ``label_type = 'blind'`` and
still have been produced by a teacher who reached the system's output — blind
is a claim about reachability, not a naming convention.

**Chance-corrected agreement (`FR-STATS-02`).** Every figure carries Cohen's
kappa, QWK, or ordinal Krippendorff's alpha — at least one of them carries a
value, never a raw percent agreement alone. Each figure also carries its
sample size in the same value: ``n``, the scoring model,
``population_scope_id``, ``backend_profile`` and ``panel_build_ref`` are
fields of the figure, not footnotes beside it (`FR-STATS-02`, `NFR-STATS-02`).

**Absence is a type (`CT-STATS-03`).** Where there is no figure, the module
returns an explicit ``NoValidationData`` carrying one of three declared
reasons — never a null, never a zero, never a sentinel float. Insufficient
data is a value, not an exception (`CT-STATS-16`): the module raises only on
programming errors, never because there is too little data.

**Atomic and holistic are kept apart (`CT-STATS-04`)** — reported separately,
never merged; no function on this surface offers a figure spanning population,
backend, assignment type, or the narrative-quality dimensions.

**Interpretations this module records** (each is a place the design is silent
and this implementation chose; all are reported on the PR):

* *The figure-vs-absence boundary.* ``agreement`` returns a figure when the
  admissible population holds at least two labels carrying both sides of the
  agreement pair; below that the answer is ``no_blind_labels`` — a first-class
  absence that still carries what *was* measured (``n``, ``excluded_count``,
  and, where a statistic could not be computed, the achievable-precision
  interval) so a reader can tell "one label, no claim" from "never
  administered". The design types ``agreement`` as
  ``AgreementFigure | NoValidationData`` and fixes no boundary; a paired
  population below two is where no chance-corrected statistic is computable at
  all, which is the boundary the contract's own type discipline points at.
* *n is the admissible population, the statistic is computed over the paired
  subset.* ``n`` counts every admissible label (the population the claim is
  about, `CT-REVIEW-08` step 4's non-lossiness); kappa/QWK/alpha are computed
  over the paired subset — labels carrying both sides of the pair. A figure
  whose ``n`` silently equaled its paired count would hide the unpaired labels
  it dropped.
* *The interval is achievable precision, not a confidence interval.* Half-width
  ``h = 1.96 · sqrt(p0(1 − p0)/n) / (1 − pe)`` — the Fleiss asymptotic
  standard error of kappa at Z = 1.96 — centred on kappa when one is
  computable; when no statistic is computable the band is the worst-case
  ``±1.96 · sqrt(0.25/n)`` centred on zero. The width is strictly decreasing
  in ``n`` (`TC-REVIEW-C17`'s differential): more blind labels buy a narrower
  claim, and a system where they do not is not reporting an interval that
  depends on its evidence. It is disclosed as achievable precision — the
  precision the sample size can support — not as a computed confidence
  interval, and carries no verdict about quality (`CT-STATS-20`).
* *Ordinal mapping for declared bands.* Band values that are integers map to
  ``int(v) − 1`` (the plan's 1..K bands are 0-based ordinals); values that are
  not map to their rank in the sorted set of observed values (``"B1".."B4"``
  keeps its suffix order). ``K`` is the larger of the ``band_counts``
  declaration and the largest observed ordinal — the criterion-free inference
  `aeh.agg`'s ordinal alpha makes when no table carries the count.
* *Two-rater alpha and QWK.* Ordinal alpha follows `aeh.agg`'s declared
  convention (``alpha = 1 − D_o/D_e``, unanimous exact 1.0 checked before the
  band-count test) with the panel-vs-teacher population as the two-rater
  ``D_o`` — the mean per-label distance between the two sides. QWK is the
  quadratic-weighted kappa over the same ordinals. Kappa is undefined only
  where chance agreement is 1 (a single category on both sides), where
  ``pe = 1`` makes every chance-corrected coefficient 0/0; the figure still
  exists and discloses the degeneracy it sits in.
* *Rung 2 reads the current cohort's labels only* (`CT-STATS-18`): the
  constructor reads the declared statement with a bound cohort parameter —
  never a join to another cohort or to Tier C — and this module writes
  nothing (`CT-STATS-15`).
* *`STATS_MIN_N_FOR_HEADLINE` is a display-qualifier boundary, not a verdict.*
  Below it a figure renders with an explicit "too few to draw conclusions
  from" qualifier (HLD §11.5's S12 mock); it says nothing about whether the
  figure is good (`NFR-SYS-08`).

**The MVVP as six separately-reported protocols (`FR-STATS-05`, #116).**
``run_mvvp`` runs the Minimum Viable Validation Protocol (HLD §2.5) and
reports each of its six steps individually — step 1 is the chance-corrected
agreement surface above, step 2 the order/position swap, step 3 the
replication floor, step 4 cross-validation by assignment type, step 5 the
consistency-bias pairing, step 6 the compression check. Never one pass/fail:
the return type carries no ``passed``, no ``ok``, no ``verdict`` (`CT-STATS-07`
sweeps the names a convenience property would take). Steps 2–5 re-run
whenever any panel member, build, quantization or prompt-template version
changes (`FR-STATS-19`, HLD R30) — ``result_id`` is content-addressed on the
assignment type and the four trigger dimensions, and no durable result is
kept to reuse, show or merge (`CT-STATS-15` writes nothing), so a changed
dimension is a different result by construction.

**The four checks that read the same population differently (#117).**
``compression_check``, ``surface_proxies``, ``routing_policy_validity`` and
``drift_check`` complete the protocol surface (`FR-STATS-06`..`FR-STATS-09`).
Each is a *comparison* rather than a quality number, and each carries the
interpretation its clause fixes inside the value it returns:

* *Compression is relative, and its blind spot is part of the value*
  (`CT-STATS-10`). The check compares the panel's band shape against the blind
  gold labels' using ``band_entropy`` and ``interior_rate`` and reports
  ``panel_narrower`` — the only direction it can see. A panel and a teacher
  compressing **together** produce a clean result, so the report carries the
  co-compression limitation as a field, including in its empty case, where
  "no distribution" and "no compression found" must not be confusable.
* *The surface-proxy regression is a measured channel.* The regression's
  inputs — assigned scores beside response length, vocabulary complexity, OCR
  quality, handwriting legibility where captured, formatting regularity — are
  the pipeline's score rows, which this module does not hold; the caller that
  measured the per-criterion correlations declares them through
  ``build_stats(surface_correlations=...)`` exactly as #116's MVVP declares
  its measured channels. What this module owns is the interpretation: a
  feature whose ``|r|`` reaches the threshold is a surface-proxy flag, the
  alert ``surface_proxy_flag_on_criterion`` fires on it (`CT-STATS-19`), and
  the per-criterion payload is the ``ProxyReport.surface_proxy_flags`` the
  validation record's writer (#118's ``promote``, through `M-PKG`) stores.
* *Subgroup analysis is a two-key gate* (`NFR-STATS-05`, `CT-STATS-18`).
  ``STATS_SUBGROUP_ANALYSIS_ENABLED`` defaults to false — the declared
  Configuration value, carried as a module constant so the default is
  inspectable — and the environment knob may enable it only where an
  installation has declared the analysis locally lawful, which is a decision
  this module cannot make. Even enabled, the breakdown runs only on an
  explicit ``subgroup=`` request; and a request while the gate is closed is a
  refusal, not an empty result.
* *Similar routing rates are failing, not uninformative* (`CT-STATS-11`,
  HLD R22). The policy is working when the escalated-and-reviewed arm shows
  the larger error rate against blind teachers (the HLD's 8%-versus-1% gap);
  rates within the tolerance mean the policy escalates the wrong things, and
  the verdict is ``failing`` — the finding about `M-AGG`'s constants, not an
  absence of one. The arms are read off the label's ``routing`` column through
  ``ROUTING_POLICY_ARM_SOURCES``: the column carries the queue's admission
  routing (`CT-AGG-06`'s closed set), so the escalated-and-reviewed arm is the
  ``reviewed`` rows — the one value `aeh.agg` never assigns, because it names
  a review that has happened — and the auto-accepted arm is the ``auto`` rows;
  still-queued, triage and provisional rows join neither. The tolerance is an
  environment knob whose default is the declared 0.05, and arms without a
  computable rate return ``no_data`` as a value (`CT-STATS-16`), never an
  exception.
* *Drift is advisory, and the report says what would make it binding*
  (`CT-STATS-12`). The sample is 20–30 submissions (`FR-STATS-09`), taken as a
  deterministic even spread that spans the sample end to end — no randomness,
  and no truncation to its head; a sample below the floor is the absence
  value, not a verdict computed on too little. The comparison runs over judged
  criteria only (`CT-DET-02`'s exclusion), against a baseline the caller
  declares from `M-PKG`'s records. ``binding_threshold`` is ``None`` **by
  design**: there is no distance, severity or sample size at which this check
  starts blocking a run — HLD R11 forbids gating a school's grading on an
  advisory comparison of at most 30 submissions, and `NFR-SYS-08` declares no
  threshold here — so the field states the absence rather than leaving it
  implied.

**The validation record and its figures (#118).** ``promote`` records one
administration (`FR-STATS-10`): the operational and blind counts land
separately, and the operational ones never reach a κ (`FR-STATS-11`); an
administration that collected no blind labels reports
``NO_NEW_VALIDATION_EVIDENCE`` as a first-class value and advances no
agreement figure (`CT-STATS-05` — the #111/#125 precedent: absence is
reported, never an earlier figure reused and never a zero); the weakest
criterion per population travels with every aggregate (`FR-STATS-13`); and
the narrative-quality channel — citation validity, hallucinated-claim rate,
teacher rating where collected — is reported separately from criterion
agreement (`FR-STATS-12`), reconciling with #98's SynthesisReport, which
carries the same rates. Interpretations this implementation records:

* *The claim is the record's write in Tier D.* `aeh.review`'s collection
  writes labels with no cohort; ``promote`` claims the unclaimed labels into
  the named cohort with this module's own declared statements, and the
  record's durable row goes through `aeh.pkg.record_promotion`, so the write
  carries `M-PKG`'s frames with `M-STATS`'s initiation (`CT-STATS-15`'s
  attribution). Audit rows are read unclaimed, never stamped — `audit_record`
  is append-only (`#103`'s trigger, `FR-DET-10`/`TC-GRADE-23`) — so their
  cohort dimension rides their insert and they remain the record's sourcing
  input only. A rung-0 instance (``build_stats``' shape) computes the same
  counters and weakest entry in memory and writes nothing — rung 0 has
  nothing durable to write to.
* *The operational-evidence weighting is declared, not inferred*
  (`FR-STATS-14`). ``operational_signal`` weights acceptance 0.25, override
  0.75, blind 1.0 — informative, weak, authoritative — and a caller may
  declare the mapping through ``build_stats(operational_weights=...)``; the
  weighting never touches κ, which is computed over the admissible population
  alone, so a weighted operational channel and an unweighted one carry the
  same agreement figure (`CT-STATS-06`'s invariance).
* *The record's κ is a single-criterion value.* A multi-criterion
  administration has its per-criterion figures in ``weakest_per_population``
  and no blended headline (`CT-STATS-04` keeps that claim unrepresentable).
  The weakest entry is the minimum computable κ with a sorted tie-break;
  where no κ is computable the entry names the criterion and carries
  ``None`` — a disclosure, not a zero.
* *The optional export touches neither the scoring pipeline nor the store*
  (`NFR-STATS-03`). ``analytical_export`` reads the labels the instance
  already holds, opens no connection, takes no lock, and writes one JSON
  document under the data directory's ``exports/`` — the cost of that
  honesty is that it reports the labels the instance was built with, which
  is exactly what its docstring says. The requirement names Parquet/DuckDB;
  this implementation writes JSON, a recorded descope: no Parquet/Arrow or
  DuckDB engine exists in the harness's declared dependency set, and the
  operative halves the requirement exists for — read-only, off the scoring
  path, never a second source of truth (ADR-6) — are what the tests pin and
  what the export holds.

The four seams (CLAUDE.md): the constructor pair is the headless driver —
``build_stats``/``open_stats`` return structured values with no console in the
loop; the deterministic transport for every external dependency is `aeh.store`
itself, the deterministic local store this module's reads ride (no egress of
its own); the environment-sensitive constants are env-gated knobs read at
call time with the declared production value as the default —
``STATS_SUBGROUP_ANALYSIS_ENABLED`` (pinned by `TC-STATS-C18`'s case), the
three detector sensitivities #117 adds for the surface-proxy flag, the
routing tolerance and the drift distance, and #118's blind-skip patience
(``STATS_BLIND_SKIP_ALERT_AFTER``, how many consecutive administrations
without a blind sample the alert waits before firing, read at call time) —
so a slower box or a lawful installation adjusts without a code change. (``STATS_MIN_N_FOR_HEADLINE``,
pinned by `TC-STATS-C20`, is a declared constant from #115 and deliberately
not an environment knob: the display-qualifier boundary is a contract value,
not an environment-sensitive one.) And every figure is stage-level
observability by construction — n, the excluded count, the stated limitation,
the verdict's stated interpretation and the advisory statement travel with the
number, next to it, not in a footnote.
