# `aeh.setup`: design notes

These notes were the docstring of `src/aeh/setup.py` before it was split into the `aeh/setup/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

M-SETUP — Stage A: the question inventory proposal, the rubric read-back, the
decomposability classification, the dependency proposals, the answer keys, the grade
policy, the prefix budget, the two blocking gates, and publication
(#50, #51, #52, #53; design §3.6,
FR-SETUP-01/-02/-03/-04/-05/-06/-07/-08/-09/-10/-11/-12/-14/-15/-16,
NFR-SETUP-01/-02/-04).

Stage A runs ONCE per package version (`CT-SETUP-16`): the assessment document the
teacher ingested through `M-INGEST` is read (never re-ingested — `CT-SETUP-11`: setup
reads documents through `M-INGEST`'s store, not around it), a model proposes the
question inventory through `M-PROV`'s seam (`FR-PROV-13` names this module a prompt
builder; `HLD §7.8` Phase 1 is the proposal logic), the teacher confirms or corrects
it, and the confirmed question rows are written through `M-PKG` (`FR-PKG-03`) — where
the §6.2 lock engages at the confirmation (`FR-SETUP-02`), deliberately earlier than
publication. The confirmation IS the teacher's assertion about content; a lock that
engaged only at publish would leave a window where the instrument could drift after
the teacher signed it. After the gate, `read_back_rubric` (#51) reads the stored rubric
into criteria and even band sets whose descriptors state what a response DOES — a
descriptor carrying a magnitude phrase (`SETUP_MAGNITUDE_PHRASES`) or a bare numeral is
rejected and re-requested, never stored (`FR-SETUP-05`).

**The two blocking steps** (`CT-SETUP-01`, §4.2.1, `FR-CONSOLE-06`): exactly two setup
operations block — confirming the question inventory (S3) and setting the answer keys
(S4). `publish()` enforces both gates and is refused until they hold; publication is
the moment `M-PKG`'s version lock flips, which is the §6.2 lock taking effect
(`FR-SETUP-02`). Everything else in the design's setup sequence is skippable with a
recorded default, and the steps this story does not stage yet are enumerated by
`steps()` as present-and-unavailable, naming the story that stages them — the console
tells the teacher the truth about what remains (`NFR-SETUP-04`, `FR-CONSOLE-25`):

- rubric read-back: HERE since #51 — non-blocking (`FR-SETUP-04`: the met/not-met
  default a criterion without a band set takes is the recorded default, so the step can
  be deferred; the derived set is recorded as `derived_default`, not passed off as an
  explicit choice),
- decomposability and dependencies: HERE since #52 — the §5.3 decision table is the
  module's (`classify_decomposability` asks the model for the five ANSWERS, never a
  verdict; fail one question and the classification follows it, and an unclear answer
  defaults `holistic`, never `atomic` — NFR-SETUP-02, RISK-27). The confirmations the
  borderline criteria surface are capped at `SETUP_MAX_CONFIRMATIONS` by THIS module
  (`CT-SETUP-13`, headlessly — no console required), dependencies default to zero and
  are written only on explicit teacher approval (`FR-SETUP-10`), and every verdict —
  teacher-confirmed or taken as the module's default — is recorded through `M-PKG`
  (`R62`: M-CALIB and M-STATS can tell the two apart),
- grade policy and the prefix budget: HERE since #53 — `set_grade_policy` captures the
  teacher's declared policy or takes the default explicitly, and publication writes the
  default for a teacher who never spoke, recording which it was (`FR-SETUP-12`, R62);
  `check_prefix_budget` counts each (question, criterion) prefix against the configured
  ceiling and drops the lowest-value exemplars where it is over — never the reference
  solution, never the criterion text (`FR-SETUP-11`). #53 also completed S4's
  `FR-SETUP-03` semantics: the confirmed inventory's deterministic questions get their
  criteria staged (`CRIT-<question id>`, exactly the two bands correct/incorrect, never
  submitted to the §5.3 test — `CT-SETUP-07`), every key is validated against the
  question's own option vocabulary, and publication stays refused while any
  deterministic criterion is unkeyed. The calibration-paper intake (`FR-SETUP-15`)
  records what the teacher uploaded and that nothing was derived from it — ambiguity
  discovery waits for M-CALIB (the `TC-SETUP-18` intake test is deferred with it).

**State is the database, never memory** (`CT-SETUP-03`): a process that dies after the
proposal resumes by constructing a fresh `SetupService` over the same Tier P file and
calling `propose_inventory` again — the stored proposal comes back unchanged, and
`steps()` reports what remains. Nothing here holds in-memory state across calls.

The four seams, from the first commit:

1. **Headless driver** — `SetupService` runs the whole stage from code: structured
   results (`InventoryProposal`, `SetupProgress` with a per-step list), no console
   required (`CT-CONSOLE-01`).
2. **Deterministic transport** — every model call goes through the `InferenceProvider`
   seam (`CT-PROV-01`); tests script a double, production passes a real provider, and
   no other egress exists (`CT-PROV-15`).
3. **Env-gated knobs** — `HARNESS_SETUP_PROPOSAL_ATTEMPTS`,
   `HARNESS_SETUP_READBACK_ATTEMPTS`, `HARNESS_SETUP_CLASSIFY_ATTEMPTS` (the
   degraded-path attempt budgets), all read at CALL time per this codebase's knob
   doctrine. The prefix budget's ceiling is deliberately NOT one of them: it is
   `RunConfig.prefix_token_ceiling`, the per-profile value M-CONF derives
   (conf.py's recorded decision — a separate env key would permit `unified-large`
   with a ceiling of 500); this module's fallback for a service constructed
   without a resolved run config is documented at
   `SETUP_PREFIX_TOKEN_CEILING_DEFAULT`, and the exact token-counting seam is
   `TC-SETUP-14`'s deferred story.
4. **Stage-level observability** — `LOGGER` ("aeh.setup") logs every proposal attempt,
   confirmation, gate refusal and publication; the proposal row carries its attempt
   count and status, so a degraded proposal is visible in the database, not just the
   log.

Coverage note: the `TC-SETUP-*` cases (test plan §5.6) land with issue #54, the
co-evolution test story paired with this one.

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.setup`. Each section is named after the file and the function or class it describes.

### service.py: SetupService

`SetupService(catalog, ingestor, provider, model_ref)` — the Tier P catalog the
package lives in, the `M-INGEST` gateway the assessment is read through, and the
`M-PROV` seam the proposal call goes through. `params` defaults to
`SamplingParams(temperature=0.0)`: a proposal is a reading task, not a sampling
one.

Design §3.6's protocol, and what this story stages:

============================  =============================================
operation                     status
============================  =============================================
`propose_inventory`           here — one proposal per version (`CT-SETUP-16`)
`confirm_inventory`           here — BLOCKING gate 1; locks the rows
`read_back_rubric`            here — #51: criteria and even band sets, magnitude
                              descriptors rejected and re-requested; one read
                              back per version (`CT-SETUP-16`)
`set_answer_keys`             here — BLOCKING gate 2; the full FR-SETUP-03
                              semantics since #53 (the confirmed inventory's
                              deterministic criteria are staged, every key is
                              validated against its question's options)
`classify_decomposability`    here — #52: the §5.3 ANSWERS from the model, the
                              decision table from the module; confirmations
                              capped at `SETUP_MAX_CONFIRMATIONS` headlessly
`confirm_classifications`     here — #52: the teacher's confirmation recorded
                              apart from the module's default (`R62`)
`propose_dependencies`        here — #52: plain-language proposals, nothing
                              written; `confirm_dependencies` writes only on
                              explicit approval
`publish`                     here — refused until both gates hold; records
                              each skipped step's default (FR-SETUP-14)
`ensure_version`, `steps`,    here — the resume and console surfaces
`current_proposal`
`set_grade_policy`            here — #53: the declared policy, or the default
                              taken explicitly and recorded (FR-SETUP-12)
`check_prefix_budget`         here — #53: per-(question, criterion) counts,
                              lowest-value exemplar drops behind a calibration
                              floor (FR-SETUP-11)
`store_calibration_papers`    here — #53: stored-not-used intake; ambiguity
                              discovery waits for M-CALIB (FR-SETUP-15)
============================  =============================================

### method_drafts.py, general_derivation.py, evidence_sum.py: rubric methods (#624)

`FR-SETUP-18/-19`, `CT-SETUP-17`. Per criterion the teacher picks a method in teacher
language (`rubric_method_choices()`, `bands` the default). Both non-default flows keep the
teacher's work as a **pending setup step record** (`rubric_method.general:<id>`,
`rubric_method.evidence_sum:<id>`) and write criterion and band rows only on confirmation.
The reason is M-PKG's draft surface: `remove_criterion` is a guard-only stub, bands cannot
be deleted, and `band_count` cannot be changed — so rows staged before confirmation would be
stranded by an edit that changes the band count, or by the teacher switching method (which
marks the other method's pending record `superseded`).

- `general`: the setup model derives a band set from the teacher's prose
  (`HARNESS_SETUP_DERIVATION_ATTEMPTS`, default 3). The numeral/magnitude scan runs on the
  derivation output (`RISK-112`); a failing reply is re-requested, and past the budget the
  derivation is refused, never staged. Showing a card spends one of the six optional
  confirmations (Q-O4), once per criterion. On confirmation (as derived, or edited) the
  criterion is written with `score_method='general'`, its bands, and M-PKG's derivation
  provenance — recorded with the CONFIRMED set, because M-PKG's publish check requires the
  stored bands to equal the recorded derivation; the model's original derivation stays in
  the step record's payload (`derived_bands`).
- `evidence_sum`: deterministic, no model call. Each named aspect becomes a 2-band aspect
  criterion (`<id>-a<n>`), descriptors derived from the aspect name; more than two levels →
  a promotion proposal (`score_method='bands'`), never a wider aspect. The composite carries
  no bands, no key and no evidence type (publish's `FR-SETUP-09` check exempts it).
- The gate: publish refuses, naming every criterion whose record is still `pending`, and
  `steps().ready_to_publish` is False while one is.

Ordering caveat: `read_back_rubric` refuses a draft that already carries criteria it did not
stage, so method criteria are confirmed after the read back.

`withdraw_rubric_method(id)` marks either pending record superseded, so a teacher who chose
`general` or a checklist and then prefers per-band descriptions is not held at the gate.
Known limit: confirmation writes its rows through M-PKG's per-call transactions (there is no
batch write for a method criterion), so a store failure mid-confirmation can leave a partial
criterion that M-PKG cannot remove; the checks run before the first write to make a rule
failure there impossible.
