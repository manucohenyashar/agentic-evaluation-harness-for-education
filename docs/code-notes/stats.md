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

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.stats`. Each section is named after the file and the function or class it describes.

### comparisons.py: drift_check

The sample is 20–30 submissions (`DRIFT_SAMPLE_RANGE`, inclusive at both
ends). Above the high end the check takes an even spread of the declared
size and reports how many it used; below the low end there is no valid
sample and the answer is the absence value with ``n`` as context — a drift
verdict computed on nineteen submissions is exactly the substitute figure
`CT-STATS-16` forbids. The spread is deterministic on purpose: the sample
must span the caller's list end to end, first and last submission
included, and no randomness may enter a claim's evidence.

The comparison runs over **judged** criteria only: a criterion the
constructor declares deterministic is excluded from
``criteria_covered``, because a deterministic result carries no verdicts
and there is no distribution to compare (`CT-DET-02`). The sample's
distributions come from the declared ``current=`` channel when the caller
supplies one, otherwise from the constructor's admissible population —
the current administration's judged distribution — and
``sample_source`` names which. With the constructor population as the
source, ``sample_size`` still describes the caller's submission sample
while the per-criterion distributions cover the instance's whole
admissible population — the disclosure is in ``sample_source`` precisely
so the two are never confused. The baseline comes from the caller's
declared ``baseline=`` channel (`M-PKG`'s records; this module writes
nothing and owns no baseline of its own), and ``distances`` compares the
two where both sides exist — the total-variation distance, with the
drifted criteria named at the tolerance.

``advisory`` is always true and ``binding_threshold`` is always ``None``
(`CT-STATS-12`): the statement in the value says what would make it
binding and why none exists. Raises on programming errors only; a sample
below the floor is the absence value, not a raise.

### exports.py: long_horizon_export

ADR-19 replaced the base clause's Parquet/DuckDB with JSON Lines, and the reason is
the one that matters for a LONG-horizon artifact: a text format with one
self-describing record per line can be read in five years by anything that can read a
line, with no engine, no version-matched reader and no binary schema to recover. The
columnar export stays available as a later optional extra; nothing here imports one.

**Reproducible by construction.** Re-exporting the same labels produces byte-identical
files: records are ordered by label id, keys are written in the declared order, and
NOTHING carries a wall clock. The generation time is exactly the field that would make
every export differ from every other, which is why this document has no header and no
`generated_at` — `analytical_export` carries one because it is a snapshot report, and
this is an archive.

**Never touches the scoring pipeline.** The labels are the ones the instance already
holds — its constructor read them — so this opens no connection, takes no lock and
writes nothing to any tier. The only writes are the files under ``exports/``, which is
what lets the export run beside a live scoring run. The cost of that honesty is the
same one `analytical_export` pays: the export reports the labels the instance was
built with, and an export of fresher data asks ``open_stats`` first.

Returns the written paths, sorted — so a caller can report what it produced without
listing the directory and picking up someone else's files.

### measurements.py: measure_position_bias

Re-scores every fixture judgment twice through the real `ScoringWorker.assemble` /
`dispatch` path — once in the shipped default order, once with
`HARNESS_JUDGE_EXEMPLAR_SEED` set to `seed` — and reports, per judge, the fraction of
its judgments whose band MOVED. A judge whose verdict is a property of the work
answers the same band either way and rates 0; one whose verdict is a property of
where the exemplars sat rates above it. That is `FR-STATS-15`'s order/position swap,
measured.

**The denominator is each judge's own measured judgments — not the fixture-submission
count, and not the dispatch count.** All three coincide in the simple world (one run,
one criterion, every submission judged) and diverge everywhere else, silently:

* one (submission, judge) yields one judgment PER CRITERION, and one more per run the
  fixture set was judged in. Dividing by `len(fixture_submissions)` counted those
  extra judgments in the numerator while leaving the denominator at six — a fixture
  set judged twice reported double the true rate, and `run_mvvp` then REFUSED the
  result for leaving `[0, 1]`, turning a wrong figure into a crash one call later;
* a submission the store holds no judgment for inflated the denominator, understating
  every rate (`2/7` where the truth is `2/6`);
* two dispatches make ONE comparison, so dividing by dispatches would halve
  everything.

**A judge with no measured judgment is absent from the result, never `0.0`.** Zero is
a measurement — "this judge did not move" — and a judge the fixture set never reached
has not been measured at all. `run_mvvp` reports an absent judge as
`measured=False` with its declared reason, which is the true statement; a fabricated
`0.0` would have been stamped `measured=True`. This is the same rule the empty-fixture
guard below applies, held at per-judge granularity.

**A permutation that moved nothing is excluded from both sides of the fraction.**
`judge._ordered_exemplars` returns early for a criterion with fewer than two
exemplars, so the salt cannot reorder what is not there: the permuted request is
byte-identical to the default, the same recorded reply answers both, and the
comparison can only ever say "no change". Counting that as evidence of
order-insensitivity would manufacture a confident `0.0` out of a criterion that was
never permutable. Units whose order did not move are skipped; a judge left with no
movable judgment is absent, and a call where nothing at all was permutable raises
rather than returning a mapping of silent zeroes.

The return is a plain `Mapping[judge build_id, float]`, which is what
`run_mvvp(measured_position_bias=...)` validates and reports verbatim. No wrapper
type: a rate that cannot be compared with `==` to the figure a reader hand-computes
is a rate nobody can check.

Judges outside `panel` are ignored rather than measured — `run_mvvp` refuses rates for
judges its declared panel does not name, so emitting one here would produce a mapping
the consumer is required to reject.

### measurements.py: measure_self_agreement

Every fixture judgment is dispatched `runs` times in the default exemplar order, and a
judgment counts as agreeing only when ALL its replications answered the same band. The
rate is the fraction of the judge's judgments that agreed — 1.0 for a judge that
repeated itself exactly, lower for one that did not.

**Replication is per judgment, not per judge.** `runs` dispatches of one submission
says nothing about the other five; the floor `FR-STATS-21` states is on each judgment,
so this issues ``runs`` dispatches for every judgment the judge actually made.

**The denominator is each judge's own measured judgments**, and a judge with none is
absent from the result rather than carrying `0.0` — for the reasons set out on
`measure_position_bias`, which apply here with the sign flipped: a fabricated `0.0`
self-agreement reads as "measured, and never stable", the harshest possible claim
about a judge that was never asked anything. The two drivers fabricating opposite
lies from the same empty input is what makes this a rule rather than a preference.

`runs` below `SELF_AGREEMENT_MINIMUM_RUNS` raises `ValueError` — a real refusal, not an
assertion, so it survives ``python -O`` and reads as a rejected argument rather than a
broken invariant.

Reported beside, never merged with, the backend's own
``deterministic_at_temperature_zero`` claim: `run_mvvp`'s step 3 carries both, because
a measured rate and a vendor's assertion are different kinds of evidence
(`CT-PROV-04`).

### mvvp.py: run_mvvp

One call, six answers — each step's own outcome record beside its own
requirement (`MVVP_STEP_REQUIREMENTS` is `FR-STATS-05`'s mapping), never
collapsed into one pass/fail (`CT-STATS-07`). The steps:

1. the chance-corrected agreement surface (`FR-STATS-02`) — the figures
   `agreement` emits, one per criterion in scope, or the surface's own
   absence value for a population with no criteria to figure;
2. the order/position swap (`FR-STATS-15`) — the held-out fixture subset
   re-scored with the exemplar order and the reference-material
   presentation order permuted, per judge (`TC-STATS-16`'s live tier
   measures the rate through the injected provider seam, the one egress
   point; headlessly each judge's result is the explicit not-measured
   value with its declared reason);
3. the replication floor (`FR-STATS-16`) — per-judge self-agreement
   reported **together with** the backend's declared
   ``deterministic_at_temperature_zero`` (`CT-PROV-04`'s claim), the two
   different claims they are, never merged;
4. cross-validation by assignment type (`FR-STATS-17`) — one assignment
   type's figures, per criterion, with the spanning refusal structural:
   no figure spanning assignment types is representable in the value, and
   where the labels carry types and none is named, the step is the
   disclosed refusal (`no_assignment_type_named`), never a pooled figure;
5. the consistency-bias pairing (`FR-STATS-18`) — every judge in scope's
   step-3 rate beside its step-2 position-bias result, one pair, never
   one figure alone;
6. the compression check (`FR-STATS-06`) — the panel's band shape
   against the gold's, with its stated limitation in the value.

**The measured channel** (the four seams' third): what a caller has
measured arrives declared — ``measured_self_agreement`` for step 3, the
≥3-run replication's per-judge rates; ``measured_position_bias`` for
step 2's swap; ``backend_claims_deterministic_at_temperature_zero`` for
the backend's declaration. A rate is reported verbatim — never clamped,
floored or omitted (`TC-JUDGE-C17` limb 3: a measured value below 1.0 is
the finding the protocol exists to surface, not a failure). What was not
measured is the declared not-measured value with its reason — never a
plausible number, never a raise (`CT-STATS-03`, `CT-STATS-16`).

**Re-run semantics (`FR-STATS-19`, `CT-STATS-08`).** ``configuration``
carries the four trigger dimensions; each is echoed in the result's
``measured_configuration`` and in steps 2–5's own records, so a consumer
can verify the match itself. ``result_id`` digests the assignment type
and the four — a changed dimension is a different id, and ``latest_mvvp``
answers consult-time calls by measuring fresh, because no durable result
is kept to reuse, show or merge.

Defined at module level and bound into ``ValidationStats`` below, so the
surface ``require(STATS_MODULE, "run_mvvp")`` names and the method the
instance carries are the same function. Raises on programming errors
only (`CT-STATS-16`): a malformed argument propagates. Insufficient data
is the per-step outcome.

### promotion.py: promote

The claim is the record's write in Tier D and this module's own: the
labels an administration collected carry no cohort until an administration
takes them (`aeh.review`'s collection writes ``cohort_id`` NULL), and the
claim is the act that makes them one administration's evidence. Audit rows
are read, never stamped — `audit_record` is append-only (#103's trigger,
`FR-DET-10`/`TC-GRADE-23`), so their cohort dimension rides their insert
and the record sources its package version from the unclaimed read. The
counts are taken over the administration's labels after the claim, so a
second `promote` of the same cohort counts that cohort's rows rather
than re-claiming anything.

* `CT-STATS-05`: an administration that collected no blind labels reports
  `NO_NEW_VALIDATION_EVIDENCE` as a first-class value — and advances no
  agreement figure. The claimed rows still land (they are the
  administration's record), the counters still move, and the figure does
  not: nothing that cannot support a validity claim ever reaches one.
* `CT-STATS-06`: the three counters count separately — ``blind_count``
  the admissible population, ``operational_count`` the claimed labels
  that are not admissible, ``cohorts_used`` the administrations the
  record now speaks for. ``agreement_kappa`` is computed only when the
  administration's blind population is single-criterion; a
  multi-criterion one has per-criterion figures in
  ``weakest_per_population`` and no blended headline, because
  `CT-STATS-04` keeps that claim unrepresentable.

Rung 0 (no data directory — `build_stats`' shape) computes the same
counters over the in-memory population and writes nothing. Rung 2 claims
through the durable file `open_stats` created; an instance must have been
built by `open_stats` for the claim to have anything to claim.

Defined at module level and bound into ``ValidationStats`` below, the way
``agreement`` is.

### service.py: build_stats

The declared kwargs arrive as keywords — the scoring-models declaration
keys criteria to their declared scoring models, ``population_scopes=`` and
``backend_profiles=`` declare the populations and backends this
installation knows (which is what makes ``no_data_for_population`` and
``no_data_for_backend`` reachable rather than declarable,
`TC-STATS-C03`'s step 3), ``band_counts=`` declares the band count a
criterion's table carries (`TC-STATS-C21`'s disclosure), and
``administration_id=`` names the administration the figures speak for
(`CT-REVIEW-10`'s keying).

#117's members read three more: ``cohort_id=`` declares the cohort the
labels belong to (so a report naming a different cohort is refused),
``evaluation_modes=`` declares each criterion's mode — the declaration
`CT-DET-02` makes binding for a verdict distribution — and
``surface_correlations=``/``subgroup_correlations=`` are the measured
channels the proxy interpretation reads, declared by the caller exactly
as the MVVP's channels are (#116's pattern). #118's members read three
more: ``operational_weights=`` declares the operational-evidence weights
the signal reads (``None`` keeps the module's declared defaults),
``administrations=`` declares the administration history the blind-skip
alert reads, and ``narrative_metrics=`` declares the narrative-quality
channel's collected metrics — the channel is separate from criterion
agreement (`CT-STATS-14`), and it speaks only where the caller declares
it.
