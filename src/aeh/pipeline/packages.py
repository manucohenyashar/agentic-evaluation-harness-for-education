"""Building and publishing a package from a written spec: `aeh package build` (live-test blocker B5).

Before this, a package could only be built by library calls (`docs/live-tests/sample-materials/
verify_sample_materials.py` was the working example), and the teacher's setup flow behind the
console holds no model. This is the operator's path: a TOML file states the questions, the
rubric lines with their bands, the multiple-choice keys and the grade boundaries, and one command
builds the version through `M-PKG`'s own API and publishes it. Every structural rule is
`M-PKG`'s (bands even and contiguous, keys among the options, boundaries distinct...); this
module only translates the file and refuses what it cannot translate.

The question inventory is written, not skipped: a judge's criterion text and question come from
it (`judge/assembly.py` reads `catalog.questions`), so a package without questions sends a real
model nothing but band names.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

#: The spec's format version, recorded as the inventory "proposal" template.
SPEC_TEMPLATE_VERSION = "aeh-package-spec/1"


#: What `M-SETUP`'s read back attaches when a judged criterion declares no evidence type.
DEFAULT_EVIDENCE_TYPE = "textual_span"


#: A package id becomes a file name (`packages/<id>.pkg.sqlite`) and must equal the test name
#: printed on the paper (`Assessment: <name>`, compared ignoring case by intake's right-test
#: check), so upper case is allowed, and uniqueness ignoring case is checked against the folder.
_PACKAGE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


_WINDOWS_RESERVED = re.compile(r"\A(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?\Z", re.IGNORECASE)


class PackageSpecError(ValueError):
    """The spec cannot be built as written. Nothing was created."""


@dataclass(frozen=True)
class BuiltPackage:
    """What `aeh package build` made: the id to quote to `aeh run` and `aeh ingest`."""

    package_id: str
    package_version: str
    questions: int
    criteria: int
    answer_keys: int
    grades: tuple[str, ...]
    approved_by: str


def read_package_spec(path: str | Path) -> dict[str, Any]:
    """The spec file, parsed. TOML only; a parse error names the line."""
    try:
        return tomllib.loads(Path(path).read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as error:
        raise PackageSpecError(f"{path}: not valid TOML: {error}. Nothing was created.") from None


def _need(table: Mapping[str, Any], key: str, where: str, kind: type | tuple = str) -> Any:
    value = table.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise PackageSpecError(f"{where}: '{key}' is required. Nothing was created.")
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise PackageSpecError(f"{where}: '{key}' has the wrong type. Nothing was created.")
    return value


def _check_package_id(store: Any, package_id: Any) -> str:
    if (not isinstance(package_id, str) or not _PACKAGE_ID.match(package_id)
            or package_id.endswith(".") or _WINDOWS_RESERVED.match(package_id)):
        raise PackageSpecError(
            f"package id {package_id!r} is not allowed: use 1 to 64 letters, digits, '.', '_' "
            f"or '-', starting with a letter or digit, not ending in '.', and not a Windows "
            f"device name. It should be the test name printed on the paper. Nothing was "
            f"created.")
    folder = Path(store.package_path(package_id)).parent
    if folder.exists():
        for existing in folder.glob("*.pkg.sqlite"):
            other = existing.name[: -len(".pkg.sqlite")]
            if other.casefold() == package_id.casefold():
                raise PackageSpecError(
                    f"package {other!r} already exists"
                    + ("" if other == package_id else
                       f" (the same name as {package_id!r} ignoring case, which is one file "
                       f"on Windows and macOS)")
                    + ". A built package is never changed: give the new one its own id. "
                      "Nothing was created.")
    return package_id


def _questions(spec: Mapping[str, Any]) -> list[dict]:
    raw = spec.get("question")
    if not isinstance(raw, list) or not raw:
        raise PackageSpecError("the spec lists no [[question]]. Nothing was created.")
    questions = []
    for ordinal, table in enumerate(raw):
        where = f"question #{ordinal + 1}"
        qid = _need(table, "id", where)
        qtype = str(table.get("type", "open"))
        options = table.get("options") or {}
        if not isinstance(options, Mapping):
            raise PackageSpecError(f"question {qid!r}: 'options' is a table such as "
                                   f"{{ A = \"...\", B = \"...\" }}. Nothing was created.")
        if qtype == "mcq" and not options:
            raise PackageSpecError(f"question {qid!r} is mcq but lists no options. Nothing "
                                   f"was created.")
        questions.append({
            "question_id": qid, "ordinal": ordinal, "question_type": qtype,
            "prompt_text": _need(table, "text", f"question {qid!r}"),
            "max_points": float(table.get("points", 0)),
            "options": [{"option_id": str(k), "ordinal": i, "label": str(v)}
                        for i, (k, v) in enumerate(options.items())],
            "model_answer": str(table.get("model_answer", "") or ""),
        })
    return questions


def build_package(store: Any, spec: Mapping[str, Any]) -> BuiltPackage:
    """Build the version the spec describes through `PackageCatalog`, and publish it.

    Refused before anything is written: a missing or unsafe package id, an id that exists
    (ignoring case), a missing `approved_by`, no questions, a criterion naming an unknown
    question, an mcq criterion without a key, a judged criterion without bands. A rule
    `M-PKG` itself enforces (band counts, points, keys among the options, distinct
    boundaries) raises its own error; the half-built package file is then removed, so a
    corrected spec can be built under the same id.
    """
    from aeh.pkg import PackageCatalog

    package_id = _check_package_id(store, spec.get("package"))
    approved_by = _need(spec, "approved_by", "the spec")
    questions = _questions(spec)
    by_id = {q["question_id"]: q for q in questions}
    if len(by_id) != len(questions):
        raise PackageSpecError("two [[question]] entries share an id. Nothing was created.")
    criteria = spec.get("criterion")
    if not isinstance(criteria, list) or not criteria:
        raise PackageSpecError("the spec lists no [[criterion]]. Nothing was created.")
    for table in criteria:
        cid = _need(table, "id", "a [[criterion]]")
        qid = _need(table, "question", f"criterion {cid!r}")
        if qid not in by_id:
            raise PackageSpecError(f"criterion {cid!r} names question {qid!r}, which the "
                                   f"spec does not list. Nothing was created.")
        if "key" in table:
            if not by_id[qid]["options"]:
                raise PackageSpecError(f"criterion {cid!r} has a key but question {qid!r} has "
                                       f"no options. Nothing was created.")
        elif not table.get("bands"):
            raise PackageSpecError(f"criterion {cid!r} needs either a 'key' (multiple choice) "
                                   f"or 'bands' (judged). Nothing was created.")
    grades = spec.get("grades") or {}
    if not isinstance(grades, Mapping):
        raise PackageSpecError("[grades] is a table such as { A = 8, B = 6 }. Nothing was "
                               "created.")

    handle = store.package(package_id)
    path = Path(store.package_path(package_id))
    try:
        catalog = PackageCatalog(handle, package_id=package_id, blobs=store.blobs())
        catalog.ensure_package()
        version = catalog.create_version(None)
        payload = json.dumps([{k: q[k] for k in ("question_id", "prompt_text", "question_type")}
                              for q in questions], sort_keys=True)
        catalog.record_proposal(
            version, proposal_id=f"spec-{uuid.uuid4().hex[:12]}",
            assessment_doc_id="spec:" + hashlib.sha256(payload.encode()).hexdigest()[:16],
            payload=payload, template_version=SPEC_TEMPLATE_VERSION,
            model_ref="operator-spec", attempts=1)
        proposal = catalog.proposal(version)
        catalog.write_confirmed_inventory(
            version, proposal_id=proposal["proposal_id"],
            questions=[{k: v for k, v in q.items() if k != "model_answer"} for q in questions],
            confirmed_at=datetime.now(timezone.utc).isoformat())
        for q in questions:
            if q["model_answer"]:
                catalog.update_question_field(version, q["question_id"], "reference_solution",
                                              q["model_answer"])
        keys = 0
        for table in criteria:
            cid, qid = table["id"], table["question"]
            if "key" in table:
                points = float(table.get("points", 1))
                catalog.add_criterion(version, cid, question_id=qid, kind="mcq",
                                      max_points=points, scoring_model="atomic", band_count=2)
                catalog.add_band(version, cid, 0, "incorrect", 0.0)
                catalog.add_band(version, cid, 1, "correct", points)
                catalog.set_mcq_options(version, cid, [(o["option_id"], o["label"])
                                                       for o in by_id[qid]["options"]])
                key = table["key"]
                catalog.set_answer_key(version, cid, [key] if isinstance(key, str) else list(key))
                keys += 1
                continue
            bands = table["bands"]
            catalog.add_criterion(
                version, cid, question_id=qid, kind="open",
                max_points=max(float(b.get("points", 0)) for b in bands),
                scoring_model=str(table.get("scoring", "holistic")),
                dependencies=tuple(table.get("depends_on", ())), band_count=len(bands),
                evidence_type=str(table.get("evidence_type", DEFAULT_EVIDENCE_TYPE)))
            for ordinal, band in enumerate(bands):
                catalog.add_band(version, cid, ordinal,
                                 _need(band, "name", f"criterion {cid!r} band {ordinal}"),
                                 float(band.get("points", ordinal)),
                                 str(band.get("descriptor", "")))
        if grades:
            catalog.set_boundaries(version, [(str(g), float(v)) for g, v in grades.items()])
        if spec.get("review_window_hours"):
            catalog.set_review_window(version, int(spec["review_window_hours"]))
        catalog.publish(version, approved_by=str(approved_by))
    except Exception:
        # The package file was created by this command; a refusal leaves no half package behind,
        # so the corrected spec can be built under the same id.
        try:
            store.close()
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
        raise
    return BuiltPackage(package_id=package_id, package_version=version,
                        questions=len(questions), criteria=len(criteria), answer_keys=keys,
                        grades=tuple(str(g) for g in grades), approved_by=str(approved_by))
