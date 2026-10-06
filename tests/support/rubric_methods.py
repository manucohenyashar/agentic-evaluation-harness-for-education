"""`F-RUBRIC-METHODS` — one criterion per rubric method plus a 3-aspect composite (TS-144, #621).

Operator-requirements test plan §5.5 names this fixture for `TC-PKG-34..37`, `TC-PKG-C21`, and
the later `TC-JUDGE-45` / `TC-GRADE-27` cases. It is a builder, not a committed file: a real
Tier P store is written through `PackageCatalog`'s own API, the way `aeh package build` writes
one (proposal, then confirmed inventory, then criteria, then publish), so an export of it has
questions to carry.

**The interface this file assumes is written ahead of #622 and #627.** The design
(`operator_requirements_design_delta.md` §3.6) fixes the data model — `criterion.score_method`
in `{bands, evidence_sum, general}` and `criterion.component_of` — but names no Python surface.
Every assumed name lives in THIS file only, so if #622 lands a different shape, this is the one
place to change, and the test bodies (which assert on `PackageError`, `is_locked` and raw
`.pkg.sqlite` rows) stay as written:

* `PackageCatalog.add_criterion(..., score_method=..., component_of=...)` — two new keyword
  arguments beside `evaluation_mode`. Omitted → the column default (`bands`, `NULL`).
* `PackageCatalog.record_derivation(v, criterion_id, *, description, derived_bands,
  recorded_at)` — the system-derived band set for a `general` criterion, with the teacher's
  prose description (`FR-PKG-26`, `FR-SETUP-18`).
* `PackageCatalog.confirm_derivation(v, criterion_id, *, confirmed_by, confirmed_at)` — the
  teacher's confirmation that makes a `general` criterion publishable.
* `PackageCatalog.derivation(v, criterion_id) -> Mapping | None` — the stored provenance,
  carrying at least `description` and `derived_bands` (a sequence of mappings with `ordinal`,
  `band`, `points`, `descriptor`).

A refusal may come from the write that breaks the shape or from `publish` — `FR-PKG-24` says
"refused at publish", and the `evaluation_mode` precedent refuses at the write. `attempt_build`
treats both as the refusal, and the oracle is that the version never locked.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping

#: The closed vocabulary, as a literal. Never imported from `aeh.pkg`: an oracle read from the
#: implementation widens with it, and the property case exists to catch exactly that widening.
SCORE_METHODS: frozenset[str] = frozenset({"bands", "evidence_sum", "general"})

STAMP = "2026-10-05T00:00:00Z"
APPROVER = "rubric-methods-fixture"
SPEC_TEMPLATE = "aeh-package-spec/1"
EVIDENCE = "textual_span"

# The F-RUBRIC-METHODS criterion ids.
MCQ = "C-mcq"
BANDS = "C-bands"
GENERAL = "C-general"
COMPOSITE = "C-comp"
ASPECTS = ("C-comp-a1", "C-comp-a2", "C-comp-a3")
ASPECT_POINTS = (1.0, 2.0, 1.0)
STRAY = "C-stray"

GENERAL_DESCRIPTION = (
    "Full credit when the student names both forces and says they balance; partial credit "
    "when only one force is named; nothing when neither is."
)


@dataclass
class Band:
    ordinal: int
    band: str
    points: float
    descriptor: str = ""


@dataclass
class Criterion:
    """One rubric line as the builder writes it. `score_method=None` omits the argument."""

    criterion_id: str
    question_id: str
    kind: str = "open"
    score_method: str | None = None
    component_of: str | None = None
    bands: list[Band] = field(default_factory=list)
    max_points: float = 0.0
    depends_on: tuple[str, ...] = ()
    key: tuple[str, ...] = ()
    options: tuple[tuple[str, str], ...] = ()
    #: `general` only: record the derivation, and confirm it.
    derive: bool = False
    confirm: bool = False


@dataclass
class Question:
    question_id: str
    question_type: str
    prompt_text: str
    max_points: float
    options: tuple[tuple[str, str], ...] = ()


@dataclass
class PackageShape:
    package_id: str
    questions: list[Question]
    criteria: list[Criterion]
    grades: tuple[tuple[str, float], ...] = (("A", 8.0), ("B", 5.0), ("C", 2.0))


def two_bands(points: float, what: str) -> list[Band]:
    """An aspect's binary band set, worst first, numeral-free descriptors."""
    return [Band(0, "absent", 0.0, f"Does not show {what}."),
            Band(1, "present", float(points), f"Shows {what}.")]


def four_bands() -> list[Band]:
    return [Band(0, "none", 0.0, "No relevant reasoning."),
            Band(1, "limited", 1.0, "Names one relevant idea without linking it."),
            Band(2, "adequate", 2.0, "Links the ideas with a gap."),
            Band(3, "full", 3.0, "Links every idea correctly.")]


def general_bands() -> list[Band]:
    return [Band(0, "neither", 0.0, "Names neither force."),
            Band(1, "one", 1.0, "Names only one force."),
            Band(2, "both", 2.0, "Names both forces without saying they balance."),
            Band(3, "balanced", 3.0, "Names both forces and says they balance.")]


def rubric_methods(package_id: str = "RUBRIC-METHODS") -> PackageShape:
    """`F-RUBRIC-METHODS`: an MCQ line, one `bands`, one `general` (derivation confirmed) and one
    `evidence_sum` composite with three 2-band aspects. Valid: it publishes once #622 lands."""
    questions = [
        Question("Q1", "mcq", "Which unit measures force?", 1.0,
                 (("A", "joule"), ("B", "newton"), ("C", "watt"))),
        Question("Q2", "open", "Explain why the trolley accelerates.", 3.0),
        Question("Q3", "open", "Explain why the book does not accelerate.", 3.0),
        Question("Q4", "open", "Describe the experiment and its result.", sum(ASPECT_POINTS)),
    ]
    criteria = [
        Criterion(MCQ, "Q1", kind="mcq", max_points=1.0, key=("B",),
                  options=questions[0].options,
                  bands=[Band(0, "incorrect", 0.0), Band(1, "correct", 1.0)]),
        Criterion(BANDS, "Q2", score_method="bands", bands=four_bands(), max_points=3.0),
        Criterion(GENERAL, "Q3", score_method="general", bands=general_bands(),
                  max_points=3.0, depends_on=(BANDS,), derive=True, confirm=True),
        Criterion(COMPOSITE, "Q4", score_method="evidence_sum", max_points=sum(ASPECT_POINTS)),
    ]
    for aspect, points, what in zip(ASPECTS, ASPECT_POINTS,
                                    ("the method", "the measurement", "the conclusion")):
        criteria.append(Criterion(aspect, "Q4", component_of=COMPOSITE,
                                  bands=two_bands(points, what), max_points=points))
    return PackageShape(package_id, questions, criteria)


def with_criterion(shape: PackageShape, criterion_id: str, **changes: Any) -> PackageShape:
    """`shape` with one criterion changed — the one-defect-away mutations hang off this."""
    criteria = [replace(c, **changes) if c.criterion_id == criterion_id else c
                for c in shape.criteria]
    assert criteria != shape.criteria, f"no criterion {criterion_id!r} in the shape"
    return replace(shape, criteria=criteria)


def without_criteria(shape: PackageShape, *criterion_ids: str) -> PackageShape:
    kept = [c for c in shape.criteria if c.criterion_id not in criterion_ids]
    assert len(kept) == len(shape.criteria) - len(criterion_ids)
    return replace(shape, criteria=kept)


# --- writing a shape into a real store -------------------------------------------------------


def catalog_for(store: Any, package_id: str) -> Any:
    from aeh.pkg import PackageCatalog

    return PackageCatalog(store.package(package_id), package_id=package_id, blobs=store.blobs())


def write_draft(store: Any, shape: PackageShape) -> tuple[Any, str]:
    """Write `shape` into a fresh draft version, without publishing. Returns (catalog, version)."""
    catalog = catalog_for(store, shape.package_id)
    catalog.ensure_package()
    version = catalog.create_version(None)
    payload = json.dumps([{"question_id": q.question_id, "prompt_text": q.prompt_text,
                           "question_type": q.question_type} for q in shape.questions],
                         sort_keys=True)
    catalog.record_proposal(
        version, proposal_id=f"prop-{shape.package_id}", assessment_doc_id=f"doc-{shape.package_id}",
        payload=payload, template_version=SPEC_TEMPLATE, model_ref="fixture", attempts=1)
    catalog.write_confirmed_inventory(
        version, proposal_id=f"prop-{shape.package_id}",
        questions=[{"question_id": q.question_id, "ordinal": i, "prompt_text": q.prompt_text,
                    "question_type": q.question_type, "max_points": q.max_points,
                    "options": [{"option_id": o, "ordinal": j, "label": label}
                                for j, (o, label) in enumerate(q.options)]}
                   for i, q in enumerate(shape.questions)],
        confirmed_at=STAMP)
    for c in shape.criteria:
        _write_criterion(catalog, version, c)
    if shape.grades:
        catalog.set_boundaries(version, list(shape.grades))
    return catalog, version


def _write_criterion(catalog: Any, version: str, c: Criterion) -> None:
    kwargs: dict[str, Any] = {}
    if c.score_method is not None:
        kwargs["score_method"] = c.score_method
    if c.component_of is not None:
        kwargs["component_of"] = c.component_of
    judged = c.kind != "mcq"
    catalog.add_criterion(
        version, c.criterion_id, question_id=c.question_id, kind=c.kind,
        max_points=c.max_points,
        scoring_model="atomic" if not judged else "holistic",
        dependencies=c.depends_on,
        band_count=len(c.bands) if c.bands else None,
        evidence_type=EVIDENCE if judged and c.bands else None,
        **kwargs)
    for b in c.bands:
        catalog.add_band(version, c.criterion_id, b.ordinal, b.band, b.points, b.descriptor)
    if c.options:
        catalog.set_mcq_options(version, c.criterion_id, list(c.options))
    if c.key:
        catalog.set_answer_key(version, c.criterion_id, list(c.key))
    if c.derive:
        catalog.record_derivation(
            version, c.criterion_id, description=GENERAL_DESCRIPTION,
            derived_bands=[{"ordinal": b.ordinal, "band": b.band, "points": b.points,
                            "descriptor": b.descriptor} for b in c.bands],
            recorded_at=STAMP)
    if c.confirm:
        catalog.confirm_derivation(version, c.criterion_id, confirmed_by=APPROVER,
                                   confirmed_at=STAMP)


def derivation(catalog: Any, version: str, criterion_id: str) -> Mapping[str, Any] | None:
    """The stored `general` provenance (assumed surface: `PackageCatalog.derivation`)."""
    return catalog.derivation(version, criterion_id)


def band_tuples(bands: Any) -> list[tuple[int, str, float, str]]:
    """(ordinal, band, points, descriptor), ordered — for comparing band sets of any origin."""
    return sorted((int(b["ordinal"]), str(b["band"]), float(b["points"]),
                   str(b.get("descriptor") or "")) for b in bands)


def build(store: Any, shape: PackageShape) -> tuple[Any, str]:
    """Write `shape` and publish it. Raises whatever the catalog raises."""
    catalog, version = write_draft(store, shape)
    catalog.publish(version, approved_by=APPROVER)
    return catalog, version


@dataclass
class Refusal:
    error: Exception
    locked_versions: list[str]


def attempt_build(store: Any, shape: PackageShape) -> Refusal:
    """Build `shape`, expecting `M-PKG` to refuse it at the write or at publish.

    Fails the calling test (AssertionError) if the shape published. Catches `PackageError` only:
    a `TypeError` from an argument the catalog does not have yet — today's state — propagates,
    which is the honest red for a written-ahead case.
    """
    from aeh.pkg import PackageError

    try:
        build(store, shape)
    except PackageError as error:
        return Refusal(error, locked_versions(store.package_path(shape.package_id)))
    raise AssertionError(
        f"package {shape.package_id!r} published, but it is one defect away from the valid "
        "F-RUBRIC-METHODS shape and must have been refused at publish (FR-PKG-24, CT-PKG-21)")


# --- raw reads: what the store actually holds -------------------------------------------------


def _connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def columns(path: str | Path, table: str) -> dict[str, Any]:
    """Column name → (declared type, notnull, default) for `table`."""
    connection = _connect(path)
    try:
        return {row["name"]: (row["type"], row["notnull"], row["dflt_value"])
                for row in connection.execute(f"PRAGMA table_info({table})")}
    finally:
        connection.close()


def locked_versions(path: str | Path) -> list[str]:
    connection = _connect(path)
    try:
        return [row["package_version_id"] for row in connection.execute(
            "SELECT package_version_id FROM package_version WHERE locked = 1")]
    finally:
        connection.close()


def rows(path: str | Path, table: str, version: str) -> list[dict[str, Any]]:
    """Every row of `table` for `version`, whole, with `package_version_id` stripped."""
    connection = _connect(path)
    try:
        found = [dict(row) for row in connection.execute(
            f"SELECT * FROM {table} WHERE package_version_id = ?", (version,))]
    finally:
        connection.close()
    for row in found:
        row.pop("package_version_id", None)
    return found


def criteria_rows(path: str | Path, version: str) -> dict[str, dict[str, Any]]:
    return {row["criterion_id"]: row for row in rows(path, "criterion", version)}


def bands_by_criterion(path: str | Path, version: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows(path, "band", version), key=lambda r: (r["criterion_id"],
                                                                   r["ordinal"])):
        out.setdefault(row["criterion_id"], []).append(row)
    return out


def shape_violations(path: str | Path, version: str) -> list[str]:
    """`CT-PKG-21` over the stored rows of one published version. Empty means it holds.

    * every criterion's `score_method` is in the literal closed set;
    * an `evidence_sum` criterion has `component_of` NULL, no band, no answer key, and at least
      one aspect;
    * every criterion with `component_of` set names an `evidence_sum` criterion of the same
      version and carries exactly two bands;
    * every `bands` / `general` criterion that is not an aspect has `component_of` NULL and a
      band set (an MCQ line is a `bands` criterion with two bands and a key).
    """
    crit = criteria_rows(path, version)
    bands = bands_by_criterion(path, version)
    problems: list[str] = []
    for cid, row in crit.items():
        method = row.get("score_method")
        if method not in SCORE_METHODS:
            problems.append(f"{cid}: score_method {method!r} is outside {sorted(SCORE_METHODS)}")
        target = row.get("component_of")
        if method == "evidence_sum":
            if target is not None:
                problems.append(f"{cid}: a composite with component_of {target!r}")
            if bands.get(cid):
                problems.append(f"{cid}: a composite carrying {len(bands[cid])} band(s)")
            if row.get("answer_key") not in (None, "", "[]"):
                problems.append(f"{cid}: a composite carrying an answer key")
            aspects = [a for a, r in crit.items() if r.get("component_of") == cid]
            if not aspects:
                problems.append(f"{cid}: a composite with no aspect criteria")
        elif target is not None:
            # Reading taken (#621 PR): an aspect is a 2-band `bands` criterion; a `general`
            # criterion is standalone by definition (CT-PKG-21's `component_of = NULL` clause).
            if method == "general":
                problems.append(f"{cid}: a general criterion with component_of {target!r}")
            parent = crit.get(target)
            if parent is None or parent.get("score_method") != "evidence_sum":
                problems.append(f"{cid}: component_of {target!r} is not a composite")
            if len(bands.get(cid, [])) != 2:
                problems.append(f"{cid}: an aspect with {len(bands.get(cid, []))} band(s)")
        elif not bands.get(cid):
            problems.append(f"{cid}: a standalone {method!r} criterion with no band set")
    return problems


# --- the seeded generator for TC-PKG-C21 -----------------------------------------------------


def random_shape(seed: int) -> PackageShape:
    """A random VALID package: 1..3 `bands` lines (2, 4 or 6 bands), one `general` line with a
    confirmed derivation, and 1..2 composites of 1..4 two-band aspects each. Dependencies only
    point at earlier standalone lines, so the graph is acyclic. Deterministic in `seed`."""
    rng = random.Random(seed)
    questions: list[Question] = []
    criteria: list[Criterion] = []
    standalone: list[str] = []

    def question(points: float) -> str:
        qid = f"Q{len(questions) + 1}"
        questions.append(Question(qid, "open", f"Question {qid} of seed {seed}.", points))
        return qid

    def banded(count: int) -> list[Band]:
        return [Band(i, f"level-{chr(ord('a') + i)}", float(i), f"Level {chr(ord('a') + i)}.")
                for i in range(count)]

    for n in range(rng.randint(1, 3)):
        count = rng.choice((2, 4, 6))
        cid = f"C-b{n}"
        deps = tuple(d for d in standalone if rng.random() < 0.3)
        criteria.append(Criterion(cid, question(count - 1.0), score_method="bands",
                                  bands=banded(count), max_points=count - 1.0, depends_on=deps))
        standalone.append(cid)
    count = rng.choice((2, 4, 6))
    criteria.append(Criterion("C-g0", question(count - 1.0), score_method="general",
                              bands=banded(count), max_points=count - 1.0,
                              depends_on=tuple(d for d in standalone if rng.random() < 0.3),
                              derive=True, confirm=True))
    for n in range(rng.randint(1, 2)):
        points = [float(rng.randint(1, 3)) for _ in range(rng.randint(1, 4))]
        composite = f"C-e{n}"
        qid = question(sum(points))
        criteria.append(Criterion(composite, qid, score_method="evidence_sum",
                                  max_points=sum(points)))
        for i, p in enumerate(points):
            criteria.append(Criterion(f"{composite}-a{i}", qid, component_of=composite,
                                      bands=two_bands(p, f"aspect {i}"), max_points=p))
    return PackageShape(f"RM-PROP-{seed:02d}", questions, criteria, grades=())


def coverage(shape: PackageShape) -> dict[str, int]:
    """How many lines of each kind the generator produced — so the property cannot pass on a
    degenerate corpus."""
    return {
        "bands": sum(1 for c in shape.criteria if c.score_method == "bands"),
        "general": sum(1 for c in shape.criteria if c.score_method == "general"),
        "evidence_sum": sum(1 for c in shape.criteria if c.score_method == "evidence_sum"),
        "aspects": sum(1 for c in shape.criteria if c.component_of is not None),
    }


#: Method values a widened or sloppy domain would admit. Each must be refused.
NON_MEMBERS: tuple[str, ...] = (
    "weighted", "Bands", "BANDS", "evidence-sum", "checklist", "sum", "", "general_v2",
)


def random_non_member(seed: int) -> str:
    """A method value outside the closed set, deterministic in `seed`."""
    rng = random.Random(seed * 7919 + 1)
    while True:
        value = (rng.choice(NON_MEMBERS) if rng.random() < 0.5 else
                 "".join(rng.choice("abcdefghijklmnopqrstuvwxyz_")
                         for _ in range(rng.randint(3, 12))))
        if value not in SCORE_METHODS:
            return value


# --- the refusal matrix: each one defect away from the valid fixture --------------------------


@dataclass(frozen=True)
class Mutation:
    """One refusal case. `must_name` are substrings the refusal's message must carry (compared
    case-insensitively): the offending criterion and the violated shape (TC-PKG-35: "the reason
    naming the violated shape")."""

    case: str
    what: str
    apply: Callable[[PackageShape], PackageShape]
    must_name: tuple[str, ...]
    #: Whether the refusal must also name all three members of the closed set.
    names_closed_set: bool = False


def names_every_method(message: str) -> list[str]:
    """The closed-set members `message` fails to name, matched as whole words — so a
    criterion id like `C-bands` or an echoed `general_v2` does not count as naming one."""
    return [m for m in sorted(SCORE_METHODS)
            if not re.search(rf"(?<![\w-]){m}(?![\w-])", message)]


def missing_names(mutation: "Mutation", message: str) -> list[str]:
    missing = [t for t in mutation.must_name if t.lower() not in message.lower()]
    if mutation.names_closed_set:
        missing += names_every_method(message)
    return missing


def _three_band_aspect(shape: PackageShape) -> PackageShape:
    return with_criterion(shape, ASPECTS[1], bands=[
        Band(0, "absent", 0.0, "Does not show the measurement."),
        Band(1, "partial", 1.0, "Shows part of the measurement."),
        Band(2, "present", 2.0, "Shows the measurement.")])


MUTATIONS: tuple[Mutation, ...] = (
    Mutation("TC-PKG-34a", "score_method = 'weighted'",
             lambda s: with_criterion(s, BANDS, score_method="weighted"),
             (), names_closed_set=True),
    Mutation("TC-PKG-35b", "a composite carrying a band set",
             lambda s: with_criterion(s, COMPOSITE, bands=two_bands(sum(ASPECT_POINTS),
                                                                    "the experiment")),
             (COMPOSITE, "band")),
    Mutation("TC-PKG-35c", "a composite with zero aspects",
             lambda s: without_criteria(s, *ASPECTS),
             (COMPOSITE, "aspect")),
    # The plan's literal "3 bands" is odd, so FR-PKG-06's even-count rule refuses it today for
    # any criterion — a refusal that says nothing about aspects. Kept as the plan states it,
    # asserting only that it is refused; the 4-band arm below is the discriminating one (four
    # bands are legal on a standalone criterion, so only the 2-band aspect rule can refuse it).
    Mutation("TC-PKG-35d-3", "an aspect with 3 bands", _three_band_aspect, ()),
    Mutation("TC-PKG-35d-4", "an aspect with 4 bands",
             # Four bands topping out at the aspect's own 2 points, so the composite's sum of
             # aspect maxima (FR-PKG-25) still holds and only the 2-band rule is broken.
             lambda s: with_criterion(s, ASPECTS[1], bands=[
                 Band(0, "absent", 0.0, "Does not show the measurement."),
                 Band(1, "hint", 0.5, "Hints at the measurement."),
                 Band(2, "partial", 1.0, "Shows part of the measurement."),
                 Band(3, "present", 2.0, "Shows the measurement.")]),
             (ASPECTS[1], "aspect")),
    Mutation("TC-PKG-35e", "an aspect whose component_of names a non-composite",
             # An ADDED 2-band criterion pointing at `C-bands`, rather than moving an aspect:
             # moving one would also break the composite's sum of aspect maxima.
             lambda s: replace(s, criteria=[*s.criteria, Criterion(
                 STRAY, "Q2", component_of=BANDS, bands=two_bands(1.0, "a stray idea"),
                 max_points=1.0)]),
             (STRAY, BANDS)),
    Mutation("TC-PKG-35f", "a standalone (general) criterion with component_of set",
             # Two bands, so the 2-band aspect rule cannot be what refuses it: the only defect
             # is a `general` criterion pointing at a composite (CT-PKG-21: `bands` and
             # `general` criteria have component_of = NULL).
             lambda s: with_criterion(s, GENERAL, component_of=COMPOSITE,
                                      bands=two_bands(3.0, "both forces balancing")),
             # Only the criterion is required by name: CT-PKG-21 read literally ("`bands` and
             # `general` criteria have component_of = NULL") admits no aspect at all, so the
             # reading this arm takes — a `bands` criterion may be an aspect, a `general` one
             # may not — is recorded in the #621 PR rather than pinned in message wording.
             (GENERAL,)),
)
