"""The system-emitted spec export: `aeh package export` (`FR-PKG-27`, R-12).

The package spec TOML is not a teacher-authored input — the console publishes the package
directly from the setup flow's confirmed state (`M-SETUP`, `SetupService.publish`). This module
is the inverse of `aeh.pipeline.packages`: it reads one package version out of the Tier P file
through `PackageCatalog`'s own read-backs and writes the spec that `aeh package build --spec`
accepts unchanged, so the spec exists only as a system-emitted artifact and a debugging inverse
(Q-O6).

Every field the store carries that the build path can express is emitted, so a rebuilt package
is row-identical to the original (`TC-PKG-37`'s differential over the store rows): questions
with their options and model answers, criteria with bands, keys, dependencies, scoring models,
evidence types, rubric methods, aspect links and construct tags — and, for a `general`
criterion, the derivation provenance (the teacher's description and the confirmed band set).
A column the build path cannot express has no spec field, so an export never writes a field
build would silently drop.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aeh.pkg import points_for_band
from aeh.pkg.spec_criteria import JUDGED_SCORING
from aeh.pkg.vocabulary import DEFAULT_SCORE_METHOD, default_evaluation_mode

from .packages import DEFAULT_EVIDENCE_TYPE, PackageSpecError, SPEC_TEMPLATE_VERSION

#: `<package_id>@<12 hex>`, the form `PackageCatalog.create_version` mints. The package id
#: itself cannot contain `@` (`_PACKAGE_ID`), so the split is unambiguous.
_VERSION_ID = re.compile(r"\A(?P<package_id>[A-Za-z0-9][A-Za-z0-9._-]{0,63})"
                         r"@[0-9a-f]{12}\Z")


@dataclass(frozen=True)
class ExportedSpec:
    """What `aeh package export` wrote, for the command's JSON report."""

    package_id: str
    package_version: str
    spec: str
    template_version: str
    questions: int
    criteria: int
    #: `general` criteria whose derivation provenance travelled (FR-PKG-27's failure path).
    derivations: int
    bytes_written: int


def export_spec(store: Any, package_version: str, dest: str | Path) -> ExportedSpec:
    """Write the spec for `package_version` to `dest`, reading only, writing only the file.

    Refuses (with `PackageSpecError`) a version id that does not name a package file, a
    version that does not exist in it, and an unpublished version: the spec is the export of
    a confirmed setup, and a draft's setup is not confirmed yet — the console publishes the
    draft's package directly from that state, with no spec in the teacher's path."""
    match = _VERSION_ID.fullmatch(str(package_version))
    if match is None:
        raise PackageSpecError(
            f"package version {package_version!r} is not a package version id "
            "(<package>@<12 hex>, as `aeh package build` and the console print it). "
            "Nothing was exported."
        )
    package_id = match.group("package_id")
    package_file = store.package_path(package_id)
    if not package_file.is_file():
        raise PackageSpecError(
            f"no package file for {package_id!r} (looked for {package_file}): the export "
            "writes the spec of a package the setup flow or `aeh package build` created. "
            "Nothing was exported."
        )
    from aeh.pkg import PackageCatalog

    # Read-only (FR-STORE-13): the export only reads, and a writable open would create and
    # migrate the file when it is missing — a refused export must leave the data directory
    # exactly as it was.
    catalog = PackageCatalog(store.package(package_id, read_only=True),
                             package_id=package_id)
    published_by = catalog.published_by(package_version)
    if published_by is None:
        raise PackageSpecError(
            f"package version {package_version!r} is not published, so it is not an export "
            "of a confirmed setup: the console publishes the package directly from the setup "
            "flow's confirmed state, and `aeh package export` writes the spec of a published "
            "version. Nothing was exported."
        )
    document = _render(catalog, package_id, package_version, published_by)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(document, encoding="utf-8")
    return ExportedSpec(
        package_id=package_id, package_version=package_version, spec=str(dest),
        template_version=SPEC_TEMPLATE_VERSION,
        questions=len(catalog.questions(package_version)),
        criteria=len(catalog.criteria(package_version)),
        derivations=sum(
            1 for row in catalog.criteria(package_version)
            if row["score_method"] == "general"),
        bytes_written=dest.stat().st_size,
    )


# --- the reads -----------------------------------------------------------------------------------


def _bands(catalog: Any, version: str, criterion_id: str) -> list[dict]:
    """The criterion's bands in ordinal order. Reading `criteria(version)` first loads the
    per-run cache for `version`, which is what the version-less `bands()` reads from."""
    catalog.criteria(version)
    return [dict(band) for band in catalog.bands(criterion_id)]


# --- the emission --------------------------------------------------------------------------------


def _toml_str(value: str) -> str:
    """A TOML basic string. JSON's escapes (\\\", \\\\, \\n, \\uXXXX, ...) are TOML's, so the
    standard encoder produces a valid, faithful TOML string — including the teacher's prose
    in a derivation description, quotes and newlines intact."""
    return json.dumps(str(value), ensure_ascii=False)


def _toml_inline_table(entries: list[tuple[str, str]]) -> str:
    return "{" + ", ".join(f"{_toml_str(k)} = {_toml_str(v)}" for k, v in entries) + "}"


def _toml_key(key: str) -> str:
    """A table key, quoted — TOML quoted keys are always valid, whatever the label holds."""
    return _toml_str(key)


def _assign(key: str, value: Any) -> str:
    """A `key = value` line: a TOML number for a real number, a TOML array for a list, a
    basic string otherwise (booleans too: a spec field is never true/false)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, list, tuple)):
        return f"{key} = {_toml_str(value)}"
    return f"{key} = {json.dumps(value, ensure_ascii=False)}"


def _render(catalog: Any, package_id: str, version: str, published_by: str) -> str:
    lines: list[str] = [
        "# Package spec — SYSTEM-EMITTED by `aeh package export` (FR-PKG-27).",
        "# A teacher never authors this file: the console publishes the package directly from",
        "# the setup flow's confirmed state. `aeh package build --spec` accepts it unchanged;",
        "# it is kept as the debugging/export inverse of the build command.",
        "",
        _assign("package", package_id),
        _assign("approved_by", published_by),
    ]
    # Top-level keys stay above the first table header: after `[grades]` a bare assignment
    # would be parsed into that table.
    policy = catalog.grade_policy(version)
    if policy.review_window_hours is not None:
        lines.append(_assign("review_window_hours", policy.review_window_hours))
    for question in catalog.questions(version):
        lines += _question_block(catalog, version, question)
    graph = catalog.dependency_graph(version)
    for row in sorted(catalog.criteria(version), key=lambda r: r["criterion_id"]):
        lines += _criterion_block(catalog, version, row,
                                  graph.get(row["criterion_id"], ()))
    boundaries = catalog.boundaries(version)
    if boundaries:
        lines += ["", "[grades]"]
        lines += [f"{_toml_key(grade)} = {floor}" for grade, floor in boundaries]
    lines.append("")
    return "\n".join(lines)


def _question_block(catalog: Any, version: str, question: dict) -> list[str]:
    question_id = question["question_id"]
    lines = ["", "[[question]]", _assign("id", question_id),
             _assign("type", question["question_type"]),
             _assign("points", question["max_points"]),
             _assign("text", question["prompt_text"])]
    options = {o["option_id"]: o["label"]
               for o in catalog.question_options(version, question_id)}
    if options:
        lines.append("options = " + _toml_inline_table(list(options.items())))
    reference = question.get("reference_solution")
    if reference:
        lines.append(_assign("model_answer", reference))
    return lines


def _band_entry(bands: list[dict], band: dict) -> str:
    # The points go through `points_for_band`, M-PKG's one sanctioned reader of the band's
    # points (CT-PKG-05) — the export re-emits the stored value, it does not re-derive it.
    fields = [f"name = {_toml_str(band['band'])}",
              f"points = {points_for_band(bands, band['band'])}"]
    if band.get("descriptor"):
        fields.append(f"descriptor = {_toml_str(band['descriptor'])}")
    return "{ " + ", ".join(fields) + " }"


def _criterion_block(catalog: Any, version: str, row: dict,
                     dependencies: tuple[str, ...]) -> list[str]:
    criterion_id = row["criterion_id"]
    lines = ["", "[[criterion]]", _assign("id", criterion_id),
             _assign("question", row["question_id"])]
    if row["kind"] == "mcq":
        lines.append(_assign("points", row["max_points"]))
        lines.append(_assign("key", list(row["answer_key"])))
        return lines

    method = row["score_method"]
    if method != DEFAULT_SCORE_METHOD:
        lines.append(_assign("score_method", method))
    if method == "evidence_sum":
        # A composite carries no bands and no key: its aspects (their own blocks) carry the
        # band sets (FR-PKG-24).
        lines.append(_assign("points", row["max_points"]))
    else:
        bands = _bands(catalog, version, criterion_id)
        lines.append("bands = [" + ", ".join(_band_entry(bands, band) for band in bands) + "]")
    if method == "general":
        derivation = catalog.derivation(version, criterion_id)
        lines.append(_assign("derivation_description", derivation["description"]))
    # The declared scoring model comes from the package-side read-back: `CT-AGG-09` keeps
    # every scoring-model read in `aeh.pkg`, and the export only re-encodes what the build
    # would otherwise default.
    declared = catalog.declared_scoring(version, criterion_id)
    if declared and declared != JUDGED_SCORING:
        lines.append(_assign("scoring", declared))
    if row["evidence_type"] and row["evidence_type"] != DEFAULT_EVIDENCE_TYPE:
        lines.append(_assign("evidence_type", row["evidence_type"]))
    if row["component_of"]:
        lines.append(_assign("component_of", row["component_of"]))
    if row["construct_tag"]:
        lines.append(_assign("construct_tag", row["construct_tag"]))
    if row["band_justification"]:
        lines.append(_assign("band_justification", row["band_justification"]))
    if row["evaluation_mode"] != default_evaluation_mode(row["kind"]):
        lines.append(_assign("evaluation_mode", row["evaluation_mode"]))
    if dependencies:
        lines.append(_assign("depends_on", list(dependencies)))
    return lines
