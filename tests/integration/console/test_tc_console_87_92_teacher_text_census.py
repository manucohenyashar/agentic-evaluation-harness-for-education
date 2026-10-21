"""`TC-CONSOLE-87` and `TC-CONSOLE-92` (issue #815) — the teacher-text census over the console
API, and the three parts of every refusal it meets.

Console clarity test plan §3.4, story T4.

| Case | What is asserted |
|---|---|
| 87 (FR-UI-23, FR-CONSOLE-71, CT-CONSOLE-53; RC-12) | every read in `API_ROUTES` and every action in `controls_payload()` is driven (success, refusal and job arms); no string field of any JSON answer matches an FR-UI-23 pattern: a requirement/test ID, a `@<12 hex>` version hash, `pkg-`, a UUID, a path separator before a `.sqlite`/`.toml` name, or `[[` |
| 92 (FR-UI-25, FR-UI-22, CT-CONSOLE-33) | over 87's refusal arms (a refused action, a refusing read): `what`, `why` and `next_action` are each non-empty and end in sentence punctuation; no refusal names a student by `student_ref`, and the refusal about a listed student names them by their name |

**The matrix.** One real console over one real store (rung 3), with:

* the existing `console_world` seed (`seed_scored_run`): a scored run whose id is a UUID, as
  real run ids are — so a refusal or label that echoes the run id is caught;
* an ENG7 package and draft the test builds inline (no other story's fixture): the shipped
  `docs/live-tests/config/eng7-read-01.package.toml` written as a draft whose grade table
  names `pass` without a boundary, with the gap's comment as `aeh.author` renders it today
  (`"... a boundary is never invented (FR-AUTHOR-08)"`, the teacher's T1). It is approved
  with the gap open (refusal), the gap answered (success), approved (success) and approved
  again (the T2b arm);
* a named class created through the `create class` action, and the student arms over it;
* a recorded draft job (`AF-02`, the F-AUTHOR corpus) for the job arms.

Every read is driven three ways — bare, with the seeded references, and with unknown ones —
and every action twice — with an empty body and with unknown references — besides the
curated success arms above.

**Readings, disclosed in the PR.**

* *ID fields.* Keys named `id`, `*_id` or `*_ids` are exempt by name (the plan exempts
  `*_id`; `id`/`*_ids` are the same thing spelled for one id or a list of them). Dictionary
  keys are structure and are not scanned; values are. Id-valued fields *not* so named —
  `context.packages[].published_version`, `impact.package_version`,
  `results class .rollup.segments[].rubric_version` — are scanned, by the plan's wording
  ("`*_id` exempt"). The SPA sends `published_version` back as a request parameter, and
  `PackageSetup.tsx` also shows it to the teacher, so the census asks #808 to split each one into
  an `*_id` field plus a teacher label rather than run it through `teacher_text()`.
* *File answers* (the CSV/PDF/workbook exports) are not scanned: FR-CONSOLE-74 keeps the
  `<package>@<hash>` form in exports.
* *The refusal shape.* FR-UI-25 names "the existing `what`/`why`/`next_action` shape". Today's
  action body carries `detail` (+ `next_action` when set) and a refusing read answers
  `{"error": ...}`; neither carries `what`/`why`. The case asserts the design's three keys on
  both, so #808 adds them (keeping `detail`/`error` beside them is not forbidden).

**Isolation: rung 3 (E1).** **Written ahead of implementation: yes** (#808): both cases are
red until every display string passes `teacher_text()` and every refusal has three parts.

**Markers.** `integration` (the fast tier excludes it) and `writtenahead`, keyed in
`WRITTEN_AHEAD_BLOCKERS` under #808.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote, urlencode

import pytest

import aeh.agg  # noqa: F401 — the full migration chain before the first store open (CLAUDE.md)
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
from aeh.console.api import API_ROUTES, controls_payload
from tests.support.console_redesign_world import (
    _request,
    served_authoring,  # noqa: F401 — the fixture
    start_draft,
    wait_for_job,
)
from tests.support.console_world import seed_scored_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

REPO_ROOT = Path(__file__).resolve().parents[3]
ENG7_SPEC = REPO_ROOT / "docs" / "live-tests" / "config" / "eng7-read-01.package.toml"
ENG7 = "ENG7-READ-01"

#: FR-UI-23's patterns, as TC-CONSOLE-87 states them.
CENSUS_PATTERNS: dict[str, re.Pattern[str]] = {
    "requirement or test id": re.compile(r"\b(FR|NFR|CT|TC|ADR|RS)-[A-Z0-9]+(-\d+)?\b"),
    "package-version hash": re.compile(r"@[0-9a-f]{12}\b"),
    "internal package ref": re.compile(r"\bpkg-"),
    "uuid": re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    "file path": re.compile(r"[\\/][^\s\\/'\"]*\.(sqlite|toml)\b"),
    "toml fragment": re.compile(r"\[\["),
}

#: A sentence ends in `.`, `!` or `?`, optionally inside a closing quote or bracket.
SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*\Z")

#: The seeded references. The run id is a UUID because real run ids are (FR-UI-23 names "a
#: `run_id` UUID"); the package id is a teacher's test name, so a `pkg-` hit is the console's.
SEEDED_RUN = str(uuid.UUID(int=0x5EED_0087))
SEEDED_COHORT = "eng7-census"
SEEDED_PACKAGE = "PHYS-QUIZ-01"
CLASS_ID = "year7-english"
CLASS_NAMES = (("Maya", "Cohen"), ("Noam", "Peretz"), ("Lior", "Ben-David"))
UNKNOWN = {
    "run_id": str(uuid.UUID(int=0xDEAD_0087)),
    "cohort_id": "no-such-class",
    "class_id": "no-such-class",
    "package_id": "NO-SUCH-TEST",
    "package_version": "NO-SUCH-TEST@0123456789ab",
    "submission_id": "no-such-paper",
    "student_ref": "no-such-student",
    "job_id": str(uuid.UUID(int=0xB0B_0087)),
    "manual_id": "no-such-manual",
}


@dataclass
class Arm:
    """One driven request and what the console answered."""

    label: str
    method: str
    path: str
    status: int
    body: Any  # the JSON answer, or None for a file answer
    kind: str  # "read" | "action"

    @property
    def refused(self) -> bool:
        if not isinstance(self.body, dict):
            return False
        if self.kind == "action" and self.status == 200:
            return self.body.get("refused") is True
        return 400 <= self.status < 500


@dataclass
class Matrix:
    arms: list[Arm] = field(default_factory=list)
    student_refs: dict[str, str] = field(default_factory=dict)  # ref -> full name
    named_refusals: list[tuple[Arm, str]] = field(default_factory=list)  # (arm, full name)


# --- driving ------------------------------------------------------------------------------------


def _call(matrix: Matrix, port: int, label: str, method: str, path: str,
          body: dict[str, Any] | None, kind: str) -> Arm:
    status, headers, raw = _request(port, method, path, body)
    content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
    answer: Any = None
    if "json" in content_type:
        answer = json.loads(raw)
    arm = Arm(label, method, path, status, answer, kind)
    matrix.arms.append(arm)
    return arm


def _fill(template: str, params: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: quote(params.get(m.group(1), "x"), safe=""), template)


def _drive_reads(matrix: Matrix, port: int, label: str, params: dict[str, str]) -> None:
    query = urlencode(params)
    for route in API_ROUTES:
        if route.read is None:
            continue
        if route.read == "help ask" and params:
            continue  # asking a question calls the assistant's model; bare is the refusal arm
        path = _fill(route.path, params)
        if route.method == "GET":
            _call(matrix, port, f"{label} read {route.read!r}", "GET",
                  f"{path}?{query}" if query else path, None, "read")
        else:
            _call(matrix, port, f"{label} read {route.read!r}", route.method, path,
                  dict(params), "read")


def _drive_actions(matrix: Matrix, port: int, label: str, params: dict[str, str]) -> None:
    controls = controls_payload()["controls"]
    assert controls, "controls_payload() lists no action: the census would prove nothing"
    reads = {r.path for r in API_ROUTES if r.read is not None}
    for control in controls:
        if control["path"] in reads:
            continue  # the POST reads are driven as reads
        _call(matrix, port, f"{label} action {control['action']!r}", control["method"],
              control["path"], dict(params), "action")


def _action(matrix: Matrix, port: int, action: str, params: dict[str, Any]) -> Arm:
    route = next(r for r in API_ROUTES if r.control == action and r.read is None)
    return _call(matrix, port, f"action {action!r}", route.method, route.path, params,
                 "action")


def _eng7_draft_text() -> str:
    """The shipped ENG7 spec as a draft whose grade table names `pass` with no boundary —
    the comment above the sentinel exactly as `aeh.author`'s renderer writes it today."""
    text = ENG7_SPEC.read_text(encoding="utf-8")
    text = text.replace('approved_by = "Sample-materials teacher"',
                        'approved_by = "Dana Teacher"')
    gap = (
        "# PLACEHOLDER(the document names the grade but states no boundary for it, and a "
        "boundary is never invented (FR-AUTHOR-08)): the minimum mark or percentage for "
        "grade pass\n"
        'pass = "<<PLACEHOLDER: grades pass>>"\n'
    )
    assert "\npass = 6\n" in text, "the shipped ENG7 spec no longer carries `pass = 6`"
    return text.replace("\npass = 6\n", "\n" + gap)


def _drive_matrix(port: int, store: Any, data_dir: Path) -> Matrix:
    matrix = Matrix()

    # The console_world seed: a scored run under a UUID run id, its open criteria queued.
    seeded = seed_scored_run(store, cohort_id=SEEDED_COHORT, run_id=SEEDED_RUN,
                             package_id=SEEDED_PACKAGE, submissions=2,
                             with_open_criteria=True, finalize=False)
    for submission in seeded.submissions:
        matrix.student_refs[f"ref-{submission}"] = ""

    # A named class, through the console's own action (success arm).
    created = _action(matrix, port, "create class", {
        "class_id": CLASS_ID, "consent_class": "synthetic",
        "rows": [{"first_name": first, "last_name": last} for first, last in CLASS_NAMES],
    })
    assert created.status == 200 and created.body.get("refused") is False, (
        f"the class could not be created, so the student arms cannot run: {created.body!r}")
    for row in store.cohort(CLASS_ID).query("SELECT student_ref, full_name FROM roster"):
        matrix.student_refs[str(row["student_ref"])] = str(row["full_name"])
    ref, name = next((r, n) for r, n in matrix.student_refs.items() if n)

    # The student arms: a refused rename (no new name) names the student; a real rename.
    refused_rename = _action(matrix, port, "rename student",
                             {"cohort_id": CLASS_ID, "student_ref": ref, "full_name": ""})
    matrix.named_refusals.append((refused_rename, name))
    _action(matrix, port, "move paper to student", {
        "cohort_id": CLASS_ID, "submission_id": "no-such-paper", "student_ref": ref})
    _action(matrix, port, "rename student",
            {"cohort_id": CLASS_ID, "student_ref": ref, "full_name": f"{name} Jr"})
    matrix.student_refs[ref] = f"{name} Jr"

    # The inline ENG7 draft: read it with its gap, approve it too early, answer the gap,
    # approve it, approve it again.
    authoring = Path(data_dir, "authoring")
    authoring.mkdir(parents=True, exist_ok=True)
    Path(authoring, f"{ENG7}.package.draft.toml").write_text(_eng7_draft_text(),
                                                            encoding="utf-8")
    eng7 = {"package_id": ENG7}
    _call(matrix, port, "read ENG7 draft", "GET",
          f"/api/v1/authoring/draft?{urlencode(eng7)}", None, "read")
    _action(matrix, port, "approve draft package", eng7)  # the gap is open: a refusal
    answered = _action(matrix, port, "answer authoring review",
                       {**eng7, "item_id": "grades pass", "value": "6"})
    assert answered.body.get("refused") is False, (
        f"the ENG7 gap could not be answered: {answered.body!r}")
    published = _action(matrix, port, "approve draft package", eng7)
    assert published.body.get("refused") is False, (
        f"the answered ENG7 draft was not published: {published.body!r}")
    _action(matrix, port, "approve draft package", eng7)  # the repeat press (T2b)
    _call(matrix, port, "read ENG7 draft after approval", "GET",
          f"/api/v1/authoring/draft?{urlencode(eng7)}", None, "read")

    # The job arms: a recorded draft job, its reads, and the cancel of the finished job.
    started = start_draft(port, "AF-02")
    matrix.arms.append(Arm("action 'draft package from documents'", "POST",
                           "/api/v1/actions/draft-package-from-documents", 200, started,
                           "action"))
    assert started.get("dispatched"), f"the recorded draft job did not start: {started!r}"
    job_id = started["job_id"]
    wait_for_job(port, job_id)
    _call(matrix, port, "read job", "GET", f"/api/v1/jobs/{quote(job_id, safe='')}", None,
          "read")
    _call(matrix, port, "read jobs", "GET", "/api/v1/jobs", None, "read")
    _action(matrix, port, "cancel job", {"job_id": job_id})
    _action(matrix, port, "draft package from scratch", {"title": "Year 7 poetry quiz"})

    # Every read: bare, seeded (the scored run, then the ENG7 package), unknown.
    _drive_reads(matrix, port, "bare", {})
    _drive_reads(matrix, port, "seeded run", {
        "run_id": seeded.run_id, "cohort_id": seeded.cohort_id,
        "package_id": seeded.package_id, "package_version": seeded.package_version_id,
        "submission_id": seeded.submissions[0], "student_ref": f"ref-{seeded.submissions[0]}",
        "job_id": job_id, "manual_id": _first_manual(port),
    })
    _drive_reads(matrix, port, "seeded ENG7", {
        "package_id": ENG7, "cohort_id": CLASS_ID, "student_ref": ref,
        "package_version": _eng7_version(store),
    })
    _drive_reads(matrix, port, "unknown", dict(UNKNOWN))

    # Every action: an empty body, then unknown references (the refusal arms).
    _drive_actions(matrix, port, "empty", {})
    _drive_actions(matrix, port, "unknown", dict(UNKNOWN))
    return matrix


def _first_manual(port: int) -> str:
    status, _headers, raw = _request(port, "GET", "/api/v1/manuals")
    assert status == 200, raw
    manuals = json.loads(raw)
    found = re.search(r'"(?:manual_id|id)":\s*"([^"]+)"', json.dumps(manuals))
    return found.group(1) if found else "x"


def _eng7_version(store: Any) -> str:
    rows = store.package(ENG7).query("SELECT package_version_id FROM package_version")
    assert rows, "the ENG7 package was approved but no package version stands"
    return str(rows[-1]["package_version_id"])


# --- the census ---------------------------------------------------------------------------------


def _exempt(key: str) -> bool:
    return key == "id" or key.endswith("_id") or key.endswith("_ids")


def _strings(value: Any, where: str = "") -> Iterator[tuple[str, str]]:
    """Every string field of a JSON answer as `(json path, text)`, ID fields skipped."""
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, dict):
        for key, item in value.items():
            if _exempt(str(key)):
                continue
            yield from _strings(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{where}[{index}]")


def _report(lines: list[str], limit: int = 150) -> str:
    shown = "\n  ".join(lines[:limit])
    more = f"\n  ... and {len(lines) - limit} more" if len(lines) > limit else ""
    return f"\n  {shown}{more}"


def test_tc_console_87_no_console_api_string_leaks_an_internal_id(served_authoring):
    """TC-CONSOLE-87: drive every read and every action — success, refusal and job arms — and
    no string field of any answer matches an FR-UI-23 pattern."""
    _server, port, store, data_dir = served_authoring
    matrix = _drive_matrix(port, store, data_dir)

    json_arms = [arm for arm in matrix.arms if arm.body is not None]
    driven = {arm.path.split("?")[0] for arm in matrix.arms}
    for route in API_ROUTES:
        if "{" not in route.path:
            assert route.path in driven, f"the census never drove {route.method} {route.path}"
    assert any(arm.refused for arm in json_arms), "the matrix met no refusal arm"
    assert any(arm.kind == "action" and arm.body.get("refused") is False
               for arm in json_arms), "the matrix met no success arm"

    hits: list[str] = []
    for arm in json_arms:
        for where, text in _strings(arm.body):
            for name, pattern in CENSUS_PATTERNS.items():
                found = pattern.search(text)
                if found:
                    start = max(0, found.start() - 40)
                    hits.append(f"{arm.label} [{arm.status}] {where}: {name} "
                                f"{found.group()!r} in ...{text[start:found.end() + 40]!r}")
    assert not hits, (
        f"{len(hits)} teacher-facing string(s) leak an internal id (FR-UI-23):"
        f"{_report(hits)}")


def test_tc_console_92_every_refusal_says_what_why_and_next(served_authoring):
    """TC-CONSOLE-92: over 87's refusal arms, `what`, `why` and `next_action` are full
    sentences; students are named by name, never by `student_ref`."""
    _server, port, store, data_dir = served_authoring
    matrix = _drive_matrix(port, store, data_dir)

    refusals = [arm for arm in matrix.arms if arm.refused]
    assert len(refusals) >= 20, (
        f"the matrix met only {len(refusals)} refusal arm(s): too few to stand for the "
        "console's refusals")

    faults: list[str] = []
    refs = [r for r in matrix.student_refs if r]
    for arm in refusals:
        for part in ("what", "why", "next_action"):
            text = arm.body.get(part)
            if not isinstance(text, str) or not text.strip():
                faults.append(f"{arm.label} [{arm.status}]: no {part!r} "
                              f"(body keys {sorted(arm.body)})")
            elif not SENTENCE_END.search(text.strip()):
                faults.append(f"{arm.label}: {part!r} is not a full sentence: {text!r}")
        spoken = json.dumps({k: v for k, v in arm.body.items() if not _exempt(str(k))})
        for ref in refs:
            if re.search(rf"(?<![\w-]){re.escape(ref)}(?![\w-])", spoken):
                faults.append(f"{arm.label}: names a student by their ref {ref!r}")

    for arm, name in matrix.named_refusals:
        assert arm.refused, f"{arm.label} was expected to refuse: {arm.body!r}"
        said = " ".join(str(arm.body.get(p) or "") for p in ("what", "why", "next_action"))
        if name not in said:
            faults.append(f"{arm.label}: the refusal about {name!r} does not name them: "
                          f"{said!r}")

    assert not faults, (
        f"{len(faults)} refusal fault(s) (FR-UI-25, FR-UI-22):{_report(faults)}")
