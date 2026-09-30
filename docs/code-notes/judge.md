# `aeh.judge`: design notes

These notes were the docstring of `src/aeh/judge.py` before it was split into the `aeh/judge/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-JUDGE` (#78, #79, #80) — judgment isolation: the whitelist request schema, the
fresh context, the version-pinned prompt template, and the response contract with the
verdict row it persists.

Design §3.10 pins the *shapes* — a `ScoringWorker` whose `assemble(unit)` is pure, a
`ScoringRequest` that is a **whitelist** (no field capable of carrying another judge's
verdict, a prior cohort, a student identity or any running score), and a prompt whose
submission arrives LAST inside the single delimited untrusted block. It pins no Python
names; the assumed surface lives in `tests/support/judge_vocabulary.py` and this module
implements it (`WORKER`, `REQUEST_TYPE`, `ISOLATED_CHECK`, `VIOLATION`,
`PROMPT_FIELDS`, `TEMPLATE_VERSION`). #79's half — the template CONTENT (`#79` owns
`FR-JUDGE-03/04/06/07`: the numeral prohibition, band presentation, exemplar order,
prefix invariance) and the `assemble_prompt` id-keyed door — lands here with the
version pin the templates render by.

**Exactly one criterion, exactly one submission, one fresh context.** Every scoring
request carries exactly one criterion and one submission, validated against the
whitelist schema (`FR-JUDGE-02`), built from nothing but the unit and the store's
rubric — no conversation history, no accumulated summary, no prior-judgment state
anywhere to carry (`FR-JUDGE-05`). There is no top-level `criterion_id` /
`submission_id` field to overload: the ids live **nested** on their views, so a caller
who tries to slip a second id into a request hits a closed schema (`TypeError`) —
TC-JUDGE-03's four rejections arriving structurally rather than by rule.

**The whitelist.** `ScoringRequest` is a frozen dataclass whose nested views carry only
the fields HLD §9.9 declares: the criterion with its bands as **names, ordinals and
descriptors — no points** (`FR-JUDGE-03`; a band's points column never leaves the
package tier), the question's prompt and reference solution, the criterion's own
extracted evidence, the parents' extracted **spans** (`dependency_evidence` — spans
only, so a parent verdict is not merely absent but unrepresentable, `FR-JUDGE-14`), and
the submission's ref and text. No field name carries a contaminating stem
(`_PROHIBITED_STEMS`); `assert_isolated` is the machine-checkable form of §7.2 Rule 1
over an assembled request, and construction itself refuses anything the whitelist has
no field for.

**Pseudonymization at assembly (§3.2).** The unit carries `student_name` on purpose
(the ledger never does), and the assembler's job is to drop it: every occurrence of the
name in submission-derived text is replaced with the unit's `student_ref` before the
request exists. Design §3.2 rejects redaction of the student's prose — the judge needs
the words — so the text travels verbatim apart from the name; a store-backed assembly
resolves the canonical document, which never held a name in the first place.

**The four seams.** Headless: `dispatch` returns a structured `ScoringResult` (band,
ordinal, confidence, cited spans, the resolved build, attempts, a stage note) — no
console anywhere. Transport: the provider arrives by injection and
`RecordedFixtureProvider` remains the only egress (the sampling parameters are
temperature-zero by default — judgment is a temperature-zero task — and the fixture key
is the render itself, so a knob change that would move a backend's answer moves the
key: a fixture recorded against an old render misses rather than mis-replays).
Knobs: the retry budget is `HARNESS_JUDGE_MAX_ATTEMPTS`, the sampling temperature
`HARNESS_JUDGE_TEMPERATURE`, the output cap `HARNESS_JUDGE_MAX_OUTPUT_TOKENS`, the
exemplar-order salt `HARNESS_JUDGE_EXEMPLAR_SEED` and the assessment re-request
budget `HARNESS_JUDGE_ASSESSMENT_RETRIES` — all read at call time.
Observability: the result carries what the stage did next to its outcome — attempts,
the resolved build, the uncited marking (`FR-JUDGE-12`), the integrity flags
(`FR-JUDGE-10`'s accepted-after-amendment mark), a note when a refusal
happened, and the invariant prefix's byte share of the payload (`CT-JUDGE-13`'s
throughput observable, in bytes — the tokenizer is the provider's, the byte split is
the transport-neutral form of the same invariant).

**The response contract (#80).** The reply is accepted only in its declared field
order — `REPLY_FIELDS` is the contract, a re-ordered reply is REJECTED as a contract
violation and never reordered and accepted (`FR-JUDGE-09`, `CT-JUDGE-05`: the order is
the mitigation, so repairing it would remove the thing being tested) — and the order
is the commitment device: a judge must place `cited_spans` and the evidence inventory
BEFORE it may name a band. `evidence_assessment` is validated as an inventory
referencing spans or band conditions: a reply whose assessment is magnitude-only
prose (`SETUP_MAGNITUDE_PHRASES`' vocabulary, M-SETUP's configured bar, with no span
or band-condition reference) is refused as `ProseAssessmentError` and re-requested
ONCE with an AMENDED prompt — the same render plus a static ground-rules correction
inserted before the submission field, a different fully-assembled request and so a
legal new call rather than a re-sampled verdict (`FR-PROV-06`, `CT-PROV-05`'s fixture
key moves with the payload) — and an acceptance after that re-request carries the
`ASSESSMENT_AMENDED` integrity flag. A refusal that survives the amendment budget is
an ordinary strike toward `HARNESS_JUDGE_MAX_ATTEMPTS`; exhaustion raises
`JudgmentError` and the upstream orchestrator quarantines the unit (`NFR-JUDGE-05`) —
never a fallback band, never a default verdict. What a LEGAL reply produced is
persisted in the verdict row: the band, its ordinal in the declared set, the judge's
own confidence, the cited-span inventory as JSON (`NULL` when the reply cited
nothing — persisted as uncited and MARKED, so M-AGG downgrades confidence rather
than discarding, `FR-JUDGE-12`/`CT-JUDGE-06`: a discarded verdict would turn a
three-judge panel into two, which `FR-AGG-03` forbids), the sufficiency answer and
the uncited mark; the row writes no value from the package's points scale, and the
table has no column for one (`FR-JUDGE-11`). `self_confidence` is persisted and
exposed as one weighted input among the observable ones; nothing in this module lets
it alone determine routing (`FR-JUDGE-13`, R22 — #93's `should_escalate` is the
consumer that holds it).

**The template (#79).** `JUDGE_PROMPT_TEMPLATE_V` pins the render; the run's
`prompt_template_v` (panel configuration) is the CALLER's declared value of that
version and is already an input to `work_id` (`FR-ORCH-01`, M-ORCH's formula), so a
template change invalidates dependent work through the id — this module's constant is
what the render is actually built from, and the fixture contract keys on it. The
rendered field order is `PROMPT_FIELD_NAMES` (`FR-JUDGE-07`'s template lint): invariant
elements first (directive, criterion, the band set, the question, the exemplars), then
the static evidence ground rules, then the submission LAST inside the single escaped
untrusted block — per-submission material (the extracted spans, the submission's words)
renders ONLY in that final field, which is what keeps the invariant prefix
byte-identical across a (judge, question, criterion) batch (`FR-JUDGE-06`, NFR-JUDGE-02:
the prefix is simultaneously the fairness guarantee and the shared cache body).

**Injection resistance (#81, `FR-JUDGE-17`).** Three defences compose, and the demarcation
is the FIRST of them, not the only one. (1) **Demarcation**: the submission AND its
extracted evidence render inside the single delimited untrusted block, placed LAST, with
every interior delimiter escaped (`_render_submission`) — and the version-pinned
directive field NAMES the block untrusted data to be graded against the criterion and
instructs the judge to disregard any instruction, role claim or scoring directive it
contains (`_DIRECTIVE`): a payload inside the block is inert because the prompt that
surrounds it pre-declares it inert. (2) **The declared band set**: a reply's band is
accepted only from the criterion's declared set (`_verdict_of`), so a band-forcing
directive can only ever produce a declared band (`CT-JUDGE-04`). (3) **Evidence
grounding**: a reply that cites spans has those citations verified byte-exactly against
the CANONICAL document (`aeh.integ.verify_span`, composed at `dispatch`) before the
verdict can exist — a forged citation (text the document never carried, offsets the
document does not hold) fails verification and the reply is refused like any other
malformed response, struck within the budget, never persisted. The gate is vacuous for
an uncited reply, and it is FAIL-CLOSED at both ends: a document that cannot be resolved
to bytes makes every citation unverifiable, and `verify_span` itself never raises. The
composition's disposition is the issue's: an injected submission is INERT (the payload is
graded as work, never obeyed) or ROUTED (the reply that obeyed it is refused,
`JudgmentError` raised at budget exhaustion, the upstream orchestrator quarantines the
unit) — never obeyed, and never a confidence lift: a refused reply produces no verdict
row, so no confidence exists to rise above M-AGG's auto-accept threshold (`FR-AGG-05`
never sees a manipulation-born verdict at all). Citations verify against the canonical
document bytes, never the pseudonymized request text (§3.2's assembly replaces names in
the transported copy; the extracted spans' offsets are the canonical document's).

**Disclosed interpretations** (design agrees on the shape, this module fixes the
reading):
- `assemble(unit, *, store=None)` is BOTH the design's pure method and the contract
  door: a shipped `WorkUnit` (or a partial arm row, as the consumer contract cases
  drive) comes in, a `ScoringRequest` comes out. The store-resolving word fetch (a
  leased unit carries `submission_text=None`) is the `store=` keyword's — the
  `M-EXTRACT` disclosure verbatim. With NO store, the door still assembles: it builds
  the request from what the unit (or arm row) carries — the rung-0 purity bet is that
  assembly needs no store, and the contract door's arms are rows stripped to identity,
  so the rubric views stay empty there. TC-EXTRACT-C15's span-text sweep stays
  registered behind its consumers (#73/#74/#97).
- Rubric resolution (`CriterionView.text`, bands, exemplars, the question) walks the
  run's package version through the shipped `PackageCatalog`, built with the store's
  blob store attached so exemplar material resolves (`blob_text` — the read the
  prefix budget's own docstring anticipates). The criterion rows carry no prose, so
  the wording is the question's `prompt_text`.
- **Band presentation** (`FR-JUDGE-04`): the declared set renders in its OWN field as
  ordered `{band}: {descriptor}` pairs in ordinal order — the order is the list's, no
  digit ordinals are rendered (a numeral in a rubric surface is exactly what the
  prohibition's scan refuses, so the template does not put one there), and a band's
  points render nowhere (`FR-JUDGE-03`). The bands field is CONDITIONAL: it renders
  exactly when the criterion declares a set. Disclosed reason: an empty set has
  nothing to present, and an always-on band-named field would put a band-named field
  into renders that carry no rubric at all — the pure contract door's renders are
  stem-scanned by the landed escalation case (`test_scoring_isolation.py`'s variant
  refuses a `band`-named field in a render that could carry a first verdict).
- **Exemplar order** (`FR-JUDGE-08`): exemplars ride on the criterion view, ordered by
  a seeded permutation keyed on (question, criterion) and the
  `HARNESS_JUDGE_EXEMPLAR_SEED` salt — fixed within a (question, criterion) batch
  (the invariant prefix's exemplar bytes are one value across the batch), differing
  across batches, reproducible for fixture recording (the salt is an env knob read at
  call time, not a clock read; `assemble` stays pure). The catalog's exemplar-id
  order is the permutation's base, so an unset salt is still deterministic.
- **The numeral prohibition's scope** (`FR-JUDGE-03`): the acceptance form is a scan
  over the RENDERED prompt, classifying fields by name — rubric surfaces (the
  criterion and bands fields) refuse ANY standalone numeral; content surfaces (the
  exemplar material, the untrusted submission block) refuse only numerals beside mark
  vocabulary, so the student's own "12 kg" survives and "worth 4 out of 4" is caught
  (`TC-PKG-09`'s boundary, mirrored verbatim at the prompt-side scan site). This
  module ships no third copy of the scan: it renders faithfully — points nowhere, no
  digit ordinals in the band field — so the two scan sites (the package tier's and
  the TS-30 suite's, one boundary stated in both) can catch a planted violation. A
  render-time refusal would make the oracle unable to fire on the very cells the
  variants plant, which is the decoration failure the block form names.
- `assemble_prompt(submission_id, criterion_id, *, rerun=False)` is the rerun-review
  door (`CT-REVIEW-14`'s judge half): the prompt a re-run of one (submission,
  criterion) unit assembles, keyed on ids alone. It renders the SAME fresh-context
  template over an empty rubric view — the pure door's shape — and the `rerun` flag
  changes no bytes: `FR-REVIEW-17`'s guarantee is structural (the whitelist schema has
  no field a teacher's label could ride, and the render carries no ids either). The
  store-backed resolution of a historical unit joins with M-REVIEW's wiring (#108/#109).
- Pseudonymization happens HERE, at assembly (§3.2): the roster name on the unit is
  replaced with the ref inside the submission text, so a payload that could leak is
  never assembled. Name-free text travels verbatim — the judge needs the words.
- The dependency channel (`FR-JUDGE-14`) is spans-only **and** store-read: parents
  come from the package's dependency graph, their evidence rows from the same
  judgeless triple keying `M-EXTRACT` wrote. A parent with no evidence row contributes
  no entry — the orchestrator's topological order and extraction gate are what
  guarantee the row exists (CT-ORCH-05); this module refuses nothing it cannot see.
- `persist(unit, result)` writes ONE `verdict` row — `verdict_id = work_id`, idempotent
  under `INSERT OR IGNORE` — carrying the band, its ordinal, the confidence, the
  cited-span inventory (JSON; `NULL` when uncited, with the mark set), the sufficiency
  answer and the uncited mark, and nothing else — and the arm's done transition in the
  same guarded transaction (the `M-EXTRACT` at-least-once shape). No criterion_score,
  evidence, narrative or package write exists in this module (CT-JUDGE-12); no points
  value is written anywhere (FR-JUDGE-11).
