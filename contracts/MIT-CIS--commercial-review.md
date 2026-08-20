# Commercial review — MIT-CIS / Agentic Consulting Development Agreement

**Reviewing:** `contracts/MIT-CIS--Agentic-Consulting--Development-Agreement.md` (draft, $135,000 fixed fee, 8 gates, 36 weeks)
**Against:** `docs/agentic-evaluation-harness-for-education.md` (v3.3, 3,457 lines, R1–R72) and the `.claude/` + `.github/` build harness
**Question asked:** are the effort and pricing realistic, and fair to both sides?
**Date:** 2026-08-19

> **Scope of this review.** Commercial and technical assessment only. It is not legal advice, and the
> suggested drafting — particularly around escrow (§8.10), the liability disclaimer (§13.2), and the
> invoicing mechanic in F6 — should be confirmed by counsel, consistent with the drafting note the
> agreement already carries.

> **Status (2026-08-19) — the recommendations below have been actioned, with one deliberate
> departure.** Part 3 recommends option **(b)**, a fee of $155,000–$175,000. The Consultant has
> elected option **(a)**: hold **$135,000**, on the judgment that a higher figure is not reachable
> within MIT's budget. The agreement has been updated accordingly, and the console (F1) is now in
> scope at Gate G4 **without a fee increase** — so the Consultant absorbs the $14k–20k identified
> there, on top of the gap in F3.
>
> Because the price is fixed, three compensating changes carry the weight instead, and they are what
> should be defended in negotiation:
>
> - **Schedule B.1(b)–(d)** records the fee as a deliberate below-market program price, ties it to the
>   Article 8 allocation as a single bargain, and disclaims any derived day rate.
> - **Schedule B.4** is restated at ordinary commercial rates ($2,500/day), so the concession applies
>   to the Schedule A scope only and does not leak into every subsequent change order.
> - **Schedule B.5** is rebuilt as three real descope options totalling $27,200, with an explicit
>   fallback that further reductions come from narrowing the Section 8.3 license rather than from
>   discounting scope.
>
> Read Part 3's fee recommendation as the analysis that justifies those three changes, not as a live
> proposal. Everything else in this review has been implemented in full.

> **This document has two passes.** Parts 1–4 below are the **first pass**, against the pre-revision
> draft; they are retained as the reasoning behind the changes now in the agreement. The
> **[second pass](#second-pass--post-revision-review)** at the end reviews the agreement *as revised*
> and is the current assessment. Where the two differ, the second pass governs — in particular, the
> first pass's day-rate derivation is superseded, because Schedule B.1(c) now expressly disclaims that
> calculation.

---

## Verdict

The **schedule is realistic**. The **price is not** — it is roughly half of what the scope in
Schedule A implies, and the gap is not a matter of opinion: the agreement contains a day rate that
values its own fixed fee at 75 person-days, for a scope that cannot be built in 75 person-days.

Four internal contradictions drive most of the problem, and three of the four cut against the
Consultant. They are fixable with surgical edits before execution; none requires renegotiating the
architecture or the gate structure, which are sound.

Separately, MIT carries one real exposure that should be closed in MIT's favour (F5), because a
one-sided agreement is not a durable one.

| # | Finding | Cuts against | Money |
|---|---|---|---|
| F1 | The §11 console (R61–R72, 13 screens) is out of the contract's requirement range and absent from every acceptance criterion | Consultant | ~$14k–20k of unpriced build |
| F2 | Schedule B.5 offers a $16,000 descope on work that is not in Schedule A | Consultant | $16k of illusory discount |
| F3 | $135,000 ÷ $1,800/day = 75 days; the scope is 170–250 days | Consultant | ~$170k–315k gap at the stated rate |
| F4 | Nine stale cross-references to the Design Document, one of them inside the liability disclaimer | Both | Legal risk, not money |
| F5 | No acceptance criterion anywhere sets a floor on transcription quality | MIT | Up to 90% of fee payable on a system that finishes but reads badly |
| F6 | 36% of the fee sits behind MIT dependencies D4/D5/D6 with no partial-invoice mechanism | Consultant | $48,600 exposed to MIT-side delay |

---

## Part 1 — Findings the two documents already disagree about

These are verifiable from the text. They are the ones to fix first, because nobody has to accept a
judgment call to accept them.

### F1. The console is unpriced scope — the headline finding

Schedule A, criterion **A1**, requires the traceability matrix to account for "every requirement
**R1–R60**." The Design Document runs to **R72**.

R61–R72 are §11, "The console: the MVP user interface," marked *new in v3.3*. It specifies thirteen
screens (S1–S13), twenty-one testable interface invariants, two blocking setup gates, an operator
quarantine surface, a minute-budgeted review queue, a run monitor at (stage, criterion, judge)
granularity, an export provenance gate, and post-finalization grade amendment.

The Design Document does not treat this as optional. §13 states:

> **The MVP console of Section 11 is Phase 1**, and it is what makes Phase 1 a product rather than a
> pipeline.

And it names three parts as cheap now / unrepairable later — the read-view seam (R61), the band-only
edit control (R65), and the blind sample's unreachability of system output (R67) — for exactly the
reason version pinning and judgment isolation are on the same list.

The git history explains how this happened: `db47b50 agreements` (2026-08-18) predates
`aeaa906 Add UI` (2026-08-19). The contract was drafted against v3.1/v3.2 of the design; the console
landed the next day and never reached Schedule A.

**What Schedule A does and does not cover.** Gate G4 is titled "Grade Policy, Teacher and Operator
Surfaces" and its eleven deliverables describe the *workflows* a console would host — setup flow,
review queue, quarantine surface, per-student output, class rollup. But not one of A23–A30 references
a screen, a browser, a route, or any R61–R72 requirement. A30's "the dashboard contains no unqualified
single accuracy percentage" is the only criterion that presupposes a UI exists at all, and it
constrains its content rather than requiring its existence. Every invariant §13 flags as unrepairable
— R61, R63, R65, R67, R68, R69, R71, R72 — is untested by any acceptance criterion in the agreement.

**The trap.** Under Section 4.5, MIT cannot withhold acceptance on unstated criteria. Under Section
12.2, the Consultant need not perform unpriced work. So on the literal text, a Consultant could pass
G4 with a command line and MIT could not object. Nobody wants that outcome — MIT would have paid
$86,400 for something no teacher can operate, and the Consultant would have delivered against §0.1's
own stated failure mode. In practice the Consultant builds the console anyway, unpaid, because the
Design Document says it is Phase 1.

**Sizing it.** §11.7 chooses the cheapest possible implementation — one process, server-rendered HTML
over loopback, reading the same SQLite files the harness writes, no build step, no client framework.
That materially limits the cost. But thirteen screens, twenty-one asserted invariants, the provenance
gate, and the minute-budgeted queue are still **10–15% of build effort**: call it **$14,000–$20,000**
at the fee level, or roughly one G-gate.

**Fix.** Extend A1 to R1–R72. Add console deliverables and acceptance criteria to G4 covering at
minimum R61, R62, R65, R67, R68, R71, and R72 — the invariants §13 identifies as unrepairable.
Re-weight G4 upward, or add the console as a priced increment. Do this before execution; after
execution it is a Change Order at the day rate, which F3 shows is itself mispriced.

### F2. Schedule B.5 discounts work that was never scoped

B.5 offers MIT, as its first descope option:

> **Gate G4 calibration and elicitation workflow** (Design Document §6.4 ambiguity discovery and
> teacher-authored rubric revision) — **deduct US $16,000**.

Read G4's deliverable list. Eleven items: grade policy engine, plain-language policy rendering, setup
flow, review queue, batch review, provisional-grade handling, blind and whole-grade sample workflows,
per-student output, class rollup, package export/import, operator surface. **No elicitation. No
ambiguity discovery. No rubric revision.** A23–A30 do not mention them either.

The Design Document agrees they are out. §13 puts elicitation in **Phase 4**, behind the Phase 3
guardrails, and warns specifically against building it early. §11.2 lists "Ambiguity elicitation
(Stage B, §6.4)" in the *No* column of the MVP table.

So B.5's first and largest descope removes something Schedule A does not contain. If MIT elects it,
MIT pays $119,000 for exactly the same delivered system.

**But the contradiction runs the other way too**, and this is why it needs a decision rather than a
deletion. Three other places in the agreement assume G4 *does* include elicitation:

- §3.3 coordination windows: "Gate G4 setup **and elicitation**"
- Dependency **D3**: "Named teacher(s) available for setup, **elicitation**, and blind sample" by G4
- B.5 itself

Either elicitation was meant to be in G4 and got dropped from the deliverable list, or it was
correctly excluded and three clauses still describe the older scope. Both readings are defensible from
the text, which is the problem.

**Fix.** Decide, then make all four places agree. Recommended: keep elicitation **out** (it matches
§13 and §11.2, and building it early is the specific error §13 warns against), strike it from §3.3 and
D3, and replace B.5 item 1. Without a replacement the descope ladder is $4,000 on $135,000 — a 3%
lever, which is not a negotiating instrument. A real ladder would offer instead: the second training
session and site runbook ($4,000), the §7.8 mixed-format deterministic path if MIT's papers are
constructed-response only, and the G6 edge profile itself if MIT elects to run cloud-hosted for year
one. That last one is a genuine $16k–25k cut and it is the one MIT would actually want.

### F3. The day rate and the fixed fee cannot both be right

$135,000 ÷ $1,800/day = **75 days**. MIT procurement will run this division; it is the first thing a
contracts officer does with a fixed price and a rate card in the same document.

Section 2.6 anticipates the objection — "not adjustable by reference to hours worked or to the method
of production" — and Schedule B.1 repeats it. Then B.4 publishes a day rate, and 12.3 makes that rate
the default price for every Change Order. The disclaimer does not survive its own rate card.

**Seventy-five days does not build this.** The division above is arithmetic; the table below is
engineering judgment and should be read as such — it is bottom-up, for a strong solo engineer running
the agentic pipeline in this repo, and it already assumes heavy AI-assisted codegen (a conventional
estimate would be roughly double). The finding survives a wide margin of error: even the low end is
2.3× the implied 75 days.

| Gate | Work | Days |
|---|---|---:|
| G0 | Mobilization, traceability over R1–R72, CI in-container against hosted provider, corpus plan | 8–12 |
| G1 | Provider abstraction ×3 impls, persistence Tier 0, §9.5–9.7 schemas, work ledger, content-hash IDs, version pinning, backend-scoped validation records | 20–30 |
| G2 | Ingestion for 4 artifact kinds, handwriting transcription, multi-file assembly with provenance, canonical immutable artifact + dependent invalidation, non-text region description, validation ladder V0–V4 + circuit breaker, operator triage, differential text-layer check, measurement by legibility band | 35–50 |
| G3 | Decomposability classification, sweep-1 batched extraction in topological order, evidence integrity gate + second-family extraction, isolation boundary, sweep-2 band scoring + prompt lint, odd-panel aggregation + ordinal Krippendorff α, deterministic MCQ evaluator, confidence routing + inversion + random arm | 30–45 |
| G4 | Declarative grade policy engine, setup flow, EV-ranked minute-budgeted queue, batch review, provisional handling, blind/whole-grade sample, per-student output, class rollup, package export/import, operator surface, **plus the F1 console** | 35–50 |
| G5 | Scaled-corpus assembly (350 by augmentation), pilot runs, Feasibility Report incl. surface-proxy regression, outage exercise | 15–20 |
| G6 | MLX/Ollama serving, quantization, concurrency ceiling, §8.5 acceptance run and reruns, conformance suite, report | 15–25 |
| G7 | Source, runbook, operator manual, teacher guide, 2 training sessions, BOM, limitations register, unassisted-run support | 12–18 |
| | **Total** | **170–250** |

At the agreement's own $1,800/day that is **$306,000–$450,000**. At $135,000 the effective realised
rate is **$540–$795/day**.

The single cleanest illustration is **G2**. Schedule A calls it "*the highest-risk Gate*." It is
funded at $21,600 — **twelve days** — to build a handwriting-capable ingestion pipeline across four
artifact kinds, a five-gate validation ladder with a circuit breaker, immutable content-hashed
artifacts with dependent-work invalidation, structured non-text region description under a
describe-never-evaluate constraint, an operator triage queue, and a measured transcription-quality
report banded by legibility. Twelve days is not a stretch target; it is off by a factor of three or
four.

**The ratio problem.** The agreement cannot keep both numbers.

- If **$135,000 is the right price**, then $1,800/day is far too low, and every Change Order and the
  B.4 support retainer bleed the Consultant at roughly a third of the fee's own implied value.
- If **$1,800/day is the right rate**, then $135,000 buys 75 days, which does not produce eight
  gates, forty-seven acceptance criteria, and a thirteen-screen console.

**Fix — pick one, and prefer the second:**

1. Raise the Fixed Fee toward the scope. See Part 3 for where it should sit.
2. Keep $135,000 as a **deliberate below-market program price** and say so in B.1, then decouple the
   rate card: raise B.4 to **$2,400–$2,800/day** and add one sentence — *"The rates in B.4 price
   incremental work outside Schedule A and are expressly not a valuation basis for the Fixed Fee,
   which reflects the license grant in Section 8.3 and the program's non-profit educational
   purpose."* That gives Section 2.6 something to stand on, stops MIT anchoring change orders at a
   loss-making rate, and makes the discount legible as a concession rather than an accident.

Also review the rest of B.4 while it is open: the retainer at $7,500/quarter for up to 3 days is
$2,500/day, which is correctly above the change rate — but *3 days a quarter* to cover corrective
maintenance plus dependency **and model-version** updates on a system whose statistics are pinned to
specific model builds is thin. One model deprecation forces a re-pin, a conformance rerun, and a
re-scoped validation record. Budget 4–5 days, or scope model-version migration out of the retainer
and price it separately.

### F4. Nine stale cross-references, one of them load-bearing

The Design Document renumbered when §11 was inserted. Risks/limits/governance moved from §11 to §12;
the implementation sequence moved from §12 to §13. Everything at §10 and below is unchanged, so the
affected set is exactly the references to §11–§13. The contract still cites the old numbering in all
nine places:

| # | Contract location | Cites | Should cite |
|---|---|---|---|
| 1 | Section 2.3 build order | Design Document §12 | §13 |
| 2 | Section 2.8(b) scaled corpus ("far cheaper to discover on 350 synthetic submissions") | §12 | §13 |
| 3 | Section 3.5 feasibility gates ("Phase 1.5, prove it on hardware") | §8.5 **and §12** | §8.5 and §13 |
| 4 | Section 7.1(b) recorded-fixture provider | §12 | §13 |
| 5 | **Section 13.2 automated-assessment disclaimer** | §0.5, §7.9, **Article 11 thereof** | §0.5, §7.9, §12 |
| 6 | Schedule A, G1 deliverable 1, three provider implementations | (R27, **§12**) | (R27, §13) |
| 7 | Schedule A, G7 deliverable 5, known-limitations register | §11 | §12 |
| 8 | Schedule B.5 ("a complete, useful, defensible product") | §12 | §13 |
| 9 | Schedule D.1 recorded-fixture provider | §12 | §13 |

Every quoted phrase is genuine and appears in §13; the section numbers are simply one behind. Items 3
and 6 are the easy ones to miss, because there the `§12` is a bare parenthetical rather than adjacent
to "Design Document." To confirm the sweep is exhaustive before signature:

```bash
grep -n '§1[123]' contracts/MIT-CIS--Agentic-Consulting--Development-Agreement.md
```

That returns items 1–4 and 6–9; item 5 uses the "Article 11 thereof" form and must be caught by eye.

**§13.2 is the one that matters.** It is the disclaimer that limits liability for automated
assessment, and it grounds itself in a Design Document section that is now the UI specification. If
that disclaimer is ever tested, MIT's counsel gets to argue the Consultant disclaimed by reference to
a document section that says nothing about the risks disclaimed. Fix it before signature.

Also fix Schedule B.1's implied scope: it prices "a validated, auditable grading harness" with no
mention of the console, which compounds F1.

While in there: `README.md` still describes the design as "v2.7, ~2,500 lines" against an actual v3.3
at 3,457. Not contractual, but it is the first thing a reviewer reads.

---

## Part 2 — Does the Claude Code harness change the answer?

The agreement leans on this explicitly. Section 2.6 permits AI-assisted development and pre-existing
orchestration harnesses as Consultant Background IP, and prices the result rather than the labour.
Section 8.11 allocates the IP in machine-generated output. That drafting is correct and worth keeping.

**What the harness genuinely compresses.** The `.claude/` pipeline — `/detailed-design-generator` →
`/create-test-plan` → `/plan-to-issues` → `/fix-issue` + `/write-tests`, with `ready-issues.sh`
computing readiness from `Depends on:` lines and `dispatch-ready-work.yml` fanning out parallel agent
runs — is a real accelerator for exactly the work this project is heaviest in: many small,
well-specified, independently testable modules behind stable interfaces. A design document this
complete is close to an ideal input; the FR→TC→issue→PR traceability chain, enforced by
`check_traceability.py` and `trace-issues.sh`, is what makes forty-seven acceptance criteria auditable
rather than aspirational. Schema-heavy work (§9.5–9.7), prompt-lint rules (A15, A16), the
deterministic MCQ evaluator, and the grade policy engine are all strongly compressible this way. My
170–250 day estimate already assumes this; without it the number is roughly double.

**What it does not compress — and this is what dominates the schedule:**

- **Measurement runs are wall-clock bound.** The §8.5 acceptance test is a multi-hour run on one
  laptop, plus reruns after tuning, plus a deliberate mid-run kill. No amount of parallel codegen
  shortens a twelve-hour batch window, and the Note under G6 exists because thermal sustain can only
  be discovered by running it.
- **Coordination windows are calendar-bound.** §3.3 requires ten business days' notice for G4
  elicitation, the G5 pilot, and G7 training. Three such windows is a month of calendar before anyone
  works.
- **Transcription quality is empirical iteration, not code generation.** G2's A9 is a *measurement*,
  and getting an open-weight VLM to read marginal handwriting reliably is prompt-and-model search
  against a fixture corpus. It is the least agent-compressible task in the project and it sits on the
  gate the agreement itself calls highest-risk.
- **Forty-seven Gate Report results.** Every criterion needs a measured figure, sourced to the right
  corpus per §2.8. That is analyst work under §4.6's honesty rules.
- **The pipeline is unproven on this project.** `docs/design/` does not exist and `TEST_CMD` in
  `.claude/settings.json` is empty, which disables the Stop-hook verification gate by design. Stage 1
  has not been run. The 36-week schedule starts from zero code *and* an unexercised pipeline, and the
  README itself notes `ready-issues.sh`/`trace-issues.sh` are "reference logic, not hardened
  production code."

**The reconciliation, and it is the sharpest thing in this review:**

> The 36-week **calendar** is realistic. The 75-day **labour budget** the day rate implies is not.
> The harness compresses the work that fits inside those 36 weeks; it does not shrink the 36 weeks,
> and it does not turn 200 days of work into 75.

That points the fix at **B.4 and B.1**, not at the schedule. Schedule B.3's 36 weeks should stand.

**One margin item the agreement forecloses.** §7.1 states the Consultant "does not require, and MIT is
not asked to fund, dedicated cloud compute, managed CI infrastructure, or third-party developer
subscriptions." The agentic pipeline's own inference spend — interactive sessions plus matrix-fanned
CI agent runs across a backlog of this size, over 36 weeks — is real, plausibly **$3,000–$10,000**,
and it is 2–7% of the fee, self-funded. That is a fine commercial choice and it keeps Schedule D
clean, but it should be a conscious one rather than a discovered one, and it belongs in the Part 3
margin arithmetic.

---

## Part 3 — Is $135,000 fair? (judgment, clearly labelled)

Everything above is sourced from the documents. This section is opinion.

**What the Consultant actually nets.** 170–250 days over 36 weeks is 4.7–6.9 days per week — near
full-time, on the low end and beyond it on the high end. $135,000 for roughly nine months
near-full-time is about **$180,000 annualised gross**, before self-employment tax, benefits, own
equipment, own CI, and the $3k–10k of agentic tooling spend above. Net, that is equivalent to roughly
a **$110,000–$130,000 salaried role** — for an engineer who can independently build a
statistically-validated, offline-capable, auditable assessment system and who authored its
architecture. That is below market for the capability, and materially below what a boutique firm would
quote for the same Schedule A (my read: **$350,000–$600,000**, work-for-hire).

**Note the tension in §3.2.** It provides that the Consultant "does not undertake to devote any
particular number of hours" and controls timing. But the scope and the 36-week schedule together imply
near-full-time engagement. The flexibility that clause offers is nominal — worth knowing before
relying on it.

**Why $135,000 is nonetheless coherent — and it is the IP.** Article 8 is where the fee is actually
justified, and B.1 says so. MIT pays for a **license, not title**: §8.2 keeps the Platform and all
Foreground IP with the Consultant, §8.3 gives MIT a perpetual, irrevocable, worldwide, royalty-free
license for research and education with sublicensing to Participating Schools, and §8.4 reserves all
commercial exploitation to the Consultant. The Consultant emerges owning a commercially exploitable
asset built substantially at MIT's expense. That is exactly why $135,000 rather than $350,000 hangs
together — **price and IP are one bargain**, and B.1's own wording ("delivered with a perpetual
institutional license rather than as work for hire") makes the trade explicit.

The corollary matters for the negotiation: **if MIT pushes the price down, the symmetric answer is the
IP lever, not the descope ladder.** The drafting note already concedes Article 8 is the clause most
likely to be negotiated, and MIT's TLO will read §8.4 — commercial license "to be negotiated in good
faith" with no terms, no revenue share, no credit — as an unpriced option. Prepare the fallback now:
a modest royalty or fee credit to MIT on commercial licensing within N years, or named-contribution
credit, both of which cost nothing unless the Platform succeeds commercially. That is a far better
concession than cutting scope, and it is the one MIT's own institutional interests are best served by.

**Recommendation.** Either:

- **(a)** Hold $135,000 and state in B.1 that it is a below-market program price reflecting the
  Section 8.3 license retention and the non-profit educational purpose — then fix B.4 per F3 so the
  concession does not leak into every change order; or
- **(b)** Move to **$155,000–$175,000**, which prices the F1 console honestly and lands at an
  effective $700–$900/day, still well under a firm's quote and defensible to MIT precisely because the
  Consultant retains title.

Given F1 alone is $14k–20k of currently unpriced work, **(b) at ~$155,000 is the defensible minimum**
if the console is added to Schedule A, and (a) is honest only if B.1 says out loud that the price is
a concession.

---

## Part 4 — Fairness to MIT: two items to fix in MIT's favour

An agreement that only protects one side does not survive procurement review, and these two are the
ones MIT's counsel will find.

### F5. No acceptance criterion sets a floor on transcription quality — this is MIT's real exposure

Every grade in the system is produced from a transcription. If handwriting transcription is poor,
every downstream statistic is measuring the wrong text — and the agreement's own §13.2(d) concedes
that "performance degrades on poor-quality scans and difficult handwriting."

Yet:

- **A9** (G2) explicitly disclaims a threshold: *"No fixed accuracy threshold applies at this Gate;
  the measurement is the deliverable."*
- **A31** (G5) — "the single most important acceptance criterion in the Agreement" — tests only that a
  zero-touch run **completes and finalizes**, not that its output is any good.
- **A34–A35** are measured-and-reported, not gated. The Note under G5 says so.
- **G7** re-tests G1–G6 for regression (A47) and adds no quality bar.

The consequence: a system that ingests, transcribes badly, scores confidently against a bad
transcription, and delivers a complete grade for every student **passes every acceptance criterion in
the agreement**. MIT would have paid the full $135,000.

The Note under G5 gives the right reason for having no threshold up front — "a threshold set before
measurement would be a guess" — and that reasoning is sound and worth keeping. But it is only half the
mechanism. The other half, converting the G5 measurement into a G7 threshold, is left entirely to
Section 12.1 Change Order, which requires the Consultant's signature. MIT has no way to get a quality
floor if the Consultant declines to sign.

**Fix — a default, not a threshold.** Add to G5's Note: *"Within fifteen business days of the G5
Feasibility Report, the parties shall set thresholds for A9 transcription fidelity and A34
per-criterion agreement, to be tested at G7 by Change Order. If the parties do not agree within that
period, the G7 threshold for each metric defaults to the G5 measured value less [10]%, tested on the
same corpus and scope."* That preserves the measure-first logic, costs the Consultant nothing if the
system holds its own G5 performance, and gives MIT a floor that does not depend on a countersignature.
It is also the single change most likely to make this agreement pass MIT procurement without a fight.

### F6. 36% of the fee sits behind MIT dependencies with no partial-invoice mechanism

G5, G6, and G7 total **$48,600 — 36% of the fee** — and each is gated on an MIT dependency: D4 (real
cohort with consents and COUHES), D5 (Apple Silicon hardware, 64GB reference), D6 (MIT personnel for
training and the unassisted run).

The agreement handles *schedule* well: §2.7, §3.3, §7.6(d), and §3.4's extended long-stop all push
delay day-for-day, and §7.6(d) confirms G0–G5 need no MIT hardware. What it does not handle is
**cash**. If MIT's COUHES approval takes four months, the Consultant has finished G5's engineering,
cannot run the gate, cannot invoice, and — under §3.2 — has no deadline claim either, because time is
not of the essence and the schedule remedy is the sole remedy. The Consultant absorbs the entire
financing cost of MIT's institutional processes.

This also cuts against MIT in an under-appreciated way: it gives the Consultant a financial incentive
to push MIT hard on dependencies rather than accommodate them, which is not the working relationship
either party wants across a 36-week program.

**Fix.** Add to §4 or §5: *"Where the Consultant has completed all work within its control for a Gate
but the Gate cannot be tested because an MIT dependency (Schedule A, D1–D6) is outstanding, the
Consultant may deliver a Gate Readiness Certificate evidencing completion. If the dependency remains
outstanding thirty days later, the Consultant may invoice fifty percent of that Gate's tranche, with
the balance payable on acceptance."* Symmetric with §14.2(b)'s existing pro-rata principle, and it
removes a perverse incentive.

### Two smaller two-sided items

- **§8.10 escrow vs §8.11(c) trade secret.** §8.10 deposits complete source into "a repository MIT
  controls" at every Gate acceptance, while §8.11(c) rests the Consultant's proprietary position
  partly on "trade secret protection in the Platform's architecture, schemas, prompt formulations, and
  configurations." §8.10 does subject the deposit to Article 10 confidentiality, which is the right
  instinct — but a trade secret claim is materially weakened by routine deposit into a third party's
  repository over 36 weeks. Tighten §8.10: name the specific repository, restrict access to named MIT
  personnel with a need to know, prohibit onward distribution including to Participating Schools
  absent an §8.3(c) sublicense, and state that the deposit is for continuity and verification only.
  MIT loses nothing it actually needs; the Consultant keeps the claim §8.11(c) depends on.
- **Schedule D token budget: fine, and not worth negotiating.** The arithmetic is internally
  consistent — a 20-submission run at ~1,300 scoring calls plus ~80 vision pages for $1–3 scales
  linearly to the stated $20–40 for a full 350-submission run at ~23,000 calls, which matches §0.1 and
  §8.4. The one soft line is G0–G4 at $400–900: transcription prompt iteration against a handwriting
  fixture corpus at four pages per submission is the token-heaviest development activity in the
  project and is not called out separately. Even so, the $3,500 cap is rounding error against $135,000
  and the §7.5 notify-at-80% mechanism handles the overrun properly. Leave it alone.

---

## Recommended edits, in priority order

**Before execution:**

1. **A1**: `R1–R60` → `R1–R72`. One character each side; it is the root of F1.
2. **G4**: add console deliverables and acceptance criteria for R61, R62, R65, R67, R68, R71, R72.
   Re-weight G4, or price the console as an increment.
3. **B.4**: raise to $2,400–$2,800/day, and add the sentence decoupling the rate card from the Fixed
   Fee valuation. Revisit the 3-day retainer allowance.
4. **B.1**: state the fee basis explicitly — below-market program price against retained Section 8.3
   license — or move to $155,000–$175,000 per F3/Part 3.
5. **B.5**: resolve the elicitation contradiction across B.5, §3.3, and D3. Replace descope item 1
   with a real lever (recommended: the G6 edge profile).
6. **Section 13.2**: `Article 11 thereof` → `§12`. Fix all nine citations in F4's table.
7. **G5 Note**: add the default-threshold mechanism from F5.
8. **§4/§5**: add the Gate Readiness Certificate from F6.
9. **§8.10**: tighten the escrow terms per the two-sided items.

**Fix in the repo, not the contract:** `README.md` still says the design is v2.7 / ~2,500 lines; it is
v3.3 / 3,457 lines.

---

## Bottom line

The gate structure, the acceptance criteria, the risk allocation at §13.4 and §7.7, and the
measurement-honesty provisions at §4.6 are unusually well built — this is a better-drafted agreement
than most software development contracts, and the feasibility-gate framing is exactly right for a
project with real empirical unknowns.

The pricing is where it comes apart, and the cause is mechanical rather than a misjudgment of value:
the contract was drafted against a design document that grew a thirteen-screen subsystem the day
after, and it published a rate card that values its own fixed fee at less than half the work.

Fix F1 through F4 and the agreement is fair to the Consultant. Add F5 and F6 and it is fair to MIT —
and, more usefully, it is an agreement MIT's procurement and TLO can approve without a round of
adversarial redlining.

---
---

# Second pass — post-revision review

**Reviewing:** the same agreement **as revised** under option (a) — fee held at $135,000, console
brought into scope at Gate G4 without a fee increase.
**Question re-asked:** with the console now in Schedule A and the price unchanged, are the effort and
pricing still realistic, and still fair to both sides?
**Date:** 2026-08-19 (same day; the contract was revised after the first pass above)

## What was actioned, verified

All nine recommended edits are in the document. Spot-checked:

| First-pass finding | Where it landed | Verified |
|---|---|---|
| F1 console unpriced | §2.9, G4 deliverable 12, criteria **A48–A56**, A1 now reads R1–R72 | Yes |
| F2 illusory descope | B.5 rebuilt as three real options totalling **$27,200** | Yes |
| F3 rate/fee contradiction | B.4 restated at **$2,500/day**; B.1(c)–(d) disclaims any derived day rate | Yes |
| F4 stale cross-references | §13.2 now cites §0.5, §7.9, §12 | Yes |
| F5 no quality floor | Note to G5 (a)–(d), with the **G5-minus-10% default** and the (b bis) comparability rule | Yes |
| F6 MIT-dependency financing | **§5.7 Gate Readiness Certificate**, 50% at 30 days | Yes |
| Escrow vs trade secret | §8.10(b)–(c) named repository, need-to-know, no onward distribution | Yes |
| README stale version | Now v3.3 / ~3,450 lines | Yes |

The arithmetic holds: B.2 sums to 100% and to $135,000; B.5's three options sum to $27,200; B.4's
retainer ($9,500 ÷ 4 days = $2,375) and migration price ($6,000 ÷ 2.5 days = $2,400) are internally
consistent with the $2,500 day rate. Nothing in the revision broke the numbers.

**A note on method.** The first pass valued the scope by dividing the fee by a day rate. **B.1(c) now
expressly disclaims that calculation** — on this review's own recommendation. The person-day figures
below are therefore the *Consultant's* internal go/no-go arithmetic and a measure of annualized
compensation. They are not offered as a contractual valuation of the Fixed Fee or of any Deliverable,
and B.1(c) governs.

---

## Verdict on the revision

**The revision fixed the drafting. It did not fix the economics — it relocated them.** Option (a)
holds the price and adds the console, so roughly $14k–20k of build moved into the agreement without
moving any money. The three compensating mechanisms (B.1(b)–(d), B.4 at ordinary rates, the B.5
ladder) protect the Consultant *outside* Schedule A: they stop the concession leaking into change
orders, and they give the negotiation a descope ladder instead of a discount ladder. All three are
well drafted and all three are worth keeping.

What none of them does is place the absorbed work anywhere. It landed in Gate G4, and G4 was not
re-weighted, not re-scheduled, and is not reachable by any of the three descope options. That is the
one structural defect the revision introduced, and it is the finding below.

| # | Finding | Cuts against | Money |
|---|---|---|---|
| N1 | G4 now carries 12 deliverables and 17 criteria at the **lightest** build-gate weighting | Consultant | ~$4k under-tranched; 40–55 days of WIP recoverable at $8,894 under §14.2(b) |
| N2 | 36 weeks became the optimistic case, not the planning case; G4's 6 weeks is the pinch point | Both | Cash-flow timing |
| N3 | **Confirmed defect:** B.5 Option 2 contradicts A24 and A49, which both hard-code "exactly two" | Both | Untestable criteria if exercised |
| N4 | The B.5 ladder cannot reach the one item absorbed for free | Consultant | No lever below $107,800 |
| N5 | The G5 default threshold is a ratchet, not a floor | MIT | Disclosure, not a defect |

---

## N1. G4 absorbed the console with no re-weight — the headline

Pure arithmetic from Schedule A and Schedule B:

| Gate | Deliverables | Acceptance criteria | Weight | Tranche | Weeks |
|---|---:|---:|---:|---:|---:|
| G2 — ingestion + ladder *(called "the highest-risk Gate")* | 7 | 7 (A8–A14) | 16% | $21,600 | 6 |
| G3 — scoring engine | 8 | 8 (A15–A22) | 16% | $21,600 | 6 |
| **G4 — policy, surfaces, package, console** | **12** | **17** (A23–A30 + A48–A56) | **14%** | **$18,900** | **6** |

G4 now carries fifty percent more deliverables and more than twice the acceptance criteria of either
neighbouring gate, in the same six weeks, for **$2,700 less**. The first pass priced the console at
$14k–20k on its own — approximately G4's entire tranche — and it now sits inside the lightest-weighted
of the three build gates.

**This has teeth beyond fairness, because two clauses operate on tranches.** §14.2(b) pays pro-rata
"reflecting the percentage of that Gate's Acceptance Criteria then demonstrably met," and §5.7(b)
invoices 50% of the tranche. Both are proportions *of the tranche*, so the gate holding the most
work-in-progress is the one that pays out least if anything goes sideways. Concretely: MIT terminates
for convenience with 8 of G4's 17 criteria met, and the Consultant recovers 8/17 × $18,900 = **$8,894**
against what is, on the sizing below, 40–55 person-days of work in progress.

**Fix — re-weight, no fee change.** B.1(c) expressly permits tranche-level movement (the pro-rata
mechanics of §5.7 and §14.2(b) are named as permitted uses), so this needs no change to the Fixed Fee
and no change to the IP bargain:

| Gate | Now | Proposed | Tranche |
|---|---:|---:|---:|
| G0 | 8% | **6%** | $8,100 |
| G1 | 10% | **9%** | $12,150 |
| G4 | 14% | **17%** | $22,950 |
| *(G2, G3, G5, G6, G7 unchanged)* | | | |

Still sums to 100% and to $135,000. G0 and G1 are the two lightest gates by content (5 deliverables
and 3–4 criteria each) and are the right place to source it from.

**State the trade-off, because it is real.** This moves $4,050 of cash from weeks 2–6 to week 24 —
$2,700 out of G0 and $1,350 out of G1, exactly G4's gain. The
Consultant is trading early cash for pro-rata protection at the gate that will carry the most exposure.
If early cash is the higher priority, the alternative is to **split G4 into two tranches** — G4a
(deliverables 1–11, A23–A30) and G4b (deliverable 12, A48–A56) — which fixes the exposure without
deferring the whole amount, at the cost of one extra acceptance cycle (§4.2's ten business days, plus
any §4.4 cure). Either is defensible. Leaving it as drafted is the option that is not.

---

## N2. The 36 weeks is now the optimistic case

The first pass concluded the schedule was realistic. That conclusion was reached on the assumption the
console would arrive **with** a fee increase — i.e. as priced scope. It is now unpriced scope in a gate
whose duration did not change, so the schedule conclusion needs restating.

**Bottom-up sizing, console included** (assumptions: one person; the `.claude/` pipeline running as
designed; open-weight model work; no subcontracting):

| Gate | Work | Person-days |
|---|---|---:|
| G0 | Plan, R1–R72 traceability matrix, CI in MIT-accessible form, **first run of pipeline stages 1–3** against a 3,457-line design | 10–15 |
| G1 | Provider abstraction ×3, persistence Tier 0, content-hash IDs and resume, version pinning, validation-record schema | 15–22 |
| G2 | Ingestion for 4 artifact kinds, assembly with provenance, canonical artifact, region descriptions, V0–V4 ladder, triage queue — **plus A9 empirical transcription measurement** | 30–45 |
| G3 | Decomposability, sweep-1 extraction, evidence-integrity gate, isolation boundary, sweep-2 bands, odd-panel + ordinal α, MCQ evaluator, confidence routing | 30–40 |
| G4 | Grade policy engine, setup flow, budgeted queue, sampling flows, per-student output, rollup, package export/import, operator surface, **+ 13-screen console (S1–S13)** | 40–55 |
| G5 | Pilot runs, Feasibility Report, compression check, surface-proxy regression, outage exercise | 12–18 |
| G6 | Edge deploy, §8.5 acceptance at 350, §8.7 conformance, Hardware Report, tuning reruns | 12–20 |
| G7 | Source/runbook/manuals, 2 training sessions, BOM, limitations register, **regression re-test of all 56 criteria**, unassisted run | 12–18 |
| | **Total** | **161–233** |

Add the PR-review load that the harness *creates* (see the harness section below) and the raw range is
173–261. Trimming the tails on judgment, the working figure is **180–250 person-days**.

**On the difference from the first pass.** Part 2 above put the scope at 170–250 days *excluding* the
console; this table says 161–233 *including* it. The gap is estimation method, not scope: the first
figure was derived top-down from the rate card, this one is built bottom-up per gate from Schedule A's
deliverable and criterion lists. Read the bottom-up figure as the better one and the first-pass figure
as superseded — the console is 40–55 days' worth of G4, not free.

Against 36 weeks — about 180 available working days — that is **1.0× to 1.4× full time**. The bottom of
the range fits; the top of the range is roughly 50 weeks, which is almost exactly §3.4's twelve-month
long-stop.

**So: 36 weeks is achievable and is not a misrepresentation, but it is the good case.** The contract is
already drafted correctly for this — §3.2 makes gate dates planning estimates, time is not of the
essence, and §3.4's twelve months is the sole schedule remedy. Nothing needs redrafting for MIT's
protection. Two things should change anyway:

- **B.3 should read "eight to eleven months" rather than "eight to nine."** It is a planning estimate
  either way, and the wider range is the honest one now that the console is in G4. This costs the
  Consultant nothing (§3.2 already governs) and pre-empts an avoidable conversation at week 26.
- **Plan cash flow against twelve months, not nine.** With §5.7 now in place the MIT-dependency risk on
  G5–G7 is half-covered; the schedule risk on G2 and G4 is not covered by anything, because it is the
  Consultant's own risk to carry under §3.2.

The single tightest point in the plan is **G4 at six weeks**. If one gate is going to slip, it is that
one, and the §5.7 Certificate does not help there — G4 has no MIT dependency to certify against.

---

## N3. Confirmed defect: B.5 Option 2 contradicts A24 and A49

Verified against the document rather than inferred.

B.5 Option 2 (the mixed-format descope, $7,000) states that on exercise, *"Schedule A's blocking setup
items reduce from two to one,"* and names the criteria that fall away as **A21–A22**. But two other
criteria hard-code the number:

- **A24** (G4): *"Setup blocks on exactly two items — question inventory and MCQ answer keys — and on
  nothing else."*
- **A49** (console): *"Exactly two console screens block progress, both in setup..."*

Neither is named in Option 2's affected list, and G4 deliverable 12 likewise describes *"the two
blocking setup screens (question inventory, answer keys)."* If Option 2 is exercised, A24 and A49
become criteria the Platform is contractually required to fail.

This is the same class of defect as first-pass F4 — two correct fixes landing separately without being
reconciled. The console criteria (A48–A56) were written after B.5 was rebuilt, and B.5's affected-list
was not revisited.

**Fix, one edit.** In Option 2, extend the affected list: *"...removes Gate G3 deliverable 7 and
criteria A21–A22 (R52–R55) ... and amends A24 and A49 to read 'exactly one' in place of 'exactly
two', and G4 deliverable 12 correspondingly."*

---

## N4. The descope ladder cannot reach the thing that was absorbed

B.5's three options total **$27,200**, giving a floor of $107,800 before the Article 8 fallback engages.
None of the three touches the console — the one item that entered Schedule A at no fee. So if MIT's
budget comes in short, the Consultant descopes work it *is* being paid for while continuing to absorb
work it is not.

A fourth option is available and is grounded in the Design Document rather than invented. §13
distinguishes sharply between the console properties that are unrepairable and those that are not: the
read-view seam (R61), the band-only edit control (R65), and the blind sample's unreachability of system
output (R67) are the expensive-to-retrofit set — while everything else in §11, and it names the wizard
shape, the queue layout, and the rollup's presentation, is *"explicitly disposable and should be built
expecting to be replaced."*

That is the only defensible seam for a console reduction, and it suggests:

> **Option 4 — console presentation reduction. Deduct US $5,000–7,000.** Retains R61, R65, R67, R68,
> the two blocking setup screens, operator quarantine, the budgeted review queue, and finalization —
> i.e. every property §13 identifies as unrepairable and every screen without which a run cannot
> complete. Reduces the presentation layer §13 names as disposable: the class rollup and
> finalization screen (S12) delivers its per-criterion distribution, misconception clusters, and MCQ
> distractor analysis as an exported file rather than as interactive views, and student detail (S13)
> drops the one-click image-crop viewer in favour of a link to the retained crop. Criteria A48–A56 are
> unaffected.

Two caveats to weigh before offering it. **A54 constrains how much can vanish** — every §7.9 touchpoint
must be present-and-unavailable naming its version, so this is a reduction in richness, not in surface
count. And **A30** ("no unqualified single accuracy percentage anywhere") plus §10's argument that the
rollup is *"the system's strongest output at n=350"* mean the rollup should be reduced, never dropped.
Offered as a lever to have available, not one to lead with.

---

## N5. Fairness to MIT: the G5 default is a ratchet, not a floor

The F5 mechanism works and MIT should accept it, but its shape should be understood rather than
discovered. The default under the Note to G5(b) is *the G5 measured value less 10%*. It guarantees that
the system does not **regress** between G5 and G7. It sets no absolute level. If transcription fidelity
on marginal handwriting measures poorly at G5, the G7 threshold defaults to something slightly worse
than poor, and A47 is satisfied.

That is defensible — the Note's own reasoning, that a threshold set before measurement is a guess, is
sound, and the (b bis) comparability rule closes the obvious evasion. And MIT is not without remedy: if
G5 measures badly, MIT's answer is **§14.2 termination for convenience** on thirty days' notice, paying
for accepted gates only ($105,300 through G5) and retaining the §8.3 license to those Deliverables,
plus §13.4's fifteen-business-day meet-and-revise. MIT can therefore decline to fund G6 and G7 —
$29,700 — on a bad G5 finding.

So the exposure is real but bounded, and the off-ramp exists. **This is a disclosure item, not a
finding.** MIT's negotiators should be told plainly: *your quality protection is the right to stop at
G5, not the right to demand a quality level.* An agreement that says so is more likely to survive
procurement than one that lets MIT discover it at week 28.

---

## Does the Claude Code harness change the answer? (revisited)

The first pass concluded the harness compresses the work inside the 36 weeks without shrinking the 36
weeks. That still holds. Three things sharpen it now that the console is in scope.

**The console is the most harness-compressible thing in the agreement.** Thirteen server-rendered
screens reading the §9 stores and writing rows the orchestrator consumes (§11.7) is close to an ideal
target for `/fix-issue`: bounded, stateless, well-specified, independently testable, and behind a seam
the design document already drew. If any part of the absorbed $14k–20k is recoverable through the
pipeline, it is this part. That is a genuine reason the Consultant's option (a) is not reckless.

**But 26% of the fee sits in gates the harness does not touch at all.** G5 (14%) and G6 (12%) —
**$35,100** — have acceptance criteria that are measurements and reports, not code. All six skills in
`.claude/skills/` — `detailed-design-generator`, `create-test-plan`, `plan-to-issues`, `fix-issue`,
`write-tests`, `work-backlog` — terminate at code plus tests: nothing in the harness runs a measurement campaign,
does prompt-and-model search against a fixture corpus, or produces a Gate Report. Add G2's A9, which is
that same empirical work embedded inside a code gate and sitting on the gate the agreement itself calls
highest-risk, and the least-compressible work is concentrated exactly where the acceptance risk is.

**And the harness converts write-time into review-time.** Stated assumptions: 72 requirements yielding
roughly one to one-and-a-half stories each, most with a paired `type:test` issue → on the order of
130–210 issues. Each agent PR needs a human read, a `reviewer` subagent pass, action on findings, and a
check against the issue's Goal — call it 20–40 minutes, plus rework on the fraction that fail review.
That is **12–28 person-days of pure PR review and merge-conflict handling**, 7–12% of the budget, in an
activity automation creates rather than removes. The README already names the residual risk: two stories
claimed in the same dispatcher run can edit overlapping files.

**The pipeline is still unexercised on this project.** `docs/design/` does not exist, so stage 1 has
never run against this design document. `TEST_CMD` in `.claude/settings.json` is empty, which disables
the Stop-hook verification gate by design. The README calls `ready-issues.sh` and `trace-issues.sh`
*"reference logic, not hardened production code."* G0's two weeks must absorb the first run of stages
1–3 on a 3,457-line input **and** the debugging of the pipeline itself — which is why G0 is sized at
10–15 days above, not the 5 its deliverable list suggests.

**Self-funded tooling.** §7.1 forecloses MIT funding the Consultant's own development inference, and
Schedule D correctly keeps only product tokens as pass-through. With the console added, the agentic
development spend across 36 weeks of interactive sessions plus matrix-fanned CI runs is plausibly
**$3,000–$10,000** — 2–7% of the fee, absorbed. That is a fine commercial choice; it should be a
budgeted one. Schedule D's own numbers stay fine and are not worth negotiating; the G0–G4 line
($400–900) remains the soft one, because transcription prompt iteration against a handwriting fixture
corpus is the token-heaviest development activity in the project, and the $3,500 cap absorbs it either
way.

---

## Is $135,000 fair, after the revision?

**To MIT: yes, clearly, and more so than before.** MIT gets a perpetual, irrevocable, sublicensable
research-and-education license; source escrow with custody terms; a quality-floor ratchet that does not
require the Consultant's countersignature; termination for convenience at any point; 10% retention
behind an unassisted end-to-end run driven without a command line; day-for-day schedule relief as the
Consultant's *only* remedy for MIT-caused delay; and capped out-of-pocket of $3,500 plus hardware MIT
buys from its own source. The one thing MIT should understand rather than discover is that it is funding
an asset it will not own — and B.1(b) states that plainly rather than burying it.

**To the Consultant: it is fair only because of Article 8, and that link is now load-bearing.** On the
sizing above, $135,000 against 180–250 days is an effective **$540–$750 per day** — 22–30% of the
Consultant's own ordinary rate in B.4. Near-full-time across nine months, that annualizes to roughly
$193,000 gross, which after self-employment tax, no benefits, own equipment and CI, and the $3k–10k of
self-funded tooling is equivalent to about a **$115,000–$135,000 salaried role** — for someone who can
independently build a statistically-validated, offline-capable, auditable assessment system and who
authored its architecture. That is below market for the capability, deliberately, and B.1(a) now says so.

What makes it coherent is that the Consultant emerges owning a commercially exploitable Platform built
substantially at MIT's expense. **That is the entire justification for the number, and after option (a)
it is the only justification left** — the console concession consumed whatever margin the first pass
identified.

**The negotiation posture that follows, and it is the practical takeaway:** MIT's TLO will read §8.4's
commercial license "to be negotiated in good faith," with no terms, no revenue share and no credit, as
an unpriced option, and will want terms on it. B.1(b) already provides the correct answer — price and IP
allocation are a single bargain, neither revisited without the other — and that clause should be pointed
at early rather than argued from scratch. If MIT wants Article 8 narrowed, the symmetric responses are a
fee increase toward the first pass's $155,000–$175,000, or B.5's ladder, in that order. **What should not
happen is Article 8 being conceded on relationship grounds while the price stays at $135,000**, because
at that point the Consultant is funding an MIT-owned asset out of a below-market fee.

---

## Recommended edits — second pass

**Before execution:**

1. **N3, B.5 Option 2** — extend the affected-criteria list to amend A24, A49, and G4 deliverable 12
   from "two" to "one". One sentence; it is the only outright defect found in this pass.
2. **N1, B.2** — re-weight G0 8→6%, G1 10→9%, G4 14→17%. No fee change, no IP change. Or split G4 into
   G4a/G4b if early cash matters more than pro-rata protection.
3. **N2, B.3** — "eight to nine months" → "eight to eleven months". Costs nothing under §3.2 and
   removes a week-26 conversation.

**Optional, to have available in negotiation:**

4. **N4** — draft Option 4 (console presentation reduction, $5,000–7,000) so the ladder can reach the
   absorbed scope. Do not lead with it.
5. **N5** — brief MIT explicitly that its quality remedy is the §14.2 off-ramp at G5, not a quality
   level. Better said than discovered.
6. Prepare the Article 8 fallback now — a royalty or fee credit to MIT on commercial licensing within
   N years, or named-contribution credit — so that §8.4 has an answer that costs nothing unless the
   Platform succeeds commercially.

**Not contract items:** budget the $3k–10k of self-funded agentic tooling; run pipeline stages 1–3 once
against the design document **before** the Effective Date, so G0's two weeks are not the first time the
harness meets a 3,457-line input.

## Bottom line, second pass

The revision did what the first pass asked and did it well: every finding is closed, the arithmetic is
clean, and the drafting around price-and-IP-as-one-bargain (B.1(b)–(d)) is the right structural answer
to holding $135,000. **The agreement is now fair to MIT without qualification, and fair to the Consultant
conditionally** — the condition being Article 8, which after option (a) carries the entire economic
justification for the fee.

Three things remain, and they are small next to what was fixed. One is a genuine defect (**N3**, one
sentence). One is a real misallocation that costs nothing to fix (**N1**, re-weight G4). One is honesty
about the calendar (**N2**, nine months → eleven). Fix those and the document is ready to execute.

The single thing to carry into the negotiation is not in any of them: **the Consultant has already spent
its concession.** The console went in for free, the descope ladder cannot reach it, and B.4 is now at
ordinary rates. There is no further room below $135,000 that does not come out of Article 8 — and
Article 8 is what makes $135,000 make sense.
