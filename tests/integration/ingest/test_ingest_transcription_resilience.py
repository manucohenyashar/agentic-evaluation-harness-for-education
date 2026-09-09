"""The three-strike transcription resilience: quarantine the submission, complete the cohort (`M-INGEST`).

Case `TC-INGEST-40` of test plan §5.5 (`NFR-INGEST-02`, Resilience / rung 1, P0) —
TS-16's remainder (issue #235): #45 closed without shipping it (disclosed there as
F3), and #220 shipped the behavior it names. The strike loop lives in
`_transcribe_page` (`HARNESS_INGEST_TRANSCRIPTION_ATTEMPTS`, default 3, read at
call time); exhausting it raises `IngestTranscriptionError`, which
`ingest_submission` catches into an honest quarantine — V0 pass, V1 fail, V2/V3
`not_reached`, status `unreadable`, `quarantined = 1` — with the strike log in the
report's stage detail, and the cohort's remaining submissions continue.

Reconciliation with the contract suite: `CT-INGEST-C14`'s fault case
(`tests/contract/ingest/test_ct_ingest_failure_taxonomy.py`) already pins the
single-submission containment shape — the honest gate columns, the three-entry
strike log, no partial artifact, retryability through a fresh ingestor. This file
is the row's own oracle and holds only what C14 does not: the exact
**transport-level** call count (read off the provider double, not just off the
report's log), the knob's **call-time read** (raise and lower it with the same
ingestor instance and watch the count follow), the mid-strike **recovery** shape,
the knob's declared edges, and the **cohort-completion** half — a submission that
strikes out does not stop the cohort's remaining submissions from ingesting to
completion, and no exception escapes the ingest call (`NFR-INGEST-02`'s "not the
run").

Rung 1: the VLM, sanitizer and rasterizer are scripted doubles with the same
shapes the #45/#46 suites pin; the store, blob directory and cohort handle are
real. `Written ahead of implementation: no` — the implementation exists (#220);
these cases run green by design.
"""

from __future__ import annotations

import json

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    Ingestor,
    PageImage,
    PdfSanitizer,
    ResidencySlot,
    SanitizeResult,
    TRANSCRIPTION_ATTEMPTS_ENV,
)
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store

pytestmark = pytest.mark.integration

ISSUE = "#235"

#: The cohort handle name the fixture opens. One cohort file IS one cohort.
COHORT = "c-tc40"


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:bbbb", quantization="q4")


class ThroughSanitizer(PdfSanitizer):
    """The fast-tier sanitizer double: no constructs, the bytes pass through."""

    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        return SanitizeResult(pdf_bytes=pdf_bytes)


class ScriptedRasterizer:
    """A rasterizer double: `plan` maps source bytes to a page list."""

    def __init__(self, plan: dict | None = None) -> None:
        self.plan = plan or {}
        self.calls: list[bytes] = []

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.calls.append(bytes(pdf_bytes))
        pages = self.plan.get(bytes(pdf_bytes),
                              [(1, b"page-one", 1000, 1400)])
        return [PageImage(page_no=page_no, png=png, width_px=w, height_px=h)
                for page_no, png, w, h in pages]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class ScriptedProvider:
    """A provider double keyed per (source blob, page) — one deterministic
    `Completion` per call, every call recorded. The call record is the oracle
    for the strike count: read off the transport itself, not just off the
    report's log."""

    def __init__(self, texts: dict | None = None) -> None:
        self.texts = texts or {}
        self.calls: list[tuple[str, int]] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        key = (fields["source_blob_hash"], int(fields["page_no"]))
        self.calls.append(key)
        return Completion(text=self.texts.get(key, "plain page"),
                          tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class FaultedProvider(ScriptedProvider):
    """The fault-injected transport (the row's technique): a key in
    `fail_forever` dies on every call — strikes out, never recovers; a key in
    `fail_times` dies until its counter is spent, then answers from `texts`
    (the recovery scripting). Each `complete` call is recorded exactly once."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_forever: set[tuple[str, int]] = set()
        self.fail_times: dict[tuple[str, int], int] = {}

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        key = (fields["source_blob_hash"], int(fields["page_no"]))
        if key in self.fail_forever:
            self.calls.append(key)
            raise RuntimeError("injected: the model channel died")
        remaining = self.fail_times.get(key, 0)
        if remaining > 0:
            self.fail_times[key] = remaining - 1
            self.calls.append(key)
            raise RuntimeError(f"injected strike; {remaining} strike(s) left")
        return super().complete(prompt, model_ref, params)


class _Fixture:
    """One fresh store, cohort, blob dir and ingestor over them."""

    def __init__(self, tmp_data_dir, name: str) -> None:
        self.root = tmp_data_dir / f"{ISSUE.strip('#')}-{name}"
        self.store = open_store(self.root)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(COHORT)
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class,"
                       " created_at) VALUES ('c-tc40', 'synthetic', 'x')")
        self.rasterizer = ScriptedRasterizer()
        self.provider = FaultedProvider()
        slot = ResidencySlot.for_policy(("transcriber",))
        self.ingestor = Ingestor(self.handle, self.blobs, self.provider,
                                 _model(), SamplingParams(temperature=0.0),
                                 self.rasterizer, residency=slot,
                                 sanitizer=ThroughSanitizer())

    def put(self, content: bytes) -> str:
        return self.blobs.put(content)

    def script(self, source: str, page_texts: dict[int, str]) -> None:
        for page_no, text in page_texts.items():
            self.provider.texts[(source, page_no)] = text

    def add_roster(self, *refs: str) -> None:
        with self.handle.transaction() as tx:
            for ref in refs:
                tx.execute("INSERT INTO roster (cohort_id, student_ref) "
                           "VALUES ('c-tc40', :r)", r=ref)

    def submission_rows(self) -> list:
        return self.handle.query("SELECT submission_id, student_ref, "
                                 "v0_integrity, v1_pages, v2_structure, "
                                 "v3_identity, ingest_status, quarantined "
                                 "FROM submission")

    def documents(self) -> list:
        return self.handle.query("SELECT document_id, submission_id "
                                 "FROM document")

    def close(self) -> None:
        self.store.close()


def _student_answer(name: str | None, *regions: str) -> str:
    head = f"Student: {name}\n" if name else ""
    return head + "\n".join(regions)


def _answer_text(question_id: str, body: str) -> str:
    return (f"<!-- region: kind=transcribed_text question_id={question_id} "
            f"state=present -->\n{body}\n<!-- /region -->")


# -- TC-INGEST-40: three strikes quarantine the submission, exactly counted -------


def test_tc_ingest_40_three_strikes_quarantine_the_submission_and_are_counted(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-40` (quarantine half) — a page whose transcription fails three
    times: the transport was asked EXACTLY three times for that page (and once
    for its healthy sibling — the strike count is per page), the call returns a
    quarantine report (no exception escapes), the row is an honestly-marked
    quarantine — V0 pass, V1 fail, V2/V3 `not_reached`, `quarantined = 1`, never
    a NULL-gates `quarantined=0` zombie — the healthy page's transcript is not
    partially stored, the strike log is in the report's stage detail, and the
    SAME ingestor immediately ingests the next submission cleanly (nothing per-
    instance is left poisoned — the residency slot included)."""
    # The exact-3 assertion pins the SHIPPED default; a box that sets the knob
    # (its documented purpose) must not skew it.
    monkeypatch.delenv(TRANSCRIPTION_ATTEMPTS_ENV, raising=False)
    fx = _Fixture(tmp_data_dir, "strikes")
    fx.add_roster("gus")
    source = fx.put(b"tc40 two pages")
    fx.rasterizer.plan[b"tc40 two pages"] = [(1, b"page-one", 1000, 1400),
                                             (2, b"page-two", 1000, 1400)]
    fx.script(source, {1: _student_answer("gus", _answer_text("Q1", "one")),
                       2: _student_answer(None, _answer_text("Q2", "two"))})
    fx.provider.fail_forever.add((source, 2))

    report = fx.ingestor.ingest_submission([source], cohort_id=COHORT,
                                           package_version="v0",
                                           filenames={source: "gus.pdf"})

    assert fx.provider.calls.count((source, 2)) == 3, (
        f"TC-INGEST-40: the transport was not asked exactly three times for "
        f"the faulted page: {fx.provider.calls.count((source, 2))} calls."
    )
    assert fx.provider.calls.count((source, 1)) == 1, (
        f"TC-INGEST-40: the healthy sibling page was retried or skipped: "
        f"{fx.provider.calls.count((source, 1))} calls."
    )
    assert report.ingest_status == "unreadable" and report.gates["v1"] == "fail", (
        f"TC-INGEST-40: the three-strike submission did not quarantine: "
        f"{report.ingest_status} / {report.gates}."
    )
    assert (report.gates["v0"] == "pass"
            and report.gates["v2"] == "not_reached"
            and report.gates["v3"] == "not_reached"), (
        f"TC-INGEST-40: the quarantine's gate columns are not honest: "
        f"{report.gates}."
    )
    strikes = report.detail["transcription_attempts"]
    assert len(strikes) == 3 and [s["attempt"] for s in strikes] == [1, 2, 3], (
        f"TC-INGEST-40: the strike log is not the three-strike limit: "
        f"{strikes}."
    )
    assert all(s["page_no"] == 2 and s["blob_hash"] == source[:12]
               and "injected" in s["error"] for s in strikes), (
        f"TC-INGEST-40: the strike log does not name the faulted page and the "
        f"injected fault: {strikes}."
    )
    finding_text = json.dumps(report.detail["findings"])
    assert "3 attempt" in finding_text, (
        f"TC-INGEST-40: the quarantine finding does not name the strike-out "
        f"for the operator: {finding_text[:300]}."
    )
    row = fx.submission_rows()[0]
    assert (row["quarantined"] == 1 and row["ingest_status"] == "unreadable"
            and row["v0_integrity"] == "pass" and row["v1_pages"] == "fail"
            and row["v2_structure"] == "not_reached"
            and row["v3_identity"] == "not_reached"), (
        f"TC-INGEST-40: the struck-out submission's row is a NULL-gates "
        f"`quarantined=0` zombie, not an honestly-marked quarantine: "
        f"{dict(row)}."
    )
    assert fx.documents() == [] and fx.handle.query(
        "SELECT COUNT(*) AS n FROM document_region")[0]["n"] == 0, (
        "TC-INGEST-40: the healthy page's transcript was partially stored — "
        "a strike-out must store nothing (no document, no regions)."
    )

    # The cohort continues on the SAME ingestor: the next submission ingests
    # cleanly — nothing per-instance (the residency slot included) is left
    # poisoned by the strike-out.
    fx.add_roster("hana")
    healthy = fx.put(b"tc40 next submission")
    fx.script(healthy, {1: _student_answer("hana", _answer_text("Q1", "fine"))})
    report = fx.ingestor.ingest_submission([healthy], cohort_id=COHORT,
                                           package_version="v0",
                                           filenames={healthy: "hana.pdf"})
    assert report.ingest_status == "ok", (
        f"TC-INGEST-40: the submission after a strike-out did not ingest "
        f"cleanly on the same ingestor: {report.ingest_status}."
    )
    assert fx.provider.calls.count((healthy, 1)) == 1, (
        "TC-INGEST-40: the healthy page after a strike-out was retried."
    )
    fx.close()


# -- TC-INGEST-40: the strike limit is the knob's call-time read -------------------


def test_tc_ingest_40_the_strike_limit_is_the_knobs_call_time_read(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-40` (the knob) — the strike limit is
    `HARNESS_INGEST_TRANSCRIPTION_ATTEMPTS` read AT CALL TIME: the SAME ingestor
    instance strikes out after one attempt with the knob lowered and after five
    with it raised — the transport count follows the knob in both directions,
    so it is the knob and not a hard-coded three. Strikes are retries, not a
    kill: a channel that dies twice and recovers completes the page on attempt
    three (`ok`, the two strikes logged with the last one marked recovered).
    The knob's declared edges — `0` and junk — refuse before the model is
    asked: through the gateway the refusal is a contained V0 quarantine with
    zero transport calls, never an escape."""
    fx = _Fixture(tmp_data_dir, "knob")
    fx.add_roster("gus", "hana")

    # Lowered to 1: exactly one attempt, then the quarantine.
    monkeypatch.setenv(TRANSCRIPTION_ATTEMPTS_ENV, "1")
    low = fx.put(b"tc40 knob one")
    fx.script(low, {1: _student_answer("gus", _answer_text("Q1", "one"))})
    fx.provider.fail_forever.add((low, 1))
    report = fx.ingestor.ingest_submission([low], cohort_id=COHORT,
                                           package_version="v0",
                                           filenames={low: "low.pdf"})
    assert fx.provider.calls.count((low, 1)) == 1, (
        f"TC-INGEST-40: with the knob at 1 the transport was asked "
        f"{fx.provider.calls.count((low, 1))} times, not once."
    )
    assert report.ingest_status == "unreadable", (
        f"TC-INGEST-40: the one-strike submission did not quarantine: "
        f"{report.ingest_status}."
    )

    # Raised to 5 — SAME ingestor instance: the knob is read at call time, not
    # bound at construction or import.
    monkeypatch.setenv(TRANSCRIPTION_ATTEMPTS_ENV, "5")
    high = fx.put(b"tc40 knob five")
    fx.script(high, {1: _student_answer("hana", _answer_text("Q1", "two"))})
    fx.provider.fail_forever.add((high, 1))
    report = fx.ingestor.ingest_submission([high], cohort_id=COHORT,
                                           package_version="v0",
                                           filenames={high: "high.pdf"})
    assert fx.provider.calls.count((high, 1)) == 5, (
        f"TC-INGEST-40: with the knob at 5 the transport was asked "
        f"{fx.provider.calls.count((high, 1))} times, not five — the limit is "
        "not read at call time."
    )
    assert len(report.detail["transcription_attempts"]) == 5, (
        f"TC-INGEST-40: the strike log does not carry the five strikes: "
        f"{report.detail['transcription_attempts']}."
    )

    # Recovery: two strikes, then the channel answers — the page completes and
    # the log says which attempt recovered.
    monkeypatch.delenv(TRANSCRIPTION_ATTEMPTS_ENV, raising=False)
    mid = fx.put(b"tc40 knob recovery")
    fx.script(mid, {1: _student_answer("gus", _answer_text("Q1", "three"))})
    fx.provider.fail_times[(mid, 1)] = 2
    report = fx.ingestor.ingest_submission([mid], cohort_id=COHORT,
                                           package_version="v0",
                                           filenames={mid: "mid.pdf"})
    assert report.ingest_status == "ok", (
        f"TC-INGEST-40: a channel that recovers within the strike limit did "
        f"not complete the page: {report.ingest_status}."
    )
    assert fx.provider.calls.count((mid, 1)) == 3, (
        f"TC-INGEST-40: the recovering page was not asked exactly three times "
        f"(two strikes, one recovery): {fx.provider.calls.count((mid, 1))}."
    )
    strikes = report.detail["transcription_attempts"]
    assert [s["attempt"] for s in strikes] == [1, 2], (
        f"TC-INGEST-40: the recovery log is not the two strikes: {strikes}."
    )
    assert strikes[-1]["outcome"] == "recovered", (
        f"TC-INGEST-40: the recovered strike is not marked as such: {strikes}."
    )

    # The knob's declared edges: below 1 and junk refuse before the model is
    # asked — zero transport calls, contained as a V0 quarantine by the
    # gateway, never an escape.
    for bad in ("0", "junk"):
        monkeypatch.setenv(TRANSCRIPTION_ATTEMPTS_ENV, bad)
        edge = fx.put(f"tc40 knob edge {bad}".encode())
        fx.script(edge, {1: _student_answer("gus", _answer_text("Q1", "x"))})
        report = fx.ingestor.ingest_submission([edge], cohort_id=COHORT,
                                               package_version="v0",
                                               filenames={edge: "edge.pdf"})
        assert report.ingest_status == "unreadable" and report.gates["v0"] == "fail", (
            f"TC-INGEST-40: the {TRANSCRIPTION_ATTEMPTS_ENV}={bad!r} edge did "
            f"not refuse as a contained V0 quarantine: {report.ingest_status} "
            f"/ {report.gates}."
        )
        assert fx.provider.calls.count((edge, 1)) == 0, (
            f"TC-INGEST-40: the model was asked under an invalid knob "
            f"({bad!r}) — the knob must refuse before the first attempt."
        )
    fx.close()


# -- TC-INGEST-40: the quarantined submission does not stop the cohort -------------


def test_tc_ingest_40_the_quarantined_submission_does_not_stop_the_cohort(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-40` (cohort-completion half) — a three-submission cohort whose
    MIDDLE member strikes out: the ingest loop runs to completion (no exception
    escapes any call), the struck-out submission quarantines honestly after
    exactly three transport calls, and both remaining submissions ingest to
    completion with their outcomes intact — `ok`, their documents and regions
    stored, their identity matched. The store holds exactly one quarantine, and
    it is the faulted member's."""
    monkeypatch.delenv(TRANSCRIPTION_ATTEMPTS_ENV, raising=False)
    fx = _Fixture(tmp_data_dir, "cohort")
    fx.add_roster("ana", "bruno", "caro")
    sources: dict[str, str] = {}
    for ref, body in (("ana", "one"), ("bruno", "two"), ("caro", "three")):
        source = fx.put(f"tc40 cohort {ref}".encode())
        fx.script(source,
                  {1: _student_answer(ref, _answer_text("Q1", body))})
        sources[ref] = source
    fx.provider.fail_forever.add((sources["bruno"], 1))

    # The caller's cohort loop, as the orchestrator drives it: one call per
    # roster member. If a strike-out escaped, the loop would die here.
    reports = {}
    for ref in ("ana", "bruno", "caro"):
        reports[ref] = fx.ingestor.ingest_submission(
            [sources[ref]], cohort_id=COHORT, package_version="v0",
            filenames={sources[ref]: f"{ref}.pdf"})

    assert set(reports) == {"ana", "bruno", "caro"}, (
        f"TC-INGEST-40: the cohort loop did not reach every submission: "
        f"{sorted(reports)} — an exception escaped the ingest call."
    )
    bruno = reports["bruno"]
    assert bruno.ingest_status == "unreadable" and bruno.gates["v1"] == "fail", (
        f"TC-INGEST-40: the faulted submission did not quarantine: "
        f"{bruno.ingest_status} / {bruno.gates}."
    )
    assert (bruno.gates["v0"] == "pass"
            and bruno.gates["v2"] == "not_reached"
            and bruno.gates["v3"] == "not_reached"), (
        f"TC-INGEST-40: the faulted submission's gates are not honest: "
        f"{bruno.gates}."
    )
    assert len(bruno.detail["transcription_attempts"]) == 3, (
        f"TC-INGEST-40: the faulted submission's strike log is not three: "
        f"{bruno.detail['transcription_attempts']}."
    )
    assert fx.provider.calls.count((sources["bruno"], 1)) == 3, (
        f"TC-INGEST-40: the faulted page was asked "
        f"{fx.provider.calls.count((sources['bruno'], 1))} times, not three."
    )
    for ref in ("ana", "caro"):
        report = reports[ref]
        assert report.ingest_status == "ok", (
            f"TC-INGEST-40: the cohort member after the quarantine ({ref}) did "
            f"not ingest to completion: {report.ingest_status}."
        )
        assert report.gates["v0"] == "pass" and report.gates["v1"] == "pass", (
            f"TC-INGEST-40: {ref}'s gates did not pass: {report.gates}."
        )
        assert fx.provider.calls.count((sources[ref], 1)) == 1, (
            f"TC-INGEST-40: {ref}'s healthy page was not asked exactly once."
        )
    rows = {row["submission_id"]: row for row in fx.submission_rows()}
    assert len(rows) == 3, (
        f"TC-INGEST-40: the store does not hold one row per submission: "
        f"{len(rows)} rows."
    )
    bruno_row = rows[reports["bruno"].submission_id]
    assert (bruno_row["quarantined"] == 1
            and bruno_row["ingest_status"] == "unreadable"
            and bruno_row["v0_integrity"] == "pass"
            and bruno_row["v1_pages"] == "fail"
            and bruno_row["v2_structure"] == "not_reached"
            and bruno_row["v3_identity"] == "not_reached"), (
        f"TC-INGEST-40: bruno's row is a NULL-gates `quarantined=0` zombie, "
        f"not an honestly-marked quarantine: {dict(bruno_row)}."
    )
    assert bruno_row["student_ref"] == "unknown", (
        f"TC-INGEST-40: the quarantined row was assigned an identity "
        f"({bruno_row['student_ref']!r}) — V3 never ran, so only the "
        "`unknown` placeholder may stand; guessing one is the TC-INGEST-27 "
        "refusal."
    )
    quarantined = [row["student_ref"] for row in rows.values()
                   if row["quarantined"] == 1]
    assert quarantined == ["unknown"], (
        f"TC-INGEST-40: the quarantine did not stay on the faulted member: "
        f"{quarantined}."
    )
    for ref in ("ana", "caro"):
        row = rows[reports[ref].submission_id]
        assert row["quarantined"] == 0 and row["ingest_status"] == "ok", (
            f"TC-INGEST-40: {ref}'s outcome did not survive the cohort run: "
            f"{dict(row)}."
        )
        assert row["student_ref"] == ref, (
            f"TC-INGEST-40: {ref}'s completed submission is not matched to "
            f"its identity: {row['student_ref']!r}."
        )
    documents = fx.documents()
    assert len(documents) == 2, (
        f"TC-INGEST-40: the cohort's completed submissions do not hold exactly "
        f"two documents: {documents}."
    )
    for document in documents:
        regions = fx.handle.query(
            "SELECT COUNT(*) AS n FROM document_region "
            "WHERE document_id = :d", d=document["document_id"])[0]["n"]
        assert regions > 0, (
            f"TC-INGEST-40: a completed submission stored a document with no "
            f"regions: {document}."
        )
    fx.close()
