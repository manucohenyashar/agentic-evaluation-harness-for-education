"""The vocabulary `M-CONSOLE`'s security, isolation and prohibition clauses are written against.

TS-76 (issue #131) implements `TC-CONSOLE-C01` … `-C12`; TS-77 has `-C13` … `-C24` and settled the
base surface in :mod:`tests.support.console_vocabulary`. **That module is where the invented
`M-CONSOLE` surface is declared**, and nothing here contradicts it — this file adds the names the
first twelve clauses need and nothing else, so the two suites cannot drift into two different
consoles. Read its docstring first.

Design §3.19 has **no Python Interfaces block at all**, so every name below is invented. Checked:
none appears in `docs/design/detailed-design.md`, `docs/design/test-plan.md` or the HLD.

Additions to the invented surface
---------------------------------
**Entry points**::

    serve_console(cfg)                -> ConsoleServer, or raises ConsoleBindRefused   (#122)
    build_console(store=..., ...)     -> ConsoleApp, now taking an injected store      (#122)

**Types**::

    ConsoleServer
        .bind_address        -> str            the *configured* value
        .socket              -> socket.socket  the **actually bound** socket
        .pid                 -> int | None     None when served in-process
        .terminate()         -> None
    ConsoleApp
        .control_actions()   -> Mapping[str, Callable]   FR-CONSOLE-32's runtime enumeration
        .perform(action, **params)   -> ControlOutcome
        .screens()           -> Mapping[str, str]        screen id -> route
        .blocking_screens()  -> tuple[str, ...]
        .progress(run_id=...)        -> ProgressReport
        .api_payload(route, **params)-> Mapping[str, Any]
        .review_queue(run_id=...)    -> QueueView
        .quarantine(cohort_id=...)   -> QueueView
    ControlOutcome  -> .rows_written, .refused, .refresh_required, .dispatched
    ProgressReport  -> the `CT-ORCH-10` shape, rendered
    QueueView       -> .route, .queries, .ranked, and **`.queue`, which is `M-REVIEW`'s own
                       declared `ReviewQueue`** — `budget_minutes`, `reserved_for_blind_minutes`,
                       `flagged_total`, `shown`, `residual_provisional` (design §3.16)

`QueueView` wraps rather than restates, and that is deliberate. `ReviewQueue` is one of the few
things in `M-CONSOLE`'s neighbourhood the design *does* declare, and `CT-REVIEW-02` names
`reserved_for_blind_minutes` as the field that *"states the subtraction"*. Inventing a parallel
`reserved_for_blind` would have made the console's view of the budget a second source of truth for
the one number `CT-CONSOLE-12`'s ordering half turns on. What is added here is only what is the
console's own: the route it served from, the queries it issued, and the ranked order it rendered.

Everything else — `RenderedPage`, `Grade`, `UploadOutcome`, `ConsoleBindRefused`, the region
markers — is `console_vocabulary`'s and is imported from there rather than restated.

Why the rules here are shaped the way they are
----------------------------------------------
Every rule below is a **claim detector**, and TS-74 and TS-77 both shipped detectors that failed
correct copy before review caught them. So each one is scoped to the thing the clause forbids
rather than to the vocabulary that surrounds it, and each has controls in **both** directions in
`tests/support/broken_console_security_fixtures.py`:

* `numeric_score_entry_fields` must not condemn the review queue's **minutes budget** input, which
  HLD §10 requires, nor S2's page numbers, nor S6's cohort size. `FR-CONSOLE-07` forbids a numeric
  *score* field, not a numeric field.
* `per_student_progress_figures` must not condemn **S13 Student detail**, which is a declared
  teacher route (`/students/{ref}`). `FR-CONSOLE-08` forbids a per-student *progress indicator
  during a run*, not a per-student view.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Iterable

from tests.support.console_vocabulary import (
    CONTROL_SURFACE_ACTIONS,
    _identifying_tokens,  # noqa: F401  (re-exported deliberately; see `form_controls`)
    visible_text,
)

# --- HLD §9.9: the fields a scoring prompt reads (CT-CONSOLE-04) --------------------------------
#
# `ScoringRequest`, leaf by leaf, dotted. Transcribed rather than sampled because §6.11.19 says the
# empty intersection is *"stronger than sampling prompts"* — and an intersection is only stronger
# than a sample if both sides are complete.
#
# `CT-JUDGE-02` calls this schema **closed**: *"Adding a field is a schema change, not a call-site
# change."* That is what makes the set comparison legitimate; against an open schema it would be a
# snapshot of today's prompt.
SCORING_PROMPT_FIELDS: frozenset[str] = frozenset(
    {
        "work_id",
        "criterion.criterion_id",
        "criterion.text",
        "criterion.bands.band",
        "criterion.bands.descriptor",
        "criterion.exemplars.band",
        "criterion.exemplars.text",
        "question.prompt_text",
        "question.reference_solution",
        "evidence.spans",
        "dependency_evidence",
        "submission_text",
    }
)

# --- HLD §11.8's Effect column, field by field (CT-CONSOLE-02, -04) ------------------------------
#
# `console_vocabulary.CONTROL_SURFACE_ACTIONS` carries the fifteen action **names** and the
# vocabulary test already checks that transcription against the HLD. This is the other column: what
# each action actually writes, at **field** granularity rather than table granularity.
#
# The granularity is the whole case. `exemplar.provenance` is written at export and
# `exemplar.text` is read by the prompt; `criterion.answer_key` is written after a run and
# `criterion.text` is read by the prompt. Both are the same table. An intersection computed over
# table names reports a violation against a console that has none.
CONSOLE_WRITE_FIELDS: dict[str, tuple[str, ...]] = {
    "approve question inventory": ("question.question_id", "question.prompt_text", "question.order"),
    "supply answer keys": ("criterion.answer_key",),
    "accept or correct rubric read-back": (
        "criterion.text",
        "criterion.decomposable",
        "criterion_band.band",
        "criterion_band.descriptor",
        "grade_policy.rule",
        "grade_boundary.cut",
    ),
    "set review window": ("grade_policy.review_window_hours",),
    "start run": ("run.run_id", "run.status"),
    "pause/resume": ("run.status",),
    "resolve quarantine item": ("submission.ingest_status",),
    "review action": (
        "review_queue.action",
        "review_queue.new_band",
        "review_queue.acted_at",
        "label.label_type",
        "label.band",
    ),
    "blind-sample submission": ("label.label_type", "label.band"),
    "correct an answer key after a run": ("criterion.answer_key",),
    "finalize batch": ("submission_grade.finalized_at", "audit_record.actor"),
    "amend a finalized grade": (
        "submission_grade.revision",
        "submission_grade.bands",
        "audit_record.actor",
    ),
    "approve exemplar paraphrases at export": (
        "exemplar.provenance",
        "package.contains_real_student_text",
    ),
    "export/import package": ("package_file.path",),
    "purge cohort": ("cohort.purged_at",),
}

#: The three actions §11.8 places **before any scoring exists**, inside the §6.2 lock.
#:
#: This is the scoping `CT-CONSOLE-04` needs and it is not invented for the test — HLD §11.1 states
#: it outright: *"nothing it writes is visible to a judge at inference time… Teacher review actions
#: are written **after** scoring"*, and §11.8's rubric row says the read-back correction is
#: *"correction of the read-back before any scoring exists, inside the §6.2 lock — not the
#: rubric-revision surface §11.2 excludes"*.
#:
#: Read literally and without this scope, the clause is unsatisfiable by §11.8's own table: the
#: read-back writes `criterion.text` and `criterion_band.descriptor`, both of which a scoring prompt
#: reads. The contamination rule `R15` protects is about a field a *later judgment* could pick up,
#: and a pre-lock write cannot be one, because the lock is what stops the value changing under a
#: run. So the assertable form is: **post-lock write set ∩ scoring-prompt read set = ∅.**
PRE_LOCK_ACTIONS: frozenset[str] = frozenset(
    {
        "approve question inventory",
        "supply answer keys",
        "accept or correct rubric read-back",
    }
)


def post_lock_write_fields(
    write_fields: dict[str, tuple[str, ...]] | None = None,
) -> frozenset[str]:
    """Every field the console writes **after** the §6.2 lock, across all fifteen actions.

    Non-empty by construction — `criterion.answer_key` is written post-lock by *"correct an answer
    key after a run"*, and it is the case's non-vacuity anchor: a genuine post-lock write that is
    correctly disjoint from the prompt. Without something in this set the intersection is empty for
    the wrong reason, which is the TS-57 failure exactly.
    """
    fields = CONSOLE_WRITE_FIELDS if write_fields is None else write_fields
    return frozenset(
        field
        for action, written in fields.items()
        if action not in PRE_LOCK_ACTIONS
        for field in written
    )


# --- HLD §11.5's screens, and the two that block (CT-CONSOLE-07) --------------------------------
#
# `FR-CONSOLE-06` / invariant 1: *"Exactly two screens shall block progress — the question
# inventory (S3) and the answer keys (S4)."* §6.11.19 says the count is asserted **against the
# route table**, so the screens are transcribed from §11.5's own headings and the vocabulary test
# checks each is still there.
SCREENS: tuple[str, ...] = (
    "S1",  # Packages (home)
    "S2",  # New package: upload
    "S3",  # Confirm the question inventory        BLOCKS
    "S4",  # Answer keys                           BLOCKS
    "S5",  # The three optional setup cards
    "S6",  # Cohort, submissions, and preflight
    "S7",  # Run monitor
    "S8",  # Operator quarantine
    "S9",  # The review queue
    "S10",  # Whole-grade sample
    "S11",  # Blind sample
    "S12",  # Class rollup and finalization
    "S13",  # Student detail
)

#: Marked `⛔ **BLOCKS**` in §11.5's headings, and nowhere else. `R60`'s test — *"could a teacher
#: start a run, do nothing at all, and still have every student graded?"* — is false the moment a
#: third appears, which is why the assertion is a count and an identity rather than a containment.
BLOCKING_SCREENS: frozenset[str] = frozenset({"S3", "S4"})

#: The operator's three (HLD §11.3's table and §3.19's route split). Everything else is the
#: teacher's. `CT-CONSOLE-12` turns on the separation being structural rather than a filter.
OPERATOR_SCREENS: frozenset[str] = frozenset({"S6", "S7", "S8"})


# --- CT-ORCH-10's shape, which CT-CONSOLE-09 says is the ceiling --------------------------------
#
# *"Progress renders at (stage, criterion, judge) granularity only — which is **exactly what
# `M-ORCH` exposes and nothing more**."* So the case is not only "no per-student figure is
# rendered"; it is that the console **derives** nothing beyond what it was given.
PROGRESS_DIMENSIONS: tuple[str, ...] = ("stage", "criterion", "judge")

#: `CT-ORCH-10` verbatim: counts by the three dimensions, plus these totals and two derived
#: figures, and *"no per-student field"*.
PROGRESS_REPORT_FIELDS: frozenset[str] = frozenset(
    {
        "counts",
        "done",
        "in_flight",
        "pending",
        "quarantined",
        "escalation_rate_so_far",
        "estimated_completion",
    }
)

#: Keys that name an individual student rather than a stage, a criterion or a judge. A payload
#: keyed by one of these carries the per-student view `R63` forbids — and §6.11.19 is explicit that
#: the realistic failure is *"a per-student figure available in a payload and merely unrendered"*.
STUDENT_IDENTIFYING_KEYS: tuple[str, ...] = (
    "submission_ref",
    "submission_id",
    "student_ref",
    "student_id",
    "candidate_number",
)

#: …and the keys that make such a figure a **progress indicator** rather than a result. A student
#: detail view (S13, `/students/{ref}`) legitimately carries a student's bands and grade; what it
#: may not carry is how far through the pipeline that student is.
PROGRESS_VALUE_KEYS: tuple[str, ...] = (
    "percent_complete",
    "percent",
    "progress",
    "pct_done",
    "completion",
    "units_done",
    "units_remaining",
    "eta",
    "estimated_completion",
)


# --- CT-CONSOLE-10: the provenance triple ------------------------------------------------------
#
# `FR-CONSOLE-09` / invariant 4, and `FR-CONF-09` names the same three: *"backend profile, panel
# builds, transcriber build, quantization … in a form the console renders on any view showing a
# grade"*. The clause names three specifically, so three is what is asserted.
PROVENANCE_FIELDS: tuple[str, ...] = ("package_version", "rubric_version", "backend_profile")

#: What a grade looks like in rendered output, so "any view showing a grade" is a decidable
#: question rather than a judgment call. A band label or a points figure inside a `grade`-marked
#: element is the marker; the region marker is the primary signal and this is the backstop for a
#: view that renders one without the marker.
GRADE_MARKERS: tuple[str, ...] = ("grade", "final-grade", "submission-grade", "rollup-grade")


# --- CT-CONSOLE-11: the agreement block ---------------------------------------------------------
#
# Three renderings, and `0.00` and a blank are failures in all three — §2.1's error is *"a blank
# that reads as fine"*.
NO_VALIDATION_FOR_POPULATION = "no validation data for this population"
NO_NEW_VALIDATION_EVIDENCE = "no new validation evidence for this administration"

#: Chance-corrected statistics. A raw percentage agreement is the thing `R8` exists to keep off the
#: page: on a four-band scale two judges guessing agree a quarter of the time, so "76% agreement"
#: is a number whose floor is not zero and which no reader corrects for.
CHANCE_CORRECTED_STATISTICS: tuple[str, ...] = (
    "kappa",
    "cohen's kappa",
    "fleiss' kappa",
    "krippendorff",
    "alpha",
    "gwet",
    "ac1",
)

#: Uncorrected figures, which may not stand alone in an agreement block.
UNCORRECTED_STATISTICS: tuple[str, ...] = (
    "raw agreement",
    "percent agreement",
    "percentage agreement",
    "exact match rate",
    "agreement rate",
)

#: `FR-CONSOLE-10` requires the figure to be **scoped**, and both scopes named: a kappa from
#: another population or another backend is a different measurement wearing the same label.
AGREEMENT_SCOPE_TERMS: tuple[str, ...] = ("population", "backend")

#: *"atomic and holistic never merged"* — one number covering both is `R51`'s merged figure.
AGREEMENT_LEVELS: tuple[str, ...] = ("atomic", "holistic")


# --- CT-CONSOLE-05 and -20: binding ------------------------------------------------------------

CLOUD_HOSTED_PROFILE = "cloud-hosted"

#: What "loopback" means when asserted against a **bound socket** rather than a configured string.
#: §6.11.19 is explicit about the difference, and it is the whole case: a console configured
#: `127.0.0.1` that binds `0.0.0.0` because the framework's default won is exactly RISK-20, and it
#: is invisible to any assertion that reads the setting back.
LOOPBACK_ADDRESSES: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

#: The settings swept under `cloud-hosted`. §6.11.19 asks for *"every combination of settings"*, so
#: the sweep is a product rather than a sample: the failure it is for is a refusal keyed on
#: something other than the profile, which a single combination would not find.
REFUSAL_SWEEP_SETTINGS: dict[str, tuple[Any, ...]] = {
    "CONSOLE_BIND": ("127.0.0.1", "0.0.0.0", "::", "localhost"),
    "CONSOLE_PORT": (None, 8080),
    "CONSOLE_POLL_INTERVAL_MS": (3000, 250),
}


# --- CT-CONSOLE-03: idempotency and the stale-state rule ----------------------------------------
#
# §11.8: *"Every one of these is idempotent, so a double-clicked button, a retried request, or a
# browser back-navigation cannot corrupt a run."* §6.11.19 asks for all three routes **per action**
# rather than sampled, *"since one non-idempotent control is enough to corrupt a run"*.
REPLAY_ROUTES: tuple[str, ...] = ("double_click", "retried_request", "back_navigation")

#: Design §3.19's Error handling, verbatim: *"A control action against stale state … is idempotent
#: or refused with a refresh, **never partially applied**."* Three outcomes, and the third is the
#: one the case exists to make impossible.
STALE_STATE_OUTCOMES: frozenset[str] = frozenset({"idempotent", "refused_with_refresh"})


def replayed_writes_are_idempotent(first: Any, replay: Any) -> tuple[bool, str]:
    """Did replaying a control action write anything new?

    Returns the verdict and the reason, so a per-action sweep names *which* action and *which*
    route broke rather than reporting a bare `False` fifteen times.

    Idempotent means **no additional row**, not "no error". A second `label` row, a second
    `audit_record`, a second `run` — each is a corrupted run that raised nothing.
    """
    if getattr(replay, "refused", False):
        return True, "refused"
    before = list(getattr(first, "rows_written", ()) or ())
    after = list(getattr(replay, "rows_written", ()) or ())
    if after == []:
        return True, "no rows written on replay"
    if after == before:
        return True, "the same rows, rewritten to the same values"
    return False, f"replay wrote {after!r} on top of {before!r}"


# --- CT-CONSOLE-06: browser storage and external origins ----------------------------------------
#
# §4.5's E6 assigns the **browser-level** facts to `TC-CONSOLE-40..42`, which are TS-49's, and §4.10
# budgets the contract tier at 60 seconds with no browser. §6.11.19 nonetheless describes C06 as
# *"a single Playwright load"*. The two readings are reconciled by asserting here what is assertable
# from **served output** — which for the origin half is arguably stronger than a page load, since a
# CDN reference a browser happens not to fetch is still an external origin in the markup — and
# leaving the runtime storage inspection to E6. Reported on the PR rather than papered over.

#: Every browser-storage API `FR-CONSOLE-17` names, plus the two spellings each is reached by.
BROWSER_STORAGE_APIS: tuple[str, ...] = (
    "localstorage",
    "sessionstorage",
    "indexeddb",
    "caches.open",
    "cachestorage",
    "serviceworker.register",
    "navigator.storage",
    "document.cookie",
)

_SCRIPT_URL_ATTRS = ("src", "href", "action", "data-src", "poster", "formaction")
_ABSOLUTE_URL = re.compile(r"^(?:([a-z][a-z0-9+.-]*:)?//|[a-z][a-z0-9+.-]*:)", re.IGNORECASE)
_CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+)""", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?['"]([^'"]+)""", re.IGNORECASE)


def _is_external(url: str) -> bool:
    """A reference that leaves this origin.

    Relative paths, root-relative paths and fragments stay; anything with a scheme or a
    protocol-relative `//host` leaves. `data:` stays — it is inlined bytes, not a request, and the
    design's own answer to *"assets vendored locally"* is exactly that.

    **`//host` is tested before `/path`**, and that order is the rule rather than tidiness. A
    protocol-relative URL starts with a slash, so a root-relative check that runs first passes
    `//fonts.googleapis.com/css?family=Inter` — which is the single likeliest violation of
    `FR-CONSOLE-18` in existence, and the one HLD §11.7 names: *"a console that renders blank at a
    school with no internet"*. Its control caught this.
    """
    url = url.strip()
    if not url:
        return False
    if url.startswith("//"):
        return True
    if url.startswith(("#", "/", "./", "../", "?")):
        return False
    if url.lower().startswith(("data:", "about:blank")):
        return False
    return bool(_ABSOLUTE_URL.match(url))


def external_origins(html: str) -> list[str]:
    """Every reference in `html` that would make the page fetch from another origin.

    `FR-CONSOLE-18` / invariant 13: *"zero requests to any origin other than its own — no CDN, no
    web font, no analytics, no telemetry"*. HLD §11.7 gives the reason and it is not abstract: *"A
    CDN reference is a console that renders blank at a school with no internet — the deployment
    this system exists for."*

    Reads attributes, inline `<style>` `url()`/`@import`, and `style=` attributes, because a web
    font arrives through the stylesheet rather than through a `<script src>` and a rule that only
    reads `src` would pass the most likely violation.
    """
    found: list[str] = []

    class _Origins(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.in_style = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
            if tag == "style":
                self.in_style = True
            for name, value in attrs:
                if not value:
                    continue
                if name in _SCRIPT_URL_ATTRS and _is_external(str(value)):
                    found.append(str(value))
                elif name == "srcset":
                    for candidate in str(value).split(","):
                        url = candidate.strip().split(" ")[0]
                        if _is_external(url):
                            found.append(url)
                elif name == "style":
                    found.extend(u for u in _CSS_URL.findall(str(value)) if _is_external(u))

        handle_startendtag = handle_starttag

        def handle_endtag(self, tag: str) -> None:
            if tag == "style":
                self.in_style = False

        def handle_data(self, data: str) -> None:
            if not self.in_style:
                return
            found.extend(u for u in _CSS_URL.findall(data) if _is_external(u))
            found.extend(u for u in _CSS_IMPORT.findall(data) if _is_external(u))

    parser = _Origins()
    parser.feed(html)
    # `@import url("…")` matches both patterns above, and a caller counting origins would read one
    # stylesheet as two. Deduplicated in document order rather than with a set, so the report still
    # reads like the page.
    return list(dict.fromkeys(found))


def browser_storage_writes(html: str) -> list[str]:
    """Every browser-storage API the served markup reaches for.

    Narrower than the plan's instrument and the PR says so: a running page could reach storage
    through code this scan never sees. What it does catch is the realistic version — the
    *"remember my place"* addition #124's own issue names as the plausible violation, which arrives
    as an inline script in a server-rendered template with no build step (HLD §11.7).

    Scanned over `<script>` bodies and event-handler attributes only. Scanning the whole document
    would report the word `localStorage` in a paragraph of documentation copy, and a rule that
    fails an honest page is a rule somebody switches off.
    """
    found: list[str] = []

    class _Scripts(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.in_script = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
            if tag == "script":
                self.in_script = True
            for name, value in attrs:
                if name.startswith("on") and value:
                    found.extend(_storage_apis_in(str(value)))

        handle_startendtag = handle_starttag

        def handle_endtag(self, tag: str) -> None:
            if tag == "script":
                self.in_script = False

        def handle_data(self, data: str) -> None:
            if self.in_script:
                found.extend(_storage_apis_in(data))

    parser = _Scripts()
    parser.feed(html)
    return found


def _storage_apis_in(source: str) -> list[str]:
    lowered = source.lower().replace(" ", "")
    return [api for api in BROWSER_STORAGE_APIS if api.replace(" ", "") in lowered]


# --- CT-CONSOLE-08: no numeric score entry field, anywhere --------------------------------------
#
# **A console full of numeric inputs is correct.** HLD §10's review queue is *"budgeted in
# minutes"*, so a minutes field is required; S2 shows page order, S6 a cohort size. A rule phrased
# as "no `input[type=number]`" condemns every one of them, and `FR-CONSOLE-07` does not say that —
# it says *"no numeric **score** entry field … all score edits are band selections"*.
#
# So the rule keys on what the field is **for**, taken from its name, id, label and placeholder,
# and then asks whether it accepts a free numeric value. That is two conditions, and both are
# needed: a `<select>` named `band` is a score control and permitted; an `<input type="number">`
# named `review_minutes` is numeric and permitted; an `<input type="text" name="new_points">` is
# neither `type=number` nor a select, and is the violation.

#: What makes a field a **score** field. `new_points` is `FR-REVIEW-10`'s own name for the derived
#: value, so a form field carrying it is the exact interface that requirement forbids.
_SCORE_FIELD_TERMS: tuple[str, ...] = (
    "score",
    "points",
    "point_value",
    "mark",
    "marks",
    "grade",
    "new_points",
    "percentage",
    "percent",
    "total",
)

#: …and what rescues a name that merely *contains* one of those.
#:
#: The first few are numbers about the run rather than about a student's mark. The last three are
#: the ones that make this list load-bearing rather than defensive, and mutation is what found
#: them: **`boundary`** because §11.8's *"declare the grade policy and boundaries"* writes
#: `grade_boundary.cut`, which is a number a teacher types into a field whose name carries
#: "grade"; **`paper`** because a cohort's paper count carries "total"; and **`band`** because the
#: control `FR-CONSOLE-07` mandates is named after the thing it is mandated instead of.
_NOT_A_SCORE_TERMS: tuple[str, ...] = (
    "minute",
    "budget",
    "page",
    "cohort",
    "size",
    "count",
    "window",
    "hours",
    "port",
    "interval",
    "band",
    "boundary",
    "paper",
)

_NUMERIC_PATTERN = re.compile(r"[\d\\]")


def numeric_score_entry_fields(html: str) -> list[str]:
    """Form controls that accept a **numeric score** typed by hand (`FR-CONSOLE-07`).

    Returns the offending field names. A `<select>` or a radio group is a band selection and never
    reported however it is named — that is the interface the requirement mandates, and `R39`'s
    reason is that a free numeric box reintroduces the centre-seeking judgment §5.10 removes.
    """
    hits: list[str] = []

    class _Fields(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
            # A `<select>` is never reported, whatever it is named — it *is* the band selection
            # `FR-CONSOLE-07` mandates, and `score_band` is a plausible name for one. Expressed by
            # only considering `input` and `textarea` rather than by tracking select nesting: an
            # `<input>` cannot legally appear inside a `<select>`, so the nesting counter this
            # replaced was machinery no document could exercise, and a mutation that deleted it
            # changed nothing.
            if tag not in ("input", "textarea"):
                return
            values = {name: str(value or "") for name, value in attrs}
            kind = values.get("type", "text").lower()
            # A band selection, whatever it is called.
            if kind in ("radio", "checkbox", "hidden", "submit", "button", "range"):
                return
            label = " ".join(
                values.get(key, "")
                for key in ("name", "id", "aria-label", "placeholder", "title", "data-field")
            ).lower()
            if not any(term in label for term in _SCORE_FIELD_TERMS):
                return
            if any(term in label for term in _NOT_A_SCORE_TERMS):
                return
            accepts_number = (
                kind == "number"
                or values.get("inputmode", "").lower() in ("numeric", "decimal")
                or bool(_NUMERIC_PATTERN.search(values.get("pattern", "")))
                or kind in ("text", "")
            )
            if accepts_number:
                hits.append(values.get("name") or values.get("id") or f"<{tag}>")

        handle_startendtag = handle_starttag

    parser = _Fields()
    parser.feed(html)
    return hits


def editable_band_controls(html: str) -> list[str]:
    """The names of the band controls a reader could actually change (`FR-CONSOLE-20`).

    Invariant 16: *"Wherever a band is displayed it is displayed as an editable band control. There
    is no view that shows a grade and cannot change it."* `R65`'s reason is the one that makes this
    a completeness assertion rather than a nicety: a read-only grade view becomes the place a
    teacher works around the band interface, which is how the numeric box comes back.

    A `disabled` or `readonly` control is **not** editable and is deliberately not counted — that
    is the shape a read-only view actually takes.
    """
    found: list[str] = []

    class _Bands(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
            if tag not in ("select", "input"):
                return
            values = {name: str(value or "") for name, value in attrs}
            names = " ".join(
                values.get(key, "") for key in ("name", "id", "class", "data-role", "aria-label")
            ).lower()
            if "band" not in names:
                return
            if "disabled" in values or "readonly" in values:
                return
            if tag == "input" and values.get("type", "").lower() not in ("radio", "checkbox"):
                return
            found.append(values.get("name") or values.get("id") or f"<{tag}>")

        handle_startendtag = handle_starttag

    parser = _Bands()
    parser.feed(html)
    return found


# --- CT-CONSOLE-09: no per-student progress figure, rendered or merely available ------------------


def per_student_progress_figures(payload: Any, _path: str = "") -> list[str]:
    """Paths in `payload` that carry a **progress figure keyed to one student**.

    Both halves are needed, and that is the whole rule. `/students/{ref}` is a declared teacher
    route and S13 is a legitimate screen, so a per-student *value* is not a violation; a per-student
    *progress* value is. `R63`'s objection is to the indicator during a run — *"a per-student
    progress bar will be requested and cannot honestly be built"* — not to student detail.

    Walks the whole structure because §6.11.19 says the realistic failure is *"a per-student figure
    available in a payload and merely unrendered"*: a UI that does not draw it today draws it in the
    next release, and the payload is where the decision was already made.
    """
    hits: list[str] = []
    if isinstance(payload, dict):
        keyed_by_student = any(
            key in STUDENT_IDENTIFYING_KEYS for key in (str(k) for k in payload)
        )
        for key, value in payload.items():
            name = str(key)
            path = f"{_path}.{name}" if _path else name
            if name in PROGRESS_VALUE_KEYS and (keyed_by_student or _under_student(_path)):
                hits.append(path)
            hits.extend(per_student_progress_figures(value, path))
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            hits.extend(per_student_progress_figures(item, f"{_path}[{index}]"))
    return hits


def _under_student(path: str) -> bool:
    """Is this path already inside a per-student container?

    A payload shaped `{"students": {"s-1": {"percent_complete": 40}}}` keys by student one level up
    from the figure, so the figure's own dict carries no identifying key. Checking the path is what
    catches the shape a keyed dictionary actually takes.
    """
    lowered = path.lower()
    return any(term in lowered for term in ("student", "submission", "candidate"))


# --- CT-CONSOLE-10: a grade never without its provenance -----------------------------------------


def grade_views_missing_provenance(html: str, provenance: Iterable[str] = PROVENANCE_FIELDS) -> list[str]:
    """Which of the three provenance figures a grade-bearing rendering fails to show.

    Asserted on **rendered output**, per §6.11.19, and over the whole page rather than inside the
    grade element: the design's own shape is a provenance footer (`FR-CONF-09` — *"in a form the
    console renders on any view showing a grade"*), which is not nested inside the grade.

    Returns the missing ones, so the failure names which figure was dropped. `RISK-12` is the
    reason it matters: a grade shown without the package version that produced it cannot be
    defended in a dispute, and the realistic gap §6.11.19 names is *"provenance present on the main
    screen and absent on the export preview"*.
    """
    text = visible_text(html).lower()
    return [field for field in provenance if not _provenance_present(text, field)]


_PROVENANCE_SPELLINGS: dict[str, tuple[str, ...]] = {
    "package_version": ("package version", "package_version", "package v"),
    "rubric_version": ("rubric version", "rubric_version", "rubric v"),
    "backend_profile": ("backend profile", "backend_profile", "profile:"),
}


def _provenance_present(text: str, field: str) -> bool:
    spellings = _PROVENANCE_SPELLINGS.get(field, (field.replace("_", " "),))
    if not any(spelling in text for spelling in spellings):
        return False
    # A label with nothing after it is the failure `CT-CONSOLE-11` names in its own domain: a
    # blank that reads as fine. The same reasoning applies here — "Package version:" alone is a
    # footer that satisfies a substring check and tells a reader nothing.
    #
    # The tail stops at the **next separator**, and that bound is load-bearing: a footer reading
    # "Package version: · Rubric version: · Backend profile:" has three empty labels, and an
    # unbounded tail reads the *next* label as this one's value and reports two of the three as
    # present. Its control caught that.
    # **Longest spelling first, and only that one.** `"package v"` is a prefix of `"package
    # version"`, so judging every spelling in turn reads the `"ersion…"` left over from the longer
    # label as the shorter one's value — and a footer of three empty labels reports two as present.
    # Its control caught that; the fix is to let the most specific spelling that appears identify
    # the label, then judge what follows *it*.
    for spelling in sorted(spellings, key=len, reverse=True):
        index = text.find(spelling)
        if index == -1:
            continue
        tail = re.split(r"[·|;.\n]|(?:\s{2,})", text[index + len(spelling) :], maxsplit=1)[0]
        return bool(re.search(r"[0-9a-z]", tail.replace(":", "").replace("-", "").strip()))
    return False


# --- CT-CONSOLE-11: what an agreement block must and must not say ---------------------------------


def agreement_block_problems(text: str) -> list[str]:
    """Everything wrong with one rendered agreement block (`FR-CONSOLE-10`).

    Four requirements in one clause, so four checks, each returning its own message — a single
    boolean would tell a reader that the block was wrong and not which of the four ways.

    `0.00` and a blank are **both** failures, and that is stated in §6.11.19 rather than inferred:
    *"the §2.1 error is a blank that reads as fine"*. A block that renders `κ = 0.00` because no
    labels were collected is worse than one that renders nothing, because zero is a real value on
    the scale — it means chance agreement, not absence.
    """
    lowered = text.lower()
    problems: list[str] = []

    if not any(stat in lowered for stat in CHANCE_CORRECTED_STATISTICS):
        problems.append(
            "no chance-corrected statistic named; a raw agreement percentage has a floor of "
            "1/k on a k-band scale and no reader corrects for it (R8)"
        )
    if any(stat in lowered for stat in UNCORRECTED_STATISTICS) and not any(
        stat in lowered for stat in CHANCE_CORRECTED_STATISTICS
    ):
        problems.append("an uncorrected agreement figure stands alone")
    if not re.search(r"\bn\s*=\s*\d+|\bsample size\b|\b\d+\s+(?:labels|pairs|papers)\b", lowered):
        problems.append("no sample size adjacent to the figure")
    for scope in AGREEMENT_SCOPE_TERMS:
        if scope not in lowered:
            problems.append(f"the figure is not {scope}-scoped")
    if sum(level in lowered for level in AGREEMENT_LEVELS) == 1:
        problems.append(
            "only one of atomic/holistic is named, so the reader cannot tell which this figure is "
            "— and a single merged figure is exactly what R51 forbids"
        )
    if re.search(r"(?:kappa|alpha|ac1|κ|α)\D{0,12}0\.00\b", lowered):
        problems.append("a 0.00 figure is rendered, which reads as chance agreement, not absence")
    return problems


# --- CT-CONSOLE-12: two queues, and what may not cross between them -------------------------------
#
# `FR-CONSOLE-11`, `-12`, `-19` and HLD §11.3. §6.11.19 asks for a **reachability** assertion over
# the queue's *queries* rather than over what it rendered, which is the same discipline
# `CT-CONSOLE-14` applies to the blind flow — and for the same reason: a filter applied after the
# fetch is one refactor away from being dropped.

#: Row states that belong to the operator and may never reach the teacher's queue.
QUARANTINE_STATES: tuple[str, ...] = (
    "quarantined",
    "unresolved_selection",
    "triage",
    "ingest_failed",
)

#: Item kinds `FR-CONSOLE-12` and `-19` keep out of the review queue. The random arm is the
#: interesting one: it *"spends compute, never teacher minutes"* (`FR-REVIEW-07`), so an
#: implementation that ranks it in has silently rewritten the experiment.
FORBIDDEN_QUEUE_ITEM_KINDS: tuple[str, ...] = ("deterministic", "blind", "random_arm", "quarantine")


def queries_reaching(queries: Iterable[Any], states: Iterable[str]) -> list[str]:
    """The queries that could return a row in any of `states`.

    A reachability assertion, and it is deliberately generous in what it counts as a reach: a query
    that *mentions* a quarantine state is reported whether it includes or excludes it, unless the
    exclusion is explicit. That asymmetry is the point — the case is about whether the row can
    arrive at all, and *"select … where status != 'quarantined'"* proves the queue is filtering
    something it should never have joined to.
    """
    hits: list[str] = []
    for query in queries:
        text = str(query).lower()
        for state in states:
            if state.lower() not in text:
                continue
            if re.search(rf"(?:!=|<>|not\s+in|not\s+like)[^,)]*{re.escape(state.lower())}", text):
                hits.append(f"{query!r} filters on {state} rather than never joining to it")
            else:
                hits.append(f"{query!r} can return a {state} row")
    return hits
