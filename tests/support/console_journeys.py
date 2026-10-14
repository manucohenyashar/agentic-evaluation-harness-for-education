"""Shared machinery for the console-redesign journey tests (TC-E2E-08..12).

The journeys share one shape: an authoring leg (replayed from the committed corpus
recordings), a run leg (captured in-test by `JourneyCaptureProvider` — no committed
recording is needed for it), the twin drive (console surface vs CLI surface), and the
pairing oracle. This module holds what those legs must agree on, so a captured
recording and the test that replays it cannot drift apart, and the whole twin drive a
journey runs, parameterized by a `JourneySpec`.

The authoring builds
--------------------

The corpus's existing recordings (AF-01..13) were captured on the qwen builds
`console_redesign_world.RECORDED_TRANSCRIBER` / `RECORDED_JUDGE` pin. Those builds can
no longer serve this account: OpenRouter's zero-retention routing removes every Qwen
endpoint with "Model bloc" (verified 2026-10-14 by dispatching the pinned build and the
unpinned slug through `OpenRouterProvider.enforcing_zero_retention()`; the same probe
removed gpt-oss and llama endpoints for the same reason). The operator's own live-test
configuration made the same move (`docs/live-tests/config/live-test.dev-ci.toml` pins
`openai/gpt-6-luna@2026-06-01`, and the live runs of 2026-10-09/10 rode it).

The AF-14..21 recordings are therefore captured on — and their replays pin —
`JOURNEY_AUTHORING_BUILD`. The request key hashes the build id with the rest of the
request, so a capture and the test that replays it must name the same build: both read
it from here. The corpus's older recordings are untouched (their keys still carry the
qwen builds they were captured under, and the tests that replay them still pin those
constants).

The capture divergence the journeys disclose
--------------------------------------------

The captured chains for AF-17 and AF-21 leave grade-boundary placeholders their
`expected.toml` contracts do not declare (`placeholders = []`): the capture model read
AF-17's "a D is less" and AF-21's merged grade tables as boundaries not numerically
stated, and the extraction never invents one (FR-AUTHOR-08). AF-14's capture satisfies
its contract exactly. A journey runs the review walk the captured draft actually asks
for — the corpus's `[review.answers]` plus the journey-disclosed boundary answers —
and reports the divergence rather than editing the generated corpus to match. See
`fixtures/F-AUTHOR/recordings/README.md`.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sqlite3
import time
import tomllib
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from urllib.parse import urlsplit

import pytest

# The eleven-module import chain FIRST (CLAUDE.md): every contributor's migrations
# must be registered before the first store open in any process.
import aeh.agg  # noqa: F401
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401

from aeh.conf import CohortRef, resolve_run_config
from aeh.conf.sources import select_profile_config
from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot
from aeh.orch import (
    CRITERION_BREAKER_RATE_ENV,
    ESCALATION_BUDGET_ENV,
    Orchestrator,
)
from aeh.prov import RecordedFixtureProvider, SamplingParams

from tests.support import console_redesign_world as crw
from tests.support import journey_world as jw
from tests.support import rubric_methods as rm
from tests.support import spa
from tests.support.author_vocabulary import RECORDINGS, af
from tests.support.conf_builders import PROMPT_TEMPLATE_V
from tests.support.console_api_vocabulary import get_bytes, post_json, refused
from tests.support.e2e_world import (
    SynthWorld,
    _pdf_of,
    _wrap_region,
    set_world_env,
)
from tests.support.impl import NotImplementedYet, require_path
from tests.support.pipe_world import pinned_uuid4

#: The build the AF-14..21 authoring recordings were captured on. See the module
#: docstring for why this is not the corpus's older qwen pin.
JOURNEY_AUTHORING_BUILD = "openai/gpt-6-luna@2026-06-01"


def _config_toml(path: Path, transcriber_build: str, judge_build: str) -> None:
    """The twins' one config file: the dev-ci profile with the journey's capture
    builds as transcriber and single judge. The capture script renders the same TOML
    from the same pinned constant, so the assembled requests — and therefore the
    `request_key` hashes — match what the tests replay."""
    lines = [
        'HARNESS_PROFILE = "dev-ci"',
        f'prompt_template_v = "{PROMPT_TEMPLATE_V}"',
        'HARNESS_COST_CEILING = "12.50"',
        'HARNESS_COST_CURRENCY = "USD"',
        'HARNESS_DECISION_ENGINE = "off"',
        "",
        "[profiles.dev-ci.transcriber]",
        'role = "transcriber"',
        'provider = "openrouter"',
        f'build_id = "{transcriber_build}"',
        "",
        "[[profiles.dev-ci.panel]]",
        'role = "judge"',
        'provider = "openrouter"',
        f'build_id = "{judge_build}"',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def journey_config_toml(path: Path) -> None:
    """The capture script's config: the AF-14..21 build pin on both roles."""
    _config_toml(path, JOURNEY_AUTHORING_BUILD, JOURNEY_AUTHORING_BUILD)


# --- the journey spec --------------------------------------------------------------------------------


@dataclass(frozen=True)
class JourneySpec:
    """One journey's identity: the fixture it runs, the ids it names, and the pin its
    replays need. Everything the journeys share is driven from this."""

    #: The test plan's id, prefixing every assertion message.
    label: str
    #: The corpus fixture whose documents the journey hands in.
    af_id: str
    #: The document filenames inside the fixture directory, in hand-in order.
    documents: tuple[str, ...]
    #: The cohort and run the journey names. Fixed ids: the differential masks the
    #: twins' minted run ids, and the capture world's own names never reach it.
    cohort_id: str
    run_id: str
    #: The build ids the phase-A replays must ask under — the AF-14..21 captures key
    #: on `JOURNEY_AUTHORING_BUILD`, the corpus's PDF fixtures on the older qwen pin.
    transcriber_build: str
    judge_build: str
    #: Review answers this journey discloses beyond the corpus's `[review.answers]` —
    #: the grade boundaries the captured draft asks and the corpus does not declare
    #: (module docstring). Walk order: the corpus's answers first, these after.
    extra_answers: Mapping[str, str] = field(default_factory=dict)
    #: The intake warning the stage-2 preview must carry (the format oracle), or None
    #: when the fixture declares none.
    expected_warning: str | None = None
    #: The editor edit's replacement suffix: the draft's first question's own text plus
    #: one teacher sentence. Phase A computes it from the draft; both twins apply the
    #: SAME value.
    edit_suffix: str = " Answer in your own words; a guess earns nothing."
    #: The override's reason — the console form's required field and the CLI mirror's.
    reason: str = (
        "Re-checked against the paper; the evidence spans name the passage asked for.")
    #: TC-E2E-12's survival probes: reload mid-drafting and mid-review, and restart the
    #: server between review answers. The probes write nothing the twins' differential
    #: would see — they only prove the teacher's progress survives the client and the
    #: process dying under them (RS-05's positive twin, TC-CONSOLE-62's browser twin).
    survival: bool = False

    @property
    def doc_paths(self) -> tuple[Path, ...]:
        return tuple(af(self.af_id) / name for name in self.documents)

    def declared_answers(self) -> dict[str, str]:
        """The review answers both twins' review legs answer from — the corpus's own
        `[review.answers]`, then this journey's disclosed extras — so the twins cannot
        answer different items."""
        contract = tomllib.loads(
            (af(self.af_id) / "expected.toml").read_text(encoding="utf-8"))
        answers = {str(k): str(v) for k, v in contract["review"]["answers"].items()}
        answers.update(self.extra_answers)
        return answers


#: The class leg's typed roster — three names, one per line, the same rows both twins
#: write (the class action's rows and the CLI's roster file).
STUDENT_NAMES = ("Amara Okafor", "Ben Whitfield", "Chen Wei")

#: How long a twin's composed run may take to reach a terminal phase, and how long the
#: browser's draft job may take to commit its draft. Env-gated (seam 3): a slow box
#: raises them without a code change.
RUN_TIMEOUT_S = float(os.environ.get("HARNESS_JOURNEY_RUN_TIMEOUT_S", "1200"))
DRAFT_TIMEOUT_S = float(os.environ.get("HARNESS_JOURNEY_DRAFT_TIMEOUT_S", "300"))

_STEPS = 'ol[aria-label="The nine stages"] li.stage'

#: The hub's map, as the rebuilt SPA renders it: one stage of the wizard stepper per
#: lifecycle step, in journey order. The card-grid helpers in `spa` describe the
#: previous hub; TC-UI-02 owns their staleness, and this engine asserts the stepper
#: the shipped bundle actually renders.
HUB_STAGE_LABELS: tuple[str, ...] = (
    "Create the class",
    "Create the test package",
    "Review the draft",
    "Approve the package",
    "Upload the papers",
    "Reading the papers",
    "Start the grading run",
    "Review the results",
    "Export the results",
)

#: TC-CONSOLE-74's forbidden vocabulary, as the visited set of a journey meets it:
#: conservative regexes over the screens' rendered text, each category the plan's list
#: names. A match is a raw engineering surface the teacher was never meant to read.
RAW_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a TOML table header", re.compile(r"^\[[A-Za-z_][\w.-]*\]\s*$", re.M)),
    ("a TOML/JSON key = value line",
     re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*\s*=\s*\S", re.M)),
    ("a JSON object literal", re.compile(r"\{\"")),
    ("a JSON quoted key", re.compile(r"\"\s*:")),
    ("a store file path", re.compile(r"\.sqlite\b")),
    ("a Windows path fragment", re.compile(r"[A-Z]:\\")),
    ("a raw package id", re.compile(r"\bpkg-")),
    ("a raw submission ref", re.compile(r"\bref-sub-")),
    ("a raw criterion id", re.compile(r"\bCRIT-")),
    # Note: question ids (Q1, Q2, ...) are NOT forbidden, though the test plan's
    # TC-CONSOLE-74 prose names a `Q\d` pattern. The plan's own oracle sentence says
    # the constant mirrors §3.3.3's left column, and that column — the declared single
    # source (design delta line 557) — carries no question-id row. The shipped system
    # speaks question ids as teacher vocabulary everywhere: the authoring flow assigns
    # them (`author/edit.py:695`), the console serves the question spelling as the
    # grading point's teacher label (`screen_reads.py:357`, CT-CONSOLE-31's fix), and
    # the teacher-guide manual renders "Q1–Q3" as teacher copy. Disclosed to the
    # coordinator as a plan-vs-design discrepancy for /create-test-plan to settle.
    ("an HTTP status code", re.compile(r"\b[45]\d\d\b")),
    ("a module name", re.compile(r"\bM-[A-Z]{2,}")),
    ("a config key", re.compile(r"\bHARNESS_[A-Z_]+\b")),
)


# --- the gates ----------------------------------------------------------------------------------------


def bundle_gates() -> None:
    """The SPA bundle's own gates: the committed page shell (issue #634) and the
    lifecycle screens' recovery wording (issue #635) — the whole bundle, not
    index.html alone, because the built bundle ships its screens' wording in the JS
    asset beside the page shell."""
    from aeh.console import SPA_BUNDLE_DIR

    require_path(
        SPA_BUNDLE_DIR / "index.html",
        "the committed SPA bundle the hub serves (M-UI foundation)", issue="#634")
    if not spa.text_in_bundle(SPA_BUNDLE_DIR, spa.RECOVERY_TEXT):
        raise NotImplementedYet(
            "the SPA bundle does not carry the lifecycle screens' recovery wording "
            "yet (issue #635)")


def document_gates(spec: JourneySpec) -> None:
    """A journey's fixture gates: the corpus documents exist; the console's upload
    read carries their format (FR-CONSOLE-50's three-format read — an honest open
    finding when it does not, reported to the coordinator, not a writtenahead claim);
    and a committed recording quotes each document, so the authoring legs can replay."""
    from aeh.console import authoring_reads

    for path in spec.doc_paths:
        require_path(
            path, f"{spec.af_id}'s corpus document this journey runs", issue="#773")
    missing = sorted(
        {path.suffix for path in spec.doc_paths}
        - set(authoring_reads._SUPPORTED_SUFFIXES))
    if missing:
        raise NotImplementedYet(
            "the console's upload read answers PDFs only "
            f"(authoring_reads._SUPPORTED_SUFFIXES = "
            f"{sorted(authoring_reads._SUPPORTED_SUFFIXES)!r}) — FR-CONSOLE-50's "
            f"three-format read is the implementation that opens the journey's "
            f"stage-2 leg for {', '.join(missing)} (the library intake already "
            "carries every format; reported as a finding on the merged stories)")
    for path in spec.doc_paths:
        needle = f"BEGIN DOCUMENT: {path.name}".encode("utf-8")
        if not any(needle in p.read_bytes() for p in RECORDINGS.glob("*.json")):
            raise AssertionError(
                f"no committed F-AUTHOR recording quotes {path.name}, so the authoring "
                "legs cannot replay — the capture pass ran (scripts/"
                "capture_authoring_recordings.py is the command), so this is a "
                "regression, not a pending implementation")


# --- the adopted shape --------------------------------------------------------------------------------


class _AdoptedShape:
    """The published package phase A built, read back from the pkg tier's own rows.

    This is the surface ``SynthWorld`` reads a package module for (``PACKAGE_ID``,
    ``OPEN_CRITERION_IDS``, ``MCQ_CRITERION_IDS``) plus what the world's seams need —
    the criteria with their bands, the questions in page order, the mcq options, the
    boundary table. Nothing here re-derives the draft's meaning: the rows ARE the
    meaning M-PKG locked, and the same rows the twins' catalogs serve.

    The judged criteria (``open_ids``) are derived the way the orchestrator derives
    them — composites withheld (``aeh.pkg.is_composite``, FR-JUDGE-38), the DECLARED
    evaluation mode deciding judged vs deterministic (FR-ORCH-35) — but ordered by
    PAGE position (question ordinal, then the rows' own order), which is the order the
    world renders band lines in and ``_stage_spans``' cursor walks.
    """

    def __init__(self, path: Path, version: str, package_id: str) -> None:
        from aeh.orch.work_units import _row_evaluation_mode
        from aeh.pkg import is_composite

        self.package_id = package_id
        self.version = version
        self.criteria_rows: dict[str, dict[str, Any]] = {
            str(row["criterion_id"]): row for row in rm.rows(path, "criterion", version)
        }
        self.row_order = {cid: i for i, cid in enumerate(self.criteria_rows)}
        bands = rm.bands_by_criterion(path, version)
        self.by_id: dict[str, SimpleNamespace] = {}
        for cid, row in self.criteria_rows.items():
            self.by_id[cid] = SimpleNamespace(
                criterion_id=cid,
                kind=str(row["kind"]),
                question_id=str(row["question_id"]),
                bands=[
                    SimpleNamespace(
                        ordinal=int(band["ordinal"]),
                        band=str(band["band"]),
                        points=float(band["points"]),
                        descriptor=str(band["descriptor"] or ""),
                    )
                    for band in sorted(bands.get(cid, []),
                                       key=lambda band: int(band["ordinal"]))
                ],
            )
        questions = sorted(
            rm.rows(path, "question", version), key=lambda q: int(q["ordinal"]))
        self.questions = [
            SimpleNamespace(
                question_id=str(q["question_id"]),
                question_type=str(q["question_type"]),
                prompt_text=str(q["prompt_text"]),
            )
            for q in questions
        ]
        self.q_order = {q.question_id: i for i, q in enumerate(self.questions)}
        options: dict[str, list[str]] = {}
        for row in rm.rows(path, "mcq_option", version):
            options.setdefault(str(row["criterion_id"]), []).append(str(row["option_id"]))
        self.mcq_options = {cid: tuple(sorted(values)) for cid, values in options.items()}
        judged = [
            (cid, row) for cid, row in self.criteria_rows.items()
            if not is_composite(row) and _row_evaluation_mode(row) == "judged"
        ]
        judged.sort(key=lambda pair: (
            self.q_order.get(str(pair[1]["question_id"]), len(self.q_order)),
            self.row_order[pair[0]]))
        self.open_ids = tuple(cid for cid, _row in judged)
        self.mcq_ids = tuple(
            cid for cid, row in self.criteria_rows.items()
            if _row_evaluation_mode(row) == "deterministic" and str(row["kind"]) == "mcq")
        self.grades = tuple(
            (str(row["grade"]), float(row["scaled_floor"]))
            for row in rm.rows(path, "grade_boundary", version))
        # A fixture bug must read as one: a judged criterion without two named bands
        # gives the world's band plan nothing to walk.
        shallow = [
            cid for cid in self.open_ids if len(self.by_id[cid].bands) < 2
            or any(not band.descriptor for band in self.by_id[cid].bands)
        ]
        assert not shallow, (
            "the adopted shape's judged criteria "
            f"{shallow} lack two bands with descriptors — the draft the corpus "
            "recorded does not match its own declared shape")
        assert self.open_ids or self.mcq_ids, (
            "the adopted shape declares no criterion at all — nothing to grade")

    @property
    def PACKAGE_ID(self) -> str:
        return self.package_id

    @property
    def OPEN_CRITERION_IDS(self) -> tuple[str, ...]:
        return self.open_ids

    @property
    def MCQ_CRITERION_IDS(self) -> tuple[str, ...]:
        return self.mcq_ids


def _adopt_shape(store, spec: JourneySpec, package_id: str) -> _AdoptedShape:
    path = store.package_path(package_id)
    versions = rm.locked_versions(path)
    assert len(versions) == 1, (
        f"{spec.label}: {package_id} holds {len(versions)} locked version(s); phase A "
        "publishes exactly one")
    return _AdoptedShape(path, versions[0], package_id)


@dataclass(frozen=True)
class _Plan:
    """One submission's reference plan: the name the roster declares, the band ordinal
    the student's work sits at per judged criterion, and the option each mcq criterion's
    mark names. Three students walk the bands from the top down."""

    name: str
    ordinals: dict[str, int]
    mcq: dict[str, str]

    @property
    def student_ref(self) -> str:
        """The identity the base world's ingest loop reads off every submission —
        the roster name is the pseudonymous ref this journey's rosters declare."""
        return self.name


def _plans_for(shape: _AdoptedShape) -> tuple[_Plan, ...]:
    plans = []
    for index, name in enumerate(STUDENT_NAMES):
        ordinals = {
            cid: max(0, len(shape.by_id[cid].bands) - 1 - index)
            for cid in shape.open_ids
        }
        mcq = {
            cid: shape.mcq_options[cid][index % len(shape.mcq_options[cid])]
            for cid in shape.mcq_ids
        }
        plans.append(_Plan(name=name, ordinals=ordinals, mcq=mcq))
    return tuple(plans)


# --- the page transcripts (shared by the world and the twins' PDFs) -----------------------------------


def _descriptor(shape: _AdoptedShape, cid: str, ordinal: int) -> str:
    for band in shape.by_id[cid].bands:
        if band.ordinal == ordinal:
            return band.descriptor
    raise KeyError(f"{cid} has no band at ordinal {ordinal}")


def _band_name(shape: _AdoptedShape, cid: str, ordinal: int) -> str:
    for band in shape.by_id[cid].bands:
        if band.ordinal == ordinal:
            return band.band
    raise KeyError(f"{cid} has no band at ordinal {ordinal}")


def _page_text(shape: _AdoptedShape, plan: _Plan, package_id: str,
               *, with_student: bool = True) -> str:
    """One submission's page, region-marked per the marker protocol — the same strings
    the capture world ingests and the twins' PDFs carry (byte-identical scans).

    The MCQ's choice is ONE resolved ``selection_mark`` region with the item line left
    OUTSIDE any marker (V2 fails prose tagged a declared mcq question); each open
    question's evidence lines are one ``transcribed_text`` region. The identity lines
    sit outside the markers too — V3 reads ``Student:``, V4 reads ``Assessment:``."""
    out: list[str] = []
    if with_student:
        out.append(f"Student: {plan.name}")
    out.append(f"Assessment: {package_id}")
    for question in shape.questions:
        out += ["", f"## {question.question_id}", ""]
        for cid in shape.mcq_ids:
            if shape.by_id[cid].question_id != question.question_id:
                continue
            letter = plan.mcq[cid]
            out.append(f"{cid}: {letter}")
            out.append(_wrap_region(
                "selection_mark", question.question_id, 0.95, letter, selection=letter))
        lines = [
            f"{cid}: {_descriptor(shape, cid, plan.ordinals[cid])}"
            for cid in shape.open_ids
            if shape.by_id[cid].question_id == question.question_id
        ]
        if lines:
            out.append(_wrap_region(
                "transcribed_text", question.question_id, 0.90, "\n".join(lines)))
    return "\n".join(out).strip("\n")


def _assessment_text(shape: _AdoptedShape, package_id: str) -> str:
    """The assessment artifact: the declared-identifier line and one region per
    question — the V4 lineage head the submissions' regions are compared against."""
    lines: list[str] = [
        f"Assessment: {package_id}",
        f"Reference paper for the {package_id} assessment",
        "",
    ]
    for question in shape.questions:
        lines += ["", _wrap_region(
            "transcribed_text", question.question_id, 0.95, question.prompt_text), ""]
    return "\n".join(lines).strip("\n")


# --- the capture world ---------------------------------------------------------------------------------


class JourneyWorld(SynthWorld):
    """``SynthWorld`` over the shape phase A published, driving the run into the
    capture store.

    Every difference from the reference world goes through a seam ``SynthWorld``
    declares, so the drive — orchestrator, deterministic evaluator, extraction workers,
    integrity gate, aggregation walk, synthesis worker and closer — is the same code
    the journeys run. The shape is the PUBLISHED package's own rows, so the catalog the
    run opens is the one the twins open too; the panel is the recorded dev-ci config's
    single judge, resolved from the same scratch config the twins read.
    """

    def __init__(self, data_dir: Path, fixture_dir: Path, *, spec: JourneySpec,
                 shape: _AdoptedShape, cfg: Any,
                 monkeypatch: pytest.MonkeyPatch | None = None) -> None:
        self._spec = spec
        self._shape = shape
        # Resolved BEFORE the base opens anything: the ingestor's transcriber and the
        # panel are the config's own refs — byte-identical with the twins' by
        # construction, so the request keys the capture records are the keys the twins
        # mint.
        self._resolved = resolve_run_config(
            select_profile_config(dict(cfg), "dev-ci"),
            CohortRef(cohort_id=spec.cohort_id, consent_class="synthetic"))
        self._plans = _plans_for(shape)
        set_world_env(ESCALATION_BUDGET_ENV, jw.ESCALATION_BUDGET, monkeypatch)
        # The criterion breaker stays off (rate 1.0): with no disagreement there is
        # nothing to trip, and the twins must not diverge on where a breaker WOULD
        # trip — scheduling, not a surface difference (the TC-E2E-06 rationale).
        set_world_env(CRITERION_BREAKER_RATE_ENV, "1.0", monkeypatch)
        with pinned_uuid4():
            super().__init__(
                data_dir, fixture_dir,
                n_submissions=len(STUDENT_NAMES),
                cohort_id=spec.cohort_id,
                run_id=spec.run_id,
                monkeypatch=monkeypatch,
                quarantine_indices=(),
                panel_size=1,
                package=shape,
                record_as_you_go=True,
            )
        self.panel_refs = tuple(self._resolved.panel)
        self.judge_refs = {ref.build_id: ref for ref in self._resolved.panel}
        self.escalation_refs = {}
        self.student_ref_by_sid = {
            str(row["submission_id"]): str(row["student_ref"])
            for row in self.handle.query(
                "SELECT submission_id, student_ref FROM submission")
        }

    # -- the seams -----------------------------------------------------------------------

    def _make_provider(self, fixture_dir: Path) -> Any:
        return jw.JourneyCaptureProvider(self, fixture_dir)

    def _cohort_submissions(self, n_submissions: int) -> tuple[_Plan, ...]:
        return self._plans[:n_submissions]

    def _ingestor(self) -> Ingestor:
        """The twins' transcription identity: the scratch config's transcriber and the
        adopted package, so the ingest keys are the keys the twins mint — including the
        declared-questions clause TC-INGEST-56 folds into every page request once a
        package is bound. The catalog rides on the constructor the way ``ingest_files``
        binds it; a version passed without a catalog invents nothing
        (``_declared_inventory`` returns None) and the request then misses the twins'
        replay by exactly that field."""
        return Ingestor(
            self.handle, self.blobs, self.provider, self._resolved.transcriber,
            SamplingParams(temperature=0.0), PdfiumRasterizer(),
            residency=ResidencySlot.for_policy(("transcriber",)),
            sanitizer=PypdfSanitizer(),
            package_catalog=self.catalog, package_version=self.version,
        )

    def _ingest_assessment(self) -> None:
        """The assessment through the gateway's own call shape: the package version
        rides along, so every page request names the package's declared questions
        (TC-INGEST-56) — exactly the keys the twins' ``ingest_files`` mints. The
        base's call omits the package, so a capture recorded under it would miss the
        twins' replay by exactly that field."""
        text = self._assessment_transcript()
        blob = self.blobs.put(_pdf_of([text]))
        self.provider.stage_transcript(blob, {1: text})
        self.ingestor.ingest_document(
            [blob], kind="assessment", order_hint=[blob],
            package_version=self.version, filenames={blob: "assessment.pdf"})

    def _build_cohort(self) -> None:
        """The cohort through the same roster writer the twins' class legs call."""
        from aeh.orch.cohorts import create_cohort

        create_cohort(self.store, self.cohort_id, "synthetic",
                      [{"full_name": plan.name} for plan in self._plans])

    def _pages_for(self, submission: _Plan, *, with_student: bool) -> list[str]:
        return [_page_text(self._shape, submission, self.package_id,
                           with_student=with_student)]

    def _assessment_transcript(self) -> str:
        return _assessment_text(self._shape, self.package_id)

    def _render_band(self, criterion_id: str, ordinal: int) -> str:
        return f"{criterion_id}: {_descriptor(self._shape, criterion_id, ordinal)}"

    def _ordinal_for(self, submission: _Plan, criterion_id: str) -> int:
        return submission.ordinals[criterion_id]

    def _judge_band(self, sid: str, cid: str, judge: str | None = None) -> str:
        """The band THIS arm records — the submission's reference band, for every arm.

        The recorded dev-ci panel is a single judge with no escalation arms, so no
        disagreement exists to widen: every judged cell records the plan's own band,
        which is what makes the capture deterministic and the twins' replay exact."""
        plan = self.cohort[self.index_by_sid[sid] - 1]
        return _band_name(self._shape, cid, plan.ordinals[cid])

    # -- the build -----------------------------------------------------------------------

    def _build(self) -> None:
        """The package phase A already published — the world adopts its locked version
        and opens the catalog over it; the cohort and the ingest legs are the base's."""
        from aeh.pkg import PackageCatalog

        versions = rm.locked_versions(self.store.package_path(self.package_id))
        assert len(versions) == 1, (
            f"{self._spec.label}: the capture store holds {len(versions)} locked "
            f"version(s) of {self.package_id}; phase A publishes exactly one")
        self.version = versions[0]
        self.catalog = PackageCatalog(
            self.store.package(self.package_id),
            package_id=self.package_id, blobs=self.blobs)
        self._build_cohort()
        self._ingest_assessment()
        self._ingest_submissions()

    def build_run(self) -> str:
        """Create and enumerate the run through the real orchestrator, the scratch
        config resolved as the run's config — the resolution the twins make too. Not
        started; ``start_run`` does."""
        self.orchestrator = Orchestrator(self.store, provider=self.provider)
        self.resolved = self._resolved
        self.run_id = self.orchestrator.create_run(
            self.cohort_id, self.version, self._resolved, run_id=self.run_id)
        self.enumeration = self.orchestrator.enumerate_units(self.run_id)
        self._stage_spans()
        return self.run_id


# --- phase A: the authoring flow the twins replay ------------------------------------------------------


def _phase_a(store, cfg: Any, spec: JourneySpec, authoring_dir: Path,
             fixture_dir: Path) -> tuple[str, str, str]:
    """Author the fixture's package into ``store`` through the real authoring flow —
    the draft (replaying the committed recordings), the review walk's declared
    answers, the editor's structured edit, the build through M-PKG's own writer
    (ADR-45: the only authoring step touching the package tier). Returns ``(package_id,
    question id, the edited text)`` — the values both twins' legs apply identically."""
    from aeh.author.edit import apply_structured_edit
    from aeh.author.review import run_review
    from aeh.author.service import authoring_service
    from aeh.author.types import ReviewAnswer
    from aeh.pipeline.packages import build_package, read_package_spec

    provider = RecordedFixtureProvider(fixture_dir)
    service = authoring_service(cfg, "dev-ci", provider=provider)
    authoring_dir.mkdir(parents=True, exist_ok=True)
    result = service.draft(list(spec.doc_paths), authoring_dir)
    draft_path = result.draft_path
    answers = spec.declared_answers()
    run_review(draft_path, [ReviewAnswer(item_id, value)
                            for item_id, value in answers.items()])
    draft = tomllib.loads(draft_path.read_text(encoding="utf-8"))
    package_id = str(draft["package"])
    questions = draft.get("question") or []
    assert questions, "the recorded draft declares no question — a fixture bug"
    first = questions[0]
    qid = str(first["id"])
    new_text = str(first.get("text") or "") + spec.edit_suffix
    apply_structured_edit(draft_path, "edit question",
                          params={"item_id": qid, "field": "text", "value": new_text})
    build_package(store, read_package_spec(draft_path))
    return package_id, qid, new_text


# --- shared twin helpers -------------------------------------------------------------------------------


def _write_papers(paper_dir: Path, shape: _AdoptedShape, plans: tuple[_Plan, ...],
                  pages_by_student: dict[str, list[str]],
                  assessment_pages: list[str]) -> tuple[Path, list[Path]]:
    """The day's papers as byte-identical PDFs on disk: the assessment once, one sheet
    per student. Both twins read the SAME bytes, so the content-addressed blobs — and
    the transcription request keys they mint — are the capture's."""
    paper_dir.mkdir(parents=True, exist_ok=True)
    assessment = paper_dir / "assessment.pdf"
    assessment.write_bytes(_pdf_of(assessment_pages))
    sheets = []
    for plan in plans:
        path = paper_dir / f"{plan.name}.pdf"
        path.write_bytes(_pdf_of(pages_by_student[plan.name]))
        sheets.append(path)
    return assessment, sheets


def _minted_run_id(store, spec: JourneySpec, whose: str) -> str:
    """The run id M-ORCH minted on this surface, read from the run table — never
    assumed."""
    handle = store.cohort(spec.cohort_id)
    rows = handle.query("SELECT run_id FROM run")
    assert len(rows) == 1, (
        f"{spec.label}: {whose} run table holds {len(rows)} run(s); the journey starts "
        "exactly one")
    return str(rows[0]["run_id"])


def _await_terminal(handle, run_id: str) -> str:
    """Poll the run row until a terminal phase; time-boxed by the env knob."""
    deadline = time.monotonic() + RUN_TIMEOUT_S
    last = ""
    while time.monotonic() < deadline:
        rows = handle.query("SELECT status FROM run WHERE run_id = :r", r=run_id)
        last = rows[0]["status"] if rows else ""
        if last in ("complete", "failed", "stopped", "cancelled"):
            return last
        time.sleep(0.25)
    return f"still {last!r} after {RUN_TIMEOUT_S}s"


def _run_catalog(store, cohort_id: str, run_id: str):
    """The run's package catalog, the console's own construction
    (``app_reads._run_catalog``): without it M-REVIEW maps bands on its default scale
    and refuses every band name the run's package declares (FR-CONSOLE-34) — a package
    whose bands are not the default scale's would make the review leg lie."""
    from aeh.pkg import PackageCatalog

    rows = store.cohort(cohort_id).query(
        "SELECT package_id, package_version_id FROM run WHERE run_id = :run_id",
        run_id=run_id)
    if not rows:
        return None
    package_id = str(rows[0]["package_id"])
    version = str(rows[0]["package_version_id"] or "")
    catalog = PackageCatalog(store.package(package_id), package_id=package_id)
    if version:
        catalog.criteria(version)  # primes the version the band reads resolve against
    return catalog


def _work_review_queue(store, run_id: str, cohort_id: str) -> None:
    """The review leg's band decisions, through the M-REVIEW library the console's
    review screen and the CLI's review door both call — on BOTH twins, with the run's
    own catalog attached, exactly the construction the console's screen makes."""
    from aeh.review import open_review

    review = open_review(store.data_dir, run_id=run_id, actor="teacher",
                         catalog=_run_catalog(store, cohort_id, run_id))
    try:
        review.build_queue(run_id, 30)
        for item in review.queue(run_id):
            # The recorded panel is one judge, so a cell here (if any route at all)
            # carries one verdict; the walk accepts whatever the queue holds, exactly
            # as the review screen's accept control does.
            if hasattr(item, "score_id"):
                review.act(item, "accept")
            else:  # a collapsed group is accepted as one band decision
                review.act_on_group(item, item.proposed_band)
    finally:
        review.close()


def _review_and_finalize(store, run_id: str, cohort_id: str) -> None:
    """The review and finalize legs: the same queue walk, then the batch settle
    through ``GradingService`` — the library the console's ``finalize batch`` control
    performs."""
    from aeh.grade import GradingService

    _work_review_queue(store, run_id, cohort_id)
    GradingService(store).finalize_batch(run_id, actor="teacher")


def _close(store) -> None:
    """Close the store, tolerating a connection the console's request thread opened."""
    import sqlite3

    try:
        store.close()
    except sqlite3.ProgrammingError:
        pass


def _patch_all_provider_sites(monkeypatch: pytest.MonkeyPatch, fixture_dir: Path) -> None:
    """Bind the twins' model boundary at every ``_provider_for`` seam.

    ``background``, ``cli`` and ``runtime`` are the pipeline's import sites (the
    TC-E2E-06 disclosure); ``authoring_actions`` is the console's own — the draft
    worker resolves its provider through it, keyed on the served config's profile.
    The replay-with-fallback answers authoring prompts strictly from the committed
    recordings (authoring prompts carry no synthesis-level field) and the run legs'
    synthesis first-sights with ``journey_world.synth_reply`` — module docstring.
    """
    from aeh.console import authoring_actions
    from aeh.pipeline import background, cli, runtime

    def synthetic_provider(_environ_or_config: object):
        return jw.ReplayWithSynthFallback(fixture_dir)

    for site in (background, cli, runtime, authoring_actions):
        monkeypatch.setattr(site, "_provider_for", synthetic_provider)


# --- the console twin's drive ---------------------------------------------------------------------------


def _extend_mask_for_authoring(mask: dict[str, str], console_dir: Path,
                               cli_dir: Path) -> dict[str, str]:
    """Pair the authoring build's minted proposal ids into the differential's mask.

    ``build_package`` mints ``spec-<hex12>`` (``MINTED_ID`` covers 32-hex shapes only),
    and each store holds exactly one — the same build ran on both sides. Masking both
    to one surrogate is the pairing the surrogate rule already gives every other
    minted id; it is disclosed in each journey's module docstring.
    """
    import sqlite3

    for dir_ in (console_dir, cli_dir):
        for db in sorted(Path(dir_).rglob("*.sqlite")):
            connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            try:
                names = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")}
                if "setup_proposal" not in names:
                    continue
                for (proposal_id,) in connection.execute(
                        "SELECT proposal_id FROM setup_proposal"):
                    if proposal_id:
                        mask.setdefault(str(proposal_id), "<authoring-proposal>")
            finally:
                connection.close()
    return mask


def _serve_and_drive(store, console_dir: Path, scratch: Path, cfg: Any,
                     spec: JourneySpec, shape: _AdoptedShape, plans: tuple[_Plan, ...],
                     qid: str, new_text: str, export_seen: dict) -> None:
    """The operator's surface, end to end: the class action, the authoring legs in the
    browser, the papers, the run through its confirmation control, the review, the
    results with their justification and override, the exports, and the wizard's
    stage-flip checkpoints — finishing with the raw-vocabulary scan over every screen
    the journey visited."""
    from aeh.console import serve_console

    label = spec.label
    server = serve_console(store=store, cfg=cfg)
    port = int(server.port)
    loopback_host = ".".join(("127", "0", "0", "1"))
    origin = f"http://{loopback_host}:{port}"
    visited: list[tuple[str, str]] = []

    def _goto(page, path: str) -> str:
        """Fragment navigation, the screens suite's rule: the wizard home waits on the
        stepper, every other screen on its heading. Every visited screen's text is
        kept for the raw-vocabulary scan."""
        route = path.split("?", 1)[0]
        page.goto(f"{origin}#{path}", wait_until="domcontentloaded")
        if route in ("", "/"):
            page.locator(_STEPS).first.wait_for(
                state="visible", timeout=spa.STEP_TIMEOUT_MS)
            page.wait_for_load_state("networkidle")
            visited.append((path, spa.main_text(page)))
            return ""
        text = spa.wait_for_screen(page)
        visited.append((path, spa.main_text(page)))
        return text

    def _dialog(page):
        return page.get_by_role("dialog").or_(page.get_by_role("alertdialog"))

    def _stage(page, number: int):
        return page.locator(_STEPS).nth(number - 1)

    def _badge(page, number: int) -> str:
        return _stage(page, number).locator("span.badge").inner_text()

    def _badge_becomes(page, number: int, want: str, what: str,
                       timeout_ms: int = 15_000) -> None:
        """The stage badge reaching its expected word. The SPA re-derives the wizard
        from its three-second context poll, so a stage's state lags the store write
        that caused it — the journey waits out the poll instead of racing it."""
        _wait_for(page, lambda: _badge(page, number) == want,
                  f"stage {number} to read {want!r} ({what})", timeout_ms=timeout_ms)

    def _wait_for(page, predicate, what: str, timeout_ms: int = 20_000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            try:
                if predicate():
                    return
            except Exception:  # the read may be mid-render; the bound decides
                pass
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"{label}: gave up waiting for {what} (at {page.url!r})")
            page.wait_for_timeout(250)

    def _action_urls(log) -> list[str]:
        return [u for u in log.requests if "/api/v1/actions/" in u]

    try:
        # -- the class leg: the console's own control, over HTTP ----------------------
        answer = crw._action(port, "create class", {
            "class_id": spec.cohort_id, "consent_class": "synthetic",
            "rows": [{"full_name": name} for name in STUDENT_NAMES],
        })
        assert not answer.get("refused"), (
            f"{label}: the create-class control refused: {answer!r}")
        roster = store.cohort(spec.cohort_id).query(
            "SELECT student_ref, full_name FROM roster ORDER BY student_ref")
        assert len(roster) == len(STUDENT_NAMES), (
            f"{label}: the class action wrote {len(roster)} students, not the "
            f"typed roster's {len(STUDENT_NAMES)}")
        # The identity the console generates for a name-only roster row — the
        # pseudonymous ref every later screen displays instead of the name
        # (FR-CONSOLE-44's safe form). Deterministic per name, so both twins'
        # ledgers carry the same refs and the pairing compares like with like.
        ref_by_name = {str(row["full_name"]): str(row["student_ref"])
                       for row in roster}

        with spa.spa_page(origin) as (page, log):
            # The origins the console under test served during this drive. The journey
            # re-serves the console (the bound run-start serve, the survival restart),
            # and each serve binds a fresh loopback port — so the boundary oracle below
            # accepts exactly these, and still catches any request to a host the
            # journey never served (CT-PROV-15's no-egress rule, applied to the SPA).
            served_origins = {urlsplit(origin).netloc}
            # -- hub ------------------------------------------------------------------
            # The hub's map is the nine-stage wizard itself: every lifecycle step the
            # journey walks renders as one stage of the stepper, in order (see
            # HUB_STAGE_LABELS for why the card-grid helpers are not the oracle).
            spa.open_hub(page, origin)
            stages = page.locator(_STEPS)
            assert stages.count() == len(HUB_STAGE_LABELS), (
                f"{label}: the hub's wizard shows {stages.count()} stage(s), not the "
                f"{len(HUB_STAGE_LABELS)} the journey walks")
            for number, want in enumerate(HUB_STAGE_LABELS, 1):
                got = stages.nth(number - 1).inner_text()
                assert want in got, (
                    f"{label}: wizard stage {number} reads {got.strip()!r}, "
                    f"not {want!r}; the hub is the journey's map")
            # stage 1: the class ledger exists, so the wizard reads it Done. The
            # wizard derives every stage from the SELECTED class/package/run (the
            # route's ?class= refs), so the journey carries its selection.
            _goto(page, f"/?class={spec.cohort_id}")
            _badge_becomes(page, 1, "Done", "after the class leg")
            _goto(page, "/class")
            class_text = spa.main_text(page)
            for name in STUDENT_NAMES:
                assert name in class_text, (
                    f"{label}: the class screen does not show {name!r}")

            # -- the authoring legs, in the browser ------------------------------------
            _goto(page, "/package/author")
            page.locator('input[aria-label="Choose files to upload"]').set_input_files(
                [str(path) for path in spec.doc_paths])
            ask_preview = page.get_by_role("button", name="Show what we understood")
            _wait_for(page, ask_preview.is_enabled,
                      "the preview button to enable once the bytes are read",
                      timeout_ms=60_000)
            ask_preview.click()
            preview = page.locator("section[aria-label='What we understood']")
            _wait_for(page, lambda: preview.locator(".preview-file").count() > 0,
                      "the preview's outline to render")
            # The format oracle: the intake's declared warning, in the teacher's
            # language, on the stage-2 screen the corpus declares it for.
            if spec.expected_warning is not None:
                warnings = preview.locator(".preview-warning").all_inner_texts()
                assert any(spec.expected_warning in text for text in warnings), (
                    f"{label}: the preview carries none of {spec.af_id}'s declared "
                    f"warnings (rendered: {warnings!r})")
            names = preview.locator(".preview-file h3").all_inner_texts()
            for path in spec.doc_paths:
                assert any(path.name in name for name in names), (
                    f"{label}: the preview names {names!r}, not every uploaded "
                    "document")
            assert not _action_urls(log), (
                f"{label}: the preview committed something: {_action_urls(log)!r}")
            assert not list(Path(console_dir, "authoring").glob("*.draft.toml")), (
                f"{label}: a draft file exists before the teacher confirmed anything")

            make = page.get_by_role("button", name="Make the draft")
            _wait_for(page, make.is_enabled, "the draft dispatch to arm")
            make.click()
            dialog = _dialog(page)
            _wait_for(page, lambda: dialog.count() > 0 and dialog.first.is_visible(),
                      "the draft confirmation to open")
            dialog.first.get_by_role("button", name="Make the draft").click()
            if spec.survival:
                # RS-05's positive twin, mid-drafting: the job belongs to the server,
                # so the page dying under it changes nothing. The dispatch registers,
                # the page reloads, and the same job is waited out to its draft.
                job_id = _draft_job_id(port, label)
                page.reload(wait_until="domcontentloaded")
                record = crw.wait_for_job(port, job_id, timeout=DRAFT_TIMEOUT_S)
            else:
                record = _wait_draft_job(port, label)
            assert record["state"] == "succeeded", (
                f"{label}: the browser's draft job ended {record['state']!r}: "
                f"{record.get('error')!r}")
            document = crw.draft_read(port)["draft"]
            package_id = document["package_id"]
            assert package_id, f"{label}: the draft read names no package: {document!r}"
            missing = int(document["missing_pieces"])
            # The wizard's honest gap (a reported finding, not a test-writable state):
            # the context read keys packages off the built `*.pkg.sqlite` files, and a
            # first draft has none — the draft job writes the draft TOML alone, and the
            # package file appears only when the approve leg builds it. So stages 2-3
            # cannot reflect a first draft, and pre-creating the file would make the
            # console's own approve refuse ("package already exists"). The hub asserts
            # what it truthfully derives here — stage 1 still Done — while the draft's
            # own read carries the work the teacher just did.
            _goto(page, f"/?class={spec.cohort_id}")
            _badge_becomes(page, 1, "Done", "still, after the draft leg")

            # -- the review walk: the declared answers, one at a time ------------------
            _goto(page, "/package/review")
            declared = spec.declared_answers()
            placeholders = list(document["placeholders"])
            listed_ids = [str(row["item_id"]) for row in placeholders]
            unclaimed = [item for item in listed_ids if item not in declared]
            assert not unclaimed, (
                f"{label}: the draft asks {unclaimed} — items beyond the corpus's "
                "declared answers and this journey's disclosed extras; the capture's "
                "draft and the corpus's contract disagree")
            for item_id in listed_ids:
                # The list is the draft read's own placeholders, re-rendered after every
                # answer — answered rows leave it and the rest close ranks, so the row
                # is targeted by its reason text, never by a shifting position.
                piece = next(row for row in placeholders
                             if str(row["item_id"]) == item_id)
                reason = str(piece.get("reason") or "")
                rows = page.locator("ul.placeholder-list li.placeholder-row")
                target = rows.filter(has_text=reason) if reason else rows
                _wait_for(page, lambda: target.count() == 1,
                          f"the row for {item_id!r} ({reason!r}) to render")
                target.first.get_by_role("button", name="Answer").click()
                page.locator("#answer-value").fill(declared[item_id])
                page.get_by_role("button", name="Send the answer").click()
                _wait_for(page, lambda: target.count() == 0,
                          f"the answered piece {item_id!r} to leave the list")
            if spec.survival:
                # RS-05's positive twin, mid-review: the reload re-attaches to the
                # store's own review state — the answer already sent stays sent, and
                # the reopened screen asks for nothing again.
                page.reload(wait_until="domcontentloaded")
            _wait_for(page,
                      lambda: "None — the draft is ready to approve."
                      in page.locator("main").inner_text(),
                      "the ready copy to render once every answer is in")
            assert int(crw.draft_read(port)["draft"]["missing_pieces"]) == 0, (
                f"{label}: the draft read still counts pieces after the walk")
            if spec.survival:
                # TC-CONSOLE-62's browser twin: the console itself goes down and comes
                # back between review answers — the answer lives in the store, not in
                # the process, so the reopened screen still reads it answered.
                server.terminate()
                server = serve_console(store=store, cfg=cfg)
                port = int(server.port)
                origin = f"http://{loopback_host}:{port}"
                served_origins.add(urlsplit(origin).netloc)
                _goto(page, f"/package/review?class={spec.cohort_id}")
                _wait_for(page,
                          lambda: "None — the draft is ready to approve."
                          in page.locator("main").inner_text(),
                          "the reopened review screen to re-attach with the answer "
                          "surviving the restart")
                assert int(crw.draft_read(port)["draft"]["missing_pieces"]) == 0, (
                    f"{label}: the draft read lost pieces across the restart")

            # -- the editor edit: the same text the CLI twin applies -------------------
            draft_file = crw.draft_path_in(console_dir, package_id)
            before_bytes = draft_file.read_bytes()
            _goto(page, f"/package/edit?package={package_id}")
            items = list(crw.draft_read(port)["draft"]["items"])
            assert items and items[0]["id"] == qid, (
                f"{label}: the draft's first item is {items[:1]!r}, not the question "
                f"phase A edited ({qid!r})")
            page.locator("#q-text-0").fill(new_text)
            page.get_by_role("button", name="Stage the changes to this question").click()
            staged = page.locator("section[aria-label='Your changes'] ul.change-list li")
            _wait_for(page, lambda: staged.count() == 1, "the staged text edit to appear")
            page.get_by_role("button", name=re.compile(r"Review changes \(1\)")).click()
            dialog = _dialog(page)
            _wait_for(page, dialog.is_visible, "the save confirmation")
            dialog.first.get_by_role("button", name="Save the changes").click()
            _wait_for(page, lambda: page.locator(".change-list-applied").count() > 0,
                      "the applied change list to render")
            applied = page.locator(".change-list-applied ul li").all_inner_texts()
            assert applied and not any("Refused:" in text for text in applied), (
                f"{label}: the editor's save was refused or empty: {applied!r}")
            assert draft_file.read_bytes() != before_bytes, (
                f"{label}: the draft file did not change — the editor's save did not "
                "apply")
            assert any("edit-draft-package" in url for url in _action_urls(log)), (
                f"{label}: the editor's save never reached the enumerated surface")

            # -- the approve leg --------------------------------------------------------
            _goto(page, "/package/review")
            approve = page.get_by_role("button", name="Approve the package")
            _wait_for(page, approve.is_visible, "the approve control to render")
            approve.click()
            dialog = _dialog(page)
            _wait_for(page, lambda: dialog.count() > 0 and dialog.first.is_visible(),
                      "the approve confirmation to open")
            dialog.first.get_by_role("button", name="Approve the package").click()
            _wait_for(page,
                      lambda: any("approve-draft-package" in url
                                  for url in _action_urls(log)),
                      "the approve action to post through the console's own control",
                      timeout_ms=30_000)
            try:
                version = _wait_published(port, store, package_id, label)
            except AssertionError:
                # The control can refuse in the teacher's language on the screen it
                # serves; the publish wait alone would name only the silence. Surface
                # what the screen showed and what the journey posted.
                outcome = page.locator("p.action-outcome").all_inner_texts()
                screen = spa.main_text(page)
                raise AssertionError(
                    f"{label}: the approve leg never published {package_id!r}; the "
                    f"screen showed {outcome!r} and read: {screen[:600]!r}; actions "
                    f"posted: {[u.rsplit('/', 1)[-1] for u in _action_urls(log)]}"
                ) from None
            _goto(page, f"/?class={spec.cohort_id}")
            # The build created the package file the context read lists, so the wizard
            # now sees the whole story: the review stage reads Done alongside the
            # published one.
            _badge_becomes(page, 4, "Done", "after the approve leg")
            _badge_becomes(page, 3, "Done", "with the package published")

            # -- the papers leg (disclosed: direct ingest, the screen driven visually) --
            assessment, sheets = _write_papers(
                scratch / "console-pdfs", shape, plans,
                {plan.name: [_page_text(shape, plan, package_id)] for plan in plans},
                [_assessment_text(shape, package_id)])
            _ingest_console(store, cfg, spec, version, assessment, sheets)
            _goto(page, f"/papers?class={spec.cohort_id}")
            papers_text = spa.main_text(page)
            for plan in plans:
                # The papers screen displays the pseudonymous ref, not the name —
                # the same safe form TC-E2E-06's papers leg asserts against.
                assert ref_by_name[plan.name] in papers_text, (
                    f"{label}: the papers screen does not show {plan.name!r}'s sheet "
                    f"(ref {ref_by_name[plan.name]!r})")
            # stage 5 on the hub itself: the sidebar strip's list items do not carry
            # the wizard's `stage` class, so the badge is read on the wizard home.
            _goto(page, f"/?class={spec.cohort_id}")
            _badge_becomes(page, 5, "Done", "after the ingest leg")

            # -- the run: row, bound serve, no-op digest, confirm, terminal ------------
            # The merged run-start screen starts a run that EXISTS: its state read
            # answers the console's bound run (the ts151 idiom), and the start posts
            # that id — a start of an existing row resumes under the run's own frozen
            # configuration (FR-CONF-15). So the orchestrator creates the row here,
            # freezing the same resolved config both twins resolve, and the console
            # re-serves bound to it — the restart idiom the survival probes use.
            resolved = resolve_run_config(
                select_profile_config(dict(cfg), "dev-ci"),
                CohortRef(cohort_id=spec.cohort_id, consent_class="synthetic"))
            Orchestrator(store).create_run(
                spec.cohort_id, version, resolved, run_id=spec.run_id)
            server.terminate()
            server = serve_console(store=store, cfg=cfg, run_id=spec.run_id)
            port = int(server.port)
            origin = f"http://{loopback_host}:{port}"
            served_origins.add(urlsplit(origin).netloc)
            before = spa.store_digest(console_dir)
            _goto(page, f"/run?class={spec.cohort_id}")
            banner_text = spa.main_text(page)
            assert spec.run_id in banner_text, (
                f"{label}: the run-start screen does not name the bound run "
                f"{spec.run_id!r}: {banner_text!r}")
            after = spa.store_digest(console_dir)
            assert not spa.changed_tables(before, after), (
                f"{label}: opening the run-start screen wrote rows — a no-op until "
                "confirmed (TC-UI-05)")
            start_buttons = page.locator("main").get_by_role(
                "button", name=re.compile(r"^\s*start", re.I))
            enabled = [start_buttons.nth(i) for i in range(start_buttons.count())
                       if start_buttons.nth(i).is_enabled()]
            assert enabled, (
                f"{label}: the run-start screen offers no enabled start control")
            enabled[0].click()
            dialog = _dialog(page)
            _wait_for(page, lambda: dialog.count() > 0 and dialog.first.is_visible(),
                      "the start confirmation to open")
            # The profile's name rides the preview read's banner, composed onto the
            # run's own frozen configuration — the confirmation carries it (FR-CONSOLE-43).
            dialog_text = dialog.first.inner_text()
            assert "dev-ci" in dialog_text, (
                f"{label}: the start confirmation names no profile: {dialog_text!r}")
            confirm = [dialog.first.get_by_role("button", name=re.compile(
                r"^\s*start", re.I)).nth(i)
                for i in range(dialog.first.get_by_role(
                    "button", name=re.compile(r"^\s*start", re.I)).count())]
            confirm = [button for button in confirm
                       if not re.search(r"cancel|back|no\b|keep|close|dismiss",
                                        button.inner_text(), re.I)]
            assert confirm, f"{label}: the confirmation has no start button"
            confirm[0].click()
            deadline = time.monotonic() + 60
            threads: dict = dict(getattr(server.app, "_run_threads", {}))
            while not threads and time.monotonic() < deadline:
                page.wait_for_timeout(200)
                threads = dict(getattr(server.app, "_run_threads", {}))
            assert threads, (
                f"{label}: confirming the start never reached the console's "
                "background — the control started no run")
            assert len(threads) == 1, (
                f"{label}: the console's background holds {len(threads)} runs; the "
                "journey starts exactly one")
            run_id = next(iter(threads))
            handle = store.cohort(spec.cohort_id)
            status = _await_terminal(handle, run_id)
            assert status == "complete", (
                f"{label}: the console twin's run did not complete: {status}")
            for thread in threads.values():
                thread.join(timeout=60)
            _goto(page, "/monitor")
            assert re.search(r"complete|finished|done", spa.main_text(page), re.I), (
                f"{label}: the monitor screen does not show the run's terminal phase")
            _goto(page, f"/?class={spec.cohort_id}&run={run_id}")
            _badge_becomes(page, 7, "Done", "after a complete run")

            # -- the review queue, then the finalize control ----------------------------
            _goto(page, "/review")
            assert spa.main_text(page), f"{label}: the review screen renders nothing"
            _work_review_queue(store, run_id, spec.cohort_id)
            status, outcome = post_json(
                port, "/api/v1/actions/finalize-batch",
                {"run_id": run_id, "actor": "teacher"})
            assert status == 200 and not refused(status, outcome), (
                f"{label}: the finalize-batch control refused: {status} {outcome!r}")

            # -- results: the overview, the drill-down's justification ------------------
            doc = crw._get_json(port, f"/api/v1/results/screen?run_id={run_id}")
            assert doc["students"], (
                f"{label}: the results read names no student: {doc!r}")
            chosen = sorted(
                (student for student in doc["students"]),
                key=lambda student: str(student["student_ref"] or ""))[0]
            chosen_sid = str(chosen["submission_id"])
            chosen_ref = str(chosen["student_ref"] or "")
            detail = crw._get_json(
                port,
                f"/api/v1/results/student-detail?submission_id={chosen_sid}"
                f"&run_id={run_id}")
            gradable = [criterion for criterion in detail["criteria"]
                        if len(criterion.get("levels") or []) >= 2]
            assert gradable, (
                f"{label}: no criterion of the drill-down offers two levels: "
                f"{detail['criteria']!r}")
            cell = gradable[0]
            cid = str(cell["criterion_id"])
            _goto(page, "/results")
            assert spa.main_text(page), f"{label}: the results screen renders nothing"
            _goto(page, f"/results/students/{chosen_sid}")
            drill_text = spa.main_text(page)
            assert "What the paper shows" in drill_text, (
                f"{label}: the drill-down renders no justification — the evidence "
                "quotes the aggregation recorded are the journey's justification leg")
            assert cell["label"] in drill_text or cid in drill_text, (
                f"{label}: the drill-down does not show the criterion {cid!r}")

            # -- the override: the required reason, then the amendment ------------------
            before_digest = spa.store_digest(console_dir)
            grade_rows_before = _grade_revisions(store, spec, chosen_sid)
            # The request log runs the whole session; this leg's refusal checks read
            # the DELTA since the drill-down, not the session's earlier posts.
            override_posts_before = list(_action_urls(log))
            override = page.locator("details.override").first
            override.locator("summary").click()
            band = override.locator(f"select[name='criterion-band-{cid}']").first
            values = band.evaluate("el => Array.from(el.options).map(o => o.value)")
            target = next(value for value in values if value != band.input_value())
            # The override the CLI twin must mirror, noted where the mirror reads it —
            # the amendment's identity is the browser's choice, not a re-derivation.
            (scratch / "override.json").write_text(json.dumps(
                {"ref": chosen_ref, "criterion": cid, "band": target}),
                encoding="utf-8")
            band.select_option(target)
            assert _action_urls(log) == override_posts_before, (
                f"{label}: changing the band posted without the confirm: "
                f"{_action_urls(log)!r}")
            override.get_by_role("button", name="Save", exact=True).click()
            note = override.locator("p.inline-note")
            _wait_for(page, note.is_visible, "the required-reason refusal to render")
            assert "A reason is required to change a final grade" in note.inner_text(), (
                f"{label}: the refusal reads {note.inner_text()!r}")
            assert _action_urls(log) == override_posts_before, (
                f"{label}: the reasonless save posted: {_action_urls(log)!r}")
            override.locator("textarea[name='override-reason']").fill(spec.reason)
            override.get_by_role("button", name="Save", exact=True).click()
            _wait_for(page,
                      lambda: any("amend-a-finalized-grade" in url
                                  for url in _action_urls(log)
                                  if url not in override_posts_before),
                      "the amendment to post through the console's own action")
            _wait_for(page,
                      lambda: len(_grade_revisions(store, spec, chosen_sid))
                      == len(grade_rows_before) + 1,
                      "the amendment's revision to land in the store")
            changed = spa.changed_tables(before_digest, spa.store_digest(console_dir))
            assert any(key.endswith(":submission_grade") for key in changed) and \
                any(key.endswith(":audit_record") for key in changed), (
                f"{label}: the amendment landed {sorted(changed)!r}, not the grade "
                "revision plus its audit record")
            history = page.locator("section.amendment-history li")
            _wait_for(page,
                      lambda: history.count() > 0
                      and "Final grade changed from" in history.first.inner_text(),
                      "the amendment's render-back to appear")
            assert "the original grade is kept in the history" in history.first.inner_text()

            # -- the exports: the console's own reads ------------------------------------
            status, _headers, csv_bytes = get_bytes(
                port, "/api/v1/results/export",
                {"run_id": run_id, "format": "csv", "revision": "1"})
            assert status == 200 and csv_bytes, (
                f"{label}: the results-export read returned {status}, "
                f"{len(csv_bytes) if csv_bytes else 0} bytes of CSV")
            export_seen["csv"] = len(csv_bytes)
            status, _headers, pdf_bytes = get_bytes(
                port, "/api/v1/results/export",
                {"run_id": run_id, "format": "pdf", "revision": "1",
                 "student_ref": chosen_ref})
            assert status == 200 and pdf_bytes[:5] == b"%PDF-", (
                f"{label}: the per-student PDF export read returned {status}, "
                f"{pdf_bytes[:16]!r}")
            export_seen["pdf"] = chosen_ref
            status, _headers, workbook_bytes = get_bytes(
                port, "/api/v1/results/workbook",
                {"run_id": run_id, "revision": "1"})
            assert status == 200 and workbook_bytes, (
                f"{label}: the workbook read returned {status}, "
                f"{len(workbook_bytes) if workbook_bytes else 0} bytes")
            export_seen["workbook"] = len(workbook_bytes)
            status, _headers, readable_pdf = get_bytes(
                port, "/api/v1/packages/readable",
                {"package_version": version, "format": "pdf"})
            assert status == 200 and readable_pdf[:5] == b"%PDF-", (
                f"{label}: the readable PDF read returned {status}, "
                f"{readable_pdf[:16]!r}")
            export_seen["readable_pdf"] = len(readable_pdf)
            status, _headers, aehpkg_bytes = get_bytes(
                port, "/api/v1/packages/readable",
                {"package_version": version, "format": "aehpkg"})
            assert status == 200 and aehpkg_bytes, (
                f"{label}: the aehpkg read returned {status}, "
                f"{len(aehpkg_bytes) if aehpkg_bytes else 0} bytes")
            export_seen["aehpkg"] = len(aehpkg_bytes)

            # -- the wizard's last flips ---------------------------------------------------
            _goto(page, f"/?class={spec.cohort_id}&run={run_id}")
            _badge_becomes(page, 8, "Done", "after the finalize")
            stage9 = _stage(page, 9)
            _badge_becomes(page, 9, "Queued", "before the exports")
            assert _badge(page, 9) == "Queued", (
                f"{label}: stage 9 reads {_badge(page, 9)!r}; the export stands "
                "queued until the teacher takes it")
            action = stage9.locator("span.stage-action").inner_text()
            assert action.replace("Next action:", "").strip() == "Export the results", (
                f"{label}: stage 9's action reads {action!r}, not the export")
            next_line = page.locator("p.wizard-next").inner_text()
            assert next_line == "Next: Export the results.", (
                f"{label}: NEXT reads {next_line!r}")

            # -- the raw-vocabulary scan over every visited screen ------------------------
            problems = []
            for path, text in visited:
                for what, pattern in RAW_PATTERNS:
                    hit = pattern.search(text)
                    if hit:
                        problems.append(
                            f"the screen at {path!r} shows {what} ({hit.group(0)!r}) — "
                            "TC-CONSOLE-74's list applied to the visited set")
            assert not problems, (
                f"{label}: raw vocabulary reached the teacher:\n" + "\n".join(problems))
            foreign = [
                u for u in log.requests
                if urlsplit(u).scheme in ("http", "https", "ws", "wss")
                and urlsplit(u).netloc not in served_origins]
            assert not foreign, (
                f"{label}: the journey left the machine's boundary: {foreign}")
            assert not spa.rejections(page), (
                f"{label}: the journey left unhandled rejections: {spa.rejections(page)}")
    finally:
        server.terminate()


def _draft_job_id(port: int, label: str) -> str:
    """The newest ``authoring_draft`` job's id, once the browser's dispatch registered
    server-side (FR-CONSOLE-52)."""
    deadline = time.monotonic() + DRAFT_TIMEOUT_S
    while time.monotonic() < deadline:
        jobs = [job for job in crw._get_json(port, "/api/v1/jobs")["jobs"]
                if str(job.get("kind")) == "authoring_draft"]
        if jobs:
            return str(jobs[-1]["job_id"])
        time.sleep(0.25)
    raise AssertionError(
        f"{label}: the draft job never registered within {DRAFT_TIMEOUT_S}s")


def _wait_draft_job(port: int, label: str) -> dict[str, Any]:
    """The draft job the browser's confirm dispatched, waited out through the console's
    own jobs read (FR-CONSOLE-52): the newest ``authoring_draft`` job, terminal or not."""
    deadline = time.monotonic() + DRAFT_TIMEOUT_S
    job_id = _draft_job_id(port, label)
    return crw.wait_for_job(port, job_id, timeout=max(1.0, deadline - time.monotonic()))


def _wait_published(port: int, store, package_id: str, label: str) -> str:
    """The version the approve leg built, read from the store once it exists — the
    action's response can return before its write lands, so the version is waited for
    the way the override's revision is.

    The file check comes FIRST, and not as a nicety: a bare connect to a SQLite path
    mints the file it names (an empty one, which the console's build would then refuse
    as "already exists"), so the wait must never open a package file the build has not
    created yet. Until the build's schema commit lands a reader sees no
    `package_version` table at all, so that window reads as "no version yet"."""
    deadline = time.monotonic() + DRAFT_TIMEOUT_S
    path = store.package_path(package_id)
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                versions = rm.locked_versions(path)
            except sqlite3.OperationalError:
                versions = []  # the build's schema may still be committing
            if versions:
                return versions[0]
        time.sleep(0.25)
    raise AssertionError(
        f"{label}: the approve leg never published a version of {package_id!r} "
        f"within {DRAFT_TIMEOUT_S}s")


def _grade_revisions(store, spec: JourneySpec, submission_id: str) -> list[int]:
    rows = store.cohort(spec.cohort_id).query(
        "SELECT revision FROM submission_grade WHERE submission_id = :s "
        "ORDER BY revision", s=submission_id)
    return [int(row["revision"]) for row in rows]


def _ingest_console(store, cfg: Any, spec: JourneySpec, version: str,
                    assessment: Path, sheets: list[Path]) -> None:
    """The papers leg, console side: the same intake pipeline ``aeh ingest`` drives
    (``provider=None`` crosses the patched ``_provider_for`` seam)."""
    from aeh.pipeline.intake import answer_sheet_files, ingest_files

    run_config = resolve_run_config(
        select_profile_config(dict(cfg), "dev-ci"),
        CohortRef(cohort_id=spec.cohort_id, consent_class="synthetic"))
    result = ingest_files(
        store, run_config, spec.cohort_id, version, assessment=str(assessment),
        sheets=answer_sheet_files([str(p) for p in sheets]))
    bad = [(sheet.file, sheet.status, sheet.detail)
           for sheet in result.sheets if sheet.status != "ok"]
    assert not bad, f"{spec.label}: the console twin's papers did not read: {bad}"


# --- the CLI twin's legs ---------------------------------------------------------------------------------


def _cli_cohort(scratch: Path, spec: JourneySpec, data_dir: Path) -> None:
    """The class leg, CLI side: the real roster file through the real matcher — the
    same names the console's class action posted, so the generated refs are identical."""
    from aeh.pipeline import cli

    roster = scratch / "cli-roster.txt"
    roster.write_text("\n".join(STUDENT_NAMES) + "\n", encoding="utf-8", newline="\n")
    code = cli.main([
        "cohort", "create", "--data-dir", str(data_dir),
        "--cohort", spec.cohort_id, "--consent", "synthetic", "--roster", str(roster)])
    assert code == 0, "the CLI twin's cohort create failed"


def _cli_author_legs(scratch: Path, cli_dir: Path, cfg_path: Path, spec: JourneySpec,
                     qid: str, new_text: str,
                     monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """The authoring legs, CLI side: ``aeh author draft``, the stdin review walk, the
    editor's own structured-edit library, then ``aeh package build`` (its provider
    seam re-bound to a raising stub — the build makes no model call, and an unexpected
    one must be loud, the TC-E2E-07 disclosure). Returns ``(the draft file, version)``."""
    from aeh.author.edit import apply_structured_edit
    from aeh.pipeline import cli

    out = cli_dir / "authoring"
    code = cli.main([
        "author", "draft", "--config", str(cfg_path),
        "--docs", *[str(path) for path in spec.doc_paths],
        "--out", str(out)])
    assert code == 0, "the CLI twin's author draft failed"
    drafts = list(out.glob("*.package.draft.toml"))
    assert len(drafts) == 1, (
        f"{spec.label}: the CLI draft wrote {len(drafts)} drafts: {drafts!r}")
    draft_path = drafts[0]
    answers = spec.declared_answers()
    monkeypatch.setattr("sys.stdin", io.StringIO(
        "\n".join(answers.values()) + "\n", newline="\n"))
    code = cli.main(["author", "review", "--draft", str(draft_path)])
    assert code == 0, "the CLI twin's author review did not ready the draft"
    # The editor's save action calls this same library; the CLI rides it directly
    # (module docstring).
    apply_structured_edit(draft_path, "edit question",
                          params={"item_id": qid, "field": "text", "value": new_text})
    from aeh.pipeline import background, cli as cli_module, runtime

    def _no_provider(_config: object):
        raise AssertionError(
            "the CLI twin's package build made a model call — the build is a "
            "writer, not an inference step")

    monkeypatch.setattr(cli_module, "_provider_for", _no_provider)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main([
            "package", "build", "--data-dir", str(cli_dir), "--spec", str(draft_path)])
    assert code == 0, f"the CLI twin's package build failed: {buffer.getvalue()!r}"
    built = json.loads(buffer.getvalue())
    version = str(built["package_version"])
    # The run legs need the replay boundary back.
    def synthetic_provider(_environ_or_config: object):
        return jw.ReplayWithSynthFallback(scratch / "recordings")

    for site in (background, cli_module, runtime):
        monkeypatch.setattr(site, "_provider_for", synthetic_provider)
    return draft_path, version


def _cli_run_legs(scratch: Path, cli_dir: Path, cfg_path: Path, cli_store,
                  spec: JourneySpec, shape: _AdoptedShape, plans: tuple[_Plan, ...],
                  package_id: str, version: str) -> str:
    """The CLI twin's class, papers, run, review, finalize and override legs — the
    terminal's surface over the same bytes. Returns the run id it started."""
    from aeh.grade import GradingService
    from aeh.pipeline import cli

    _cli_cohort(scratch, spec, cli_dir)
    assessment, sheets = _write_papers(
        scratch / "cli-pdfs", shape, plans,
        {plan.name: [_page_text(shape, plan, package_id)] for plan in plans},
        [_assessment_text(shape, package_id)])
    code = cli.main([
        "ingest", "--data-dir", str(cli_dir), "--cohort", spec.cohort_id,
        "--package-version", version, "--config", str(cfg_path),
        "--assessment", str(assessment), *[str(p) for p in sheets]])
    assert code == 0, "the CLI twin's ingest failed"
    code = cli.main([
        "run", "--data-dir", str(cli_dir), "--cohort", spec.cohort_id,
        "--package-version", version, "--config", str(cfg_path)])
    assert code == 0, "the CLI twin's run did not complete"
    run_id = _minted_run_id(cli_store, spec, "the CLI twin's")
    _review_and_finalize(cli_store, run_id, spec.cohort_id)
    # The override's mirror: the same GradingService.amend the console's amend action
    # performs, with the same band's points, actor and reason — the revision and audit
    # rows the differential compares.
    note = _override_note(scratch)
    sid_rows = cli_store.cohort(spec.cohort_id).query(
        "SELECT submission_id FROM submission WHERE student_ref = :r",
        r=note["ref"])
    assert len(sid_rows) == 1, (
        f"{spec.label}: the CLI roster resolves {note['ref']!r} to "
        f"{len(sid_rows)} submission(s)")
    catalog = rm.catalog_for(cli_store, package_id)
    points = catalog.points_for_band(note["criterion"], note["band"])
    GradingService(cli_store).amend(
        run_id, str(sid_rows[0]["submission_id"]),
        {note["criterion"]: points}, "operator", spec.reason)
    return run_id


def _override_note(scratch: Path) -> dict[str, str]:
    """The override the console leg chose, noted where the CLI mirror reads it — the
    amendment's identity is the browser's choice, not a re-derivation."""
    note = scratch / "override.json"
    assert note.is_file(), (
        "the console's override leg never noted its target — the CLI mirror has "
        "nothing to mirror")
    return json.loads(note.read_text(encoding="utf-8"))


# --- the journey body ------------------------------------------------------------------------------------


def _open_store_with(data_dir: Path):
    """A store whose migration chain is complete — the package fixture writes Tier P/C."""
    for sub in ("packages", "cohorts", "blobs"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    from aeh.store import open_store

    return open_store(data_dir)


def run_full_journey(spec: JourneySpec, tmp_path_factory: pytest.TempPathFactory,
                     monkeypatch: pytest.MonkeyPatch) -> dict:
    """One journey, end to end: the gates, phase A, the capture leg, the console twin,
    the CLI twin, the pairing oracle. Returns the export ledger for the test's own
    closing assertions.

    The format gate runs first and honestly: a journey whose formats the console's
    upload read cannot carry yet never reaches stage 2 — `document_gates` raises the
    open finding, not a writtenahead claim.
    """
    bundle_gates()
    document_gates(spec)
    scratch = tmp_path_factory.mktemp(spec.af_id.lower())
    fixture_dir = scratch / "recordings"
    # The merged fixture dir (module docstring): the committed authoring corpus copied
    # in, so ONE provider dir serves the authoring legs' replays and the run legs'
    # capture.
    shutil.copytree(RECORDINGS, fixture_dir)
    for key, value in (
        ("HARNESS_PROFILE", "dev-ci"),  # pinned: env wins over cfg (conf.sources)
        ("HARNESS_FIXTURE_DIR", str(fixture_dir)),
        ("HARNESS_INGEST_DPI", "72"),
        ("HARNESS_INGEST_V4_SEMANTIC_FLOOR", "0.0"),
        ("HARNESS_ORCH_RANDOM_ARM_RATE", "0"),
    ):
        monkeypatch.setenv(key, value)
    _patch_all_provider_sites(monkeypatch, fixture_dir)

    cfg_path = scratch / "journey.dev-ci.toml"
    _config_toml(cfg_path, spec.transcriber_build, spec.judge_build)
    from aeh.pipeline.runtime import _load_config_file

    cfg = _load_config_file(str(cfg_path))

    # -- phase A + the capture leg -----------------------------------------------------
    capture_dir = scratch / "capture"
    capture_store = _open_store_with(capture_dir)
    try:
        package_id, qid, new_text = _phase_a(
            capture_store, cfg, spec, capture_dir / "authoring", fixture_dir)
        shape = _adopt_shape(capture_store, spec, package_id)
        plans = _plans_for(shape)
        world = JourneyWorld(capture_dir, fixture_dir, spec=spec, shape=shape,
                             cfg=cfg, monkeypatch=monkeypatch)
        world.build_run()
        world.start_run()
        from aeh.pipeline.driver import run_to_completion

        captured = run_to_completion(
            world.store, world.run_id, provider=world.provider,
            run_config=world.resolved)
        assert captured.status == "complete", (
            f"the capture's own journey did not complete: {captured.status} "
            f"{captured.pause_reason!r}")
    finally:
        _close(capture_store)

    # -- the console twin: the operator's surface ----------------------------------------
    console_dir = scratch / "console"
    console_store = _open_store_with(console_dir)
    export_seen: dict[str, object] = {}
    try:
        _serve_and_drive(console_store, console_dir, scratch, cfg, spec, shape,
                         plans, qid, new_text, export_seen)
    finally:
        _close(console_store)

    # -- the CLI twin: the terminal's surface --------------------------------------------
    cli_dir = scratch / "cli"
    cli_store = _open_store_with(cli_dir)
    try:
        _draft_path, version = _cli_author_legs(
            scratch, cli_dir, cfg_path, spec, qid, new_text, monkeypatch)
        _cli_run_legs(scratch, cli_dir, cfg_path, cli_store, spec, shape, plans,
                      package_id, version)
    finally:
        _close(cli_store)

    # -- the oracle -----------------------------------------------------------------------
    mask = _extend_mask_for_authoring(
        jw.pairing_mask(console_dir, cli_dir), console_dir, cli_dir)
    from tests.support.console_api_vocabulary import row_differences

    console_rows = jw.canonical_tier_rows(console_dir, mask=mask)
    cli_rows = jw.canonical_tier_rows(cli_dir, mask=mask)
    diffs = row_differences(console_rows, cli_rows)
    assert not diffs, (
        f"{spec.label}: the same journey over the same documents wrote different "
        f"stores — {len(diffs)} table(s) differ:\n"
        + "\n".join(f"  {d}" for d in diffs[:12]))
    assert export_seen, f"{spec.label}: the console's export leg never read the routes"
    return export_seen


__all__ = [
    "JOURNEY_AUTHORING_BUILD",
    "JourneySpec",
    "JourneyWorld",
    "RAW_PATTERNS",
    "RUN_TIMEOUT_S",
    "DRAFT_TIMEOUT_S",
    "STUDENT_NAMES",
    "bundle_gates",
    "document_gates",
    "journey_config_toml",
    "run_full_journey",
]
