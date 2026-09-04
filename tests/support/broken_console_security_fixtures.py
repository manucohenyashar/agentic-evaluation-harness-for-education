"""Controls for `console_security_vocabulary`'s rules, in both directions.

Every rule in TS-76 is a prohibition detector, and a prohibition detector fails in two directions.
The direction that gets caught in review is the one that misses a violation; the direction that
gets caught **in use** is the one that condemns correct copy, because a rule which fails a
compliant console is a rule the first person to hit it switches off. TS-74 shipped rules that
rejected the disclaimers their own clauses required; TS-77 shipped a narrative rule that condemned
*"the student remarks"*.

So the "correct" fixtures here are deliberately awkward: a console **full** of numeric inputs, a
payload **full** of per-student values, an audit page that is a table. Each is what §3.19 and HLD
§11.5 actually specify, and each would be condemned by the obvious version of the rule beside it.
"""

from __future__ import annotations

# --- FR-CONSOLE-07 / -20: numeric score entry, and the numbers a console must have ---------------

#: A review queue rendered correctly — and it carries **four** numeric inputs, every one required.
#:
#: HLD §10's queue is *"budgeted in minutes"*, so the minutes field is not an oversight to be swept
#: away; S6 needs a cohort size and S2 a page number. A rule phrased as "no `input[type=number]`"
#: condemns this whole screen, and `FR-CONSOLE-07` does not say that — it says no numeric **score**
#: field. The band control beside them is what a score edit is allowed to look like.
CORRECT_REVIEW_SCREEN_HTML = """
<form data-role="review-item" action="/runs/r-1/review">
  <label for="minutes">Review budget (minutes)</label>
  <input type="number" id="minutes" name="review_minutes" value="25" min="5" max="120">
  <label for="pages">Pages in this document</label>
  <input type="number" id="pages" name="page_count" value="4">
  <label for="cohort">Cohort size</label>
  <input type="number" id="cohort" name="cohort_size" value="350">
  <label for="window">Review window (hours)</label>
  <input type="number" id="window" name="review_window_hours" value="48">
  <label for="cut">Grade boundary: B</label>
  <input type="number" id="cut" name="grade_boundary_cut" value="70">
  <label for="papers">Papers in this cohort</label>
  <input type="number" id="papers" name="total_papers" value="350">
  <label for="band">Criterion 3</label>
  <select id="band" name="new_band">
    <option>absent_or_wrong</option><option>asserts_only</option>
    <option selected>derives_only</option><option>derives_and_justifies</option>
  </select>
  <label for="overall">Overall</label>
  <select id="overall" name="score">
    <option selected>met</option><option>not_met</option>
  </select>
  <span class="mark-summary">8 of 10 points</span>
</form>
"""

#: The three inputs above whose **names carry a score word** and which are nonetheless required.
#:
#: They are what the rule's not-a-score rescue exists for, and without them the rescue is dead
#: code: none of the minutes, page and cohort fields contains a score term at all, so a rule with
#: the rescue deleted passes them anyway. Mutation found exactly that.
#:
#: * `grade_boundary_cut` — §11.8's *"declare the grade policy and boundaries"* writes
#:   `grade_boundary.cut`, and a cut point is a number a teacher types. It carries "grade".
#: * `total_papers` — carries "total".
#: * `score` — a `<select>` offering band options, which is the interface `FR-CONSOLE-07`
#:   **mandates**, under the bluntest possible name. It is compliant: a fixed set of options is a
#:   band selection whatever the form field is called, and `FR-REVIEW-10` derives `new_points`
#:   from the band. A rule that read the name without reading the control would condemn the band
#:   selector itself, and nothing else in the fixture exercises that exemption — every other
#:   score-named control is rescued by the word "band" in its own name.
REQUIRED_FIELDS_WHOSE_NAMES_CARRY_A_SCORE_WORD: tuple[str, ...] = (
    "grade_boundary_cut",
    "total_papers",
    "score",
)

#: The four shapes a numeric score box actually arrives in. Only the first is an
#: `input[type=number]`; a rule keyed on the type alone misses the other three, and the third and
#: fourth are what somebody writes when the first one is rejected in review.
SCORE_ENTRY_HTML: dict[str, str] = {
    "a number input named score": '<input type="number" name="score" value="7">',
    "a text input named new_points": '<input type="text" name="new_points" value="7">',
    "a numeric-inputmode field named mark": '<input inputmode="numeric" name="mark_awarded">',
    "a pattern-restricted text field named points": (
        r'<input type="text" name="total_points" pattern="[0-9]{1,3}">'
    ),
    # Caught by "points" and by nothing else in the term list — so deleting that one term is
    # visible. Mutation found the other three covering for it.
    "a plain field named points_earned": '<input type="number" name="points_earned">',
}

#: A rollup that shows a grade and **cannot change it** — invariant 16's violation, and the one
#: `R65` says becomes the place teachers work around the band interface. Both spellings of
#: read-only appear, because an implementation reaches for whichever it remembers.
READ_ONLY_GRADE_HTML = """
<section class="grade">
  <span class="band">derives_only</span>
  <select name="band" disabled><option>derives_only</option></select>
  <input name="band_readonly" type="radio" readonly checked>
  <input type="hidden" name="band" value="derives_only">
</section>
"""

#: The same rollup done right: the band a reader sees is the band they can change.
EDITABLE_GRADE_HTML = """
<section class="grade">
  <select name="new_band"><option selected>derives_only</option><option>asserts_only</option></select>
  <p>Package version: pkg-3.2.0 · Rubric version: rub-1.4 · Backend profile: edge-local</p>
</section>
"""

# --- FR-CONSOLE-18: external origins ------------------------------------------------------------

#: A page that loads **everything** from its own origin, the way HLD §11.7 requires: *"Assets
#: vendored locally, one stylesheet, no framework."* It still carries a font, a stylesheet, a
#: script and an image — a rule that reports any URL at all condemns it.
SELF_CONTAINED_PAGE_HTML = """
<link rel="stylesheet" href="/static/console.css">
<script src="/static/console.js"></script>
<style>
  @font-face { font-family: Console; src: url('/static/fonts/console.woff2'); }
  body { background: url("./paper.png"); }
</style>
<img src="/blobs/sha256-ab12/crop.png" alt="scanned answer">
<a href="#review-queue">Skip to the queue</a>
<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="">
"""

#: The four routes an external origin actually arrives by, and only the first is a `<script src>`.
#: The web font is the likeliest of them — it is one line in a stylesheet and it is what makes the
#: console render blank at a school with no internet.
EXTERNAL_ORIGIN_HTML: dict[str, str] = {
    "a CDN script": '<script src="https://cdn.example.net/htmx.min.js"></script>',
    "a protocol-relative web font": '<link rel="stylesheet" href="//fonts.googleapis.com/css?family=Inter">',
    "an @import in an inline stylesheet": '<style>@import url("https://cdn.example.net/reset.css");</style>',
    "a background image in a style attribute": (
        '<div style="background:url(https://analytics.example.net/px.gif)"></div>'
    ),
    # A responsive crop served from a CDN. `srcset` is the attribute nobody remembers to scan,
    # and S8 renders image crops (`FR-CONSOLE-29`) — so it is the one this console would carry.
    "a CDN crop in a srcset": (
        '<img src="/blobs/crop.png" srcset="https://cdn.example.net/crop@2x.png 2x">'
    ),
}

# --- FR-CONSOLE-17: browser storage --------------------------------------------------------------

#: An honest page that **talks about** browser storage without touching it. This is what the
#: console's own privacy note looks like, and a whole-document substring scan condemns it — which
#: is why the scan reads script bodies and event handlers only.
PAGE_THAT_MENTIONS_STORAGE_HONESTLY = """
<p>This console writes nothing about a student to your browser: no localStorage, no sessionStorage,
no service worker, and no cookie carrying student text.</p>
<script>document.querySelector('form').addEventListener('submit', function () { this.dataset.sent = '1'; });</script>
"""

#: The *"remember my place"* addition #124's own issue names as the plausible violation — and it is
#: plausible precisely because it is helpful: a teacher interrupted mid-queue comes back to item 1.
#: The sentinel is a student name, which is what makes it `FR-CONSOLE-17` rather than a preference.
REMEMBER_MY_PLACE_HTML = """
<script>
  localStorage.setItem('queue.position', JSON.stringify({student: 'Amara Okonkwo', item: 14}));
</script>
"""

STORAGE_WRITE_HTML: dict[str, str] = {
    "localStorage in an inline script": REMEMBER_MY_PLACE_HTML,
    "sessionStorage in an event handler": (
        "<button onclick=\"sessionStorage.setItem('draft', document.forms[0].narrative.value)\">Save</button>"
    ),
    "a registered service worker": "<script>navigator.serviceWorker.register('/sw.js');</script>",
    "an IndexedDB cache of the queue": "<script>indexedDB.open('review-queue', 1);</script>",
}

#: The student name seeded into the data before the page is rendered, per §6.11.19's *"a sentinel
#: student name present in the data"*. Distinctive enough that finding it anywhere is unambiguous.
SENTINEL_STUDENT_NAME = "Amara Okonkwo"

# --- FR-CONSOLE-08: per-student progress ----------------------------------------------------------

#: `CT-ORCH-10`'s shape, which is what the run monitor is allowed to render.
CORRECT_PROGRESS_PAYLOAD: dict[str, object] = {
    "counts": [
        {"stage": "judge", "criterion": "c4", "judge": "j-1", "done": 312, "pending": 38},
        {"stage": "judge", "criterion": "c4", "judge": "j-2", "done": 310, "pending": 40},
    ],
    "done": 622,
    "in_flight": 12,
    "pending": 78,
    "quarantined": 3,
    "escalation_rate_so_far": 0.11,
    "estimated_completion": "2026-09-04T02:40:00Z",
}

#: **S13 Student detail, and it is permitted.** `/students/{ref}` is a declared teacher route and
#: the screen exists; a rule that condemns any per-student payload condemns the design. What makes
#: it legal is that it carries results, not progress.
CORRECT_STUDENT_DETAIL_PAYLOAD: dict[str, object] = {
    "submission_ref": "sub-0142",
    "student_name": SENTINEL_STUDENT_NAME,
    "bands": {"c1": "derives_only", "c4": "asserts_only"},
    "grade": "incomplete",
    "package_version": "pkg-3.2.0",
}

#: The two shapes a per-student progress figure arrives in. The second is the one §6.11.19 warns
#: about — *"available in a payload and merely unrendered"* — and the first is what a keyed
#: dictionary looks like, where the identifying key is one level above the figure.
PER_STUDENT_PROGRESS_PAYLOADS: dict[str, object] = {
    "keyed by student, one level up": {
        "students": {"sub-0142": {"percent_complete": 40}, "sub-0143": {"percent_complete": 95}}
    },
    "a list of rows carrying the ref beside the figure": {
        "rows": [{"submission_ref": "sub-0142", "progress": 0.4, "eta": "12m"}]
    },
}

# --- FR-CONSOLE-09: provenance ---------------------------------------------------------------------

#: A grade view carrying all three figures, in the footer form `FR-CONF-09` describes.
GRADE_WITH_PROVENANCE_HTML = """
<section class="grade"><h2>Grade: B</h2><span class="band">derives_only</span></section>
<footer class="provenance">Package version pkg-3.2.0 · Rubric version rub-1.4 ·
Backend profile edge-local (llama-3.1-70b-instruct-q5_K_M)</footer>
"""

#: The realistic gap §6.11.19 names: *"provenance present on the main screen and absent on the
#: export preview"*. Two of three are here, which is why the rule returns *which* is missing.
EXPORT_PREVIEW_MISSING_PROVENANCE_HTML = """
<section class="grade"><h2>Grade: B</h2></section>
<footer class="provenance">Package version pkg-3.2.0 · Rubric version rub-1.4</footer>
"""

#: A footer that prints all three **labels** and no values. It satisfies any substring check and
#: tells a reader nothing — the same "blank that reads as fine" §2.1 names, in a different block.
PROVENANCE_LABELS_WITHOUT_VALUES_HTML = """
<section class="grade"><h2>Grade: B</h2></section>
<footer class="provenance">Package version: · Rubric version: · Backend profile:</footer>
"""

# --- FR-CONSOLE-10 / -24 / -26: the agreement block --------------------------------------------------

#: What a correct agreement block says. Chance-corrected, `n` adjacent, both scopes named, and the
#: two levels reported separately rather than merged.
CORRECT_AGREEMENT_BLOCK = (
    "Atomic agreement: Cohen's kappa 0.71 (n = 48 blind-labelled papers), "
    "population Grade 11 physics, backend edge-local. "
    "Holistic agreement: kappa 0.64 (n = 48), same population and backend."
)

#: One failure each, so a test names which of the four requirements broke.
BROKEN_AGREEMENT_BLOCKS: dict[str, str] = {
    "uncorrected": (
        "Atomic and holistic raw agreement: 76% (n = 48), population Grade 11 physics, "
        "backend edge-local."
    ),
    "no sample size": (
        "Atomic kappa 0.71, holistic kappa 0.64, population Grade 11 physics, backend edge-local."
    ),
    "unscoped": "Atomic kappa 0.71 (n = 48); holistic kappa 0.64 (n = 48).",
    "only one level named": (
        "Agreement: kappa 0.71 (n = 48), atomic, population Grade 11 physics, backend edge-local."
    ),
    # Broken by the chance-correction requirement **alone**: it names no statistic at all, and
    # no uncorrected one either, so it is not caught by the stands-alone check covering for it.
    "a bare figure with no statistic named": (
        "Agreement 0.71 (n = 48), atomic and holistic, population Grade 11 physics, "
        "backend edge-local."
    ),
    "zero rendered as a figure": (
        "Atomic kappa 0.00 (n = 0), holistic kappa 0.00 (n = 0), population Grade 11 physics, "
        "backend edge-local."
    ),
}

#: `FR-CONSOLE-24`'s failure, and it has no symptom: the block looks *better* than the honest one.
#: RISK-08 is the silent carry-forward, so the fixture carries a real figure from a real prior
#: administration, which is what a cached template produces.
#:
#: Deliberately **well formed** — chance-corrected, `n` adjacent, both scopes named, both levels
#: reported. It has to be: a carry-forward that failed a well-formedness check would be caught by
#: the rule above, and RISK-08 would not be a risk. The only thing wrong with it is the date.
CARRIED_FORWARD_AGREEMENT_BLOCK = (
    "Atomic agreement: Cohen's kappa 0.71 (n = 48), population Grade 11 physics, "
    "backend edge-local. Holistic agreement: kappa 0.64 (n = 48), same population and backend. "
    "Measured 2026-01-14, during the previous administration."
)

#: What that block must say instead when this administration collected no blind labels.
HONEST_ABSENT_AGREEMENT_BLOCK = (
    "No new validation evidence for this administration: no blind labels were collected."
)

# --- FR-CONSOLE-11 / -12 / -19: the two queues -----------------------------------------------------

#: Queries a correct review queue issues. It never names a quarantine state, because the queue is
#: built from `review_queue` rows that were never created for a quarantined submission.
CORRECT_QUEUE_QUERIES: tuple[str, ...] = (
    "select item_id, submission_ref, expected_value from review_queue where run_id = :run_id "
    "order by expected_value desc limit :budget",
    "select criterion_id, band, descriptor from criterion_band where package_version_id = :pv",
)

#: The two shapes the leak takes, and the second is the one that reads as *correct* in review — a
#: filter is visible, deliberate and one refactor from being dropped. §6.11.19 asks for
#: reachability over the queries for exactly that reason.
LEAKY_QUEUE_QUERIES: dict[str, str] = {
    "joins straight to quarantined rows": (
        "select s.submission_ref, s.ingest_status from submission s "
        "join review_queue q on q.submission_ref = s.submission_ref where s.ingest_status = 'quarantined'"
    ),
    "fetches everything and filters after": (
        "select * from submission where ingest_status != 'quarantined' and run_id = :run_id"
    ),
}
