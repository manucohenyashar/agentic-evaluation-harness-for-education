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
