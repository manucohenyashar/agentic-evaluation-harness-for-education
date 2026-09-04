"""The vocabulary `M-CONSOLE`'s rendering and honesty clauses are written against.

TS-77 (issue #132) implements `TC-CONSOLE-C13` … `-C24`, twelve of the twenty-four `CT-CONSOLE`
clause cases; #131 has the other twelve. Both are written ahead of six implementing stories
(#122 … #127), and this module is what stops them drifting apart from the design in the meantime:
the literals live here, transcribed, and `tests/contract/console/test_ct_console_vocabulary.py`
asserts them against the documents they came from.

**Those assertions are green and they are not coverage.** They check that *this fixture still
matches the design*, not that `M-CONSOLE` does anything. Read them as drift detection.

The invented surface, settled in one place
------------------------------------------
Design §3.19 has **no Python Interfaces block at all** — only prose, a route table and a
control-surface table. So unlike every other module in this repo, there is not one declared
callable to write a clause case against, and every name below is this suite's. They are written
down here rather than reinvented per file, because twelve cases each guessing a slightly different
shape is how a written-ahead suite becomes unimplementable::

**Module attributes**::

    CONSOLE_BIND, CONSOLE_PORT, CONSOLE_POLL_INTERVAL_MS   the three declared knobs

**Constructors and entry points**::

    build_console(cohort_size=..., provider=...)  -> ConsoleApp
    start_console(cfg)                            -> raises ConsoleBindRefused under `cloud-hosted`
    render_review_queue(app, run_id)              -> RenderedPage    (#124)
    render_rollup(app, run_id)                    -> RenderedPage    (#125)
    render_submission_text(app, text=...)         -> RenderedPage + .refused   (#127)
    review_queue_header(page)                     -> {flagged, shown, left_provisional}   (#124)
    blind_flow(run_id=..., submission_ref=...)    -> .queries, .transport_payloads, .submitted
    touchpoint_surface(app)                       -> Mapping[str, TouchpointRender]        (#125)
    amend_finalized_grade(app, ...)               -> a new grade revision                  (#125)
    export_package(app, ...)                      -> raises ProvenanceRefused at the gate  (#125)
    upload_scans(app, cohort_id=..., size_bytes=...) -> UploadOutcome                      (#122)

**Types**::

    ConsoleApp
        .routes()             -> Mapping[str, tuple[str, ...]]   surface -> routes
        .write_surface()      -> tuple[str, ...]   FR-CONSOLE-32's enumeration
        .read_surface()       -> tuple[str, ...]   the stores/tables it reads
        .actual_couplings()   -> tuple[str, ...]   everything it really touches (CT-CONSOLE-21)
        .telemetry()          -> Mapping[str, tuple[str, ...]]   metric -> dimensions
        .telemetry_values(metric, dimension=...) -> the values emitted for that dimension
        .audit_routes()       -> tuple[str, ...]   the surfaces CT-CONSOLE-23 sweeps
        .bind_address         -> str
        .render(route, **params) -> RenderedPage
        .finalize_batch(run_id=..., actor=...)   -> Mapping[submission_ref, Grade]
        .set_review_window(run_id=..., hours=...)
        .export_grades(run_id=...)               -> rows carrying `.provisional`
        .grade_revision(submission_ref=..., revision=...) -> Grade | None
        .validation_record(package_version=...)  -> .provenance_gate_outcome
    RenderedPage        -> .html, .queries, .poll_interval_ms
    Grade               -> .finalized_at, .revision, .bands
    UploadOutcome       -> .dispatched, .blob_refs, .staged_in_browser
    TouchpointRender    -> .implemented, .present, .available, .available_in_version
    ConsoleBindRefused, ProvenanceRefused

**Required markup.** The rendering clauses assert *where* things appear, so the region markers are
part of the invented surface too: `narrative`, `mark`, `group-actions`, `item-actions` and
`review-item`, each on the element's `id`, `class` or `data-role`.

Durations and memory are **measured by the tests**, not read off these objects — a figure the code
under test reports about itself is a claim, not a measurement — so `RenderedPage` carries no
`duration_seconds` and `UploadOutcome` no memory field.

Whoever implements #122 … #127 adopts these names or renames in both places. Checked: none of
them appears anywhere in either design document or the HLD.
"""

from __future__ import annotations

import os
import re
from typing import Any

# --- HLD §7.9's touchpoint inventory (CT-CONSOLE-17) --------------------------------------------
#
# `FR-CONSOLE-25` / `R72`: *"Every teacher touchpoint in §7.9's inventory is either implemented in
# the interface or rendered as present-and-unavailable, naming the version in which it arrives. No
# touchpoint is silently absent."*
#
# §6.11.18's instruction is that the sweep is **enumerated against §7.9 rather than sampled**, so
# the inventory is transcribed in full — twelve rows, in the document's order — and the vocabulary
# test asserts each one is still in the HLD table. A sampled sweep would pass while the touchpoint
# nobody sampled was silently absent, which is the exact failure the clause names.
#
# The value is the `Blocks grades?` column, because `R60` and `CT-CONSOLE-07` both turn on it:
# **exactly two** setup items block and nothing in the recurring run does.
TEACHER_TOUCHPOINTS: dict[str, bool] = {
    "Confirm the question inventory": True,
    "Supply multiple-choice answer keys": True,
    "Approve how the rubric was understood": False,
    "Confirm decomposability classifications": False,
    "Declare the grade policy and boundaries": False,
    "Answer ambiguity-elicitation questions": False,
    "Mark 10 to 15 calibration papers": False,
    "Work the review queue": False,
    "Blind sample": False,
    "Whole-grade sample": False,
    "Finalize the batch": False,
    "Drift check on package reuse": False,
}

#: The two that block, named so a regression says *which*. `R60`'s test — *"could a teacher start a
#: run, do nothing at all, and still have every student graded the next morning?"* — is false the
#: moment a third one appears.
BLOCKING_TOUCHPOINTS: frozenset[str] = frozenset(
    {"Confirm the question inventory", "Supply multiple-choice answer keys"}
)

#: The one touchpoint the MVP does **not** implement, named in HLD §11.2 and §11.9: *"The life
#: cycle this console executes is §7.9's inventory minus one touchpoint."*
#:
#: This is what makes `CT-CONSOLE-17` a real case rather than a tautology. If every touchpoint were
#: implemented, "either implemented or rendered present-and-unavailable" would be satisfied by the
#: first half alone and the clause would assert nothing. Exactly one row must take the second
#: branch, and it is this one — so the case asserts the branch is taken, with a version named.
MVP_ABSENT_TOUCHPOINT = "Answer ambiguity-elicitation questions"

# --- HLD §11.8's control surface (CT-CONSOLE-21's coupling half) ---------------------------------
#
# `FR-CONSOLE-32`: *"The console's write surface shall be exactly the enumerated control-surface
# actions of HLD §11.8 and shall be enumerable at runtime, so a test can assert no undeclared write
# path exists."* Design §3.19 repeats the list in prose; this is that list.
#
# `CT-CONSOLE-21`'s durable half is that the console is *"replaceable without touching the harness
# — the seam is that it only reads stores and writes the enumerated control rows"*. That seam is
# only assertable if the enumeration is fixed, which is why it is transcribed rather than read from
# the implementation.
CONTROL_SURFACE_ACTIONS: tuple[str, ...] = (
    "approve question inventory",
    "supply answer keys",
    "accept or correct rubric read-back",
    "set review window",
    "start run",
    "pause/resume",
    "resolve quarantine item",
    "review action",
    "blind-sample submission",
    "correct an answer key after a run",
    "finalize batch",
    "amend a finalized grade",
    "approve exemplar paraphrases at export",
    "export/import package",
    "purge cohort",
)

#: Design §3.19's route table, split by surface. `CT-CONSOLE-17`'s sweep needs the routes to know
#: what "a reachable screen" means, and `CT-CONSOLE-16` asserts the provenance gate is one.
TEACHER_ROUTES: tuple[str, ...] = (
    "/packages",
    "/packages/new",
    "/setup/*",
    "/runs/{id}/review",
    "/runs/{id}/blind",
    "/runs/{id}/sample",
    "/runs/{id}/rollup",
    "/students/{ref}",
)
OPERATOR_ROUTES: tuple[str, ...] = (
    "/cohorts",
    "/cohorts/{id}/preflight",
    "/runs/{id}/monitor",
    "/quarantine",
)

# --- CT-CONSOLE-19 and -20: the numbers -----------------------------------------------------------
#
# `NFR-CONSOLE-01`: *"The review queue shall render within 2 seconds and the rollup within 3 seconds
# for a 350-student run, because both are opened inside a fixed time budget."* The reason is the
# assertion's justification: render time comes straight out of the teacher's review minutes.
REVIEW_QUEUE_BUDGET_SECONDS = 2.0
ROLLUP_BUDGET_SECONDS = 3.0
REFERENCE_COHORT_SIZE = 350

#: Design §3.19's Configuration line, verbatim: *"`CONSOLE_BIND` (127.0.0.1), `CONSOLE_PORT`,
#: `CONSOLE_POLL_INTERVAL_MS` (3000)."*
#:
#: `CONSOLE_PORT` has **no declared default** and that is transcribed as `None` rather than guessed.
#: Inventing 8080 here would make it the requirement the first time somebody hit it — the same
#: reasoning `conf_builders.default_retention_setting` documents.
CONSOLE_KNOBS: dict[str, object] = {
    "CONSOLE_BIND": "127.0.0.1",
    "CONSOLE_PORT": None,
    "CONSOLE_POLL_INTERVAL_MS": 3000,
}

#: `CT-CONSOLE-20`'s adversarial value: a routable address, which an operator would set to "make it
#: work from the other machine". The clause is explicit that setting it must **not** defeat
#: `CT-CONSOLE-05`'s refusal, because the refusal keys on the deployment profile rather than on the
#: bind address. A knob that could switch off a security refusal would make the refusal advisory.
ROUTABLE_BIND = "0.0.0.0"

# --- CT-CONSOLE-22: observability ------------------------------------------------------------------
#
# Design §3.19: *"Page render times, control actions by type, skip rates per optional setup step,
# review budget requested versus used."*
RENDER_TIME_METRIC = "page_render_time"
CONTROL_ACTION_METRIC = "control_actions_by_type"
SKIP_RATE_METRIC = "skip_rate_per_setup_step"
REVIEW_BUDGET_METRIC = "review_budget_requested_vs_used"

OBSERVABILITY_METRICS: frozenset[str] = frozenset(
    {RENDER_TIME_METRIC, CONTROL_ACTION_METRIC, SKIP_RATE_METRIC, REVIEW_BUDGET_METRIC}
)

#: The optional setup steps the skip rate must be broken down by. Every §7.9 touchpoint that does
#: **not** block and is part of setup — which is what "optional setup step" means, since a blocking
#: step cannot be skipped and a per-run step is not setup.
#:
#: `CT-CONSOLE-22` says the skip rates are *"the pilot's actual instrument for HLD §11.9's six
#: questions, which is why they are contract rather than incidental telemetry"*, and §6.11.19 adds
#: that they must be emitted **per step**: an aggregate skip rate cannot answer any of the six.
OPTIONAL_SETUP_STEPS: tuple[str, ...] = (
    "Approve how the rubric was understood",
    "Confirm decomposability classifications",
    "Declare the grade policy and boundaries",
    "Answer ambiguity-elicitation questions",
    "Mark 10 to 15 calibration papers",
)

#: HLD §11.9's six pilot questions, by the phrase each turns on. Transcribed so `CT-CONSOLE-22`'s
#: "instrument for the six questions" is checkable rather than rhetorical — and because the HLD's
#: own prose calls them *"those five answers"* directly under a list of six, which is the kind of
#: drift a transcription check is for.
PILOT_QUESTIONS: tuple[str, ...] = (
    "minute-budget",
    "group actions",
    "band-only",
    "residual message",
    "operator / teacher split",
    "rubric findings",
)

# --- CT-CONSOLE-13: what a narrative may not say ----------------------------------------------------
#
# `FR-CONSOLE-15`: *"Narrative shall render before the mark, and narrative text shall contain no
# numeral-bearing or overall-quality claim."*
#
# **A narrative legitimately contains numerals.** It cites question numbers, line numbers, dates and
# quantities from the student's own work — *"in Question 4, the calculation on line 12"* is exactly
# the evidence-grounded narrative the design wants. What is forbidden is a numeral **denoting a
# score**. A detector that condemned every digit would fail correct copy and be switched off by
# whoever hit it first, which is the failure TS-74 shipped twice.
#
# So the rule is scoped: a numeral adjacent to scoring vocabulary, or a mark-shaped construction.
#: `FR-CONSOLE-15` forbids a **numeral-bearing score claim**, and the rule matches score
#: *constructions* rather than a scoring word plus a digit anywhere in the sentence.
#:
#: Review measured the word-plus-digit version condemning four realistic narratives: *"the answer
#: **points** to 3 possible causes"*, *"the frequency **band** around 400 Hz"*, *"the student
#: **remarks** in line 4"*, *"the graph is **poorly** scaled"*. Every one is evidence-grounded copy
#: a correct console would render, and a rule that fails correct copy is a rule somebody switches
#: off. Constructions separate them: *"7 out of 10"* is a mark and *"3 possible causes"* is not,
#: whatever words surround either.
_SCORE_PATTERNS: tuple[str, ...] = (
    # "7 out of 10", "7/10", "8 of 10"
    r"\b\d+(?:\.\d+)?\s*(?:/|out of|of)\s*\d+",
    # a scoring verb with a numeral in reach: "scored 7", "awarded 7 of a possible 10"
    r"\b(?:scored|scores|scoring|marked|graded|awarded|earns|earned)\b[^.]{0,40}\d",
    # a numeral carrying a scoring unit: "8 points", "3 marks", "70 percent"
    r"\b\d+(?:\.\d+)?\s*(?:points?|marks?|percent)\b",
    r"\d+\s*%",
)

_OVERALL_QUALITY_CLAIMS = (
    "excellent",
    "outstanding",
    "poor",
    "weak overall",
    "strong overall",
    "good work",
    "well done",
    "overall quality",
    "overall this",
    "high quality",
    "low quality",
    "satisfactory",
    "unsatisfactory",
)

#: **Matched on word boundaries, not as substrings.** Review measured four realistic
#: evidence-grounded narratives condemned: *"the student **remarks**"*, *"the answer **points** to
#: 3 causes"*, *"the graph is **poorly** scaled"*, *"the frequency **band** around 400 Hz"*. Every
#: one is copy a correct console renders, and a rule that fails correct copy gets switched off —
#: which is the failure mode that matters here, since `CT-SYNTH-14` already keeps the mark out of
#: the narrative upstream and this rule is the console-side second check.
_SCORE_CLAIM = re.compile("|".join(_SCORE_PATTERNS))

#: Overall-quality claims stay word-matched, on boundaries: `poorly` is not `poor`.
_OVERALL_CLAIMS = re.compile(
    r"\b(?:" + "|".join(re.escape(claim) for claim in _OVERALL_QUALITY_CLAIMS) + r")\b"
)


def forbidden_narrative_claims(text: str) -> list[str]:
    """The sentences in `text` a narrative may not contain (`FR-CONSOLE-15`).

    Two kinds, both returned so a failure names which: a **numeral-bearing score claim** — a digit
    in the company of scoring vocabulary — and an **overall-quality claim**.

    Deliberately *not* "any sentence with a digit in it". `"The calculation on line 12 of Question
    4 omits the units"` is a correct narrative and must pass; `"scored 7 out of 10"` must not. Both
    directions have controls in `test_ct_console_vocabulary.py`, because a rule with only the
    catching half is a rule that fails correct copy.
    """
    hits: list[str] = []
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if _SCORE_CLAIM.search(lowered):
            hits.append(sentence)
        elif _OVERALL_CLAIMS.search(lowered):
            hits.append(sentence)
    return hits


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[.!?\n]+", text) if part.strip()]


# --- CT-CONSOLE-23: what an actor string may not be presented as -------------------------------------
#
# *"Consumers must not treat any console action as attributable to a specific person beyond the
# actor string a form supplies."* §6.11.19: sweep the audit surface and assert nothing presents an
# actor string as an authenticated identity — *"a `finalized_by` rendered as proof of who acted
# would be a false claim in a dispute (RISK-12)"*.
#
# **A correct console still renders `finalized_by`.** It has to: the audit record exists and the
# actor string is what the form supplied. What it may not do is present that string as *verified*.
# So this is a claim sweep with a negation filter, the same shape as TS-75's equivalence sweep —
# and for the same reason, since the honest rendering says the words the naive net forbids.
AUTHENTICATED_IDENTITY_TERMS: tuple[str, ...] = (
    "authenticated",
    "verified identity",
    "verified user",
    "signed in as",
    "logged in as",
    "confirmed identity",
    "identity verified",
    "proof of who",
    "authenticated user",
)

_IDENTITY_NEGATIONS: tuple[str, ...] = (
    "not ",
    "no ",
    "never",
    "cannot",
    "unverified",
    "unauthenticated",
    "self-declared",
    "self declared",
    "as supplied",
    "does not",
    "is not",
    "without",
    "none",
)


def authenticated_identity_claims(text: str) -> list[str]:
    """Sentences that present an actor string as an authenticated identity.

    The negation filter is what keeps the honest rendering — *"`finalized_by` is a self-declared
    actor string and is not an authenticated identity"* — from being reported as the violation it
    warns about.
    """
    hits: list[str] = []
    for sentence in _sentences(text):
        for clause in _clauses(sentence):
            lowered = clause.lower()
            if not any(term in lowered for term in AUTHENTICATED_IDENTITY_TERMS):
                continue
            if any(negation in lowered for negation in _IDENTITY_NEGATIONS):
                continue
            hits.append(sentence.strip())
            break
    return hits


def _clauses(sentence: str) -> list[str]:
    """A sentence split at the punctuation that separates independent claims.

    **The negation filter has to be scoped or it disarms the sweep.** Review measured a realistic
    audit page — a table of rows, one of which said "no items" — swallowing the whole sweep,
    because `visible_text` joined the rows into one segment, `_sentences` found no full stop, and
    a single bare "no " anywhere in it exempted the lot. On a table-shaped page, which is what an
    audit surface is, the sweep reported nothing whatever the page claimed.

    So the negation must sit in the **same clause** as the term it is meant to negate. A row
    saying "no items" no longer excuses a different row saying "the authenticated user".
    """
    return [part for part in re.split(r"[;:,\u2014\u2013]|\s\u00b7\s|\n", sentence) if part.strip()]


# --- CT-CONSOLE-24: the non-promise, and what "visibly" means ------------------------------------------
#
# `NFR-CONSOLE-07`: *"English and left-to-right only in the MVP, stated as a deliberate limitation
# rather than an oversight."* §6.11.19: feed non-English and RTL content through and assert the
# system *"fails or degrades **visibly** rather than rendering mojibake or silently reversing text
# in a way a monolingual operator would not notice"*.
#
# **"Visibly" has to be a checkable predicate or the case asserts nothing.** Almost any output is
# "not byte-identical mojibake", so a test phrased as the absence of mojibake passes on essentially
# everything. So the three acceptable outcomes are enumerated: the system raises, or it renders a
# warning naming the limitation, or it refuses the input. Anything else — including a page that
# renders the text and says nothing — is the silent degradation the clause is about.
#: **Phrases, not words.** Review measured the first version passing on any page containing the
#: word "english" — which is the likeliest subject name in the pilot, so an English paper carrying
#: silently-reversed Arabic satisfied the predicate. `"ltr"` was worse: it matched inside
#: "u**ltr**a-wide". Each marker below is a phrase a page would only carry deliberately.
VISIBLE_DEGRADATION_MARKERS: tuple[str, ...] = (
    "left-to-right only",
    "left to right only",
    "english only",
    "english and left-to-right",
    "right-to-left text",
    "right to left text",
    "not supported",
    "unsupported",
    "cannot render",
    "may be misordered",
    "shown unstyled",
)

#: The classic UTF-8-decoded-as-Latin-1 signature, plus the replacement character. Present in a
#: rendering means mojibake reached the page; the clause forbids that outcome regardless of
#: whether a warning was also shown.
#:
#: `"×"` (U+00D7) was in the first version and is gone: neither probe is Hebrew, so it could never
#: fire as a true positive, while `"1024 × 768"` on a crop view and `"3 × 4"` in a narrative fire
#: it. A marker that cannot catch what it is for and can catch what it is not is pure false
#: positive.
MOJIBAKE_MARKERS: tuple[str, ...] = ("�", "Ã¢", "Ã©", "Ã¨", "Ø§Ù", "â€")

#: Non-English and RTL probes. Arabic and Hebrew because §0.2's deployment context is the reason
#: the clause says localisation is *"a real later requirement"* rather than a hypothetical.
RTL_PROBE = "المدرسة الثانوية — إجابة الطالب"
NON_ENGLISH_LTR_PROBE = "Élève: réponse à la question numéro quatre"


def visibly_degraded(rendered: str, raised: BaseException | None, refused: bool) -> bool:
    """Did the system fail or degrade **visibly** on non-English or RTL input?

    The disjunction the clause allows, made checkable: it raised, or it refused, or the rendering
    names the limitation. A page that shows the text and says nothing satisfies none of the three
    and is the failure `CT-CONSOLE-24` exists to make visible.
    """
    if raised is not None or refused:
        return True
    lowered = rendered.lower()
    return any(marker in lowered for marker in VISIBLE_DEGRADATION_MARKERS)


# --- CT-CONSOLE-18: the upload, sized by a knob -------------------------------------------------------
#
# The clause is explicit that *"hundreds of megabytes of scans are a normal upload, not an edge
# case"*, and §6.11.19 asks for peak RSS during a multi-hundred-megabyte upload. That size cannot
# live in the contract tier's 60-second budget and it cannot be hard-coded either: a constant
# calibrated for one machine becomes a phantom failure on every other one (`CLAUDE.md`, seam 3).
#
# So the size is an env-gated knob with the production-shaped value as its default, and the
# assertion is a **ratio** rather than an absolute — an implementation that streams uses memory
# proportional to its buffer, not to the upload.
UPLOAD_PROBE_BYTES = int(os.environ.get("HARNESS_CONSOLE_UPLOAD_PROBE_BYTES", 300 * 1024 * 1024))

#: Peak memory may not exceed this fraction of the upload. A streaming implementation is far
#: under it; one that buffers the batch in memory is at or above 1.0 by construction.
UPLOAD_RSS_RATIO_CEILING = 0.25

#: …but never less than this in absolute terms. The knob above exists so a slower box can shrink
#: the probe, and at a small probe a pure ratio is blown by any incidental allocation — the knob
#: added to prevent a phantom failure would then cause one. The ceiling is the larger of the two.
MEMORY_FLOOR_BYTES = 8 * 1024 * 1024

#: `CT-CONSOLE-18`'s other half, and the one that catches the common bug: a handler that *awaits*
#: the work rather than dispatching it. Independent of the memory question — an implementation can
#: stream to disk and still block the request for four minutes.
HANDLER_BUDGET_SECONDS = 1.0


def _identifying_tokens(attrs: list[tuple[str, Any]]) -> set[str]:
    """The tokens of an element's `id`, `class` and `data-role` — the three that name a region.

    Deliberately narrow. Reading every attribute means an unrelated `data-contains`, `aria-label`
    or `title` can make an element answer to a marker it does not carry, and the ordering and
    slicing helpers built on this are both assertions about *which element* something is.
    """
    tokens: set[str] = set()
    for name, value in attrs:
        if name in ("id", "class", "data-role") and value:
            tokens.update(str(value).split())
    return tokens


def dom_order(html: str, *markers: str) -> list[int]:
    """The document order of `markers`, by element rather than by substring.

    `CT-CONSOLE-13` asserts *"narrative renders **before** the mark"* and *"group actions render
    **above** per-item actions"*, and §6.11.19 calls for a DOM-order assertion — because the
    ordering is the thing that shapes judgment: a narrative shown after the mark is read as
    justification for it rather than as evidence.

    Parsed rather than `str.find`, which breaks the moment one of the markers appears inside an
    attribute value — a `data-role="mark"` on a wrapper would put "the mark" before the narrative
    it contains.

    Matched against `id`, `class` and `data-role` **only**, and by token equality. An earlier
    version read every attribute and used substring containment, which made a wrapper carrying
    `data-contains="mark narrative"` register both markers at the wrapper — so an ordering
    assertion passed on the wrapper's attribute rather than on the elements. Found by
    `element_text`'s control, not by this function's own test, which is the argument for giving
    every helper one.
    """
    from html.parser import HTMLParser

    class _Order(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.seen: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            tokens = _identifying_tokens(attrs)
            matched = [marker for marker in markers if marker in tokens]
            # An element naming **two** of the markers is a wrapper around both, not either of
            # them, so it establishes no order between them. Appending both would establish the
            # order they were asked in, which is how an ordering assertion passes on its own
            # argument list rather than on the document.
            if len(matched) == 1:
                self.seen.append(matched[0])

    parser = _Order()
    parser.feed(html)
    return [parser.seen.index(m) if m in parser.seen else -1 for m in markers]


def elements(html: str, marker: str) -> list[str]:
    """The outer HTML of **every** element carrying `marker`, in document order.

    `dom_order` and `element_text` both take the *first* match, which is right when the caller
    means "the narrative of this item" and wrong when the clause is universal. `CT-CONSOLE-13` says
    narrative renders before the mark — of every item — and review measured a page-level check
    passing on a queue whose first item was correct and whose fifth was inverted.

    So the ordering and content sweeps iterate `elements(html, "review-item")` and assert inside
    each, which is the same "enumerated, not sampled" discipline `CT-CONSOLE-17` applies to
    touchpoints.
    """
    from html.parser import HTMLParser

    class _Collect(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.found: list[str] = []
            self.depth = 0
            self.start = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
            if self.depth:
                if tag not in _VOID_TAGS:
                    self.depth += 1
                return
            if marker in _identifying_tokens(attrs):
                self.depth = 1
                self.start = self.getpos_offset()

        def handle_endtag(self, tag: str) -> None:
            if not self.depth or tag in _VOID_TAGS:
                return
            self.depth -= 1
            if self.depth == 0:
                end = self.getpos_offset() + len(f"</{tag}>")
                self.found.append(html[self.start : end])

        def getpos_offset(self) -> int:
            line, column = self.getpos()
            return sum(len(part) + 1 for part in html.split("\n")[: line - 1]) + column

    parser = _Collect()
    parser.feed(html)
    return parser.found


def visible_text(html: str) -> str:
    """The rendered text of `html`, with tags and attributes removed.

    The claim sweeps in this suite are about what a **reader** sees. Running them over raw markup
    would let a class name or a template comment trip a rule, and would let real copy hide inside
    an attribute the sweep never reads.

    **Block elements are separated by a full stop, not a space**, and that is load-bearing rather
    than cosmetic. Review measured `CT-CONSOLE-23`'s sweep going vacuous on a table-shaped audit
    page: joined by spaces, the whole table became one "sentence", and one row saying "no items"
    exempted every other row from the negation filter. An audit surface *is* a table, so that was
    the shape the case would actually have run on. A block boundary is a sentence boundary to a
    reader, and now to the sweep.
    """
    from html.parser import HTMLParser

    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []

        def _break(self) -> None:
            if self.parts and self.parts[-1] != _BLOCK_BREAK:
                self.parts.append(_BLOCK_BREAK)

        def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
            if tag in _BLOCK_TAGS:
                self._break()

        def handle_endtag(self, tag: str) -> None:
            if tag in _BLOCK_TAGS:
                self._break()

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    parser = _Text()
    parser.feed(html)
    joined = " ".join(" ".join(parser.parts).split())
    # Collapse the markers into single terminators and tidy the ones that landed beside real
    # punctuation, so the result reads like a page rather than like a parser's output.
    joined = re.sub(rf"(?:\s*{re.escape(_BLOCK_BREAK)}\s*)+", ". ", joined)
    return re.sub(r"\s*\.\s*\.", ".", joined).strip(" .") + ("." if joined.strip(" .") else "")


def coupling_surface(app: Any) -> set[str]:
    """Everything `M-CONSOLE` touches: what it reads, plus what it is declared to write.

    `NFR-CONSOLE-05` / `CT-CONSOLE-21`: *"the console shall be replaceable without touching the
    harness; the seam is that it only reads stores and writes the enumerated control rows."* That
    is a claim about a **set**, so the case asserts the set — a second console could be written
    against exactly this and nothing else.
    """
    return set(app.read_surface()) | set(app.write_surface())


#: The tags that end a line for a reader. A page's structure is its punctuation.
_BLOCK_TAGS: frozenset[str] = frozenset(
    {
        "p", "div", "section", "article", "aside", "header", "footer", "main", "nav",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li", "dl", "dt", "dd",
        "table", "thead", "tbody", "tfoot", "tr", "td", "th",
        "form", "fieldset", "legend", "label", "figure", "figcaption", "blockquote", "pre", "br",
    }
)

#: Elements that never have an end tag. `_Slice` counts nesting depth to know where an element
#: stops, and a `<br>` or an `<img>` inside it increments a depth that never comes back down — so
#: the slice runs to the end of the document. Review measured exactly that: an `<img>` crop inside
#: a review item (which is what S8 renders) made `element_text(..., "narrative")` swallow the mark,
#: reintroducing the precise failure the slice exists to prevent.
_VOID_TAGS: frozenset[str] = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)

_BLOCK_BREAK = "␞"  # a symbol no page renders, so it cannot arrive in the input


def element_text(html: str, marker: str) -> str:
    """The visible text inside the element whose `id`, `class` or `data-role` carries `marker`.

    `CT-CONSOLE-13` asserts something about the **narrative specifically** — that it carries no
    numeral-bearing or overall-quality claim — not about the page. Running the rule over the whole
    rendering would sweep the mark itself, which is a numeral in scoring company by definition, and
    every correct review item would fail.

    Kept here rather than as a field on `RenderedPage` so the invented surface stays the one the
    module docstring declares: a test that needed `.narrative_text` would be inventing a
    thirteenth attribute for one assertion, and twelve cases each doing that is how a
    written-ahead suite stops being implementable.
    """
    from html.parser import HTMLParser

    class _Slice(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.depth = 0
            self.inside = False
            self.parts: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
            if self.inside:
                # A void element has no end tag, so counting it would leave the depth permanently
                # raised and the slice would never close.
                if tag not in _VOID_TAGS:
                    self.depth += 1
                return
            if marker in _identifying_tokens(attrs):
                self.inside = True
                self.depth = 1

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
            # `<br/>`, XHTML style. `HTMLParser` routes these here and never calls `handle_endtag`,
            # so the base class's default of "start then end" would also unbalance the count.
            if not self.inside and marker in _identifying_tokens(attrs):
                self.inside = True
                self.depth = 1

        def handle_endtag(self, tag: str) -> None:
            if not self.inside or tag in _VOID_TAGS:
                return
            self.depth -= 1
            if self.depth <= 0:
                self.inside = False

        def handle_data(self, data: str) -> None:
            if self.inside:
                self.parts.append(data)

    parser = _Slice()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())
