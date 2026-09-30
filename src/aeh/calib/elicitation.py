"""The capped questions put to the teacher, and applying the answers as rubric clarifications."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .constants import (
    EDIT_ELIGIBLE_CATEGORY,
    EXAMPLES_PER_SIDE_BY_SIDE,
    _FIXTURE_CRITERION_ID,
    LOGGER,
)
from .errors import CalibrationError, PhaseDependencyError


# --- the elicitation cap (FR-CALIB-05, seam 3) ------------------------------------------------------
#
# "The teacher answers no more than CALIB_MAX_QUESTIONS questions" — NFR-CALIB-01's
# teacher-time budget expressed as an exact number, not a guideline. The cap is the
# knob (seam 3): teacher time is environment-shaped too, so the value is read at call
# time under `HARNESS_CALIB_MAX_QUESTIONS`, production value as the default, a mis-set
# or out-of-range value falling back rather than raising — a mis-set knob must not stop
# a calibration, and the run outcome discloses what actually applied.

CALIB_MAX_QUESTIONS: int = 6


CALIB_MAX_QUESTIONS_ENV: str = "HARNESS_CALIB_MAX_QUESTIONS"


def _max_questions(environ: Mapping[str, str] | None = None) -> int:
    """The cap on questions put to the teacher, read from its knob at call time. A value below 1
    would ask nothing and still call it calibration, so it falls back to the declared default like
    any other bad value."""
    source = os.environ if environ is None else environ
    raw = source.get(CALIB_MAX_QUESTIONS_ENV)
    if raw is None or not raw.strip():
        return CALIB_MAX_QUESTIONS
    try:
        value = int(raw)
    except ValueError:
        return CALIB_MAX_QUESTIONS
    return value if value >= 1 else CALIB_MAX_QUESTIONS


#: The declaration seam: version id -> the Tier P migration version the version was
#: created under. Deliberately declared, never inferred — nothing in a version's
#: content can recover when it was born, and an inference would silently claim the
#: lock's guarantee for versions created before the lock existed. Unregistered
#: versions read as created under the current schema.
_VERSION_SCHEMA_VINTAGES: dict[str, int] = {}


#: The migration that installed the lock's columns on package_version (aeh.pkg's third
#: migration). A version born under an earlier migration predates the lock.
_LOCK_ARRIVAL_MIGRATION = 3


#: A vintage from before the first content-bearing migration, used for the pre-lock
#: declaration below — the earliest schema a real package file could have been built on.
_PRE_LOCK_VINTAGE = 1


_FIXTURE_PRE_LOCK_VERSION = "pkg-v1-pre-lock"


def package_version_predating_schema_lock() -> str:
    """Test seam: declare and return a package version created before the schema lock existed.

    This is the seam a caller or test uses to name such a version — the registry above
    is deliberately not a thing the module populates from the store, because vintage is
    a fact about a file's history that no content can recover. `apply_answers` refuses
    a declared pre-lock version with `PhaseDependencyError` (`CT-CALIB-15`)."""
    _VERSION_SCHEMA_VINTAGES[_FIXTURE_PRE_LOCK_VERSION] = _PRE_LOCK_VINTAGE
    LOGGER.info("declared pre-lock vintage %d for package version %r",
                _PRE_LOCK_VINTAGE, _FIXTURE_PRE_LOCK_VERSION)
    return _FIXTURE_PRE_LOCK_VERSION


def _refuse_pre_lock_vintage(version_id: str) -> None:
    """Refuse an edit to a version created before the schema lock existed."""
    vintage = _VERSION_SCHEMA_VINTAGES.get(version_id, _LOCK_ARRIVAL_MIGRATION)
    if vintage < _LOCK_ARRIVAL_MIGRATION:
        raise PhaseDependencyError(
            f"package version {version_id!r} was created under Tier P schema migration "
            f"{vintage}, which predates the §6.2 schema lock (installed by migration "
            f"{_LOCK_ARRIVAL_MIGRATION}): the guarantee that every edit routes through "
            "M-PKG's guard does not hold for it, so no calibration edit is applied "
            "against it (CT-CALIB-15). The version needs re-importing under the current "
            "schema before it can be clarified."
        )


# --- elicitation: a question with options, never a pre-authored edit (CT-CALIB-05) ------------------
#
# "Elicitation presents OPTIONS, never a pre-authored rubric edit — the teacher's ANSWER
# generates the edit." The two halves of that sentence are both structural here: the
# question value carries options and carries no edit field at all (not an edit field
# that happens to be None — the attribute does not exist), and the edit is generated
# from the answer at application time, deterministically, through M-PKG.

#: The options an elicitation question offers. A prompt to a person, not an API
#: contract: the teacher may also answer in their own words, and `apply_answers`
#: composes the edit from the band's current descriptor and the answer — with
#: *keep as is* generating no edit at all (see `docs/code-notes/calib.md`).
QUESTION_OPTIONS: tuple[str, ...] = ("broaden", "narrow", "keep as is")


@dataclass(frozen=True)
class Finding:
    """One ambiguity the teacher would be asked about: its criterion, its triage category
    (required, CT-CALIB-04), how many submissions it affects (used for ranking, FR-CALIB-05), the
    two examples shown side by side, and which band's descriptor is ambiguous, so clarifying one
    band never silently changes another."""

    criterion_id: str
    category: str
    submissions_affected: int
    examples: tuple[str | None, ...] = ()
    band_ordinal: int = 0


@dataclass(frozen=True)
class ElicitationQuestion:
    """One question put to the teacher: options and exactly two examples (NFR-CALIB-01). It has no
    edit field at all (CT-CALIB-05); an edit only comes into being when the teacher's answer is
    applied."""

    question_id: str
    criterion_id: str
    question: str
    options: tuple[str, ...]
    examples: tuple[str | None, ...]
    submissions_affected: int
    band_ordinal: int = 0


#: The session of questions the most recent `elicit` call asked, so `apply_answers`
#: can resolve an answer's question id back to its criterion and its wording. A module
#: global because elicitation and application are two calls a teacher makes minutes
#: apart, not two arguments of one call; the resolution rule is stated on
#: `_resolve_criterion`.
_ACTIVE_QUESTIONS: list[ElicitationQuestion] = []


def elicit(
    findings: Sequence[Finding], *, environ: Mapping[str, str] | None = None
) -> tuple[ElicitationQuestion, ...]:
    """Turn edit-eligible findings into at most `CALIB_MAX_QUESTIONS` questions.

    Ranked by how many submissions the ambiguity affects (`FR-CALIB-05`), ties broken
    by criterion id for determinism, and capped at the env-read knob — together the cap
    and the ranking decide which ambiguities the teacher never sees, which is why the
    cap is asserted exactly in the contract suite (`CT-CALIB-05`).

    Each question carries `QUESTION_OPTIONS` and exactly two examples (NFR-CALIB-01's
    side-by-side pair) — and no edit, on any path (`CT-CALIB-05`). The questions asked
    become the session `apply_answers` resolves answers against.
    """
    eligible = [f for f in findings if f.category == EDIT_ELIGIBLE_CATEGORY]
    ranked = sorted(eligible, key=lambda f: (-f.submissions_affected, f.criterion_id))
    cap = _max_questions(environ)
    questions = []
    for position, finding in enumerate(ranked[:cap], start=1):
        examples = tuple(finding.examples)[:EXAMPLES_PER_SIDE_BY_SIDE]
        examples = examples + (None,) * (EXAMPLES_PER_SIDE_BY_SIDE - len(examples))
        questions.append(
            ElicitationQuestion(
                question_id=f"q{position}",
                criterion_id=finding.criterion_id,
                question=(
                    f"criterion {finding.criterion_id} reads ambiguously to "
                    f"{finding.submissions_affected} submissions: should its descriptor "
                    "be broadened, narrowed, or kept as is?"
                ),
                options=QUESTION_OPTIONS,
                examples=examples,
                submissions_affected=finding.submissions_affected,
                band_ordinal=finding.band_ordinal,
            )
        )
    global _ACTIVE_QUESTIONS
    _ACTIVE_QUESTIONS = questions
    LOGGER.info(
        "elicitation asked %d of %d eligible findings (cap=%d, env=%s)",
        len(questions), len(eligible), cap,
        os.environ.get(CALIB_MAX_QUESTIONS_ENV, "<unset>") if environ is None
        else environ.get(CALIB_MAX_QUESTIONS_ENV, "<unset>"),
    )
    return tuple(questions)


# --- the lock write-path: every edit through M-PKG, no second check (FR-CALIB-07) -------------------
#
# CT-CALIB-06 makes the lock structural by ROUTING: this module has no copy of the
# forbidden-field list and no guard of its own — a second implementation of one rule is
# what drifts (RISK-06). The refused-edit door below exists so the sweep can drive each
# locked field through the catalog and watch the catalog's own guard raise.

#: The §6.2 field names an edit can touch, in the HLD's vocabulary — the same names the
#: contract sweep parametrizes over. These are message/route names, never a gate: the
#: gate is the catalog's `_guard` (`NFR-PKG-03`), reached through the routing map below.
LOCKED_FIELD_NAMES: tuple[str, ...] = (
    "max_points",
    "criterion_count",
    "question_type",
    "scoring_model",
    "construct_tag",
    "criterion_band",
    "criterion_dependency",
)


@dataclass(frozen=True)
class LockedFieldEdit:
    """An edit to one field frozen by the schema lock; the input to the forced-edit test.

    The door exists to demonstrate refusal, not to permit: every field in the
    vocabulary is locked, so every door call raises `SchemaLockViolation` raised by the
    catalog's guard (`raised_by == "catalog"`, `CT-CALIB-06`)."""

    locked_field: str
    criterion_id: str
    description: str


def edit_touching(locked_field: str) -> LockedFieldEdit:
    """Build the edit that would change one locked field, for the refusal test.

    `criterion_count` is the one door whose target is not an existing criterion —
    adding one needs an id nothing is using yet; the rest address the criterion the
    test package carries (`_FIXTURE_CRITERION_ID`)."""
    if locked_field not in LOCKED_FIELD_NAMES:
        raise CalibrationError(
            f"unknown locked field {locked_field!r}; the §6.2 vocabulary is "
            f"{LOCKED_FIELD_NAMES}."
        )
    criterion_id = (
        "CRIT-CALIB-NEW" if locked_field == "criterion_count" else _FIXTURE_CRITERION_ID
    )
    return LockedFieldEdit(
        locked_field=locked_field,
        criterion_id=criterion_id,
        description=f"an edit altering the {locked_field} of the published rubric",
    )


def _route_forced_edit(catalog: Any, base: str, edit: LockedFieldEdit) -> None:
    """Send a forced edit through the catalog method whose guard covers its field.

    One route per vocabulary name, all on the PUBLISHED base — so the catalog's own
    `_guard` raises, which is the entire point: this module performs no lock check of
    its own (`CT-CALIB-06`), it merely offers the edit to the one implementation."""
    field = edit.locked_field
    criterion = edit.criterion_id
    if field == "max_points":
        catalog.update_criterion_field(base, criterion, "max_points", 5.0)
    elif field == "criterion_count":
        catalog.add_criterion(base, criterion)
    elif field == "question_type":
        catalog.update_criterion_field(base, criterion, "question_type", "mcq")
    elif field == "scoring_model":
        catalog.update_criterion_field(base, criterion, "scoring_model", "atomic")
    elif field == "construct_tag":
        catalog.update_criterion_field(base, criterion, "construct_tag", "clarity")
    elif field == "criterion_band":
        catalog.update_band_field(base, criterion, 0, "label", "Clarified")
    elif field == "criterion_dependency":
        catalog.update_criterion_dependency(base)
    else:  # unreachable: `edit_touching` validates against the same tuple
        raise CalibrationError(f"no catalog door routes a {field!r} edit.")


def _clarified_descriptor(
    current_descriptor: str, answer: str
) -> str | None:
    """The band descriptor the teacher's answer produces, or None when it produces none. The
    answer, never the model, creates the edit (CT-CALIB-05).

    Composition, not replacement: the band's descriptor as it stands is the base of
    every result, because a revision that erased what the band means would be the
    edit destroying the very thing it claims to clarify — and the NEXT calibration
    would chain on the erased text. The answer's first word reads as an intent and
    the directional clause is appended to the current text; anything else is the
    teacher's own clarification, appended verbatim; *keep as is* (or an empty
    answer) is `None` — no edit exists to generate, and the confirmation belongs
    in the history row, which the caller writes either way. There is no closed
    answer schema to reject against — the question's options are a prompt to a
    person, and refusing a teacher's own words would send them back to the interface
    for no safety gain: the edit still goes through the catalog's guard."""
    base = current_descriptor.strip() or "the band's descriptor"
    stripped = answer.strip()
    first = stripped.lower().split(" ", 1)[0] if stripped else ""
    if first == "keep" or not stripped:
        return None
    if first == "broaden":
        return (f"{base}; broadened to also cover responses that only partially "
                "meet the criterion")
    if first == "narrow":
        return f"{base}; narrowed to responses that fully meet the criterion"
    return f"{base}; {stripped}"


#: The session question ids are `q1..qn`; the number picks the criterion positionally
#: when the session and the version disagree (see `docs/code-notes/calib.md`).
_QUESTION_ID_PATTERN = re.compile(r"q(\d+)")


def _resolve_criterion(
    question_id: str, criterion_ids: Sequence[str], base: str
) -> tuple[str, str, int]:
    """Find the criterion an answer's question id refers to in the version being edited, with the
    question text the history will record and the band ordinal to clarify.

    The session's own mapping wins only when its criterion still exists in the version
    being edited — discovery and elicitation can run against different revisions of the
    same rubric without the ambiguity having moved. Otherwise the question id's position
    picks the criterion from the version's own ordering (the order the catalog reports
    the version's criteria in), and the recorded question is the generic form naming
    THAT criterion — never a session wording that names a criterion the edit does not
    touch, which is the row that would lie about what happened. The fallback band is
    ordinal 0: a positional resolution carries no band information of its own."""
    session = {question.question_id: question for question in _ACTIVE_QUESTIONS}
    asked = session.get(question_id)
    if asked is not None and asked.criterion_id in criterion_ids:
        return asked.criterion_id, asked.question, asked.band_ordinal
    match = _QUESTION_ID_PATTERN.fullmatch(question_id)
    if match is not None:
        position = int(match.group(1))
        if 1 <= position <= len(criterion_ids):
            criterion_id = criterion_ids[position - 1]
            question_text = (
                f"should the descriptor of criterion {criterion_id} be broadened, "
                "narrowed, or kept as is?"
            )
            return criterion_id, question_text, 0
    raise CalibrationError(
        f"the answer {question_id!r} matches no criterion of package version {base!r} "
        f"(its criteria are {list(criterion_ids)}). Answers are keyed by the elicitation "
        "session's question ids (q1..qn), resolved against the version being edited."
    )


def apply_answers(
    answers: Mapping[str, str],
    *,
    catalog: Any | None = None,
    package_version: str | None = None,
    forced_edit: LockedFieldEdit | None = None,
) -> str | None:
    """Apply the teacher's answers as rubric clarifications, written through M-PKG.

    Every edit follows the catalog's own revision flow (`FR-PKG-04`): a new version is
    created as a copy of the one being clarified, the descriptor edit lands on the
    unlocked copy, and the conversation that produced it is appended to the elicitation
    history on the published base (`FR-CALIB-13`/`-14`). Nothing here writes a locked
    field, and nothing here writes anywhere but through the catalog — `M-CALIB` has no
    second check of its own (`FR-CALIB-07`, `CT-CALIB-06`).

    Three doors:

    * the ordinary one — `answers` keyed by elicitation question id, applied against
      `package_version` or the catalog's latest version; one new version per EDIT (a
      *keep as is* answer generates no edit: no version is minted and its history row
      records an empty `resulting_edit`), each copy parented on the previous, so the
      history's `resulting_edit` names the version its answer produced. Returns the
      last version an edit landed on, or `None` when every answer kept the rubric
      as is — no edit exists to return;
    * the forced-edit door — `forced_edit` routes one locked-field edit through the
      catalog on the published base, which refuses it with `SchemaLockViolation` (the
      sweep's vehicle; nothing lands, nothing is appended, `None` returns);
    * the refusal that precedes both — an edit against a declared pre-lock vintage
      raises `PhaseDependencyError` (`CT-CALIB-15`).
    """
    if not isinstance(answers, Mapping) or not answers:
        raise CalibrationError(
            "apply_answers requires at least one answer keyed by an elicitation "
            f"question id; got {type(answers).__name__}."
        )
    if package_version is not None:
        _refuse_pre_lock_vintage(package_version)
    if forced_edit is not None:
        if catalog is None:
            raise CalibrationError(
                "a forced edit needs the catalog it is routed through: pass the same "
                "catalog the real edit would take (CT-CALIB-06)."
            )
        base = package_version if package_version is not None else catalog.latest_version()
        if base is None:
            raise CalibrationError("the package carries no version for the edit to touch.")
        _refuse_pre_lock_vintage(base)
        _route_forced_edit(catalog, base, forced_edit)
        return None
    if package_version is None:
        if catalog is None:
            raise CalibrationError(
                "apply_answers needs the catalog the edit is written through "
                "(FR-CALIB-07), or an explicit package_version to clarify."
            )
        base = catalog.latest_version()
    else:
        base = package_version
    if base is None:
        raise CalibrationError("the package carries no version to calibrate against.")
    _refuse_pre_lock_vintage(base)
    rows = catalog.criteria(base)
    # The version's OWN ordering, not an alphabetical rewrite of it: the positional
    # fallback resolves qN against the order the catalog reports, so the docstring's
    # claim and the resolution agree.
    criterion_ids = list(dict.fromkeys(row["criterion_id"] for row in rows))
    if not criterion_ids:
        raise CalibrationError(
            f"package version {base!r} carries no criteria to clarify."
        )
    current = base
    for question_id, answer in sorted(answers.items()):
        criterion_id, question_text, band_ordinal = _resolve_criterion(
            question_id, criterion_ids, base
        )
        # Probe the answer's intent BEFORE minting anything: the keep/empty rule
        # lives in `_clarified_descriptor` alone, and a probe against a placeholder
        # base answers "does this answer generate an edit at all" without one.
        if _clarified_descriptor("", answer) is None:
            # *Keep as is*: no edit exists to generate. Nothing lands on the rubric,
            # no version is minted, and the confirmation lives in the history row.
            catalog.append_elicitation(
                base, question_text, list(QUESTION_OPTIONS), answer, resulting_edit="",
            )
            LOGGER.info(
                "calibration answer kept the rubric as is: criterion %s (question %s), "
                "no edit",
                criterion_id, question_id,
            )
            continue
        current = catalog.create_version(current)
        # Read the descriptor being clarified off the freshly minted copy: the copy
        # carries the base's bands verbatim (the revision flow's verbatim copy) and is
        # now the file's latest version, which is the one `bands()` reads — so the
        # composition composes against the text being edited, whatever version that is.
        bands = catalog.bands(criterion_id)
        band_row = next(
            (row for row in bands if row.get("ordinal") == band_ordinal), None
        )
        if band_row is None and 0 <= band_ordinal < len(bands):
            band_row = bands[band_ordinal]
        current_descriptor = (band_row or {}).get("descriptor", "") or ""
        clarified = _clarified_descriptor(current_descriptor, answer)
        if clarified is None:  # unreachable: the probe above proved the answer edits
            raise CalibrationError(
                f"the answer for {question_id!r} generated no edit on the second "
                "resolution — an internal inconsistency in answer handling."
            )
        catalog.update_band_field(current, criterion_id, band_ordinal, "descriptor",
                                  clarified)
        catalog.append_elicitation(
            base, question_text, list(QUESTION_OPTIONS), answer, resulting_edit=current,
        )
        LOGGER.info(
            "calibration edit landed: version %s clarifies criterion %s band %d "
            "(question %s)",
            current, criterion_id, band_ordinal, question_id,
        )
    return None if current is base else current
