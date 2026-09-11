"""`TC-REVIEW-19` / `SEC-11` — verbatim student work never reaches browser storage.

**`TC-REVIEW-19`** (Security / 4, P0): *"No verbatim student work is written to any
browser storage."* **`SEC-11`** (`FR-CONSOLE-17`, Browser, A01): *exercise review,
blind and student views, then inspect browser storage and caches — nothing written; no
service worker.* The two are one clause, and `NFR-REVIEW-04` states its own pairing:
*"Review views display verbatim student work; the console writes none of it to browser
storage."* That pairing is what makes this file more than a re-run of `CT-CONSOLE-06`'s
sweep: there the pages are swept over a store double whose seeded sentinel is a
student *name*, and the browser-level half of that clause is E6's. Here the store is
real and the seeded content is verbatim student *work* — the submission's text sits in
the blob store (round-tripped) and the student view renders the work-derived narrative
— and the same pages still reach for no storage API at all. The sweep runs over pages
that genuinely display the work, which is the condition `NFR-REVIEW-04`'s sentence
describes and the one a screenshot cannot distinguish from an empty-store pass.

Two disclosures, both inherited from the vocabulary's own reconciliation note
(`console_security_vocabulary`'s C06 block):

- **The instrument is served output.** §4.5's E6 assigns the browser-level facts
  (actual `localStorage` contents, cache entries, live service-worker state) to
  `TC-CONSOLE-40..42` — TS-49's, not landed. What is assertable from served markup is
  asserted here: every storage API `FR-CONSOLE-17` names is scanned for in `<script>`
  bodies and event-handler attributes, over the three `M-REVIEW`-facing views with
  student-linked data behind them. A page could reach storage through code this scan
  never sees; that residue is E6's, and the gap is a finding on the PR, not a silent
  substitution.
- **The review view renders honest-zero over a real store.** The shipped queue read
  orders by `rank_position`, a column no migration adds, so S9's render is an empty
  queue over real data — the exercise clause is still discharged (the view is rendered
  with student-linked data in the ledger and swept), and the queue surface itself is
  `#124`'s.

Isolation: rung 3 — a real store, the real console read path, the real blob store; the
socket guard is autouse.
"""

from __future__ import annotations

import pytest
from tests.support.console_security_vocabulary import browser_storage_writes

from aeh.store import open_store
from tests.support import broken_review_fixtures as broken
from tests.support.impl import CONSOLE_MODULE, require
from tests.support.orch_run import seed_cohort, seed_document

pytestmark = [pytest.mark.integration]

_COHORT = "c-blind-adv"
_SUBMISSION = "S-ADV-0019"
_CRITERION = "C-ADV"
_RUN = "run-blind-adv"

#: The verbatim student work the submission carries — distinctive enough that any
#: storage write carrying it would be attributable, and asserted to round-trip through
#: the blob store before the sweep, so the pages below are swept with the work
#: demonstrably in the data.
_WORK = (
    "verbatim student work sentinel 9014: the candidate's own answer, written by "
    "nobody else, in their own words."
)

#: The three `M-REVIEW`-facing views (`SEC-11`'s exercise clause names review, blind
#: and student), each with the anchor its page must show. The student view's anchor is
#: data-derived — the work-derived narrative the seeded ledger renders. The review and
#: blind pages render their declared static content over the real store (the queue's
#: honest-zero; the blind screen is a statement, not a data view) — swept all the same,
#: which is what the exercise clause asks; the queue's honest-zero and the blind
#: screen's statement-only body are `#124`'s surface, disclosed above.
_VIEWS = (
    (f"/runs/{_RUN}/review", "Review queue"),
    (f"/runs/{_RUN}/blind", "Blind-sample"),
    (f"/students/{_SUBMISSION}", broken.SYSTEM_OUTPUT_SENTINELS["narrative"]),
)

#: The criterion_score insert this file needs — the fourteen columns the shipped table
#: carries after the aggregation migration, in the shape the `M-AGG` contract cases
#: seed, with the system's output in `broken.SYSTEM_OUTPUT_SENTINELS`'s own values.
_INSERT_SCORE = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing, confidence, confidence_base, "
    "spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk) "
    "VALUES (:sid, :cid, :band, :points, :judge_count, :agreement, :state, "
    ":routing, :confidence, :confidence_base, :spans_verified, "
    ":evidence_present, :sufficiency_flag, :ocr_overlap_risk)"
)
_INSERT_NARRATIVE = (
    "INSERT INTO narrative (narrative_id, submission_id, criterion_id, run_id, "
    "level, question_id, text, citations, score_claim_flag) "
    "VALUES (:nid, :sid, :cid, :rid, 'l1_question', :qid, :text, '[]', 0)"
)


def _seed_student_work_store(tmp_data_dir):
    """A real store whose cohort ledger carries verbatim student work (blob + document
    row), the work-derived narrative the student view displays, and the system's score
    row — the data the three views under sweep are *about*."""
    store = open_store(tmp_data_dir)
    seed_cohort(store, (_SUBMISSION,), cohort_id=_COHORT)
    content_hash = seed_document(store, _SUBMISSION, text=_WORK, cohort_id=_COHORT)
    cohort = store.cohort(_COHORT)
    with cohort.transaction() as tx:
        tx.execute(
            _INSERT_SCORE,
            sid=_SUBMISSION, cid=_CRITERION,
            band=broken.SYSTEM_OUTPUT_SENTINELS["system_band"],
            points=broken.SYSTEM_OUTPUT_SENTINELS["points"],
            judge_count=3, agreement=0.95, state="provisional_unreviewed",
            routing="queued", confidence=broken.SYSTEM_OUTPUT_SENTINELS["confidence"],
            confidence_base=0.95, spans_verified=1, evidence_present=1,
            sufficiency_flag=1, ocr_overlap_risk=0,
        )
        tx.execute(
            _INSERT_NARRATIVE,
            nid="nar-adv-19", sid=_SUBMISSION, cid=_CRITERION, rid=_RUN, qid="Q1",
            text=broken.SYSTEM_OUTPUT_SENTINELS["narrative"],
        )
    return store, content_hash


def test_tc_review_19_no_view_writes_verbatim_student_work_to_browser_storage(
    tmp_data_dir,
):
    """`TC-REVIEW-19` — the review, blind and student views, exercised over a store
    whose ledger holds verbatim student work, write to no browser storage.

    The detector is the vocabulary's `browser_storage_writes`, positive-controlled
    first — it must flag the realistic violation (an inline "remember my place" script)
    or the all-clear below proves nothing. The display half of `NFR-REVIEW-04` is
    anchored per view before the sweep: the student page renders the work-derived
    narrative, so the nothing-written verdict is over a page that genuinely displays
    verbatim student content."""
    build_console = require(CONSOLE_MODULE, "build_console", issue="#124")

    store, content_hash = _seed_student_work_store(tmp_data_dir)
    try:
        # The work is in the store, byte for byte — the sweep below is over data.
        assert store.blobs().get(content_hash).decode("utf-8") == _WORK, (
            "the seeded student work is missing, so the sweep below would run over an "
            "empty store and assert nothing"
        )

        # Positive control: the detector catches the realistic violation — an inline
        # script persisting a blind label's band for "remember my place".
        controlled = browser_storage_writes(
            '<script>localStorage.setItem("blind-band", "B3");'
            'sessionStorage.setItem("last-ref", "S-ADV-0019");</script>'
        )
        assert "localstorage" in controlled and "sessionstorage" in controlled, (
            f"fixture bug: the storage detector returned {controlled} — it no longer "
            "catches an inline localStorage write, so the all-clear below proves nothing"
        )

        app = build_console(store=store)
        for route, anchor in _VIEWS:
            page = app.render(route)
            assert anchor in page.html, (
                f"{route} rendered nothing recognisable ({anchor!r} absent), so the "
                "storage sweep below would be an all-clear over a page that is not "
                "the view the clause names"
            )
            writes = browser_storage_writes(page.html)
            assert writes == [], (
                f"{route} reaches for browser storage ({sorted(set(writes))}). "
                "TC-REVIEW-19 / NFR-REVIEW-04: review views display verbatim student "
                "work, and the console writes none of it to browser storage — a "
                "work-derived value persisted client-side survives the purge the "
                "store's own retention rules enforce, outside every audit trail "
                "(SEC-11: nothing written)."
            )
    finally:
        store.close()


#: `SEC-11`'s other half — *"no service worker"*. A worker would outlive the page, the
#: session and the purge: it can cache served bytes (student work among them) and
#: re-serve them after the store has forgotten them, so its absence is a retention
#: claim, not a tidiness one. The served markup is the assertable surface: no
#: registration, no install hook, no cache-API reach.
_SERVICE_WORKER_MARKERS = (
    "serviceworker.register",
    'addEventListener("install"',
    "addEventListener('install'",
    "caches.open",
    "cachestorage",
)


def _service_worker_violations(html: str) -> list[str]:
    """The service-worker reaches one served page carries — `SEC-11`'s detector."""
    lowered = html.lower()
    return [
        marker
        for marker in _SERVICE_WORKER_MARKERS
        if marker.lower() in lowered
    ]


def test_sec_11_no_service_worker_is_registered_or_installed(tmp_data_dir):
    """`SEC-11` — *"Nothing written; no service worker."* The worker-registration
    paths a deployment would use, plus the flow's own route, are served and scanned:
    none registers a service worker, none installs one, none opens a cache. The
    detector is positive-controlled first. Browser-level state (a live registration
    the markup alone cannot see) is `TC-CONSOLE-40`'s — TS-49/E6, unlanded."""
    build_console = require(CONSOLE_MODULE, "build_console", issue="#124")

    store, _ = _seed_student_work_store(tmp_data_dir)
    try:
        # Positive control: a page that registers a worker and hooks its install
        # event is flagged on both counts.
        controlled = _service_worker_violations(
            '<script>navigator.serviceWorker.register("/sw.js");'
            'self.addEventListener("install", () => caches.open("v1"));</script>'
        )
        assert "serviceworker.register" in controlled and 'addEventListener("install"' in controlled, (
            f"fixture bug: the service-worker detector returned {controlled} — it no "
            "longer catches a registration, so the all-clear below proves nothing"
        )

        app = build_console(store=store)
        violations: list[str] = []
        for path in ("/sw.js", "/service-worker.js", "/serviceworker.js", f"/runs/{_RUN}/blind"):
            violations.extend(
                f"{path} serves {marker!r}"
                for marker in _service_worker_violations(app.render(path).html)
            )
        assert violations == [], (
            f"a service worker reached the console's served surface: {violations}. "
            "SEC-11: no service worker — one that caches the views caches verbatim "
            "student work the store's purge rules can never reach."
        )
    finally:
        store.close()