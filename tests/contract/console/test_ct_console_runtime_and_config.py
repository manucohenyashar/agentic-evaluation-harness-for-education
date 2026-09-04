"""`CT-CONSOLE-18` … `-21` — what the process does under load, what the knobs may not switch off,
and what the console is coupled to.

Test plan §6.11.19, TS-77 (issue #132). These four are the clauses about the console as a running
program rather than as a set of pages, and three of them name a failure that a functional test
passes:

* `-18` — an upload handler that buffers the batch in memory works perfectly on a two-page
  fixture and dies on a real scan batch. The clause is explicit that *"hundreds of megabytes of
  scans are a normal upload, not an edge case"*.
* `-19` — a review queue that renders in eight seconds is correct and unusable; the budget exists
  because the screen is opened inside a fixed number of teacher minutes.
* `-20` — `CONSOLE_BIND` is a knob that must **not** be able to defeat a security refusal.
* `-21` — no build step, no framework, and the coupling surface that makes the console
  replaceable.

**Two things this suite could not implement as specified, both reported in the PR rather than
quietly substituted.** `CT-CONSOLE-21`'s *"install into a clean environment"* has nothing to
install against — `pyproject.toml` puts `src` and `.` on the pytest path and there is no package
build — so the achievable half is asserted (no toolchain artefacts, no network at render time, and
the coupling surface) and the install is named as missing. And `CT-CONSOLE-19`'s poll-interval
half and its measurement half are keyed on different stories, because the run monitor is #122's
and the two screens the budgets name are #124's and #125's.
"""

from __future__ import annotations

import pytest

from tests.support.conf_builders import hosted_cfg
from tests.support.console_vocabulary import (
    CONSOLE_KNOBS,
    HANDLER_BUDGET_SECONDS,
    REFERENCE_COHORT_SIZE,
    REVIEW_QUEUE_BUDGET_SECONDS,
    ROLLUP_BUDGET_SECONDS,
    ROUTABLE_BIND,
    UPLOAD_PROBE_BYTES,
    UPLOAD_RSS_RATIO_CEILING,
    coupling_surface,
)
from tests.support.impl import CONSOLE_MODULE, require

pytestmark = pytest.mark.contract


# --- CT-CONSOLE-18 — long work, and where the bytes go -----------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c18_the_upload_handler_dispatches_the_work_rather_than_awaiting_it():
    """`FR-CONSOLE-04`, first half — *"long work shall never occur in a request handler"*.

    Separated from the memory half below because they fail independently and this is the one that
    catches the common bug: an implementation can stream every byte to disk correctly and still
    block the request until transcription finishes. The teacher sees a browser spinning for four
    minutes and reloads, which is also the moment `FR-CONSOLE-02`'s idempotence is tested for real.

    Two assertions, because either alone is weak. **Duration** catches the handler that waits;
    **dispatch** catches the handler that returns fast because the work is not happening at all.
    """
    upload = require(CONSOLE_MODULE, "upload_scans", issue="#122")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    outcome = upload(build_console(), cohort_id="c-1", size_bytes=UPLOAD_PROBE_BYTES)

    assert outcome.handler_seconds < HANDLER_BUDGET_SECONDS, (
        f"the upload handler ran for {outcome.handler_seconds:.1f}s. FR-CONSOLE-04: long work "
        f"never happens in a request handler — it is dispatched and the orchestrator picks it up "
        f"on its own schedule (FR-CONSOLE-01)."
    )
    assert outcome.dispatched, (
        "the handler returned quickly and dispatched nothing, so the work is not queued anywhere. "
        "A fast handler that dropped the batch passes a duration assertion."
    )


@pytest.mark.writtenahead
@pytest.mark.slow
def test_tc_console_c18_a_large_upload_streams_to_the_blob_store_rather_than_into_memory():
    """`NFR-CONSOLE-06` — asserted as **peak RSS relative to the upload**, not as an absolute.

    §6.11.19 asks for peak process RSS during a multi-hundred-megabyte upload, *"since a buffering
    implementation passes a functional test and dies on a real scan batch"*.

    Two decisions, both stated rather than buried. The size is an **env-gated knob**
    (`HARNESS_CONSOLE_UPLOAD_PROBE_BYTES`) with the production-shaped default, because a hard-coded
    300 MB is a constant calibrated for one machine and becomes a phantom failure on every smaller
    one (`CLAUDE.md`, seam 3). And the bound is a **ratio**: an implementation that streams uses
    memory proportional to its buffer, one that buffers is at or above 1.0 by construction — and
    that holds at any probe size, on any box, which an absolute megabyte figure does not.

    Marked `slow` as well as `writtenahead`: §4.7 budgets the whole contract tier at 60 seconds for
    330 cases, and a real multi-hundred-megabyte upload does not belong inside it. Excluded by
    marker rather than by quietly shrinking the probe until it fits, which would delete the case.
    """
    upload = require(CONSOLE_MODULE, "upload_scans", issue="#122")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    outcome = upload(build_console(), cohort_id="c-1", size_bytes=UPLOAD_PROBE_BYTES)

    ratio = outcome.peak_rss_growth_bytes / UPLOAD_PROBE_BYTES
    assert ratio < UPLOAD_RSS_RATIO_CEILING, (
        f"peak RSS grew by {ratio:.2f}× the upload size ({outcome.peak_rss_growth_bytes} bytes for "
        f"a {UPLOAD_PROBE_BYTES}-byte upload). NFR-CONSOLE-06: uploads stream to the "
        f"content-addressed blob store; a batch buffered in memory works on a fixture and dies on "
        f"a real scan batch."
    )
    assert outcome.blob_refs, (
        "nothing reached the blob store, so the memory figure above is the memory cost of doing "
        "nothing"
    )
    assert not outcome.staged_in_browser, (
        "the upload was staged in the browser, which NFR-CONSOLE-06 forbids alongside buffering — "
        "it moves the same failure to a machine with less memory and no error reporting"
    )


# --- CT-CONSOLE-19 — render budgets and the poll ------------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.slow
def test_tc_console_c19_the_review_queue_and_rollup_render_inside_their_budgets_at_350_students():
    """`NFR-CONSOLE-01` — two budgets, asserted separately, at the stated load.

    Two seconds and three, for a 350-student run. The clause gives the reason and §6.11.19 keeps
    it: both screens are *"opened inside a fixed time budget"*, so every second of render time is
    taken directly out of the teacher's review minutes. A queue that renders in eight seconds is
    functionally correct and has spent a tenth of a ten-minute budget on itself.

    Asserted separately rather than as a total, because they are different screens with different
    numbers and a combined bound would let a fast queue subsidise a slow rollup.

    **Keyed on #125, and that is a judgment call.** `NFR-CONSOLE-01` is traced to #126, which
    builds S1, S2, S6 and S8 — none of the two screens this NFR names. The case actually needs the
    review queue (#124) and the rollup (#125), which are siblings with no ordering between them, so
    no single key is certainly last. #125 is chosen because it completes the rollup surface
    (`FR-CONSOLE-19`/`-20`/`-24`). The mis-trace is reported for `/plan-to-issues`.
    """
    render_rollup = require(CONSOLE_MODULE, "render_rollup", issue="#125")
    render_queue = require(CONSOLE_MODULE, "render_review_queue", issue="#124")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    app = build_console(cohort_size=REFERENCE_COHORT_SIZE)
    queue = render_queue(app, run_id="r-350")
    rollup = render_rollup(app, run_id="r-350")

    assert queue.rendered_items, "the review queue rendered nothing, so its duration means nothing"
    assert queue.duration_seconds < REVIEW_QUEUE_BUDGET_SECONDS, (
        f"the review queue took {queue.duration_seconds:.2f}s at {REFERENCE_COHORT_SIZE} students "
        f"against a {REVIEW_QUEUE_BUDGET_SECONDS}s budget"
    )
    assert rollup.duration_seconds < ROLLUP_BUDGET_SECONDS, (
        f"the rollup took {rollup.duration_seconds:.2f}s against a {ROLLUP_BUDGET_SECONDS}s budget"
    )


@pytest.mark.writtenahead
def test_tc_console_c19_the_run_monitor_polls_the_ledger_and_adds_no_write_load():
    """The other half of `CT-CONSOLE-19`, and it needs only the monitor — so it is keyed on #122.

    *"The run monitor polls the ledger every `CONSOLE_POLL_INTERVAL_MS` (3000)."* Two claims:

    - the interval is the declared one, not something faster that felt more responsive;
    - and polling is a **read**. `FR-CONSOLE-01` says the console holds no pipeline state, and a
      monitor that wrote a heartbeat row would put write load on the single-writer thread of an
      active run — every few seconds, for hours, from a page nobody is necessarily watching.

    Asserted under a write audit rather than by inspecting the query text, since a poll that writes
    through an ORM or a session bookkeeping table would not look like a write in SQL.
    """
    from tests.support.guards import recording_write_audit

    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")
    poll_interval = require(CONSOLE_MODULE, "CONSOLE_POLL_INTERVAL_MS", issue="#122")

    assert poll_interval == CONSOLE_KNOBS["CONSOLE_POLL_INTERVAL_MS"]

    app = build_console()
    with recording_write_audit() as writes:
        monitor = app.render("/runs/{id}/monitor", id="r-1")

    assert monitor.poll_interval_ms == CONSOLE_KNOBS["CONSOLE_POLL_INTERVAL_MS"], (
        f"the monitor page polls every {monitor.poll_interval_ms}ms; the declared interval is "
        f"{CONSOLE_KNOBS['CONSOLE_POLL_INTERVAL_MS']}ms"
    )
    console_writes = [w for w in writes if w.attributed_to == "M-CONSOLE"]
    assert not console_writes, (
        f"polling the ledger wrote {[w.target for w in console_writes]}. The monitor is a read: a "
        f"heartbeat written every three seconds for the hours a run lasts is write load on the "
        f"single-writer thread, from a page that may have no one in front of it."
    )


# --- CT-CONSOLE-20 — the knobs, and the one that must not be a switch ---------------------------------


@pytest.mark.writtenahead
def test_tc_console_c20_the_three_knobs_carry_their_declared_defaults():
    """Design §3.19's Configuration line, asserted against the module.

    `CONSOLE_PORT` is asserted only to **exist**, because the design declares no default for it.
    Asserting a value would be asserting this suite's guess, and the first implementer to pick a
    different one would get a red test citing a requirement that does not exist.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")
    console = require(CONSOLE_MODULE, issue="#122")

    assert getattr(console, "CONSOLE_BIND") == CONSOLE_KNOBS["CONSOLE_BIND"]
    assert getattr(console, "CONSOLE_POLL_INTERVAL_MS") == CONSOLE_KNOBS["CONSOLE_POLL_INTERVAL_MS"]
    assert hasattr(console, "CONSOLE_PORT"), (
        "CONSOLE_PORT is a declared knob with no declared default; it must exist as a knob even "
        "though this suite does not assert its value"
    )
    assert build_console is not None


@pytest.mark.writtenahead
def test_tc_console_c20_a_routable_bind_does_not_defeat_the_cloud_hosted_refusal():
    """`CT-CONSOLE-20`'s security-relevant half, and the reason the clause mentions the knob at all.

    *"`CONSOLE_BIND` is security-relevant: `CT-CONSOLE-05`'s refusal is not defeated by changing
    it, because the refusal keys on the deployment profile."*

    The adversarial construction is the one an operator would actually perform: set the bind
    address to something routable so the console can be reached from the next room. If that
    switched off the refusal, `FR-CONSOLE-05` would be advisory — and what it is guarding is an
    unauthenticated student-record system on a network (`R68`, §13). The refusal is in code rather
    than in documentation precisely because the documentation would be read as a default.

    **This overlaps #131 deliberately.** `CT-CONSOLE-05` is `TC-CONSOLE-C01`…`-C12`'s territory;
    what is asserted here is the knob's inability to defeat it, which is `CT-CONSOLE-20`'s own
    sentence. Both suites should keep their half.
    """
    start_console = require(CONSOLE_MODULE, "start_console", issue="#122")
    ConsoleBindRefused = require(CONSOLE_MODULE, "ConsoleBindRefused", issue="#122")

    with pytest.raises(ConsoleBindRefused):
        start_console(hosted_cfg(CONSOLE_BIND=ROUTABLE_BIND))

    # The default bind under the same profile refuses too — so the refusal above is the profile,
    # not the address. Without this row the case would pass against a console that refused any
    # routable bind on every profile, which is a different (and weaker) rule.
    with pytest.raises(ConsoleBindRefused):
        start_console(hosted_cfg(CONSOLE_BIND=CONSOLE_KNOBS["CONSOLE_BIND"]))


# --- CT-CONSOLE-21 — no toolchain, and the seam ---------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c21_the_console_renders_with_no_toolchain_and_no_network(network_guard):
    """`NFR-CONSOLE-02` — the achievable half of *"install into a clean environment"*.

    The clause is about a school: *"repairable by whoever is present"*. No build step, no npm
    toolchain, no client framework, no network at render time. Asserted three ways — the repo
    carries no toolchain artefacts, the rendered page pulls no external origin, and the render
    completes with the socket guard active.

    **The clean-environment install is not achievable here and is reported rather than faked.**
    `pyproject.toml` puts `src` and `.` on the pytest path; there is no package build and nothing
    to install into a fresh environment. Substituting "the guard was on and nothing broke" for
    "installed clean and rendered" would be the weaker rung the skill forbids taking silently.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    rendered = build_console().render("/packages")

    html = rendered.html.lower()
    for artefact in ("cdn.", "googleapis", "unpkg", "jsdelivr", "http://", "https://"):
        assert artefact not in html, (
            f"the rendered page references {artefact!r}. FR-CONSOLE-18 requires zero requests to "
            f"any origin other than its own, and NFR-CONSOLE-02 requires no network at render time."
        )
    for framework in ("react", "vue.", "angular", "webpack", "vite"):
        assert framework not in html, f"the page loads {framework!r}; no client framework is allowed"

    network_guard.assert_no_network()


@pytest.mark.writtenahead
def test_tc_console_c21_the_coupling_surface_is_its_reads_plus_its_declared_writes():
    """`NFR-CONSOLE-05` — the durable half of the clause, and the one worth asserting.

    *"The console shall be replaceable without touching the harness; the seam is that it only reads
    stores and writes the enumerated control rows."* That is a claim about a **set**: the union of
    what it reads and what `FR-CONSOLE-32` declares it writes is its entire coupling to the system.
    A second console could be written against exactly that and nothing else — which is what
    "replaceable" means, and it is checkable.

    So the assertion is that nothing outside the union is touched. An import of a pipeline module,
    a direct call into `M-JUDGE`, a shared in-process object — each would be coupling that a
    replacement console would have to reproduce and that nothing in the design tells it about.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    app = build_console()
    surface = coupling_surface(app)

    assert surface, "the console declares neither reads nor writes, so this seam is unasserted"
    assert set(app.write_surface()) <= surface

    undeclared = set(app.actual_couplings()) - surface
    assert not undeclared, (
        f"the console is coupled to {sorted(undeclared)}, which is neither a store it reads nor a "
        f"control row it declares writing. NFR-CONSOLE-05's replaceability is exactly the claim "
        f"that this set is empty: whatever is in it, a second console would have to reproduce "
        f"without the design ever mentioning it."
    )
