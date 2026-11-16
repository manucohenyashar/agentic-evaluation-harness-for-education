"""`TC-CONSOLE-123` — page reading, priced and capped (FR-CONSOLE-97, FR-PROV-09; RSV-32).

Statistical-validity test plan r2 §3.23, story T21 (issue #905). **Written ahead of S30 (#872)**,
which is open: these cases carry `writtenahead` and are registered in `WRITTEN_AHEAD_BLOCKERS`
under "#872". Remove the marker — never the test — when #872 lands, and re-check them green.

SV-33: page reading ran before a run existed and counted against no ceiling (R5). FR-CONSOLE-97:
the Papers confirmation states the estimated cost of reading the selected files (pages x the
transcriber's per-page estimate from `estimate_cost`) on a remote profile and *"no cost: local
models"* on `edge-local`; a reading job stops dispatching when its spend reaches
`HARNESS_READ_COST_CEILING`, pauses with the reason named on Papers and Jobs, resumes from the
next unread file (sheets already read are kept), and records its spend on the job.

World: `tests/support/reading_world.py` — `TC-CONSOLE-77`'s console over the sample physics
class, with a stand-in OpenRouter that prices every page request at 0.02 and a reader whose
`estimate_cost` answers 0.0042 per call (so pages x estimate is exact whatever token budgets the
implementation picks).

Interface bets (the design names no console surface for these; each is one line to reconcile
when #872 lands, and the red names #872 rather than an unrelated crash):

| Bet | Used for |
|---|---|
| `GET /api/v1/papers/estimate?cohort_id=<id>&pages=<n>` answering `{"estimate": <decimal string or null>, "text": <sentence>}` | the confirmation's figure and its "no cost: local models" sentence |
| The estimate is priced by the same reader-provider factory the reading job uses (`aeh.pipeline.background._provider_for`) | the exact figure |
| A paused reading job reads `state == "paused"` (or `paused: true`) on `GET /api/v1/jobs/<id>`; its reason is a sentence (any string value) on the job record and on `GET /api/v1/papers` naming the 0.01 figure | the pause and its reason |
| `POST /api/v1/actions/resume-reading` with `{"cohort_id", "job_id"}` is **Resume** | the resume |
| The job record carries the spend as `spend`, or in the jobs read's existing `cost_usd` field | the recorded spend |
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from tests.support.reading_world import (
    PER_PAGE_ESTIMATE,
    is_paused,
    make_class,
    reading_world,
    request,
    upload,
    wait_settled,
)

pytestmark = pytest.mark.writtenahead

_BLOCKER = "S30 (#872) has not landed"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _names_the_ceiling(document) -> bool:
    """Some sentence in the document names the 0.01 figure and the limit it is."""
    words = ("ceiling", "limit", "cost", "spend", "spent")
    return any("0.01" in text and any(w in text.lower() for w in words)
               for text in _strings(document))


@pytest.fixture
def world(tmp_data_dir, monkeypatch, capsys, network_guard):
    yield from reading_world(tmp_data_dir, monkeypatch, capsys, network_guard)


def test_tc_console_123_the_papers_confirmation_states_pages_times_the_per_page_estimate(world):
    port = world["port"]
    make_class(port, world["roster"])
    pages = 7
    status, answer = request(port, "GET", f"/api/v1/papers/estimate?cohort_id=ps9-class&pages={pages}")
    assert status == 200, f"FR-CONSOLE-97: no reading estimate read ({_BLOCKER}): {answer!r}"
    assert Decimal(str(answer["estimate"])) == pages * PER_PAGE_ESTIMATE, answer
    assert world["fake"].requests == [], "an estimate must send nothing to the page reader"


def test_tc_console_123_edge_local_reads_no_cost_local_models(tmp_data_dir, network_guard):
    """`edge-local`: the confirmation carries no figure and says so in the teacher's words."""
    from aeh.conf import effective_config, parse_config_document
    from aeh.console import serve_console
    from aeh.pipeline.runtime import _open_store

    weights = "@sha256:" + "0" * 64
    text = "\n".join([
        'HARNESS_PROFILE = "edge-local"', 'HARNESS_HARDWARE_PROFILE = "unified-large"',
        'HARNESS_DECISION_ENGINE = "off"', 'prompt_template_v = "conf-v1.0.0"', "",
        "[transcriber]", 'role = "transcriber"', 'provider = "local"',
        f'build_id = "/models/qwen3-vl-8b-q4.gguf{weights}"', 'quantization = "q4"',
        'served_as = "qwen3-vl:8b"', "",
        "[[panel]]", 'role = "judge"', 'provider = "local"',
        f'build_id = "/models/qwen3-30b-q4.gguf{weights}"', 'quantization = "q4"',
        'served_as = "qwen3:30b"', "",
    ])
    from tests.support.guards import loopback_census

    store = _open_store(str(tmp_data_dir))
    server = serve_console(store, cfg=effective_config(parse_config_document(text, "toml")))
    census = loopback_census(network_guard)
    census.__enter__()
    try:
        make_class(server.port, "S9-001\nS9-002")
        status, answer = request(server.port, "GET",
                                 "/api/v1/papers/estimate?cohort_id=ps9-class&pages=7")
        assert status == 200, f"FR-CONSOLE-97: no reading estimate read ({_BLOCKER}): {answer!r}"
        assert answer["estimate"] is None, answer
        assert "no cost: local models" in answer["text"], answer
    finally:
        census.__exit__(None, None, None)
        server.terminate()
        try:
            store.close()
        except Exception:  # noqa: BLE001 - a connection opened on a request thread
            pass


def test_tc_console_123_the_ceiling_pauses_after_the_first_file_and_resume_rereads_nothing(
        world, monkeypatch):
    port, version, fake = world["port"], world["version"], world["fake"]
    make_class(port, world["roster"])
    monkeypatch.setenv("HARNESS_READ_COST_CEILING", "0.01")
    stems = list(world["sheets"])[:3]

    # Every file is queued into the one job before the first finishes (the gate), so "after
    # the first file" is the ceiling's doing and not an upload race.
    fake.hold()
    status, answer = upload(port, world["paper"], cohort_id="ps9-class", package_version=version,
                            kind="assessment", filename="01-test-paper.pdf")
    assert status == 200 and answer["dispatched"] is True, answer
    job_id = answer["job_id"]
    for stem in stems:
        status, answer = upload(port, world["sheets"][stem], cohort_id="ps9-class",
                                package_version=version, kind="sheet", filename=f"{stem}.pdf")
        assert status == 200 and answer["job_id"] == job_id, answer
    fake.release()

    record = wait_settled(port, job_id)
    assert is_paused(record), (
        f"FR-CONSOLE-97: the reading job did not pause at HARNESS_READ_COST_CEILING=0.01 "
        f"({_BLOCKER}); it read {len(set(fake.page_hashes))} file(s): {record!r}")
    # Paused after the first file: only the test paper was sent.
    assert set(fake.page_hashes) == {world["paper_hash"]}, fake.page_hashes
    spent_requests = len([r for r in fake.requests if r.method == "POST"])
    # The job row records its spend: what the reader billed so far.
    spend = record.get("spend", record.get("cost_usd"))
    assert spend is not None, record
    # A tolerance below a thousandth of a cent: an implementation may sum the reported float
    # costs, and that drift is not what this clause is about.
    assert abs(Decimal(str(spend)) - Decimal(fake.cost) * spent_requests) < Decimal("0.00001"), record
    # The reason is named on Jobs and on Papers: a sentence (a string value, not a key or a
    # number elsewhere in the record) naming the ceiling's figure and what it limits.
    assert _names_the_ceiling(record), f"the paused job names no ceiling reason: {record!r}"
    status, papers = request(port, "GET", "/api/v1/papers?cohort_id=ps9-class")
    assert status == 200 and _names_the_ceiling(papers), (
        f"the Papers read names no ceiling reason: {papers!r}")

    # Resume (the teacher raises the ceiling first): continues from the next unread file.
    monkeypatch.setenv("HARNESS_READ_COST_CEILING", "10")
    status, answer = request(port, "POST", "/api/v1/actions/resume-reading", json.dumps(
        {"cohort_id": "ps9-class", "job_id": job_id}).encode("utf-8"))
    assert status == 200 and answer.get("dispatched") is True, answer
    resumed = wait_settled(port, answer.get("job_id") or job_id)
    assert resumed["state"] == "succeeded", resumed
    wanted = [world["paper_hash"]] + [world["sheet_hashes"][s] for s in stems]
    assert sorted(set(fake.page_hashes)) == sorted(wanted), "a queued file was never read"
    reread = sorted(h for h in set(fake.page_hashes) if fake.page_hashes.count(h) > 1)
    assert reread == [], f"FR-CONSOLE-97: resume re-read {reread}"
