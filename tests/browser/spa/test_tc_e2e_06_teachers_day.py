"""TC-E2E-06 — the teacher's-day journey: one day's work, driven twice, compared.

Operator-requirements test plan §5.6 (P0, rung 4: E6 + the fixture provider). The
journey the plan describes — install, configure, set up, class, papers, run start
(banner + confirm), monitor, review, results/export, ask for help, close the terminal
— is driven TWICE into twin stores over one shared recording:

* **the operator's surface** — the committed SPA served by a real ``serve_console``,
  driven in a Chromium-family browser through the hub's lifecycle screens
  (``tests/support/spa.py``'s vocabulary); the run's start goes through the console's
  own ``start run`` control, and the results/export bytes come back through the
  console's ``results export`` read;
* **the CLI's surface** — ``aeh cohort create`` (the real roster file, so the
  name-identity matcher runs), ``aeh ingest``, ``aeh run`` and ``aeh results
  show/export`` through ``aeh.pipeline.cli.main``.

The oracle is the differential: after both journeys, the two stores hold IDENTICAL
tier rows under the §4.7 pairing (minted ids paired by surrogate, timing records
dropped) — ``tests/support/journey_world.py``'s ``pairing_mask`` and
``canonical_tier_rows`` over ``row_differences``. A surface that writes something the
CLI cannot produce — or vice versa — shows up here, not in review.

**Model boundary.** Both twins replay one capture (``journey_world``):
``JourneyCaptureProvider`` records every reply into a shared fixture folder; the twins
replay through ``ReplayWithSynthFallback``. Disclosed: the fallback answers a
FIRST-SIGHT synthesis prompt with the same ``journey_world.synth_reply`` the capture
answered with, because the synthesis prompt carries the store's own minted submission
id (``synth.prompt_for``) — no recording taken in another store can satisfy it.
Everything else is strict replay; any other fixture miss raises (CT-PROV-08), so a
journey step that stops being replayable is a loud error, not a silent divergence.
The fallback is bound by patching the pipeline's ``_provider_for`` bindings — the
module-level import sites (``background``, ``cli``) plus ``runtime`` itself, which
``ingest_files`` re-imports from at call time (the one egress seam, CT-PROV-15) —
disclosed in the PR.

**Other disclosed divergences** (each deliberate, each named in the PR):

* The package leg builds the same fixture shape on BOTH sides through ``aeh.pkg``'s
  real writer (``rubric_methods.build``) — the console's package-setup screen and
  ``aeh package build`` both write through that service. The model-backed Stage A
  draft flow is not driven; ``SetupService``'s read-back is asserted on the console
  side (#624) so the setup surface still sees the published version.
* Both class legs write the roster through the same writer ``aeh cohort create`` calls
  (``aeh.orch.cohorts.create_cohort``): the console leg calls it directly (the cohort
  editor's write control is not in the API yet), the CLI side through ``aeh cohort
  create --roster``. The refs are generated deterministically from the cohort, the
  ordinal and the name, so the twins' rosters — and the resolved ref every redacted
  request head carries — are row-identical, which is also what keeps the capture's
  request keys replayable in the twins.
* Neither surface names its run: the SPA's start control and ``aeh run`` both let
  M-ORCH mint the run id (no pending run exists when the day starts), so every leg
  after the run resolves each twin's minted id from its own store, and the
  differential reads run ids through ``tier_rows``'s generic ``<minted>`` masking
  (``MINTED_ID`` covers the ``run-<32hex>`` shape).
* The review and finalize legs go through the same M-REVIEW / M-GRADE libraries the
  console's review screen and ``finalize batch`` control call, on both sides.
* ``dev-ci`` is the twins' profile: the console refuses ``cloud-hosted`` outright, and
  dev-ci + ``HARNESS_FIXTURE_DIR`` is the one combination ``_provider_for`` answers
  with the fixture provider.
* The ask-for-help leg's transport is a stub: the QA prompt is a shape no replay
  fixture can carry (only synthesis may miss), so ``help_read.provider_for`` is bound
  to a stub ``complete`` — retrieval stays local (M-HELP), the ask stays on the
  machine's side of the boundary, and its exchange log still writes through the real
  store path.

Written ahead of implementation (test-plan §8.2): red until the committed bundle's
lifecycle screens (#635), the console reads (#631), the Q&A panel (#638), the help
module (#636), the live-acceptance entry point (#618), the rubric-method read-backs
(#624) and the bundle itself (#634) land. The gates below fail in milliseconds —
BEFORE any browser is launched or store built — and each names its issue.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

import pytest

from tests.support import journey_world as jw
from tests.support import spa
from tests.support.impl import NotImplementedYet, require, require_path

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
    pytest.mark.writtenahead,  # red until #634/#635/#636/#638/#618/#631/#624 land
]

#: FR-UI-07's recovery wording — the lifecycle screens' first-shipped phrase (#635).
_RECOVERY_PHRASE = "check that the console service is running"
#: FR-UI-06's answers-only affordance wording — the Q&A panel's first-shipped phrase (#638).
_QA_PHRASE = "does not operate the system"
#: The console reads the journey needs (TS-148's vocabulary, #631).
_CONSOLE_READS = {"run start preview", "results export"}
#: The rubric-method read-backs the package-setup screen shows (#624).
_SETUP_SYMBOLS = (
    "derive_general_bands", "derivation_card", "confirm_general_derivation",
    "build_evidence_sum", "set_aspect_descriptor", "confirm_evidence_sum",
)  # #624 landed `set_aspect_descriptor` — the invented `edit_aspect_descriptor` re-pointed
#: How long a twin's composed run may take to reach a terminal phase. Env-gated
#: (seam 3): a slow box raises it without a code change.
RUN_TIMEOUT_S = float(__import__("os").environ.get("HARNESS_JOURNEY_RUN_TIMEOUT_S", "1200"))


def _gates() -> None:
    """Every blocker, checked before anything expensive is built. Each refusal names
    the issue that unblocks it, so a red run here is readable without opening the
    trace."""
    from aeh.console import API_ROUTES, SPA_BUNDLE_DIR

    require_path(
        SPA_BUNDLE_DIR / "index.html",
        "the committed SPA bundle the hub serves (M-UI foundation)", issue="#634")
    text = (SPA_BUNDLE_DIR / "index.html").read_text(encoding="utf-8")
    for phrase, issue in ((_RECOVERY_PHRASE, "#635"), (_QA_PHRASE, "#638")):
        if phrase not in text:
            raise NotImplementedYet(
                f"the SPA bundle does not carry {phrase!r} yet — the lifecycle screens "
                f"or the Q&A panel (issue {issue}) are not here yet")
    require("aeh.conform", "run_live_acceptance",
            issue="#618 — the live-acceptance entry point NFR-SYS-17's walkthrough names")
    require("aeh.help", "HelpAssistant",
            issue="#636 — the help module the ask-for-help leg calls")
    import aeh.setup
    missing = [name for name in _SETUP_SYMBOLS if not hasattr(aeh.setup.SetupService, name)]
    if missing:
        raise NotImplementedYet(
            "aeh.setup.SetupService does not yet carry " + ", ".join(missing)
            + " — the rubric-method read-backs the package-setup screen shows (issue #624)")
    reads = {getattr(route, "read", None) for route in API_ROUTES}
    if not _CONSOLE_READS <= reads:
        raise NotImplementedYet(
            "the console API has no 'run start preview' / 'results export' read yet "
            "(issue #631); the journey's banner and export legs are blocked on it")


def _patch_provider_sites(monkeypatch: pytest.MonkeyPatch, fixture_dir: Path) -> None:
    """Bind the twins' model boundary at the pipeline's ``_provider_for`` seam.

    ``dev-ci`` + ``HARNESS_FIXTURE_DIR`` answers the plain replayer; the twins need the
    synthesis-only fallback on top (module docstring). Every binding the pipeline reads
    is patched: ``background`` and ``cli`` import ``_provider_for`` at module level from
    ``.runtime``, so they each need their own attribute replaced; ``intake`` imports the
    name only inside ``ingest_files``, from ``.runtime`` at call time — patching
    ``runtime`` covers the twins' direct ``ingest_files``. (``intake`` itself has no
    ``_provider_for`` attribute to patch.)
    """
    from aeh.pipeline import background, cli, runtime

    def synthetic_provider(run_config: object):
        return jw.ReplayWithSynthFallback(fixture_dir)

    for site in (background, cli, runtime):
        monkeypatch.setattr(site, "_provider_for", synthetic_provider)


def _config_toml(path: Path) -> str:
    """The twins' run config as the file ``aeh run --config`` reads: the dev-ci profile
    with the hosted panel and transcriber — the same refs the capture and the console
    twin resolve, rendered once from those values so the sides cannot drift."""
    from tests.support.conf_builders import (
        HOSTED_PANEL_3, HOSTED_TRANSCRIBER, PROMPT_TEMPLATE_V,
    )

    lines = [
        'HARNESS_PROFILE = "dev-ci"',
        f'prompt_template_v = "{PROMPT_TEMPLATE_V}"',
        'HARNESS_COST_CEILING = "12.50"',
        'HARNESS_COST_CURRENCY = "USD"',
        'HARNESS_DECISION_ENGINE = "off"',
        "",
        "[profiles.dev-ci.transcriber]",
        f'role = "{HOSTED_TRANSCRIBER.role}"',
        f'provider = "{HOSTED_TRANSCRIBER.provider}"',
        f'build_id = "{HOSTED_TRANSCRIBER.build_id}"',
    ]
    for ref in HOSTED_PANEL_3:
        lines += [
            "", "[[profiles.dev-ci.panel]]",
            f'role = "{ref.role}"',
            f'provider = "{ref.provider}"',
            f'build_id = "{ref.build_id}"',
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return "\n".join(lines) + "\n"


def _write_papers(paper_dir: Path, pages_by_student: dict[str, list[str]],
                  assessment_pages: list[str]) -> tuple[Path, list[Path]]:
    """The day's papers as byte-identical PDFs on disk: the assessment once, one sheet
    per student. The twins read the SAME files."""
    from tests.support.e2e_world import _pdf_of

    paper_dir.mkdir(parents=True, exist_ok=True)
    assessment = paper_dir / "assessment.pdf"
    assessment.write_bytes(_pdf_of(assessment_pages))
    sheets = []
    for student in jw.STUDENTS:
        path = paper_dir / f"{student.student_ref}.pdf"
        path.write_bytes(_pdf_of(pages_by_student[student.student_ref]))
        sheets.append(path)
    return assessment, sheets


def _open_store_with(data_dir: Path):
    """A store whose migration chain is complete — the package fixture writes Tier P/C."""
    for sub in ("packages", "cohorts", "blobs"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    from aeh.store import open_store

    return open_store(data_dir)


def _console_cohort(store) -> None:
    """The class leg, console side: the roster through the same writer ``aeh cohort
    create`` calls (``aeh.orch.cohorts.create_cohort``) — the cohort editor's write
    control is not in the API yet, but what the console's class surface fronts must
    still be the rows that writer produces (TC-CONSOLE-55). The refs are generated
    deterministically from the cohort, the ordinal and the name, so the twins'
    rosters are row-identical (module docstring)."""
    from aeh.orch.cohorts import create_cohort

    create_cohort(store, jw.COHORT_ID, "synthetic",
                  [{"full_name": s.student_ref} for s in jw.STUDENTS])


def _minted_run_id(store, whose: str) -> str:
    """The run id M-ORCH minted on this surface, read from the run table — never
    assumed: `create_run` mints `run-<uuid4>` on both surfaces."""
    handle = store.cohort(jw.COHORT_ID)
    rows = handle.query("SELECT run_id FROM run")
    assert len(rows) == 1, (
        f"TC-E2E-06: {whose} run table holds {len(rows)} run(s); the day's journey "
        "starts exactly one")
    return str(rows[0]["run_id"])


def _await_terminal(handle, run_id: str) -> str:
    """Poll the run row until a terminal phase; time-boxed by the env knob."""
    deadline = time.monotonic() + RUN_TIMEOUT_S
    last = ""
    while time.monotonic() < deadline:
        rows = handle.query(
            "SELECT status FROM run WHERE run_id = :r", r=run_id)
        last = rows[0]["status"] if rows else ""
        if last in ("complete", "failed", "stopped", "cancelled"):
            return last
        time.sleep(0.25)
    return f"still {last!r} after {RUN_TIMEOUT_S}s"


def test_tc_e2e_06_teachers_day_journey(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The teacher's-day journey, driven through the operator's surface and the CLI's,
    writes identical stores."""
    _gates()
    scratch = tmp_path_factory.mktemp("teachers-day")
    fixture_dir = scratch / "recordings"
    for key, value in (
        ("HARNESS_PROFILE", "dev-ci"),  # pinned: env wins over cfg (conf.sources), so a
        # stray profile in the developer's env would silently re-profile the twins
        ("HARNESS_FIXTURE_DIR", str(fixture_dir)),
        ("HARNESS_INGEST_DPI", "72"),
        ("HARNESS_INGEST_V4_SEMANTIC_FLOOR", "0.0"),
        ("HARNESS_ORCH_RANDOM_ARM_RATE", "0"),
    ):
        monkeypatch.setenv(key, value)
    _patch_provider_sites(monkeypatch, fixture_dir)

    # -- capture once ---------------------------------------------------------------
    # A throwaway world renders the papers first (the same pinned pages the capture
    # ingests), so the twins write byte-identical PDFs of the SAME scans.
    probe = jw.TeachersDayWorld(scratch / "probe", fixture_dir, monkeypatch=monkeypatch)
    pages_by_student = {
        student.student_ref: probe._pages_for(student, with_student=True)
        for student in jw.STUDENTS
    }
    assessment_pages = [probe._assessment_transcript()]
    probe.store.close()
    shutil.rmtree(scratch / "probe")

    capture = jw.TeachersDayWorld(scratch / "capture", fixture_dir, monkeypatch=monkeypatch)
    capture.build_run()
    capture.start_run()
    from aeh.pipeline import run_to_completion

    captured = run_to_completion(
        capture.store, capture.run_id, provider=capture.provider,
        run_config=capture.resolved)
    assert captured.status == "complete", (
        f"the capture's own journey did not complete: {captured.status} "
        f"{captured.pause_reason!r}")
    capture.store.close()

    # -- the twins' shared config ---------------------------------------------------
    cfg_path = scratch / "journey.dev-ci.toml"
    _config_toml(cfg_path)
    from aeh.pipeline.runtime import _load_config_file

    cfg = _load_config_file(str(cfg_path))

    # -- console twin: the operator's surface ----------------------------------------
    console_dir = scratch / "console"
    console_store = _open_store_with(console_dir)
    export_seen: dict[str, object] = {}
    try:
        _catalog, version = _build_package(console_store)
        _console_cohort(console_store)
        assessment, sheets = _write_papers(
            scratch / "console-pdfs", pages_by_student, assessment_pages)
        _ingest_console(console_store, version, assessment, sheets)
        _serve_and_drive(
            console_store, console_dir, cfg, version, monkeypatch, export_seen)
    finally:
        _close(console_store)

    # -- CLI twin: the terminal's surface --------------------------------------------
    cli_dir = scratch / "cli"
    cli_store = _open_store_with(cli_dir)
    try:
        _catalog, version = _build_package(cli_store)
        _cli_cohort(scratch, monkeypatch)
        assessment, sheets = _write_papers(
            scratch / "cli-pdfs", pages_by_student, assessment_pages)
        _cli_ingest(cli_dir, version, assessment, sheets, cfg_path, monkeypatch)
        _cli_run(cli_dir, version, cfg_path, monkeypatch)
        _review_and_finalize(cli_store, _minted_run_id(cli_store, "the CLI twin's"))
    finally:
        _close(cli_store)

    # -- the oracle -------------------------------------------------------------------
    mask = jw.pairing_mask(console_dir, cli_dir)
    console_rows = jw.canonical_tier_rows(console_dir, mask=mask)
    cli_rows = jw.canonical_tier_rows(cli_dir, mask=mask)
    from tests.support.console_api_vocabulary import row_differences

    diffs = row_differences(console_rows, cli_rows)
    assert not diffs, (
        "TC-E2E-06: the same day's work wrote different stores — "
        f"{len(diffs)} table(s) differ:\n" + "\n".join(f"  {d}" for d in diffs[:12]))
    # The answers the teacher saw are the ones the export delivered.
    assert export_seen, "TC-E2E-06: the console's export leg never read the route"


def _build_package(store):
    """The package leg: the F-RUBRIC-METHODS shape through the real M-PKG writer, on
    both sides (module docstring — the console's setup screen writes through it)."""
    from tests.support import rubric_methods

    return rubric_methods.build(store, rubric_methods.rubric_methods())


def _ingest_console(store, version: str, assessment: Path, sheets: list[Path]) -> None:
    """The papers leg, console side: the papers-screen upload lands in the same intake
    pipeline (``provider=None`` crosses the patched ``_provider_for`` seam)."""
    from aeh.conf import CohortRef, resolve_run_config
    from aeh.pipeline.intake import answer_sheet_files, ingest_files

    cfg = effective_cfg()
    run_config = resolve_run_config(
        dict(cfg), CohortRef(cohort_id=jw.COHORT_ID, consent_class="synthetic"))
    result = ingest_files(
        store, run_config, jw.COHORT_ID, version, assessment=str(assessment),
        sheets=answer_sheet_files([str(p) for p in sheets]))
    bad = [(s.file, s.status, s.detail) for s in result.sheets if s.status != "ok"]
    assert not bad, f"the console twin's papers did not read: {bad}"


def effective_cfg():
    from tests.support.conf_builders import (
        HOSTED_PANEL_3, HOSTED_TRANSCRIBER, hosted_cfg,
    )
    from aeh.conf import effective_config

    return effective_config(hosted_cfg(
        "dev-ci", panel=HOSTED_PANEL_3, transcriber=HOSTED_TRANSCRIBER))


def _serve_and_drive(store, console_dir: Path, cfg: dict, version: str,
                     monkeypatch: pytest.MonkeyPatch, export_seen: dict) -> None:
    """The journey through the served SPA in a browser, plus the console's own leaves.

    The browser's legs are the hub, the seven lifecycle screens, the confirm dialog
    and the recovery wording; the leaves the SPA fronts (the start control, the export
    read, the help ask) are exercised over the same origin the SPA itself uses. The
    socket guard stands down under the ``browser`` marker (``tests/conftest.py`` — the
    Playwright driver's event loop needs a loopback socket pair in this interpreter),
    so the no-egress oracle here is the browser's own request log
    (``log.foreign_requests()``, asserted below) plus the model boundary: the twins'
    provider is the fixture replayer, and the ask leg's transport is the local stub,
    both bound before any request is made.
    """
    from aeh.console import help_read, serve_console

    # The ask leg's transport (module docstring): the QA model resolves to the effective
    # panel's first judge (FR-CONF-30, dev-ci → panel[0]), whose real transport is
    # OpenRouter — bound here to the stub instead, before the server can build its
    # assistant (built on the first ask and held).
    def _help_provider(_model_ref: object) -> _HelpReplay:
        return _HelpReplay()

    monkeypatch.setattr(help_read, "provider_for", _help_provider)

    server = serve_console(store=store, cfg=cfg)
    port = int(server.port)
    loopback_host = ".".join(("127", "0", "0", "1"))
    origin = f"http://{loopback_host}:{port}"
    try:
        with spa.spa_page(origin) as (page, log):
            # -- hub ------------------------------------------------------------
            spa.open_hub(page, origin)
            hub = spa.main_text(page)
            for destination in (*spa.LIFECYCLE_SCREENS, "help", "status"):
                card = spa.hub_card(page, destination)
                assert card.count() == 1, (
                    f"TC-E2E-06: the hub has no {destination!r} destination "
                    f"(found {card.count()}); the hub is the journey's map")
            # -- setup ----------------------------------------------------------
            _go(page, origin, "package")
            assert version in spa.main_text(page), (
                "TC-E2E-06: the package screen does not show the published version — "
                "the live-state read (#634) is not on the setup screen")
            # the setup read-back the teacher confirms against (#624)
            from aeh.setup import setup_service_for_store
            service = setup_service_for_store(store, _PACKAGE_ID)
            assert service.current_proposal() is not None, (
                "TC-E2E-06: SetupService's read-back does not see the published "
                "version's proposal — the setup screen would show nothing")
            # -- class ----------------------------------------------------------
            _go(page, origin, "class")
            roster_text = spa.main_text(page)
            for student in jw.STUDENTS:
                assert student.student_ref in roster_text, (
                    f"TC-E2E-06: the class screen does not show {student.student_ref!r}")
            # -- papers ---------------------------------------------------------
            _go(page, origin, "papers")
            papers_text = spa.main_text(page)
            for student in jw.STUDENTS:
                assert student.student_ref in papers_text, (
                    f"TC-E2E-06: the papers screen does not show {student.student_ref!r}'s "
                    "sheet")
            # -- run start: banner + confirm -------------------------------------
            before = spa.store_digest(console_dir)
            _go(page, origin, "run_start")
            banner_text = spa.main_text(page)
            assert "dev-ci" in banner_text, (
                f"TC-E2E-06: the run-start screen names no profile — the banner the "
                f"preview read answers is not rendered: {banner_text!r}")
            after = spa.store_digest(console_dir)
            assert not spa.changed_tables(before, after), (
                "TC-E2E-06: opening the run-start screen wrote rows — a no-op until "
                "confirmed (TC-UI-05)")
            # the start control opens the confirmation; confirming it — a click on
            # the dialog's own named button, TC-UI-05's idiom — posts the console's
            # own control
            dialog = _confirm_start(page)
            assert dialog is not None, (
                "TC-E2E-06: starting a run without a confirmation dialog — the "
                "journey's confirm step (NFR-SYS-17) is not on the screen")
            named = dialog.get_by_role("button", name=_START_ACTION)
            confirm = [named.nth(i) for i in range(named.count())
                       if not _CANCEL.search(named.nth(i).inner_text())]
            assert confirm, (
                "TC-E2E-06: the confirmation has no button naming the start action")
            confirm[0].click()
            # the SPA posts 'start run'; the run drives in the console's background,
            # keyed by the id M-ORCH minted — discover it, never assume one
            deadline = time.monotonic() + 60
            threads: dict = dict(getattr(server.app, "_run_threads", {}))
            while not threads and time.monotonic() < deadline:
                page.wait_for_timeout(200)
                threads = dict(getattr(server.app, "_run_threads", {}))
            assert threads, (
                "TC-E2E-06: confirming the start never reached the console's "
                "background — the control started no run")
            assert len(threads) == 1, (
                f"TC-E2E-06: the console's background holds {len(threads)} runs; "
                "the day's journey starts exactly one")
            run_id = next(iter(threads))
            handle = store.cohort(jw.COHORT_ID)
            status = _await_terminal(handle, run_id)
            assert status == "complete", (
                f"TC-E2E-06: the console twin's run did not complete: {status}")
            for thread in threads.values():
                thread.join(timeout=60)
            # -- monitor ---------------------------------------------------------
            _go(page, origin, "monitor")
            assert _TERMINAL_WORD.search(spa.main_text(page)), (
                "TC-E2E-06: the monitor screen does not show the run's terminal phase")
            # -- review ----------------------------------------------------------
            _go(page, origin, "review")
            assert spa.main_text(page), "TC-E2E-06: the review screen renders nothing"
            # the queue's band decisions, through the same M-REVIEW library the review
            # screen's controls call (both twins — module docstring)
            _work_review_queue(console_store, run_id)
            # finalize through the console's own control door, over the same origin
            # the SPA posts to — the same GradingService call the CLI twin makes below
            from tests.support.console_api_vocabulary import (
                get_bytes, post_json, refused,
            )

            status, outcome = post_json(
                port, "/api/v1/actions/finalize-batch",
                {"run_id": run_id, "actor": "teacher"})
            assert status == 200 and not refused(status, outcome), (
                f"TC-E2E-06: the console's finalize-batch control refused: "
                f"{status} {outcome!r}")
            # -- results ----------------------------------------------------------
            _go(page, origin, "results")
            assert spa.main_text(page), "TC-E2E-06: the results screen renders nothing"
            # the export bytes come back through the console's own read
            # (FR-CONSOLE-44): the marks CSV and one student's PDF, the artifacts the
            # walkthrough's step 11 reads back
            status, _headers, csv_bytes = get_bytes(
                port, "/api/v1/results/export",
                {"run_id": run_id, "format": "csv", "revision": "1"})
            assert status == 200 and csv_bytes, (
                f"TC-E2E-06: the results-export read returned {status}, "
                f"{len(csv_bytes) if csv_bytes else 0} bytes of CSV")
            export_seen["csv"] = len(csv_bytes)
            first = jw.STUDENTS[0]
            status, _headers, pdf_bytes = get_bytes(
                port, "/api/v1/results/export",
                {"run_id": run_id, "format": "pdf", "revision": "1",
                 "student_ref": first.student_ref})
            assert status == 200 and pdf_bytes[:5] == b"%PDF-", (
                f"TC-E2E-06: the per-student PDF export read returned {status}, "
                f"{pdf_bytes[:16]!r}")
            export_seen["pdf"] = first.student_ref
            # -- help -------------------------------------------------------------
            _go(page, origin, "help")
            assert spa.main_text(page), "TC-E2E-06: the help screen renders nothing"
            status_code, answer = _ask_help(port)
            assert status_code == 200 and answer, (
                f"TC-E2E-06: asking for help over the console API failed: "
                f"{status_code} {answer!r}")
            assert not log.foreign_requests(), (
                f"TC-E2E-06: the journey left the machine's boundary: "
                f"{log.foreign_requests()}")
            assert not spa.rejections(page), (
                f"TC-E2E-06: the journey left unhandled rejections: {spa.rejections(page)}")
    finally:
        server.terminate()


_PACKAGE_ID = "RUBRIC-METHODS"
_TERMINAL_WORD = re.compile(r"complete|finished|done", re.I)
#: The run-start control and its confirmation, named as TC-UI-05's vocabulary keys them.
_START_ACTION = re.compile(r"^\s*start", re.I)
_CANCEL = re.compile(r"cancel|back|no\b|keep|close|dismiss|^\s*[x×]\s*$", re.I)


def _go(page, origin: str, destination: str) -> None:
    spa.go_to(page, origin, destination)
    spa.wait_for_screen(page)


def _confirm_start(page):
    """Click the run-start control and return its confirmation dialog, or None.

    TC-UI-05's idiom: the action is a *button* on the screen, and the confirmation it
    opens is a dialog the test waits for — confirming is a click on the dialog's own
    named button (never ``Locator.accept()``, which exists only on the native
    ``page.on("dialog")`` object)."""
    buttons = page.locator("main").get_by_role("button", name=_START_ACTION)
    enabled = [buttons.nth(i) for i in range(buttons.count())
               if buttons.nth(i).is_enabled()]
    assert enabled, (
        "TC-E2E-06: the run-start screen offers no enabled start control — the "
        "journey's confirm step (NFR-SYS-17) is not on the screen")
    enabled[0].click()
    dialog = page.get_by_role("dialog").or_(page.get_by_role("alertdialog"))
    try:
        dialog.first.wait_for(state="visible", timeout=5_000)
    except Exception:
        return None
    return dialog.first


class _HelpReplay:
    """The ask leg's transport: a stub ``complete`` the HelpAssistant drives.

    The manuals' retrieval is local (M-HELP); only the one prose call needs answering,
    and no replay fixture can carry it — the QA prompt is a new shape the capture never
    recorded (only synthesis is allowed to miss, module docstring). So the leg binds a
    stub instead of a network transport: the ask stays on the machine's side of the
    boundary (CT-PROV-15) and its log still writes through the real M-HELP store path.
    Disclosed in the PR."""

    def complete(self, prompt: object, model_ref: object, params: object):
        from aeh.prov import Completion

        return Completion(
            text="Open the Results screen for a student's grades; the export there "
                 "writes the marks CSV and the per-student PDFs into the data folder.",
            tokens_in=10, tokens_out=5, latency_ms=1,
            resolved_build=getattr(model_ref, "build_id", ""),
            cached_prefix_tokens=0, cost=None)


def _ask_help(port: int) -> tuple[int, object]:
    """The ask-for-help leg over the same read-only endpoint the Q&A panel calls."""
    from tests.support.console_api_vocabulary import get_json

    return get_json(
        port, "/api/v1/help/ask",
        {"q": "How do I read a student's results and send them home?"})


def _work_review_queue(store, run_id: str) -> None:
    """The review leg's band decisions, through the M-REVIEW library the console's
    review screen and the CLI's review door both call — on BOTH twins, so the stores
    carry the same review actions (module docstring)."""
    from aeh.review import open_review

    review = open_review(store.data_dir, run_id=run_id, actor="teacher")
    try:
        review.build_queue(run_id, 30)
        for item in review.queue(run_id):
            # Populated in this world, never empty: one extraction family means
            # extractor_disagreement is None, which counts adverse fail-closed — the
            # hard cap (0.40) sits under the 0.90 holistic threshold, so every
            # multi-verdict cell routes "queued" here.
            if hasattr(item, "score_id"):
                review.act(item, "accept")
            else:  # a collapsed group is accepted as one band decision
                review.act_on_group(item, item.proposed_band)
    finally:
        review.close()


def _review_and_finalize(store, run_id: str) -> None:
    """The CLI twin's review and finalize legs: the same queue walk, then the batch
    settle through `GradingService` — the library the console's `finalize batch`
    control performs (the twins finalize through the same code)."""
    from aeh.grade import GradingService

    _work_review_queue(store, run_id)
    GradingService(store).finalize_batch(run_id, actor="teacher")


def _cli_cohort(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The class leg, CLI side: the real roster file through the real matcher."""
    from aeh.pipeline import cli

    roster = scratch / "cli-roster.txt"
    roster.write_text(
        "\n".join(student.student_ref for student in jw.STUDENTS) + "\n",
        encoding="utf-8", newline="\n")
    code = cli.main([
        "cohort", "create", "--data-dir", str(scratch / "cli"),
        "--cohort", jw.COHORT_ID, "--consent", "synthetic", "--roster", str(roster)])
    assert code == 0, "the CLI twin's cohort create failed"


def _cli_ingest(data_dir: Path, version: str, assessment: Path, sheets: list[Path],
                cfg_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The papers leg, CLI side: ``aeh ingest``."""
    from aeh.pipeline import cli

    code = cli.main([
        "ingest", "--data-dir", str(data_dir), "--cohort", jw.COHORT_ID,
        "--package-version", version, "--config", str(cfg_path),
        "--assessment", str(assessment),
        *[str(p) for p in sheets]])
    assert code == 0, "the CLI twin's ingest failed"


def _cli_run(data_dir: Path, version: str, cfg_path: Path,
             monkeypatch: pytest.MonkeyPatch) -> None:
    """The run leg, CLI side: ``aeh run`` drives the composed pipeline to completion."""
    from aeh.pipeline import cli

    code = cli.main([
        "run", "--data-dir", str(data_dir), "--cohort", jw.COHORT_ID,
        "--package-version", version, "--config", str(cfg_path)])
    assert code == 0, "the CLI twin's run did not complete"


def _close(store) -> None:
    """Close the store, tolerating a connection the console's request thread opened."""
    import sqlite3

    try:
        store.close()
    except sqlite3.ProgrammingError:
        pass
