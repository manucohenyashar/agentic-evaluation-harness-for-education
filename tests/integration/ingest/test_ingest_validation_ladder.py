"""The validation ladder V0-V3, the status vocabulary, and quarantine routing (`M-INGEST`).

Cases `TC-INGEST-23`, `-24`, `-26` (its absent/blank half), `-27`, `-29`, `-30`, `-31`
and `-32` of test plan §5.5 (TS-16, issue #45), run against the ladder #40 landed.
Rung 2 — real Tier C files, real blob directories; the VLM, sanitizer and rasterizer are
scripted doubles with the same shapes the gateway suite pins. `Written ahead of
implementation: yes` is stale for the ladder itself — #40 shipped it; these cases run
green by design.

The implementation audit behind this file probed the shipped module and found five
places where the plan's oracle is not yet enforced. They are **disclosed here rather
than shipped red** (the `writtenahead` registry keys on things that do not exist yet;
a bug in shipped code has no such target), each with its probe evidence:

- **F1** (`TC-INGEST-26`'s first input): a question the package declares but the
  transcript omits produced **no V2 failure** — the gate iterated the regions that
  existed and never the declared set, and `_absent_regions` (the expected-region read
  the plan's oracle needs) had no call site in the module. Probe: catalog declaring
  `Q1`..`Q3`, transcript carrying `Q1`/`Q2` → `gates[v2] == "pass"`, no failure.
  The half this file pins is the plan's most dangerous consequence: nothing may
  record the absent question as a blank answer. **Closed by #219**: the declared-set
  check is wired into V2 (`_absent_regions` mints each missing question its own
  `absent` row) and the gate names the missing ids; the test below asserts the
  live form.
- **F2** (`TC-INGEST-26`'s second input): an `mcq` question whose selection mark is
  ambiguous was **no V2 failure either** — the gate refused a selection only where the
  package declares `open`, and never asked whether a declared-`mcq` selection
  resolved. Probe: ambiguous mark under a declared `mcq` → `gates[v2] == "pass"`
  (and V4 then *matched* the submission). **Closed by #219**: an unresolved
  selection under a declared `mcq` is a V2 failure naming the question, and the
  submission quarantines as `incomplete` — asserted below.
- **F3** (`TC-INGEST-40`, whole case): a page whose transcription fails is **not
  contained** — the provider's exception escapes `ingest_submission` raw (the module
  has no transcription retry loop; the only re-request loop is the evaluative-
  description one), leaving the submission row inserted with NULL gate columns and
  killing the caller's cohort loop. `NFR-INGEST-02` / the class docstring promise the
  opposite ("fail the unit, never the run"). No test ships: the case's every
  observable (quarantine + cohort completion) is the behaviour that is missing.
- **F4** (`TC-INGEST-23`'s fifth fixture): a raster below the profile's resolution
  floor ingests — `HARNESS_INGEST_RESOLUTION_FLOOR` (default 150) is declared but
  read by nothing; only the pixel *ceiling* is checked. Probe: a 50x70 px page →
  `gates[v0] == "pass"`. **Closed by #227**: the floor is enforced at the
  post-raster integrity gate, the fixture below runs live.
- **F5** (`TC-INGEST-31`'s third input): two files with **identical** filenames are
  silently ordered by the filename tier (a stable sort over the caller's blob
  order) — ambiguity is never detected. The no-numbers/no-markers/no-filenames
  refusal works and is pinned below. **Closed by #227**: the filename tier
  refuses a natural-key collision over blobs, naming the colliding files.

Rung notes, stated rather than silently substituted: `TC-INGEST-30` and `-32` are
rung 3 (real neighbouring modules) but `M-CONSOLE` and `M-REVIEW` do not exist yet.
The achievable rung is the ingest-side routing — the quarantine data the operator
surface reads, and the module's write set — because that routing is `M-INGEST`'s
decision; the rendered-queue halves are already owned by the console and review
contract suites (`CT-CONSOLE-C12`, `CT-REVIEW-05`, keyed on their stories).
"""

from __future__ import annotations

import re

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    INGEST_STATEMENTS,
    IngestGapError,
    IngestSanitizeError,
    Ingestor,
    PageImage,
    PdfSanitizer,
    ResidencySlot,
    SanitizeResult,
)
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store

pytestmark = pytest.mark.integration

ISSUE = "#45"

#: The `ingest_status` vocabulary (FR-INGEST-29) — exactly five values, and the five
#: stage names of the design's state model are deliberately NOT among them.
INGEST_STATUSES = ("ok", "low_confidence_ocr", "unreadable", "incomplete",
                   "unmatched_assessment")
NOT_STATUSES = ("scored", "quarantined", "transcribed", "uploaded", "validated")

#: The tables `M-INGEST`'s declared statements may write — the routing boundary
#: FR-INGEST-30 holds at the module level.
INGEST_OWNED_TABLES = {"submission", "document", "document_region",
                       "token_cluster", "unresolved_token",
                       "assessment_match_proposal", "v4_cohort_breaker"}
FORBIDDEN_TABLE_PATTERN = re.compile(r"review|label|queue|grade|score|band")


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:bbbb", quantization="q4")


class ThroughSanitizer(PdfSanitizer):
    """The fast-tier sanitizer double: no constructs, the bytes pass through."""

    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        return SanitizeResult(pdf_bytes=pdf_bytes)


class RefusingSanitizer(PdfSanitizer):
    """Refuses one source the way the live `PypdfSanitizer` refuses an unreadable
    one — before any rasterization, so the V0 stage must resolve to quarantine."""

    def __init__(self, message: str) -> None:
        self.message = message
        self.asked: list[bytes] = []

    def sanitize(self, pdf_bytes, *, strip=True, **kwargs):
        self.asked.append(bytes(pdf_bytes))
        raise IngestSanitizeError(self.message)


class ScriptedRasterizer:
    """A rasterizer double: `plan` maps source bytes to a page list; every call and
    every layer request is recorded so a test can prove a stage never ran."""

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
    `Completion` per call, every call recorded."""

    def __init__(self, texts: dict | None = None) -> None:
        self.texts = texts or {}
        self.calls: list[tuple[str, str]] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        key = (fields["source_blob_hash"], int(fields["page_no"]))
        self.calls.append(key)
        return Completion(text=self.texts.get(key, "plain page"),
                          tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class _Fixture:
    """One fresh store, cohort, blob dir and ingestor over them."""

    def __init__(self, tmp_data_dir, name: str, sanitizer=None,
                 rasterizer: ScriptedRasterizer | None = None) -> None:
        self.root = tmp_data_dir / f"{ISSUE.strip('#')}-{name}"
        self.store = open_store(self.root)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort("c-ladder")
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, "
                       "created_at) VALUES ('c-ladder', 'synthetic', 'x')")
        self.rasterizer = rasterizer or ScriptedRasterizer()
        self.provider = ScriptedProvider()
        slot = ResidencySlot.for_policy(("transcriber",))
        self.ingestor = Ingestor(self.handle, self.blobs, self.provider,
                                 _model(), SamplingParams(temperature=0.0),
                                 self.rasterizer, residency=slot,
                                 sanitizer=sanitizer or ThroughSanitizer())

    def put(self, content: bytes) -> str:
        return self.blobs.put(content)

    def script(self, source: str, page_texts: dict[int, str]) -> None:
        for page_no, text in page_texts.items():
            self.provider.texts[(source, page_no)] = text

    def add_roster(self, *refs: str) -> None:
        with self.handle.transaction() as tx:
            for ref in refs:
                tx.execute("INSERT INTO roster (cohort_id, student_ref) "
                           "VALUES ('c-ladder', :r)", r=ref)

    def catalog(self, kinds: list[str]):
        from aeh.pkg import PackageCatalog, PackageDraft

        seed = self.store.package("pkg-ladder")
        with seed.transaction() as tx:
            tx.execute("INSERT INTO package (package_id, created_at) "
                       "VALUES ('pkg-ladder', 'x')")
        catalog = PackageCatalog(seed, package_id="pkg-ladder")
        version = catalog.create_version(None, PackageDraft(title="ladder"))
        for index, kind in enumerate(kinds, start=1):
            catalog.add_criterion(version, f"C{index}", question_id=f"Q{index}",
                                  kind=kind, max_points=4.0)
        return catalog, version

    def submission_rows(self) -> list:
        return self.handle.query("SELECT submission_id, student_ref, "
                                 "v0_integrity, v1_pages, v2_structure, "
                                 "v3_identity, v4_match, ingest_status, "
                                 "quarantined FROM submission")

    def close(self) -> None:
        self.store.close()


def _student_answer(name: str | None, *regions: str) -> str:
    head = f"Student: {name}\n" if name else ""
    return head + "\n".join(regions)


def _answer_text(question_id: str, body: str) -> str:
    return (f"<!-- region: kind=transcribed_text question_id={question_id} "
            f"state=present -->\n{body}\n<!-- /region -->")


def _selection(question_id: str, state: str, option: str = "") -> str:
    return (f"<!-- region: kind=selection_mark question_id={question_id} "
            f"selection_state={state} selection={option} -->\n"
            "the mark as seen\n<!-- /region -->")


def _written_tables() -> set[str]:
    """Every table `aeh.ingest`'s declared statements write — the module's whole
    write surface, read from the declared-literal registry rather than from a
    database at runtime, so a new write cannot pass unnoticed."""
    pattern = re.compile(r"(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|"
                         r"DELETE\s+FROM)\s+([a-z0-9_]+)", re.IGNORECASE)
    tables: set[str] = set()
    for statement in INGEST_STATEMENTS.values():
        sql = statement.sql if hasattr(statement, "sql") else str(statement)
        tables.update(match.group(1).lower() for match in pattern.finditer(sql))
    return tables


# -- TC-INGEST-23: the V0 file-integrity sweep -----------------------------------------------------


@pytest.mark.parametrize("case", ["unopenable", "encrypted", "zero-page", "blank",
                                  "below-floor"])
def test_tc_ingest_23_v0_sweep_quarantines_unreadable_and_never_proceeds(
        tmp_data_dir, case):
    """`TC-INGEST-23` — each V0 fixture quarantines as `unreadable`, never reaches a
    later gate, and costs **zero VLM calls** (the oracle names the unopenable and
    encrypted cases; the zero-page, blank and below-floor refusals also end before
    the first transcript is requested, which the sweep asserts for all five).

    The sweep's fifth fixture — a file below the profile's resolution floor — went
    live with #227: `HARNESS_INGEST_RESOLUTION_FLOOR` (default 150) is enforced at
    the post-raster integrity gate (F4 in the module docstring was the disclosure)."""
    refusal = {
        "unopenable": RefusingSanitizer("the source is not a PDF (no header)"),
        "encrypted": RefusingSanitizer("the source is encrypted; an unreadable "
                                       "artifact cannot be ingested"),
    }.get(case)
    plan = {
        "zero-page": {b"source": []},
        "blank": {b"source": [(1, b" ", 1000, 1400), (2, b" ", 1000, 1400),
                              (3, b"drawn", 1000, 1400)]},
        "below-floor": {b"source": [(1, b"page-one", 50, 70)]},
    }.get(case)
    fx = _Fixture(tmp_data_dir, f"v0-{case}", sanitizer=refusal,
                  rasterizer=ScriptedRasterizer(plan) if plan is not None else None)
    source = fx.put(b"source")

    report = fx.ingestor.ingest_submission([source], cohort_id="c-ladder",
                                           package_version="v0",
                                           filenames={source: "scan-01.md"})

    assert report.gates["v0"] == "fail", (
        f"TC-INGEST-23 ({case}): the V0 gate column does not record the failure — "
        "each gate's outcome lives in its own column (FR-INGEST-29).")
    assert report.ingest_status == "unreadable", (
        f"TC-INGEST-23 ({case}): a V0 refusal quarantines as `unreadable` "
        "(FR-INGEST-21), not "
        f"{report.ingest_status!r}.")
    assert report.detail["findings"], (
        f"TC-INGEST-23 ({case}): the quarantine carries no operator finding.")
    row = fx.submission_rows()[0]
    assert row["quarantined"] == 1, (
        f"TC-INGEST-23 ({case}): the quarantine state is on the row — that is what "
        "the operator surface reads (FR-INGEST-30).")
    assert fx.provider.calls == [], (
        f"TC-INGEST-23 ({case}): the VLM was called for an unreadable source — "
        f"V0 ends the ladder before any transcript is requested.")
    assert fx.handle.query("SELECT COUNT(*) AS n FROM document")[0]["n"] == 0, (
        f"TC-INGEST-23 ({case}): an unreadable source must not store a document.")
    if case == "below-floor":
        joined = "\n".join(str(f["finding"]) for f in report.detail["findings"])
        assert "50x70px" in joined and "150" in joined, (
            "TC-INGEST-23 (below-floor): the refusal must name the measured "
            "resolution and the profile's floor for the operator, got: "
            f"{joined!r}.")
    if isinstance(refusal, RefusingSanitizer):
        assert fx.rasterizer.calls == [], (
            f"TC-INGEST-23 ({case}): the refused source was rasterized anyway — "
            "the sanitizer refusal precedes rasterization.")
    fx.close()


# -- TC-INGEST-24: V1 names the specific pages -----------------------------------------------------


def test_tc_ingest_24_v1_quarantines_naming_the_specific_pages(tmp_data_dir):
    """`TC-INGEST-24` — fewer pages than declared, a repeated printed page and a
    duplicated sheet each quarantine **naming the specific pages** (the oracle is the
    named positions, not merely a failure); a complete stack passes the gate."""
    fx = _Fixture(tmp_data_dir, "v1")

    # Fewer pages than declared: three rasters printed 'of 5' — the continuation
    # sheets (printed 4 and 5) never arrived.
    source = fx.put(b"stack-of-five")
    fx.rasterizer.plan[b"stack-of-five"] = [(1, b"a", 1000, 1400),
                                            (2, b"b", 1000, 1400),
                                            (3, b"c", 1000, 1400)]
    fx.script(source, {1: "Page 1 of 5, the ink is fresh",
                       2: "Page 2 of 5, the margin is clean",
                       3: "Page 3 of 5, the fold is sharp"})
    report = fx.ingestor.ingest_submission([source], cohort_id="c-ladder",
                                           package_version="v0",
                                           filenames={source: "scan-01.md"})
    joined = "\n".join(str(f["finding"]) for f in report.detail["findings"])
    assert report.gates["v1"] == "fail", (
        "TC-INGEST-24: the V1 column does not record the gap.")
    assert report.ingest_status == "incomplete"
    assert "missing positions [4, 5]" in joined, (
        f"TC-INGEST-24: the quarantine must name the specific missing pages, "
        f"got: {joined!r} (FR-INGEST-22).")
    assert fx.handle.query("SELECT COUNT(*) AS n FROM document")[0]["n"] == 0

    # A repeated printed page: two sheets printed 'Page 1 of 2' beside the real
    # page 2 — the printed set is complete, so the repeat is what the gate names.
    source = fx.put(b"repeated-page")
    fx.rasterizer.plan[b"repeated-page"] = [(1, b"a", 1000, 1400),
                                            (2, b"b", 1000, 1400),
                                            (3, b"c", 1000, 1400)]
    fx.script(source, {1: "Page 1 of 2, first pass words",
                       2: "Page 1 of 2, second differing words",
                       3: "Page 2 of 2, closing remarks with other words"})
    report = fx.ingestor.ingest_submission([source], cohort_id="c-ladder",
                                           package_version="v0",
                                           filenames={source: "scan-02.md"})
    joined = "\n".join(str(f["finding"]) for f in report.detail["findings"])
    assert report.gates["v1"] == "fail" and report.ingest_status == "incomplete"
    assert "repeats positions [1]" in joined, (
        f"TC-INGEST-24: the quarantine must name the duplicated page, got: "
        f"{joined!r} (FR-INGEST-22).")

    # A duplicated sheet with no printed numbers at all: the duplicate detector
    # names the two pages it refuses to concatenate (FR-INGEST-08).
    source = fx.put(b"duplicated-sheet")
    fx.rasterizer.plan[b"duplicated-sheet"] = [(1, b"a", 1000, 1400),
                                               (2, b"b", 1000, 1400)]
    fx.script(source, {1: "the duplicated sheet reads exactly this",
                       2: "the duplicated sheet reads exactly this"})
    report = fx.ingestor.ingest_submission([source], cohort_id="c-ladder",
                                           package_version="v0",
                                           filenames={source: "scan-03.md"})
    joined = "\n".join(str(f["finding"]) for f in report.detail["findings"])
    assert report.gates["v1"] == "fail" and report.ingest_status == "incomplete"
    assert "page 1" in joined and "page 2" in joined, (
        f"TC-INGEST-24: the duplicate quarantine names both pages, got: "
        f"{joined!r}.")
    assert "Surface for" in joined, (
        "TC-INGEST-24: duplicates are surfaced for confirmation, never "
        "concatenated (FR-INGEST-08).")

    # The control: a complete, correctly numbered stack passes V1.
    source = fx.put(b"complete-stack")
    fx.rasterizer.plan[b"complete-stack"] = [(1, b"a", 1000, 1400),
                                             (2, b"b", 1000, 1400)]
    fx.add_roster("amara-o")
    fx.script(source, {1: "Student: amara-o\nPage 1 of 2, opening remarks",
                       2: "Page 2 of 2, closing remarks with other words"})
    report = fx.ingestor.ingest_submission([source], cohort_id="c-ladder",
                                           package_version="v0",
                                           filenames={source: "scan-04.md"})
    assert report.gates["v1"] == "pass", (
        "TC-INGEST-24: a complete stack must pass the gate.")
    assert report.ingest_status == "ok"
    fx.close()


# -- TC-INGEST-26: an absent region is never a blank answer ----------------------------------------


def test_tc_ingest_26_an_absent_region_is_never_recorded_as_a_blank_answer(
        tmp_data_dir):
    """`TC-INGEST-26` (first input, live since #219) — the package declares `Q3`;
    the transcript never carries it. The gate must fail V2 **naming the missing
    question**, and whatever the ladder records for the absent question must read
    `absent`, NEVER `blank`: blank is a legitimate zero, absent is a scanning
    failure, and collapsing them mis-scores the student (FR-INGEST-16/23). The
    designed shape — which `TC-INGEST-17`'s expected-region read pins — is an
    `absent` row of its own; #219 wired `_absent_regions` into the ladder, so the
    row is now required, not merely tolerated (the F1 disclosure above recorded
    the pre-fix silence)."""
    fx = _Fixture(tmp_data_dir, "v2-absent")
    catalog, version = fx.catalog(["open", "mcq", "open"])
    source = fx.put(b"missing-q3")
    fx.script(source, {1: _student_answer(
        "amara-o",
        _answer_text("Q1", "the worked answer, quite unlike anything else"),
        _selection("Q2", "resolved", "B"))})
    report = fx.ingestor.ingest_submission(
        [source], cohort_id="c-ladder", package_version=version,
        package_catalog=catalog, filenames={source: "scan-01.md"})

    # The named gap: V2 fails, and the failure names the missing question id
    # (FR-INGEST-23's routing promise — the operator reads the id, not a bare
    # failure).
    assert report.gates["v2"] == "fail", (
        "TC-INGEST-26: a question the package declares with no region in the "
        "transcript must fail the structure gate (FR-INGEST-23).")
    named = [f for f in report.detail["v2_failures"]
             if f["question_id"] == "Q3"]
    assert named and "no region for a question" in named[0]["finding"], (
        "TC-INGEST-26: the V2 gap does not name the missing question: "
        f"{report.detail['v2_failures']!r}.")
    rows = fx.handle.query(
        "SELECT element_kind, content_state FROM document_region "
        "WHERE document_id = :d", d=report.document_id)
    recorded = {row["element_kind"]: row["content_state"] for row in rows}
    assert recorded.get("Q3") != "blank", (
        "TC-INGEST-26: the absent question is recorded as a BLANK answer — blank "
        "is a legitimate zero, absent is a scanning failure (FR-INGEST-16).")
    assert recorded.get("Q3") == "absent", (
        f"TC-INGEST-26: the absent question's own row reads "
        f"{recorded.get('Q3')!r} — the designed value is `absent`, minted by the "
        "declared-set read (FR-INGEST-16, TC-INGEST-17).")
    # The submission halts at V2: quarantined, `incomplete` — it never advances
    # to scoring, so the absent question can never be read as a blank answer.
    # V4's own verdict is still recorded (the plan's decision table needs the
    # recorded signals), but an `uncertain` there is the same missing question
    # V2 already named and must not rename the diagnosis.
    row = next(r for r in fx.submission_rows()
               if r["submission_id"] == report.submission_id)
    assert row["quarantined"] == 1 and row["ingest_status"] == "incomplete", (
        f"TC-INGEST-26: the missing-question submission must quarantine as "
        f"`incomplete`, got quarantined={row['quarantined']}, "
        f"status={row['ingest_status']!r} (FR-INGEST-23).")
    assert report.gates["v4"] != "match", (
        "TC-INGEST-26: an incomplete paper must not be V4-MATCHED into "
        "proceeding — the submission halted at V2 (FR-INGEST-23).")
    fx.close()


def test_tc_ingest_26_an_unresolved_mcq_selection_is_a_v2_failure(
        tmp_data_dir):
    """`TC-INGEST-26` (second input, live since #219) — an `mcq` region whose
    selection mark did not resolve is a V2 failure routed to the operator,
    naming the question (FR-INGEST-23). Disclosed in this file's docstring (F2,
    probe from #45): the gate used to refuse a selection only where the package
    declares `open` and never asked whether a declared-`mcq` selection resolved —
    the ambiguous mark passed V2 and V4 then matched the submission. The honest
    stored pair (`CT-INGEST-05`'s biconditional) is asserted beside the gate."""
    fx = _Fixture(tmp_data_dir, "v2-mcq-unresolved")
    fx.add_roster("amara-o")
    catalog, version = fx.catalog(["mcq"])
    source = fx.put(b"unresolved-mcq")
    fx.script(source, {1: _student_answer(
        "amara-o", _selection("Q1", "ambiguous"))})
    report = fx.ingestor.ingest_submission(
        [source], cohort_id="c-ladder", package_version=version,
        package_catalog=catalog, filenames={source: "scan-01.md"})

    assert report.gates["v2"] == "fail", (
        "TC-INGEST-26: an mcq question whose selection did not resolve must "
        "fail the structure gate (FR-INGEST-23).")
    named = [f for f in report.detail["v2_failures"]
             if f["question_id"] == "Q1"]
    assert named and "unresolved selection" in named[0]["finding"], (
        "TC-INGEST-26: the V2 gap does not name the question and its "
        f"unresolved selection: {report.detail['v2_failures']!r}.")
    row = next(r for r in fx.submission_rows()
               if r["submission_id"] == report.submission_id)
    assert row["quarantined"] == 1 and row["ingest_status"] == "incomplete", (
        f"TC-INGEST-26: the unresolved-selection submission must quarantine as "
        f"`incomplete`, got quarantined={row['quarantined']}, "
        f"status={row['ingest_status']!r} (FR-INGEST-23).")
    regions = fx.handle.query(
        "SELECT selection_state, selection FROM document_region "
        "WHERE document_id = :d AND region_kind = 'selection_mark'",
        d=report.document_id)
    assert regions and regions[0]["selection_state"] == "ambiguous" \
        and regions[0]["selection"] is None, (
        "TC-INGEST-26: the ambiguous mark did not store the honest pair — "
        f"{dict(regions[0])!r} (CT-INGEST-05).")
    fx.close()


# -- TC-INGEST-27: identity is matched or routed, never guessed ------------------------------------


@pytest.mark.parametrize("case", ["exact", "ambiguous", "unmatched", "absent"])
def test_tc_ingest_27_identity_is_matched_or_routed_never_guessed(
        tmp_data_dir, case):
    """`TC-INGEST-27` — the three-way: an exact roster match proceeds; an ambiguous
    match and a non-match route to triage **carrying the candidate options**, and in
    neither case is a `student_ref` ever assigned. The identity-less transcript is
    the fourth routing: the absence itself is the finding."""
    fx = _Fixture(tmp_data_dir, f"v3-{case}")
    roster = {"exact": ("amara-o", "benito"),
              "ambiguous": ("amara-o", "amara-o-2"),
              "unmatched": ("amara-o", "benito"),
              "absent": ("amara-o",)}[case]
    fx.add_roster(*roster)
    declared = {"exact": "amara-o", "ambiguous": "amara",
                "unmatched": "zelda", "absent": None}[case]
    source = fx.put(f"identity-{case}".encode())
    fx.script(source, {1: _student_answer(declared,
                                          _answer_text("Q1", "the worked answer"))})
    report = fx.ingestor.ingest_submission(
        [source], cohort_id="c-ladder", package_version="v0",
        filenames={source: "scan-01.md"})
    joined = "\n".join(str(f["finding"]) for f in report.detail["findings"])
    row = fx.submission_rows()[0]

    if case == "exact":
        assert report.gates["v3"] == "pass" and row["ingest_status"] == "ok", (
            "TC-INGEST-27: an exact roster match proceeds to a clean ingest.")
        assert row["student_ref"] == "amara-o", (
            "TC-INGEST-27: the matched identity is recorded on the row.")
        assert row["quarantined"] == 0
        return
    assert row["quarantined"] == 1, (
        f"TC-INGEST-27 ({case}): an unresolved identity quarantines — it is never "
        "guessed (FR-INGEST-24).")
    assert row["student_ref"] == "unknown", (
        f"TC-INGEST-27 ({case}): no student_ref may be assigned to a "
        f"{case} identity (FR-INGEST-24).")
    if case == "ambiguous":
        assert report.gates["v3"] == "ambiguous"
        assert "candidates: ['amara-o', 'amara-o-2']" in joined, (
            "TC-INGEST-27: the triage item carries the candidate options, got: "
            f"{joined!r}.")
    elif case == "unmatched":
        assert report.gates["v3"] == "unmatched"
        assert "does not match the roster" in joined
    else:
        assert "no student identity found" in joined, (
            "TC-INGEST-27: the identity-less transcript routes on its absence, "
            f"got: {joined!r}.")
    fx.close()


# -- TC-INGEST-29: per-gate columns, the status vocabulary, the transition matrix ------------------


def test_tc_ingest_29_per_gate_columns_status_vocabulary_and_transitions(
        tmp_data_dir):
    """`TC-INGEST-29` — the schema half of the state model: each gate's outcome in
    its own column (never one boolean), `ingest_status` inside exactly the five
    declared values (the state model's stage names are refused by the CHECK), the
    legal re-ingest transition, and the single-writer rule that makes the illegal
    transitions unreachable.

    (`low_confidence_ocr` was, until #221, accepted by the schema but produced by
    no ladder path — that disclosure is closed: a clean ladder with a reading
    below the confidence floor flags it, admissible like `ok`.)"""
    fx = _Fixture(tmp_data_dir, "v29")
    columns = {row["name"] for row in fx.handle.query(
        "PRAGMA table_info(submission)")}
    for column in ("v0_integrity", "v1_pages", "v2_structure", "v3_identity",
                   "v4_match", "ingest_status", "quarantined"):
        assert column in columns, (
            f"TC-INGEST-29: the submission schema has no {column!r} column — "
            "each gate's outcome is its own column (FR-INGEST-29).")

    # The vocabulary: every declared status is representable; every stage name of
    # the state model (and 'scored') is refused by the CHECK constraint itself.
    with fx.handle.transaction() as tx:
        for status in INGEST_STATUSES:
            tx.execute("INSERT INTO submission (submission_id, cohort_id, "
                       "student_ref, ingest_status) VALUES (:s, 'c-ladder', "
                       "'r', :st)", s=f"vocab-{status}", st=status)
        for status in NOT_STATUSES:
            with pytest.raises(Exception) as refused:
                tx.execute("INSERT INTO submission (submission_id, cohort_id, "
                           "student_ref, ingest_status) VALUES (:s, 'c-ladder', "
                           "'r', :st)", s=f"refused-{status}", st=status)
            assert type(refused.value).__name__ == "IntegrityError", (
                f"TC-INGEST-29: ingest_status {status!r} must be refused by the "
                f"schema, got {type(refused.value).__name__}.")

    # Mixed outcomes land in their own columns: V0 passes while V2 fails on the
    # same submission — no boolean collapse (CT-INGEST-08).
    catalog, version = fx.catalog(["open", "open"])
    source = fx.put(b"mixed-outcome")
    fx.script(source, {1: _student_answer("amara-o",
                                          _selection("Q1", "resolved", "A"))})
    fx.add_roster("amara-o")
    report = fx.ingestor.ingest_submission(
        [source], cohort_id="c-ladder", package_version=version,
        package_catalog=catalog, filenames={source: "scan-01.md"})
    row = next(r for r in fx.submission_rows()
               if r["submission_id"] == report.submission_id)
    assert row["v0_integrity"] == "pass" and row["v2_structure"] == "fail", (
        "TC-INGEST-29: a mixed submission carries each gate's own outcome — "
        f"got v0={row['v0_integrity']!r}, v2={row['v2_structure']!r}.")
    quarantined_id = report.submission_id
    quarantined_row = dict(row)

    # The legal transition: the quarantined submission re-enters as a NEW
    # submission (operator action, corrected scan); the failed row is never
    # rewritten, and the corrected one proceeds to `ok`.
    corrected = fx.put(b"corrected-scan")
    fx.script(corrected, {1: _student_answer(
        "amara-o",
        _answer_text("Q1", "the worked answer, quite unlike anything else"),
        _answer_text("Q2", "a second answer with different words here"))})
    again = fx.ingestor.ingest_submission(
        [corrected], cohort_id="c-ladder", package_version=version,
        package_catalog=catalog, filenames={corrected: "scan-fixed.md"})
    assert again.submission_id != quarantined_id, (
        "TC-INGEST-29: a re-ingest is a NEW submission, not a rewrite of the "
        "quarantined row (the design's re-entry rule).")
    assert again.ingest_status == "ok" and again.gates["v2"] == "pass", (
        "TC-INGEST-29: the corrected submission passes the gate that quarantined "
        "its predecessor.")
    after = next(r for r in fx.submission_rows()
                 if r["submission_id"] == quarantined_id)
    assert dict(after) == quarantined_row, (
        "TC-INGEST-29: the quarantined row is immutable across the re-ingest.")

    # The illegal transitions have no door: the ladder's single gate write is the
    # only statement that touches `ingest_status`, and nothing in the module's
    # declared write set can reach a score, a grade, or either queue.
    writers = [name for name, statement in INGEST_STATEMENTS.items()
               if "ingest_status" in (statement.sql
                                      if hasattr(statement, "sql")
                                      else str(statement))
               and "UPDATE" in (statement.sql if hasattr(statement, "sql")
                                else str(statement))]
    assert writers == ["update_submission_gates"], (
        f"TC-INGEST-29: ingest_status is written from more than the ladder's own "
        f"gate update: {writers!r}.")
    written = _written_tables()
    assert written <= INGEST_OWNED_TABLES, (
        f"TC-INGEST-29: the ingest module writes outside its declared surface: "
        f"{sorted(written - INGEST_OWNED_TABLES)!r}.")
    reached = sorted(t for t in written if FORBIDDEN_TABLE_PATTERN.search(t))
    assert reached == [], (
        "TC-INGEST-29: no transition leads from a gate failure to a score — the "
        f"module's write set reaches {reached!r} (CT-INGEST-09, FR-INGEST-30).")
    fx.close()


# -- TC-INGEST-30: quarantine routes to the operator surface, and nowhere else ---------------------


def test_tc_ingest_30_nine_quarantines_reach_the_operator_surface_alone(
        tmp_data_dir):
    """`TC-INGEST-30` — a cohort with nine quarantined submissions: all nine are on
    the operator surface (the quarantine state the console's route reads), **zero**
    appear in the teacher review queue — queried directly on the shipped
    `review_queue` table, as the plan's oracle names — and the module's write set
    carries them nowhere else (no review, label, queue, grade or score table is
    reachable from any declared ingest statement).

    Rung note: the rendered halves of this case are already owned by the console
    and review contract suites (`CT-CONSOLE-C12`'s
    `no_quarantine_item_is_reachable_from_the_review_queue`, `CT-REVIEW-05`'s
    never-rendered populations), keyed on their stories; what `M-INGEST` owes is
    the routing decision itself, which is what is pinned here."""
    fx = _Fixture(tmp_data_dir, "v30", sanitizer=RefusingSanitizer(
        "the source is not a PDF (no header)"))
    for index in range(9):
        source = fx.put(f"quarantined-{index}".encode())
        report = fx.ingestor.ingest_submission(
            [source], cohort_id="c-ladder", package_version="v0",
            filenames={source: f"scan-{index:02d}.md"})
        assert report.ingest_status == "unreadable"

    rows = fx.submission_rows()
    assert len(rows) == 9
    assert all(row["quarantined"] == 1 for row in rows), (
        "TC-INGEST-30: every quarantined submission is on the operator surface — "
        "the row's quarantine state is what that surface reads (FR-INGEST-30).")
    assert all(row["v0_integrity"] == "fail" for row in rows)

    assert fx.handle.query("SELECT COUNT(*) AS n FROM review_queue")[0]["n"] == 0, (
        "TC-INGEST-30: the teacher review queue holds one of the nine — quarantined "
        "items route to the operator surface only (FR-INGEST-30).")

    written = _written_tables()
    assert written <= INGEST_OWNED_TABLES, (
        f"TC-INGEST-30: the ingest module writes outside its surface: "
        f"{sorted(written - INGEST_OWNED_TABLES)!r}.")
    reached = sorted(t for t in written if FORBIDDEN_TABLE_PATTERN.search(t))
    assert reached == [], (
        "TC-INGEST-30: a quarantined item must never reach the teacher review "
        f"queue — the module's write set reaches {reached!r} (FR-INGEST-30).")
    fx.close()


# -- TC-INGEST-31: the order is requested, never guessed -------------------------------------------


@pytest.mark.parametrize("case", ["no-order-info", "identical-filenames",
                                  "digit-variant-filenames"])
def test_tc_ingest_31_the_order_is_requested_never_guessed(tmp_data_dir, case):
    """`TC-INGEST-31` — two sheets, no printed page numbers, no fiducial markers,
    no operator order: the ladder quarantines and asks the operator, and **no
    document row is created** — no order is guessed. The plan's three inputs: no
    filenames at all; two files sharing an identical name; and two distinct names
    the natural key cannot separate (`page-1.md` vs `page-01.md` — the
    order-ambiguous spelling variant). All three refuse identically (#227 closed
    the F5 disclosure: identical names were silently ordered by a stable sort
    over the caller's blob order).

    The two transcription calls are the ladder's own price (FR-INGEST-02, one
    call per page): the page-number tier is only decidable from transcripts, so
    reaching the filename tier costs exactly the per-page baseline and the
    refusal itself spends none — pinned as the two-call baseline. (The gate
    column that records the refusal is `v0` — the order ladder's
    `IngestOrderError` shares `IngestError`'s handler — which this test does not
    pin: the design names no column for an order refusal.)"""
    fx = _Fixture(tmp_data_dir, f"v31-{case}")
    first = fx.put(b"sheet-one")
    second = fx.put(b"sheet-two")
    fx.script(first, {1: "alpha sheet, wholly distinct prose"})
    fx.script(second, {1: "beta sheet, entirely other words"})
    filenames = {
        "no-order-info": None,
        "identical-filenames": {first: "scan.md", second: "scan.md"},
        "digit-variant-filenames": {first: "page-1.md", second: "page-01.md"},
    }[case]

    report = fx.ingestor.ingest_submission([first, second],
                                           cohort_id="c-ladder",
                                           package_version="v0",
                                           filenames=filenames)

    joined = "\n".join(str(f["finding"]) for f in report.detail["findings"])
    assert report.ingest_status == "unreadable", (
        f"TC-INGEST-31 ({case}): an indeterminable order quarantines "
        "(FR-INGEST-31).")
    assert "state the order and re-ingest" in joined, (
        f"TC-INGEST-31 ({case}): the quarantine asks the operator for the "
        f"order, got: {joined!r}.")
    assert fx.handle.query("SELECT COUNT(*) AS n FROM document")[0]["n"] == 0, (
        f"TC-INGEST-31 ({case}): no order is guessed — no document row exists.")
    assert fx.submission_rows()[0]["quarantined"] == 1
    assert len(fx.provider.calls) == 2, (
        f"TC-INGEST-31 ({case}): the refusal spent model calls of its own — the "
        "two transcription calls are the ladder's one-per-page price "
        "(FR-INGEST-02); the refusal adds none.")
    if filenames is not None:
        for name in filenames.values():
            assert repr(name) in joined, (
                f"TC-INGEST-31 ({case}): the refusal must name the colliding "
                f"filenames, got: {joined!r}.")
    fx.close()


# -- TC-INGEST-32: setup-artifact failures surface to the teacher ----------------------------------


@pytest.mark.parametrize("kind", ["assessment", "reference", "rubric"])
@pytest.mark.parametrize("stage", ["v0", "v1"])
def test_tc_ingest_32_setup_failures_surface_to_the_teacher_never_to_quarantine(
        tmp_data_dir, kind, stage):
    """`TC-INGEST-32` — a V0 and a V1 failure on an `assessment`, a `reference` and
    a `rubric` artifact surface to the uploading teacher (the exception propagates
    to the upload handler — that hand-off is the surface), and nothing enters the
    operator quarantine: no submission row exists at all, so the operator queue
    count is unchanged.

    Rung note: the upload-screen rendering half is `M-CONSOLE`'s (S2's screens,
    #123/#126; `CT-SETUP-12` carries the same clause for the setup flow) — this
    pins the `M-INGEST` half, which is where the routing decision lives."""
    refusing = None
    if stage == "v0":
        refusing = RefusingSanitizer("the source is not a PDF (no header)")
    fx = _Fixture(tmp_data_dir, f"v32-{kind}-{stage}", sanitizer=refusing)
    source = fx.put(b"setup-artifact")
    if stage == "v0":
        expected = IngestSanitizeError
    else:
        fx.rasterizer.plan[b"setup-artifact"] = [(1, b"a", 1000, 1400),
                                                 (2, b"b", 1000, 1400)]
        fx.script(source, {1: "Page 1 of 3, the printed header page",
                           2: "Page 2 of 3, the printed body page"})
        expected = IngestGapError

    with pytest.raises(expected) as raised:
        fx.ingestor.ingest_document([source], kind=kind)

    assert "not a PDF" in str(raised.value) or "missing positions" in str(
        raised.value), (
        f"TC-INGEST-32 ({kind} {stage}): the teacher surfaces the reason, got: "
        f"{raised.value!r}.")
    assert fx.handle.query("SELECT COUNT(*) AS n FROM submission")[0]["n"] == 0, (
        f"TC-INGEST-32 ({kind} {stage}): a setup artifact is not a submission — "
        "its failure must not enter the operator quarantine (FR-INGEST-32).")
    assert fx.handle.query("SELECT COUNT(*) AS n FROM submission "
                           "WHERE quarantined = 1")[0]["n"] == 0
    fx.close()
