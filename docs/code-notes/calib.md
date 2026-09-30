# `aeh.calib`: design notes

These notes were the docstring of `src/aeh/calib.py` before it was split into the `aeh/calib/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

M-CALIB — Rubric Calibration (§3.17): discovery and triage (#137), the
capped elicitation, the lock write-path and the history (#138), and the two
guardrail gates (#139).

Three stories have landed. The first (#137) is the half the design builds as a
guardrail before the feature it guards (`§3.17`'s phasing note): discovery of
where a rubric is ambiguous, and the triage that categorizes every disagreement
before anything is revised. The second (#138) is the half a teacher actually
meets: the elicitation that turns edit-eligible findings into at most
`CALIB_MAX_QUESTIONS` questions — ranked by how many submissions the ambiguity
affects — each carrying options and two examples, never a pre-authored edit;
the application of the teacher's answers as rubric clarifications written
**through `M-PKG`'s §6.2 lock**; the history that records every question,
option set, answer and resulting edit; and the skip path, which grades the
class against R₀ unchanged and is never on the critical path. The third
(#139) is the pair of guardrail gates between a proposed revision and a live
one (`§6.5`–`§6.7`): dual-scoring non-inferiority over the **full class**
against a threshold **declared before the comparison** — never a default —
and adversarial back-translation, in which a model *not in the scoring panel*
is asked to construct a student response on which R₀ and R₁ would assign
different scores, and a successful construction is evidence the construct
changed. Any gate failure reverts to R₀ rather than shipping with a warning:
`CalibrationRunOutcome.shipped_with_warning` and `GateResult.advisory_only`
are structurally False — the checkable statement of `CT-CALIB-02`, in the
same shape as `TriageVerdict`'s `fitted` — so the forbidden "warned revision"
is unconstructible on this surface rather than merely avoided.

**Ambiguity discovery, never a measurement of accuracy (`FR-CALIB-01`,
`CT-CALIB-03`).** `discover()` scores teacher-graded calibration samples under
R₀ — the rubric version the caller names, which is the package's current
delivered version before any edit — and reports where the teacher's band and
the panel's band differ, per criterion. The output is typed as ambiguity
discovery (`DiscoveryReport.kind`) and carries no field an accuracy figure
falls out of: no matched/total pair, no rate, no correctness count. The
teacher's labels are a second opinion, not a gold standard, and the
calibration set is far too small for an accuracy claim — the figures that
exist are `M-STATS`'s, computed over admissible blind labels (`CT-STATS-01`).

**The required triage category (`FR-CALIB-02`, `CT-CALIB-04`).** Every
disagreement carries a triage category — `rubric_ambiguity`,
`model_failure`, or `teacher_inconsistency` — as a *required* output field.
The requirement is enforced at the triage boundary, where it has teeth: a
`Disagreement` discovered with no category yet is exactly what discovery
emits (categorizing is the triage step's judgement, not discovery's guess),
and `triage()` refuses it with `TriageCategoryRequired`. An optional category
would default into *some* path, and the editable path is the dangerous
default — the refusal is what makes that unreachable. Past the boundary the
`TriageVerdict` always carries one, and a verdict without one is
unconstructible.

**Eligibility is structural, not policy (`FR-CALIB-02`).** Only
`rubric_ambiguity` is eligible to produce a proposed edit. That is not a
flag the module promises to respect — `edit_eligible` is derived from the
category inside the value, and `TriageVerdict.__post_init__` refuses the
construction of a non-`rubric_ambiguity` verdict carrying a `proposed_edit`,
so no caller, on any path, can attach one. Even a `rubric_ambiguity` verdict
carries `proposed_edit=None` at triage: the edit is generated from the
teacher's *answer* during elicitation (#138, `CT-CALIB-05`), never proposed
by the model.

**Teacher inconsistency is surfaced, never fitted to (`FR-CALIB-03`).** A
`teacher_inconsistency` verdict carries both examples side by side — the
teacher's own differing labels, as a two-slot pair. The constructor refuses a
one-example verdict, because one example is an accusation and two are a
comparison the teacher can resolve. Nothing on this surface generates an edit
from one: with the eligibility rule above, a `teacher_inconsistency` verdict
cannot carry a `proposed_edit` at all.

**A model failure routes to the pipeline, not the rubric (`FR-CALIB-04`).**
A `model_failure` verdict carries a `PipelineFinding` naming where the
model's failure lives — extraction, decomposition, or panel composition —
and no rubric edit (structurally, as above). The stage is the disagreement's
declared `pipeline_stage` when the caller carries that evidence; otherwise
the default is `panel_composition`, the surface a scored band disagreement
is observed on, disclosed as an interpretation on the PR.

**The four seams.** Headless: module-level `discover`/`triage`/`elicit`/
`apply_answers`/`run_for_assignment`/`non_inferiority`/`back_translate` return
structured values, no console on any path. Deterministic transport: the
scoring side of discovery arrives through injected channels — `model_bands`
(the recorded-transport form, pre-scored under R₀) or the `scorer` callable
(the injected scoring seam a test binds to `RecordedFixtureProvider`-backed
code and production binds to the panel) — so a calibration run needs no
network and no real upstream (`CT-PROV-10`), and the provider stays the only
egress point (`CT-PROV-15`). The gates ride the same seam: the full class's
dual-scored bands arrive as a registered roster (pre-scored under R₀ and R₁,
the same recorded-transport form), and the off-panel model's construction
attempts arrive as a bound session — a build with neither is *unavailable*,
never invented. Env-gated knobs, all read at call time: the aggregate
more-than-a-handful-of-ambiguities alert threshold
(`HARNESS_CALIB_AMBIGUITY_ALERT_AFTER`), the elicitation cap
(`HARNESS_CALIB_MAX_QUESTIONS`, `FR-CALIB-05` — the cap is the knob, because
teacher time is environment-shaped too), the standing threshold declaration's
env fallback (`HARNESS_CALIB_NONINFERIORITY_THRESHOLD`), the class-size
cap (`HARNESS_CALIB_CLASS_SIZE_CAP` — production default is **no cap**: the
gate scores the full class, `NFR-CALIB-02`, and a set cap refuses an
oversized class rather than silently scoring a subset), and the off-panel
checker this deployment names (`HARNESS_CALIB_OFF_PANEL_MODEL` — the gate
reads it when the caller passes no explicit checker; nothing declared is
the unavailable mode, never an invented adversary). Observability: the
report, the run outcome and each gate result carry what each stage did —
papers scored, criteria excluded as deterministic, unscored papers, per-stage
notes, the aggregate alert, the run's fairness note and revision trace, the
threshold's source and declared-at timestamp, the per-gate outcome and the
class shift distribution — never a bare status.

**The two gates (`FR-CALIB-08`/`-09`, `§6.5`/`§6.6`).** `non_inferiority`
compares the R₀ and R₁ dual scores the *full class* already carries and
rejects the revision when **more than** the threshold of the class shifted by
a full band — strictly more: exactly-at-threshold passes, because the
requirement says "more than". The threshold is never defaulted
(`CT-CALIB-13`: 0.10 is the HLD's *example*, not a validated value): an
explicit argument wins, then a standing institutional declaration made
through `declare_institutional_threshold` (or its env fallback), and with
neither the gate refuses with `ThresholdNotDeclared` — an unowned threshold
governing whether a rubric changes is the decision nobody made. The gate
refuses the calibration set itself (`InsufficientPopulation`: it "lacks the
sample size to mean anything", `NFR-CALIB-02`) and reports *where its
threshold came from* (`threshold_source`) and *when it was fixed relative to
the first result* (`threshold_declared_at` < `first_result_at`), so a
threshold chosen after the outcome shows up as one. `back_translate` asks a
model **off the panel** to construct a response on which R₀ and R₁ would
differ; a construction that succeeds rejects the revision outright — an
advisory note would be the warned revision renamed (`CT-CALIB-08`). The
off-panel build is refused at configuration time in `M-CONF` when it shares a
served build with the panel (`RunConfig.__post_init__`, `NFR-CALIB-04`), and
`back_translate` refuses it again at the gate, because two entries naming the
same build are the same model however they are labelled. Every failure mode
ends at R₀ (`CT-CALIB-02`): the gate outcomes and the run outcome carry the
revert as data, and `simulate_failure` drives each of the eight enumerated
modes through the module's real paths to the same terminal state.

**Version pinning (`FR-CALIB-10`/`-11`, `§6.7`, `CT-CALIB-09`).** A revision
that passed both gates is pinned with `pin_revision` — the package version,
the approver, and a timestamp — before anything consumes it, and consumers
keep R₀-scored and R₁-scored results out of one unannotated rollup (`M-GRADE`
and `M-STATS` carry their halves; this module mints the pin). The cost is
budgeted, not incurred (`NFR-CALIB-03`, `CT-CALIB-12`): `plan_dual_scoring`
discloses the call count — one additional full-class pass — *before*
authorization, `authorize` records the operator's approval, and
`run_dual_scoring` makes exactly the disclosed number of calls through the
injected provider.

**The store surface is `M-PKG`'s, exclusively.** Nothing here opens a store
on its own authority or carries a schema of its own: every question, answer
and resulting edit is recorded through `PackageCatalog.append_elicitation`
(`FR-CALIB-13`), and every rubric clarification lands through the same
catalog's revision flow — a new version created by `create_version`, edited
while unlocked, behind the §6.2 lock the catalog's `_guard` already enforces
(`FR-CALIB-07`; a second implementation of that lock is what would drift,
`CT-CALIB-06`). The append-only elicitation history's schema arrived with
`M-PKG`'s migration 5 (`FR-PKG-20`, `NFR-PKG-01`), so this story needs no
migration of its own and adds nothing to the store's census.

Interpretations this module records (each a place the design is silent and
this implementation chose; all reported on the PR):

* *Discovery emits uncategorized disagreements.* `FR-CALIB-02` says every
  disagreement *carries* a required category; §3.17's interface has `triage`
  as a separate step from `discover`. Read together: discovery identifies,
  triage categorizes, and the required-field refusal sits between them. A
  discovered disagreement that already carried a model-assigned category
  would be the module triaging its own failures — the fitting the clause
  exists to prevent, one step early.
* *The side-by-side pair is a structural two-slot surface.* `triage()`
  normalizes the teacher's repeat labels to exactly two example slots — the
  pair the teacher resolves (NFR-CALIB-01's "two student examples shown side
  by side"). A disagreement carrying more than two repeat labels displays
  its first two as the pair; one carrying none arrives as a pair with both
  slots unfilled (visible as None) rather than the surface pretending to be
  complete — the pair's length is structural, so a verdict constructed
  directly with anything but two slots is refused (`SideBySideRequired`), and
  the one-example shape is unconstructible by hand.
* *The default pipeline stage is where the failure is observed.* A scored
  band the teacher disagrees with is observed on the panel's composition of
  the verdict; extraction and decomposition failures are only visible when
  the caller declares them (`Disagreement.pipeline_stage`). The default
  names where the disagreement was *seen*, never guesses where it was
  *caused*.
* *The teacher's repeat-label spread is surfaced in the notes, not as a
  disagreement.* Where the teacher's own labels for one criterion differ
  across samples but the panel matched both, no teacher-vs-model disagreement
  exists to categorize — and inventing one to carry the finding would be a
  disagreement with no sides. The spread is disclosed per criterion in the
  report's notes as material for the triage conversation (`FR-CALIB-03`),
  never fitted to.
* *Answer-to-edit resolution is the teacher's words, not a vocabulary.*
  `apply_answers` reads the answer's first word as an intent — *broaden*,
  *narrow*, *keep as is* — and composes the clarified descriptor from the band's
  CURRENT text, never a replacement of it: broaden and narrow append the
  directional clause the answer chose to the descriptor as it stands (a revision
  that erased what the band means would be the edit destroying the thing it
  claims to clarify), the teacher's own words are appended as the clarification
  itself, and *keep as is* generates no edit at all — nothing lands, no version is
  minted, and the confirmation lives in the history row alone. There is no closed
  answer schema to reject against, because the question's options are a
  prompt to a person, not an API contract: a teacher who types a sentence
  is giving the clarification, and refusing it would send them back to the
  interface for no safety gain (the edit itself still goes through the
  catalog's guard).
* *A question's criterion is matched to the version being edited, with a
  positional fallback.* The session a question was asked under and the
  version an answer is applied against are different reads of the same
  package; when the question's `criterion_id` exists in the target
  version's criteria it is used, otherwise the question's position picks
  the criterion from the version's own ordering. The fallback exists because
  discovery and elicitation can run against different revisions of the same
  rubric without the ambiguity having moved; the ordering is the version's,
  not the session's — and the history row records the generic wording naming
  the criterion actually edited, so a stale session (elicited against a
  different package) can never leave a row whose question names a criterion
  the edit did not touch.
* *A pre-§6.2-lock vintage is declared, not inferred.* Whether a package
  version predates the schema lock is a property of when it was created —
  the lock's columns arrived in `M-PKG`'s migration 3 — and no inference
  from content could recover it. `package_version_predating_schema_lock()`
  is the declaration seam a caller (or a test) uses to name such a version;
  `apply_answers` refuses it with `PhaseDependencyError` rather than
  attempting an edit the vintage cannot carry (`CT-CALIB-15`).
* *A standing threshold declaration is consumed by the gate run it was
  declared for.* `declare_institutional_threshold` records a threshold with
  the moment it was fixed, and the next gate run that uses it consumes it —
  a fresh declaration per comparison is the strictest honest reading of
  "declared before the comparison" (`FR-CALIB-08`): a threshold that stood
  forever would let a comparison run months later under a number chosen for
  a different one, with nothing distinguishing that from a fresh decision.
  An explicit `threshold` argument is never consumed — it is the caller's
  declaration at the call itself.
* *A "shift" is any full-band difference, in either direction.*
  Non-inferiority asks whether the *instrument* moved, and a student whose
  band moved a full level under R₁ has been regraded in a teacher-recognizable
  sense whether the move was up or down; the clause reads "shifts", not
  "drops" (`FR-CALIB-08`). A paper shifts when any criterion's band differs
  between its R₀ and R₁ scores.
* *The gate consumes pre-scored rosters; the budgeted pass buys the R₁ half.*
  `non_inferiority` reads the class's dual-scored bands from the registered
  roster — the recorded-transport form, the same shape discovery's
  `model_bands` takes (`CT-PROV-10`) — so the gate is a comparison, not a
  scoring run. `run_dual_scoring` is the one additional full-class pass
  (`NFR-CALIB-03`) that drives the injected provider, and the R₁ scores it
  buys come back on the plan; joining them with R₀'s accumulated bands and
  registering the roster is the caller's act, and in this build the
  registration route is the test seam. #139 is the last module in build
  order, so there is no later story to land a production registration route
  in — the gap is recorded on the module's `type:test` issue.
* *A plan for an unregistered cohort is built on disclosed defaults.*
  `plan_dual_scoring` against a cohort the module has no roster for cannot
  know the class's shape, so it plans against the declared example class
  (`PLAN_DEFAULT_CLASS_SIZE`, `PLAN_DEFAULT_CRITERIA_COUNT`) and says so in
  the plan's notes — never silently: an estimated cost built on an unstated
  assumption is a budget that lies.
* *The structurally-False flags are the clause made checkable.*
  `CalibrationRunOutcome.shipped_with_warning` and
  `GateResult.advisory_only` are always False, exactly as
  `TriageVerdict.fitted` reads the one shape the constructor already refuses:
  `CT-CALIB-02` forbids the warned revision and `CT-CALIB-08` forbids the
  advisory outcome, so the fields exist to be asserted, and a code path that
  could set them cannot be written without making the assertion fail.
* *`simulate_failure` is the caller-side terminal-state policy, not an
  eighth failure path.* Each of `CT-CALIB-02`'s eight enumerated modes is
  driven through the module's real refusal paths — the gate's refusals, the
  triage boundary, the unbound off-panel transport — and the sweep asserts
  the *outcome shape* every failure resolves to: R₀ unchanged, the ambiguous
  criteria lower-confidence, no revision shipped, nothing shipped with a
  warning (`FR-CALIB-10`). The seam exists because the terminal state is a
  property of how callers resolve these failures, and the contract pins it.

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.calib`. Each section is named after the file and the function or class it describes.

### discovery.py: discover

The samples arrive as ``calibration_papers`` — the refs stored-not-used at
setup (`FR-SETUP-15`) — and the teacher's grades for them as
``teacher_bands`` (paper → criterion → band): the teacher's grades are the
*second opinion* the disagreement is measured against, never a gold
standard, and nothing here turns the comparison into one.

The panel's side is R₀-scoring, through one of two injected transports:

* ``model_bands`` — the panel's bands under R₀, already scored (paper →
  criterion → band). The recorded-transport form: a run that already
  scored the samples under the same rubric version hands its results over,
  and discovery compares without another model call.
* ``scorer`` — the scoring seam as a callable, ``(paper, criterion_id)``
  → band. A test binds a deterministic stub or `RecordedFixtureProvider`-
  backed code (the provider stays the only egress point, `CT-PROV-15`);
  production binds the panel. The calibration papers the teacher graded
  are the criteria the teacher graded — discovery scores those, so an
  unscored criterion is one the teacher never graded.

Both bound at once? The recorded bands win and the scorer stays
unexercised — one transport per run, and the run's notes name the ignored
one rather than dropping it silently.

The rubric version the caller names **is R₀** — the package's current
delivered version before any edit — and the report carries it as
``package_version``, so every disagreement names the instrument both sides
read. Reading a published version is what discovery does; revising one is
what only elicitation (#138) through `M-PKG`'s lock may do.

Deterministic criteria are not calibration subjects (#89's separation, the
same exclusion `FR-REVIEW-12` draws for the blind sample): a criterion
declared ``deterministic`` in ``evaluation_modes`` is kept out by name and
reported in ``deterministic_excluded`` — scoring an answer-key lookup
with a panel would be theatre, and disagreeing with an answer key is a
key error, not a rubric ambiguity.

The report is ambiguity discovery, never a measurement of accuracy
(`CT-CALIB-03`): it carries the disagreements, what each stage did, and
nothing an accuracy figure falls out of. Where nothing could be scored the
report says why in ``notes`` — a bare success over an empty result is the
silent-failure shape the four seams exist to prevent.

Raises on programming errors only: a non-string or empty
``package_version``, or an empty ``calibration_papers``, is a caller
defect and raises; a paper with no teacher bands is a finding's absence,
disclosed in the notes, never an exception.

### discovery.py: triage

The category is the disagreement's *required* field: one that arrives
without one is refused with `TriageCategoryRequired`, because an
uncategorized disagreement would default into some path and the editable
path is the dangerous default. A category outside the closed set of three
is a caller defect and raises.

What each category produces is the eligibility rule, structurally:

* ``rubric_ambiguity`` — the only edit-eligible verdict
  (`verdict.edit_eligible`). The edit itself does not exist yet: it is
  generated from the teacher's answer during elicitation (#138,
  `CT-CALIB-05`), so ``proposed_edit`` is None at triage even here.
* ``teacher_inconsistency`` — surfaced with both examples side by side
  (`FR-CALIB-03`): the teacher's repeat labels, normalized to the
  two-slot pair. Never fitted to — ``fitted`` reads False structurally,
  because the verdict constructor refuses an edit on this category.
* ``model_failure`` — produces a `PipelineFinding` naming the pipeline
  stage the failure lives in (`FR-CALIB-04`), and no rubric edit: the
  category is not edit-eligible, structurally.

The disagreement's ``pipeline_stage`` declares where a known model failure
lives when the caller has that evidence; without it the finding names
``panel_composition``, the surface a scored-band disagreement is observed
on — where it was *seen*, never a guess at where it was *caused*.
