"""Building and publishing a package from a written spec: `aeh package build` (live-test blocker B5).

Before this, a package could only be built by library calls (`docs/live-tests/sample-materials/
verify_sample_materials.py` was the working example), and the teacher's setup flow behind the
console holds no model. The teacher's path is the console's setup flow, which publishes the
package directly from its confirmed state (`M-SETUP`, `FR-PKG-27`); the spec TOML is a
system-emitted export (`aeh.pipeline.spec_export`), and this command remains as its
debugging/export inverse (Q-O6). A TOML file states the questions, the
rubric lines with their bands, the multiple-choice keys and the grade boundaries, and one command
builds the version through `M-PKG`'s own API and publishes it. `M-PKG` enforces its structural
rules (an even, contiguous band set; monotone points; distinct boundaries). Everything else a
published, permanent package could not later correct is checked here first, by `plan_package`,
before anything is written: a key among its question's options, every question graded, a judged
line only on a question that can carry one, explicit band points, known dependencies and scoring
models, and every field's type.

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


#: `M-PKG`'s scoring models (the column has no CHECK, and aggregation treats anything that is not
#: exactly `holistic` as atomic, so a typo would silently change how a line is scored).
SCORING_MODELS: tuple[str, ...] = ("atomic", "atomic_with_gate", "holistic")


def _evaluation_modes() -> tuple[str, ...]:
    """`M-PKG`'s declared evaluation modes (`FR-PKG-22`), read from the vocabulary module rather
    than restated: a widened vocabulary must not leave the spec checker behind."""
    from aeh.pkg.vocabulary import EVALUATION_MODES

    return EVALUATION_MODES


def _fail(message: str) -> PackageSpecError:
    return PackageSpecError(f"{message} Nothing was created.")


def _text(table: Mapping[str, Any], key: str, where: str, *, required: bool = True) -> str:
    value = table.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise _fail(f"{where}: '{key}' is required.")
        return ""
    if not isinstance(value, str):
        raise _fail(f"{where}: '{key}' must be text, got {type(value).__name__}.")
    return value.strip()


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(f"{where} must be a number, got {value!r}.")
    return float(value)


def _tables(spec: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    raw = spec.get(key)
    if not isinstance(raw, list) or not raw:
        raise _fail(f"the spec lists no [[{key}]].")
    if not all(isinstance(entry, Mapping) for entry in raw):
        raise _fail(f"every [[{key}]] must be a table of fields.")
    return raw


def packages_folder(store: Any) -> Path:
    """The folder package files live in (`packages/`), without opening any."""
    return Path(store.package_path("_")).parent


def check_package_id(packages_dir: Path, package_id: Any) -> str:
    """The id, or `PackageSpecError`: not a safe file name, or a package by that name (ignoring
    case: one file on Windows and macOS) already exists in `packages_dir`."""
    if (not isinstance(package_id, str) or not _PACKAGE_ID.match(package_id)
            or package_id.endswith(".") or _WINDOWS_RESERVED.match(package_id)):
        raise _fail(
            f"package id {package_id!r} is not allowed: use 1 to 64 letters, digits, '.', '_' "
            f"or '-', starting with a letter or digit, not ending in '.', and not a Windows "
            f"device name. It should be the test name printed on the paper.")
    if packages_dir.exists():
        for existing in packages_dir.glob("*.pkg.sqlite"):
            other = existing.name[: -len(".pkg.sqlite")]
            if other.casefold() == package_id.casefold():
                raise _fail(
                    f"package {other!r} already exists"
                    + ("" if other == package_id else
                       f" (the same name as {package_id!r} ignoring case, which is one file "
                       f"on Windows and macOS)")
                    + ". A built package is never changed: give the new one its own id.")
    return package_id


@dataclass(frozen=True)
class PackagePlan:
    """A spec checked and translated, with nothing written yet."""

    package_id: str
    approved_by: str
    questions: tuple[dict, ...]
    criteria: tuple[dict, ...]
    grades: tuple[tuple[str, float], ...]
    review_window_hours: int | None


def _criterion_method(table: Mapping[str, Any], cid: str, where: str) -> str:
    """The line's declared rubric method (`FR-PKG-24`), `bands` when omitted: every spec before
    the export vocabulary meant a bands criterion, and still does. Membership is exact —
    M-PKG refuses anything else at the write, and the checker refuses it here, by name."""
    method = _text(table, "score_method", where, required=False) or "bands"
    if method not in ("bands", "evidence_sum", "general"):
        raise _fail(f"{where} {cid!r}: score_method {method!r} is not one of "
                    "bands, evidence_sum, general (FR-PKG-24).")
    return method


def _passthrough_fields(table: Mapping[str, Any], where: str) -> dict[str, Any]:
    """The optional criterion columns the export carries back (`FR-PKG-27`): a rebuilt package
    keeps them, so its rows stay identical to the original's. Type-checked here; M-PKG refuses
    a value outside its own vocabulary at the write."""
    evaluation_mode = _text(table, "evaluation_mode", where, required=False) or None
    if evaluation_mode is not None and evaluation_mode not in _evaluation_modes():
        raise _fail(f"{where}: evaluation_mode {evaluation_mode!r} is not one of "
                    f"{', '.join(_evaluation_modes())} (FR-PKG-22).")
    return {
        "evaluation_mode": evaluation_mode,
        "construct_tag": _text(table, "construct_tag", where, required=False),
        "band_justification": _text(table, "band_justification", where, required=False)
        or None,
    }


def _depends(cid: str, table: Mapping[str, Any], ids: list[str], where: str) -> tuple[str, ...]:
    """The line's `depends_on`, as a tuple of ids the spec itself lists (`FR-PKG-05`)."""
    depends = table.get("depends_on", [])
    if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends):
        raise _fail(f"{where}: 'depends_on' is a list of criterion ids, such as [\"C3\"].")
    unknown = [d for d in depends if d not in ids or d == cid]
    if unknown:
        raise _fail(f"{where}: depends_on {unknown} names no other criterion in the spec.")
    return tuple(depends)


def _judged_line(
    cid: str, qid: str, translated: list[tuple[int, str, float, str]], scoring: str,
    depends: tuple[str, ...], table: Mapping[str, Any], method: str,
    ids: list[str], declared_methods: Mapping[str, str],
) -> dict:
    """A judged line that carries a band set: a `bands` criterion, a `general` criterion's
    confirmed set, or a composite's 2-band aspect. The aspect's `component_of` names an
    `evidence_sum` criterion elsewhere in the spec — checked here, so the export's shape
    refuses before anything is written (`FR-PKG-24`, `CT-PKG-21`)."""
    where = f"criterion {cid!r}"
    component_of = _text(table, "component_of", where, required=False) or None
    if component_of is not None:
        if method == "general":
            raise _fail(f"{where} is general, and a general criterion is standalone: it "
                        f"cannot be an aspect of {component_of!r} (CT-PKG-21).")
        if component_of == cid:
            raise _fail(f"{where} cannot be its own aspect.")
        if component_of not in ids or declared_methods.get(component_of) != "evidence_sum":
            raise _fail(f"{where}: component_of {component_of!r} names no evidence_sum "
                        "criterion in the spec.")
        if len(translated) != 2:
            raise _fail(f"{where} is an aspect of {component_of!r}, and an aspect is exactly "
                        "two bands (absent / present), not "
                        f"{len(translated)}.")
    fields = {
        "id": cid, "question": qid, "kind": "open", "bands": translated,
        "scoring": scoring, "depends_on": depends,
        "evidence_type": _text(table, "evidence_type", where, required=False)
        or DEFAULT_EVIDENCE_TYPE,
        "max_points": max(points for _, _, points, _ in translated),
        "score_method": method if method != "bands" else None,
        "component_of": component_of,
        "derivation_description": None,
    }
    fields.update(_passthrough_fields(table, where))
    return fields


def _composite(cid: str, qid: str, scoring: str, depends: tuple[str, ...],
               table: Mapping[str, Any]) -> dict:
    """An `evidence_sum` criterion: a grouping record over its aspects. It carries no band set
    and no key (`CT-PKG-21`) — the export emits its points, which are the sum of its aspects'
    maxima (`FR-PKG-25`)."""
    where = f"criterion {cid!r}"
    if "bands" in table:
        raise _fail(f"{where} is evidence_sum, and a composite carries no bands — its "
                    "aspects do (FR-PKG-24). List the aspects as their own two-band lines "
                    "with component_of naming this id.")
    if "key" in table:
        raise _fail(f"{where} is evidence_sum, and a composite carries no key (CT-PKG-21).")
    # `.get`, not a subscript: this is the operator's spec line, not the store's band column,
    # and TC-PKG-C05's static half scans subscripts to keep that column single-canonical.
    declared_points = table.get("points")
    if declared_points is None:
        raise _fail(f"{where}: 'points' is required (the composite's max is the sum of its "
                    "aspects' maxima, FR-PKG-25).")
    fields = {
        "id": cid, "question": qid, "kind": "open", "bands": [],
        "scoring": scoring, "depends_on": depends,
        "evidence_type": None,
        "max_points": _number(declared_points, f"{where}: 'points'"),
        "score_method": "evidence_sum", "component_of": None,
        "derivation_description": None,
    }
    fields.update(_passthrough_fields(table, where))
    return fields


def plan_package(spec: Mapping[str, Any], packages_dir: Path) -> PackagePlan:
    """Check the whole spec and translate it, touching nothing. Everything a published package
    could not later correct is refused here, because publication is permanent:

    * a key that is not one of its question's options (every student would be marked wrong);
    * a judged line (bands) on a multiple-choice question, a line with both a key and bands, and
      a question no line grades (intake's structure checks would then park every paper);
    * bands without explicit `points` (a best-first list would otherwise score backwards), and a
      `scoring` outside `M-PKG`'s vocabulary;
    * `depends_on` that is not a list of other lines in the spec;
    * a rubric method outside the closed set, an `evidence_sum` composite that carries bands or
      a key or no `points`, and an aspect that is not exactly two bands naming an `evidence_sum`
      line in the spec (`FR-PKG-24`, `CT-PKG-21`) — the vocabulary the spec export emits;
    * any field of the wrong type, named.
    """
    if not isinstance(spec, Mapping):
        raise _fail("the spec must be a table of fields.")
    package_id = check_package_id(packages_dir, spec.get("package"))
    approved_by = _text(spec, "approved_by", "the spec")

    questions: list[dict] = []
    for ordinal, table in enumerate(_tables(spec, "question")):
        qid = _text(table, "id", f"question #{ordinal + 1}")
        where = f"question {qid!r}"
        qtype = _text(table, "type", where, required=False) or "open"
        if qtype not in ("open", "mcq", "mixed"):
            raise _fail(f"{where}: type {qtype!r} is not one of open, mcq, mixed.")
        options = table.get("options", {})
        if not isinstance(options, Mapping) or not all(
                isinstance(label, str) for label in options.values()):
            raise _fail(f"{where}: 'options' is a table such as {{ A = \"...\", B = \"...\" }}.")
        if qtype in ("mcq", "mixed") and not options:
            raise _fail(f"{where} is {qtype} but lists no options.")
        if qtype == "open" and options:
            raise _fail(f"{where} is open but lists options; make it mcq or mixed.")
        questions.append({
            "question_id": qid, "ordinal": ordinal, "question_type": qtype,
            "prompt_text": _text(table, "text", where),
            "max_points": _number(table.get("points", 0), f"{where}: 'points'"),
            "options": [{"option_id": str(k), "ordinal": i, "label": label}
                        for i, (k, label) in enumerate(options.items())],
            "model_answer": _text(table, "model_answer", where, required=False),
        })
    by_id = {q["question_id"]: q for q in questions}
    if len(by_id) != len(questions):
        raise _fail("two [[question]] entries share an id.")

    criteria: list[dict] = []
    raw_criteria = _tables(spec, "criterion")
    ids = [_text(t, "id", "a [[criterion]]") for t in raw_criteria]
    if len(set(ids)) != len(ids):
        raise _fail("two [[criterion]] entries share an id.")
    declared_methods = {i: _criterion_method(t, i, "a [[criterion]]") for i, t in
                        zip(ids, raw_criteria)}
    for cid, table in zip(ids, raw_criteria):
        where = f"criterion {cid!r}"
        qid = _text(table, "question", where)
        if qid not in by_id:
            raise _fail(f"{where} names question {qid!r}, which the spec does not list.")
        question = by_id[qid]
        option_ids = [o["option_id"] for o in question["options"]]
        has_key, has_bands = "key" in table, "bands" in table
        if has_key and has_bands:
            raise _fail(f"{where} has both a 'key' and 'bands'; a line is one or the other.")
        if has_key:
            if declared_methods[cid] != "bands":
                raise _fail(f"{where} has a key, so its score_method is 'bands', not "
                            f"{declared_methods[cid]!r}.")
            key = table["key"]
            key_ids = [key] if isinstance(key, str) else key
            if not isinstance(key_ids, list) or not key_ids or not all(
                    isinstance(k, str) and k for k in key_ids):
                raise _fail(f"{where}: 'key' is an option id such as \"C\", or a list of them.")
            if not option_ids:
                raise _fail(f"{where} has a key but question {qid!r} has no options.")
            stray = [k for k in key_ids if k not in option_ids]
            if stray:
                raise _fail(f"{where}: key {stray} is not among question {qid!r}'s options "
                            f"{option_ids}.")
            criteria.append({"id": cid, "question": qid, "kind": "mcq", "key": list(key_ids),
                             "max_points": _number(table.get("points", 1), f"{where}: 'points'"),
                             "options": [(o["option_id"], o["label"])
                                         for o in question["options"]]})
            continue
        scoring = _text(table, "scoring", where, required=False) or "holistic"
        if scoring not in SCORING_MODELS:
            raise _fail(f"{where}: scoring {scoring!r} is not one of {', '.join(SCORING_MODELS)}.")
        depends = _depends(cid, table, ids, where)
        if declared_methods[cid] == "evidence_sum":
            criteria.append(_composite(cid, qid, scoring, depends, table))
            continue
        if not has_bands:
            raise _fail(f"{where} needs either a 'key' (multiple choice) or 'bands' (judged).")
        if question["question_type"] == "mcq":
            raise _fail(f"{where} is judged (bands) but question {qid!r} is multiple choice: "
                        f"give it a 'key', or make the question 'mixed'.")
        bands = table["bands"]
        if not isinstance(bands, list) or not bands or not all(
                isinstance(b, Mapping) for b in bands):
            raise _fail(f"{where}: 'bands' is a list of tables, worst first.")
        translated = []
        for ordinal, band in enumerate(bands):
            bwhere = f"{where} band {ordinal + 1}"
            if "points" not in band:
                raise _fail(f"{bwhere}: 'points' is required (bands are listed worst first, "
                            f"and the points say so).")
            translated.append((ordinal, _text(band, "name", bwhere),
                               _number(band.get("points"), f"{bwhere}: 'points'"),
                               _text(band, "descriptor", bwhere, required=False)))
        method = declared_methods[cid]
        if method == "general":
            derivation = _text(table, "derivation_description", where)
            criteria.append({
                "id": cid, "question": qid, "kind": "open", "bands": translated,
                "scoring": scoring, "depends_on": depends,
                "evidence_type": _text(table, "evidence_type", where, required=False)
                or DEFAULT_EVIDENCE_TYPE,
                "max_points": max(points for _, _, points, _ in translated),
                "score_method": method, "component_of": None,
                "derivation_description": derivation,
                **_passthrough_fields(table, where)})
            continue
        criteria.append(_judged_line(cid, qid, translated, scoring, depends,
                                     table, method, ids, declared_methods))
    ungraded = [q["question_id"] for q in questions
                if q["question_id"] not in {c["question"] for c in criteria}]
    if ungraded:
        raise _fail(f"question(s) {ungraded} have no rubric line; intake's structure check would "
                    f"then park every paper. Add a [[criterion]] for each, or remove them.")

    grades = spec.get("grades", {})
    if not isinstance(grades, Mapping):
        raise _fail("[grades] is a table such as { A = 8, B = 6 }.")
    window = spec.get("review_window_hours")
    if window is not None and (isinstance(window, bool) or not isinstance(window, int)
                               or window < 0):
        raise _fail("'review_window_hours' is a whole number of hours, 0 or more.")
    return PackagePlan(
        package_id=package_id, approved_by=approved_by, questions=tuple(questions),
        criteria=tuple(criteria),
        grades=tuple((str(g), _number(v, f"grade {g!r}")) for g, v in grades.items()),
        review_window_hours=window)


def build_package(store: Any, spec: Mapping[str, Any]) -> BuiltPackage:
    """Build the version the spec describes through `PackageCatalog`, and publish it.

    Everything checkable is checked first by `plan_package`, which writes nothing. A rule `M-PKG`
    itself enforces (band counts, monotone points, distinct boundaries) raises its own error
    after the package file exists; the half-built file is then removed, so a corrected spec
    builds under the same id. That cleanup closes the whole `store` (a tier handle cannot be
    closed alone), which is right for `aeh package build`, the one-shot command that owns it.
    """
    from aeh.pkg import PackageCatalog
    from aeh.pkg.spec_criteria import write_spec_criteria

    plan = plan_package(spec, packages_folder(store))
    path = Path(store.package_path(plan.package_id))
    existed = path.exists()
    try:
        catalog = PackageCatalog(store.package(plan.package_id), package_id=plan.package_id,
                                 blobs=store.blobs())
        catalog.ensure_package()
        version = catalog.create_version(None)
        payload = json.dumps([{k: q[k] for k in ("question_id", "prompt_text", "question_type")}
                              for q in plan.questions], sort_keys=True)
        catalog.record_proposal(
            version, proposal_id=f"spec-{uuid.uuid4().hex[:12]}",
            assessment_doc_id="spec:" + hashlib.sha256(payload.encode()).hexdigest()[:16],
            payload=payload, template_version=SPEC_TEMPLATE_VERSION,
            model_ref="operator-spec", attempts=1)
        catalog.write_confirmed_inventory(
            version, proposal_id=catalog.proposal(version)["proposal_id"],
            questions=[{k: v for k, v in q.items() if k != "model_answer"}
                       for q in plan.questions],
            confirmed_at=datetime.now(timezone.utc).isoformat())
        for q in plan.questions:
            if q["model_answer"]:
                catalog.update_question_field(version, q["question_id"], "reference_solution",
                                              q["model_answer"])
        write_spec_criteria(catalog, version, plan.criteria, plan.approved_by)
        if plan.grades:
            catalog.set_boundaries(version, list(plan.grades))
        if plan.review_window_hours is not None:
            catalog.set_review_window(version, plan.review_window_hours)
        catalog.publish(version, approved_by=plan.approved_by)
    except BaseException as error:
        # Remove the half-built package so a corrected spec builds under the same id, unless
        # the file was there before this command opened it. A cleanup failure never replaces
        # the error that explains what was wrong with the spec.
        try:
            store.close()
            if not existed:
                for suffix in ("", "-wal", "-shm"):
                    Path(str(path) + suffix).unlink(missing_ok=True)
        except Exception as cleanup:  # noqa: BLE001
            error.add_note(f"the half-built package at {path} could not be removed: {cleanup}")
        raise
    keys = sum(1 for c in plan.criteria if c["kind"] == "mcq")
    return BuiltPackage(package_id=plan.package_id, package_version=version,
                        questions=len(plan.questions), criteria=len(plan.criteria),
                        answer_keys=keys, grades=tuple(g for g, _ in plan.grades),
                        approved_by=plan.approved_by)
