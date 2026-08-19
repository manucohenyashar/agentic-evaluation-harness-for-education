# Agentic Evaluation for Education: A Research-Grounded Architecture for a Local, Open-Source Grading Harness

*A research report for engineers and executives. Prepared for the design of a teacher-facing evaluation harness that runs on open-source models on local hardware, for deployment in schools with limited or no reliable internet connectivity.*

---

## 0. Problem statement

### 0.1 The problem this system exists to solve

Feedback is among the highest-leverage interventions available to a teacher, and it is the first thing that disappears when a teacher is overloaded. Grading thirty constructed responses with substantive per-criterion comments is several hours of work.

**In the target deployment, classes run from 150 to 350 students.**

At that size the arithmetic stops being about slower feedback and becomes about no feedback at all. A single set of 250 essays, at even four minutes each for a genuine read and comment, is more than sixteen hours of continuous work for one assessment, for one class. No teacher does this. What happens instead is one of two adaptations, and both are damaging:

1. **The assessment stops being graded meaningfully.** Work is collected, spot-checked, and returned with a mark that carries little information, or returned late enough that it no longer connects to anything.
2. **The assessment format degrades to what is mechanically gradeable.** Constructed responses, worked problems, short essays, and lab writeups get replaced by multiple choice, because multiple choice is the only thing that can be graded at n=350. The assessment instrument is chosen by grading capacity rather than by what the teacher actually wants to know.

The second adaptation is the more serious one and the less visible one. It means that in these classrooms, the kinds of work that develop and demonstrate reasoning are not merely under-assessed, they are **often not assigned at all**. A curriculum can quietly narrow to fit the grading bottleneck, and the resulting learning outcomes then look like a teaching-quality problem when they are actually a throughput problem.

This is the gap the system targets. **The relevant comparison is therefore not "is this system as accurate as a teacher grading carefully."** In a 30-student classroom that would be the right benchmark. At 250 students the counterfactual is no substantive feedback at all, and frequently no constructed-response assignment in the first place. The system is not competing with careful human grading; it is competing with a blank.

That reframing raises the value of the system and, importantly, **does not lower the quality bar**, for a reason worth stating plainly: a bad score still lands on a real student's record, and a teacher who catches the system being wrong twice will correctly abandon it. What the reframing does change is the shape of the goal. The objective is not to replicate a teacher's marking. It is to return two things that currently do not exist at this class size: **per-student evidence-grounded feedback**, and **a class-level diagnostic view** telling the teacher which criteria the cohort actually missed.

The second of those may be the larger prize. A teacher with 300 students has essentially no visibility into aggregate misconceptions, because forming that picture requires holding 300 papers in your head. A per-criterion breakdown showing that 210 of 300 students missed the same conceptual step is information that reshapes the next lesson, and at n=300 it is also **statistically solid** in a way the same analysis at n=30 is not (Section 3.5).

This pressure is not evenly distributed globally. According to UNESCO and the International Task Force on Teachers for Education 2030, sub-Saharan Africa averages roughly **one trained teacher per 58 students at primary level and roughly 43 at secondary**, against global averages closer to 26 and 19 respectively, and the region needs on the order of **15 million additional teachers** to meet 2030 education goals. Southern Asia carries the second-largest teacher shortage globally, concentrated at the secondary level. Individual classes in the target settings run well above these national averages.

The intended deployment context includes teacher-development and curriculum programs in Nigeria and comparable settings in India, where the constraint is not enthusiasm or teacher capability but time, class size, and infrastructure.

### 0.2 The deployment reality, and what it rules out

The design constraints below are not preferences. Each one eliminates an architecture that would otherwise be the obvious choice.

**Scale is the dominant constraint.** A 350-student class with a five-question assessment and three rubric criteria per question is 15 criteria, which at full three-judge panel depth is 15,750 scoring judgments plus 5,250 extraction calls plus synthesis, on the order of **23,000 model calls for one assessment for one class**. This is an order of magnitude beyond what a 30-student design has to survive, and it invalidates several choices that are perfectly reasonable at classroom scale. Section 8.4 works the throughput arithmetic; Section 7.1 revises the panel design in response. Treat every "this is cheap" claim in the rest of this report as needing to be re-checked against n=350.

**Connectivity is intermittent, not merely slow.** A frontier-model API requires a working connection at the moment of grading. In the target settings, connectivity is unreliable on a timescale of hours to days. A system that fails when the network fails is a system that fails on the day the teacher actually needs it, and worse, it fails unpredictably, which is what destroys trust in a tool. **In the offline school deployment, the harness must run to completion with the network cable unplugged.**

Note carefully what this does and does not rule out, because version 2.4 overstated it. It rules out a design that *can only* reach a remote inference service — a system with a hard network dependency is unusable in the target schools. It does **not** rule out the system supporting a remote inference service, and §0.7 makes supporting one a requirement. What it rules out specifically is the **hybrid fallback**: a run that begins against one backend and silently switches to another when the first stalls, because a path exercised rarely is a path that is never validated, and because a run whose scores come from two different model backends is not a run whose statistics mean anything. The resolution is that the backend is **selected by configuration before a run starts and is fixed for the life of that run**, with both backends first-class and both routinely exercised. The cost argument likewise scopes to the offline profile: at n=350, per-token pricing is a real recurring expense that a school with a capital budget and no operating budget cannot absorb, which is why local inference remains the answer *there* — not a reason the system may not run in a datacenter for a program that is funded differently.

**Power is stable, via solar.** This is a real advantage over the default assumption for the region and it changes what is feasible: multi-hour uninterrupted batch runs are on the table, which is precisely what n=350 requires. It does **not** remove the need for checkpointing and resumability (Section 8.4), but it changes the justification. A run of this size takes hours, and over hours the realistic failure modes are software crashes, an out-of-memory condition on a model swap, a corrupt input file, or an operator stopping the job, not grid failure. A two-hour run that must restart from zero because submission 240 was malformed is unacceptable regardless of how reliable the electricity is. Resumability is a function of run *duration*, not of power reliability.

**Per-token cost is not a rounding error.** At 23,000 calls per assessment per class, frontier API pricing that is negligible against a US software budget becomes a recurring operating expense that scales with how much teaching you do. A capital purchase of one machine that then grades without marginal cost is a fundamentally different financial proposition. The economics must favor using the system more, not less, and at this scale only local inference does that.

**In the offline school deployment, student work should not leave the school.** Beyond FERPA-style regulatory questions, transmitting minors' work to a foreign commercial cloud is a governance conversation that many education ministries and school leaders will reasonably decline to have. Local execution resolves this architecturally rather than contractually, which is a materially stronger position (Section 11). In the cloud profile that advantage is not available and has to be replaced with explicit contractual and technical controls — zero-retention routing, regional hosting, a data-processing agreement — which §0.7 and Section 11 specify. The important thing is that this is a *profile-level* difference the operator chooses with open eyes, not a property some deployments quietly lose.

**In the offline school deployment, hardware is a single machine, not a cluster.** The realistic unit of deployment is one reasonably-specified computer per school or per program, shared across teachers, running overnight batches rather than interactive sessions. Apple Silicon's unified memory makes a single machine in this class genuinely capable (Section 8.1), and the architecture is portable to comparable non-Apple hardware, but nothing in the edge profile may assume horizontal scale-out. The cloud profile lifts this constraint — it may scale concurrency horizontally — but it may not require doing so, because the same code has to run in the single-machine case.

**Teacher review time does not scale with class size, and this is the constraint most likely to be missed.** The confidence-routing design (Section 5.8) sends uncertain judgments to the teacher. At 30 students a 15% flag rate is about 68 review items, which is manageable. At 350 students the same rate is roughly 790 items, which is not a review queue, it is a second full-time job. **Any design that routes a fixed *percentage* to human review has failed at n=350.** The review queue must be budgeted in teacher-minutes and ranked by expected value, which is a requirement (R12) that simply does not arise at classroom scale. Section 10 specifies it.

**The same test is administered many times.** A teacher runs the same course across sections, terms, schools, and years, and the assessment is reused with it. Rubric tuning (Section 6) is the largest teacher-time investment the system asks for, and repeating it per cohort would violate R9 outright. The tuned assessment must therefore persist as a reusable artifact and be portable between institutions **offline**, since the network that would sync it does not exist. Section 9.4 specifies the package format; the practical consequence is that packages travel on a USB stick and must be a single self-contained file.

**Ingestion is a real subsystem at this scale.** Three hundred and fifty handwritten submissions is not a file-upload step, it is a scanning and transcription pipeline with its own error modes, and transcription failures on a student's handwriting will look exactly like a student who wrote nothing. Stage A needs explicit low-confidence handling that routes to the teacher as a *transcription* problem rather than silently scoring a garbled response as wrong. It also needs to catch the structural mistakes that arrive with paper at this volume — missing pages, duplicated scans, and answer sheets handed in against the wrong paper — because every one of those produces a low grade that looks like a student who did badly. Section 7.7 specifies the module; Section 7.5 specifies how its uncertainty is routed.

### 0.3 The central engineering problem

Those constraints force open-weight models in the range a single machine can hold, which are meaningfully less capable than frontier models at holistic judgment. And yet:

**A grading system that is not trustworthy is worse than no grading system at all.** An unreliable score attached to a student's record does real harm, and a teacher who catches the system being wrong twice will correctly stop using it. Quality is not a dimension we are permitted to trade against cost here. If anything, the trust bar is *higher* in a setting where the teacher has less time to check the system's work.

So the engineering problem is precisely this:

> **How do we obtain evaluation results trustworthy enough to inform real grades, using models substantially weaker than the frontier, on one machine, with no network?**

The answer this report develops is that **architecture can substitute for model scale**, within limits that need to be measured rather than assumed. The empirical basis for that claim is not wishful: AutoSCORE (AAAI 2026, Section 4) found that decomposing scoring into an evidence-extraction step followed by a scoring step improved accuracy for every model tested, **with the largest relative gains on the smaller open-weight models**. The gap between an 8B model and a frontier model narrows when the 8B model is asked to do a narrow, well-specified thing rather than a broad, holistic one. Similarly, a panel of diverse smaller models has been shown to outperform a single large judge (Section 5.1), and rubric decomposition into atomic criteria improves agreement independent of model choice (Section 5.3).

Every architectural decision in this report is an instance of that same move: **take work the frontier model would have done implicitly inside one large judgment, and make it explicit, narrow, and verifiable.** Extraction before scoring. One criterion per judgment. Evidence citation as a hard requirement. Panel diversity instead of model size. Confidence routing so the system's uncertainty becomes visible rather than hidden. None of these require a bigger model, and several of them work *better* on smaller ones.

### 0.4 Derived requirements

The rest of the report can be read as a response to these. Requirement IDs are referenced where relevant.

| ID | Requirement | Derives from | Addressed in |
|---|---|---|---|
| **R1** | **In the edge profile**, runs to completion fully offline, with no network service in the critical path; in *every* profile, the inference backend is fixed at run start and no run may fail over to a different backend mid-flight | Intermittent connectivity; comparability of scores within a run | §0.7, §8.1, §8.2 |
| **R2** | Fits on a single machine, with model weights that can be swapped rather than held concurrently | Single-machine deployment | §7.1, §8.1, §8.4 |
| **R3** | Resumable at fine granularity without redoing completed work, because runs last hours | Run duration, not power | §8.4, §9.4 |
| **R4** | **In the edge profile**, student work never leaves the machine, including intermediate artifacts. In the cloud profile the equivalent protection is explicit and configured — zero-retention routing, regional hosting, a data-processing agreement — and is surfaced to the operator rather than assumed | Data sovereignty | §0.7, §9.8, §11 |
| **R5** | **In the edge profile**, zero marginal cost per assessment after hardware purchase. In the cloud profile, per-run cost is estimated before dispatch and enforced against a configured ceiling | Cost structure at 23k calls/assessment | §0.7, §8.1, §8.3, §8.7 |
| **R6** | Evaluation quality sufficient to inform real grades, despite non-frontier models | Trust bar | §5, §7.2, §7.3 |
| **R7** | System uncertainty is visible and routes to the teacher rather than being hidden in a confident-looking number | Trust bar | §5.8, §10 |
| **R8** | Quality claims are honest and chance-corrected, never inflated agreement percentages | Trust bar, §2.1 | §2.5, §3.1, §6.8, §10 |
| **R9** | Teacher time cost of operating the system is minutes, not hours, including any calibration | Teacher time is the scarce resource | §6.4, §6.8 |
| **R10** | **Grades a 350-student assessment (~23,000 model calls) within an overnight batch window on one machine** | Class size | §7.1, §8.3, §8.4 |
| **R11** | Degrades gracefully: works with whatever the teacher provides, never blocks on optional inputs | Real classroom conditions | §6.9 |
| **R12** | **Human review queue is budgeted in teacher-minutes and ranked by expected value, never a fixed percentage of submissions** | Review time does not scale with n | §10 |
| **R13** | **Low-confidence transcription is surfaced as a transcription problem, not scored as a wrong answer** | 350 handwritten submissions | §0.2, §9.4 |
| **R14** | **Any run is resumable after interruption without redoing completed work, and rerunning is idempotent** | Multi-hour runs | §9.4, §9.5 |
| **R15** | **No component of the scoring path can retrieve from memory at inference time** | Judgment isolation | §9.1 |
| **R16** | **A tuned assessment and its calibrated rubric persist as a reusable package; a later cohort grades with zero retuning** | Teachers repeat tests across cohorts and schools | §9.4 |
| **R17** | **Packages are portable as a single self-contained file, transferable offline** | No reliable network between schools | §9.4, §9.12 |
| **R18** | **Per-cohort and per-package statistics persist, so a package's validation record compounds with use** | Validation accumulates (§6.8) | §9.7 |
| **R19** | **No single extraction error may produce unanimous panel agreement without an independent detection path** | Common-mode failure upstream of the panel | §7.4 |
| **R20** | **Teacher acceptance and independent teacher scoring are stored as different label types; only the latter is treated as ground truth** | Automation bias | §6.8, §9.7 |
| **R21** | **Every administration *offers* a small blind sample scored by the teacher without seeing system output. It is strongly recommended and never blocking: skipping it ships grades normally and stops the validation record advancing, which the system says plainly** | Unbiased validation, without making grade delivery hostage to teacher availability (R60) | §6.8, §10 |
| **R22** | **The routing policy is itself validated: measured on whether it actually sends errors to the teacher** | Confidence may be miscalibrated | §7.1, §6.8 |
| **R23** | **Package validation is population-scoped in the schema; there is no global "validated" flag** | Instruments do not transfer unconditionally | §9.5 |
| **R24** | **Transcription routing is based on whether an OCR error could change the score, not on OCR confidence alone** | OCR error correlates with student characteristics | §7.5 |
| **R25** | **Throughput is demonstrated on target hardware in a full-pipeline acceptance test, not inferred from arithmetic** | R10 is a hypothesis until measured | §8.6 |
| **R26** | **Unreviewed low-confidence scores are marked provisional and carried forward, never silently finalized or backfilled** | Review budget will run out | §10 |
| **R27** | **All model access goes through one provider abstraction. Local serving and OpenRouter are interchangeable implementations of it, selected by configuration. No stage of the pipeline may contain a backend-specific code path** | The same code must run offline at a school, in a container in CI, and in a datacenter | §0.7, §8.7 |
| **R28** | **The full pipeline runs to completion inside a Linux container on non-Apple hardware with every model call served by OpenRouter. This is the development and CI configuration and it is a supported deployment, not a test stub** | The system is built and tested on Windows-hosted containers, not on Macs | §0.7, §8.7, §12 |
| **R29** | **Cloud hosting is a first-class deployment target: the same harness, the same open-weight models, served through OpenRouter, for programs with connectivity and no capital budget for hardware** | Not every deployment is a disconnected school | §0.7, §8.7, §9.12 |
| **R30** | **Backend equivalence is measured, never assumed. Every validation record is scoped to the backend, model build, and quantization that produced it, and a conformance suite runs identical fixtures against local and OpenRouter backends** | A 4-bit local quantization and a hosted build of "the same" model are different graders | §0.7, §8.5, §8.7, §9.5 |
| **R31** | **No real student work is sent to any remote provider outside a deployment explicitly configured and consented for it. Development and CI corpora are synthetic or consented; cloud production runs require zero-retention routing** | Testing must not become an exfiltration path | §0.7, §9.14, §11 |
| **R32** | **Transcription produces one canonical, content-hashed, immutable Markdown artifact per document. Every evidence span is a byte offset into it; re-transcription creates a new version and invalidates dependent work rather than editing in place** | §7.4 verifies span offsets against source bytes; a mutable source makes every stored span a lie | §7.7 |
| **R33** | **A document arriving as several PDFs is assembled deterministically, with per-page provenance recorded, and duplicate or missing pages are detected rather than silently concatenated** | Multi-file submissions are the norm, not the exception | §7.7 |
| **R34** | **Every artifact passes structural validation before it can enter Stage C. Validation failures quarantine as ingestion problems and are never expressed as scores** | Extends R13 from OCR confidence to document structure | §7.7, §9.11 |
| **R35** | **Every submission is validated as belonging to the assessment it is about to be graded against. Mismatch and uncertain both halt scoring for that submission and route to a human; the system never reassigns a submission to a different assessment automatically** | A wrong-test submission produces a confident unanimous zero that no downstream gate can detect | §7.7 |
| **R36** | **Absent content and blank content are distinguished at ingest. A missing page is an ingestion failure; an intentionally blank answer is a score of zero. Only the latter may reach scoring** | "Empty ≠ zero" (§7.4) applied upstream, where the distinction is still recoverable | §7.7, §7.4 |
| **R37** | **The transcription model is version-pinned, backend-scoped, and validated on the actual submission medium exactly like a panel member — and it is selected independently of the panel, on transcription quality alone** | It is a model in the scoring path's supply chain, and its output quality bounds every grade; but it makes no judgments, so panel-selection criteria neither qualify nor disqualify it | §6.7, §7.7, §8.2 |
| **R38** | **Evaluation happens against Markdown, never against a PDF. Every PDF of every artifact kind is converted by the ingestion module; no stage downstream of ingestion ever receives a PDF or a page image, and there is no second path by which a PDF becomes text** | Evidence spans are byte offsets into a text artifact; a judge handed an image has nothing to cite and the whole evidence-citation discipline silently stops applying | §7.7, §7.4 |
| **R39** | **Judges emit an ordinal band label from a closed, criterion-specific set. Numeric points are derived orchestrator-side from a pinned band→points table. No point value, `max_points`, or numeric scale appears in a judge's prompt or output** | Continuous numeric scales produce central-tendency bias; a judge that never sees a number cannot drift toward the middle of one | §5.10 |
| **R40** | **Every band carries a behaviourally-anchored descriptor stating what a response in that band does. Band sets are even-numbered so there is no default middle, and binary (met / not met) is the default — graded bands require justification** | "Which of these is true?" is checkable; "how good is this out of five?" is a magnitude judgment, and magnitude judgments attract the centre | §5.10, §5.3 |
| **R41** | **Panel aggregation happens on the ordinal band scale; the band→points mapping is applied once, after aggregation. Averaging band-derived points is forbidden** | Averaging band numbers reconstructs the continuous scale the bands exist to remove, and lands on values no band describes | §5.10, §7.3 |
| **R42** | **The judge's response is generated evidence-first: cited spans, then the evidence assessment against the band descriptors, then the band. Enforced by response-schema field order and linted like §8.4's prompt ordering** | Field order is generation order; emitting the verdict first produces a snap judgment followed by a confabulated justification | §5.10, §8.4 |
| **R43** | **The band set and the band→points mapping are covered by the §6.2 schema lock, version-pinned, and any change passes the §6.5 non-inferiority gate** | Tuning the mapping against teacher scores moves every grade without touching a judge — construct drift by a new route | §5.10, §6.2, §6.5 |
| **R44** | **The MVVP includes a score-compression check comparing the panel's band distribution against blind gold labels, with its shared-bias blind spot recorded as a known limit** | Compression is invisible to agreement metrics: judges that all compress agree with each other | §2.5, §5.10 |
| **R45** | **Every non-text region is emitted into the Markdown as a structured description dense enough for extraction to localize any fact a criterion could turn on: arrow labels and directions, named points and marked relations, axis labels and intercepts, what each label attaches to, and spatial relations stated explicitly** | Diagrams, graphs and spatially-encoded tables carry the reasoning being assessed, and none of it survives a pass that only lifts characters off the page | 7.7 |
| **R46** | **A description is descriptive only, never evaluative, and evidence cited from a described region is marked as such, retains its image crop for teacher review, and triggers impact routing** | A verdict smuggled into a description is inherited by every judge and produces unanimity that the integrity gate cannot see; and span verification proves faithful quotation of a description, never fidelity of that description to the drawing | 7.7, 7.4, 7.5 |
| **R47** | **Struck-through work and handwritten corrections are preserved and marked as retracted or superseding, never silently flattened** | Which version counts is a rubric question, not a transcription question; once crossed out has become not written, nothing downstream can recover the difference | 7.7, R36 |
| **R48** | **Panel size is always odd — 1, 3 or 5, never 2 or 4 — and escalation moves 1 → 3 without passing through 2. Enforced as a CHECK constraint on `judge_count`** | A median needs a unique middle; every tie-break rule for an even panel is a hidden severity or leniency bias falling exclusively on the judgments that were already the hardest | §5.10, §7.1 |
| **R49** | **No rubric criterion is decomposed without an explicit, recorded decomposability determination confirmed by the teacher. When the answer is unclear the criterion is preserved as written: decomposition is the intervention, preservation is the null action** | Preserving a weight does not preserve a construct; a configural criterion is redefined by decomposition however the points add up | §5.3, §6.2 |
| **R50** | **Criteria classified `holistic` are scored as a single judgment against band descriptors, start at full panel depth with no single-judge base, and carry a lower auto-acceptance ceiling** | They are the judgments decomposition could not simplify, routed to the mode a sub-frontier panel is weakest at | §5.3, §7.1 |
| **R51** | **Agreement statistics are reported separately for atomic and holistic criteria; a package headline figure may never merge them** | They will differ and the holistic ones will be worse; merging produces a number describing neither | §5.3, §9.5 |
| **R52** | **Evaluation mode is a property of the criterion, not the question: a criterion is `judged` or `deterministic`. Deterministic criteria are scored by lookup against a teacher-supplied answer key and never sent to the panel. Question types (open, mcq, mixed) are proposed at assessment ingestion, confirmed by the teacher, and locked under §6.2** | The key is ground truth by definition, so there is nothing for a judge to be uncertain about. Criterion-level mode is what makes "circle the answer and explain your choice" expressible at all | §7.8 |
| **R53** | **Deterministic-item correctness never enters any agreement, κ, or grader-quality figure. It is reported separately from the judged portion of the test** | MCQ items agree with the teacher essentially always; merging them inflates the headline with items that involved no judgment, and rewards the format §0.1 exists to stop crowding out constructed response | §7.8, §9.5, §10 |
| **R54** | **Uncertainty about a multiple-choice item is a transcription problem routed to operator triage, never to the teacher grade-review budget** | The remedy is a rescan or a glance at the crop, not a judgment; mixing them lets smudged bubbles compete with genuine grade disputes for the same thirty minutes | §7.8, §7.5 |
| **R55** | **An ambiguous, multiple, or unreadable selection mark is surfaced as such and never silently resolved to an option or scored as incorrect** | R36 applied to mark reading: a student who selected correctly in handwriting the scanner could not resolve has not answered wrongly | §7.8 |
| **R56** | **Every submission receives a complete final grade computed automatically, with no per-student teacher action. Teacher effort scales with the review budget they choose, never with class size** | This is the system’s reason to exist (§0.1). Producing criterion judgments but leaving a human to compile 350 grades reproduces the bottleneck one level up and delivers nothing | §7.9 |
| **R57** | **The teacher declares a grade policy once — how criteria combine into question scores, questions into a total, and totals into a grade — stored in the package, locked under §6.2, version-pinned, and applied automatically thereafter. It is declarative, never a script** | Combining marks is a professional decision that varies by subject and institution; a hardcoded weighted sum is a policy masquerading as a mechanism. Declarative keeps it approvable in plain language and reproducible for an appeal | §7.9, §6.2 |
| **R58** | **Provisional inputs never withhold a grade. The grade is issued with a coverage record, and shown as a range only where unreviewed items could move the student across a boundary. Only a genuinely missing score — an ingestion failure — renders a grade incomplete, and that routes to the operator** | Provisional means labelled, not withheld. An unreviewed grade honestly labelled is the product; a withheld grade is a failure to deliver it | §7.9, §10 |
| **R59** | **Grade boundaries are a declared object in the package** | §10 ranked review by proximity to a boundary and ReviewItem carried a boundary delta, while nothing defined one — the ranking was not computable | §7.9, §10 |
| **R60** | **After the setup phase, no stage may block grade delivery on a teacher action. Every remaining teacher touchpoint is an offer, and the cost of skipping it is stated rather than paid in undelivered grades. A run started with zero subsequent teacher input completes, finalizes, and delivers a full set of grades** | The teacher’s time buys calibration once and sampling thereafter. Any per-run gate makes 350 students’ grades hostage to one person’s availability, which is the bottleneck §0.1 exists to remove | §7.9, §6.8, §10 |

R9 and R12 deserve emphasis because they are easy to violate accidentally and they interact. **Any design that asks the teacher for significant up-front effort, or that hands back a review queue proportional to class size, has failed at the thing it was built to fix.** This is the reasoning behind treating calibration as a few short elicitation questions rather than a labeling task (Section 6.4), behind harvesting validation data from the teacher's ordinary review actions rather than requesting it (Section 6.8), and behind budgeting the review queue rather than thresholding it (Section 10).

### 0.5 What we will not trade away

Under pressure, the following are not available as optimizations. Each is somewhere a constrained deployment would be tempted to cut, and each cut would be invisible in the metrics the system reports about itself:

- **Automatic grading of the bulk.** Every submission gets a complete final grade without per-student teacher action (R56). Teacher time buys calibration at the front and sampling afterwards; it is never spent compiling grades. Under schedule pressure the tempting cut is to ask the teacher to “just check these few hundred” — that is not a degraded version of this system, it is the absence of it.
- **The teacher remains accountable for grades.** The system is formative decision support. Section 4's K-12 research is explicit that this is also what teachers and students will accept.
- **Judgment isolation** (Section 7.2). It is the cheapest place to buy speed and the most damaging place to buy it.
- **Honest statistics** (Section 3.1, Section 3.5). No inflated agreement numbers, no accuracy claims from eight-sample calibration sets.
- **Version pinning and auditability** (Section 6.7). A grade that cannot be explained cannot be defended, and in a resource-constrained school the ability to defend a grade may matter more, not less.
- **Backend-scoped validation** (Sections 0.7, 8.7). A validation record describes an instrument *and* the grader that produced it. Quoting agreement statistics measured on one backend as if they described another is the same error as quoting raw agreement as if it were chance-corrected, and it will be tempting precisely because the cloud profile accumulates labels faster.
- **Construct validity** (Section 6). A rubric that has drifted into measuring response length will produce excellent-looking agreement statistics and systematically mis-serve exactly the students who write less fluently, which in multilingual settings is a serious equity failure mode.

### 0.6 What success looks like

A teacher with 300 students in a school running on solar power and with no reliable internet sets a constructed-response assessment, which today they would not set at all because it could not be graded. The submissions are scanned into a machine in the staff room in the evening. The batch runs overnight.

The next morning the teacher has: per-student criterion-level narrative feedback grounded in citable evidence from each student's own work; a review queue sized to the thirty minutes they actually have, ranked so the items that could move a student across a grade boundary come first; and a class view showing that 210 of 300 students missed the same conceptual step in question 3. They keep final authority over every score. They walk into the next lesson knowing exactly what to reteach, to whom.

The measure of success is not that the system grades as well as a teacher would have. It is that **work which is currently not assigned, because it cannot be graded, becomes assignable** — and that the feedback students receive goes from nothing to something specific, evidenced, and timely.

The rest of this report is about what the research says it takes to get there without the result being untrustworthy.

### 0.7 Deployment profiles: local and cloud are both first-class 

Everything above describes the hardest deployment — a disconnected school on solar power — and versions 2.0 through 2.4 wrote the architecture as if that were the *only* deployment. That was a mistake, and it is corrected here.

**The design MUST support cloud hosting, and MUST support serving every model call through OpenRouter, as first-class supported configurations rather than as a degraded mode or a test fixture.** Two independent reasons, and either one alone would be sufficient:

1. **This is how the system gets built and tested.** Development and CI run in a Linux container on Windows hosts. There is no Apple Silicon in the loop, no MLX, and no local model server. Every model call in every automated test goes to OpenRouter. A design that only works on a Mac with Ollama is a design that cannot be tested, and an untested grading system is not shippable at any quality bar, let alone this one.
2. **A large share of real deployments will be hosted.** The offline school is the hardest case, not the only case. A teacher-development program with reliable connectivity, a district running a central instance for many schools, a pilot that needs to start next week without a hardware procurement cycle — all of these are better served by a hosted instance running the same open-weight models through OpenRouter than by shipping Macs. Refusing to support them narrows the system to the subset of users who can buy hardware first.

#### The three profiles

| Profile | Where it runs | Inference | Primary purpose | R1 offline guarantee |
|---|---|---|---|---|
| `edge-local` | One machine at the school (Apple Silicon reference; consumer GPU per §8.1) | Local server — MLX / vLLM-MLX / Ollama / llama.cpp | The disconnected-school deployment of §0.2 | **Required.** Runs with the cable unplugged |
| `cloud-hosted` | Container in a datacenter | **OpenRouter**, same open-weight model families | Connected schools, districts, programs without capital budget | Not applicable — network is the substrate |
| `dev-ci` | Linux container, typically on a Windows host | **OpenRouter** | Development, automated tests, the acceptance harness | Not applicable |

`dev-ci` and `cloud-hosted` are the same code path with different data, budget ceilings, and governance settings. That is deliberate: it means the cloud deployment is exercised on every commit, by construction.

#### The rule that keeps this from becoming the thing §0.2 warned about

Version 2.4 argued that a rarely-exercised fallback path is never really validated, and used that to forbid cloud inference outright. The argument is right; the conclusion was too broad. What it actually forbids is **runtime failover**, and that prohibition stands and is now R1's second clause:

> **The inference backend is chosen by configuration before a run begins and is fixed for the entire run.** A run never fails over from local to OpenRouter or back. If the configured backend becomes unavailable mid-run, the run pauses and resumes against the *same* backend (§9.10's ledger makes this safe), or it is abandoned and restarted. It never silently completes on a different grader.

The reason is not purity. A criterion scored by a local 4-bit quantization and a criterion scored by a hosted build of nominally the same model are two different graders (§2.2: rankings do not transfer). A run that mixes them produces per-criterion scores that are not comparable to each other, which corrupts the class-level rollup, the confidence gate, and every statistic in the validation record — silently, in exactly the way §3.6 describes.

Note the argument now cuts the *other* way as well, and this is the thing most likely to be missed. Because `dev-ci` runs on OpenRouter continuously, **the OpenRouter path will be the best-tested path in the system and the local path will be the under-exercised one.** The under-tested backend is the one deployed to schools with no IT support. Two mitigations, both mandatory:

- **The hardware acceptance test (§8.5) runs on the `edge-local` profile and gates any edge deployment.** It cannot be satisfied by a cloud run.
- **A backend conformance suite (§8.7) runs the same frozen fixtures against both backends** and reports where they diverge, so divergence is a measurement rather than a surprise.

#### The provider abstraction (R27)

One interface, two implementations, chosen by configuration:

```
InferenceProvider
  .complete(prompt, model_ref, params) -> completion + usage + provider metadata
  .capabilities() -> {supports_seed, supports_prefix_cache, max_concurrency,
                      deterministic_at_temperature_zero, cost_per_token}
```

Constraints that make the abstraction real rather than nominal:

- **No stage of the pipeline may branch on which backend is in use.** Extraction, scoring, synthesis, and the isolation rules of §7.2 are identical in both. If a stage needs to know, that is a capability question and belongs in `capabilities()`.
- **Everything §8.4 forces stays forced in both.** Prompt field ordering, criterion batching, the student submission last, one criterion per call, no cross-submission context. The cache mechanics differ — a local server holds a prefix tree in its own KV cache, a hosted provider may or may not expose prompt caching — but the *prompt construction* does not vary, because varying it would change scores.
- **Capability differences are declared, not discovered at hour two of a batch.** Seed support, determinism at temperature 0, achievable concurrency, and prefix-cache behavior all differ by provider and by model. A run records what it actually had (§9.7), so a validation record can never be read as if it came from a configuration it did not.
- **`model_ref` is a resolved build identity, not a friendly name.** "Llama 3.3 70B" is not a grader; a specific OpenRouter model slug pinned to a provider and served build, or a specific local GGUF at a specific quantization with a weights hash, is. §6.7's version-pinning requirement covers both, and R30 makes validation records carry it.

#### What cloud hosting changes, stated plainly

| Concern | `edge-local` | `cloud-hosted` |
|---|---|---|
| Data sovereignty (R4) | Architectural — work never leaves the machine | Contractual and configured: zero-retention routing, regional hosting, DPA. Must be shown to the operator, not buried |
| Marginal cost (R5) | Zero after purchase | Real and per-token. A pre-dispatch cost estimate and an enforced ceiling are required (§8.7) |
| Throughput (R10) | Bounded by one machine's memory and thermals (§8.4) | Bounded by provider rate limits and budget, not by hardware. Usually easier |
| Model identity | You control the exact weights | The provider controls the served build and may change it under a stable slug (§8.7) |
| Failure modes | OOM, thermal throttling, disk | Rate limits, provider outages, silent model substitution, cost overrun |
| Privacy story | A headline feature | A managed risk with named controls |

The cloud profile is genuinely better on some of these and genuinely worse on others. It is not the offline profile with the constraints relaxed; it is a different set of constraints, and Sections 8.7 and 11 specify the controls each one needs.

### 0.8 The approach to bias: structural prevention, independent measurement, asymmetric confidence

Bias is not one risk in this design; it is the dominant category of risk, and it has a property that determines the entire strategy for handling it. **Every bias this system is exposed to makes the system's own quality numbers look better, not worse.** Judges that compress toward the middle of a scale compress together, so inter-judge agreement rises (§5.10). Judges sharing a contaminated context converge, so agreement rises (§7.2). Judges reading the same corrupted evidence agree unanimously, so confidence rises (§7.4). A teacher rubber-stamping a review produces a label recording that the system was right (§6.8). A rubric optimized toward a teacher's scores while abandoning their standards improves measured agreement precisely as it stops measuring the intended construct (§3.6). In every case the instrument moves the wrong way. A monitoring-based strategy — ship it, watch the dashboard, react when the numbers degrade — is therefore not a weak approach here, it is an actively inverted one, and this is the single most important thing to understand about why the architecture looks the way it does.

Three principles follow, and nearly every design decision in this report is an instance of one of them.

**First, prevent structurally rather than instructing behaviourally.** Where a bias can be made impossible in the data model, it is, because a constraint a component cannot violate is worth more than a rule it is asked to follow. A prompt saying "do not let the rubric weights drift" is a request; a schema in which weights are not a writable field is a guarantee (§6.2). The same move recurs throughout: the judge request schema is a whitelist with no field for another judge's verdict, so cross-contamination is a schema violation rather than a lapse (§7.2); the synthesis result schema has no points field, so narrative composition cannot move a grade (§7.2 Rule 3); judges receive band labels with no numeric scale at all, so there is no scale midpoint to drift toward (§5.10, R39); and response field order is part of the contract, so the verdict cannot be emitted before the evidence that justifies it (R42).

**Second, measure with an instrument the bias cannot reach.** Where prevention is impossible, the measurement must be independent of the thing being measured. Accuracy is computed only from **blind** labels, where the teacher grades without seeing system output, because acceptance labels measure agreement with the machine rather than correctness (§6.8, R20/R21). Agreement is always chance-corrected, since raw percentages overstate by 33 to 41 points (§2.1). Rubric revisions are checked by an **off-panel** model that shares no blind spots with the judges (§6.6), and validated against a held-out set the system is never tuned on. Validation records are scoped to a population and a backend, so a number earned in one context cannot be silently read as applying to another (R23, R30). And escalation triggers on observable signals — disagreement, missing evidence, proximity to a grade boundary — rather than on a model's self-reported confidence, because a model's opinion of its own reliability is exactly the quantity a biased model gets wrong (§7.1).

**Third, make confidence asymmetric, and invert it where a bias would inflate it.** The system's uncertainty is a first-class output rather than something smoothed away. Unanimous agreement on evidence that failed integrity checks yields **low** confidence, not high, which is the confidence calculation running backwards from intuition on purpose (§7.4, R19). Low-confidence transcription routes on whether an error *could change this criterion's score*, not on a document-level quality number (§7.5, R24). Submissions that may belong to a different assessment halt on `uncertain` as well as on `mismatch`, because a binary gate forces a bad trade and the ambiguous cases fall disproportionately on the students already least well served (§7.7, R35). Unreviewed items stay visibly provisional rather than being quietly finalized (R26). The through-line is that the system is built to make its own doubt visible to a human rather than to resolve it in favour of a confident-looking number.

What this approach does not do is claim the biases are eliminated. §11 records what remains, including the ones the design can only partially defend: transcription quality that tracks handwriting and language fluency rather than understanding, an override log that over-represents hard cases, and score compression shared between the panel and the teacher, which a check comparing one against the other cannot see. Naming those is part of the strategy rather than a caveat on it — a system claiming to have solved bias is making the same category of error as one reporting uncorrected agreement percentages.

---

## How to read this report

You already know the fundamentals of agentic evaluation: build ground truth, evaluate the full trajectory rather than just the final answer, and measure the judge itself rather than trusting it blindly. This report does not re-cover that ground. Instead it distills what the **last twelve months of research** adds on top of those fundamentals, and translates those findings into a concrete architecture for a system where:

- A teacher uploads a **test or assignment**.
- The teacher uploads a **definition of good**, meaning a solution or answer key.
- The teacher uploads a **rubric**.
- The teacher uploads a **batch of student submissions**.
- The system returns a **per-student evaluation** and a **class-level rollup**, using **open-weight models rather than a paid frontier API** — served either locally on the school's own machine or through **OpenRouter** when the deployment is hosted (Section 0.7). The model family and the pipeline are the same either way; only the provider behind the abstraction changes.

Every statistical term is explained in plain language the first time it appears. A glossary repeats the short versions at the end of Section 3. Section 0 states the problem and the derived requirements (R1 to R31) that the architecture answers; readers who want the motivation and constraints before the research should start there, and readers who only want the design can start at Section 5. **Readers who care about how this is hosted, tested, or deployed to anything other than a Mac should read Section 0.7 and Section 8.7**, which specify the deployment profiles and the OpenRouter path.

---

## 1. The founding idea, tested

Your working hypothesis is that a student completing an assignment and an AI agent completing a task are structurally the same kind of thing: an intellectual entity turning a **goal plus context** into an **output**, which can then be scored against a **rubric** and a **reference answer**. That hypothesis holds up well, and it is why the last year of agentic-evaluation research, most of which was written about grading *models* rather than students, transfers directly to grading *people*. Three 2026 papers make the transfer explicit:

- **AutoSCORE** (Wang et al., AAAI 2026) treats a student's constructed response exactly like an agent trajectory. The response is first decomposed into rubric-relevant *components*, and only then are those components scored, rather than asking a model to read the whole response and produce a single number. This is "evaluate the trajectory, not just the final answer," applied to a paragraph instead of a tool-call sequence.
- **RULERS** (arXiv:2601.08654) formalizes rubric-based text scoring as an evidence-grounded pipeline. Every rubric checklist item is assigned an *evidence type*, the judge must cite the span of the response that satisfies it, and that citation is verified against the source text before a score is assigned. Same discipline as trajectory verification: cite your evidence, do not simply assert.
- **Creating and Evaluating K-12 GenAI Assessment Graders** (Tian et al., University of Washington and Colleague AI, 2026) is the most direct education-specific validation. It runs a real interrater-agreement study against Massachusetts Comprehensive Assessment System (MCAS) data using Claude Sonnet 4, Claude Haiku 4.5, GPT-5, and GPT-5 Mini as graders, and reports the same reliability statistics that agentic-eval researchers report for LLM judges.

**Where the analogy needs a caveat.** A coding agent's trajectory is usually evaluable against an objectively correct outcome: tests pass or they do not. A student's constructed response is not. A partially correct answer is common, and it *is the hard case*, not the exception. The physics-exam study in Section 4 finds human-AI agreement is strong at the top and bottom of the performance range and weakest for exactly these ambiguous, partial-credit, middle-of-the-distribution responses. The architecture has to be built around that weak point.

There is a second disanalogy, and version 1 did not take it seriously enough. When you evaluate an agent, you own the rubric. You wrote it, you can rewrite it, and the only thing at stake is whether your benchmark still measures what you wanted. When you evaluate a student, **the rubric belongs to the teacher**, it may have been published to students in advance, and it may be the basis on which a grade gets defended to a parent or an administrator. Changing it is not a free engineering action. Section 6 is the direct consequence of taking that difference seriously.

---

## 2. The leading research: "Reliability without Validity" (UC Berkeley, 2026)

If this report has one paper to anchor an architecture on, it is **Norman, Rivera, and Hughes, "Reliability without Validity: A Systematic, Large-Scale Evaluation of LLM-as-a-Judge Models Across Agreement, Consistency, and Bias"** (UC Berkeley School of Information, June 2026, arXiv:2606.19544). It is the largest study of its kind: 21 AI judges from 9 providers, across three established benchmarks and three testing protocols, producing roughly 541,000 individual judgments. It matters here because it directly measures the failure modes an evaluation harness has to guard against, and because it distills its findings into a five-step checklist that maps almost one-to-one onto the architecture in Section 7.

### 2.1 Finding 1: "kappa deflation" is universal

Every one of the 21 judges, regardless of maker, size, or release date, showed a **33.8 to 41.3 percentage-point gap** between raw agreement and chance-corrected agreement on the standard MT-Bench evaluation. A judge advertising 85% agreement was really operating around κ = 0.48. This held for frontier models released as recently as April 2026. **Implication:** any dashboard or vendor claim leading with "our AI agrees with teachers X% of the time" is an unverified marketing number until the chance-corrected figure appears next to it.

### 2.2 Finding 2: judge rankings do not transfer across tasks

Eleven of the 21 judges shifted by four or more rank positions when moved between benchmarks; the largest single shift was 15 positions. Only two judges held a top-three rank on all three benchmarks. **Implication:** picking "the best model" from a public leaderboard and assuming it will be the best grader for AP US History short-answer questions is unsafe. Validate on *your* assignment types.

### 2.3 Finding 3: the consistency-bias paradox

This is the paper's most important operational finding. Two judges (Qwen 3 8B and Gemini 2.5 Flash) showed *very high* test-retest reliability, above 0.98, while *simultaneously* showing *severe* position bias, up to 0.192, nearly two orders of magnitude worse than the least-biased model tested. The mechanism is simple: a model that deterministically favors whichever answer appears first will look perfectly reliable on a repeat test, because it always makes the same mistake in the same direction. **A judge that never changes its mind is not necessarily trustworthy; it may just be consistently biased.** Reporting stability alone, which is common practice, actively conceals this.

### 2.4 Finding 4: verbosity bias has shrunk, position bias has not

Across all 21 judges, the tendency to reward longer answers regardless of quality was small, under 0.011 correlation, a real improvement over 2023-era research where length effects explained 20 to 40% of scoring variance. Position bias ranged enormously, from 0.002 to 0.192, with no reliable relationship to model size or reasoning capability. Two of three reasoning-enabled models still showed meaningful position bias.

### 2.5 The Minimum Viable Validation Protocol (MVVP)

The paper's practical output is a five-step checklist to run **before** trusting a judge in production:

1. **Chance-correct.** Report Cohen's κ or Krippendorff's α next to any raw agreement number, and treat the chance-corrected figure as the headline.
2. **Swap positions and order.** Test whether the verdict changes when the order of options, criteria, or reference material changes.
3. **Replicate.** Run each judgment at least three times independently and measure self-agreement.
4. **Cross-validate.** Validate on at least two different assignment types or item styles.
5. **Audit the paradox.** Whenever test-retest reliability exceeds 0.95, explicitly check position bias before declaring the judge trustworthy.

A sixth step is added here in v2.7, because the five above can all be satisfied by a panel whose scores have quietly stopped discriminating:

6. **Check for compression (R44).** Compare the panel's band distribution per criterion against the blind gold labels' distribution (§6.8). A panel whose mass sits in interior bands where the teacher used the outer ones is exhibiting central-tendency bias, and none of steps 1 to 5 would reveal it — judges that compress together *agree*, which raises every reliability number in the protocol. Section 5.10 specifies the check and states its limit honestly: it detects the panel compressing *more* than the teacher, not both compressing together.

---

## 3. Statistics, explained for non-statisticians

Six ideas carry the whole design. None require a math background. They require distrusting the first agreement percentage you are shown.

### 3.1 "Percent agreement" lies, and it lies by a predictable amount

If two graders agree 85% of the time, some of that agreement happened by luck. With a three-point rubric and two graders guessing at random, they land on the same score about one time in three with zero skill involved. **Percent agreement never subtracts out that luck.**

**Cohen's Kappa** (κ) is the fix: agreement *after* subtracting chance. It runs from 0 (no better than chance) to 1 (perfect). Rule of thumb: 0.6 to 0.8 is substantial, above 0.8 is near-perfect. **Krippendorff's Alpha** (α) is the close cousin that also handles more than two graders and ordinal scales, which real classroom rubrics have. Treat α as "kappa, flexible enough for actual classrooms."

Per Section 2.1, the gap between raw agreement and kappa ran 33 to 41 points across 21 judges. **Rule: never report a raw agreement percentage without the chance-corrected number beside it.**

### 3.2 Consistency is not correctness

A grader who gives the same wrong score every time is perfectly consistent and completely wrong. **Test-retest reliability** measures whether a grader repeats itself, not whether it is right. Section 2.3 shows why this distinction is load-bearing.

### 3.3 Order should not matter, but it does

**Position bias** is the tendency to favor whatever was seen first, or second, independent of quality. For rubric-based single-item grading, which is most of what a teacher does, the equivalent risks are **criterion-order bias** (the order rubric criteria are presented in) and **anchor bias** (which example the model saw first as a calibration reference). **Verbosity bias** is the length-based version.

### 3.4 One benchmark does not tell you what you think

A judge near the top on one dataset can rank near the bottom on another, because different benchmarks reward different things. Translation: validating your pipeline on essay grading tells you little about lab reports or math proofs. Validate per assignment *type*.

### 3.5 Small samples cannot validate anything 

This is the correction to version 1's sample-size guidance, and it matters for Stage B.

Suppose you run the pipeline on 8 teacher-graded submissions, each with 5 binary rubric criteria. That is 40 decisions, which sounds like a reasonable amount of evidence. It is not. Flipping a *single* decision from correct to incorrect can move kappa by several points, and the uncertainty band around any kappa you compute at that size is so wide that "κ = 0.71" and "κ = 0.45" are not meaningfully distinguishable results. You cannot tell a good grader from a mediocre one at that sample size.

The practical consequence, developed fully in Section 6.6: **a small calibration set is an instrument for finding problems, not for measuring quality.** Eight samples can reliably show you that a rubric criterion is ambiguous, because a single clear instance of ambiguity is itself the finding. Eight samples cannot tell you your system agrees with the teacher at any particular rate. Version 1 conflated these two uses. They need different sample sizes and they belong at different points in the architecture.

There is also a subtler trap. If you *optimize against* a set that small (which is exactly what a naive reflect-and-revise loop does), you will fit the noise. The optimizer will find whatever incidental pattern separates the high scores from the low ones in those eight papers, and length is usually the easiest one to find. You then get excellent measured agreement on your calibration set and a rubric that has quietly become a length detector. The measured agreement is real; it just is not evidence of anything.

### 3.6 Reliability versus validity, the distinction the whole report turns on 

Two words that sound like synonyms and are not:

- **Reliability** asks: is the measurement *consistent*? Does it give the same answer on repeat, across graders, across occasions?
- **Validity** asks: is it measuring *the thing you meant to measure*?

A bathroom scale that always reads exactly 12 pounds heavy is perfectly reliable and invalid. This is the distinction in the Berkeley paper's title, and it is the distinction at the heart of the rubric-revision problem: a revised rubric can improve reliability (the system now agrees with the teacher more often) while destroying validity (it agrees for the wrong reasons, because it now measures length rather than reasoning quality).

One more term you will need for Section 6. **Construct** is the abstract thing being measured: "understanding of conservation of momentum," "ability to support a claim with textual evidence." The rubric document is not the construct. It is an *instrument*, an attempt to write the construct down well enough that a grader can apply it. Two differently-worded rubrics can express the same construct, and that fact is exactly what makes Stage B possible.

### 3.7 Glossary

| Term | One-line meaning |
|---|---|
| Exact match / percent agreement | How often two graders picked the same score, uncorrected for luck |
| Cohen's κ (kappa) | Percent agreement with chance-agreement subtracted out |
| Krippendorff's α (alpha) | Kappa's cousin, handles more than 2 raters and ordinal scales |
| QWK (Quadratic Weighted Kappa) | Kappa variant penalizing big misses (1 vs 5) more than small ones (4 vs 5); the standard metric for rubric scoring |
| Test-retest reliability | Whether a grader repeats its own verdict; says nothing about correctness |
| Position bias | Favoring an answer because of where it appeared |
| Verbosity bias | Favoring longer answers regardless of quality |
| Kappa deflation | The gap between raw and chance-corrected agreement, typically 10 to 40 points |
| Reliability | Is the measurement consistent? |
| Validity | Is it measuring the right thing? |
| Construct | The abstract skill or knowledge being measured, as distinct from the rubric text describing it |
| Construct drift | When a revised instrument stops measuring the original construct |
| Non-inferiority check | Testing that a change did *not* alter outcomes, rather than testing that it improved them |
| Halo effect / criterion conflation | A strong showing on one criterion inflating an unrelated criterion's score |
| Contrast effect / anchoring | A submission scored higher or lower because of what was graded immediately before it |
| Error carried forward | Awarding credit for a later step correctly executed on an earlier step's wrong answer |
| Prefix caching | Reusing the computed state of an identical prompt prefix across calls; a speed optimization, not shared context |
| Working store | Per-run, on-disk record of extracted evidence, keyed by submission and criterion; how dependencies resolve across batches |
| Prefix tree | Nested layers of shared prompt context, cached at each level, deepest layer reused most |

---

## 4. What the education-specific research adds

Section 2 studies general-purpose AI judges. Four recent education-specific studies close the gap to grading student work.

**Creating and Evaluating K-12 GenAI Assessment Graders Through Context Engineering** (Tian, Liu, Esbenshade, Xiao, Zhang, Lápicus, Han, He, Sun; University of Washington and Colleague AI, 2026) is the closest thing to a controlled trial for this use case. Using real MCAS data and four models, it found: larger foundation models achieved *substantial* agreement with human raters in **math and science**; agreement was noticeably *more variable* in **English Language Arts**, where scoring is more interpretive; and, most important for product design, teachers and students showed strong acceptance of **AI-generated narrative feedback** but real skepticism toward **AI-generated numeric scores**. The paper's own conclusion is that these models work best as **formative tools, not summative evaluators.** That shapes the output design in Section 10: lead with rich per-criterion narrative feedback, treat the number as secondary and teacher-adjustable.

**Designing Reliable LLM-Assisted Rubric Scoring for Constructed Responses: Evidence from Physics Exams** (Tang, Ambrose, Cheng; University of Notre Dame, 2026) scored real handwritten undergraduate physics exams with GPT-4o against four human instructors. Human-AI agreement was **comparable to human-human agreement** overall, but **highest for clearly strong or clearly weak responses and weakest for ambiguous, partial-credit, mid-performance responses.** Second, a **fine-grained checklist-style analytic rubric produced more consistent scoring than a holistic rubric**, and criterion-level agreement was stronger for clearly-defined conceptual checks than for extended procedural judgments. **Rule: convert every teacher-submitted rubric into an explicit criterion-by-criterion checklist before scoring.** Section 6.2 explains why this particular transformation is safe even though rubric editing in general is not.

**AutoSCORE: Enhancing Automated Scoring with Multi-Agent Large Language Models via Structured Component Recognition** (Wang, Ding, Wu, Sun, Liu, Zhai; AAAI 2026) is the most load-bearing paper for a *local, open-source* deployment. It splits grading into a **Component Extraction Agent** that pulls rubric-relevant pieces of a response into a structured, evidence-linked representation, and a separate **Scoring Agent** that assigns scores from that representation. Tested on GPT-4o plus two open-weight models (Llama-3.1-8B and Llama-3.1-70B) across the ASAP benchmark, the two-agent design consistently beat single-agent end-to-end scoring, **with the largest relative gains on the smaller open-source models.** This is the direct answer to getting trustworthy grading from a model small enough to run on a Mac: make it extract evidence first in a narrow step, then score.

**The Impact of LLM Self-Consistency and Reasoning Effort on Automated Scoring Accuracy and Cost** (Frohn, Khan Academy, 2026) should change your compute budget. Using 900 real student conversations scored by trained human raters, it tested whether sampling the *same* model repeatedly and majority-voting (ensemble sizes 1 through 7) improves accuracy the way it does for math and logic problems. **It does not.** Going from 1 to 7 produced no statistically significant gain, and a companion study (Xue et al., 2026) found under 1% QWK improvement from 5-way intra-model voting. The mechanism: individual calls were already 0.89 to 0.97 self-consistent, so voting five near-identical answers together confirms the same answer five times, right or wrong. What *did* help was raising reasoning effort (modest, non-monotonic) and using genuinely *different* models.

---

## 5. Advanced best practices

Beyond ground truth, trajectory evaluation, and judging the judge, here is what the last year adds, as actionable rules.

### 5.1 Use a small panel of different-family judges, not repeated calls to one judge

**Replacing Judges with Juries** (Verga et al., 2024, with 2025 to 2026 follow-ups) found a panel of several *smaller* models from *different* families outperformed a single large judge, cost less, and showed less shared bias, because bias baked into one family's training does not automatically infect another. Combined with the Khan Academy finding, the rule is precise: **spend your evaluator budget on model-family diversity (2 to 3 families), not on sampling one model repeatedly.**

### 5.2 Decompose before you score

Per AutoSCORE, split "read the essay and grade it" into extract-then-score. This is the educational analogue of evaluating the trajectory: the extraction step *is* the trajectory, made explicit and auditable instead of buried in one opaque call.

### 5.3 Decompose a rubric criterion only when decomposition preserves its construct (revised in v2.9)

Analytic checklist rubrics beat holistic paragraph rubrics on both agreement and explainability, per the physics-exam study and RULERS, and decomposition helps smaller models most (§0.3). That finding is real and it is why this architecture leans on decomposition everywhere. But versions before 2.9 drew the wrong conclusion from it — that *every* rubric criterion should be converted to an atomic checklist — and defended that with an argument that does not hold.

**First, a distinction that matters, because the objection below lands on one of these and not the other.** Section 5.2's decomposition is a *pipeline* split: extract the evidence, then score against it, rather than doing both in one opaque call. Nothing about the construct changes; the same judgment is made, with its intermediate step made explicit and auditable. That is the AutoSCORE finding and it is unaffected by anything here. Section 5.3's decomposition is a *rubric* split: taking one criterion the teacher wrote and replacing it with several. That one can change what is being measured, and it is the subject of this section.

#### The argument that was wrong

Version 2.2 through 2.8 held that decomposition was inherently safe because it preserves the weight: splitting "shows appropriate work, 5 points" into four sub-checks totalling 5 points was called a clarification under a fixed weight rather than a redefinition (§6.2). **Preserving the weight guarantees the arithmetic. It says nothing about whether the sum of the parts is the thing the teacher was measuring.** Those are different claims, and the design was treating the easy one as evidence for the hard one.

Four ways a faithful-looking decomposition changes the construct:

- **Configural constructs are not conjunctions.** "The argument is coherent" is not "has a thesis" AND "has evidence" AND "has transitions." A response can satisfy every sub-item and still be incoherent, and can violate several while being plainly coherent. The whole is a *configuration* of the parts, not a function of them, and a checklist replaces a gestalt judgment with something a mechanical response can satisfy.
- **The scoring model changes from compensatory to conjunctive.** A holistic band is usually compensatory: strength in one dimension offsets weakness in another, which is exactly what a human marker does when awarding a band. A weighted checklist is additive-conjunctive. For the same work these produce different scores, and the difference is not random — it systematically penalizes the **unusual but valid** response, which fails checklist items that presumed the expected route while a holistic reader would have awarded full credit. That is a fairness property, not just an accuracy one.
- **Interactions get credited that the teacher never intended.** "Selects an appropriate method and executes it correctly" split into two items awards half credit for executing an inappropriate method flawlessly. The teacher's intent was near-zero. Splitting created a scoring path that did not previously exist.
- **Gates disappear.** "A report with no safety analysis fails regardless of everything else" is a threshold, not a weight. Decomposed into weighted items, the gate becomes a deduction and the failing report passes.

#### The decomposability test

Stage A therefore does not decompose by default. It **asks, per criterion, whether decomposition is safe, and records the answer.** The default when the answer is unclear is to leave the teacher's criterion as written: decomposition is the intervention, preservation is the null action, and §1 already establishes that the rubric belongs to the teacher and changing it is not a free engineering action.

Five questions, all answerable against a proposed decomposition:

1. **Completeness.** Could a response satisfy every proposed sub-item and still fail the original criterion as the teacher understands it? If yes, the construct is configural — do not decompose.
2. **Non-interference.** Could a response fail a sub-item and still deserve full credit on the original? If yes, the checklist will over-penalize valid alternative approaches.
3. **Independence.** Can each sub-item be judged without knowing the verdict on another? If not, either declare the dependency explicitly (§7.2 Rule 2) or do not split.
4. **Additivity.** Does the teacher's intended score equal the weighted sum, or does it depend on *which pattern* of items was met? Pattern-dependence means compensatory or configural scoring, not additive.
5. **Gates.** Is there any sub-item whose failure should zero the criterion regardless of the others? If so the criterion is not additive; it needs a gate rather than a weight.

**The model proposes; the teacher confirms.** This is §6.4's elicitation pattern, and the same time budget applies (R9): the model classifies each criterion with its reasoning, and only criteria it classifies as borderline, or proposes to decompose despite a warning sign, are surfaced for confirmation. A rubric of fifteen criteria should cost the teacher a handful of yes/no answers, not fifteen.

#### Three outcomes, recorded in the package

| Classification | Scoring | When |
|---|---|---|
| `atomic` | Decomposed into independently-answerable sub-criteria, each scored as its own judgment | All five questions pass |
| `atomic_with_gate` | Decomposed, plus one or more sub-items marked as gates: failing a gate forces the parent criterion to its lowest band regardless of the others | Question 5 identifies a threshold |
| `holistic` | Not decomposed. Scored as a single judgment of the whole criterion against its band descriptors | Any of questions 1, 2 or 4 fails |

The classification is stored on the criterion, is visible in the teacher's rubric review UI, and is **locked under §6.2** — reclassifying a criterion from `holistic` to `atomic` later is a redefinition of what is being measured, not a clarification of it.

#### What "route appropriately" has to mean for holistic criteria

Retaining holistic evaluation is not a free escape hatch, and the design should be honest about why: it routes the judgments we could not decompose — the hardest ones — to the mode this system is weakest at, since §0.3's entire premise is that decomposition is what closes the gap between an 8B model and a frontier one. A holistic criterion is where that premise does not apply. Four consequences follow, and they are requirements rather than suggestions:

- **Full panel by default, never a single-judge base (R50).** §7.1's adaptive depth runs one judge and escalates; holistic criteria start at three. They are the population escalation exists for.
- **Band descriptors do more work here than anywhere else.** A holistic criterion scored against §5.10's behaviourally-anchored bands is far more defensible than the same criterion scored 0–5, because the judge must still commit to a checkable statement about what the response does. Holistic does not mean unanchored, and a holistic criterion whose bands are vague magnitude phrases has kept every problem decomposition would have solved while adding none of its benefits.
- **A lower confidence ceiling and higher escalation priority.** Cap auto-acceptance for holistic criteria below the atomic ceiling, and rank them higher in the §10 review queue at equal expected value.
- **Agreement reported separately, never merged (R51).** A package's headline agreement statistic must not average atomic and holistic criteria together. They will differ, the holistic ones will be worse, and merging them produces a number that describes neither — the same error §2.1 identifies in reporting uncorrected agreement, one level up.

One honest limitation to record with the rest: evidence citation (§7.3 item 3) is weaker for holistic criteria. A judge scoring a whole-criterion gestalt will cite broader spans than one answering a narrow sub-question, which makes §7.4's integrity signal correspondingly less sharp. This is a real cost of preserving the construct, and it is still the right trade — a precise integrity check on the wrong measurement is not an improvement.

### 5.4 Report the chance-corrected number, always

Per Section 2.1. Worth restating standalone because it is the most common production mistake.

### 5.5 Explicitly test for the consistency-bias paradox

Per Section 2.3. Before adding a model to the panel: does it give a stable verdict on repeat, *and* does the verdict survive shuffling presentation order? Passing the first and failing the second disqualifies it from autonomous scoring, however reassuring "it is very consistent" sounds.

### 5.6 Validate per assignment type

Per Section 2.2. Maintain a per-assignment-type validation record, not a single system-wide accuracy claim.

### 5.7 Calibrate the rubric as ambiguity discovery, with the teacher authoring every change (revised in v2)

Two 2025 to 2026 papers, **Automated Refinement of Essay Scoring Rubrics via Reflect-and-Revise** and **Confusion-Aware Rubric Optimization for LLM-Based Automated Grading** (Chu et al., 2026), show that rubric *wording* can be tuned against human-scored examples so the model's scores align better with the raters', without any model fine-tuning. That is attractive for a local deployment where fine-tuning is impractical.

But note the sample sizes in that work: roughly 200 essays in the Reflect-and-Revise study, and the physics-exam calibration used 20 exams scored by four instructors across two rounds. Version 1 of this report suggested 5 to 10 samples. **That number cannot support an optimization loop** (Section 3.5), and running one anyway produces a rubric fitted to noise.

More fundamentally, freely optimizing rubric text against a teacher's scores risks improving reliability while destroying validity (Section 3.6). The rewrite that best reproduces the teacher's numbers is not necessarily the rewrite that best captures the teacher's standards.

**The corrected practice: treat the calibration pass as ambiguity discovery, not optimization.** The system finds places where the rubric is underspecified and surfaces them to the teacher as a short set of targeted questions. The teacher's answers become the rubric edit. The system never authors a change to what is being measured. Section 6 is the full design.

### 5.8 Route uncertain grades to the teacher

**CHiL(L)Grader: Calibrated Human-in-the-Loop Short-Answer Grading** (2026) demonstrates a confidence-based routing loop built for exactly this scenario: the model produces a score plus a confidence estimate, low-confidence predictions route to the teacher, the teacher's correction feeds back, and the threshold is an exposed parameter letting a school trade automation against reliability. The reported gap in actual accuracy between accepted and routed predictions confirmed the gate was doing real work rather than adding friction.

### 5.9 Lead with narrative feedback, treat the number as secondary

Per the K-12 GenAI Assessment Graders study. Teachers and students trust and act on specific criterion-level written feedback far more than a bare number. Generate feedback text as a first-class output tied to each criterion.

Note this is about what the *teacher and student* see. It is not a statement about generation order inside a judgment, which §5.10 specifies separately and which is a different concern with a different rationale.

### 5.10 Score in words, anchored in behaviour — never on a numeric scale 

Every version before 2.7 asked judges for a number on a continuous per-criterion scale: `max_points: 5`, verdicts like `3.5`. That is the exact format that produces **central-tendency bias**, and the design had no defense against it and no way to see it.

#### The bias, and why this system was blind to it

Central tendency is one of the oldest documented rater errors, alongside leniency, severity, and halo. Ask anyone — human or model — "how good is this, 0 to 10?" and they avoid the ends. Nobody feels certain enough to award a 0 or a 10, so judgments pile up in the middle and the effective range of the scale shrinks. The cause is the *question*: "how good?" asks for a vague magnitude, and vague magnitude judgments have no natural stopping point except the middle. For LLM judges specifically, the well-documented symptoms are low score dispersion, clustering on round values, and a pull toward the mid-to-upper range.

Two things made this worse here than in an ordinary rating system.

**The design contradicted itself.** Section 5.3 calls for decomposed, independently-answerable criteria — which implies judgments so narrow there is barely a middle to retreat into. But nothing enforced it. The schema declared `max_points REAL` and the worked exchange contract scored a criterion at `3.5` out of `5`. The stated intent lived in prose and the opposite lived in the schema, and the schema is what runs.

**And the failure is invisible in every metric the system reports about itself.** This is the same shape as §7.4's finding, one level over. If all three judges compress toward the centre, they compress *together* — so inter-judge agreement **rises**, and confidence rises with it. Then agreement is computed against a teacher who, being human, has the same bias, so κ against gold labels also looks respectable. Every number on the dashboard improves while the scores quietly lose the range that made them informative. A rubric that has stopped discriminating between a strong answer and an adequate one is exactly as damaging as §3.6's rubric that has become a length detector, and just as hard to notice.

#### The fix, in the order of how much work each part does

**1. Anchor every band in behaviour, not in magnitude (R40).** This is the main lever, and it matters more than the choice of labels over numbers.

Do not ask "how good is this out of 5." Ask "which of these statements is true of this response," where each option states what a response at that level *does*:

| Band | Descriptor |
|---|---|
| `derives_and_justifies` | States the conclusion, cites the governing mechanism, and addresses the boundary case |
| `derives_only` | States the conclusion and cites the mechanism; does not address the boundary case |
| `asserts_only` | States the conclusion with no mechanism cited |
| `absent_or_wrong` | No conclusion stated, or a conclusion contradicted by the cited evidence |

Now the judgment is a **factual match**, and it is checkable against the evidence spans the extractor already localized. There is no way to hedge toward the middle, because the middle bands also carry conditions and asserting them when they are false is simply wrong. This is the same move the whole architecture rests on (§0.3): take something the model would do implicitly as a holistic impression and make it explicit, narrow, and verifiable.

**2. Even-numbered band sets, and binary by default (R40).** A five-band scale still has a middle to retreat to. An even set forces a judgment onto one side or the other. And since §5.3 already requires atomic criteria, **the honest default is two bands — met / not met.** A yes/no question has no centre at all. Graded bands are the exception and should carry a reason: use them where partial credit is genuinely part of the construct being measured, not as the default shape. Four bands is usually the most any atomic criterion needs; six requires justification in the package.

**3. Judges never see a number (R39).** Bands go in, a band label comes out, and the band→points mapping lives entirely orchestrator-side. This is not cosmetic: leaving `max_points: 5` in the request means the model is reasoning against a numeric scale regardless of what it is asked to emit, and the label becomes a thin wrapper over the same biased judgment. The whole of point 3 is load-bearing for points 1 and 2.

**4. Generate evidence first, band last (R42).** Field order in a structured response *is* generation order. The pre-2.7 contract emitted `points` first and `rationale` last, which produces a snap judgment followed by a justification invented to fit it.

The corrected order is `cited_spans` → `evidence_assessment` → `evidence_sufficient` → `band` → `self_confidence`.

Note carefully what this does and does not fix. The band still follows the reasoning, so it is still anchored to it — and that is *desirable*; a verdict that ignored the reasoning preceding it would be worse. What matters is what the reasoning is made of:

- **Free-form evaluative prose** — "a fairly weak answer overall, though it shows some understanding" — is itself a vague magnitude judgment. A band anchored to that has simply inherited the central-tendency problem one step earlier and out of sight, where no schema constraint can reach it.
- **Evidence-referential prose** — "span 340–402 states the conclusion; no span addresses the boundary case" — is an inventory. A band anchored to that is anchored to facts.

So `evidence_assessment` is specified as an inventory against the band descriptors, not as free commentary. **Point 4 only works because of point 1**; reordering the fields alone would achieve nothing.

#### Aggregation stays on the ordinal scale (R41)

The trap: three judges return bands, the orchestrator maps each to points, averages them, and gets 3.67. That value corresponds to no band, describes no behaviour, and has reconstructed exactly the continuous scale the bands were introduced to remove.

**Panel size is always odd (R48).** A median needs a unique middle, and an even panel has none: two judges returning adjacent bands leave the verdict genuinely undefined. Permitted sizes are **1, 3, or 5** — never 2, never 4. In practice the design uses 1 as the adaptive base and 3 on escalation (§7.1); 5 is available but rarely justified, since §7.1 finds diminishing returns beyond 3.

Resist the obvious alternative, which is to keep even panels and add a tie-break rule. Every such rule is a **silent systematic bias**: always taking the lower band is severity bias, always the upper is leniency bias, and either lands exclusively on the cases where the panel was split — which §7.1 identifies as the judgments where human-AI agreement is already weakest, and §5.10 identifies as where compression concentrates. A tie-break would apply a hidden thumb on the scale to precisely the population least able to absorb one. An odd panel makes the question not arise.

Enforce it structurally rather than by convention: `criterion_score.judge_count` carries a CHECK constraint for oddness, so an even panel is a write that fails rather than a verdict that quietly rounds.

**When a panel member fails, restore odd or fall back — never adjudicate between two.** A quarantined or unrecoverable scoring unit can leave three judges as two mid-criterion. Retry to restore the third; if that fails, discard the second verdict and fall back to the base single-judge band, marked provisional (R26). Two verdicts and a coin flip is worse than one verdict honestly labelled as one.

**Aggregate on the band scale, map once, at the end.** The panel's verdict is a band — the median band, with the modal band and the spread recorded — and only that aggregated band is converted to points. Disagreement is measured ordinally, so that adjacent-band disagreement counts for less than distant disagreement; Krippendorff's α already handles ordinal scales (§3.1), which is why §7.3 specifies it rather than a raw agreement count.

The same rule applies upward: per-criterion points aggregate arithmetically into question and test totals as before, because at that level a total genuinely is a sum. It is only the judge-level verdict that must never be averaged.

#### The mapping is part of the instrument, not a knob (R43)

A useful property of deriving points from bands is that the mapping can be revised without re-running a single judgment. That is also its hazard: someone can move every grade in the system by editing a lookup table, and the temptation to tune it until the system's scores match the teacher's is exactly the construct drift §6 exists to prevent — arriving by a route §6 does not currently cover.

So the band set and the band→points mapping are **inside the §6.2 schema lock**, version-pinned with the rubric (§6.7), and any change goes through the §6.5 dual-scoring non-inferiority gate like a rubric revision. Exemplar bands are drawn from the criterion's declared band set rather than being free text, so an anchor always names a band that exists.

#### Detecting what remains (R44)

The measures above reduce compression; they do not prove its absence. Add a **compression check** to the MVVP (§2.5): compare the panel's band distribution per criterion against the blind gold labels' distribution. A panel whose distribution is materially narrower — mass concentrated in interior bands where the teacher used the outer ones — is compressing, and that is a finding about the panel, not about the cohort.

`criterion_stats` already stores `sd_points` and a per-criterion `histogram`, and `package_validation` already stores `expected_sd` and `expected_histogram`. The machinery exists; it is currently pointed only at cross-cohort drift (§9.4) and has never been pointed at the judges themselves.

**State the blind spot plainly, because it is real.** This check compares the panel against a teacher, and the teacher has the same bias — it is a human rater error first, and the models most likely learned it from human-generated text. If panel and teacher compress by similar amounts, the comparison shows good agreement and detects nothing. What this check catches is *relative* compression: the panel compressing **more** than the teacher. Catching absolute compression needs a criterion-referenced anchor instead of a rater-referenced one — verifying that a band's stated conditions are actually met in the cited spans, which the behavioural descriptors of point 1 make possible precisely because they are checkable. Treat that as the stronger check and this one as the cheap continuous monitor.

---

## 6. Rubric calibration without re-grading: the guardrail design 

This section replaces the naive reflect-and-revise loop. It answers the question directly: **if the teacher graded against rubric R₀ and the system now runs on revised rubric R₁, what makes the teacher's original scores a valid reference?**

### 6.1 The reframe: the scores are ground truth, the rubric text is a parameter

The apparent paradox dissolves once you separate two things the word "rubric" conflates:

1. **The construct**: what the teacher actually believes counts as good work. This lives in the teacher's head. Their scores are an expression of it.
2. **The instrument wording**: the text handed to a grader so they can apply that construct.

Rubric revision tunes (2) while holding (1) fixed. This is standard practice in the automated-essay-scoring literature: the Reflect-and-Revise study refined rubrics against a fixed set of human-scored essays and nobody re-graded anything. **The human labels are the criterion. The rubric text is a free parameter of the grading system.**

So you correlate against the **scores**, not against the rubric document. That is legitimate **if and only if R₁ is a semantics-preserving reformulation of R₀.** The entire risk of this stage is concentrated in that conditional, which is what the rest of Section 6 exists to enforce.

### 6.2 Guardrail 1: constrain the edit space structurally, not by instruction

Split possible edits into two categories.

**Allowed (clarification):**
- Decomposing a holistic band into atomic checklist items — **only for a criterion Stage A classified `atomic` or `atomic_with_gate` (§5.3). For a `holistic` criterion this is forbidden, not allowed**
- Adding operational definitions for vague adjectives ("thorough" becomes what specifically counts as thorough)
- Adding explicit edge-case handling ("partial credit if the correct formula is stated but the arithmetic fails")
- Adding evidence-type annotations per criterion (what kind of textual evidence satisfies this)

**Forbidden (redefinition):**
- Changing point weights or cut scores
- Changing the band set, a band's descriptor, or the band→points mapping (§5.10, R43). Editing that table moves every grade in the system without re-running a judgment, which makes it the cheapest available route to construct drift and the least visible
- Adding or removing criteria
- Changing which construct a criterion measures
- Reclassifying a criterion scoring model (§5.3): moving a criterion from `holistic` to `atomic` changes what is being measured, not how clearly it is stated
- Introducing any surface feature (length, vocabulary level, formatting) as a scoring signal
- **Adding, removing, or altering a criterion dependency** (see Section 7.2, Rule 2)

Implement this as a **schema constraint, not a prompt instruction.** If the revision step can only emit new sub-items and definitions nested under existing criteria, with weights, criterion count, and the dependency graph structurally immutable in the data model, most construct drift becomes impossible by construction rather than by the model's good behavior. A prompt saying "please do not change the weights" is a request. A schema where weights are not a writable field is a guarantee.

The dependency graph belongs inside this lock for the same reason weights do. A criterion dependency is a channel through which one judgment can influence another (Section 7.2), so quietly adding one during calibration is a way to reintroduce exactly the contamination the isolation rules exist to prevent, and it would do so while *improving* measured agreement, which is the signature of construct drift. Dependencies are declared once, by the teacher or by Stage A's decomposition, are visible in the teacher's rubric review UI, and are read-only thereafter.

Versions before 2.9 argued here that checklist decomposition is inherently safe, on the grounds that splitting "shows appropriate work, 5 points" into four sub-checks totalling 5 points preserves the weight. That argument does not hold, and Section 5.3 now replaces it. **Preserving the weight guarantees the arithmetic; it says nothing about whether the sum of the parts is what the teacher was measuring.** A configural criterion — one a response can satisfy piece by piece while failing as a whole — is redefined by decomposition however carefully the points add up. Decomposition is therefore conditional on the §5.3 test, and the resulting classification sits inside this lock for the same reason the dependency graph does: set once at Stage A with the teacher confirming, read-only thereafter.

### 6.3 Guardrail 2: triage every disagreement before revising anything

When the system and teacher disagree on a calibration sample, there are three possible causes, and **only one of them justifies touching the rubric**:

**(a) Rubric ambiguity.** Two defensible readings of the criterion exist and the model picked the other one. → Revise the wording. Legitimate.

**(b) Model failure.** The rubric was clear and the model misapplied it. → Fix the extraction step, the decomposition, or the panel composition. **Do not touch the rubric.** Rewriting rubric text to compensate for a model limitation bakes that limitation permanently into your school's stated standard.

**(c) Teacher inconsistency.** The teacher scored two near-identical responses differently, usually because of fatigue, ordering, or an unstated distinction. → Flag it, do not fit to it. Fitting to case (c) launders one grader's off-day into institutional policy.

The naive loop collapses all three into "rewrite the rubric," which is precisely how the construct gets corrupted. Make the triage an **explicit output field** in the calibration step, so every proposed edit carries its justification category and only category (a) edits proceed to the teacher.

Case (c) is worth detecting for its own sake. Surfacing a teacher's own inconsistency back to them, gently and with both examples side by side, is genuinely useful to them and is the kind of thing only an automated second pass would ever catch.

### 6.4 Guardrail 3: make revision an elicitation, with the teacher as author

This is the highest-value mechanism, and it sidesteps the re-grading constraint entirely. You cannot ask a teacher to re-grade 30 essays. You can absolutely ask them to answer four targeted questions in two minutes.

So the interaction is not "the system revised your rubric to match your scores." It is:

> Your rubric says "shows appropriate work." On Maya's submission you gave 4 out of 5: she wrote the correct kinematic equation but dropped a negative sign in the arithmetic. On Devon's you gave 2 out of 5 for the same pattern. Which did you mean?
>
> ○ Correct method with an arithmetic slip earns near-full credit
> ○ Arithmetic errors cap this criterion regardless of method
> ○ It depends on something else (tell us what)

The teacher's answer becomes the rubric edit, verbatim in substance. **Validity is preserved by construction**, because the human authored the change and it is now their stated standard rather than an inferred one. The model's job drops from "optimize the rubric" to "localize the ambiguities," a task small local models do well and which carries no construct risk at all.

Three properties make this work operationally:
- It costs the teacher minutes, not hours, so it is actually adoptable.
- It resolves case (c) from Section 6.3 in the same motion, since the teacher gets to rule on their own inconsistency.
- The resulting rubric is defensible in a grade dispute in a way an auto-optimized one is not, because there is a record of the teacher stating the standard.

**Design rule: cap the number of elicitation questions per assignment** (four to six is a reasonable ceiling). If the calibration pass surfaces twenty ambiguities, that is a signal the rubric needs a conversation with the teacher, not a signal to ask twenty questions. Present the highest-impact ones, ranked by how many submissions in the class the ambiguity affects.

### 6.5 Guardrail 4: dual-score for non-inferiority

Keep R₀ running alongside R₁ across the **full class**, not just the calibration set. Then compare:

- If R₁ improves agreement with the teacher on calibration samples **while** R₀ and R₁ produce near-identical scores across the other 25 submissions, you clarified. The revision resolved an ambiguity without moving the standard.
- If R₀ and R₁ **diverge systematically across the whole class**, you redefined. Reject the revision and escalate to the teacher.

This is a **non-inferiority check** (Section 3.7 glossary): you are testing that a change did *not* alter outcomes, which is a different and in this case more useful question than testing that it improved them. It is cheap, since it is one extra scoring pass with a rubric you already have, and it is the single best automated tripwire for construct drift. Note that it works on the full class, where you have hundreds of submissions rather than 8, so unlike the calibration-set statistics it has enough data behind it to mean something.

Set an explicit divergence threshold up front (for example: reject if more than 10% of the class shifts by a full rubric level) rather than eyeballing it after the fact.

### 6.6 Guardrail 5: adversarial back-translation with an independent model

Ask a **different-family model that did not participate in the revision**: "Construct a student response on which R₀ and R₁ would assign different scores."

- If it can produce one, the revision changed the construct. Investigate.
- If it consistently fails across several attempts and several prompting angles, you have real evidence of semantic preservation.

This runs locally, costs almost nothing, and catches the length-detector failure mode fast, because a model asked to exploit a difference between two rubrics will find a surface-feature shortcut immediately if one exists. Use a model from outside the scoring panel so its blind spots do not correlate with the panel's.

### 6.7 Guardrail 6: version-pin everything

Every stored score carries the rubric version that produced it. R₀-scored and R₁-scored results never appear in the same class rollup without an explicit annotation. For a grade dispute you must be able to show which rubric version produced the grade and that the teacher approved that version, with a timestamp.

This is non-negotiable in a system touching student records, cheap to build in now, and expensive to retrofit later. Store the rubric version, the model panel composition, the panel members' versions, and the confidence threshold in force, alongside every score. When a district asks how a grade was produced eighteen months later, that record is the answer.

### 6.8 Where validation actually comes from: the override log

The last correction to version 1. Restating Stage B's purpose honestly:

**On a fresh assignment, the calibration pass is ambiguity discovery, not validation.** It finds where the rubric is underspecified. It cannot tell you the system agrees with the teacher at κ = 0.82, because at that sample size no such claim is supportable (Section 3.5).

Real validation comes from somewhere the architecture already has: **the teacher's accept/edit/override actions in Stage D.** Every time a teacher accepts a score, edits it, or overrides it, you get a labeled data point, produced under the rubric version currently in force, at **zero marginal cost to the teacher**. Across one class you accumulate roughly 30. Across a semester, hundreds. Across a school, thousands.

That is your **operational** validation signal, and it is where much of the Minimum Viable Validation Protocol (Section 2.5) runs. **Stage B feeds the loop. Stage D is the loop.**

#### But teacher acceptance is not ground truth 

Version 2.3 of this report called the override log "the validation set." That claim was too strong, and the gap matters more as the system gets better.

When a teacher sees a proposed score of 4 and clicks accept, what has been established? Possibly that the teacher independently judged 4 to be correct. Possibly that the score looked plausible, the teacher had 200 more items to get through, the evidence was not inspected, and changing it did not seem worth the effort. **Acceptance under time pressure, with the machine's answer already on screen, is a measurement contaminated by the thing it is supposed to be measuring.** This is ordinary automation bias, and it is not a hypothetical: the design deliberately puts a busy teacher in front of a plausible-looking answer, which is the exact condition that produces it.

The trap is that this gets *worse* as the system improves. The more often the system is right, the more reasonable it becomes to accept without checking, and the more the "ground truth" collapses into a record of people agreeing with the machine. A system validated this way can drift arbitrarily far and show excellent agreement statistics the entire time.

So distinguish two label types, and never mix them in a validity claim:

| Type | How produced | What it supports |
|---|---|---|
| **Operational label** | Teacher accepted, edited, or overrode a score they could see | Detecting problem criteria, ranking review, tracking override rates over time |
| **Gold label** | Teacher scored the item **blind**, with the system's score, rationale, and narrative hidden | Agreement statistics, calibration, drift, subgroup analysis, routing-policy evaluation |

**Every administration should include a small blind sample (R21) — and it must never gate the grades.** Draw 15 to 25 submissions at random, hide all system output, and have the teacher score those criteria independently before seeing anything.

Be precise about what skipping it costs, because the honest answer is not “nothing” and it is also not “broken grading”. If the teacher skips, **the class is graded and delivered exactly as normal**; what does not happen is that this administration contributes any evidence about accuracy. The package’s validation record simply does not advance, and the system reports that rather than quietly reusing an older figure: *“no new validation evidence for this administration.”* That keeps R8’s honesty requirement and R60’s automation requirement satisfied at the same time — the price of skipping is paid in what the system may claim, never in whether students get their grades. **Blind-grade the judged criteria only.** Asking a teacher to re-answer multiple-choice items against a key they supplied spends the scarcest resource in the system (R9) on items whose correctness was never in question, and produces labels R53 excludes from every statistic anyway. On a mixed paper the blind sample therefore costs less teacher time than the raw criterion count suggests — which is a genuine benefit of mixed formats worth stating, as distinct from the reporting artifact §7.8 warns against. At 350 students this is a rounding error in coverage and roughly 10 to 20 minutes of teacher time, and it should be carved out of the review budget explicitly rather than competing with it, because it is the only unbiased signal the system will ever have. Everything else, however voluminous, is contaminated.

Note also that an *edit* is stronger evidence than an *accept*, since editing requires the teacher to have formed an independent view. Weight accordingly: an override is informative, an acceptance is weak, a blind score is authoritative.

The blind sample also has a second use. It is the only way to answer the question in Section 7.1: is the routing policy actually catching errors? Comparing error rates between routed and auto-accepted items requires ground truth on both populations, and only the blind sample provides it.

**Labels accumulate against the assessment package, not against a single class.** Per Section 9.4, a tuned assessment persists and is reused across cohorts, so the labels a second and third cohort generate attach to the same instrument. The validation record is therefore cumulative across administrations rather than restarting each term.

**At n=350 this works dramatically better than at classroom scale.** A single assessment produces hundreds of labeled judgments rather than dozens, which means you reach the sample regime the published rubric-tuning literature actually used (20 to 200 examples) after **one or two assessments** rather than after a semester. The large-class deployment that makes throughput hard makes validation easy, and that is a genuine and somewhat unintuitive advantage: the setting with the worst grading problem is also the setting where the system earns the right to be trusted fastest. Section 7.1's random-escalation arm feeds the same store and is what keeps the estimate unbiased.

This reframing also makes rubric revision progressively safer. By the second or third assignment of a term you are revising against a hundred accumulated labels rather than eight, which is the sample regime the published literature actually supports. The system earns the right to a real optimization loop over time rather than assuming it on day one.

Two biases affect the override log and they compound. **Selection bias**: teachers scrutinize flagged items more than auto-accepted ones, so overrides over-represent hard cases. **Acceptance bias**: as above, agreement with a visible machine score is not independent judgment. The blind sample corrects both at once, which is why it replaces the earlier recommendation of a spot-check queue of auto-accepted items shown *with* their scores. Showing the score defeats the purpose.

### 6.9 Summary: the calibration contract

| Question | Answer |
|---|---|
| What is ground truth? | The teacher's original scores |
| What is being tuned? | The rubric's wording only, never its weights, criteria, or constructs |
| Who authors changes? | The teacher, via targeted elicitation questions |
| What does the model do? | Localizes ambiguity; proposes wording; never decides what is measured |
| What *evidence* is there that the construct held? | Dual-scoring non-inferiority across the full class, plus adversarial back-translation, plus the surface-proxy checks below. These are guardrails, not proof |
| What does the calibration pass measure? | Nothing. It discovers ambiguities. It does not validate. |
| Where does validation come from? | The accumulated Stage D override log, plus random spot-checks |
| What if the teacher declines to answer? | Grade with R₀ unchanged and flag affected criteria as lower-confidence |

**No automated check can prove construct validity, and the table should not be read as claiming otherwise.** Dual-scoring shows that two rubric versions produce similar scores; it does not show they produce them for the same reasons, and two versions that both reward length will agree beautifully. Adversarial back-translation is itself model-based and inherits the models' blind spots. The strongest evidence for construct validity remains, in order: the change was authored by the teacher (§6.4), the schema made redefinition structurally impossible (§6.2), blind human labels agree out of sample (§6.8), and the score does not depend on things that should not matter.

**Make that last one operational.** Regress the assigned scores against surface features that ought to be irrelevant and check whether they explain variance:

- response length in tokens
- vocabulary complexity and language-fluency proxies
- OCR quality score for that submission (§7.5)
- handwriting-legibility band, where captured
- formatting regularity
- where locally lawful and ethical, language group and other subgroup breakdowns

A criterion whose scores correlate strongly with length or OCR quality is measuring something other than what it claims, whatever the agreement statistics say. Run this per criterion after each administration and store it with the package's validation record. This is the check that would actually catch the length-detector failure mode, and unlike the model-based guardrails it cannot be fooled by the same bias it is testing for.

That last row of the table matters too. **The system must work with zero teacher calibration input.** Elicitation is an offer that improves quality, never a gate that blocks grading. A teacher on a Sunday night with 90 papers will skip it, and the harness has to degrade gracefully into "grade with the rubric as given, be more conservative about auto-accepting on the ambiguous criteria."

---

## 7. Reference architecture

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │  TEACHER INPUTS                                                      │
 │  1) Assignment/Test   2) Reference Solution   3) Rubric (R0)         │
 │  4) Student Submissions (batch)                                      │
 └───────────────────────────────┬─────────────────────────────────────┘
                                 ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  STAGE A - INGESTION & RUBRIC DECOMPOSITION                          │
 │  • ALL PDFs -> pages -> VLM -> ONE canonical .md artifact per doc    │
 │    EVERY artifact kind, typed or handwritten. No PDF or page image   │
 │    ever reaches a stage below this one (§7.7, R38)                   │
 │    several PDFs assemble deterministically (R33)                     │
 │    content-hashed + immutable: evidence spans offset into it (R32)   │
 │  • VALIDATION LADDER before anything is scored (§7.7, R34):          │
 │      V0 file integrity   V1 page completeness   V2 structure         │
 │      V3 student identity                                             │
 │      V4 ASSESSMENT MATCH - is this submission even for this test?    │
 │         mismatch OR uncertain -> human. Never auto-reassign (R35)    │
 │      any failure -> operator quarantine, NEVER a score               │
 │  • DECOMPOSABILITY TEST per criterion (§5.3, R49): can this be split  │
 │    without changing what it measures? Unclear -> do NOT split        │
 │      atomic | atomic_with_gate | holistic, teacher-confirmed, locked │
 │      holistic -> full panel, no single-judge base (R50)              │
 │  • Attach an "evidence type" per criterion (RULERS, §1)              │
 │  • SCHEMA LOCK: weights + criterion count immutable downstream (§6.2)│
 └───────────────────────────────┬─────────────────────────────────────┘
                                 ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  STAGE B - AMBIGUITY DISCOVERY  (optional, skippable, §6)            │
 │  Purpose: find underspecified criteria. NOT to validate. (§6.8)      │
 │                                                                      │
 │  B1  Score any already-teacher-graded samples with R0                │
 │  B2  TRIAGE each disagreement (§6.3):                                │
 │        (a) rubric ambiguity  -> proceed to B3                        │
 │        (b) model failure     -> fix pipeline, DO NOT touch rubric    │
 │        (c) teacher inconsistency -> flag to teacher, do not fit      │
 │  B3  ELICIT: <=6 targeted questions; TEACHER authors the answer(§6.4)│
 │  B4  Apply edits within schema lock -> R1                            │
 │  B5  GUARDRAIL GATE before R1 goes live:                             │
 │        • Dual-score R0 vs R1 across FULL class; reject on            │
 │          systematic divergence (non-inferiority, §6.5)               │
 │        • Adversarial back-translation w/ off-panel model (§6.6)      │
 │        • Version-pin R1 + teacher approval + timestamp (§6.7)        │
 │      FAIL ANY GATE -> revert to R0, flag criteria as low-confidence  │
 │                                                                      │
 │  IF SKIPPED: proceed with R0, mark ambiguous criteria conservative   │
 └───────────────────────────────┬─────────────────────────────────────┘
                                 ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  STAGE C - SCORING   (two sweeps around a working store, §8.4)       │
 │                                                                      │
 │  SWEEP 1: EXTRACTION   batched by (question, criterion)              │
 │           JUDGED criteria only. Deterministic (MCQ) items skip both  │
 │           sweeps entirely: key lookup, no model call (§7.8)          │
 │           executed in TOPOLOGICAL ORDER over the dependency graph    │
 │   ┌──────────────────────┐                                           │
 │   │ Extraction Agent     │  localizes rubric-relevant evidence spans │
 │   │ (single small model) │  + compares to reference solution         │
 │   └──────────┬───────────┘                                           │
 │              ▼                                                       │
 │              ▼                                                       │
 │   ┌──────────────────────────────────────────────────────────────┐   │
 │   │ EVIDENCE INTEGRITY GATE (§7.4, R19) - before any scoring      │   │
 │   │  • span offsets verified against source bytes (zero cost)     │   │
 │   │  • required-evidence check: empty != zero, ROUTE don't score  │   │
 │   │  • OCR overlap check (§7.5, R24): could a transcription       │   │
 │   │    error in THIS span change THIS criterion?                  │   │
 │   │  • 2nd-family extraction on high-risk criteria only           │   │
 │   └──────────┬───────────────────────────────────────────────────┘   │
 │   ┌──────────────────────────────────────────────────────────────┐   │
 │   │  WORKING STORE  (on disk, per-run, PII-protected)            │   │
 │   │  key: (run_id, submission_id, criterion_id)                  │   │
 │   │  value: evidence spans + offsets. NO judge dimension.        │   │
 │   │  This is how Rule 2 dependencies resolve across batches.     │   │
 │   └──────────┬───────────────────────────────────────────────────┘   │
 │              │  fully populated before Sweep 2 begins, so Sweep 2    │
 │              │  has NO ordering constraint -> schedule for cache     │
 │              ▼                                                       │
 │   ══ JUDGMENT ISOLATION BOUNDARY (§7.2 Rule 1) ═══════════════════   │
 │   Each cell = ONE criterion x ONE judge x ONE submission, built      │
 │   from FRESH context. No prior verdict, no prior student, no         │
 │   conversation history crosses this boundary.                        │
 │   Prefix caching IS allowed (carries no verdict).                    │
 │   N independent calls sharing a prefix != one call with N students.  │
 │                                                                      │
 │  SWEEP 2: SCORING   loop order: judge > question > criterion >       │
 │                     parallel over submissions  (§8.4)                │
 │        Judge A        Judge B        Judge C    <- diverse families  │
 │   C1 [ verdict ]    [ verdict ]    [ verdict ]   <- ALL students in │
 │   C2 [ verdict ]    [ verdict ]    [ verdict ]      in parallel per  │
 │   C3 [ verdict ]    [ verdict ]    [ verdict ]      cell, identical  │
 │   C4 [ verdict ]    [ verdict ]    [ verdict ]      cached prefix    │
 │    ▲                                                                 │
 │    └── C4 reads C2's EVIDENCE from the store if the schema declares  │
 │        it. C2's SCORE never travels. Artifact comes from extraction, │
 │        not from any judge, so all judges see identical input and     │
 │        panel independence is preserved. Default = no dependencies.   │
 │   ═══════════════════════════════════════════════════════════════    │
 │              │                                                       │
 │              ▼                                                       │
 │   ┌────────────────────────────────┐   ┌──────────────────────────┐  │
 │   │ Aggregation & Confidence        │   │ SYNTHESIS (Rule 3)       │  │
 │   │ • MEDIAN BAND across the panel  │──>│ L1: per question         │  │
 │   │   (ordinal, never an average -  │   │ L2: per test, reads only │  │
 │   │    §5.10 R41), then map band    │   │     the L1 syntheses     │  │
 │   │    -> points ONCE, here         │   │ SCORES NOT WRITABLE      │  │
 │   │ • ordinal α: adjacent-band      │   │ in either output schema, │  │
 │   │   disagreement < distant        │   │ and no numeric claims in │  │
 │   │ • chance-corrected (§3.1, §5.4) │   │ prose either (§10)       │  │
 │   │ • INVERTS on evidence-integrity │   │                          │  │
 │   │   failure: unanimous judges on  └──────────────────────────────┘  │
 │   │   bad evidence = LOW confidence                                   │
 │   │ • derived points aggregate arithmetically up the tree, never      │
 │   │   via synthesis. Only the JUDGE-level verdict is never averaged   │
 │   └───────────────┬─────────────────┘                                 │
 │                                                                      │
 │  CHECKPOINT UNIT = (judge, question, criterion) cell, not student    │
 │  ALL state above persists via the §9 stores; §9.1 one-way rule:      │
 │  orchestrator reads memory, judges never do.                         │
 └─────────────────────────────────────────────────┼───────────────────┘
                                                   ▼
                             ┌──────────────────────────────────────┐
                             │ CONFIDENCE-BASED ROUTING (§5.8)       │
                             │  high confidence -> auto-score        │
                             │  low confidence  -> teacher queue     │
                             │  + random spot-check sample (§6.8)    │
                             └───────────────┬──────────────────────┘
                                             ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  STAGE D - TEACHER REVIEW  ***THE VALIDATION INSTRUMENT*** (§6.8)    │
 │  • Per-criterion narrative feedback shown first (§5.9)               │
 │  • Numeric score shown as adjustable, secondary artifact             │
 │  • Evidence citations (spans from submission) per criterion          │
 │  • One-click accept / edit / override                                │
 │  • EVERY action logged as a labeled datapoint w/ rubric version      │
 │    -> this accumulating log is where MVVP (§2.5) actually runs       │
 └───────────────────────────────┬─────────────────────────────────────┘
                                 ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  STAGE E - FINAL GRADES + CLASS-LEVEL ROLLUP                         │
 │  • Apply the teacher-declared grade policy to EVERY submission       │
 │    automatically. No per-student teacher action (§7.9, R56)          │
 │  • Provisional inputs label a grade, never withhold it (R58)         │                                        │
 │  • Per-criterion score distribution across the class                 │
 │  • Chance-corrected agreement, scoped + sample-size qualified        │
 │  • Misconception clusters; flagged low-confidence items              │
 │  • Rubric version in force + guardrail-gate results                  │
 └───────────────────────────────┬─────────────────────────────────────┘
                                 ▼
                    ┌───────────────────────────────────┐
                    │ LONGITUDINAL VALIDATION STORE      │
                    │ accumulated override labels across │
                    │ assignments -> real MVVP runs here │
                    │ -> earns the right to a genuine    │
                    │    optimization loop over time     │
                    └───────────────────────────────────┘
```

### 7.1 How many evaluators do you actually need?

The research answers this precisely, and against the "more judges is more reliable" intuition:

- **Do not use ensemble size (repeated calls to one model) as your reliability lever.** Sections 4 and 5.1: no significant accuracy gain, multiplied cost.
- **Do use model-family diversity.** A panel of **3 judges from different families** (odd by requirement, R48) (Llama-family, Qwen-family, an open GPT-family model) captures most of the PoLL benefit at a cost one Mac sustains. Beyond 3, diminishing returns and, at large class sizes, prohibitive cost; 5 is permitted but rarely worth it, and even sizes are not permitted at all because they leave the median undefined (§5.10, R48). See the adaptive-depth revision below.
- **Spend the savings on decomposition and reasoning effort.** Per Frohn, reasoning effort produced a real if modest gain. Per AutoSCORE, adding an extraction step produced the largest gain of any single architectural change, especially on smaller models. Both beat a fourth same-family judge.
- **The number that matters most is not AI judges, it is accumulated human labels.** And per Section 6.8, those accumulate for free from Stage D rather than being demanded from the teacher up front. At n=350 they accumulate roughly ten times faster than the classroom-scale assumption, which materially improves the validation regime.

#### Adaptive panel depth at scale (R10)

Everything above holds at classroom scale, where a three-judge panel is cheap. At 350 students it is not: 15 criteria × 350 students × 3 judges is 15,750 scoring judgments, and the third judge costs real hours of wall clock (Section 8.4). A uniform three-judge panel is the single largest cost in the system and it is spent almost entirely on judgments where all three judges will agree anyway.

**Allocate panel depth where the research says disagreement actually lives.** Run one judge on every judgment, **except on `holistic` criteria, which start at the full panel (R50)** — those are the ones §5.3 could not decompose, and decomposition is what this architecture relies on to make a small model reliable, so they are precisely where a single judge is least trustworthy. Escalate to the full panel only where escalation is warranted. Note the ladder is **1 → 3** and never passes through 2: adding a single second judge would produce an even panel with no unique median, so escalation adds two judges at once (§5.10, R48).

| Escalation trigger | Kind | Rationale |
|---|---|---|
| Verdict falls in an interior band rather than an extreme one | Observable | The physics-exam study (Section 4) found human-AI agreement is strongest at the extremes and weakest for ambiguous partial-credit responses. This is the empirically identified weak point, so it is where the panel earns its cost. Note this is a *different* fact from §5.10's central-tendency bias, and the two interact: interior verdicts are both genuinely harder and the place a compressing panel over-produces. Escalating them is the right response to either cause, but a rising interior rate is a signal to check §5.10's compression measure, not just to spend more compute |
| Evidence is absent, unverified, or flagged insufficient | Observable | Extraction problems must not resolve into confident scores (Section 7.4) |
| Verdict produced without an evidence citation | Observable | Uncited verdicts are already treated as low-confidence (Section 7.3, item 3) |
| Transcription uncertainty overlaps the criterion's evidence span | Observable | Section 7.5, R24 |
| Criterion has a history of disagreement or override in the accumulated label store | Historical | Per-criterion, data-driven, improves with use |
| Score is anomalous against the package's expected distribution | Observable | Section 9.4's baseline, applied per judgment |
| First judge reports low self-confidence | **Weak signal** | Useful as one feature; see the caution below |
| Random sample (5 to 10%) | **Mandatory** | The only unbiased estimate of how often a single judge and the full panel would have differed |

**Self-reported confidence is a feature, not the authority.** Language models are poorly calibrated in a specific and damaging way: the cases they are confidently wrong about are, by construction, the cases self-confidence will never flag. An escalation policy resting primarily on the model's own uncertainty will systematically miss the errors that matter most. Build the policy from **observable** signals (score position, evidence integrity, transcription overlap, distributional anomaly, criterion history), treat self-confidence as one input among them, and weight it according to how well it has actually predicted teacher overrides in the accumulated label store rather than according to how reasonable it sounds.

Cost effect: at a 30% escalation rate, scoring drops to roughly **53% of full-panel cost**. At 20%, roughly 47%.

**Validate the routing policy itself, not just the grader (R22).** The question "how accurate is the system" is less operationally important than "does the routing send the errors to the teacher." Using the blind sample (Section 6.8), measure the error rate among escalated-and-reviewed judgments against the error rate among auto-accepted ones. A policy that is working shows a large gap, for example 8% error in the routed population against 1% in the auto-accepted one. A policy that shows similar error rates in both populations is doing nothing except consuming the teacher's time, and it needs rebuilding rather than tuning. This measurement is only possible because of the random arm, which is why the random arm is not optional: without it the escalation policy is unfalsifiable.

**Escalation-rate circuit breaker.** The throughput arithmetic in Section 8.4 assumes escalation lands near 30%. A poorly worded question or a criterion that the panel simply cannot apply can drive that to 80% or more, which breaks the batch window and produces thousands of low-confidence judgments of little value. So monitor escalation rate per criterion during the sweep: **if a criterion escalates for more than half of the first 20 to 30 submissions, halt escalation for that criterion**, mark it `un-gradeable_by_panel`, score the remainder single-judge and provisional, and surface it to the teacher as a rubric problem rather than as 350 uncertain grades.

This is a quality signal at least as much as a cost control. A criterion that confuses the panel on a third of responses is a criterion whose wording needs work, and that is exactly the finding Section 6's elicitation loop exists to act on. The circuit breaker converts an expensive failure into a cheap, actionable one, and feeds the next round of rubric tuning.

The complementary control is a **global escalation ceiling**: if overall escalation exceeds the budgeted rate, continue admitting escalations in expected-value order and mark the remainder provisional (Section 10, R26) rather than letting the run overrun its window. Degrade the depth of scrutiny visibly; never degrade it silently.

This is a stronger and better-motivated version of the "earned single-judge optimization" in Section 8.3: rather than retiring the panel on criteria that have proven uncontested, it allocates panel depth per *judgment* based on where disagreement is predicted. At n=350 it moves from an optimization to a requirement.

### 7.2 Judgment isolation 

Version 2 said to score one criterion per call. That is necessary but not sufficient, and the imprecision matters once this runs inside an agent framework where a "call" can carry conversation history. **The contamination that produces cross-criterion bias comes from shared context between judgments, not from shared processes.** A single long-running agent process that starts each judgment from a clean context is safe. Three separate agent processes passing a conversation history between them are not. Specify the property, not the topology.

Three rules.

#### Rule 1: Context isolation per judgment

**Every scoring judgment sees exactly one criterion, one submission, and nothing else.** No prior criterion's verdict, no prior student's submission, no accumulated conversation, no running summary. Context is constructed fresh per judgment from the rubric, the extracted evidence, the reference solution, and nothing carried forward.

This blocks three distinct contamination paths, worth naming separately because they are routinely conflated:

- **Halo effect / criterion conflation.** A strong thesis statement inflates the unrelated "cites sources correctly" score. This is the best documented of the three in the grading literature and the one most people mean when they raise this concern.
- **Cross-submission anchoring / contrast effects.** Grading Devon immediately after Maya's exceptional paper depresses Devon's score. This is a well-established human sequential-rating bias, and there is no basis for assuming a model holding the prior submission in context is immune. If your batch loop reuses context across the class to save tokens, you have built this in deliberately.
- **Cross-assignment leakage.** An agent that handled last week's lab report carrying assumptions into this week's essay. Mostly hypothetical with stateless calls, and immediately real the moment anyone adds session memory or a persistent agent.

**Prefix caching is explicitly permitted and encouraged.** Caching the computed state of a fixed rubric-and-assignment prefix is a performance optimization over identical text; it is not shared context between judgments and it carries no verdict information. State this in the design doc, because someone will otherwise disable caching believing they are preventing contamination, and on local Mac inference that cache is a large fraction of your throughput (Section 8.3).

#### Rule 2: Declared dependencies, or none

An absolute isolation rule would produce wrong grades, so this rule is deliberately not absolute. Some criteria are genuinely dependent:

- **Error carried forward.** In math and physics, standard pedagogy awards credit for part (b) executed correctly on part (a)'s wrong answer. A scorer blinded to part (a) cannot distinguish "correct method, inherited error" from "wrong." The Notre Dame physics study (Section 4) already found extended procedural judgments were the weakest agreement category; blinding them to prior parts makes that worse, not better.
- **Internal-consistency criteria.** "The conclusion follows from the evidence the student presented" is definitionally a relation between two other parts of the response.

So: **a criterion may receive input from another criterion only through an explicitly declared dependency in the rubric schema, and only the declared artifact, never the other criterion's score.**

Criterion 4 may receive "the evidence spans extracted for criterion 2." Criterion 4 may **not** receive "criterion 2 was awarded 4 of 5."

That distinction carries the whole rule. Passing *evidence* preserves the information a grader legitimately needs to apply error-carried-forward or judge internal consistency. Passing *scores* is precisely the halo channel Rule 1 exists to close. A dependency is a pipe for facts, never for verdicts.

Implementation constraints:
- **Default to zero dependencies.** A criterion is independent unless the teacher or Stage A's decomposition explicitly declares otherwise.
- **Dependencies live inside the Section 6.2 schema lock** and are read-only after the teacher approves them, so calibration cannot quietly add one.
- **Declared dependencies are visible in the teacher's rubric review UI**, in plain language ("criterion 4 will see the work you credited under criterion 2").
- **The dependency graph must be acyclic.** A cycle is a rubric-design error and should be rejected at Stage A rather than resolved at runtime.
- **Dependencies are satisfied from the extraction layer, never from judge output.** See below.

**Which artifact travels, and why it matters more than it looks.** There are two plausible sources for the evidence that flows across a dependency edge, and picking the wrong one silently destroys panel independence.

- *From judge output*: Judge A's criterion-4 judgment receives Judge A's criterion-2 output. This couples a judge's later judgments to its own earlier ones, and if you instead pooled the panel's criterion-2 output as a shared input, all three judges' criterion-4 judgments would share an input, making their agreement partly an artifact of a common cause. That contaminates the confidence signal (see below).
- *From the extraction layer*: criterion 4 receives the evidence spans the **extraction agent** localized for criterion 2. Extraction runs once per submission per criterion, produces no verdict, and is identical for every judge.

**Take it from the extraction layer.** All judges then see byte-identical input, panel independence is fully preserved, and the dependency store needs no judge dimension.

This is sufficient for both motivating cases, which is the non-obvious part. For error carried forward, what criterion 4 needs is *the student's part (a) answer*, so it can check whether part (b) follows correctly from that answer. It does not need to know whether part (a) was scored correct, and in fact must not, since that is a score crossing the boundary. For internal consistency, criterion 4 needs *the evidence the student presented*, which is exactly what extraction localized. In both cases the extraction artifact carries all the information a legitimate dependency requires, and none of the verdict information Rule 1 exists to block.

Section 8.4 covers where these artifacts are stored between the extraction sweep and the scoring sweep.

#### Rule 3: Synthesis reads, never writes (and is hierarchical)

Isolation has one real cost: the feedback comes out incoherent. Five independently written criterion comments can contradict each other, repeat the same observation five times, or praise in criterion 1 something that criterion 3 penalizes. Since the K-12 research (Section 4) finds narrative feedback is the part teachers and students actually trust and act on, incoherent feedback is not a cosmetic problem, it degrades the system's most valuable output.

The fix is a **synthesis pass that reads criterion verdicts and composes the student-facing narrative, while being structurally prohibited from modifying any score.** Enforce it the same way as Section 6.2: scores are not a writable field in the synthesis step's output schema, so it is a guarantee rather than an instruction. Synthesis consumes verdicts and evidence and emits prose only.

**Synthesize in two levels, not one.** A single pass reading every verdict for a whole submission is fine for a three-question quiz and degrades badly on a ten-question exam with three criteria each, where thirty verdicts plus their evidence spans is a large context for a small local model. Quality then fails precisely where it is most valuable. Instead:

- **Per question, per submission:** synthesize that question's criterion verdicts into coherent feedback on that question. Small, focused, high quality.
- **Per test, per submission:** read only the per-question syntheses, not the raw verdicts, and produce the overall narrative.

Both levels stay read-only on scores. **Points aggregate arithmetically up the tree from the criterion scores and never pass through a synthesis step**, so no amount of narrative composition can move a grade. Note the two different rules that apply at two different levels, since they are easy to conflate: the *judge-level* verdict is a band and is aggregated ordinally, never averaged (§5.10, R41); the *criterion-level* points that result are summed into question and test totals, because at that level a total genuinely is a sum.

This preserves score independence while producing feedback that reads as though one coherent teacher wrote it.

#### Why isolation also makes your confidence signal honest

A side benefit worth stating explicitly, because it affects a number the system acts on. If panel judges share context, their agreement is partly an artifact of having seen the same prior verdicts, which inflates the inter-judge agreement statistic. That statistic is the confidence signal driving the Stage C to Stage D routing decision (Section 5.8). Without isolation, the confidence gate is partly measuring correlated noise, and it will route too few submissions to the teacher precisely on the criteria where the judges have influenced each other most. Independent judgments make the agreement number mean what Section 7.3 item 4 claims it means.

### 7.3 How the panel is organized to avoid bias

1. **Criterion-atomic scoring under judgment isolation.** One rubric criterion per judgment, fresh context each time, per Section 7.2. Avoids criterion conflation, cross-submission anchoring, and cross-assignment leakage.
2. **Order randomization.** Randomize criterion presentation order and which example anchors any few-shot calibration. Targets position bias (Section 2.4). Note that under Rule 1 this randomization is across independent judgments, so it is genuinely independent randomization rather than reshuffling within one conversation.
3. **Evidence citation required.** Each judge cites the span supporting its verdict per criterion (RULERS). An uncited verdict is treated as lower-confidence downstream, and cited spans are what travel across any declared dependency (Rule 2).
4. **Ordinal, chance-corrected aggregation.** The panel's verdict is the **median band**, not an average (§5.10, R41) — averaging judges' band-derived points lands on values that correspond to no band and describes no behaviour, rebuilding the continuous scale the bands exist to remove. Points are derived once, from the aggregated band. Track inter-judge Krippendorff's α **with an ordinal metric**, so adjacent-band disagreement counts for less than distant disagreement, and use that as the live confidence signal driving the C-to-D routing decision rather than a raw "2 of 3 agreed" count.
5. **Off-panel model reserved for adversarial checks.** Keep at least one installed model *out* of the scoring panel so it can serve as the independent back-translation checker in Section 6.6 without correlated blind spots.
6. **Synthesis is read-only** with respect to scores (Rule 3).
7. **Run the MVVP (Section 2.5) per assignment type** before trusting the panel on a live class, and re-run it whenever a panel member changes.
8. **Scale format is itself a bias control.** Behaviourally-anchored band labels, even-numbered, binary by default, with no numeric scale ever visible to a judge (§5.10). This sits alongside order randomization in item 2: both are structural defenses against a bias that would otherwise be invisible, because a panel that compresses toward the centre compresses *together* and therefore agrees.

### 7.4 Extraction integrity: the common-mode failure the panel cannot see 

Sections 7.2 and 7.3 make the judges independent of each other. They do not make the judges independent of the **extraction step**, and that is a real hole in the design as written up to v2.3.

The dependency is:

```
                          ┌──> Judge A ──> 2
Submission ──> Extraction ├──> Judge B ──> 2
                          └──> Judge C ──> 2
```

The judges are independent *conditional on the extraction*. They are not independent with respect to the student's actual answer. If the extractor misses a span, hallucinates one, or mis-segments a multi-part response, all three judges reason from the same corrupted representation and reach the same wrong verdict.

**The panel then reports unanimous agreement, and the confidence signal goes up.** This is worse than ordinary judge correlation, because the mechanism that is supposed to detect error is the mechanism that conceals it: high inter-judge agreement is read as high confidence, the judgment is auto-accepted, and it never reaches the teacher. The system is most confident exactly when it is systematically wrong.

Note the tension with Section 7.2 Rule 2, which deliberately removed the judge dimension from the evidence store so every judge sees byte-identical input. That decision was correct for panel independence and it is precisely what creates this exposure. The resolution is not to give each judge its own extraction, which would reintroduce the coupling Rule 2 avoids, but to add **independent detection** between extraction and scoring.

Four mechanisms, in ascending cost. The first two are close to free and should always run.

**1. Deterministic span verification (zero model cost, always on).** Every extracted span carries character offsets into the submission. Verify mechanically that the offsets are in range and that the quoted text matches the source bytes exactly. This catches hallucinated evidence, drifted offsets, and spans invented wholesale, which is a real and common failure mode in smaller models. A span that fails verification is discarded and the extraction is retried; repeated failure quarantines the unit rather than scoring on fabricated evidence.

**2. Required-evidence check (zero model cost, always on).** A criterion whose evidence type demands a citation, but for which extraction returned nothing, **must not be auto-scored as zero**. Empty evidence is ambiguous between "the student did not do this" and "the extractor did not find it," and those two have opposite consequences for the student. Treat empty evidence on a citation-requiring criterion the same way Section 9.10 treats a failed transcription: route it, do not score it. This is the single cheapest protection against extraction failure silently becoming a low grade.

**3. Sufficiency flag from the judge (low cost, always on).** The judge is not given the full submission, because that would forfeit the decomposition benefit that AutoSCORE found matters most for small models (Section 4). It is given one additional output field: `evidence_sufficient`, a boolean. A judge that reports "I cannot apply this criterion from the evidence I was given" is reporting an extraction problem, not a student problem. Judgments where any panel member raises this flag route to re-extraction, and on repeat, to the teacher.

This is deliberately a *detection* channel rather than an escape hatch. Letting the judge read the original response when evidence looks thin sounds appealing and quietly reintroduces the holistic judgment the architecture exists to avoid, unevenly and only on hard cases, which is the worst possible place for it.

**4. Second-family extraction on high-risk criteria (real cost, targeted).** For criteria flagged high-risk, either by construct (multi-step procedural work, internal consistency) or by history in the accumulated label store, run extraction twice using models from different families and compare the span sets. Disagreement on which spans are relevant is a strong signal, and unlike judge disagreement it is measured *before* the common-mode error can propagate. Reserve this for the minority of criteria that warrant it; running it everywhere would roughly double the extraction sweep.

**The confidence formula must account for this.** Inter-judge agreement can no longer be the sole confidence input, because it is inflated exactly when extraction fails. Confidence combines: panel agreement (where available), span verification results, evidence sufficiency flags, extraction agreement where a second extractor ran, and citation quality. **A unanimous panel operating on unverified or insufficient evidence is a low-confidence result, not a high-confidence one**, and the aggregation step must encode that inversion explicitly, because the naive combination gets it exactly backwards.

### 7.5 Transcription risk: route on impact, not on confidence 

Section 0.2 identifies ingestion as a real subsystem at 350 handwritten submissions. Two properties make it more dangerous than a throughput problem.

**OCR error is not randomly distributed across students.** Students with poor handwriting, heavy corrections, mixed-language answers, diagrams, or mathematical notation get systematically worse transcription. Since transcription quality propagates into evidence quality and then into grades, uncorrected this becomes a bias that tracks handwriting and language fluency rather than understanding, and it will disproportionately affect the students the system exists to serve. Treat it as an equity risk with a technical cause, not as a data-quality nuisance.

**Confidence is the wrong routing signal.** "OCR confidence is low" is not the question. The question is: **could a plausible transcription error change this criterion's score?** A garbled word in a passage irrelevant to criterion 4 does not matter. A garbled minus sign in the one line criterion 4 evaluates matters entirely. Route on the intersection of transcription uncertainty and the evidence spans a criterion actually depends on, which the harness knows, because extraction already localized them.

This yields a rule with teeth: **if a low-confidence transcription region overlaps the evidence span for a criterion, that criterion cannot be auto-scored**, regardless of how confident the panel is. Everything else proceeds normally, which keeps the routed volume proportional to genuine risk rather than to overall scan quality. The same rule extends to **described graphical regions** (§7.7, R46): a description is a model’s account of a drawing, span verification cannot check it against the image, and so a criterion whose evidence lies wholly inside one is a routing candidate on that basis alone.

Ingestion should therefore emit, per submission: the transcript, per-region confidence, layout confidence, detection of equations and diagrams, page completeness, and an overall quality score. Per-region confidence is what makes impact-based routing possible; a single document-level number does not. Section 7.7 specifies the module that produces all of this — the transcription model, the assembly of multi-file submissions, and the validation ladder that runs before any of it reaches scoring.

**Reducing the failure rate is worth more than handling it well.** Two practical measures, both drawn from the review of this design:

- **Structured answer templates.** Printable answer sheets with ruled response boxes, per-question anchors, and a QR or fiducial marker for page identification and deskewing. This converts unbounded page-layout analysis into bounded region extraction and improves recognition materially, at the cost of printing, which is a cost the target settings already bear for the assessment itself.
- **Transcription clustering.** Rather than asking a teacher to transcribe individual illegible words one submission at a time, cluster visually similar unresolved tokens across the whole cohort and ask once. A teacher who resolves one scrawl resolves it for every student who writes it that way. At n=350 with a shared curriculum vocabulary this collapses a large fraction of the manual work, and it is the difference between transcription triage fitting in the teacher-minute budget and blowing straight through it.

Clustering across submissions at ingestion does **not** violate judgment isolation. Stage A produces no verdicts; it produces text. The isolation boundary sits between extraction and scoring (Section 7.2), and nothing about resolving a handwriting cluster gives a judge information about another student's answer. Worth stating explicitly, because the rule elsewhere is strict enough that an implementer may otherwise assume cross-submission work is forbidden everywhere.

**Transcription triage is its own interface, run before extraction.** It is a different task from grade review, with a different rhythm and a different person potentially doing it, and mixing the two would corrupt the teacher-minute budget for review (R9, R12). Triage first, then grade.

### 7.6 How this compares to an existing platform

[GradeWithAI](https://www.gradewithai.com) is a useful publicly documented reference for what a commercial single-frontier-model version of this product looks like today. Its published architecture as of mid-2026: LMS integration (Canvas, Google Classroom, Google Forms, Microsoft Teams), teacher-uploaded or AI-generated rubrics, a **single frontier model** as the grading engine (it states it is "Powered by Gemini 3"), AI-generated-content detection, and a strong teacher-override workflow with regrade requests and manual score and comment overrides. It is FERPA-aligned and states student work is not used for model training.

That design independently validates several recommendations here: teacher-editable rubrics, a mandatory human-override path, and narrative feedback alongside scores. It also illustrates the gaps this architecture closes. A **single judge** inherits that judge's specific biases wholesale, which Section 2.2's finding (no single model is a reliable top performer across task types) makes directly relevant. A **cloud-only, single-provider** design cannot run locally, cannot function without network access, and ties the district's privacy posture to a third party's cloud rather than to hardware the school controls. Note precisely where the criticism lands, since this architecture also supports a hosted deployment (Section 0.7): the objection is to being cloud-*only* and to a single proprietary judge, not to cloud hosting as such. A school on the `cloud-hosted` profile here can move to `edge-local` without changing product, keeps its panel diversity either way, and runs open-weight models it could serve itself. That optionality is the difference, and it is worth more than a categorical refusal to run in a datacenter would be. And its AI-rubric-generation feature has no published construct-validity guardrail of the kind Section 6 specifies, which matters most precisely when a generated or auto-edited rubric is used to justify a grade.

### 7.7 The ingestion and transcription module 

Section 7.5 specifies how transcription *risk* is routed. This section specifies the module that produces the transcription in the first place. Every earlier version drew it as one box reading "OCR if needed" while simultaneously calling ingestion a real subsystem (§0.2) and naming it the acceptance-test line most likely to fail (§8.5). That gap is closed here.

#### The invariant this module exists to enforce (R38)

> **Evaluation happens against Markdown, never against a PDF. Every PDF entering the system passes through this module and leaves as a Markdown artifact, and no stage downstream of ingestion ever receives a PDF, a page image, or a byte of a source file.**

This is stated as an absolute because a single exception dissolves the guarantees the rest of the architecture rests on. Evidence spans are byte offsets into a text artifact (§7.4); the integrity gate verifies them against that artifact's bytes; the working store keys on offsets into it; the audit record behind a grade is explicable only if the text a judge saw is the text on record. A judge handed a page image instead has no offsets to cite, and the entire evidence-citation discipline — the mechanism that makes an 8B model's judgment defensible at all — silently stops applying to that submission.

"Every PDF" means every PDF, of every artifact kind, typed or handwritten: assessments, reference solutions, rubrics, and student submissions alike. A typed reference solution is not exempt for being machine-readable. It goes through the same module, produces the same kind of canonical artifact, carries the same provenance, and passes the same validation, because the downstream stages compare these artifacts against each other — V4's structural and semantic matching compares an assessment artifact to a submission artifact — and artifacts produced by different routes are not reliably comparable.

**This module is the sole gateway.** There is no second path by which a PDF becomes text anywhere in the system. If a future component needs document text, it reads a `document` row; it does not open a source file.

#### What it takes in and what it emits

**Input** is PDFs. Assessments and reference solutions may be typed; **student submissions are predominantly handwritten and scanned**, which is the hard case and the design target. Any of the four artifact kinds may arrive as one PDF or as several.

**Output** is a single **structured Markdown artifact** per logical document, plus a sidecar of per-region metadata. Markdown rather than plain text because the downstream stages need structure the text does not carry: question boundaries so Stage C can address a `(question, criterion)` cell, answer-region boundaries so a criterion's evidence can be localized, and preserved notation for equations and tables. Non-text content — diagrams, graphs, spatially-encoded tables, struck-through work — is emitted as a structured *description* rather than dropped (R45), which is what lets a criterion be scored against a drawing at all. Markdown rather than a rich layout format because evidence spans are byte offsets and a format with hidden state makes offsets unstable.

```
 ALL PDFs (1..N)   ──►  rasterize        ──►  transcription       ──►  assembly
 every artifact         every page,           VLM, one page per       ordered, deduped
 kind, typed or         no exceptions         call, no exceptions     provenance kept
 handwritten                 │
                             └─ text layer, where present, is extracted too and used
                                as a DIFFERENTIAL CHECK on the VLM output — never as
                                a substitute for it, and never as a way around this module
                                                                              │
                                                                              ▼
                                                            ┌──────────────────────────────┐
                                                            │ canonical Markdown artifact  │
                                                            │ content-hashed, immutable    │
                                                            │ + region metadata sidecar    │
                                                            └──────────────┬───────────────┘
                                                                           ▼
                                                              VALIDATION LADDER  V0..V4
                                                              pass → Stage A/C
                                                              fail → operator triage queue
```

#### The transcription model

**Reference choice: `Qwen3-VL-8B-Instruct`**, on the basis of external testing showing it handles scanned handwritten exam pages and converts them to Markdown reliably. It is open-weight, fits the `edge-local` memory profiles alongside the judge panel, and is reachable through OpenRouter for the `cloud-hosted` and `dev-ci` profiles, which R27's provider abstraction requires of every model in the system.

It is a model in the scoring path's supply chain, so the same discipline applies to it as to any panel member (R37):

- **Version-pinned** with a resolved build identity, not a friendly name (§6.7, §8.7). A transcription model that changes underneath a package silently changes every grade produced with it.
- **Backend-scoped in the validation record** (R30). A local 4-bit quantization and a hosted build transcribe differently, and the difference lands on exactly the students §7.5 identifies as most at risk.
- **Validated on the actual medium.** Benchmarking transcription on clean typed text and discovering handwriting at a pilot site is the specific mistake §8.5 warns about. The conformance suite's fixture set (§8.7) must include real scanned handwriting spanning legible to marginal, and the acceptance gate measures transcription quality on it.

**The transcription model and the evaluation panel are chosen independently, on unrelated criteria, and neither choice constrains the other.** This is worth stating plainly because the two decisions look superficially like the same decision — "which open-weight model do we use" — and they are not:

| | Transcription model | Panel judges |
|---|---|---|
| Task | Reproduce marks on a page as text | Judge a response against a criterion |
| Selected on | Recognition accuracy on real handwriting, layout parsing, notation fidelity | Chance-corrected agreement with teacher labels, low bias, family diversity |
| Failure modes | Misrecognition, hallucinated completion of illegible text, layout misparsing | Position bias, anchoring, halo, the consistency-bias paradox (§2.3) |
| How many | Exactly one | 2 to 3, from different families, deliberately decorrelated |
| Redundancy strategy | The validation ladder and §7.5's impact routing | A diverse panel |

The panel will in practice be **stronger and more carefully bias-validated models than the transcription model**, because judgment is the harder task and the one the whole architecture is built to make trustworthy. That is expected, not a compromise: an 8B vision model reading handwriting well says nothing about how a 30B text model scores a partial-credit physics answer, and the reverse is equally true.

Two specific inferences to avoid, both of which a careful reader will otherwise draw:

- **§8.2's caution about Qwen 3 8B being the most position-biased judge in the Berkeley cohort does not transfer here.** Position bias is a property of comparative judgment, and this model makes none — it transcribes. Do not read the judging caution as a reason to avoid the family for transcription.
- **Equally, good transcription performance is not evidence of judging ability.** Qwen3-VL-8B-Instruct being the right transcription choice is not an argument for a Qwen model in the panel. Panel membership is earned against accumulated labels via the MVVP (§2.5), by a model chosen for that job.

#### Every page goes through the model

Each PDF is decomposed to pages, and **every page is rasterized and transcribed by the VLM** — one page, one call, no exceptions by artifact kind or by whether the page happens to carry an embedded text layer. Rasterization DPI is a pinned profile parameter, not an incidental choice: it changes recognition quality and it changes image token count, which is most of the cost.

Uniformity here is a correctness property, not tidiness. Mixed pages are the common case — a printed question paper with handwritten answers written onto it — so a per-page choice of extraction method would mean a single document assembled from two different transcription processes with two different Markdown conventions. Downstream, V4 compares an assessment artifact against a submission artifact structurally and semantically, and criterion text has to align with what a judge reads; artifacts produced by different routes are not reliably comparable. One process for every page keeps them so.

**Where a page does carry a genuine embedded text layer, extract it as well — as a cross-check, not as a substitute.** This is free, deterministic ground truth for that page, and it makes the strongest oracle available anywhere in the ingestion pipeline: a differential comparison against the VLM's output. Two uses, both worth having:

- **It catches transcription drift on exactly the artifact where drift is most dangerous.** A model asked to transcribe text it can already read will occasionally *improve* it, and a silently corrected reference solution is a corrupted answer key that every subsequent grade is measured against. Divergence between the text layer and the VLM output on a reference solution is a hard stop, not a warning.
- **It is a continuous, zero-cost quality signal on the transcription model itself.** Every typed page in the corpus is a free labeled example. A rising divergence rate across runs is early evidence that the pinned build changed, that quantization is hurting, or that DPI is set too low — the same signal §8.7's conformance suite produces, obtained as a by-product of ordinary operation.

Record per page whether a text layer was present and, when it was, the measured divergence. "How closely did the model reproduce text we could read exactly" belongs in the audit record, and a reader assessing whether to trust a grade will want it.

#### Graphical regions become descriptions dense enough to score from (R45)

A great deal of what a student submits is not text. Free-body diagrams, geometry constructions, an arrow showing the direction of a force, a plotted graph, a table whose meaning lives in its column alignment, labels connected by leader lines to particular objects, crossed-out working, a correction squeezed in above an earlier line — all of these carry the reasoning a criterion is meant to evaluate, and none of them survive a transcription pass that only lifts characters off the page.

**For every non-text region, the module emits a structured description into the Markdown, and that description must be complete enough that the extraction stage can localize every fact a criterion might turn on.** This is the working definition of "detailed enough": not that a human would recognize the drawing from it, but that no criterion attached to this question could need a fact the description omits. If a criterion asks whether the normal force is drawn perpendicular to the surface, the description has to state the direction of each arrow relative to each surface; a description reading "a free-body diagram with several labelled forces" has thrown away the entire content of the judgment.

What that means per kind of element:

| Element | The description must carry |
|---|---|
| Free-body diagram | Every arrow: its label, origin point, direction (angle, or relation to a named surface or axis), and relative magnitude where drawn to scale. The body itself, and which arrows attach to it |
| Geometry construction | Named points, segments, and angles; which lines are marked congruent, parallel, or perpendicular; auxiliary constructions and what they connect |
| Graph or plot | Axis labels and units, scale, plotted shape, intercepts, turning points, asymptotes, any marked or annotated coordinates, and whether the curve passes through or merely near the data |
| Table whose meaning depends on alignment | Emitted as an actual Markdown table. The alignment *is* the relation; flowing it into prose destroys it |
| Labels and annotations | What each label attaches to, and how the attachment is indicated — leader line, adjacency, arrow, bracket |
| Spatial relations generally | Above/below, left/right, inside/outside, connected/unconnected, stated explicitly, since the reader of the Markdown has no image |
| Selection marks on a multiple-choice item | Which option is marked and how — filled bubble, tick, cross, circled letter, letter written in the margin. Multiple marks, marks between options, and erasures are reported as such rather than resolved (§7.8, R55) |
| Crossed-out working | Marked as struck through, with its content preserved (see below) |
| Correction written above an earlier line | Marked as superseding, with both the original and the correction preserved |

#### Describe, never evaluate

This is the constraint that keeps the previous one from becoming dangerous, and it deserves stating as forcefully as the extraction-integrity rule it protects.

**A description states what is on the page. It never states whether what is on the page is correct.** "An arrow labelled N originates at the block and points away from the inclined surface, approximately perpendicular to it" is a description. "The student correctly shows the normal force perpendicular to the surface" is a verdict — rendered by the transcription model, outside the isolation boundary, before any judge has seen the work.

Consider what that does to the architecture. Every judge reads the same description (§7.4). A judgment smuggled into it is therefore inherited by the whole panel, which then agrees unanimously — and §7.4's confidence inversion does not fire, because the spans verify and the evidence is present. It is precisely the common-mode failure R19 exists to prevent, arriving through a channel R19 does not watch, introduced by the one component in the system that was never supposed to be making judgments at all (§7.7's separation of the transcription model from the panel).

The discipline is the same one §5.10 applies to band descriptors: **state what it does, not how good it is.** Evaluative vocabulary — correct, valid, appropriate, properly, as expected, should be — has no place in a description, and both the prompt template and the acceptance fixtures should check for it.

#### Retracted and superseded work is preserved, never flattened (R47)

Crossed-out work and corrections are not noise to be cleaned up. They are the difference between a student who did not attempt something and one who attempted it, saw the error, and fixed it — and between work the student is offering for assessment and work they have explicitly withdrawn.

So the Markdown represents them rather than resolving them:

- **Struck-through content is retained and marked as struck through.** A criterion may legitimately need to know that a wrong approach was abandoned; more to the point, a transcription that silently deletes it has made a grading decision about what counts.
- **A correction written above or beside an earlier line is marked as superseding it**, with both versions present and the relationship stated. Which one a criterion should score against is a rubric question, not a transcription question, and the transcription must not answer it by discarding one of them.

This is R36's absent-versus-blank distinction applied to graphical edits, and it fails the same way when collapsed: once "crossed out" has become "not written," nothing downstream can recover the difference.

#### Described regions are higher-risk evidence, and the system must know it (R46)

There is a gap here that is easy to miss and important to name. §7.4's integrity gate verifies that a cited span's byte offsets resolve to the claimed text in the canonical Markdown. For a described region, **that check proves the judge quoted the description faithfully. It proves nothing about whether the description is faithful to the drawing.** Span verification cannot see the image.

So evidence originating in a described region carries a risk that text evidence does not, and the design treats it accordingly:

- **Regions are marked by kind in the metadata**, so every downstream stage can tell a student's own words from a model's account of a picture, and a judge is told which of its evidence is described rather than transcribed.
- **The image crop is retained and shown to the teacher** whenever a reviewed criterion's evidence lies in a described region. This is the only point in the pipeline where a human can check description fidelity at all, so it has to be one click, not a hunt through the original PDF.
- **Described regions feed §7.5's impact routing.** The rule there — a criterion cannot be auto-scored when a low-confidence transcription region overlaps its evidence span — extends to described regions: description is inherently less certain than character recognition, and a criterion whose evidence lies wholly inside a description is a routing candidate on that basis alone.
- **Second-family description on high-risk criteria only**, mirroring §7.4's second-family extraction. Two independent descriptions of the same crop that disagree on a load-bearing fact is a detectable signal; a single description is unfalsifiable. Reserve it for criteria the risk register marks high, since it doubles the cost of the most expensive part of ingestion.

**Structural completeness has to account for this too.** Gate V2 checks that every question has an answer region; a question answered entirely by a diagram must not be recorded as `absent` merely because it contains no prose. A described region is present content.

#### Assembly: several PDFs into one artifact (R33)

A single logical document routinely arrives as several files — a scanner that splits after N pages, a phone camera producing one PDF per photo batch, a student answering on a continuation sheet handed in separately. Concatenating them in whatever order the filesystem returns is the obvious implementation and it is wrong in a way that produces plausible-looking output: an answer sheet assembled out of order transcribes fine and then fails to match its questions, and the failure surfaces as a low grade rather than as an ingestion error.

Assembly rules:

- **Order is explicit and recorded.** Take it from the operator's stated order, from a printed page number or fiducial marker on the sheet (§7.5's structured answer templates make this reliable), or from filename ordering — in that order of preference, recording which was used. Never from directory iteration order, which is not stable across platforms.
- **Every output region carries page provenance**: source file hash, page index within that file, and position in the assembled sequence. This is what lets a teacher reviewing a flagged criterion be shown the actual page it came from, and what lets a re-scan of one page be substituted without re-transcribing the rest.
- **Duplicate pages are detected, not concatenated.** The same page scanned twice — common when a batch is rescanned after a jam — is caught by page-image or transcript similarity and surfaced for confirmation. Silent duplication doubles a student's answer and can move a score.
- **Sequence gaps are detected.** A jump in printed page numbers, or a discontinuity in the question sequence, is a missing page and feeds gate V1 below.

#### The canonical artifact, and why it must be immutable (R32)

This is the constraint that follows from the existing design and was never stated. §7.4's evidence-integrity gate verifies that every cited evidence span's byte offsets actually resolve to the claimed text in the source. That check is only meaningful if the source cannot change. The assembled Markdown is therefore:

- **Content-hashed**, with the hash recorded in the audit record behind every grade derived from it
- **Immutable once accepted.** Corrections — a re-scanned page, a resolved transcription cluster (§7.5), an operator fixing a misparsed question boundary — produce a **new version** with a parent pointer, exactly as packages do (§9.4).
- **Invalidating on re-version.** Work units computed against version *n* are invalidated when version *n+1* supersedes it, via the content-hash work IDs of §9.10, which already make this automatic rather than bookkeeping. Editing the transcript in place while verdicts referencing its offsets already exist is the failure this rule prevents, and it would be invisible: the spans would still resolve, to different text.

#### The validation ladder

Five gates, cheapest first, run before an artifact can enter Stage C. **Every gate's output is a routing decision, never a score** (R34). This is the same principle as §7.4's "empty ≠ zero," applied at the point where the distinction is still recoverable — once a missing page has been scored as an unanswered question, nothing downstream can tell it apart from a student who wrote nothing.

| Gate | Checks | On failure |
|---|---|---|
| **V0 File integrity** | PDF opens, not encrypted, page count > 0, pages not blank or near-blank, resolution above the profile's floor | Quarantine as unreadable; operator rescans. Never proceeds. |
| **V1 Page completeness** | Assembled page count against expectation; printed page-number sequence continuity; duplicate-page detection; continuation-sheet reconciliation | Quarantine with the specific missing or duplicated pages named |
| **V2 Structural completeness** | Every question in the assessment has a corresponding answer region in the submission; every question the assessment declares is present in the assessment artifact itself. For multiple-choice questions, that the region contains a *resolvable* selection (§7.8) | Route to operator with the specific question IDs. **Absent region ≠ blank answer** (R36); an ambiguous or multiple mark is routed, never resolved or scored incorrect (R55) |
| **V3 Identity** | Student name or ID extracted and matched against the cohort roster | Ambiguous or unmatched routes to triage; never guessed |
| **V4 Assessment match** | Does this submission actually belong to this assessment? See below | Halt scoring for this submission; route to a human. **Never auto-reassign** (R35) |

V2 deserves emphasis on one point. "There is no answer region for question 4" and "question 4's answer region is empty" are different facts with different consequences, and an implementation that represents both as an empty string has destroyed the distinction permanently. The first is an ingestion failure and must not be scored. The second is a legitimate zero. Represent them distinctly in the region metadata from the first moment they are known.

#### Gate V4: the wrong-test submission

This is the gate that most justifies the module, and the reasoning is worth spelling out because the failure it prevents is invisible to every downstream defense the architecture has.

Honest mix-ups are expected at scale: an answer sheet for last term's paper handed in with this term's, two sections sitting different versions of a paper and the piles getting crossed, a scanner operator processing the wrong stack. At 350 submissions per class across multiple sections, this is not an edge case — it is a recurring operational reality.

Consider what happens without this gate. The submission transcribes cleanly. Every criterion's extraction runs and legitimately finds no matching evidence, because the student answered different questions. Every judge independently scores zero. **The panel is unanimous, and §7.4's confidence inversion does not fire, because the evidence is not corrupt — it is genuinely absent.** The system therefore reports a confident, high-agreement zero for a student who may have answered their actual paper perfectly. Section 0.3's trust argument says a teacher who catches the system being wrong twice will correctly abandon it; this is the single most abandonment-inducing output the system can produce, and no gate after ingestion can catch it.

It is also cheap to catch, and cheap to catch *early*: detecting it at ingest costs a handful of calls, while detecting it never costs roughly 66 wasted model calls per submission and a catastrophic wrong result.

**Layered signals, cheapest and most reliable first:**

1. **Explicit identifiers.** A QR code or printed assessment ID on the answer sheet, which §7.5's structured templates already recommend for deskewing and page identification. Where present this is decisive and nearly free — one more reason those templates repay their printing cost.
2. **Structural fingerprint.** Question count, numbering scheme, and per-question answer-region shape compared against the assessment. A five-question paper matched against a submission with eight numbered answers is a mismatch regardless of content.
3. **Semantic correspondence.** For each question, cheap similarity between the assessment's question text and the submission's answer region — restated prompts, shared domain vocabulary, expected notation. Aggregate across questions rather than trusting any one, since a genuinely poor answer legitimately looks dissimilar. What distinguishes a weak student from a wrong paper is that the weak student is dissimilar on *some* questions; the wrong paper is dissimilar on *all* of them, systematically.
4. **Cohort and roster context.** A submission whose extracted student identity is not on this cohort's roster is a candidate mismatch even when everything else looks plausible.

**Outcome is three-valued, and the middle value is the important one:** `match` proceeds; `mismatch` halts; **`uncertain` also halts.** A binary gate forces a bad choice between blocking correct submissions and passing wrong ones, and the class where the signals are weakest — sparse answers, poor handwriting, an unconventional response style — is exactly the population §7.5 identifies as already disadvantaged by transcription. Routing uncertain cases to a human keeps the error asymmetric in the safe direction.

**The system never reassigns automatically.** Where a mismatch is detected and other assessments are available to compare against, the system may *propose* candidates ranked by the same signals, and a human confirms. Automatic reassignment is refused for two reasons: it is a data-integrity operation performed on a guess, and it removes the human moment where the actual mistake — a crossed pile, a mislabeled stack — gets noticed and corrected at its source rather than papered over one submission at a time.

**Validate in both directions.** The user-visible mistake is usually "answer sheet submitted against the wrong test," but the inverse happens too: the *assessment* uploaded for a cohort is the wrong version, in which case every submission fails V4 identically. A high V4 failure *rate* is therefore a distinct signal from an individual failure and should be surfaced differently — one mismatched submission is a student-level triage item, and 340 mismatched submissions is one operator-level error with one fix. Wire that as a circuit breaker in the same spirit as §7.1's escalation-spike breakers: halt the run and ask, rather than generating 340 triage items.

#### What this costs, and where it runs

The transcription pass is one VLM call per rasterized page. For a five-question assessment at 350 students with roughly four pages each, that is about 1,400 page calls, plus the assessment, reference solution, and rubric.

That is around 6% of the ~23,100 scoring calls (§8.4) by count, but **it is not 6% of the wall clock**, and prior versions were wrong to leave it out of the arithmetic entirely. Each page call carries an image in the input — on the order of a thousand or more tokens depending on rasterization DPI — and emits several hundred tokens of Markdown, and vision encoding is slower per token than text. Treat OCR as plausibly the same order of magnitude as the scoring pass in wall clock rather than a rounding error on it, and **measure it in the §8.5 acceptance test rather than estimating it**, which that section already requires.

Two placement consequences:

- **On `discrete-gpu` and `unified-small` profiles the VLM is its own residency slot** (§8.1). Run the entire ingestion pass for the whole cohort, unload, then load the first judge. This is the same whole-batch-per-model discipline the judge loop already follows, and per-submission interleaving of OCR and scoring would be fatal for the same reason.
- **Ingestion is fully parallel and has no ordering constraint**, unlike the extraction sweep. Pages are independent, so this stage is the easiest place in the pipeline to saturate available concurrency.

Describing graphical regions is the part of this that varies most. A page of prose emits a few hundred tokens; a page whose answer is a free-body diagram with eight labelled arrows emits substantially more, and a high-risk criterion may warrant a second description from a different family (R46). Budget transcription output per page as a range rather than a constant, and measure it on real submissions in the §8.5 acceptance test — the medium that dominates the cost is the medium the deployment actually receives.

The validation ladder adds a small number of calls per submission for V4's semantic signals and none for V0 to V2, which are deterministic checks. Against the cost of the failure it prevents, that is not a trade-off worth analyzing.

#### Where it sits in the flow

Ingestion runs before Stage A's rubric decomposition for the assessment artifacts, and before the Stage C extraction sweep for submissions. Validation failures never enter Stage C at all: they land in the operator's quarantine list (§9.16), which is the same surface §7.5's transcription triage uses and a different surface from the teacher's grade-review queue. This matters for R9 and R12 — quarantine triage is operator work with a different rhythm, and letting it consume the teacher-minute review budget would defeat the budgeting the whole review design rests on.

### 7.8 Mixed-format tests: deterministic items alongside judged ones (new in v3.0)

Teacher feedback on the design was that real tests are not purely constructed-response. A paper that is mostly open questions will often carry a handful of multiple-choice items, and a system that cannot ingest such a paper is a system the teacher has to work around. This section specifies mixed-format support.

#### The architectural shape: a different evaluator, an identical pipeline

A multiple-choice item has a known correct answer. Its evaluation is a **lookup against a declared answer key**, not a judgment — there is nothing for a panel to be uncertain about, no rubric to interpret, and no construct to preserve. This makes the integration far smaller than it first appears, provided one framing is adopted:

> An MCQ item is a criterion whose **evaluator is a deterministic comparison rather than a panel**. Everything downstream of the verdict is unchanged.

Concretely it slots into the existing model as a binary criterion carrying `evaluation_mode = 'deterministic'` and `scoring_model = 'atomic'` (an MCQ criterion is atomic by construction, so §5.3's decomposability test does not arise), two bands — `correct` and `incorrect` — which is already an even band set with no middle (§5.10, R40), and points derived from the band by the same mapping as everything else. Aggregation, the review queue, the audit record, points summing into question and test totals, package portability: all identical. **The panel is simply not invoked.**

What changes is where the risk lives.

#### How ingestion knows which is which

The transcription module does not classify question types on the fly, and should not: guessing a question's format per submission would mean 350 independent chances to get it wrong, with the error surfacing as a grade rather than as an ingestion problem. The determination is made **once, on the assessment, and is then a lookup**.

**Phase 1 — ingesting the assessment (once per package).** Here there is genuinely nothing to consult, so the module *proposes*. A question carrying an enumerated option list, selectable markers (bubbles, boxes, lettered alternatives), and an instruction like "circle" or "select one" is proposed as `mcq`; a question with a ruled response area and no option list is proposed as `open`; a question with both is proposed as `mixed`. The proposal includes the option set for each MCQ question, since that becomes the `mcq_option` rows.

**The teacher confirms the proposal, and supplies the answer keys.** This is the §6.4 elicitation pattern and the same R9 time budget applies: the module presents its inventory — "Q1–Q3 multiple choice with four options each, Q4 open, Q5 circle-and-explain" — and the teacher corrects it and enters the keys. The system never infers an answer key from the assessment; a key is ground truth and comes from the teacher. Getting this wrong is cheap to fix at setup and expensive to discover at hour two of a batch, which is the same argument §8.4 makes for checking the prefix budget at Stage A.

**Phase 2 — ingesting submissions (every submission thereafter).** The module is **told**. `question_type`, the option set, and the answer regions are already in the package, so transcription is targeted extraction against a known structure rather than open-ended layout analysis: for question 3 it is looking for exactly one of four known markers in a known region, and for question 5 it is looking for a marker *and* a prose region. This is strictly more reliable than classification, and it is what makes gate V2's "does this region contain a resolvable selection" check meaningful — the module knows a selection is supposed to be there.

It also means a **structural disagreement is a finding rather than a silent adaptation**: a submission whose question 3 region contains prose and no markers, when the package says question 3 is multiple choice, is not quietly re-read as an open answer. It is a V2 failure routed to the operator, and at scale a *pattern* of such failures is a V4 signal that this is the wrong paper (§7.7).

#### Questions that are both

"Circle the correct answer and explain your choice" is common enough that it has to work, and it is the reason **evaluation mode is a property of the criterion rather than of the question.** Such a question carries one `deterministic` criterion for the selection and one or more `judged` criteria for the explanation. The panel sees only the judged ones; the selection is a lookup; the points sum into the question total as usual.

One consequence deserves an explicit default, because it is a scoring-model decision that will otherwise get made by accident. **The explanation is judged on its own merits, independent of whether the selection was correct.** A student can select wrongly and reason well, or select correctly by luck and reason badly, and those are different results that a naive coupling would collapse. If a teacher genuinely wants the explanation's credit to be conditional on the selection, that is a declared criterion dependency under §7.2 Rule 2 — visible, teacher-authored, and inside the §6.2 lock — never an implicit behaviour of the mixed question type.

Note also that the judged criteria of a mixed question must not receive the selection as context. Telling a judge "the student chose B, which is correct" before it evaluates the explanation is an anchor, and it is exactly the contamination §7.2's isolation boundary exists to prevent. The deterministic verdict and the judged verdict are computed independently and combined only at aggregation.

#### The risk moves from judgment to transcription

For an open question, the hard problem is whether the judgment is right. For an MCQ item the answer key is right by definition, and **the entire remaining risk is whether we correctly read which option the student selected.** That is the ingestion module's problem (§7.7), not the panel's, and it is a real problem on scanned handwritten papers:

| Situation | Correct handling |
|---|---|
| One clear mark | Extract the option, score deterministically |
| Two or more marks | **Ambiguous** — never pick one, never score as incorrect |
| A mark erased or crossed out with another added | Apply §7.7's retraction rules (R47): the struck mark is retracted, the remaining one is the answer, and both are preserved |
| A mark placed between two options | **Ambiguous** — route |
| A letter written in a margin instead of a bubble filled | Valid selection; the description must capture it (R45) |
| No mark anywhere | **Blank**, which is a legitimate zero — distinct from a page that is missing, which is not (R36) |
| Mark present but the region is unreadable | **Absent**, an ingestion failure, not a wrong answer |

The last three rows are R36's distinction — absent, blank, present — applied to mark reading, and they fail the same way if collapsed. **An unresolvable mark is never silently resolved to an option, and never scored as incorrect (R55).** A student who selected the right answer in handwriting the scanner could not resolve has not answered wrongly.

**Ambiguity here is operator work, not teacher work.** "Which option is this mark?" is a transcription question with a rescan or a glance at the crop as its remedy. It belongs in §7.5's transcription triage queue, run before grading, and must not consume the teacher-minute review budget that R9 and R12 exist to protect. Mixing them would make a stack of smudged bubbles compete with genuine grade disputes for the same thirty minutes.

#### The statistical trap, and why it matters beyond hygiene

Deterministic items agree with the teacher essentially always. Folding them into the package's agreement statistics therefore **inflates the headline figure with items that involved no judgment at all** — a test that is 40% multiple choice would report markedly better agreement than a pure constructed-response test of identical quality, purely as an artifact of its format. This is §2.1's inflated-agreement error and R51's don't-merge-holistic-with-atomic error arriving one level up, and the fix is the same: **MCQ correctness is reported separately and never enters any agreement, κ, or quality figure for the judged portion of the test (R53).**

There is a second reason to be strict about this, and it is the more important one. §0.1 identifies the problem this system exists to solve: assessment format degrading to whatever is mechanically gradeable, so that constructed responses stop being assigned at all. If the system's own reporting makes multiple-choice items look better — higher agreement, higher confidence, near-zero cost, no review queue — it applies exactly the pressure §0.1 describes, from inside the tool built to relieve it. Supporting mixed-format papers is right. Letting the dashboard quietly reward the multiple-choice half is not, and separate reporting is what prevents it.

What deterministic items *should* feed is the class-level diagnostic (§10), where they are genuinely strong: exact per-item difficulty, and distractor analysis showing which wrong option the cohort chose, which at n=350 is a sharp signal about a specific misconception. Report that prominently. Just never as evidence about the grader.

#### The rest of the integration

- **Question type is declared in the package** and is part of the schema lock (§6.2): converting an open question to multiple choice, or the reverse, is a redefinition of what is being assessed, not a clarification.
- **Answer keys are exact and versioned.** Single-select is the default; multi-select and its partial-credit policy (all-or-nothing, or per-option) are declared by the teacher rather than inferred. Negative marking, if used, is declared for the same reason.
- **Structural validation extends naturally.** Gate V2 checks that every question has an answer region; for MCQ it also checks that the region contains a resolvable selection. Gate V4's assessment-match check gets *stronger* with MCQ present, since option counts and per-question option labelling are a precise structural fingerprint of which paper this is (§7.7).
- **Throughput improves proportionally.** MCQ items consume no scoring calls and no extraction calls, so a paper with 20% multiple-choice items costs roughly 20% less than §8.4's arithmetic implies. They still cost ingestion, which is where their work is.
- **The results side of the data model distinguishes the two modes explicitly**, because several invariants stop holding for a deterministic criterion. It produces no `verdict` rows, so its `criterion_score` carries `judge_count = 0` — the odd-panel constraint of R48 admits zero alongside 1, 3 and 5 precisely so this is expressible. Its extracted answer lives in `document_region.selection`, with `selection_state` able to say `ambiguous` or `multiple_marks` rather than being forced into an option (R55). An unresolvable mark sets `state = 'unresolved_selection'` and routes to `'triage'`, the operator queue, not the teacher’s (R54). And `label.evaluation_mode` is what makes R53 enforceable from the data rather than by convention: agreement is computed over blind, judged rows only.
- **Distractor analysis has its own tables.** `mcq_item_stats` holds the per-option response distribution and `mcq_item_summary` the item difficulty, blank count, and unresolved count. Keeping the unresolved count separate matters: a question with many unreadable marks is a scanning problem, and reading it as a difficult question would send the teacher to reteach something the cohort may have answered correctly.
- **The rubric-calibration machinery of §6 does not apply.** There is no ambiguity to elicit and no construct to drift; a wrong answer key is a straightforward error the teacher corrects, and the version pin records when it changed.

### 7.9 From criterion scores to a final grade (new in v3.1)

Versions before 3.1 stopped at the criterion score. Roll-up was described in one sentence — "points aggregate arithmetically up the tree" — and there was no object anywhere holding a student's final grade, no way for a teacher to say how their marks should be combined, and no definition of the grade boundaries that §10's review ranking already claimed to use. This section closes that, and it is a correction to the product, not a detail.

#### The principle this rests on

**Every submission receives a complete final grade, computed automatically, with no per-student teacher action (R56).**

This is not an efficiency target; it is the system's reason to exist. §0.1's argument is that at 250 to 350 students the counterfactual is *no substantive feedback at all*, because the arithmetic of marking defeats the teacher. A design that produces criterion-level judgments but leaves a human to compile 350 final grades has reproduced the bottleneck one level up and delivered nothing. **Teacher effort must scale with the review budget they choose (R12), never with class size.**

The corollary is where the teacher's time actually goes, and it should be stated plainly because it inverts the intuition:

> The teacher invests time **once**, at the front, calibrating the instrument on the order of 10 to 15 papers (§6). After that they sample and spot-check. They do not compile grades, and they do not review 350 papers to produce them.

Risk follows from this, and the design accepts it deliberately rather than pretending otherwise. Grades will be issued that no human inspected. The mitigations are everywhere else in this report — evidence citation, the panel, confidence routing, the review queue ranked by what could actually move a grade, the blind sample, the provisional marking of unreviewed items — and none of them is a reason to withhold the grade. **An unreviewed grade, honestly labelled, is the product. A withheld grade is a failure to deliver it.**

#### The teacher declares the process; the system applies it

Combining marks is a professional decision that belongs to the teacher and varies by subject, institution, and assessment. A hardcoded weighted sum is a policy masquerading as a mechanism. So the teacher declares a **grade policy** once, at setup, alongside the rubric — and the system then applies it to every submission without asking again (R57).

**It is declarative, not a script.** A free-text formula field, or embedded code, would be unauditable, impossible to show a teacher in plain language, and impossible to reproduce faithfully three years later when a grade is disputed. Instead the policy is a small vocabulary of composable rules stored as data:

```json
{
  "per_question": {
    "Q1": { "rule": "sum_criteria" },
    "Q4": { "rule": "sum_criteria",
            "gate": { "criterion": "c12", "requires_band_at_least": "met",
                      "else_question_points": 0 } }
  },
  "test_total":  { "rule": "sum_questions", "drop_lowest_n": 0 },
  "scale_to":    100,
  "rounding":    "half_up_1dp",
  "boundaries":  [ { "min": 80, "grade": "A" }, { "min": 70, "grade": "B" },
                   { "min": 60, "grade": "C" }, { "min": 50, "grade": "D" },
                   { "min":  0, "grade": "F" } ]
}
```

**A default policy exists so that even this cannot stall a run.** If the teacher declares nothing, the system uses sum-of-criteria into sum-of-questions, raw points, no boundary table, and shows that in plain language for them to change whenever they like. Declaring a policy is strongly worth the five minutes; not declaring one produces defensible totals rather than no grades. The only setup item that genuinely cannot be defaulted is a multiple-choice answer key — there is no honest guess at which option is correct (§7.8).

The supported rules are deliberately few: sum with weights, a gate (a criterion or question whose failure caps or zeroes its parent), best-*k*-of-*n* or drop-lowest, scaling to a total, a rounding rule, and a boundary table. Anything a teacher needs that this cannot express is a finding worth collecting, not a reason to open the door to arbitrary code.

Three properties follow from keeping it declarative, and each matters:

- **It can be shown back in plain language** for approval: *"Each question is the sum of its parts. Question 4 scores zero if the safety analysis is missing. The total is scaled to 100 and rounded to one decimal. 80 and above is an A."* A teacher can approve that; nobody can approve a formula string.
- **It is inside the §6.2 schema lock and version-pinned** (§6.7). Editing the boundary table moves every grade in the cohort without re-running a single judgment — the same hazard as editing the band→points mapping (R43), and it gets the same treatment.
- **It is reproducible.** A grade issued in 2026 can be recomputed exactly, from the same criterion scores under the same policy version, which is what makes it defensible in an appeal.

#### Grade boundaries are now a real object

§10 ranks the review queue partly by *proximity to a grade boundary*, and `ReviewItem` carries a `grade_boundary_delta` — but nothing in the design defined a boundary. That was a dangling reference: the ranking could not actually be computed. Boundaries now live in the grade policy (R59), which makes the review ranking implementable and gives the teacher the one control that most changes which students the system asks them to look at.

#### Provisional inputs never block a grade

This is where an over-cautious reading of R26 would have destroyed the product. Unreviewed low-confidence criteria are marked provisional and carried forward — but **the grade is still computed and still issued.** Provisional means *labelled*, never *withheld*.

Every final grade therefore carries its own coverage record: how many of its criteria were auto-accepted, how many were reviewed by the teacher, how many remain provisional, and — the number that actually matters — whether the provisional ones could move the student across a boundary. Where they could, the student's grade is shown as a range rather than a point until reviewed. Where they could not, the grade is simply the grade, and there is nothing to escalate.

One case genuinely cannot produce a complete grade, and it must not be confused with the above: a criterion with **no score at all**, because a page was missing, a mark was unreadable, or a unit quarantined. That is an ingestion failure, not judgment uncertainty. Such a grade is marked incomplete, the specific missing input is named, and it goes to the **operator** queue as a rescan (§7.5, §7.8) — not to the teacher as a marking decision. These are few, and they are the only legitimate blocker.

Finalization is a **single batch action for the whole class**, and it names what it covers: *"Finalize 350 grades. 41 criteria across 28 students remain unreviewed; 3 of those could move a grade boundary."* One click, fully informed, recorded in the audit trail. Never 350 clicks.

#### Every teacher touchpoint, and whether it blocks (R60)

The automation principle is easy to assert and easy to erode one reasonable-sounding gate at a
time, so it is recorded here as a checkable inventory rather than a claim. **Two setup items
block, both once per package. Nothing in the recurring run does.**

| Teacher touchpoint | Phase | Blocks grades? |
|---|---|---|
| Confirm the question inventory | Setup, once | **Yes** — a test that has not been defined cannot be marked |
| Supply multiple-choice answer keys | Setup, once | **Yes** — there is no honest guess at which option is correct (§7.8) |
| Approve how the rubric was understood | Setup, once | No — defaults to the rubric exactly as written |
| Confirm decomposability classifications (§5.3) | Setup, once | No — defaults to preserving the criterion whole |
| Declare the grade policy and boundaries | Setup, once | No — a default sum applies, shown in plain language |
| Answer ambiguity-elicitation questions (§6.4) | Setup, once, optional | No — Stage B is skippable by design |
| Mark 10 to 15 calibration papers | Setup, once, optional | No |
| Work the review queue (§10) | **Every run** | **No** — unreviewed items are provisional, not withheld (R58) |
| Blind sample (R21) | **Every run** | **No** — skipping costs validation evidence, not grades |
| Whole-grade sample | **Every run** | **No** |
| Finalize the batch | **Every run** | **No** — automatic on completion or at window lapse |
| Drift check on package reuse (§9.4) | Per reuse | No — advisory, per R11 |

The one thing that legitimately stops a *particular* grade after setup is an **ingestion**
failure — a missing page, an unreadable mark, a submission matched to the wrong paper. Those
are few, they are named specifically, and they go to whoever handles scanning rather than to
the teacher (§7.5, §7.7). A rescan is not a marking decision.

**The test to apply to any future change:** could a teacher start a run, do nothing at all, and
still have every student graded the next morning? If the answer becomes no, the change has
removed the thing this system is for, whatever else it improved.

#### Sample the grades, not only the criteria

The review queue works at criterion level, and that is the right granularity for finding a mis-scored judgment. It is the wrong granularity for noticing that a student's *overall* result is implausible — every criterion can look defensible while the total lands somewhere a teacher would never have put it, and nothing in a per-criterion queue surfaces that.

This is a **recommendation, not a gate** (R60): grades are already final and delivered whether or not anyone looks. So the recommended practice, and what the interface should offer by default, is a **whole-grade sample**: 10 to 15 complete final grades drawn at random, shown as the student would receive them — total, boundary grade, per-criterion breakdown, and the feedback. The teacher reads them end to end and either recognizes their own standard or does not. It costs a few minutes, it is the fastest check available on whether the instrument as a whole is behaving, and it catches whole classes of error that per-criterion review structurally cannot.

Draw this sample from the auto-accepted population, not the flagged one, for the same reason §6.8's random spot-check arm exists: reviewing only what the system already doubted tells you nothing about what it was confident and wrong about.

---

## 8. Running it on open-weight models: locally on one machine, or hosted through OpenRouter

Sections 8.1 through 8.6 specify the `edge-local` profile — the hardest case, and the one that constrains the architecture. **Section 8.7 specifies the `cloud-hosted` and `dev-ci` profiles served through OpenRouter, which are equally required (R28, R29) and are where the code is actually developed and tested.** Everything in 8.3 and 8.4 — the compute-budget priority order, the loop nesting, the prompt field ordering, criterion batching, the prohibition on batch-prompting — is backend-independent and applies unchanged to both. Only the serving mechanics and the failure modes differ.

### 8.1 The local inference stack (mid-2026)

Apple Silicon is a credible platform here largely because of **unified memory**: RAM and GPU memory are shared, so a Mac with enough RAM holds a larger model than a discrete GPU at similar cost.

| Tool | Role | Notes |
|---|---|---|
| **Ollama** (0.19+) | Easiest path to an OpenAI-compatible local API | Now uses Apple's **MLX** backend on Apple Silicon; one command to pull and run |
| **MLX-LM** | Apple's native framework, direct Python/Swift access | Fastest raw inference on Apple Silicon; more setup; also supports local fine-tuning if you later specialize a judge |
| **LM Studio** | GUI wrapper | Good for demos and manual spot-checks, less suited to production batch scoring |
| **llama.cpp** | The underlying engine most of the above build on | Broadest format support; use directly only for control Ollama does not expose |

**Hardware guidance:** a 32GB Apple Silicon Mac comfortably runs 30B-parameter mixture-of-experts models at usable speed; 64GB handles 70B-class models. Since Section 7.1 recommends 2 to 3 moderately-sized models rather than one very large one, a single 32 to 64GB Mac is realistic for a classroom or small school. District-scale work is where a dedicated always-on Mac Studio, or a second machine, becomes worth considering. Note that within a single `edge-local` run, R1 forecloses the option a well-connected deployment would reach for here — bursting part of the batch to remote inference at peak — and forecloses it for a reason stronger than connectivity: a run whose criteria were scored partly locally and partly by a hosted build is a run with two graders in it (Section 0.7). Throughput in this profile therefore has to come from the execution plan in Section 8.4. A deployment that *does* have connectivity is not stuck with that ceiling; it runs the whole assessment on the `cloud-hosted` profile instead (Section 8.7). The choice is per run, not per call.

**On hardware portability (R2, R5), and the constraint version 2.3 stated too casually.** Apple Silicon is the reference target because unified memory gives unusually good capability per dollar and per watt, and because it is a single quiet appliance. But "portable to a consumer GPU" needs qualifying: a 24GB RTX 3090 or a 16GB card **cannot hold a three-model panel resident**, and attempting it produces out-of-memory failures or offloading that destroys the throughput the design depends on.

The architecture already accommodates this, but by accident rather than by contract. The Section 8.4 loop nesting puts the judge model outermost precisely so weights load once per model, which means the panel is *already* sequential rather than concurrent. Make that an enforced **hardware profile** rather than an emergent property:

| Profile | Memory | Residency policy | Panel |
|---|---|---|---|
| `unified-large` | 64GB+ Apple Silicon | May hold 2 models resident; swap the third | 1 or 3 judges, larger models |
| `unified-small` | 32GB Apple Silicon | One model resident at a time | 3 judges, 30B-class MoE or smaller |
| `discrete-gpu` | 16 to 24GB VRAM | **Exactly one model in VRAM at a time, weights purged before the next loads** | 3 judges, 8B-class, quantized |

Under `discrete-gpu` the orchestrator must complete a model's *entire* batch across all questions, criteria, and submissions before unloading it and loading the next family. This is the loop nesting taken to its conclusion, and it is what makes a commodity GPU viable at all. Budget for the swap: two or three load/unload cycles per run is minutes, which is acceptable; per-criterion swapping would be fatal.

**Quantization is a profile parameter, not a free choice.** Each profile should specify a quantization target (commonly 4-bit for the discrete-GPU profile) and record it in `panel_config`, because a package validated against one quantization is not automatically valid against another. Section 2.2's finding that judge behavior does not transfer across contexts applies here too.

**The KV cache competes with weights, and this ceiling must be explicit.** Continuous batching holds a KV cache per in-flight request, and that memory comes out of the same pool as the model. Each profile therefore needs a stated concurrency ceiling and a documented fallback: when projected KV memory would exceed the ceiling, reduce concurrency, and if concurrency falls below the point where batching still pays, drop to sequential serving and accept the slower run rather than crashing mid-batch. Measure this during the acceptance test (Section 8.5) rather than deriving it.

**What the hardware profiles do not constrain is the provider.** The table above governs the `edge-local` profile, where model weights and machine memory are the binding constraint. Under `cloud-hosted` and `dev-ci` there is no residency policy to enforce, no weight-swap cost, and no VRAM ceiling — the panel may be served concurrently, and the outermost-loop-is-the-judge-model ordering of Section 8.4 becomes a free choice rather than a forced one. Keep the ordering anyway, so that a package's execution trace is comparable across profiles; the cost of keeping it is nil and the cost of two divergent execution orders is that scores stop being comparable between the profile you tested on and the profile you shipped.

What the `edge-local` profile does require is that the serving endpoint is local for the whole of that run — per R1 there is no partial-remote configuration, only a whole-run choice of profile (Section 0.7).

**Power behavior matters as much as speed (R3).** A single Apple Silicon machine drawing tens of watts under sustained inference is within range of the battery-and-solar arrangements many target schools already run for other equipment. This is a real argument for the single-appliance design over a multi-GPU workstation, independent of purchase price, and it is worth confirming against the actual power situation at a pilot site before committing to hardware.

Budget for the extra passes this design adds. Dual-scoring (Section 6.5) costs one additional full-class pass whenever a rubric revision is proposed, and back-translation (Section 6.6) costs a handful of calls. Both are cheap relative to the panel itself, but they are not free, and they only run on assignments where calibration actually happened.

### 8.2 Model panel suggestions

Pick from **different families** so biases do not correlate. Reasonable Ollama-installable starting points as of mid-2026: a Llama-family model (Llama 3.3), a Qwen-family model (Qwen 3), and an open GPT-family model (GPT-OSS 120B if hardware allows, a smaller variant otherwise). Reserve one additional installed model outside the panel for adversarial checks (Section 7.3, item 5).

Treat this as a starting panel to validate against your own accumulated labels, not a fixed prescription. Per Section 2.2 rankings shift across task types, so the right panel for algebra proofs may not be right for history essays. Re-run the MVVP whenever you swap a member.

**The transcription model is a separate slot, not a panel member, and it is not chosen here.** `Qwen3-VL-8B-Instruct` (§7.7) occupies its own residency slot and its own version pin. It never scores anything, so none of this section's reasoning applies to it: no family-diversity requirement, no MVVP, no position-bias audit — those are properties of judgment, and it makes none. Conversely, nothing about it constrains the panel. **Expect the panel to be stronger and more carefully bias-validated than the transcription model**, because judging a partial-credit response is the harder task and the one the architecture exists to make trustworthy. The redundancy protecting against transcription error is the validation ladder and §7.5's impact routing, not a second opinion. Budget its memory alongside the panel under §8.1's profiles, and note that on single-residency profiles it runs as a complete pass before any judge loads.

**Choose panel members that exist on both backends (R30).** Because the same panel has to run locally at a school and through OpenRouter in CI and in hosted deployments, restrict the panel to open-weight families that are both locally servable and available as OpenRouter models. This is a real constraint on panel selection and it is worth accepting deliberately: a judge that only exists in one profile cannot be validated in the other, and its behavior in the profile you did not test is unknown. Note also that "the same model" across profiles is an assumption to be measured, not a fact — a 4-bit local quantization and a provider's served build differ, sometimes materially, which is why validation records are backend-scoped and the conformance suite of Section 8.7 exists.

One specific caution: the Berkeley study found **Qwen 3 8B was the single most position-biased judge in its 21-model cohort** (0.192) while also having the *highest* test-retest reliability (0.992). It is the textbook instance of the consistency-bias paradox. That does not disqualify the Qwen family, and larger Qwen models may behave differently, but it is a concrete reason to run Section 2.5's step 5 on any small model before trusting it, rather than reading its stability as reassurance.

### 8.3 Spending your compute budget correctly

Priority order, restated as a budget rule because it is the finding most likely to be misapplied:

1. **Decomposition** (extraction agent plus scoring agent). Largest single accuracy gain in the cited research, and it *helps smaller models most*, which is exactly your constraint.
2. **Model-family diversity** (3 judges; panel size is always odd, R48). Meaningful bias reduction at moderate cost.
3. **Guardrail passes** (dual-scoring, back-translation). Not accuracy improvements, but the difference between a defensible system and an undefensible one. Cheap.
4. **Reasoning effort** on models that support it. Real but smaller and non-monotonic; test per model rather than assuming more thinking is better.
5. **Same-model repeated sampling / majority voting.** Last, because the research shows near-zero benefit at the cost of items 2 through 4.

#### Paying for judgment isolation

Section 7.2's Rule 1 has a real cost and it needs planning for. Full isolation means **criteria × judges × submissions** judgments. Fifteen criteria, three judges, 350 students is 15,750 scoring calls plus extraction and synthesis, roughly 23,000 in total (Section 8.4). At this scale the mitigations below are not optimizations, they are what makes the system run at all. In order of impact:

**Prefix-cache the invariant context.** The rubric, the assignment, and the reference solution are identical across every judgment for a given assignment, and they are most of your input tokens. Caching that prefix is the single largest win available and, per Rule 1's explicit carve-out, costs you nothing in isolation terms. Current MLX-backed local stacks support this well.

**Batch by criterion, not by student.** Run every submission in the class for criterion 1 against one warm cache, then move to criterion 2. Batching by student invalidates the criterion-specific portion of the cache on every iteration. This ordering is also the one that makes Rule 1 easy to hold: you are never tempted to reuse a student-level context because you never assemble one. Section 8.4 gives the full loop nesting, including why the judge model rather than the question belongs in the outermost position.

**Earn a reduced panel over time.** Once your accumulated override log (Section 6.8) shows all three judges have agreed on a given criterion 98% of the time across a full semester, that criterion is a candidate for single-judge scoring, with the full panel reserved for contested criteria. This is a genuine optimization but an **earned** one: it requires the accumulated labels to justify it, so it belongs in Phase 3 or later (Section 12), never on day one. Re-open a criterion to the full panel whenever its override rate rises.

What you should *not* do to save compute: reuse context across submissions, collapse multiple criteria into one call, or let judges see each other's verdicts. Each of these buys speed by reintroducing exactly the bias the panel exists to remove, and each does so invisibly, since none of them degrade any metric you are currently watching.

### 8.4 Execution plan, parallelization, and the working store 

Judgment isolation (Section 7.2) plus prefix caching (Section 8.3) together determine the execution order. This is not a free choice to be made later by whoever writes the batch loop; the ordering is forced, and getting it wrong costs both throughput and score fairness.

#### The loop nesting

The most expensive context switch on a memory-constrained Mac is **swapping model weights**, not losing a prompt cache. A 30B model is tens of seconds to load, and on a 32GB machine you may not be able to hold three judges resident at once. So the judge model is the outermost loop:

```
for judge_model in panel:            # outermost: weights load once per model
  for question in test:              #   caches question text + reference solution
    for criterion in judged(question):  #   JUDGED criteria only (§7.8): deterministic
                                     #     ones never enter either sweep
      parallel for submission in class:   #  only this varies
        score(criterion, submission)      #  independent call, fresh context
```

**Deterministic criteria are not in this loop at all (§7.8).** A multiple-choice item is
scored by a key lookup against the selection the ingestion module already extracted, so it
generates no extraction call, no scoring call, no panel iteration, and no prefix-cache
traffic. It is evaluated once per submission in a single pass over the results, at a cost
indistinguishable from zero against the ~23,000 model calls beside it. This is the whole
performance argument for treating evaluation mode as a first-class property rather than
scoring everything through the panel and discarding the redundancy afterwards: the saving
comes from **never dispatching the work**, not from making it cheap.

Traversed depth-first, this gives a **prefix tree** rather than a flat cache:

| Prefix layer | Shared across | Rough size |
|---|---|---|
| System prompt + judge instructions | everything for that model | ~200 tokens |
| + question text + reference solution | all judged criteria in that question | ~800 tokens |
| + criterion definition + exemplars | every submission in the class | ~500 tokens |
| + extracted evidence + submission text | nothing, unique per call | ~300 tokens |

Roughly 1,500 of 1,800 input tokens are shared and cacheable at the innermost level. Depth-first traversal keeps the deepest prefix hot, which matters under any cache implementation and matters most under naive ones that retain only the most recent prefix.

**The shared prefix needs a hard token budget.** Those numbers assume a compact reference solution and two or three short exemplars. A STEM question with a full worked solution and six exemplars can push the prefix to several thousand tokens, and the cost is not linear in one place but two: it consumes the context window of a small model, degrading its reasoning on the part that matters, and it multiplies KV cache memory by the concurrency level, which is what causes an out-of-memory failure part-way through a batch that started fine.

So enforce a ceiling, on the order of 1,500 to 2,000 prefix tokens depending on profile, at **Stage A rather than at run time**. When a teacher's uploaded reference solution or exemplar set exceeds it, say so during setup, when it can be fixed, rather than failing at hour two of a batch. If the ceiling is still exceeded, drop the lowest-value exemplars rather than truncating the reference solution or the criterion text, and record in `run_metrics` which exemplars were dropped, since a package that silently grades with fewer anchors than it was validated with is no longer the validated package.

#### The prompt-template rule this forces

**The student submission must be the last thing in the prompt.** Every invariant (system instructions, rubric, criterion, reference solution, exemplars) comes first, in stable order.

This sounds trivially obvious stated plainly and is the single easiest thing to get wrong, because the natural way to write a grading prompt is "here is the student's answer, now here is what to look for." That ordering produces a zero percent cache hit rate and **no error message telling you so**. The system will simply be five times slower than it should be, for a reason nobody can see. Write this as a lint rule over prompt templates, not as a comment.

#### Batching by criterion is a fairness property, not just a speed one

Worth surfacing to non-engineers, because it upgrades this from optimization to requirement. When you batch by criterion, **every student in the class is judged against byte-identical context**: same rubric wording, same exemplars, same reference solution, same position in the prompt, same model weights. If you loop per student and anything varies across iterations, you have introduced a source of score variance unrelated to the student's work.

This also resolves a tension with Section 7.3 item 2. Under Rule 1 each judgment contains exactly one criterion, so there is no within-prompt criterion order left to randomize; isolation eliminated criterion-order bias structurally rather than statistically. What remains is exemplar order, and the correct rule is: **fix exemplar order within a (question, criterion) batch, randomize it across batches.** That preserves the cache and is better methodology, since varying the anchor per student would make anchor choice a source of between-student variance. Speed and fairness point the same direction here, which is rare enough to be worth noticing.

#### The trap: batching is not batch-prompting

Batching by criterion means **N independent calls sharing a cached prefix.** It does not mean one call containing many submissions.

The second thing looks like the same optimization, is dramatically cheaper in tokens, and will occur to whoever implements this within about four minutes. It is also a total violation of Rule 1. Multiple submissions in one context is explicit cross-submission comparison, which is exactly the anchoring path the isolation boundary exists to close, and it reliably produces a spread-the-grades effect where the model implicitly ranks students against each other instead of scoring each against the rubric. The failure is silent and the code looks like a smart optimization in review. Put an explicit prohibition next to the batching guidance and assert it in a test.

#### The working store, and how dependencies actually resolve

Rule 2 dependencies need criterion 2's extraction artifact available when criterion 4 is scored. Under per-student looping that is a local variable. Under criterion-batched execution, criterion 2 finished for the entire class long before criterion 4 begins, so the artifacts must be persisted somewhere in between. That is the working store.

**Split Stage C into two sweeps:**

- **Sweep 1, extraction.** Batched by (question, criterion) over **judged criteria only** — a deterministic criterion has no evidence for a judge to read, so it is absent from both sweeps (§7.8) — executed in **topological order over the dependency graph**, writing every extracted evidence artifact to the working store. Topological order is required here because criterion 4's *extraction* may itself need criterion 2's extraction ("find the evidence the student presented" precedes "does the conclusion follow from it").
- **Sweep 2, scoring.** Batched by (judge, question, criterion), reading extraction artifacts from the store.

The consequence is worth stating because it is a genuine simplification: **once extraction completes, the store is fully populated, so the scoring sweep has no ordering constraint at all and can be scheduled purely for cache locality and weight-swap avoidance.** The dependency graph binds only the extraction sweep, which is the cheaper of the two (one small model, no panel multiplication).

**Store design:**

| Property | Specification |
|---|---|
| Key | `(run_id, submission_id, criterion_id)` |
| Value | Extracted evidence spans, offsets into the submission, extraction model + version |
| Judge dimension | **None.** Artifacts come from extraction, not judges (Rule 2), so all judges read identical values |
| Written by | Extraction sweep only |
| Read by | Scoring sweep (criteria with declared dependencies), both synthesis levels, Stage D evidence display |
| Persistence | On disk, not in process memory, so runs survive a crash and resume |
| Scope | Per run. Not a cross-run cache and not a memory the system accumulates |
| Retention | Purged on run completion, except the spans actually cited in a returned score, which move to the durable audit record (Section 6.7) |

SQLite is more than sufficient and gives you crash-safe writes and resumable reads without operational overhead. Do not reach for a vector store; this is keyed lookup, not similarity search. Section 9 specifies this store in full, along with the eight others the harness turns out to need, the work ledger that makes runs resumable, and the rule that keeps the persistence layer from becoming a contamination channel.

**Treat the working store as student PII.** It contains verbatim spans of student work. Put it in the same protected location as the submissions themselves, not in a world-readable temp directory, and wipe it on completion. On local hardware this never leaves the machine, which is the architectural privacy advantage from Section 11, but "never leaves the machine" is not the same as "safe to leave lying in `/tmp`."

#### Checkpointing and progress reporting change shape

Two second-order consequences that will otherwise be discovered late:

**The unit of completed work is the (judge, question, criterion) cell, not the student.** A crash at 60% leaves every student complete on criteria 1 through 7 and nothing on 8 through 12. Checkpoint at cell boundaries and make runs resumable at that granularity. Section 9.4 specifies the work ledger and the idempotency scheme that make this automatic rather than bookkeeping.

**You cannot show a teacher finished grades for the first 18 students mid-run**, because no student is finished until the last criterion completes. Progress reads "criterion 8 of 12, judge 2 of 3." Results release per question (once all criteria in a question are done for all students) or per test at the end. State this explicitly in the design or someone will build a per-student progress bar that can never be populated honestly.

**A free win:** because execution is grouped by criterion, the Stage E class rollup ("where did everyone struggle on criterion 2") is computed along the grain of execution rather than against it. The data arrives already grouped the way the rollup wants it.

#### Throughput arithmetic at n=350 (R10)

This is the calculation that determines whether the system is usable, and it should be run against real hardware before committing to a serving stack.

A five-question assessment with three criteria per question is 15 criteria. For a class of 350:

| Stage | Calls |
|---|---|
| Ingestion / transcription (1 VLM call per rasterized page, ~4 pages per submission) | ~1,400 |
| Multiple-choice items, if any | **0** — deterministic lookup, no extraction and no scoring calls (§7.8) |
| Extraction (1 pass per submission per **judged** criterion) | 5,250 |
| Scoring, uniform 3-judge panel over judged criteria | 15,750 |
| Scoring, adaptive panel at 30% escalation (Section 7.1) | 8,400 |
| Synthesis L1 (per question) + L2 (per test) | 2,100 |
| **Total, uniform panel** | **~23,100** |
| **Total, adaptive panel** | **~15,750** |

At roughly 300 output tokens per call, the uniform-panel run is about 6.9M output tokens. Wall clock depends almost entirely on the serving stack:

| Serving mode | Approx. throughput | Wall clock, n=350 uniform |
|---|---|---|
| Single-stream (one request at a time) | ~50 tok/s | **~38 hours** |
| Continuous batching, ~32 concurrent | ~1,150 tok/s aggregate | **~1.7 hours** |

**This is the decisive architectural finding for the deployment context.** Single-stream serving does not merely make the system slow at 350 students, it makes it unusable: a 38-hour run cannot fit an overnight window and will not be attempted twice. Continuous batching brings the same work inside two hours. The order-of-magnitude gap is not a tuning detail; it is the difference between a working product and a demo.

Two consequences follow:

1. **The serving stack is a first-class architectural decision, not an ergonomics preference.** Independent mid-2026 benchmarks on an M4 Pro 64GB have reported comparable *single-user* throughput for Ollama and vllm-mlx while vllm-mlx delivered roughly an order of magnitude higher *aggregate* throughput at around 32 concurrent requests, at slightly worse single-request latency. Since this harness is a batch workload where per-request latency is irrelevant and aggregate throughput is everything, that trade is entirely favorable. Verify the figures on your own hardware and model mix, but do not default to Ollama on ease of setup alone.

2. **The execution plan in this section is what makes continuous batching possible.** Thirty to 350 concurrent requests differing only in their final few hundred tokens, all sharing a cached prefix, is the ideal workload profile for a continuous-batching server. Per-student looping would produce serial, cache-cold requests and would forfeit the entire order-of-magnitude gain. Criterion-batching, prefix ordering, and high concurrency are one design, not three.

Combining adaptive panel depth with continuous batching brings a 350-student assessment to roughly an hour, which comfortably fits an overnight window with room for the ingestion and OCR pass.

**This is not R10 satisfied. It is R10 shown to be architecturally achievable.** The estimate rests simultaneously on model size, quantization, prompt length, output length, achieved concurrency, KV cache headroom, model load time, cache implementation behavior, thermal sustain, and disk throughput. Any one of those can move the result by a factor.

**The ingestion row is small by call count and is not small by wall clock**, which is why versions before 2.6 were wrong to leave it out entirely rather than merely imprecise. Those ~1,400 page calls each carry a rasterized page image in the input — on the order of a thousand or more tokens, set by the profile's DPI — and vision encoding is slower per token than text. Section 7.7 works this through; the planning consequence is to treat transcription as plausibly the same order of magnitude as the scoring pass rather than a rounding error on it, and to measure it in the §8.5 acceptance test, which already requires the real OCR stage rather than a stub. Arithmetic of this kind is a hypothesis, and Section 8.5 specifies the test that turns it into a fact.

**On the `cloud-hosted` and `dev-ci` profiles the call counts are identical and the binding constraint moves.** The 23,100 calls do not change — they are a property of the pipeline, not the backend — but wall clock stops being a function of one machine's memory and thermals and becomes a function of the provider's rate limits and how much you are willing to spend. That usually makes the overnight window easy and introduces two constraints the local profile does not have: a per-run cost that is real money (R5), and rate limiting that produces 429s rather than out-of-memory errors. Section 8.7 specifies both. It also means CI must never run the full 23,000-call batch on every commit; the test tiers there are sized deliberately.

#### Serving-stack implication

This execution plan turns the harness into a **high-concurrency, shared-prefix** workload, which is the profile the throughput table above depends on. One caveat worth planning for: sustaining high concurrency costs memory for the KV cache of every in-flight request, and that memory competes with model weights on a unified-memory machine. Concurrency is therefore a tunable to be measured against your model sizes, not maximized blindly. Find the concurrency level where aggregate throughput plateaus on your hardware, and size the panel to leave headroom for it.

### 8.5 The hardware acceptance test 

Throughput, memory headroom, and OCR viability are empirical properties of a specific hardware and model combination. They are not derivable from the architecture, and shipping on the arithmetic alone risks discovering at a pilot site that the overnight batch takes nine hours.

**This gate belongs to the `edge-local` profile and cannot be satisfied by a cloud run (R30).** Section 0.7 notes the inversion this version introduces: because development and CI run on OpenRouter, the local path becomes the least-exercised path in the system while remaining the one deployed to schools with no IT support. A green CI pipeline is therefore *no evidence at all* about whether an overnight batch completes on a 32GB Mac. The acceptance test is what closes that gap, and it must be run on the actual target hardware with the actual local serving stack. A `cloud-hosted` deployment has its own, different gate — throughput against provider rate limits, cost per assessment against the configured ceiling, and behavior under a provider outage mid-run — specified in Section 8.7.

**Make this a release gate, not instrumentation.** Before committing to hardware for a deployment, run the full pipeline end to end:

- 350 representative submissions, in the actual medium (handwritten and scanned if that is the deployment reality, not clean typed text)
- a **mixed-format paper** if the deployment will see one: open questions plus multiple-choice items, so mark-reading is exercised alongside transcription (§7.8). Record the unresolved-mark rate separately from the OCR failure rate — they have different remedies
- the real OCR stage, not a stub
- the actual target models at the actual quantization
- the actual serving stack at the actual concurrency
- persistence writing to the actual storage medium
- one deliberate mid-run kill, to exercise resume

Measure and record against the hardware profile:

| Metric | Gate |
|---|---|
| Wall clock, ingestion through synthesis | Fits the overnight window with margin |
| Peak memory, weights plus KV cache | Stays under the profile ceiling at target concurrency |
| Achieved aggregate throughput | Within range of the continuous-batching projection |
| Prefix cache hit rate | High; a low rate means the Section 8.4 prompt ordering has regressed |
| Model swap time and count | Minutes total, not per criterion |
| Thermal sustain over the full run | No sustained throttling |
| OCR failure and manual-triage rate | Triage time fits the budget (R9), not just the failure rate |
| Failure and retry rate | Units fail, run completes |
| Resume time and correctness after kill | No duplicated or lost work |
| Disk growth | Within the device's free space with margin |

The OCR line is the one most likely to fail and the one least often tested, because it is easy to benchmark inference on clean text and discover handwriting later. Test the medium you will actually receive.

`run_metrics` (Section 9.7) already captures most of these, which means the acceptance test is largely a matter of reading instrumentation the harness produces anyway. The change is in status: these figures gate a deployment rather than merely describing one.

### 8.6 Tooling

| Tool | What it's for | Why it fits |
|---|---|---|
| **Inspect AI** (UK AI Security Institute) | Reference open-source framework for building and running LLM evaluations: datasets, solvers, scorers as first-class objects | Model-agnostic; works against local Ollama-served endpoints as easily as hosted APIs; closest thing to an industry-standard harness |
| **AutoRubric** (Rao & Callison-Burch, UPenn, 2026) | Open-source Python library purpose-built for rubric-based LLM evaluation | Implements ensemble judging, few-shot calibration, position-bias mitigation, and κ-based reliability reporting out of the box; routes through LiteLLM, so the same configuration reaches a local Ollama endpoint or an OpenRouter model — which is exactly the R27 seam |
| **DeepEval** | Pytest-style LLM evaluation framework | Wire the pipeline into a repeatable CI-style regression suite: "does this rubric revision still score last month's accumulated labels the same way" (this is Section 6.5's non-inferiority check, automated) |
| **MLflow evaluation tracking** | Experiment tracking and dashboarding | Useful once multiple schools run the harness and you want validation metrics tracked over time, which is where Section 6.8's longitudinal store lives |
| **OpenRouter** | Single OpenAI-compatible endpoint fronting many open-weight model families | The `cloud-hosted` and `dev-ci` inference provider (R28, R29). One API key and one base URL reach Llama, Qwen, and GPT-OSS family models, so panel diversity does not mean managing three vendor accounts |
| **LiteLLM** | Provider-shim library with a uniform OpenAI-compatible surface | The practical way to implement R27's `InferenceProvider` without writing two clients: the same call targets a local Ollama/vLLM endpoint or an OpenRouter model by changing configuration. AutoRubric already routes through it |

**Concrete build recommendation:** use **AutoRubric** as the scoring and aggregation layer, since it already implements most of Section 7.2's bias mitigations, pointed at the R27 provider abstraction rather than at a specific server — **LiteLLM** underneath, resolving to a local **Ollama** or **vLLM-MLX** endpoint under `edge-local` and to **OpenRouter** under `cloud-hosted` and `dev-ci`. Use **Inspect AI** or **DeepEval** as the outer harness that runs the MVVP against accumulated override labels and enforces the Section 6.5 non-inferiority gate as a hard CI check before any rubric revision ships. Because that CI harness runs in a container with no local models, it necessarily runs against OpenRouter, which is exactly the configuration Section 8.7 specifies — and one more reason the provider abstraction has to exist before anything else is built on top of it.

### 8.7 The OpenRouter path: development, CI, and cloud deployment 

This section specifies the `cloud-hosted` and `dev-ci` profiles of Section 0.7. It is not an appendix describing a fallback. **It describes the configuration in which every automated test of this system runs and in which a substantial share of production deployments will run (R28, R29).** The pipeline is identical to Sections 7 and 8.4 — same isolation rules, same criterion batching, same prompt field ordering, same persistence. What follows is only what differs.

#### Why OpenRouter specifically

The panel requires 2 to 3 models from *different families* (Section 5.1), and family diversity is the mechanism that decorrelates bias. Sourcing that diversity directly means three vendor relationships, three API surfaces, and three billing arrangements — for a system whose deployments include a two-person program running a pilot. OpenRouter fronts the open-weight families the panel needs behind one OpenAI-compatible endpoint and one key, which makes panel diversity an ordinary configuration choice instead of a procurement exercise. It also keeps the harness on **open-weight models** rather than sliding toward a frontier API, which matters because the whole architecture (Section 0.3) is built on the premise that structure substitutes for model scale — a premise that stops being tested the moment the panel quietly becomes three frontier models.

#### The five things that actually differ, and what each requires

**1. Model identity is not under your control, and this is the most dangerous difference.** A local deployment pins a GGUF file with a weights hash; it grades identically next month. A hosted model slug is a *routing target*: the provider behind it, the served build, the quantization it runs, and the sampling defaults can all change without the slug changing. Section 2.2's finding that judge rankings do not transfer, and Section 6.7's version-pinning requirement, both apply directly.

Requirements this forces:
- Record the **resolved** provider and build metadata the response reports, per call, in `run_metrics` — not the slug you requested. A slug is a request; the metadata is what actually graded the work.
- Pin the provider explicitly where OpenRouter allows it, rather than accepting whichever is cheapest at dispatch time. Price-based routing across providers within one run reintroduces the mixed-grader problem of Section 0.7 at a finer grain, and does it invisibly.
- Treat a detected build change as a **panel change**: re-run the MVVP (Section 2.5), and do not extend the existing validation record across it. R30 makes validation records backend-scoped precisely so this is expressible rather than glossed over.
- Add build-substitution detection to the drift check of Section 9.4: if scores on a frozen fixture set shift while nothing in the package changed, the model changed underneath you.

**2. Determinism is weaker, and the statistics depend on knowing how much weaker.** Section 2.5 step 3 requires measuring self-agreement by replicating judgments. Local serving at temperature 0 with a fixed seed is close to reproducible; hosted inference frequently is not, because batching, hardware, and provider-side settings all perturb it. Declare `supports_seed` and `deterministic_at_temperature_zero` in `capabilities()`, and **measure** actual self-agreement on each backend rather than assuming it. This is not a defect to be worked around — a real classroom deployment on the cloud profile has whatever run-to-run variance the provider has, and the honest response is to measure it and report it (R8) rather than to present a local determinism figure as if it described the hosted system.

**3. Prompt caching works differently, and Section 8.4's ordering still applies.** The prefix tree of Section 8.4 assumes a server holding a KV cache you control. A hosted provider may offer prompt caching, may require opting in, may price it differently, and may not offer it for a given model at all. **Keep the field ordering and criterion batching regardless.** The reasons are unchanged and only partly about speed: batching by criterion is what guarantees every student in the class is judged against byte-identical context (Section 8.4's fairness argument), and that property is backend-independent. Where caching is available, the ordering earns its cost reduction too; where it is not, the ordering still earns the fairness property, which was always the more important of the two.

**4. The failure modes are different, and so is the retry policy.** Local runs fail on memory, thermals, and disk. Hosted runs fail on rate limits, provider outages, and truncated or malformed responses under load.
- **Rate limiting is the normal case, not an error.** Respect `Retry-After`, back off exponentially with jitter, and cap in-flight requests at a configured concurrency rather than dispatching all 350 submissions for a criterion at once. Section 9.13's backpressure rule extends here: a run that outruns its rate limit converts throughput into retries.
- **A provider outage pauses the run; it does not switch backends.** The work ledger (Section 9.10) already makes this safe — completed cells stay completed, the run resumes against the same configured backend. This is R1's second clause and it is the whole reason that clause exists.
- **Transient failures are retried; the score is not resampled.** Retrying a call that returned a 429 is a transport retry. Retrying a call because you did not like the verdict is sampling until you get the answer you want, and it corrupts every statistic in the system. Enforce this in code: retries are permitted on transport and parse failures only, and the retry count goes in `run_metrics` where a rising rate is visible.
- **Quarantine, do not silently drop.** A cell that exhausts its retries goes to the Section 9.11 failure taxonomy as a quarantined unit, surfaced to the operator. A run that completes with 40 cells silently missing produces a class rollup that is wrong in a way nobody can see.

**5. Cost is real and must be bounded before dispatch, not discovered after (R5).** At ~23,100 calls per assessment, a per-token price that looks negligible per call is not negligible per run, and the failure mode is a program discovering it after grading three classes.
- **Estimate before dispatch.** Call count is known from (questions × criteria × submissions × panel depth) plus extraction and synthesis; token counts per call are known from the prefix budget of Section 8.4. Show the operator an estimate and a ceiling before the run starts.
- **Enforce the ceiling during the run**, with the same pause-and-surface behavior as a provider outage rather than a silent stop. A run halted at 70% with a clear reason is recoverable; a run that stopped for an unstated reason is not.
- **Record actual spend per run in `run_metrics`**, so cost per assessment becomes a measured property of a package rather than a projection.
- **The adaptive panel (Section 7.1) is worth more here than locally.** It cuts calls from ~23,100 to ~15,750, which locally buys wall clock and on the cloud profile buys roughly a third of the bill. The same optimization, a different currency.

#### The backend conformance suite (R30)

This is the mechanism that keeps two supported backends from quietly becoming two different products, and it is what makes it honest to test on OpenRouter and deploy on a Mac.

Maintain a small frozen fixture set — on the order of 30 to 50 submissions spanning the score range, including the mid-range partial-credit cases Section 1 identifies as the hard ones, with known reference scores. Run the identical fixture set through the full pipeline on each backend and compare:

| Compared | Why it matters | Response to divergence |
|---|---|---|
| Per-criterion score distributions | The headline question: does this backend grade the same work the same way | Material shift means the backends are different graders; validation records must not be shared across them |
| Chance-corrected agreement with the fixture labels | Whether one backend is simply worse at this task | Investigate before shipping the worse one anywhere |
| Confidence and escalation rate | A backend that escalates twice as often silently doubles the teacher's review burden (R12) | Re-budget the review queue per backend, or fix it |
| Evidence-integrity failure rate (Section 7.4) | Extraction quality can differ by build even when scores look similar | Treat as a Section 7.4 gate failure, not a metrics note |
| Self-agreement over repeated runs | Quantifies the determinism gap of item 2 above | Report per backend; never quote the local figure for a hosted deployment |

Run it in CI on every panel or model change, and record the result in the package's validation record. **Divergence is an expected finding, not a bug** — a 4-bit local quantization and a hosted build are genuinely different graders, and Section 2.2 predicts exactly this. The purpose of the suite is not to prove they are the same. It is to make sure nobody ever assumes they are.

#### The `dev-ci` profile, concretely

The system is developed and tested in a Linux container on a Windows host, with no Apple Silicon, no MLX, and no local model server (R28). Two consequences worth stating so they are designed for rather than discovered:

- **Tier the tests by cost, because a 23,000-call run per commit is neither affordable nor fast.** Most of the suite — prompt construction, field ordering, the isolation assertions of Section 7.2, the batch-prompting prohibition of Section 8.4, ledger and resume behavior, schema migrations, cost estimation, retry and quarantine logic — needs no live model at all and should run against a **recorded-response fixture provider**, a third implementation of the same `InferenceProvider` interface. Live OpenRouter calls belong in a smaller nightly tier running the conformance suite and a scaled-down end-to-end run. This is not a compromise: the deterministic scaffolding is where wrong-output bugs actually live, and testing it against frozen fixtures makes the suite fast, offline, and reproducible.
- **No real student work in CI (R31).** Fixtures are synthetic or consented. The provider abstraction makes this easy to get wrong in one specific way — a developer pointing a local debugging run at OpenRouter with a real cohort loaded — so gate it: refuse to dispatch to a remote provider when the loaded cohort is not flagged as synthetic or consented, and make the override explicit and logged rather than a configuration flag someone can set once and forget.

---

## 9. The memory and persistence layer 

At 23,000 model calls and multi-hour runs, persistence stops being an implementation detail and becomes the substrate the harness sits on. This section specifies it: what is stored, in what shape, on what infrastructure, with what recovery semantics, and in what format it moves between actors.

### 9.1 The rule that governs the entire design

Before any schema, the constraint that shapes all of it:

> **The orchestrator reads memory. The judges never do.**

Independent evaluation is the whole point of Section 7.2. Each criterion runs on its own judgment with fresh context precisely so that no evaluator inherits another's reasoning. A persistence layer is required anyway, because the process is long and stateful, but it must never become the channel that undoes the isolation.

The distinction is between a **persistence layer** and an **agent memory**. An agent memory in the conventional sense is a store a model queries at inference time, retrieving what it judges relevant. If a scoring judge could query this store it could retrieve another judge's verdict on the same criterion, its own verdict on a different criterion, or how it scored the previous student. Each of those is a contamination path Rule 1 exists to close, and retrieval-based memory reopens all of them at once while looking like a feature.

The flow is therefore strictly one-way:

```
  store ──> orchestrator ──> assembles context ──> judge ──> verdict ──> store
     ▲                                                                     │
     └─────────────────────────────────────────────────────────────────────┘
              the judge has no read path back into the store
```

The orchestrator decides what a judgment may see, assembles exactly that, and passes it as a complete self-contained prompt. The judge is a pure function of the context it was handed. This is what makes isolation *checkable*: you can assert properties of an assembled context before dispatch, which you cannot do about what a model chose to retrieve.

Corollaries to write into the design doc:

- **No tool-calling access to the store from within an extraction or scoring call.** If the model can call a lookup function, isolation stops being enforceable.
- **No semantic retrieval anywhere in the scoring path.** Everything the harness needs is keyed lookup on identifiers it already holds. (A semantic index over the durable analytics tier is fine, because nothing in the scoring path reads it.)
- **Context assembly is a testable unit.** Assert that an assembled scoring context contains no verdict field, no other submission's identifier, and no criterion other than the target. That assertion is the machine-checkable form of Rule 1, and Section 9.9's request schema is what makes it easy to write.

### 9.2 What persistence buys

Three distinct things, with different lifetimes. Conflating them produces a store that does none well.

**1. Long-run resilience.** A 350-student run is hours long and produces tens of thousands of intermediate artifacts. Extraction writes evidence that scoring reads across batch boundaries; dependencies resolve between criteria processed at different times; escalations create work mid-run; the review queue must survive the teacher closing the laptop. Without durable state the run is one uninterruptible transaction, which at this duration is not a viable design.

**2. Reuse of tuned assessments across cohorts.** A teacher rarely gives a test once. The same or near-identical assessment runs across sections, terms, schools, and years. Rubric tuning (Section 6) is the most expensive teacher-time investment in the system, and it is nonsense to repeat it per cohort. Once tuned, the assessment and its calibrated rubric should persist together as a reusable package. Section 9.4.

**3. Accumulated validation and metrics.** Section 6.8 establishes that real validation comes from accumulated teacher override labels rather than from small calibration sets. That accumulation only exists if it is persisted across runs, cohorts, and months, along with the statistics computed from it.

The second and third compound in a way worth stating explicitly, because it is the strongest argument for this architecture: **a persisted assessment package appreciates with every use.** First cohort, the teacher tunes and the package records the outcome. Second cohort, zero tuning, and the package gains a few hundred more labels. By the tenth administration the package carries a genuinely well-validated instrument with per-criterion agreement statistics across thousands of judgments and multiple student populations. The system gets more trustworthy the more it is used, without additional teacher effort. That is the opposite of the usual dynamic, where a tool degrades as it drifts from its original validation.

### 9.3 Four tiers, by lifetime

| Tier | Contains | Lifetime | Student PII | Portable |
|---|---|---|---|---|
| **P. Package catalog** | Assessment, tuned rubric versions, dependency graph, exemplars, validated panel config, cumulative validation record | Permanent | No, by construction | **Yes, single file** |
| **C. Cohort corpus** | This administration's submissions, transcripts, roster reference | Per administration | Yes, heavily | No |
| **R. Run state** | Work ledger, evidence, verdicts, scores, narratives, review session | Per run | Yes | No |
| **D. Durable record** | Audit records, labels, metrics | Permanent | Minimal, pseudonymized | Exportable |

The tier boundaries are drawn on **PII and portability**, not on convenience. Tier P is what moves between schools, so it must contain no student work; Tier C is the largest PII surface and is purged after acceptance; Tier D keeps only what is needed to defend a grade and to validate the system.

### 9.4 The Assessment Package

The package is the unit of reuse: a self-contained, versioned, portable bundle representing *a test and everything learned about how to grade it*.

**Contents:**

| Component | Why it travels with the package |
|---|---|
| Assessment definition: questions, instructions, reference solution | The test itself |
| Rubric version, decomposed into atomic criteria | The tuned artifact, the expensive part |
| Criterion dependency graph | Structural, not cohort-specific (§7.2 Rule 2) |
| Elicitation history: the questions asked and the teacher's answers | Provenance for why the rubric reads as it does (§6.4) |
| Anchor exemplars, de-identified | What calibrates the judges |
| Validated panel config and prompt template version | Per §2.2 rankings do not transfer; the package records what was actually validated |
| Cumulative validation record: per-criterion agreement, label counts, cohorts | Lets the next teacher see how trustworthy this package actually is |
| Expected score distribution per criterion | The baseline for the drift check below |

**Exemplars are the PII hazard, and the naive fix damages the thing exemplars are for.** Anchor examples come from real student responses, and a package carrying them verbatim exports one cohort's work to every school that later loads it. Version 2.3 of this report recommended defaulting to synthetic exemplars. That recommendation was too simple: synthetic examples written to illustrate a band tend to be cleaner, more canonical, and more articulate than real student work, and they frequently miss the *actual* local misconceptions, which is precisely what an anchor exists to calibrate against. Trading construct fidelity for privacy is a real cost, not a free win.

The revised policy separates two questions that version 2.3 conflated: what the exemplars are, and where the package travels.

| Provenance | Use | Export |
|---|---|---|
| `real_verbatim` | Full fidelity; the default **within the originating institution** | Blocked |
| `paraphrased` | Locally rewritten to preserve the reasoning error and drop identifying detail, teacher-approved | Permitted |
| `synthetic` | Teacher-authored illustration of a band | Permitted |

**Within an institution, use real exemplars.** The privacy constraint bites on export, not on local use, and there is no reason to degrade calibration for a package that never leaves the school.

**For export, paraphrase rather than synthesize.** Paraphrasing preserves the structure of the misconception, which is the thing being anchored, while removing the student's voice and identifying detail. It runs locally, needs teacher approval, and produces better anchors than invention does. Synthetic remains the fallback where a response cannot be paraphrased without either losing the point or remaining recognizable.

Enforce it structurally: `contains_real_student_text` in the package metadata, checked at export, with the exemplar `provenance` CHECK constraint backing it. And record in the validation record which provenance the package was validated with, since a package validated with real anchors and exported with synthetic ones is not the instrument its statistics describe.

**Reuse is not free, and the guardrail matters.** The rubric was tuned against one cohort's ambiguities. A different cohort may have different language backgrounds, different prior curriculum coverage, a different teacher's emphasis. Section 2.2 established that judge rankings do not transfer across task types; the same caution applies one level up, to transferring a calibrated instrument across populations.

So package reuse should carry a **cheap drift check** rather than assuming transfer:

1. Score a small random sample of the new cohort, 20 to 30 submissions, which at n=350 is a rounding error in compute.
2. Compare the observed per-criterion score distribution to the distribution recorded
   — for **judged** criteria. A shift in a multiple-choice item's correct-rate is a fact
   about this cohort, not evidence that a rubric failed to transfer, and reading it as
   drift would flag the one part of the instrument that cannot drift (§7.8) in the package.
3. Flag criteria where the distributions differ materially. A criterion where the previous cohort averaged 3.8 and this one averages 1.9 is either a genuinely different population or a rubric that does not transfer, and the teacher should be told which criteria to look at before the full run.
4. Proceed on approval. The check is advisory, not a gate; per R11 the system must still run when the teacher skips it.

**Population scope is a hard schema constraint, not a warning (R23).** A package must never carry a global "validated" flag or a single headline κ. Validation records are keyed by population scope (Section 9.5), so the same package can honestly report strong agreement for one curriculum and language of instruction and no evidence at all for another. Without this, a package accumulating thousands of labels across mixed populations produces an impressive aggregate that conceals population-specific failure, and the aggregate is exactly what a busy teacher will read. When a package is loaded into a population it has no validation record for, the correct display is "no validation data for this population," not the number from somewhere else.

This is deliberately much lighter than the Section 6 tuning process. It is a smoke test, not a recalibration, and its output is one screen: "criteria 2 and 7 look different in this cohort, everything else matches."

**Portability is a file, not an API.** In the deployment context of Section 0.2 there is no reliable network, so package sharing between schools happens by USB stick, not by sync service. The package must therefore be a **single self-contained file** that can be copied, emailed when connectivity permits, and imported offline: a SQLite file or a signed archive containing the package database plus any blobs. Design for sneakernet first; any sync service is a later convenience layered on a format that already works without it. A `cloud-hosted` instance uses the identical format — it simply has a network to move it over — which is what lets a package built at a hosted district instance be handed to a disconnected school on a USB stick and used immediately. Its validation record travels with it, backend-scoped per R30, so the receiving school can see that the package's statistics were accumulated on a different backend and treat them accordingly rather than inheriting a number that does not describe its own configuration.

**Versioning and lineage.** Packages are immutable once published; a revision creates a new version with a parent pointer. This preserves the Section 6.7 audit requirement: a grade issued in 2026 must be explicable against the exact package version in force then, even after the package has been revised three times since.

### 9.5 Schemas: Tier P, the package catalog

SQLite DDL. Types are indicative; the shapes are the specification.

```sql
CREATE TABLE package (
  package_id        TEXT PRIMARY KEY,      -- stable across versions
  title             TEXT NOT NULL,
  subject           TEXT,
  grade_level       TEXT,
  language          TEXT,
  origin_institution TEXT,
  contains_real_student_text INTEGER NOT NULL DEFAULT 0,  -- export gate (§9.4)
  created_at        TEXT NOT NULL
);

CREATE TABLE package_version (
  package_version_id TEXT PRIMARY KEY,     -- content hash of the whole bundle
  package_id         TEXT NOT NULL REFERENCES package,
  parent_version_id  TEXT REFERENCES package_version,
  version_label      TEXT NOT NULL,        -- 'v3'
  approved_by        TEXT NOT NULL,        -- teacher identifier
  approved_at        TEXT NOT NULL,
  gate_results       TEXT,                 -- JSON: non-inferiority + back-translation (§6.5, §6.6)
  validated_panel    TEXT NOT NULL,        -- JSON: models, versions, quantization
  prompt_template_v  TEXT NOT NULL,
  schema_version     INTEGER NOT NULL,
  published          INTEGER NOT NULL DEFAULT 0,   -- immutable once 1
  UNIQUE (package_id, version_label)
);

-- How criterion scores become a final grade (§7.9, R57). Declared by the teacher once, at
-- setup, applied automatically to every submission thereafter. Declarative rather than a
-- script so it can be shown back in plain language, locked under §6.2, version-pinned, and
-- reproduced exactly years later when a grade is disputed.
CREATE TABLE grade_policy (
  package_version_id TEXT PRIMARY KEY REFERENCES package_version,
  per_question       TEXT NOT NULL,        -- JSON: per-question rule + optional gate
  test_total         TEXT NOT NULL,        -- JSON: sum_questions | best_k_of_n | drop_lowest_n
  scale_to           REAL,                 -- null = keep raw points
  rounding           TEXT NOT NULL,        -- e.g. half_up_1dp
  plain_language     TEXT NOT NULL,        -- the teacher-approved wording of the above. What
                                           -- was actually approved is this, not the JSON
  approved_by        TEXT NOT NULL,
  approved_at        TEXT NOT NULL
);

-- Grade boundaries. §10 already ranked review by proximity to a boundary and ReviewItem
-- already carried grade_boundary_delta; before v3.1 nothing defined one, so that ranking
-- was not computable (R59).
CREATE TABLE grade_boundary (
  package_version_id TEXT NOT NULL REFERENCES package_version,
  min_score          REAL NOT NULL,        -- on the scaled total
  grade              TEXT NOT NULL,        -- 'A', 'Pass', '4' — whatever the institution uses
  PRIMARY KEY (package_version_id, min_score)
);

CREATE TABLE question (
  question_id        TEXT PRIMARY KEY,
  package_version_id TEXT NOT NULL REFERENCES package_version,
  ordinal            INTEGER NOT NULL,
  prompt_text        TEXT NOT NULL,
  question_type      TEXT NOT NULL         -- open | mcq | mixed (§7.8, R52). "mixed" is
                     CHECK (question_type IN ('open','mcq','mixed')),  -- "circle the answer AND
                                           -- explain your choice", which is common. Locked
                                           -- under §6.2: converting between types is a
                                           -- redefinition of what is assessed
  reference_solution TEXT,                 -- the "definition of good" for the judged part;
                                           -- null only for pure mcq
  max_points         REAL NOT NULL,
  CHECK (question_type = 'mcq' OR reference_solution IS NOT NULL)
);

-- Option set for a multiple-choice question. Needed by ingestion, so it knows what marks to
-- look for, and by the class rollup, where distractor analysis at n=350 is a sharp signal.
CREATE TABLE mcq_option (
  question_id     TEXT NOT NULL REFERENCES question,
  option_id       TEXT NOT NULL,           -- 'A', 'B', ...
  ordinal         INTEGER NOT NULL,
  text            TEXT NOT NULL,
  PRIMARY KEY (question_id, option_id)
);

CREATE TABLE criterion (
  criterion_id       TEXT PRIMARY KEY,
  package_version_id TEXT NOT NULL REFERENCES package_version,
  question_id        TEXT NOT NULL REFERENCES question,
  ordinal            INTEGER NOT NULL,
  text               TEXT NOT NULL,
  max_points         REAL NOT NULL,        -- ceiling for aggregation only; never shown to a judge (R39)
  -- How this criterion is evaluated (§7.8, R52). This is a property of the CRITERION, not
  -- of the question: a "circle and explain" question carries one deterministic criterion for
  -- the selection and one or more judged criteria for the explanation.
  evaluation_mode    TEXT NOT NULL
                     CHECK (evaluation_mode IN ('judged','deterministic')),
  answer_key         TEXT,                 -- JSON [option_id,...]; required when deterministic
  multi_select       INTEGER NOT NULL DEFAULT 0,
  partial_credit     TEXT,                 -- all_or_nothing | per_option; declared, not inferred
  scoring_model      TEXT NOT NULL         -- §5.3 decomposability determination (R49).
                     CHECK (scoring_model IN ('atomic','atomic_with_gate','holistic')),
                                           -- Locked under §6.2: reclassifying is a
                                           -- redefinition, not a clarification
  decomposition_basis TEXT,                -- which of the five §5.3 questions decided it,
                                           -- and that the teacher confirmed. Null only for
                                           -- criteria the teacher authored already atomic
  is_gate            INTEGER NOT NULL DEFAULT 0,  -- sub-criterion whose failure forces the
                                           -- parent to its lowest band (atomic_with_gate)
  band_count         INTEGER NOT NULL      -- even, so there is no default middle (R40)
                     CHECK (band_count % 2 = 0 AND band_count BETWEEN 2 AND 6),
  evidence_type      TEXT,                 -- RULERS annotation (§1)
  construct_tag      TEXT,                 -- what this measures; changing it is a redefinition (§6.2)
  CHECK (evaluation_mode = 'judged' OR answer_key IS NOT NULL)
);

-- The scoring scale (§5.10). A judge chooses one of these labels; the orchestrator maps it
-- to points afterwards. Both the label set and the mapping are inside the §6.2 schema lock
-- and pass the §6.5 non-inferiority gate when changed (R43), because editing this table
-- moves every grade in the system without re-running a single judgment.
CREATE TABLE criterion_band (
  criterion_id    TEXT NOT NULL REFERENCES criterion,
  band            TEXT NOT NULL,           -- stable label, e.g. 'derives_and_justifies'
  ordinal         INTEGER NOT NULL,        -- 0 = lowest; the ordering aggregation uses
  descriptor      TEXT NOT NULL,           -- what a response in this band DOES (R40).
                                           -- Behavioural and checkable against cited spans,
                                           -- never a magnitude phrase like "good" or "3 of 5"
  points          REAL NOT NULL,           -- orchestrator-side only; never sent to a judge
  PRIMARY KEY (criterion_id, band),
  UNIQUE (criterion_id, ordinal)
);

CREATE TABLE criterion_dependency (        -- §7.2 Rule 2
  child_criterion_id  TEXT NOT NULL REFERENCES criterion,
  parent_criterion_id TEXT NOT NULL REFERENCES criterion,
  artifact_kind       TEXT NOT NULL CHECK (artifact_kind = 'evidence'),
  rationale           TEXT,                -- shown to the teacher in plain language (§10)
  PRIMARY KEY (child_criterion_id, parent_criterion_id)
);

CREATE TABLE exemplar (
  exemplar_id        TEXT PRIMARY KEY,
  criterion_id       TEXT NOT NULL REFERENCES criterion,
  band               TEXT NOT NULL,        -- must name a band that exists, not free text (§5.10)
  text               TEXT NOT NULL,
  provenance         TEXT NOT NULL CHECK (provenance IN
                       ('synthetic','paraphrased','real_consented')),
  ordinal            INTEGER NOT NULL,     -- fixed within a batch, randomized across (§8.4)
  FOREIGN KEY (criterion_id, band) REFERENCES criterion_band(criterion_id, band)
);

CREATE TABLE elicitation_history (         -- provenance for §6.4
  elicitation_id     TEXT PRIMARY KEY,
  package_version_id TEXT NOT NULL REFERENCES package_version,
  criterion_id       TEXT REFERENCES criterion,
  question_asked     TEXT NOT NULL,
  options_offered    TEXT,                 -- JSON
  teacher_answer     TEXT NOT NULL,
  resulting_edit     TEXT NOT NULL,
  answered_at        TEXT NOT NULL
);

-- The record that makes a package worth reusing.
-- R23: validation is ALWAYS scoped to a population. There is no global
-- "validated" flag, by construction: population_scope_id is in the primary key.
CREATE TABLE population_scope (
  population_scope_id TEXT PRIMARY KEY,
  curriculum          TEXT,               -- 'NERDC Physics SS2'
  institution_type    TEXT,
  region              TEXT,
  language_of_instruction TEXT,
  student_l1_profile  TEXT,
  grade_level         TEXT,
  assignment_type     TEXT NOT NULL
);

CREATE TABLE package_validation (
  package_version_id  TEXT NOT NULL REFERENCES package_version,
  criterion_id        TEXT NOT NULL REFERENCES criterion,
  population_scope_id TEXT NOT NULL REFERENCES population_scope,
  backend_profile     TEXT NOT NULL,        -- edge-local | cloud-hosted (R30)
  -- Judged criteria only. Deterministic (multiple-choice) items never appear here: their
  -- correctness is not evidence about the grader, and including them would inflate every
  -- figure in this table (§7.8, R53).
  scoring_model       TEXT NOT NULL,        -- atomic | atomic_with_gate | holistic (R51).
                                            -- In the key so a headline figure cannot merge
                                            -- holistic and atomic agreement (§5.3)
  panel_build_ref     TEXT NOT NULL,        -- hash over the resolved panel: per judge,
                                            -- provider + served build + quantization (§8.7)
  cohorts_used        INTEGER NOT NULL,
  operational_count   INTEGER NOT NULL,   -- accept/edit/override; NOT a validity claim
  blind_count         INTEGER NOT NULL,   -- the only labels agreement is computed from
  agreement_kappa     REAL,               -- from blind labels only (§3.1, R20)
  agreement_qwk       REAL,
  override_rate       REAL,               -- operational signal
  surface_proxy_flags TEXT,               -- JSON: length/OCR/fluency correlations (§6.9)
  expected_mean       REAL,               -- baseline for the §9.4 drift check
  expected_sd         REAL,
  expected_histogram  TEXT,
  last_updated        TEXT NOT NULL,
  PRIMARY KEY (package_version_id, criterion_id, population_scope_id,
               backend_profile, panel_build_ref, scoring_model)
);
```

**`backend_profile` and `panel_build_ref` are in the primary key for the same reason `population_scope_id` is (R30).** A validation record describes an instrument *and* the grader that produced it. Statistics accumulated on OpenRouter-served builds do not automatically describe a school running 4-bit local quantizations of nominally the same models, and Section 2.2's non-transfer finding applies to this axis as directly as it does to task type. Putting the backend in the key makes "no validation data for this configuration" a representable state rather than a caveat someone has to remember — which is the same argument R23 makes for population scope, applied one axis over. When a package validated in a hosted district instance arrives at a disconnected school by USB stick, the school sees exactly that: a rich validation record for a configuration that is not the one it is about to run.

Note what `package_validation` enables, and note the shape the population key forces it into. When a teacher loads a package, the system can say: *this rubric has been used with 6 cohorts in your curriculum and language of instruction, with 180 blind-scored responses; agreement there is κ = 0.71, though criterion 4 sits at 0.44 and is worth watching. It has also been used with 4 cohorts elsewhere, for which no validation carries over.*

Three things make that honest where a single headline number would not be. Agreement comes from blind labels only, so it is not a record of teachers accepting the machine (R20). It is scoped to a population, so nothing transfers silently across curricula or languages (R23). And it names the weakest criterion, since a package advertising only its aggregate repeats the Section 2.1 error in portable form.

### 9.6 Schemas: Tier C and Tier R, cohort and run state

```sql
CREATE TABLE cohort (
  cohort_id          TEXT PRIMARY KEY,
  package_version_id TEXT NOT NULL,        -- which package was administered
  institution        TEXT,
  section_label      TEXT,                 -- 'Year 11 Physics, Section B'
  administered_at    TEXT NOT NULL,
  student_count      INTEGER NOT NULL
);

-- One row per transcribed logical document (§7.7). Assessments, reference solutions and
-- submissions all land here, because all four artifact kinds arrive as PDFs and all four
-- need the same immutability and provenance guarantees.
CREATE TABLE document (
  document_id     TEXT PRIMARY KEY,
  kind            TEXT NOT NULL            -- assessment|reference|rubric|submission
                  CHECK (kind IN ('assessment','reference','rubric','submission')),
  version         INTEGER NOT NULL DEFAULT 1,
  parent_doc_id   TEXT REFERENCES document, -- re-transcription supersedes, never edits (R32)
  content_hash    TEXT NOT NULL,           -- over the canonical markdown; in every audit record
  markdown        TEXT NOT NULL,           -- THE canonical source text; all spans offset into this
  source_blobs    TEXT NOT NULL,           -- JSON [{file_hash, page_index, seq}] -- assembly provenance (R33)
  page_count      INTEGER NOT NULL,
  -- Every page is VLM-transcribed (R38). Where a page also carried an embedded text layer,
  -- that layer is a differential check on the model, never a substitute for it (§7.7).
  pages_with_text_layer INTEGER NOT NULL,
  text_layer_divergence REAL,              -- null when no page had one; rising = model drift
  transcriber_ref TEXT NOT NULL,           -- resolved build id of the VLM (R37). Never null:
                                           -- there is no path to a document without one
  created_at      TEXT NOT NULL,
  UNIQUE (content_hash)
);

-- Region metadata sidecar. Absence of a row and an empty row mean different things (R36).
CREATE TABLE document_region (
  document_id     TEXT NOT NULL REFERENCES document,
  region_id       TEXT NOT NULL,
  question_id     TEXT,                    -- null for non-answer regions
  span_start      INTEGER NOT NULL,        -- byte offsets into document.markdown
  span_end        INTEGER NOT NULL,
  source_page_seq INTEGER NOT NULL,        -- which assembled page this came from
  ocr_conf        REAL,                    -- per-region; document-level is NOT enough (§7.5)
  region_kind     TEXT NOT NULL            -- R46; selection_mark is an MCQ answer (§7.8)
                  CHECK (region_kind IN ('transcribed_text','described_graphic',
                                         'selection_mark')),
                                           -- Downstream must be able to tell a student's own
                                           -- words from a model's account of a picture
  crop_ref        TEXT,                    -- content-addressed image crop; required when
                                           -- region_kind = described_graphic, because this is
                                           -- the only way a human can check the description
  retraction      TEXT                     -- null | struck_through | superseded_by:<region_id>
                  CHECK (retraction IS NULL OR retraction = 'struck_through'
                         OR retraction LIKE 'superseded_by:%'),   -- R47
  -- Selection extraction for multiple-choice regions (§7.8). The markdown carries a
  -- description; the deterministic evaluator needs a structured value, and needs to be able
  -- to say "I could not resolve this" without it collapsing into an answer (R55).
  selection       TEXT,                    -- JSON [option_id,...]; null unless resolved
  selection_state TEXT                     -- resolved | ambiguous | multiple_marks
                  CHECK (selection_state IS NULL OR selection_state IN
                         ('resolved','ambiguous','multiple_marks')),
  content_state   TEXT NOT NULL            -- present | blank | absent  (R36).
                                           -- A described_graphic is 'present': a question
                                           -- answered by a diagram is not an absent answer
                  CHECK (content_state IN ('present','blank','absent')),
  PRIMARY KEY (document_id, region_id)
);

CREATE TABLE submission (
  submission_id   TEXT PRIMARY KEY,
  cohort_id       TEXT NOT NULL REFERENCES cohort,
  student_ref     TEXT NOT NULL,           -- pseudonymous
  blob_hash       TEXT NOT NULL,           -- content-addressed original
  document_id     TEXT NOT NULL REFERENCES document,   -- the canonical transcript (R32)
  transcript_conf REAL,                    -- document level; NOT sufficient for routing
  layout_conf     REAL,
  has_equations   INTEGER,
  has_diagrams    INTEGER,
  page_complete   INTEGER,
  -- Validation ladder outcomes (§7.7). Recorded per gate rather than collapsed to one
  -- boolean, because "which gate failed" is what tells the operator what to actually do.
  v0_integrity    TEXT NOT NULL,           -- pass|fail
  v1_pages        TEXT NOT NULL,           -- pass|fail  + detail in ingest_detail
  v2_structure    TEXT NOT NULL,           -- pass|fail
  v3_identity     TEXT NOT NULL,           -- pass|uncertain|fail
  v4_match        TEXT NOT NULL            -- match|uncertain|mismatch  (R35)
                  CHECK (v4_match IN ('match','uncertain','mismatch')),
  v4_signals      TEXT,                    -- JSON: which signals fired, for the human deciding
  ingest_detail   TEXT,                    -- JSON: missing pages, duplicate pages, unmatched questions
  ingest_status   TEXT NOT NULL            -- ok | low_confidence_ocr | unreadable
                                           -- | incomplete | unmatched_assessment  (R13, R34, R35)
);

CREATE TABLE run (
  run_id             TEXT PRIMARY KEY,
  cohort_id          TEXT NOT NULL REFERENCES cohort,
  package_version_id TEXT NOT NULL,
  panel_config       TEXT NOT NULL,        -- JSON; may differ from validated_panel, and is recorded if so
  backend_profile    TEXT NOT NULL,        -- edge-local | cloud-hosted | dev-ci (§0.7)
  provider_config    TEXT NOT NULL,        -- JSON: provider, base endpoint, per-judge model_ref,
                                           -- pinned upstream provider, retention setting in force,
                                           -- concurrency cap, cost ceiling (§8.7)
  prompt_template_v  TEXT NOT NULL,
  escalation_policy  TEXT NOT NULL,        -- JSON (§7.1)
  drift_check        TEXT,                 -- JSON result of the §9.4 check, or null if skipped
  status             TEXT NOT NULL,        -- pending|running|paused|complete|failed
  started_at         TEXT,
  completed_at       TEXT
);

-- Resumability backbone. One row per unit of work.
CREATE TABLE work_unit (
  work_id       TEXT PRIMARY KEY,          -- deterministic hash, §9.10
  run_id        TEXT NOT NULL REFERENCES run,
  stage         TEXT NOT NULL,             -- extract|score|deterministic|synth_l1|synth_l2
                                           -- 'deterministic' carries a null judge_id: MCQ
                                           -- items are in the ledger so a run stays
                                           -- resumable and idempotent, but no judge runs
  submission_id TEXT NOT NULL,
  criterion_id  TEXT,
  question_id   TEXT,
  judge_id      TEXT,
  origin        TEXT NOT NULL,             -- base|escalation|random_arm  (§7.1)
  status        TEXT NOT NULL,             -- pending|leased|done|failed|quarantined
  attempts      INTEGER NOT NULL DEFAULT 0,
  lease_owner   TEXT,
  lease_expires TEXT,
  last_error    TEXT
);
CREATE INDEX idx_wu_sched ON work_unit(run_id, status, stage, criterion_id);

CREATE TABLE evidence (                    -- the §8.4 working store
  run_id        TEXT NOT NULL,
  submission_id TEXT NOT NULL,
  criterion_id  TEXT NOT NULL,
  spans         TEXT NOT NULL,             -- JSON [{start,end,text}]
  extractor     TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  PRIMARY KEY (run_id, submission_id, criterion_id)
);
-- No judge_id column, by design: dependencies are satisfied from extraction, not from judges (§7.2 Rule 2).

CREATE TABLE verdict (
  work_id       TEXT PRIMARY KEY REFERENCES work_unit,
  run_id        TEXT NOT NULL,
  submission_id TEXT NOT NULL,
  criterion_id  TEXT NOT NULL,
  judge_id      TEXT NOT NULL,
  band          TEXT NOT NULL,             -- the judge's verdict (§5.10). NOT points: a judge
                                           -- never emits a number and never sees one (R39)
  band_ordinal  INTEGER NOT NULL,          -- denormalized for ordinal aggregation (R41)
  self_conf     REAL,
  cited_spans   TEXT,                      -- null = uncited, downgrades confidence (§7.3)
  evidence_assessment TEXT,                -- inventory against the band descriptors, generated
                                           -- BEFORE the band (R42), not free commentary
  latency_ms    INTEGER,
  created_at    TEXT NOT NULL
);
-- No points column, deliberately. Points exist only after aggregation (R41); storing a
-- per-judge point value would invite averaging them, which rebuilds the continuous scale
-- the bands exist to remove.
-- Deterministic criteria (§7.8) produce NO rows in this table: there is no judge and no
-- verdict, only a lookup. Their criterion_score row carries judge_count = 0, which is why
-- that column admits 0 alongside the odd panel sizes.
CREATE INDEX idx_verdict_agg ON verdict(run_id, submission_id, criterion_id);

CREATE TABLE criterion_score (
  run_id            TEXT NOT NULL,
  submission_id     TEXT NOT NULL,
  criterion_id      TEXT NOT NULL,
  band              TEXT NOT NULL,         -- median band across the panel (R41)
  band_spread       INTEGER NOT NULL,      -- ordinal distance low..high band; adjacent
                                           -- disagreement is weaker evidence than distant
  points            REAL NOT NULL,         -- DERIVED from band via criterion_band, once,
                                           -- after aggregation. Never an average of judges
  judge_count       INTEGER NOT NULL      -- 0 for a deterministic criterion (§7.8); otherwise
                    CHECK (judge_count = 0        -- 1, 3 or 5. An even panel has no unique
                           OR judge_count % 2 = 1),  -- median, so it is a failed write rather
                                           -- than a rounded verdict (R48)
  agreement         REAL,                  -- null when judge_count is 0 or 1; ordinal α
  -- Extraction-integrity inputs. Unanimous judges on unverified evidence is
  -- LOW confidence, not high (§7.4); confidence must encode that inversion.
  spans_verified    INTEGER NOT NULL,      -- deterministic offset/text check
  evidence_present  INTEGER NOT NULL,
  sufficiency_flag  INTEGER NOT NULL,      -- any judge said evidence insufficient
  ocr_overlap_risk  INTEGER NOT NULL,      -- §7.5, R24
  confidence        REAL NOT NULL,
  routing           TEXT NOT NULL          -- 'triage' is the operator queue, NOT the
                    CHECK (routing IN ('auto','queued','reviewed',  -- teacher's review
                                       'provisional','triage')),        -- budget (R54)
  state             TEXT NOT NULL
                    CHECK (state IN ('final','provisional_unreviewed',
                                     'ungradeable_by_panel',
                                     'unresolved_selection')),  -- §7.8, R55: an unreadable
                                           -- mark is not a wrong answer
  PRIMARY KEY (run_id, submission_id, criterion_id)
);

-- THE FINAL GRADE. Before v3.1 the schema stopped at criterion_score and no table held a
-- student's result (§7.9, R56). One row per submission, produced automatically for every
-- submission, with no per-student teacher action.
CREATE TABLE submission_grade (
  run_id            TEXT NOT NULL,
  submission_id     TEXT NOT NULL,
  raw_points        REAL NOT NULL,
  scaled_score      REAL NOT NULL,
  grade             TEXT,                  -- from grade_boundary; null if none declared
  policy_version    TEXT NOT NULL,         -- which grade_policy produced this, for appeals
  -- Coverage. A grade is issued whichever way these fall; they say what it rests on, and
  -- provisional inputs never withhold it (R58).
  criteria_total    INTEGER NOT NULL,
  criteria_auto     INTEGER NOT NULL,      -- auto-accepted, never seen by a human
  criteria_reviewed INTEGER NOT NULL,      -- teacher accepted, edited or overrode
  criteria_provisional INTEGER NOT NULL,   -- scored but unreviewed (R26)
  criteria_missing  INTEGER NOT NULL,      -- NO score: missing page, unreadable mark,
                                           -- quarantined unit. The only legitimate blocker
  boundary_at_risk  INTEGER NOT NULL,      -- could the provisional items move this student
                                           -- across a boundary? The number that matters
  score_low         REAL,                  -- when boundary_at_risk, show a range not a point
  score_high        REAL,
  state             TEXT NOT NULL
                    CHECK (state IN ('final','provisional','incomplete')),
                                           -- incomplete = criteria_missing > 0, an INGESTION
                                           -- problem routed to the operator, never to the
                                           -- teacher as a marking decision
  finalized_at      TEXT,                  -- set by one batch action for the whole class
  PRIMARY KEY (run_id, submission_id)
);

CREATE TABLE narrative (
  run_id        TEXT NOT NULL,
  submission_id TEXT NOT NULL,
  level         TEXT NOT NULL,             -- l1_question|l2_test
  question_id   TEXT,
  text          TEXT NOT NULL,
  PRIMARY KEY (run_id, submission_id, level, question_id)
);
-- Synthesis writes here and has no write path to criterion_score (§7.2 Rule 3).

CREATE TABLE review_queue (
  run_id        TEXT NOT NULL,
  submission_id TEXT NOT NULL,
  criterion_id  TEXT NOT NULL,
  rank_score    REAL NOT NULL,             -- expected value (§10)
  reason        TEXT NOT NULL,             -- boundary|disagreement|history|random_arm|ocr
  est_seconds   INTEGER NOT NULL,
  shown_at      TEXT,
  action        TEXT,                      -- accept|edit|override|skip
  new_band      TEXT,                      -- the teacher edits on the band scale (§5.10)
  new_points    REAL,                      -- derived from new_band, not entered directly
  acted_at      TEXT,
  PRIMARY KEY (run_id, submission_id, criterion_id)
);
```

### 9.7 Schemas: Tier D, durable records and metrics

```sql
CREATE TABLE audit_record (                -- append-only; never updated or deleted
  audit_id           TEXT PRIMARY KEY,
  submission_id      TEXT NOT NULL,
  criterion_id       TEXT NOT NULL,
  final_points       REAL NOT NULL,
  decided_by         TEXT NOT NULL,        -- system|teacher
  package_version_id TEXT NOT NULL,        -- exactly which instrument produced this grade
  -- A deterministic grade has no panel and no cited spans; what makes it explicable is the
  -- key it was checked against and the selection that was read (§7.8). Forcing a panel_config
  -- onto it would record a fiction in an append-only table.
  evaluation_mode    TEXT NOT NULL CHECK (evaluation_mode IN ('judged','deterministic')),
  panel_config       TEXT,                 -- null when deterministic
  prompt_template_v  TEXT,                 -- null when deterministic
  answer_key_ref     TEXT,                 -- key + its package version; null when judged
  selection_read     TEXT,                 -- the option(s) extracted; null when judged
  cited_spans        TEXT,
  recorded_at        TEXT NOT NULL
);

CREATE TABLE label (                       -- §6.8
  label_id           TEXT PRIMARY KEY,
  package_version_id TEXT NOT NULL,
  cohort_id          TEXT NOT NULL,
  criterion_id       TEXT NOT NULL,
  assignment_type    TEXT NOT NULL,        -- MVVP runs per type (§2.5, §5.6)
  -- R20: acceptance is not ground truth. Only 'blind' supports validity claims.
  label_type         TEXT NOT NULL CHECK (label_type IN
                       ('accept','edit','override','blind')),
  saw_system_output  INTEGER NOT NULL,     -- 0 only for blind labels
  -- R53: a teacher overriding a multiple-choice result is telling us the answer key or the
  -- mark reading was wrong, not that a grader misjudged. Operationally useful, but it is not
  -- evidence about grader quality, so agreement is computed over judged rows only.
  evaluation_mode    TEXT NOT NULL CHECK (evaluation_mode IN ('judged','deterministic')),
  -- Bands, not points, are what agreement is computed over: the scale is ordinal, and
  -- comparing derived point values would smuggle interval assumptions back in (§5.10, R41).
  system_band        TEXT NOT NULL,
  teacher_band       TEXT NOT NULL,        -- the teacher grades on the same band scale
  band_distance      INTEGER NOT NULL,     -- ordinal gap; feeds ordinal α and the R44 check
  system_points      REAL NOT NULL,        -- derived, retained for reporting only
  teacher_points     REAL NOT NULL,        -- derived, retained for reporting only
  agreed             INTEGER NOT NULL,     -- exact band match
  routing            TEXT NOT NULL,        -- auto|queued; required to de-bias (§6.8)
  origin             TEXT NOT NULL,        -- base|escalation|random_arm|blind_sample
  review_seconds     INTEGER,              -- rushed acceptances are weaker evidence
  panel_config       TEXT NOT NULL,
  recorded_at        TEXT NOT NULL
);
-- Agreement statistics computed over label_type='blind' AND evaluation_mode='judged' only.
-- Everything else is an operational signal, not a validity claim.
CREATE INDEX idx_label_mvvp ON label(assignment_type, criterion_id, recorded_at);

-- Per-cohort statistics. Feeds the class rollup and the package's expected distributions.
CREATE TABLE criterion_stats (
  cohort_id        TEXT NOT NULL,
  criterion_id     TEXT NOT NULL,
  n                INTEGER NOT NULL,
  band_histogram   TEXT NOT NULL,          -- JSON {band: count}; the primary distribution
  band_entropy     REAL NOT NULL,          -- spread across bands. Collapsing toward interior
                                           -- bands is the compression signal (R44)
  interior_rate    REAL NOT NULL,          -- share of verdicts in non-extreme bands. Compare
                                           -- against the blind-gold interior rate, not to a
                                           -- fixed threshold: the question is whether the
                                           -- PANEL is narrower than the teacher (§5.10)
  mean_points      REAL NOT NULL,          -- derived; reporting only
  sd_points        REAL NOT NULL,          -- derived; reporting only
  histogram        TEXT NOT NULL,          -- JSON, over derived points; reporting only
  escalation_rate  REAL NOT NULL,
  override_rate    REAL,                   -- of reviewed items
  panel_agreement  REAL,                   -- chance-corrected ordinal α, escalated subset
  uncited_rate     REAL NOT NULL,
  PRIMARY KEY (cohort_id, criterion_id)
);
-- For deterministic criteria, band_histogram is the correct/incorrect split and
-- band_entropy / interior_rate are null: a two-band deterministic scale has no interior
-- and no compression to measure (§5.10, §7.8).

-- Per-option response distribution for multiple-choice questions. §7.8 calls distractor
-- analysis one of the strongest class-level outputs at n=350 — which wrong option the cohort
-- chose is a sharp, specific signal about a misconception — and it needs its own shape,
-- since criterion_stats is per-band and this is per-option.
CREATE TABLE mcq_item_stats (
  cohort_id       TEXT NOT NULL,
  question_id     TEXT NOT NULL,
  option_id       TEXT NOT NULL,
  chosen_count    INTEGER NOT NULL,
  is_key          INTEGER NOT NULL,        -- denormalized so the rollup needs no join
  PRIMARY KEY (cohort_id, question_id, option_id)
);
CREATE TABLE mcq_item_summary (
  cohort_id           TEXT NOT NULL,
  question_id         TEXT NOT NULL,
  n                   INTEGER NOT NULL,
  correct_rate        REAL NOT NULL,       -- item difficulty, exact rather than estimated
  blank_count         INTEGER NOT NULL,    -- answered nothing: a legitimate zero
  unresolved_count    INTEGER NOT NULL,    -- mark unreadable: NOT a wrong answer (R55).
                                           -- A high rate here is a scanning problem, and
                                           -- must never be read as a difficult question
  PRIMARY KEY (cohort_id, question_id)
);

-- Operational metrics. Not about students; about whether the harness is healthy.
CREATE TABLE run_metrics (
  run_id              TEXT PRIMARY KEY,
  total_work_units    INTEGER NOT NULL,
  escalated_units     INTEGER NOT NULL,
  quarantined_units   INTEGER NOT NULL,
  wall_clock_seconds  INTEGER NOT NULL,
  tokens_in           INTEGER,
  tokens_out          INTEGER,
  cache_hit_rate      REAL,                -- validates the §8.4 prefix ordering
  peak_concurrency    INTEGER,
  ocr_failure_rate    REAL,
  review_minutes_used REAL,
  review_items_shown  INTEGER,
  review_items_flagged INTEGER,            -- shown vs flagged is the R12 honesty check
  resolved_builds     TEXT,                -- JSON: per judge, the provider + served build the
                                           -- responses actually reported (§8.7 item 1). What
                                           -- graded the work, not what was requested
  transport_retries   INTEGER,             -- transport/parse only; never score resampling
  rate_limited_calls  INTEGER,             -- rising rate means concurrency is set too high
  rate_limit_wait_s   INTEGER,
  estimated_cost      REAL,                -- shown to the operator before dispatch (§8.7 item 5)
  actual_cost         REAL,                -- cost per assessment as a measured property
  cost_currency       TEXT,
  retention_setting   TEXT                 -- zero-retention routing in force, per R31/§9.14
);
```

The provider columns exist so that a grade issued on the cloud profile is as explicable years later as one issued locally (§6.7). `resolved_builds` is the load-bearing one: a model slug records what was *asked for*, and on a hosted provider that is not the same thing as what answered. A gap between `estimated_cost` and `actual_cost` is also worth watching as a signal in its own right — it usually means escalation ran higher than projected, which is a quality signal wearing a billing costume.

`cache_hit_rate` deserves a note. It is the only direct evidence that the Section 8.4 prompt ordering is actually working, and a silent regression there is a five-fold slowdown with no error message. Treat a drop in this metric as a build failure, not a curiosity.

### 9.8 What is *not* stored

Worth stating explicitly, because each absence is a design decision:

- **No cross-judgment scratchpad.** There is no place for a judge to leave notes for a later judgment. If such a table existed, someone would use it.
- **No embedding index over student submissions.** Nothing in the scoring path retrieves by similarity (§9.1).
- **No global student profile.** The harness does not accumulate a picture of a student across assessments. This is partly privacy and partly bias: a grader that knows a student's history is a grader with an anchor, and the halo effect Section 7.2 blocks within an assessment would return across assessments.
- **No raw model conversation logs beyond the current run.** Rationales are kept in the verdict record; full prompt transcripts are debug artifacts with a short retention.

### 9.9 Exchange contracts between actors

The wire format between orchestrator and each worker. These are the isolation guarantee expressed as data structures: **what a judge can see is exactly what the schema permits, and there is no field for another verdict.**

**ExtractionRequest / ExtractionResult**

```json
// ExtractionRequest
{
  "work_id": "sha256:...",
  "criterion": { "criterion_id": "c4", "text": "...", "evidence_type": "textual_span" },
  "question": { "prompt_text": "...", "reference_solution": "..." },
  "dependency_evidence": [                     // §7.2 Rule 2, evidence only
    { "criterion_id": "c2", "spans": [{ "start": 120, "end": 188, "text": "..." }] }
  ],
  "submission": { "submission_id": "s231", "transcript": "..." }   // ALWAYS LAST (§8.4)
}

// ExtractionResult
{
  "work_id": "sha256:...",
  "spans": [{ "start": 340, "end": 402, "text": "..." }],
  "extractor": "qwen3-30b-a3b@q4",
  "notes": null
}
```

**ScoringRequest / ScoringResult** — the critical contract:

```json
// ScoringRequest
{
  "work_id": "sha256:...",
  "criterion": {
    "criterion_id": "c4", "text": "...",
    // No max_points, no point values, no numeric scale of any kind (R39). A judge that can
    // see a 0..5 scale reasons on it whatever it is asked to emit, and the label becomes a
    // thin wrapper over the same centre-seeking judgment.
    "bands": [                                       // even-numbered, ordered low to high
      { "band": "absent_or_wrong",      "descriptor": "No conclusion stated, or a conclusion contradicted by the cited evidence" },
      { "band": "asserts_only",         "descriptor": "States the conclusion with no mechanism cited" },
      { "band": "derives_only",         "descriptor": "States the conclusion and cites the mechanism; does not address the boundary case" },
      { "band": "derives_and_justifies","descriptor": "States the conclusion, cites the mechanism, and addresses the boundary case" }
    ],
    "exemplars": [ { "band": "derives_and_justifies", "text": "..." },
                   { "band": "asserts_only",          "text": "..." } ]
  },
  "question": { "prompt_text": "...", "reference_solution": "..." },
  "evidence": { "spans": [ { "start": 340, "end": 402, "text": "..." } ] },
  "dependency_evidence": [ { "criterion_id": "c2", "spans": [ ... ] } ],
  "submission_text": "..."                     // ALWAYS LAST
}
```

There is deliberately **no field** for: other judges' verdicts, this judge's verdicts on other criteria, other submissions, prior cohorts, the student's identity or history, or the running score. The schema is a whitelist, and validating a request against it is the mechanical enforcement of Rule 1.

```json
// ScoringResult
{
  "work_id": "sha256:...",
  // FIELD ORDER IS GENERATION ORDER AND IS PART OF THE CONTRACT (R42). Evidence first,
  // verdict last. The pre-2.7 schema emitted the score first and the rationale last, which
  // is a snap judgment followed by a justification invented to fit it. Lint this the way
  // §8.4 lints prompt field order.
  "cited_spans": [ { "start": 340, "end": 402 } ],   // null => confidence downgrade
  "evidence_assessment": "Span 340-402 states the conclusion and names the mechanism. No span addresses the boundary case.",
                                                     // An INVENTORY against the band
                                                     // descriptors, not free commentary.
                                                     // "a fairly weak answer overall" is a
                                                     // magnitude judgment and recreates the
                                                     // centre-seeking bias one step earlier
  "evidence_sufficient": true,                       // §7.4: false => extraction problem,
                                                     //   route for re-extraction, do not score
  "band": "derives_only",                            // one of the declared bands. No number
  "self_confidence": 0.62                            // a feature, not the authority (§7.1)
}
```

**AggregationResult** (orchestrator-internal, never sent to a judge):

```json
{
  "submission_id": "s231", "criterion_id": "c4",
  "verdicts": [ { "judge_id": "llama33", "band": "derives_only" },
                { "judge_id": "qwen3",   "band": "derives_and_justifies" },
                { "judge_id": "gptoss",  "band": "derives_only" } ],
  // Aggregation is ORDINAL (R41): median band, spread recorded. Mapping each judge to
  // points and averaging would have produced 3.33 -- a value that corresponds to no band
  // and describes no behaviour, rebuilding the continuous scale the bands remove.
  // judge_count is odd by requirement (R48): a two-judge panel split across adjacent
  // bands has no unique median, and any tie-break would be a hidden thumb on the scale.
  "band": "derives_only", "band_spread": 1, "judge_count": 3,
  "points": 3.0,                                     // derived from the aggregated band, once
  "agreement": 0.71,                                 // ordinal α: adjacent disagreement
                                                     // counts for less than distant
  "confidence": 0.58,
  "routing": "queued", "route_reason": "adjacent_band_disagreement"
}
```

**SynthesisRequest** carries verdicts and evidence but its **result schema has no points field at all** (§7.2 Rule 3), which is how "synthesis cannot move a grade" becomes structural rather than instructed:

```json
// SynthesisResult (L1, per question)
{ "work_id": "sha256:...", "question_id": "q3", "text": "..." }
```

**ReviewItem**, orchestrator to teacher UI:

```json
{
  "submission_id": "s231", "criterion_id": "c4",
  "student_ref": "R-0231",
  // The teacher reviews and edits on the BAND scale, with points shown as the derived
  // consequence. An override that set points directly would bypass the band descriptors
  // and produce a label that cannot be compared with a panel verdict (§5.10, R41).
  "proposed_band": "derives_only",
  "band_options": [ { "band": "asserts_only",  "descriptor": "..." },
                    { "band": "derives_only",  "descriptor": "..." } ],
  "proposed_points": 3.0, "max_points": 5,           // shown to the teacher, never to a judge
  "narrative": "...",
  "evidence_spans": [ { "start": 340, "end": 402, "text": "..." } ],
  "reason": "boundary", "est_seconds": 40,
  "package_version_id": "pkg:...@v3",
  "grade_boundary_delta": 0.25
}
```

**LabelRecord**, teacher action back to the durable store:

```json
{
  "package_version_id": "pkg:...@v3", "cohort_id": "coh:2026-b",
  "criterion_id": "c4",
  "system_points": 3.75, "teacher_points": 3.0,
  "action": "override", "routing": "queued", "origin": "escalation",
  "recorded_at": "2026-08-09T07:41:00Z"
}
```

**PackageManifest**, the portable export (§9.4):

```json
{
  "package_version_id": "pkg:9f3a...@v3",
  "title": "Kinematics Unit Test", "subject": "Physics", "grade_level": "Year 11",
  "parent_version_id": "pkg:9f3a...@v2",
  "questions": 5, "criteria": 15,
  "contains_real_student_text": false,
  "validated_panel": ["llama-3.3-70b@q4", "qwen3-30b-a3b@q4"],
  "prompt_template_v": "2026.07.1",
  "validation_by_population": [                   // R23: never a global flag
    { "population_scope_id": "ng-nerdc-ss2-en",
      "cohorts_used": 6,
      "operational_count": 2412,                  // NOT a validity claim (R20)
      "blind_count": 180,                         // agreement computed from these only
      "kappa": 0.71,
      "weakest_criterion": { "criterion_id": "c4", "kappa": 0.44 },
      "surface_proxy_flags": ["c7:length_correlation"] }
  ],
  "exemplar_provenance": "paraphrased",           // what it was validated with (§9.4)
  "schema_version": 4,
  "signature": "..."
}
```

The manifest is what a teacher sees before importing a package. It is deliberately honest about the weakest criterion, because a package that advertises only its overall number is the Section 2.1 mistake in portable form.

### 9.10 Idempotency and the work ledger

Resumability comes from making every unit of work **deterministically identifiable and exactly-once**.

```
work_id = sha256(run_id, stage, submission_id, criterion_id, judge_id,
                 package_version_id, panel_config,
                 prompt_template_version, extractor_version)
```

Three properties follow:

1. **Resume is trivial.** On restart, skip any unit with `status='done'`. No separate bookkeeping about where the run was.
2. **Invalidation is automatic.** Change the rubric, swap a judge, edit a prompt template, and every affected work ID changes, so stale results cannot be silently reused. This is also the mechanism behind the Section 6.5 dual-scoring gate: two package versions produce disjoint work IDs and coexist without collision.
3. **Reruns are safe.** Re-running a completed run is a no-op rather than a duplicate-write hazard.

**Leases prevent stuck work.** A worker claims a unit by setting `status='leased'` with an owner and an expiry a few minutes out, heartbeating while it works. If the process dies the lease expires and a sweeper returns the unit to `pending`. Without leases a crash mid-flight leaves work permanently claimed and the run never completes.

**Poison-pill quarantine.** A submission that fails extraction three times, typically a malformed scan or a pathological OCR result, moves to `quarantined` rather than being retried forever. Quarantined units surface as an ingestion problem (R13), never as a score. **A student must never receive a low grade because a file failed to parse**, and without explicit quarantine that is exactly what happens: the pipeline scores an empty transcript as an empty answer.

**The ledger grows during the run**, because adaptive panel depth (§7.1) creates escalation units mid-flight. Consequences a naive design gets wrong:

- The completion predicate is not "all enumerated units done." It is **"no pending units and no in-flight units that could spawn escalations."**
- Escalation units carry `origin='escalation'`, keeping the random arm statistically separable in the label store. Conflating them destroys the unbiased estimate.
- Insert escalation units in the same transaction as the verdict that triggered them, so a crash between the two cannot lose the escalation.

### 9.11 Failure taxonomy

| Failure | Detection | Response |
|---|---|---|
| Process crash or operator stop | Lease expiry | Sweeper requeues; resume from ledger |
| Model server unreachable | Connection error | Backoff, pause run, alert operator; do not fail units |
| Out of memory on model swap | Allocation error | Reduce concurrency and retry; if persistent, drop to a smaller panel and record it in `panel_config` |
| Panel left with an even judge count by a failed unit | Oddness check before aggregation | Retry to restore the third judge. If unrecoverable, discard the second verdict and fall back to the base single-judge band, marked provisional. Never adjudicate between two (R48) |
| Malformed model output | Schema validation fails | Retry up to 3 times; then quarantine and flag the criterion |
| Unparseable submission | Ingest or extraction failure | Quarantine, route to teacher as an ingestion issue (R13) |
| PDF unreadable or encrypted (V0) | Ingestion gate | Quarantine; operator rescans. Never scored |
| Missing or duplicated page (V1) | Page-sequence or similarity check | Quarantine naming the specific pages; a rescan of one page produces a new document version, not an in-place edit (R32) |
| Question has no answer region (V2) | Structural check against the assessment | Route to operator as `absent`, never as a blank answer worth zero (R36) |
| Submission matched to the wrong assessment (V4) | Identifier, structural, and semantic signals disagree | Halt scoring for that submission; propose candidates for a human to confirm. Never reassign automatically (R35) |
| **Cohort-wide V4 failure spike** | V4 mismatch rate across the run exceeds a threshold | Circuit-break the run. 340 mismatches is one operator error with one fix, not 340 triage items (§7.7) |
| Assembly order undeterminable | No page numbers, no markers, ambiguous filenames | Quarantine and ask the operator for the order. Guessing produces a document that transcribes cleanly and fails V2 (R33) |
| Disk full | Write error | Halt immediately, preserve ledger; a partial audit write is worse than stopping |
| Clock skew on resume | Lease timestamps in the future | Use monotonic counters for leases, not wall-clock alone |
| Package schema newer than binary | Version check at import | Refuse to import, tell the operator to upgrade |
| Provider rate limit (cloud) | HTTP 429 | Expected, not an error: honor `Retry-After`, back off with jitter, lower in-flight concurrency. Count in `run_metrics` |
| Provider outage mid-run (cloud) | Repeated 5xx or timeouts | Pause the run and alert; resume against the **same** backend. Never fail over to another provider or to local — that would put two graders in one run (R1, §0.7) |
| Cost ceiling reached (cloud) | Running spend vs configured ceiling | Pause and surface with the spend and the remaining unit count; never stop silently, and never continue past the ceiling unattended |
| Resolved model build changed mid-run (cloud) | Response build metadata differs from the run's `resolved_builds` | Pause and alert. The panel changed underneath the run; continuing produces a run graded by two different judges under one name (§8.7 item 1) |
| Remote dispatch attempted with non-synthetic cohort in `dev-ci` | Pre-dispatch check on cohort consent flag | Refuse to dispatch (R31). Overriding is explicit and logged, never a silent config flag |

General principle: **fail the unit, never the run.** A run of 23,000 units should tolerate hundreds of individual failures and still deliver, with failures visible in the operator surface and affected students flagged rather than silently mis-scored.

### 9.12 Infrastructure: what to actually deploy

**Recommendation: SQLite at the school node, Postgres only if a central catalog is genuinely needed, and not an agent-memory framework at all.**

**SQLite in WAL mode is the default and probably the endpoint.** One file per cohort for Tiers C and R, one file per package for Tier P, one shared file for Tier D.

- **No server process.** Nothing to install, configure, start on boot, or restart after a crash. In a school staff room with no IT staff this outweighs every performance consideration.
- **Crash-safe.** WAL gives durable commits and readers that do not block the writer, which matches the workload: many concurrent readers, one serialized writer.
- **Capacity is not close to a concern.** A 350-student run is roughly 23,000 work units and a similar number of verdicts; tens of megabytes.
- **The package format falls out for free.** A portable package is a SQLite file, which is exactly the sneakernet requirement of Section 9.4. This is a strong argument on its own.
- **Backup is `cp`.** Tier D and Tier P are small files copyable to a USB stick.

**Blobs on the filesystem, hashes in the database.** Scans and PDFs live in a content-addressed directory; the database holds the hash and relative path. Keeps the database small and deduplicates resubmissions automatically.

**Postgres is a reasonable choice for exactly one thing: a central package catalog serving many schools**, if and when a program reaches the scale where packages are curated centrally and pushed out, and where someone exists to operate a server. It buys concurrent multi-writer access and richer analytics over accumulated labels across institutions. It buys nothing at a single school node, where it costs an install, a service to keep running, and a dependency that fails in exactly the conditions Section 0.2 describes. **Design the package format so this is a later deployment choice, not an architectural commitment**: if packages and labels are portable files, adding a central Postgres catalog later is a sync layer, not a rewrite.

**On mem0 and agent-memory frameworks: not appropriate here, and the reason is architectural rather than a matter of quality.** Tools in that family are built to let a model store and semantically retrieve what it deems relevant across sessions. That capability is precisely what Section 9.1 forbids in the scoring path: a judge that can recall how it scored a similar response, or what it noted about this student earlier, is a judge with an anchor, and the isolation guarantee is gone. They solve a real problem, that problem is conversational continuity for an assistant, and this harness needs the opposite property, which is enforced amnesia at judgment boundaries. What the harness needs is a transactional record store with exact-match keys, which is a database.

If a future component genuinely needs semantic retrieval, for instance clustering misconceptions across a class for the Stage E rollup, that is fine, because it sits outside the scoring path and reads only aggregate results. Keep it there, and keep it unable to write anything a judge will ever see.

**On the `cloud-hosted` and `dev-ci` profiles, the storage recommendation does not change by default, and the reason is worth stating.** A hosted single-tenant instance is still one writer serving one institution's runs, so SQLite on a persistent volume remains correct and keeps the package-is-a-file property (Section 9.4) intact. What changes is that the volume must genuinely persist — a container with an ephemeral filesystem silently converts the resumability guarantee of R3 and R14 into nothing, and it fails in exactly the way that is invisible until the first mid-run restart. Postgres becomes the right answer at the point a hosted instance is genuinely multi-tenant, with concurrent runs for different institutions needing isolation and multi-writer access. That is the same "later deployment choice, not an architectural commitment" boundary described above; the portable-file package format is what keeps it a choice.

**Optional analytics path:** export Tier D to Parquet and query with DuckDB when running the MVVP over months of accumulated labels. Read-only, never touches the scoring pipeline.

### 9.13 Concurrency and write throughput

- **Single writer thread.** Workers push results to an in-process queue; one thread drains and commits. Removes lock contention entirely.
- **Batch commits.** Every ~100 results or every few seconds. Per-row transactions at 23,000 units generate needless fsync pressure; batching keeps crash loss to seconds of work.
- **Ledger status commits promptly.** Losing a verdict costs one recomputation; losing the knowledge that a unit was done costs resume correctness.
- **Write the verdict and its ledger status in one transaction**, or a crash between them either loses completed work or marks incomplete work done.
- **Backpressure.** If the write queue grows past a threshold, slow dispatch. A run that outruns its own persistence loses work on crash.

### 9.14 Retention, PII, and purge

Tier C and Tier R hold verbatim student work in several places at once: transcripts, evidence spans, cited spans, narratives. This is the largest PII surface in the system and exists only for the run.

- **Purge Tiers C and R when results are accepted**, after promoting audit records, labels, and statistics. Real deletion, and remember `VACUUM`, since SQLite does not return freed pages otherwise.
- **Promote the minimum.** Audit records need the cited spans behind each grade, not full transcripts. Labels need scores and metadata, no text.
- **Tier P must never accumulate PII.** The `contains_real_student_text` flag and the exemplar `provenance` constraint are the enforcement points, and export should refuse when the flag is set unless explicitly overridden.
- **Pseudonymize in Tier D.** Labels carry `student_ref`, not names; the identity mapping lives in Tier C and is purged with it.
- **Filesystem permissions, not intent.** Harness-user-only directories. Never `/tmp`. Encryption at rest where the platform makes it cheap, which on a Mac it does.
- **Purge is a resumability boundary.** Once Tier R is gone the run cannot be resumed or re-explained beyond the audit record, so require explicit teacher acceptance first and default to retaining until then.

**On the cloud profile, PII leaves the machine by design, and the controls have to be explicit (R4, R31).** Under `edge-local` this whole section is enforced by the filesystem: student text never crosses a network boundary, and Section 11 can call that a headline feature. Under `cloud-hosted` the same text is in a container's volume and, more consequentially, in the body of every model call. That protection has to be rebuilt out of things that are configured rather than architectural:

- **Zero-retention routing is required, not preferred.** Configure the provider so prompts are not retained or used for training, verify it is actually in force for each model in the panel rather than assuming the account-level setting covers everything, and record the setting in `run_metrics` so an audit can show what was in force for a given grade.
- **Prefer regional routing** where the institution's jurisdiction requires it, and treat inability to constrain routing as a reason not to use a given model in that deployment.
- **The prompt is the PII surface.** Section 8.4's working store is student PII on disk; on this profile the same spans are also in every outbound request. Redaction is not available — the judge needs the actual text — so the control is provider selection and retention policy, not filtering.
- **Names never need to leave.** Pseudonymize before dispatch: the judge scores a response against a rubric and has no use for a student's identity. `student_ref` in, `student_ref` out, identity mapping stays in Tier C.
- **`dev-ci` sends synthetic or consented data only (R31)**, enforced at dispatch as described in Section 8.7, not by developer discipline.

### 9.15 Schema versioning

Tiers P and D outlive many software versions, so migrations are needed from day one: a `schema_version` table, forward-only numbered migrations applied at startup, and a refusal to open a schema newer than the binary understands. Packages carry their `schema_version` in the manifest so an older installation can decline an import cleanly instead of misreading it, which matters when packages travel between schools running different versions.

Tiers C and R are per-administration and can be recreated, so they need far less ceremony.

This is unglamorous and it is the difference between a validation record that compounds across years and one discarded at the first upgrade.

### 9.16 What the operator sees

- **Progress** from the ledger: units done, in flight, pending, quarantined, by stage and criterion.
- **Estimated completion** from observed throughput against remaining units, adjusted for the escalation rate observed so far, since escalations add work not in the initial count.
- **Quarantine list**, which is the operator's actual work: submissions needing a rescan or manual transcription.
- **Resume as a first-class command** requiring no arguments and safe to run when nothing is wrong.

### 9.17 How each stage depends on persistence

| Stage | Reads | Writes | Why persistence is required |
|---|---|---|---|
| Package import | Tier P file | package, criteria, validation record | Reuse across cohorts without retuning (§9.4) |
| Drift check | package_validation, sample scores | run.drift_check | Compares this cohort to the package baseline |
| A. Ingest | blobs | submission, transcript | OCR is expensive; never redo on resume |
| B. Ambiguity discovery | package, prior labels | package_version, elicitation_history | Dual-scoring compares two versions across the full class (§6.5) |
| C1. Extraction | package, submission | evidence, ledger | Dependencies resolve across batches hours apart (§7.2 Rule 2) |
| C1b. Integrity gate | evidence, submission region_conf | verified flags, re-extraction units | Span verification and OCR-overlap checks precede scoring (§7.4, §7.5) |
| C2. Scoring | evidence, criterion, exemplars | verdict, ledger, escalation units | Escalation decisions read persisted verdicts (§7.1) |
| C3. Aggregation | verdict | criterion_score | Panel verdicts complete at different times |
| C4. Synthesis | verdict, evidence, narrative L1 | narrative | L2 reads L1's earlier output (§7.2 Rule 3) |
| D. Review | criterion_score, review_queue | review_queue, audit_record, label | Teacher sessions span days; provisional items carry forward (R26) |
| D2. Blind sample | submissions only | label (type='blind') | The only unbiased ground truth (§6.8, R21) |
| E. Grade + Rollup | criterion_score, grade_policy, grade_boundary | **submission_grade**, criterion_stats, mcq_item_stats | Every submission gets a final grade automatically (R56); the aggregate view also feeds the package baseline |
| Package update | label, criterion_stats | package_validation | This is how a package appreciates with use (§9.2) |
| Validation | label | label | Accumulates across cohorts and months (§6.8) |

Every arrow crossing a time boundary is a persistence dependency, and at n=350 across repeated cohorts nearly every arrow crosses one. That is the case for treating this as architecture rather than plumbing.

---

## 10. What the teacher actually sees

**Per-student evaluation, per rubric criterion:**
- A narrative explanation, first and most prominent (Section 5.9).
- The specific span(s) of the submission used as evidence (Section 7.3, item 3).
- A score, editable in one click, visually secondary to the narrative.
- A visible **confidence flag** when the item was routed for review rather than auto-scored (Section 5.8). Teachers should see *which* scores the system was unsure about.
- The **rubric version** in force, discreetly, so a disputed grade can be traced (Section 6.7).

**The review queue, budgeted rather than thresholded (R12):**

This is the part of the teacher experience that breaks if it is designed at classroom scale. A confidence threshold that flags 15% of judgments produces about 68 review items in a 30-student class and roughly 790 in a 350-student class. The second number is not a queue, it is a second job, and a teacher who opens it once will not open it again.

So the review queue is **budgeted in teacher-minutes, not derived from a threshold.** The teacher says how long they have. The system fills that budget with the highest-value items available and is explicit about what it did not surface.

**Deterministic criteria do not enter this queue.** A multiple-choice item that was read
cleanly has a correct score by construction; there is nothing for the teacher to adjudicate,
and admitting it would spend budgeted minutes on the one part of the paper that does not need
them (R54). The two exceptions are routed elsewhere rather than here: an unresolvable mark is
an operator triage item (§7.5), and a suspected wrong answer key is a package correction the
teacher makes once for the whole cohort, not 350 individual reviews.

**Rank by expected value, decision-theoretically.** Uncertainty alone is the wrong ordering, because a highly uncertain judgment on a criterion worth 2% of the grade matters less than a moderately uncertain one on a criterion worth 20%. The ranking quantity is:

```
        probability the score is wrong  ×  impact on the student if it is
rank =  ─────────────────────────────────────────────────────────────────
                          estimated review time
```

Which resolves in practice to:

- **Impact**: criterion weight in the final grade, and proximity to a grade boundary. A judgment that could move a student between pass and fail outranks one that moves a strong student from 88 to 85.
- **Probability of error**: panel disagreement weighted by spread, evidence integrity failures (Section 7.4), transcription overlap (Section 7.5), and the criterion's historical override rate. Not self-reported confidence alone (Section 7.1).
- **Cost**: estimated seconds to review, so that many cheap high-value items can outrank one expensive marginal one.
- **Reserved carve-outs**, protected from value ranking because their purpose is statistical rather than corrective: the **blind sample** (Section 6.8, R21) and the **random arm** (Section 7.1). Both must survive triage, so allocate them a fixed share of the budget up front rather than letting the ranking crowd them out.

**What happens to the residual (R26).** The budget will run out with items still flagged, and the design must say what becomes of them rather than leaving it to whatever the implementation happens to do. The residual is not a rare edge case: at 350 students it is most of the queue.

Two things must not happen. **The residual must not be silently finalized**, since that records an unreliable score as though it were reviewed. And it must not be **backfilled with a substitute value such as the cohort mean or a default partial credit**, which was proposed during review of this design and is worse than it sounds: it assigns a student a number derived from other students' work, which is indefensible in a grade dispute ("why did I receive 3?" "because your classmates averaged 3"), and it corrupts the class-level distribution that is the system's most valuable output (Section 0.1). A fabricated score is not a safe default; it is an unfalsifiable one.

The policy instead:

1. **Mark provisional.** The system's score stands as the working value, tagged `provisional_unreviewed`, visible as such to the teacher and reflected in what the student sees.
2. **Carry forward, do not drop.** Provisional items persist in the queue across review sessions. Persistence already supports this (Section 9.6); the queue is not per-sitting.
3. **Aggregate honestly, and still aggregate.** A total containing provisional criteria is issued, marked provisional, with its coverage recorded (§7.9, R58). Where those criteria could move the student across a boundary, show a range rather than a point. What must not happen is withholding the grade: provisional means labelled, not missing.
4. **Finalize automatically; let the teacher intervene, never wait for them (R60).** Versions before 3.2 required the teacher to accept the batch before grades finalized, which quietly made every grade in the class hostage to one person having time — a teacher who is ill, or simply busy, would leave 350 students ungraded, which is the exact failure §0.1 describes. Grades therefore finalize **on run completion by default**. The teacher may configure a review window (say 48 hours) during which they stay provisional; when it lapses they finalize on their own. The batch-accept action remains available for a teacher who wants to sign off explicitly, and the audit record notes which path was taken — but it is an option, never a gate. Accountability is exercised through approving the instrument at setup and through the standing ability to change any grade at any time, not through a mandatory click on every run. The teacher may reasonably decide that 600 low-impact provisional items are fine; that decision should be theirs and recorded, not made by a default.
5. **Escalate on the next administration.** Criteria that persistently exhaust the budget are criteria the escalation policy is over-flagging, or rubric items that need work. Surface the pattern rather than absorbing it every term.

Be explicit at the top of the queue: "You have 30 minutes. These are the 40 highest-value items of 790 flagged. The remaining 750 are scored provisionally and will stay in your queue." Hiding the residual would misrepresent what the system did, and the teacher needs to know it exists when a student queries a grade.

**Batch-level actions matter more than per-item ones at this scale.** If 210 of 350 students missed criterion 3 identically, the teacher should be able to review the pattern once and apply a decision to the group, rather than clicking through 210 near-identical items. Design for the group action first; per-item review is the exception path.

**Score compression is the bias this design was blind to longest.** Central tendency — raters avoiding the ends of a scale — was structurally invited by the pre-2.7 numeric scale, and it is invisible to every metric the system reports: judges that compress toward the middle compress *together*, so inter-judge agreement rises and confidence rises with it, and agreement against a teacher who shares the same human bias still looks respectable. Section 5.10's behaviourally-anchored bands are the structural defense, and R44's compression check is the monitor — but note the monitor's honest limit: it detects the panel compressing *more* than the teacher, not both compressing together. The only defense against the latter is that a band descriptor's conditions are checkable against the cited spans, which is why the descriptors must state what a response *does* and never how good it is.

**There are two distinct ordering rules and they are easy to confuse.** Section 5.10 governs generation order *inside* a judgment — cited spans, then the evidence assessment, then the band — and exists so the verdict is anchored to an evidence inventory rather than to a vague impression. Section 5.9 and the bullet below govern presentation order *to the teacher*. Different concerns, different rationales; neither substitutes for the other.

**Guard the narrative-versus-score ordering.** Section 5.9 recommends showing narrative feedback before the numeric score, which is right. But a synthesis narrative that says "the reasoning here is strong overall" sitting above a score of 2 is functionally a second, competing grade, and a teacher skimming 40 items will anchor on the prose. Synthesis is barred from *writing* scores (Section 7.2 Rule 3); it must also be barred from *implying* them. Prohibit numeric claims and holistic overall-quality verdicts in synthesis output, keep narratives criterion-anchored and evidence-referenced, and test for it: an assertion that generated narrative contains no score-like claims is as checkable as the schema constraint that keeps synthesis out of the score field.

**Class-level rollup:**
- Score distribution per criterion across the class: where the whole class struggled versus where most succeeded, which is the actual pedagogical value teachers want. **At n=350 this is the system's strongest output**, both because it is information the teacher cannot obtain any other way at this class size, and because the statistics are genuinely solid at that sample size in a way they are not at n=30 (Section 3.5). Misconception clustering, which is noise on 30 responses, is a real signal on 350.
- **Chance-corrected agreement**, in plain language ("the graders agreed on X of Y students after accounting for lucky guesses"), **with the sample size stated next to it** so nobody reads an 8-sample figure as a system-wide accuracy claim.
- The submissions routed for review, those flagged but not reviewed, and why.
- If a rubric revision happened: what changed, that the teacher approved it, and that the non-inferiority gate passed.

**What it should never show:** a single unqualified "AI accuracy: 94%." Per Section 2.1 that number is inflated by chance agreement; per Section 2.2 it does not transfer across assignment types; per Section 3.5 it is not even measurable at calibration-set sizes. A defensible dashboard reports the chance-corrected figure, scoped to this assignment type, with its sample size attached.

**Four outputs, four risk profiles, four sets of metrics.** The system produces criterion scores, a total grade, narrative feedback, and a class-level diagnosis. On a mixed-format paper, the criterion-score metrics cover the **judged** items only; deterministic multiple-choice correctness is reported alongside them and never merged into them (§7.8, R53), since an item with a known answer is not evidence about the quality of a grader. These fail independently and should not share a single quality number. A model can produce well-grounded feedback attached to a slightly wrong score, or a correct score with a misleading explanation, and only separate measurement distinguishes them:

| Output | The question | How measured |
|---|---|---|
| Criterion score | Is this criterion's score correct? | κ / QWK against blind labels, per criterion (§6.8) |
| Total grade | Does aggregation reflect the rubric? | Deterministic; unit-testable, not a model property |
| Narrative feedback | Is it grounded, faithful to this student's work, and actionable? | Citation validity rate, teacher rating on a sample, hallucinated-claim rate |
| Class diagnosis | Does the identified misconception actually exist? | Teacher confirmation on the rollup, sampled |

Feedback quality is the output the K-12 research says teachers and students most value, and it is the one most likely to go unmeasured because it has no obvious number. Measure it deliberately: a system with κ = 0.8 and ungrounded feedback is failing at its most valuable job.

**Progress reporting during a run:** because execution is batched by criterion rather than by student (Section 8.4), no individual student is finished until the final criterion completes. Progress reads "criterion 8 of 12, judge 2 of 3," and results release per question or per test, not per student. A per-student progress bar cannot be populated honestly under this execution plan, so do not design one.

**Calibration UI principles:**
- Elicitation questions are an offer, never a gate. The skip button is first-class.
- Show the two conflicting student examples side by side. The teacher is answering about their own students' actual work, not about abstract rubric language, and that is what makes the question answerable in seconds.
- Never present a rubric edit as a fait accompli awaiting approval. Present the question; let the answer generate the edit.
- Show the final revised rubric text for explicit confirmation before it goes live, because that confirmation is the record referenced in Section 6.7.

**Rubric review UI, on declared dependencies (Section 7.2, Rule 2):**
- Show any declared dependency in plain language, not schema terms: "when grading criterion 4, the grader will see the work you credited under criterion 2" rather than "C4 depends on C2.evidence."
- Make it clear that only *evidence* travels, never scores, since a teacher's reasonable worry on reading "criterion 4 sees criterion 2" is exactly the halo effect the rule prevents.
- Dependencies default to none. Where the teacher's subject makes them likely (multi-part math and physics problems, where error carried forward is standard practice), offer the dependency as a suggestion during Stage A decomposition rather than applying it silently.
- Once approved, dependencies are read-only for the life of the rubric version (Section 6.2).

---

## 11. Risks, limits, and governance

- **Mid-range responses are the weak point, not the exception.** Every scoring system here degrades on ambiguous, partial-credit work. Route these to teachers by default rather than treating high confidence as the norm and low confidence as a rare edge case.
- **Mixed-format reporting can quietly push assessment back toward multiple choice.** Deterministic items agree with the teacher essentially always, cost nothing, and generate no review queue. If the system reports them alongside judged criteria in one figure, its own dashboard makes the multiple-choice half of a paper look like the better-performing half — applying exactly the pressure §0.1 identifies as the problem, from inside the tool built to relieve it. R53 keeps the statistics separate in the schema rather than by convention; the residual risk is presentational, and belongs on the list of things to check whenever the teacher-facing views change.
- **Rubric decomposition can change the construct, and the weight arithmetic hides it.** Splitting a criterion into sub-checks that total the same points looks conservative and is not: a configural criterion — coherence of argument, appropriateness of method — can be satisfied piece by piece while failing as a whole, and a compensatory holistic band becomes a conjunctive checklist that systematically penalizes the unusual-but-valid response. Sections 5.3 and 6.2 make decomposition conditional on an explicit test with preservation as the default. The residual risk is that the test is applied by a model and confirmed by a busy teacher, so treat a criterion reclassified from holistic to atomic as a redefinition requiring the same scrutiny as a rubric revision.
- **Construct drift is the primary risk introduced by rubric revision**, and it is insidious because it *improves* your measured agreement while degrading what you are actually measuring (Section 3.6). The Section 6 guardrails exist specifically because this failure mode is invisible to the metric a naive loop optimizes. If you ship only one guardrail, ship the dual-scoring non-inferiority gate (6.5): it is cheap, automatic, and catches the largest class of failures.
- **Do not compute agreement statistics from small calibration sets and present them as validation.** Section 3.5. If a stakeholder asks "how accurate is it," the honest early answer is "we do not have enough graded work yet to say, and here is the plan for when we will," not a number derived from eight papers.
- **Judgment isolation will be the first thing sacrificed under performance pressure**, and its erosion is silent. Reusing context across submissions or collapsing criteria into one call makes the system measurably faster and degrades no metric anyone is watching, while reintroducing halo and anchoring effects and inflating the very inter-judge agreement number the confidence gate depends on (Section 7.2). Treat isolation as an architectural invariant enforced in code, with a test that asserts no verdict from one judgment appears in another's context, rather than as a convention that survives on discipline. Section 8.3 gives the sanctioned ways to buy back the speed, and Section 8.4 gives the execution plan that makes them the default.
- **Unanimous panel agreement on corrupted evidence is the system's most dangerous failure**, because the mechanism meant to detect error is the one that hides it (Section 7.4). Confidence must invert on evidence-integrity failures rather than rising with agreement, and the two zero-cost checks (span verification, required-evidence) should be treated as non-optional rather than as hardening.
- **Teacher acceptance drifts toward rubber-stamping as the system improves**, which quietly converts the validation set into a record of people agreeing with the machine (Section 6.8). The blind sample is the only defense, it must be carved out of the review budget rather than competing with it, and agreement statistics must be computed from blind labels alone.
- **A reused package can silently stop fitting its population.** A rubric calibrated on one cohort carries that cohort's assumptions about language, prior coverage, and what a typical answer looks like. Section 2.2's finding that judge rankings do not transfer across task types applies one level up to transferring a calibrated instrument across student populations. The Section 9.4 drift check is cheap and advisory; the failure mode it guards against, a package quietly under-serving a cohort it was never validated on, is neither cheap nor visible. Treat a package's validation record as scoped to the populations listed in it.
- **The most likely way this system's isolation guarantees get destroyed is by someone adding "memory" to the agents.** It will be proposed in good faith and it will sound like an improvement: let the judge recall how it scored similar responses, give the grader context about the student, add retrieval so it can look things up. Every version of that reopens the contamination paths of Section 7.2, and none of them degrade a metric the system reports about itself. Section 9.1's one-way rule (the orchestrator reads memory, judges never do) is the architectural answer, and the context-assembly assertion described there is the machine-checkable form of it.
- **The working store is student PII on disk.** It holds verbatim spans of student work for the duration of a run (Section 8.4). Store it alongside the submissions under the same access controls, never in a shared temp directory, and purge it on completion. On `edge-local` this never leaves the machine, which is a real advantage but not a substitute for handling the file correctly. On `cloud-hosted` it sits on a container volume and the same spans are also in every outbound model call, so the file-handling discipline is necessary and no longer sufficient — Section 9.14 specifies what has to be added.
- **Do not silently change a rubric a teacher published to students.** If students received R₀ in advance, a mid-stream revision has fairness implications beyond the technical ones, regardless of how well-guardrailed. Surface this explicitly in the calibration UI and default to R₀ when the assignment is flagged as having a student-facing published rubric.
- **The override log is a biased sample.** Teachers scrutinize flagged items more than auto-accepted ones, so overrides over-represent hard cases. Maintain the random spot-check queue (Section 6.8) or your accumulated validation set will be systematically pessimistic.
- **A validated panel does not stay validated.** Re-run the MVVP when assignment type, subject, or grade level changes, and periodically regardless. The Berkeley study's own limitations note silent model drift; the same applies to any local model version you update.
- **Local deployment is a genuine privacy advantage worth stating explicitly — and it is a property of the profile, not of the product.** On `edge-local`, student work never leaves school-controlled hardware, which sidesteps a large class of FERPA and vendor-data-handling questions that a cloud-only competitor solves contractually instead of architecturally. Treat this as a headline feature of that profile. What must not happen is the claim surviving the profile: marketing an architectural privacy guarantee while an institution is running `cloud-hosted`, where the same protection is contractual (Section 9.14) and only as good as the retention setting actually in force. The system should be able to state which profile it is running in and what that implies, in the operator's own interface.
- **The cloud profile's most likely governance failure is an institution that does not know which profile it is on.** The two are one product, deliberately, and that is what makes this possible: a district could enable hosted grading for convenience without anyone re-opening the data conversation that the local deployment made unnecessary. Make profile a visible, deliberate, logged setting — surfaced at run dispatch, recorded in the audit record behind every grade, and impossible to change mid-run.
- **Silent provider-side model substitution is the cloud profile's equivalent of construct drift.** A hosted slug can start routing to a different served build with no signal, and the resulting grader is a different grader (Section 8.7). Like construct drift, it degrades what is being measured while degrading no metric anyone is watching. The frozen-fixture conformance suite is the detector; without it, a package's accumulated validation record can go stale in a single provider-side change and continue to be displayed as if current.
- **Testing on one backend and deploying on another is a real risk this design accepts deliberately.** CI runs on OpenRouter; schools run local quantizations. Section 0.7 states the inversion plainly — the least-exercised path is the one that ships to the users with the least support — and it is mitigated rather than eliminated, by the Section 8.5 hardware gate and the Section 8.7 conformance suite. Anyone reasoning about this system's reliability should hold that as a known, managed limitation rather than assuming a green CI pipeline says anything about a Mac in a staff room.
- **The research is consistent that these systems work best as formative decision support with a teacher accountable for any grade affecting a student's record.** Stage D is not a stopgap to be automated away over time. It is the feature the research says makes the system trustworthy, and per Section 6.8 it is also the thing generating your validation data. Automating it away would remove the system's only source of ground truth.
- **AI-generated-content detection** (present in the GradeWithAI reference platform) is a far less mature research area than rubric-based scoring. This report does not recommend building or relying on it as part of the core pipeline; false-positive rates remain a live unresolved concern, and a false accusation of cheating is a much worse failure than a mis-scored criterion.

---

## 12. Implementation sequence

A suggested build order, front-loading the parts that make everything else safe:

**Phase 1, no calibration at all.** Stage A, C, D, E with rubric R₀ exactly as the teacher wrote it. Three things from the v2.4 review belong here rather than later, because each is cheap now and invalidates accumulated data if added afterwards: **span verification and the required-evidence check** (Section 7.4, near-zero cost, prevents extraction failures becoming low grades), **the blind sample** (Section 6.8, without which Phase 2 accumulates contaminated labels), and **`label_type` on every stored label** (Section 9.7, since retrofitting the distinction onto labels already collected is impossible). Panel of 2 to 3 diverse local models, extraction-then-scoring, confidence routing, full override logging with version pinning. **Judgment isolation (Section 7.2, Rules 1 and 3) and the criterion-batched execution plan (Section 8.4) are Phase 1 requirements, not later hardening steps.** Both are nearly free to build in at the start and expensive to retrofit: isolation because retrofitting means invalidating every label accumulated under the contaminated design, and the execution plan because prompt templates written in the wrong field order have to be rewritten and revalidated. The **persistence layer of Section 9** ships in Phase 1 too, at least Tier 0, the work ledger, the evidence and verdict stores, and the audit record. At 23,000 units per run there is no usable version of this system without resumability, and the content-hash work IDs (Section 9.4) are close to free at the start and painful to retrofit once results exist without them. Dependency *reads* from it (Rule 2) can wait until you hit a subject that needs them, which in practice means multi-part math or physics. **The provider abstraction of Section 0.7 (R27) is also Phase 1, and in build order it is nearly first**: development happens in containers against OpenRouter (R28), so the abstraction is not a portability feature to be added once a second deployment appears — it is the only way the first line of code gets tested at all. Building it later means retrofitting a seam through extraction, scoring, and synthesis simultaneously, and it means the local path and the tested path diverge before there is any suite that would notice. Ship Phase 1 with three provider implementations from the start: local, OpenRouter, and the recorded-fixture provider the fast test tier runs against. **Mixed-format support (§7.8) belongs in Phase 1**, and cheaply: the deterministic evaluator is a lookup, and the schema fields that carry it — `evaluation_mode`, `answer_key`, `selection`, `label.evaluation_mode` — are close to free at the start and painful to retrofit, since labels and audit records written without the distinction cannot be separated afterwards. It is also the difference between a teacher being able to use the system on their actual papers and having to restructure their assessment to fit the tool, which is the failure mode §0.1 is about.

This phase is a complete, useful, defensible product. Ship it before anything in Section 6 exists.

The **ingestion module of Section 7.7 is Phase 1** in full, including the validation ladder — not the transcription pass with the gates deferred. The gates are cheap to build and each one prevents a class of wrong grade that no later stage can detect: V4 in particular guards against a confident unanimous zero for a student who answered a different paper, and there is no version of "ship it and add validation later" where those grades are recoverable. The canonical-artifact rules (R32) belong here for the same reason as the content-hash work IDs: retrofitting immutability onto a transcript that verdicts already reference by offset is not a migration, it is an invalidation of everything computed so far.

**Phase 1.5, prove it on hardware — and prove the backends agree.** Run the Section 8.5 acceptance test before committing to a deployment platform or promising a batch window. This is a gate, not a milestone: a nine-hour result changes the product, and it is far cheaper to discover on 350 synthetic submissions than at a pilot site. Run the Section 8.7 backend conformance suite at the same time, for the same reason and with the same status. Everything up to this point will have been developed and tested on OpenRouter, so this is the first moment anyone finds out whether the local quantizations grade like the builds the whole suite was written against. Both gates are cheap here and expensive after a pilot has student grades in it.

**Phase 2, accumulate.** Run Phase 1 across real classes. The override log builds. Add the random spot-check queue. Once you have a few hundred labels for an assignment type, run the MVVP against them for real and find out what your panel's actual chance-corrected agreement is. Because Phase 1 enforced isolation, that agreement number is honest and the labels stay usable.

**Phase 3, add the guardrails before the feature they guard.** Build dual-scoring non-inferiority (6.5), adversarial back-translation (6.6), and the triage classifier (6.3) *before* shipping any rubric revision capability. This ordering is deliberate: the guardrails are useless retrofitted onto a shipped optimizer, because by then teachers have rubrics in production that were revised without them. This is also the earliest point at which the earned single-judge optimization in Section 8.3 becomes defensible, since it needs Phase 2's accumulated agreement history to justify it.

**Phase 3.5, ship the Assessment Package.** Once tuning exists (Phase 4 below) it is worth persisting, but the package format should land with Phase 1's persistence layer rather than being bolted on: even an untuned package saves re-uploading the test and reference solution for every cohort, and the validation record starts compounding from the first administration. Export and import as a single file (Section 9.4) is the piece to get right early, since retrofitting portability onto a database-shaped store is painful.

**Phase 4, ship elicitation.** Ambiguity discovery plus teacher-authored revision (6.4), gated by Phase 3's checks. By now you have Phase 2's accumulated labels to validate against, which is the sample regime where this technique actually has published support.

The temptation will be to build Phase 4 first, because it demos beautifully. Resist it. Phase 1 delivers most of the value, and Phase 4 without Phase 3 is the version of this system that quietly turns into a length detector.

**The three things that must be right on day one**, because each is expensive to retrofit and each silently invalidates accumulated data if it is wrong, are **version pinning** (Section 6.7), **judgment isolation** (Section 7.2), and **the provider abstraction with backend-scoped validation records** (Sections 0.7 and 8.7). The third joins the list in version 2.5 for the same reason the first two are on it: labels accumulated without recording which backend and build produced them cannot be repaired later, because the information was never captured. Everything else in this report can be added incrementally.

---

## 13. Source list

**Judge reliability, bias, and validation methodology**
- Norman, J. D., Rivera, M. U., & Hughes, D. A. (2026). *Reliability without Validity: A Systematic, Large-Scale Evaluation of LLM-as-a-Judge Models Across Agreement, Consistency, and Bias.* UC Berkeley School of Information. arXiv:2606.19544.
- Verga, P. et al. (2024, foundational, with 2025 to 2026 follow-ups). *Replacing Judges with Juries: Evaluating LLM Generations with a Panel of Diverse Models.* arXiv:2404.18796.
- Shi, L., Ma, C., Liang, W., et al. (2025). *Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge.* AACL-IJCNLP.
- Bavaresco, A. et al. (2025). *LLMs Instead of Human Judges? A Large-Scale Empirical Study Across 20 NLP Evaluation Tasks.* ACL.

**Education-specific automated scoring**
- Tian, Z. V., Liu, A., Esbenshade, L., Xiao, M., Zhang, Z., Lápicus, Y., Han, T., He, K., & Sun, M. (2026). *Creating and Evaluating K-12 GenAI Assessment Graders Through Context Engineering.* University of Washington / Colleague AI. arXiv:2606.12422.
- Tang, X., Ambrose, G. A., & Cheng, Y. (2026). *Designing Reliable LLM-Assisted Rubric Scoring for Constructed Responses: Evidence from Physics Exams.* University of Notre Dame. arXiv:2604.12227.
- Wang, Y., Ding, Z., Wu, X., Sun, S., Liu, N., & Zhai, X. (2026). *AutoSCORE: Enhancing Automated Scoring with Multi-Agent Large Language Models via Structured Component Recognition.* AAAI, 40, 40898–40906. arXiv:2509.21910.
- Frohn, S. (2026). *The Impact of LLM Self-Consistency and Reasoning Effort on Automated Scoring Accuracy and Cost.* Khan Academy. arXiv:2604.26954.
- Chu, Y., Li, H., Yang, K., Copur-Gencturk, Y., Krajcik, J., Shin, N., & Tang, J. (2026). *Confusion-Aware Rubric Optimization for LLM-Based Automated Grading.* arXiv:2603.00451.
- *Automated Refinement of Essay Scoring Rubrics for Language Models via Reflect-and-Revise.* (2025). arXiv:2510.09030.
- *CHiL(L)Grader: Calibrated Human-in-the-Loop Short-Answer Grading.* (2026). arXiv:2603.11957.
- Xue, M., Xiao, X., Liu, Y., & Wilson, M. (2026). *On the Consistency of Automatic Scoring with Large Language Models.* Educational and Psychological Measurement.

**Rubric design and evidence-grounded scoring**
- *From Rubrics to Reliable Scores: Evidence-Grounded Text Evaluation with RULERS.* (2026). arXiv:2601.08654.
- Rao, D. & Callison-Burch, C. (2026). *Autorubric: A Unified Framework for Rubric-Based LLM Evaluation.* University of Pennsylvania. arXiv:2603.00077.

**Open-source tooling**
- UK AI Security Institute. *Inspect AI: A Framework for Large Language Model Evaluations.* github.com/UKGovernmentBEIS/inspect_ai
- Confident AI. *DeepEval: The Open-Source LLM Evaluation Framework.* deepeval.com
- AutoRubric documentation. autorubric.org

**Local / open-source inference on Apple Silicon**
- Apple MLX framework documentation and mid-2026 Apple Silicon LLM performance comparisons (Ollama, MLX-LM, llama.cpp, LM Studio).

**Hosted inference for the cloud and CI profiles (Section 8.7)**
- OpenRouter. openrouter.ai — model catalog, provider routing and pinning, data-retention policy controls, and rate-limit documentation. Check the retention and routing controls directly against the account configuration rather than relying on documentation alone, since these are the controls R31 depends on.
- LiteLLM. docs.litellm.ai — provider-shim library used to implement the R27 `InferenceProvider` seam across local and hosted endpoints.

**Existing commercial reference platform**
- GradeWithAI. gradewithai.com (accessed July 2026).

**Education access and teacher supply (Section 0)**
- UNESCO / International Task Force on Teachers for Education 2030. *Closing the gap: Ensuring there are enough qualified and supported teachers in sub-Saharan Africa.* teachertaskforce.org
- UNESCO and Teacher Task Force (2024). *Global Report on Teachers: Addressing teacher shortages and transforming the profession.* Paris: UNESCO.
- UNESCO Institute for Statistics. *Pupil-teacher ratio indicators, primary and secondary.* uis.unesco.org
- UNESCO Conference on Education Data and Statistics (2024). *Teacher data: definitions, qualifications, and reporting.* uis.unesco.org

---

*This report reflects publicly available research current as of late July 2026. Given the pace of publication in this area, re-check the source list before treating any specific benchmark number as current beyond a few months.*
