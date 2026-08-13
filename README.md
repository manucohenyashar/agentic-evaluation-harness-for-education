# Agentic Evaluation Harness for Education

A teacher-facing grading system that runs **open-weight models** — locally on a single
machine in a disconnected school, or hosted through OpenRouter — and returns per-student,
evidence-grounded feedback plus a class-level diagnostic view, for classes of **150 to 350
students**.

The full design is [`docs/agentic-evaluation-harness-for-education.md`](docs/agentic-evaluation-harness-for-education.md)
(v2.7, ~2,500 lines). This README summarizes what the system is, then documents how this
repository is built.

## The problem

Feedback is one of the highest-leverage things a teacher does, and the first thing that
disappears under load. A set of 250 constructed responses, at four minutes each for a
genuine read and comment, is over sixteen hours of work — for one assessment, for one class.
No teacher does this, and the adaptations are both damaging:

1. The work gets collected, spot-checked, and returned with a mark that carries little
   information, too late to connect to anything.
2. **The assessment format degrades to whatever is mechanically gradeable.** Constructed
   responses, worked problems, and lab writeups get replaced by multiple choice, because
   multiple choice is the only thing gradeable at n=350.

The second is the serious one and the less visible one: in these classrooms the work that
develops reasoning is often *not assigned at all*, and the resulting outcomes look like a
teaching-quality problem when they are a throughput problem.

So the benchmark is not "as accurate as a teacher grading carefully." At 250 students the
counterfactual is no substantive feedback at all. **The system competes with a blank.** That
reframing raises the value without lowering the bar — a bad score still lands on a real
student's record, and a teacher who catches the system being wrong twice will correctly
abandon it.

The target deployments are teacher-development and curriculum programs in settings like
Nigeria and India, where the constraint isn't teacher capability but time, class size, and
infrastructure.

## What makes it hard

Each constraint eliminates an architecture that would otherwise be obvious:

| Constraint | What it rules out |
|---|---|
| **Scale**: ~23,000 model calls per assessment per class | Anything validated at 30 students; a uniform 3-judge panel becomes the dominant cost |
| **Connectivity is intermittent**, hours to days | A design that *only* reaches a remote service. The offline profile must run with the cable unplugged |
| **One machine, not a cluster** | Horizontal scale-out in the edge profile |
| **Per-token cost isn't a rounding error** at 23k calls | Frontier APIs as the economics of "use it more" |
| **Student work shouldn't leave the school** | Cloud-only designs that solve privacy contractually rather than architecturally |
| **Teacher review time doesn't scale with class size** | Any policy routing a fixed *percentage* to review — 15% of 350 is ~790 items, a second full-time job |

Those constraints force open-weight models a single machine can hold, which are meaningfully
weaker than frontier models at holistic judgment. Hence the central engineering problem:

> **How do you get evaluation results trustworthy enough to inform real grades, using models
> substantially weaker than the frontier, on one machine, with no network?**

## How the design answers it

**Architecture substitutes for model scale.** Every decision is the same move: take work a
frontier model would do implicitly inside one large judgment, and make it explicit, narrow,
and verifiable. The research basis is that decomposition helps *smaller* models most — the
gap to frontier narrows when an 8B model is asked to do a narrow, well-specified thing
rather than a broad holistic one.

- **Extraction before scoring.** Localize the rubric-relevant evidence spans first, then
  score against them.
- **One criterion per judgment**, from fresh context. No prior verdict, prior student, or
  conversation history crosses the isolation boundary.
- **Evidence citation is mandatory** and verified against the source bytes.
- **A panel of diverse model families** instead of one bigger judge, so biases don't
  correlate.
- **Confidence routing** so the system's uncertainty is visible rather than hidden inside a
  confident-looking number.
- **Chance-corrected statistics only.** Raw agreement overstates by 33–41 points; a judge
  advertising 85% agreement is really operating near κ = 0.48.
- **Judges answer in words, not numbers.** Each criterion offers a small, even-numbered set
  of bands, each describing what a response *does* ("states the conclusion and cites the
  mechanism; does not address the boundary case"). Points are derived afterwards, and no
  numeric scale is ever visible to a judge. Asking "how good is this out of 5?" invites the
  centre; asking "which of these is true?" is checkable against the cited evidence.

Four failure modes the design specifically defends against, all of which are invisible to
the metrics a naive system reports about itself:

- **Common-mode extraction failure** — judges are independent of each other but all consume
  one extractor's output, so an extraction error produces *unanimous* agreement and raises
  confidence. The system would be most certain exactly when systematically wrong. Confidence
  therefore **inverts** on evidence-integrity failures.
- **Construct drift** — a rubric tuned to match a teacher's numbers can quietly become a
  length detector, improving measured agreement while degrading what's being measured. Every
  rubric revision passes a dual-scoring non-inferiority gate, and the teacher authors the
  change.
- **Score compression** — raters, human and model alike, avoid the ends of a numeric scale
  and drift toward the middle. Judges that compress do it *together*, so inter-judge
  agreement rises and confidence rises with it, while the scores quietly stop
  discriminating. Defended structurally by the band scale above, since a compressed panel
  looks excellent on every metric the system reports about itself.
- **The wrong-test submission** — an answer sheet handed in against the wrong paper. Every
  criterion legitimately finds no evidence, the panel unanimously scores zero, and the
  confidence inversion above does *not* fire because the evidence isn't corrupt, it's
  genuinely absent. A student who did the work correctly gets a confident, high-agreement
  zero. Caught at ingest by a validation ladder, because nothing downstream can catch it.

### How we deal with bias

Bias is the main thing that can go wrong here, and it has one nasty property that shapes
our whole approach: **when this system goes wrong, its own quality scores go up, not
down.**

That sounds odd, so it's worth seeing why. Suppose all three grading models start playing
it safe and giving everything a middling mark. They're now all doing the same thing — so
they *agree with each other*, and "the graders agree" is exactly what we measure to decide
whether to trust them. The score on our dashboard improves while the grading gets worse.
The same thing happens if the models are accidentally shown each other's opinions, or if
they're all fed the same faulty reading of a student's paper, or if a teacher gets into
the habit of clicking "accept" without really looking. Every one of these makes us look
*more* reliable, not less.

So we can't simply ship it and watch the numbers. Waiting for the numbers to drop would
mean waiting forever. Instead we do three things:

- **Build the problem out, rather than asking the models to behave.** Wherever we can, we
  make a bias physically impossible instead of writing a rule against it. The graders are
  never shown a 0–10 scale, so there's no middle of the scale to drift toward — they pick
  a written description of what the answer actually does. They're never shown each other's
  marks, because there's nowhere in the system to put them. A rule can be broken; a
  missing option can't.
- **Check our work with a ruler the bias can't bend.** We only measure accuracy against a
  small sample the teacher grades *without seeing what the system said* — because if they
  can see it, we're measuring agreement with the machine rather than correctness. Any
  rubric change is checked by a separate model that isn't part of the grading panel, so it
  doesn't share the same blind spots. And a system that says "I'm confident" doesn't get
  believed on its own word; we look at whether the graders actually agreed and whether the
  evidence held up.
- **When in doubt, ask the teacher — and say so.** The system is built to make its
  uncertainty visible rather than hide it behind a confident number. Where a shortcut
  would let it look more certain, it's deliberately built to do the opposite: if all the
  graders agree but the underlying evidence failed our checks, that counts as *low*
  confidence, not high, because unanimous agreement about the wrong thing is the most
  dangerous output we can produce. Anything not reviewed in time stays clearly marked as
  unreviewed rather than quietly becoming final.

We don't claim to have removed bias. The design names what's left — including the parts we
can only partly defend, like scanning quality that's worse for students with messier
handwriting. Being specific about what we haven't solved is part of the approach, not a
footnote to it: a grading system claiming to be bias-free is making exactly the kind of
overconfident claim we built all this to avoid.

## Reference architecture

```
  Teacher inputs:  assignment · reference solution · rubric R0 · student submissions
        │
  A  INGESTION & RUBRIC DECOMPOSITION
        ALL PDFs (mostly handwritten) → vision model → one canonical Markdown artifact
        evaluation only ever sees Markdown; no PDF reaches any stage below this one
        several PDFs assemble deterministically; artifact is immutable + content-hashed
        validation ladder: file integrity · missing pages · structure · student identity
                           · does this submission even belong to this test?
        rubric → atomic criteria, evidence type per criterion
        schema lock: weights + criterion count immutable downstream
        │
  B  AMBIGUITY DISCOVERY  (optional, skippable)
        finds underspecified criteria — does NOT validate
        triage → elicit (≤6 questions, teacher authors the answer) → guardrail gate
        │
  C  SCORING — two sweeps around an on-disk working store
        sweep 1  extraction, batched by (question, criterion), topological order
                 ↓  EVIDENCE INTEGRITY GATE — span offsets verified; empty ≠ zero
        ══════   JUDGMENT ISOLATION BOUNDARY   ═══════════════════════════
        sweep 2  scoring: one criterion × one judge × one submission, fresh context
                 judge → question → criterion → parallel over submissions
                 aggregation + inter-judge agreement → read-only synthesis
        │
     CONFIDENCE ROUTING   high → auto-score   low → teacher queue   + random spot-check
        │
  D  TEACHER REVIEW  ← the system's primary validation instrument
        narrative feedback first, score secondary and adjustable, evidence citations
        every accept/edit/override logged as a labeled datapoint
        │
  E  CLASS ROLLUP  per-criterion distributions, misconception clusters, honest statistics
        │
     LONGITUDINAL VALIDATION STORE — agreement statistics compound across administrations
```

Stage D is the load-bearing one and is not a stopgap to be automated away: it is what the
research says makes the system trustworthy, *and* it is the only source of ground truth the
system has. Teacher acceptance and blind teacher scoring are stored as different label types,
because acceptance drifts toward rubber-stamping as the system improves.

Supporting all of it is a persistence layer whose governing rule is one-way: **the
orchestrator reads memory and the judges never do.** A store a judge could query at inference
time would reopen every contamination path the isolation boundary closes. Runs are resumable
at (judge, question, criterion) granularity, because a 350-student run takes hours and
restarting from zero is unacceptable.

A tuned assessment persists as a portable **Assessment Package** — test, calibrated rubric,
exemplars, panel config, and cumulative validation record in one file that travels between
schools on a USB stick and appreciates with each use.

## Deployment profiles

The same code path, selected by configuration. The backend is fixed before a run starts and
never changes mid-run — a run scored partly by a local 4-bit quantization and partly by a
hosted build is a run whose statistics mean nothing.

| Profile | Runs on | Inference | For |
|---|---|---|---|
| `edge-local` | One machine at the school | Local server (MLX / vLLM-MLX / Ollama) | The disconnected-school deployment |
| `cloud-hosted` | Container in a datacenter | **OpenRouter**, same open-weight families | Connected schools, districts, programs without capital budget |
| `dev-ci` | Linux container on a Windows host | **OpenRouter** | Development and automated tests |

Development and CI run entirely on OpenRouter, which has a consequence the design states
explicitly: the **local** path becomes the least-exercised one, and it's the path deployed to
schools with no IT support. A green CI pipeline is no evidence that an overnight batch
completes on a 32GB Mac. Two gates close that: a hardware acceptance test that only an
edge-profile run can satisfy, and a backend conformance suite that runs frozen fixtures
through both backends and reports where they diverge.

---

# Building it: the Claude Code harness

A `.claude/` + `.github/workflows/` setup that turns the design document above into a
detailed design, a test plan, and a dependency graph of GitHub issues, then works through
that graph automatically: dependencies gate what's allowed to start, independent branches
(including the whole test track) run in parallel, and every issue goes through plan mode →
implement → verify → adversarial review → PR. Every piece is a documented Claude Code or
GitHub Actions feature — nothing here is a separate framework to trust.

## The pipeline

Four stages, each owned by exactly one skill. Single ownership is the point: it is what
stops two skills producing the same artifact in two incompatible shapes.

```
  HLD / architecture doc
        │  /detailed-design-generator
        ▼
  docs/design/detailed-design.md          ← owns modules + FR-*/NFR-* IDs
        │  /create-test-plan docs/design/
        ▼
  docs/design/test-plan.md                ← owns TC-* IDs, risk register, test-story sizing
        │  /plan-to-issues docs/design/
        ▼
  GitHub issues (type:story | type:test)  ← owns issue numbers + the dependency graph
        │
        ├── /fix-issue N    (type:story) → implementation PR
        └── /write-tests N  (type:test)  → test-code PR
```

### Single ownership, and why it's enforced

| Artifact | Sole owner | Everyone else |
|---|---|---|
| `FR-*` / `NFR-*` requirement IDs | `/detailed-design-generator` | References them; never invents one |
| `TC-*` IDs, risk register, test strategy | `/create-test-plan` | References them |
| Story sizing and dependency order | `/create-test-plan` §8.2 + the design's module graph | `/plan-to-issues` transcribes, doesn't re-partition |
| GitHub issues | `/plan-to-issues` | No other skill runs `gh issue create` |
| **Test code** | `/write-tests` | `/fix-issue` doesn't author test files (one exception) |
| Implementation code | `/fix-issue` | `/write-tests` doesn't implement production code |

This is a correction, not a style preference. An earlier version had
`detailed-design-generator` produce a test plan *and* a story backlog, which `/plan-to-issues`
then re-derived from prose — so one design yielded two incompatible backlogs with different
IDs and granularity, and the second silently discarded the first. Two owners of one artifact
is how a traceability chain breaks.

### The test-authorship boundary

The rule most often violated in good faith, because both implementation skills have a
plausible reason to write a test. Getting it wrong yields two suites for one requirement, in
two styles, asserting slightly different things.

- Every `FR-*` has `TC-*` cases in the test plan, which become a `type:test` issue.
  **`/write-tests` implements them; `/fix-issue` does not.**
- `/fix-issue` verifies by running the suite, including tests from the paired test issue if
  it has landed. If it hasn't, the story's acceptance criteria are the gate and the PR says
  so — rather than letting "the suite is green" stand in for "this works" when the suite
  doesn't test it.
- **The one exception:** a defect fix with no existing `TC-*` coverage. `/fix-issue` writes
  the regression test inline — that's what a regression test *is* — and adds the case to
  `test-plan.md` in the same PR, so the plan stays the map of what's tested.

### Traceability

The chain `FR-* → TC-* → issue #N → PR` is the actual product. Two checks keep it honest,
both exit non-zero on a gap:

```bash
python .claude/skills/create-test-plan/scripts/check_traceability.py --design docs/design/detailed-design.md --plan docs/design/test-plan.md
./scripts/trace-issues.sh docs/design/
```

The first proves every requirement has test cases. The second proves the IDs survived the
translation into GitHub — without it the chain silently ends at the issue boundary, which is
exactly where work gets dropped.

What carries the IDs across that boundary is the issue body contract, written by
`/plan-to-issues` from `.claude/skills/plan-to-issues/references/issue-templates.md`. Every
issue has:

- **Goal** — one checkable sentence; what the PR is judged against, by a human and by the
  `reviewer` subagent
- **Traces to** — the `FR-*` / `TC-*` IDs, listed explicitly (no `..` ranges — `trace-issues.sh`
  matches literally)
- **Acceptance criteria** in Given/When/Then, including at least one failure path
- **Technical notes** — the actual interfaces and data structures restated, not a pointer
  back to the design doc
- **Evaluation strategy** and **Definition of done**
- **Depends on: #12, #34** when it has dependencies, in exactly that form
- On test issues, **Written ahead of implementation: yes/no** — which tells `/write-tests`
  whether a red suite is expected or a bug. Never left to be inferred.

### Where the rules live

`CLAUDE.md` carries only the subset that has to be in context on every request — ownership,
the test boundary, the `Depends on:` form, and the working rules — because it is prepended
to every call whether or not the pipeline is involved. Everything explanatory lives here,
and the per-stage detail lives in each skill, loaded when that skill runs. If you're adding
guidance, put it in the skill that needs it; add to `CLAUDE.md` only when it must hold for
ad-hoc work where no skill is running.

## What's in here

| File | Purpose |
|---|---|
| `CLAUDE.md` | The pipeline, ownership rules, and issue conventions Claude reads every session |
| `.claude/settings.json` | Test command, advisor model, Stop hook wiring |
| `.claude/hooks/verify.sh` | Stop hook: blocks ending a turn on unverified changes |
| `.claude/skills/detailed-design-generator/` | Stage 1 — HLD → detailed design (`FR-*`/`NFR-*` IDs) |
| `.claude/skills/create-test-plan/` | Stage 2 — design → comprehensive test plan (`TC-*` IDs) |
| `.claude/skills/plan-to-issues/` | Stage 3 — design + test plan → dependency-linked issues. The only issue creator |
| `.claude/skills/fix-issue/` | Stage 4a — implements one `type:story` issue |
| `.claude/skills/write-tests/` | Stage 4b — implements one `type:test` issue (handles TDD-ahead-of-code) |
| `.claude/skills/work-backlog/` | Local/interactive: pick the next ready issue, pair with `/goal` |
| `.claude/agents/reviewer.md` | Adversarial-review subagent used by both implementation skills |
| `scripts/ready-issues.sh` | Computes which issues are unblocked and unclaimed |
| `scripts/trace-issues.sh` | Verifies design/test-plan IDs survived into the issues |
| `.github/workflows/dispatch-ready-work.yml` | Claims ready issues, fans out one agent run per issue |
| `.github/workflows/claude-mentions.yml` | Ad hoc `@claude` help, separate from the automated backlog |

## How the dependency graph works

There's no separate database of "blocked/ready" state to keep in sync. Readiness is
recomputed fresh every run from two things GitHub already tracks:

1. **A label**, `type:story` or `type:test` — which skill handles the issue.
2. **A body line**, `Depends on: #12, #34` — which other issues must be *closed* first. No
   line means no dependencies.

`scripts/ready-issues.sh` reads both, checks every open story/test issue against the current
state of the issues it names, and returns whichever are unblocked and not already claimed.
Because it's recomputed from scratch each time, a dependency closing (its PR merging with
`Fixes #N`) is enough to make everything downstream eligible on the very next run — nothing
has to be told to re-check.

It also skips, with a reason on stderr, two things that used to cause trouble: issues whose
`Depends on:` line has no parseable `#N` (which previously read as "no dependencies" and
started blocked work), and issues labeled `status:needs-attention` (which previously got
re-claimed and re-failed on every dispatcher run).

Code and test issues share this exact mechanism. Nothing hardcodes "tests run after code": a
test issue can depend on the code it tests, or have no dependency and be written against the
design ahead of the implementation. The issue says which, in a `Written ahead of
implementation` field — see `write-tests/SKILL.md`.

## Setup

1. Copy this tree into your repo root (merge `.claude/`, `.github/`, and `scripts/` if you
   already have any of them).
2. **`git init` and add a GitHub remote if this isn't a repo yet.** Everything from stage 3
   on assumes git: PRs, branches, `git diff` in the reviewer, and the Stop hook's
   working-tree check.
3. Set `TEST_CMD` in `.claude/settings.json`. It ships **empty**, which disables the
   verification gate — deliberately, because a `TEST_CMD` pointing at a suite that doesn't
   exist makes the Stop hook fail every turn that touches a file, and people learn to ignore
   it. Set it as soon as there's a real suite.
4. Wire the GitHub Action once: run `/install-github-app` from Claude Code in your repo, or
   follow manual setup — both install the Claude GitHub App and an `ANTHROPIC_API_KEY` (or
   `CLAUDE_CODE_OAUTH_TOKEN`) secret.
   [docs → github-actions](https://docs.claude.com/en/docs/claude-code/github-actions)
5. Run the pipeline: `/detailed-design-generator` on your architecture doc, then
   `/create-test-plan docs/design/`, then `/plan-to-issues docs/design/`. Check the printed
   graph before letting anything pick work up.
6. Either let CI take it from here (issues closing and PRs merging trigger
   `dispatch-ready-work.yml` on their own), or run it yourself locally with `/goal` +
   `/work-backlog`.

## How the automation avoids stepping on itself

- **Claiming is two-phase.** `dispatch-ready-work.yml` has a `claim` job that computes the
  ready set and labels each issue `status:in-progress` *before* a second `work` job fans out
  matrix runs — so the race window is "one small job labeling issues one at a time," not "N
  parallel jobs each deciding independently what's free."
- **Only one dispatcher run claims at a time.** The workflow-level
  `concurrency: group: claude-dispatcher` means if an issue closes and a PR merges in quick
  succession, the second dispatcher run queues behind the first instead of racing it.
- **Failures don't get silently retried.** A failed run is labeled
  `status:needs-attention`, and `ready-issues.sh` skips those — so it surfaces for a human
  instead of looping on the same failure every 30 minutes.

What it does **not** fully solve: two independent stories claimed in the same run can still
edit overlapping files and conflict when both PRs land. This is the same tradeoff Anthropic
calls out for agent teams — size and scope stories so independent ones touch different
files, and it mostly disappears. Worth designing your `/create-test-plan` §8.2 sizing and
your story grouping with that in mind, the same way you'd size tickets for two human
engineers working at once.

## Mapping back to Claude Code's own docs

- **Loop between coding agent and evaluator** — `fix-issue`/`write-tests` step 3, backed by
  the Stop hook, and optionally `/goal` for the local path.
  [docs → goal](https://docs.claude.com/en/docs/claude-code/goal)
- **Plan mode before coding** — step 1 of both implementation skills.
  [docs → permission-modes](https://docs.claude.com/en/docs/claude-code/permission-modes)
- **Advisor pattern** — `advisorModel` in settings, invoked on ambiguous issues.
  Anthropic-API-only, still experimental.
  [docs → advisor](https://docs.claude.com/en/docs/claude-code/advisor)
- **Supervisor pattern** — the `claim` → `work` matrix *is* the supervisor for the automated
  path (one job decides and hands off work). For a single hard story you want split across a
  frontend/backend/test split interactively, agent teams are still the documented in-session
  option. [docs → agent-teams](https://docs.claude.com/en/docs/claude-code/agent-teams)
- **Test harness integration** — Stop hook + step 3 of both implementation skills.
- **Git issues → implementation, respecting dependencies** — the resolver script + dispatcher
  workflow above.
  [docs → github-actions](https://docs.claude.com/en/docs/claude-code/github-actions)

## Notes

- `ready-issues.sh` and `trace-issues.sh` are reference logic, not hardened production code.
  Both need `gh` (authenticated) and `jq`. Test them against your real issue list before
  trusting them in CI.
- The `reviewer` subagent has no `Edit` tool on purpose, so it has to report findings rather
  than quietly rewrite the diff itself.
- A Stop hook's block is capped at 8 consecutive tries by Claude Code itself, so a genuinely
  broken test suite can't loop forever locally; the CI path bounds the same risk with
  `--max-turns 60`.
