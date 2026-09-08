"""M-SETUP — Stage A: the question inventory proposal, the two blocking gates, and
publication (#50; design §3.6, FR-SETUP-01/-02/-16, NFR-SETUP-04).

Stage A runs ONCE per package version (`CT-SETUP-16`): the assessment document the
teacher ingested through `M-INGEST` is read (never re-ingested — `CT-SETUP-11`: setup
reads documents through `M-INGEST`'s store, not around it), a model proposes the
question inventory through `M-PROV`'s seam (`FR-PROV-13` names this module a prompt
builder; `HLD §7.8` Phase 1 is the proposal logic), the teacher confirms or corrects
it, and the confirmed question rows are written through `M-PKG` (`FR-PKG-03`) — where
the §6.2 lock engages at the confirmation (`FR-SETUP-02`), deliberately earlier than
publication. The confirmation IS the teacher's assertion about content; a lock that
engaged only at publish would leave a window where the instrument could drift after
the teacher signed it.

**The two blocking steps** (`CT-SETUP-01`, §4.2.1, `FR-CONSOLE-06`): exactly two setup
operations block — confirming the question inventory (S3) and setting the answer keys
(S4). `publish()` enforces both gates and is refused until they hold; publication is
the moment `M-PKG`'s version lock flips, which is the §6.2 lock taking effect
(`FR-SETUP-02`). Everything else in the design's setup sequence is skippable with a
recorded default, and the steps this story does not stage yet are enumerated by
`steps()` as present-and-unavailable, naming the story that stages them — the console
tells the teacher the truth about what remains (`NFR-SETUP-04`, `FR-CONSOLE-25`):

- rubric read-back: #51 (its `reference_solution` column already exists and is the one
  field the confirmation lock leaves writable),
- decomposability and dependencies: #52,
- grade policy, grade boundaries and the prefix budget: #53 — which also stages S4's
  full `FR-SETUP-03` validation semantics. Here `set_answer_keys` is the thin,
  blocking write-through to `PackageCatalog.set_answer_key`, and publish's second gate
  reads the same structural fact it will enforce: every deterministic criterion keyed.

**State is the database, never memory** (`CT-SETUP-03`): a process that dies after the
proposal resumes by constructing a fresh `SetupService` over the same Tier P file and
calling `propose_inventory` again — the stored proposal comes back unchanged, and
`steps()` reports what remains. Nothing here holds in-memory state across calls.

The four seams, from the first commit:

1. **Headless driver** — `SetupService` runs the whole stage from code: structured
   results (`InventoryProposal`, `SetupProgress` with a per-step list), no console
   required (`CT-CONSOLE-01`).
2. **Deterministic transport** — every model call goes through the `InferenceProvider`
   seam (`CT-PROV-01`); tests script a double, production passes a real provider, and
   no other egress exists (`CT-PROV-15`).
3. **Env-gated knobs** — `HARNESS_SETUP_PROPOSAL_ATTEMPTS` (the degraded-path attempt
   budget, read at CALL time per this codebase's knob doctrine).
4. **Stage-level observability** — `LOGGER` ("aeh.setup") logs every proposal attempt,
   confirmation, gate refusal and publication; the proposal row carries its attempt
   count and status, so a degraded proposal is visible in the database, not just the
   log.

Coverage note: the `TC-SETUP-*` cases (test plan §5.6) land with issue #54, the
co-evolution test story paired with this one.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from aeh.ingest import DocumentId
from aeh.pkg import (
    PackageCatalog,
    PackageDraft,
    PackageVersionId,
    QUESTION_TYPES,
)
from aeh.prov import InferenceProvider, ModelRef, PromptPayload, SamplingParams

__all__ = [
    "InventoryProposal",
    "PROPOSAL_ATTEMPTS_DEFAULT",
    "PROPOSAL_ATTEMPTS_ENV",
    "ProposedOption",
    "ProposedQuestion",
    "QuestionCorrection",
    "SETUP_PROMPT_TEMPLATE_V",
    "SetupError",
    "SetupOrderError",
    "SetupProgress",
    "SetupService",
    "SetupStep",
]

#: Module observability: every proposal attempt, confirmation, gate refusal and
#: publication is logged with its identifiers (the four seams' stage-level trace).
LOGGER = logging.getLogger("aeh.setup")

#: The version-pinned inventory prompt (`CT-SETUP-14`, `TC-SETUP-22`): changing the
#: wording changes what the model was asked, so the text carries a version and the
#: proposal row records which one produced it. A prompt change is a NEW version string
#: and a new proposal — never an in-place edit of this constant's meaning.
SETUP_PROMPT_TEMPLATE_V = "setup-inventory-v1"

#: The degraded-path attempt budget (`CT-SETUP-12`): a model proposal that fails to
#: parse or validate is re-requested up to this many times, then the proposal is
#: recorded as `needs_manual_entry` — degraded but complete: the teacher enters the
#: questions as corrections and confirms. Env-gated so a slow test box can shrink it.
PROPOSAL_ATTEMPTS_ENV = "HARNESS_SETUP_PROPOSAL_ATTEMPTS"
PROPOSAL_ATTEMPTS_DEFAULT = 3


def _configured_proposal_attempts() -> int:
    """The attempt budget, read at call time — never at import (`M-PKG`'s knob
    doctrine: a test or deployment sets it per operation, not per process load)."""
    raw = os.environ.get(PROPOSAL_ATTEMPTS_ENV)
    if not raw:
        return PROPOSAL_ATTEMPTS_DEFAULT
    try:
        value = int(raw)
    except ValueError as error:
        raise SetupError(
            f"{PROPOSAL_ATTEMPTS_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise SetupError(
            f"{PROPOSAL_ATTEMPTS_ENV}={value} is below 1: at least one proposal "
            "attempt is required."
        )
    return value


class SetupError(Exception):
    """Base for every `M-SETUP` failure — the taxonomy is siblings, never a chain.

    Storage-layer errors (`M-PKG`'s) are deliberately NOT wrapped: they propagate
    unchanged (`CT-SETUP-12`), because a caller branching on a data-layer refusal
    needs the data-layer type, and re-raising it under a setup name would break that
    branch."""

    retryable = False


class SetupOrderError(SetupError):
    """A setup operation ran out of order, or a blocking gate was not yet satisfied
    (`§4.2.1`'s sequence): confirming before proposing, proposing after confirming,
    publishing before both blocking gates hold. The refusal names the gate and the
    step that unblocks it — the console renders this verbatim."""

    retryable = False


@dataclass(frozen=True)
class ProposedOption:
    """One option of a proposed `mcq`/`mixed` question, exactly as proposed.

    No correctness field — ADR-1's rule travels with the option set: correctness is
    the answer key, a separate blocking step (`FR-PKG-17`, S4)."""

    option_id: str
    ordinal: int
    label: str


@dataclass(frozen=True)
class ProposedQuestion:
    """One proposed question, exactly as the model proposed it (`FR-SETUP-01`): the
    prompt text verbatim, a `question_type` from `aeh.pkg.QUESTION_TYPES`, and the
    option set for any `mcq`/`mixed` question. The teacher confirms or corrects
    THIS — never a paraphrase."""

    question_id: str
    ordinal: int
    prompt_text: str
    question_type: str
    max_points: float
    options: tuple[ProposedOption, ...]


@dataclass(frozen=True)
class QuestionCorrection:
    """One teacher correction, applied at confirmation time.

    Actions: `set` patches fields of a proposed question; `remove` drops it;
    `add` contributes a question the model missed (and is the manual-entry vehicle
    that completes the degraded path, `CT-SETUP-12`: an `add` correction must carry
    `question_type` and `prompt_text`). Corrections apply BEFORE the write — after
    confirmation the inventory is locked (`FR-SETUP-02`) and this module offers no
    edit at all."""

    question_id: str
    action: str = "set"
    question_type: str | None = None
    prompt_text: str | None = None
    ordinal: int | None = None
    max_points: float | None = None
    options: tuple[ProposedOption, ...] | None = None


@dataclass(frozen=True)
class InventoryProposal:
    """The proposal a version holds, as rebuilt from its stored row.

    `status` is the payload's own word for how it got here: `proposed` (awaiting the
    teacher) or `needs_manual_entry` (the degraded path: the model's replies never
    parsed, the questions are empty, the teacher enters them as `add` corrections —
    degraded but complete, `CT-SETUP-12`). It never becomes "confirmed" — confirmation
    is not a payload word but the row's `confirmed_at` column, and this object's
    `confirmed` flag is the signal for it (the payload is frozen at confirm time; the
    column is what the §6.2 lock keys on). `attempts` is how many model calls
    the stored proposal cost, `model_ref` the build that actually answered
    (`FR-PROV-04`), `template_version` the pinned prompt that asked (`TC-SETUP-22`)."""

    proposal_id: str
    assessment_doc_id: DocumentId
    package_version_id: PackageVersionId
    template_version: str
    model_ref: str
    attempts: int
    questions: tuple[ProposedQuestion, ...]
    status: str
    confirmed_at: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.confirmed_at is not None

    def entry(self, question_id: str) -> ProposedQuestion | None:
        for question in self.questions:
            if question.question_id == question_id:
                return question
        return None


@dataclass(frozen=True)
class SetupStep:
    """One setup step as the console renders it (`NFR-SETUP-04`, `FR-CONSOLE-25`).

    A step that is not `available` yet is present-and-unavailable: the list names it
    and its staging story, so the teacher sees the whole sequence without being
    offered an operation that does not exist. `publish` is not a step — it is the
    gate point the blocking steps hold shut."""

    step_id: str
    name: str
    blocking: bool
    available: bool
    done: bool
    note: str = ""


@dataclass(frozen=True)
class SetupProgress:
    """The setup state of one package version, structured for the console and the
    headless driver: the enumerated steps, the honest remaining count (steps that are
    available and not done), and whether `publish`'s two gates would pass right now."""

    package_version_id: PackageVersionId | None
    steps: tuple[SetupStep, ...]
    remaining_steps: int
    ready_to_publish: bool

    def headline(self) -> str:
        """The console's one-line state (`NFR-SETUP-04`): `setup incomplete — N steps
        remain`, the ready line, or — with no draft version — the finished/not-started
        line. A zero that is NOT a lie reads `ready`, because a count of remaining
        steps that no one can act on is the console lying."""
        if self.ready_to_publish:
            return f"setup complete for {self.package_version_id!r} — ready to publish"
        if self.package_version_id is None and self.remaining_steps == 0:
            return ("setup has finished for this package (its version is published); "
                    "a new instrument is a new package or a revision (FR-PKG-02)")
        if self.package_version_id is None:
            return ("setup has not started — no draft version exists yet; "
                    f"{self.remaining_steps} step(s) remain (the question inventory)")
        return (
            f"setup incomplete — {self.remaining_steps} step(s) remain for "
            f"{self.package_version_id!r}"
        )


_INVENTORY_INSTRUCTION = (
    "You are reading one assessment document and proposing the question inventory a "
    "grading package will be built from (HLD §7.8, Phase 1 — propose once, from the "
    "document alone). For every question the document asks:\n"
    "- question_type is 'mcq' when the question enumerates options or answer markers "
    "(lettered options, checkboxes, a 'circle one' instruction); 'open' when it names "
    "a ruled response area with nothing to mark; 'mixed' when one question carries "
    "both a marked part and a written part.\n"
    "- For every mcq or mixed question include the full option set exactly as "
    "printed, one entry per option, with the option's printed id and label.\n"
    "- Copy prompt_text verbatim from the document; set ordinal to the question's "
    "printed number and max_points to its printed marks (0 when the document shows "
    "none).\n"
    "- Propose only what the document contains: no invented questions, no merged or "
    "split questions, and no answer key — the teacher declares keys in a separate "
    "blocking step.\n"
    "Reply with ONLY a JSON object, no prose, of this shape — note an open question "
    "carries an EMPTY options list, and only mcq/mixed carry entries in it:\n"
    '{"questions": [{"question_id": "Q1", "ordinal": 1, "prompt_text": "...", '
    '"question_type": "open", "max_points": 4, "options": []}, '
    '{"question_id": "Q2", "ordinal": 2, "prompt_text": "...", '
    '"question_type": "mcq", "max_points": 2, "options": [{"option_id": "A", '
    '"ordinal": 0, "label": "..."}]}]}'
)


def _now() -> str:
    """The confirmation stamp. UTC ISO — the same shape the store's
    `datetime('now')` stamps carry (which are UTC), so one column sorts cleanly."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _ReplyError(Exception):
    """A model reply that did not parse into a valid proposal. PRIVATE on purpose:
    it is the retried failure (`CT-SETUP-12`), never surfaced — the caller sees the
    re-request, or the degraded proposal with the last error recorded in it."""


def _parse_reply(text: str) -> tuple[ProposedQuestion, ...]:
    """Parse the model's reply into proposed questions, raising `_ReplyError` on
    anything that is not a valid inventory — the failure the attempt loop re-requests.
    The reply is expected to be one JSON object; prose around it is tolerated (models
    add it), JSON-shaped text that is not an inventory is not."""
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise _ReplyError("the reply contains no JSON object.")
    try:
        parsed = json.loads(stripped[start:end + 1])
    except ValueError as error:
        raise _ReplyError(f"the reply is not valid JSON: {error}") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("questions"), list):
        raise _ReplyError("the reply's JSON does not carry a 'questions' list.")
    if not parsed["questions"]:
        raise _ReplyError(
            "the reply proposes zero questions — the document asks something; an "
            "empty inventory is not a proposal."
        )
    questions: list[ProposedQuestion] = []
    seen_ids: set[str] = set()
    seen_ordinals: set[int] = set()
    for index, raw in enumerate(parsed["questions"]):
        if not isinstance(raw, dict):
            raise _ReplyError(f"question #{index} is not an object.")
        question_id = raw.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise _ReplyError(f"question #{index}: question_id must be a non-empty string.")
        if question_id in seen_ids:
            raise _ReplyError(f"question #{index}: duplicate question_id {question_id!r}.")
        seen_ids.add(question_id)
        ordinal = raw.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise _ReplyError(
                f"question {question_id!r}: ordinal must be a non-negative integer, "
                f"got {ordinal!r}."
            )
        if ordinal in seen_ordinals:
            raise _ReplyError(
                f"question {question_id!r}: duplicate ordinal {ordinal} — two "
                "questions cannot share a position."
            )
        seen_ordinals.add(ordinal)
        prompt_text = raw.get("prompt_text")
        if not isinstance(prompt_text, str) or not prompt_text.strip():
            raise _ReplyError(f"question {question_id!r}: prompt_text must be non-empty.")
        question_type = raw.get("question_type")
        if question_type not in QUESTION_TYPES:
            raise _ReplyError(
                f"question {question_id!r}: question_type {question_type!r} is outside "
                f"the vocabulary {QUESTION_TYPES} (FR-SETUP-01)."
            )
        max_points = raw.get("max_points", 0.0)
        if isinstance(max_points, bool) or not isinstance(max_points, (int, float)):
            raise _ReplyError(
                f"question {question_id!r}: max_points must be a number, got "
                f"{max_points!r}."
            )
        raw_options = raw.get("options", [])
        if not isinstance(raw_options, list):
            raise _ReplyError(f"question {question_id!r}: options must be a list.")
        options: list[ProposedOption] = []
        option_ids: set[str] = set()
        option_ordinals: set[int] = set()
        for option_index, raw_option in enumerate(raw_options):
            if not isinstance(raw_option, dict):
                raise _ReplyError(
                    f"question {question_id!r} option #{option_index} is not an object."
                )
            option_id = raw_option.get("option_id")
            label = raw_option.get("label")
            if not isinstance(option_id, str) or not option_id.strip():
                raise _ReplyError(
                    f"question {question_id!r} option #{option_index}: option_id must "
                    "be a non-empty string."
                )
            if option_id in option_ids:
                raise _ReplyError(
                    f"question {question_id!r}: duplicate option_id {option_id!r}."
                )
            if not isinstance(label, str) or not label.strip():
                raise _ReplyError(
                    f"question {question_id!r} option {option_id!r}: label must be "
                    "non-empty."
                )
            option_ordinal = raw_option.get("ordinal", option_index)
            if (not isinstance(option_ordinal, int) or isinstance(option_ordinal, bool)
                    or option_ordinal < 0):
                raise _ReplyError(
                    f"question {question_id!r} option {option_id!r}: ordinal must be "
                    f"a non-negative integer, got {option_ordinal!r}."
                )
            if option_ordinal in option_ordinals:
                raise _ReplyError(
                    f"question {question_id!r}: duplicate option ordinal "
                    f"{option_ordinal} — two options cannot share a position."
                )
            option_ordinals.add(option_ordinal)
            option_ids.add(option_id)
            options.append(ProposedOption(option_id=option_id,
                                          ordinal=option_ordinal, label=label))
        if question_type in ("mcq", "mixed") and not options:
            raise _ReplyError(
                f"question {question_id!r} is {question_type} but proposes no options "
                "— the teacher would have nothing to mark (FR-SETUP-01)."
            )
        if question_type == "open" and options:
            raise _ReplyError(
                f"question {question_id!r} is open but carries {len(options)} "
                "option(s) — a typed mismatch is a proposal bug, not a content choice."
            )
        questions.append(ProposedQuestion(
            question_id=question_id, ordinal=ordinal, prompt_text=prompt_text,
            question_type=question_type, max_points=float(max_points),
            options=tuple(options),
        ))
    return tuple(questions)


def _question_to_dict(question: ProposedQuestion) -> dict:
    """The catalog's record shape for `write_confirmed_inventory` — plain mappings,
    because the data layer does not import this module's types."""
    return {
        "question_id": question.question_id,
        "ordinal": question.ordinal,
        "prompt_text": question.prompt_text,
        "question_type": question.question_type,
        "max_points": question.max_points,
        "options": [
            {"option_id": option.option_id, "ordinal": option.ordinal,
             "label": option.label}
            for option in question.options
        ],
    }


def _assert_confirmed_shape(questions: Sequence[ProposedQuestion]) -> None:
    """Re-validate AFTER corrections (`CT-PKG-12` in setup's own voice): a correction
    set can collide ordinals or duplicate ids that the proposal alone never had. The
    catalog re-validates at the write (`InventoryError`); this pre-check keeps the
    failure in setup's taxonomy with the correction named."""
    if not questions:
        raise SetupError(
            "a confirmed inventory carries at least one question — the corrections "
            "removed every proposed question. Add one (the manual-entry path) or "
            "confirm the proposal unmodified."
        )
    seen_ids: set[str] = set()
    seen_ordinals: set[int] = set()
    for question in questions:
        if question.question_id in seen_ids:
            raise SetupError(
                f"correction produced a duplicate question_id {question.question_id!r}."
            )
        seen_ids.add(question.question_id)
        if question.ordinal in seen_ordinals:
            raise SetupError(
                f"correction produced a duplicate ordinal {question.ordinal} "
                f"(question {question.question_id!r}) — two questions cannot share a "
                "position."
            )
        seen_ordinals.add(question.ordinal)
        if question.question_type not in QUESTION_TYPES:
            raise SetupError(
                f"correction set question {question.question_id!r} to question_type "
                f"{question.question_type!r}, outside the vocabulary {QUESTION_TYPES}."
            )
        if question.question_type in ("mcq", "mixed") and not question.options:
            raise SetupError(
                f"correction left {question.question_type} question "
                f"{question.question_id!r} without options — the teacher would have "
                "nothing to mark."
            )
        if question.question_type == "open" and question.options:
            raise SetupError(
                f"correction left open question {question.question_id!r} with an "
                "option set — a typed mismatch is a correction bug, not a content "
                "choice."
            )


def _proposal_from_row(v: PackageVersionId, row: Mapping[str, Any]) -> InventoryProposal:
    """Rebuild the stored proposal — the resume path's read (`CT-SETUP-03`: state is
    the database). The payload's entries become `ProposedQuestion`s verbatim; a
    malformed stored payload raises `SetupError` naming the corruption rather than
    silently re-proposing over it."""
    try:
        payload = json.loads(row["payload"])
        entries = payload["entries"]
        status = payload["status"]
    except (ValueError, KeyError, TypeError) as error:
        raise SetupError(
            f"the stored proposal for version {v!r} is malformed ({error}) — the "
            "payload is provenance and is not silently replaced; delete the version "
            "and run setup again."
        ) from error
    questions = tuple(
        ProposedQuestion(
            question_id=str(entry["question_id"]),
            ordinal=int(entry["ordinal"]),
            prompt_text=str(entry["prompt_text"]),
            question_type=str(entry["question_type"]),
            max_points=float(entry.get("max_points", 0.0)),
            options=tuple(
                ProposedOption(option_id=str(option["option_id"]),
                               ordinal=int(option["ordinal"]),
                               label=str(option["label"]))
                for option in entry.get("options", ())
            ),
        )
        for entry in entries
    )
    return InventoryProposal(
        proposal_id=str(row["proposal_id"]),
        assessment_doc_id=str(row["assessment_doc_id"]),
        package_version_id=v,
        template_version=str(row["template_version"]),
        model_ref=str(row["model_ref"]),
        attempts=int(row["attempts"]),
        questions=questions,
        status=status,
        confirmed_at=row["confirmed_at"],
    )


class SetupService:
    """M-SETUP's Stage A, end to end, from code (`CT-SETUP-11`'s headless driver).

    `SetupService(catalog, ingestor, provider, model_ref)` — the Tier P catalog the
    package lives in, the `M-INGEST` gateway the assessment is read through, and the
    `M-PROV` seam the proposal call goes through. `params` defaults to
    `SamplingParams(temperature=0.0)`: a proposal is a reading task, not a sampling
    one.

    Design §3.6's protocol, and what this story stages:

    ============================  =============================================
    operation                     status
    ============================  =============================================
    `propose_inventory`           here — one proposal per version (`CT-SETUP-16`)
    `confirm_inventory`           here — BLOCKING gate 1; locks the rows
    `set_answer_keys`             here — BLOCKING gate 2 (thin; #53 stages the
                                  full `FR-SETUP-03` semantics)
    `publish`                     here — refused until both gates hold
    `ensure_version`, `steps`,    here — the resume and console surfaces
    `current_proposal`
    `read_back_rubric`            #51 (the `reference_solution` column exists)
    `classify_decomposability`,   #52
    `confirm_classifications`,
    `propose_dependencies`
    `set_grade_policy`            #53 (grade boundaries land there too)
    `check_prefix_budget`         #53
    ============================  =============================================
    """

    def __init__(
        self, catalog: PackageCatalog, ingestor: Any, provider: InferenceProvider,
        model_ref: ModelRef, *, params: SamplingParams | None = None,
    ) -> None:
        self._catalog = catalog
        self._ingestor = ingestor
        self._provider = provider
        self._model_ref = model_ref
        self._params = params if params is not None else SamplingParams(temperature=0.0)

    @property
    def package_id(self) -> str:
        """The package this service stages, as the catalog knows it."""
        return self._catalog.package_id

    # -- the version and the resume surface -------------------------------------------------

    def ensure_version(self) -> PackageVersionId:
        """The draft version setup works on, minted on first call: the package row and
        its initial version are exactly what `create_version` refuses to mint itself
        (`FR-SETUP-16`'s first move). Resumption calls this and gets the SAME draft —
        the latest unpublished version — because state is the database (`CT-SETUP-03`)."""
        draft = self._catalog.draft_version()
        if draft is not None:
            return draft
        self._catalog.ensure_package()
        version = self._catalog.create_version(None)
        LOGGER.info("minted initial package version %s for setup", version)
        return version

    def current_proposal(self) -> InventoryProposal | None:
        """The draft version's stored proposal, or None — what a resuming console
        re-renders without calling the model again."""
        v = self._catalog.draft_version()
        if v is None:
            return None
        stored = self._catalog.proposal(v)
        return _proposal_from_row(v, stored) if stored else None

    def steps(self) -> SetupProgress:
        """The enumerated setup steps and what remains (`TC-SETUP-03`'s shape,
        `NFR-SETUP-04`'s honest count).

        With no draft version the package is in one of two states, told apart by
        `has_version`: NOT STARTED (no version at all — the inventory step is
        available, because proposing mints the initial version) or FINISHED (a
        published version, no draft — every step unavailable and the count 0: no step
        can be acted on, and a count that says otherwise is the console lying).

        `answer_keys`' done state is the structural fact `publish` enforces — every
        deterministic criterion keyed — which with zero criteria is vacuously true:
        no deterministic criterion exists until #53 stages their creation from the
        confirmed inventory, so in this story's world a confirmed inventory is
        publishable and the console must say so rather than demand a step whose work
        does not exist yet."""
        v = self._catalog.draft_version()
        if v is None:
            # No draft. Two states, told apart (`has_version`): a package with NO
            # version has not started — the inventory step is available (its first
            # move mints the draft); a package whose versions are all published has
            # FINISHED — no step can be acted on, and the remaining count is 0
            # because a count that says otherwise is the console lying.
            started = self._catalog.has_version()
            later_steps = (
                SetupStep(
                    step_id="rubric_readback",
                    name="Rubric read-back against the stored rubric",
                    blocking=False, available=False, done=False,
                    note="staged by #51",
                ),
                SetupStep(
                    step_id="decomposability",
                    name="Criterion decomposability and dependencies",
                    blocking=False, available=False, done=False,
                    note="staged by #52",
                ),
                SetupStep(
                    step_id="grade_policy",
                    name="Grade policy, boundaries and the prefix budget",
                    blocking=False, available=False, done=False,
                    note="staged by #53",
                ),
            )
            return SetupProgress(
                package_version_id=None,
                steps=(
                    SetupStep(
                        step_id="inventory",
                        name="Question inventory: propose, correct, confirm",
                        blocking=True, available=not started, done=False,
                        note="setup has not started — proposing mints the package's "
                        "initial version" if not started else
                        "setup has finished (its version is published); a new "
                        "instrument is a new package or a revision (FR-PKG-02)",
                    ),
                    SetupStep(
                        step_id="answer_keys",
                        name="Answer keys for the deterministic criteria",
                        blocking=True, available=False, done=False,
                        note="needs a draft version and a confirmed inventory",
                    ),
                ) + later_steps,
                remaining_steps=1 if not started else 0,
                ready_to_publish=False,
            )
        stored = self._catalog.proposal(v)
        confirmed = bool(stored and stored["confirmed_at"])
        criteria = self._catalog.criteria(v)
        unkeyed = [
            row["criterion_id"] for row in criteria
            if row.get("scoring_model") == "atomic" and not row.get("answer_key")
        ]
        keys_done = not unkeyed
        keys_note = ""
        if not confirmed:
            keys_note = "unlocks when the question inventory is confirmed (§4.2.1)"
        elif unkeyed:
            keys_note = f"answer keys missing for: {', '.join(unkeyed)}"
        elif not any(row.get("scoring_model") == "atomic" for row in criteria):
            keys_note = "no deterministic criteria yet — #53 stages their creation"
        later = (
            SetupStep(
                step_id="rubric_readback",
                name="Rubric read-back against the stored rubric",
                blocking=False, available=False, done=False,
                note="staged by #51",
            ),
            SetupStep(
                step_id="decomposability",
                name="Criterion decomposability and dependencies",
                blocking=False, available=False, done=False,
                note="staged by #52",
            ),
            SetupStep(
                step_id="grade_policy",
                name="Grade policy, boundaries and the prefix budget",
                blocking=False, available=False, done=False,
                note="staged by #53",
            ),
        )
        steps = (
            SetupStep(
                step_id="inventory",
                name="Question inventory: propose, correct, confirm",
                blocking=True, available=True, done=confirmed,
                note="" if confirmed else "the teacher's confirmation is blocking "
                "gate 1 of 2 (FR-SETUP-02)",
            ),
            SetupStep(
                step_id="answer_keys",
                name="Answer keys for the deterministic criteria",
                blocking=True, available=confirmed, done=keys_done,
                note=keys_note,
            ),
        ) + later
        remaining = sum(1 for step in steps if step.available and not step.done)
        ready = confirmed and keys_done
        return SetupProgress(
            package_version_id=v, steps=steps, remaining_steps=remaining,
            ready_to_publish=ready,
        )

    # -- Stage A: propose, confirm (BLOCKING), publish ---------------------------------------

    def propose_inventory(self, assessment_doc: DocumentId) -> InventoryProposal:
        """Propose the question inventory from the assessment document — ONCE per
        version (`CT-SETUP-16`).

        The document is read through `M-INGEST` (`CT-SETUP-11`); one model call goes
        out through the provider seam per attempt (`CT-SETUP-12`'s budget, env-gated).
        A reply that fails to parse or validate is re-requested; after the budget the
        proposal is recorded as `needs_manual_entry` — degraded but complete, the
        teacher enters the questions as `add` corrections and confirms.

        Already-stored proposals come back unchanged (the resume path — no new model
        call); a CONFIRMED inventory refuses to be proposed again (`SetupOrderError`):
        it is locked (`FR-SETUP-02`), and a new instrument is a new version."""
        v = self.ensure_version()
        stored = self._catalog.proposal(v)
        if stored is not None:
            proposal = _proposal_from_row(v, stored)
            if proposal.confirmed:
                raise SetupOrderError(
                    f"the inventory for version {v!r} was already confirmed at "
                    f"{proposal.confirmed_at}; the question rows are locked "
                    "(FR-SETUP-02) and proposing again is out of order (CT-SETUP-16). "
                    "A new instrument is a new version (FR-PKG-02)."
                )
            LOGGER.info("resuming with the stored proposal %s for version %s",
                        proposal.proposal_id, v)
            return proposal

        markdown = self._ingestor.read_document(assessment_doc)
        payload = PromptPayload(fields=(
            ("instruction", _INVENTORY_INSTRUCTION),
            ("assessment_transcript", markdown),
        ))
        proposal_id = uuid.uuid4().hex[:12]
        budget = _configured_proposal_attempts()
        last_error = ""
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref,
                                                     self._params)
                questions = _parse_reply(completion.text)
            except _ReplyError as error:
                last_error = f"attempt {attempt}: {error}"
                LOGGER.warning("inventory proposal reply failed to parse (%d/%d): %s",
                               attempt, budget, error)
                continue
            except Exception as error:  # contained: the transport's failure is a
                # failed attempt, and the degraded path — not a crash — is the
                # honest end of a budget spent (CT-SETUP-12).
                last_error = f"attempt {attempt}: {type(error).__name__}: {error}"
                LOGGER.warning("inventory proposal attempt %d/%d failed: %s",
                               attempt, budget, error)
                continue
            body = {
                "status": "proposed",
                "entries": [_question_to_dict(question) for question in questions],
            }
            self._catalog.record_proposal(
                v, proposal_id=proposal_id, assessment_doc_id=assessment_doc,
                payload=json.dumps(body, sort_keys=True),
                template_version=SETUP_PROMPT_TEMPLATE_V,
                model_ref=completion.resolved_build, attempts=attempt,
            )
            proposal = InventoryProposal(
                proposal_id=proposal_id, assessment_doc_id=assessment_doc,
                package_version_id=v, template_version=SETUP_PROMPT_TEMPLATE_V,
                model_ref=completion.resolved_build, attempts=attempt,
                questions=questions, status="proposed",
            )
            LOGGER.info(
                "proposed inventory %s for version %s from document %s: %d "
                "question(s) in %d attempt(s), prompt %s",
                proposal_id, v, assessment_doc, len(questions), attempt,
                SETUP_PROMPT_TEMPLATE_V,
            )
            return proposal

        body = {
            "status": "needs_manual_entry",
            "entries": [],
            "reason": last_error,
        }
        self._catalog.record_proposal(
            v, proposal_id=proposal_id, assessment_doc_id=assessment_doc,
            payload=json.dumps(body, sort_keys=True),
            template_version=SETUP_PROMPT_TEMPLATE_V,
            model_ref=self._model_ref.build_id, attempts=budget,
        )
        LOGGER.warning(
            "inventory proposal for version %s degraded to needs_manual_entry after "
            "%d attempt(s): %s — the teacher enters the questions as corrections "
            "(CT-SETUP-12)", v, budget, last_error,
        )
        return InventoryProposal(
            proposal_id=proposal_id, assessment_doc_id=assessment_doc,
            package_version_id=v, template_version=SETUP_PROMPT_TEMPLATE_V,
            model_ref=self._model_ref.build_id, attempts=budget, questions=(),
            status="needs_manual_entry",
        )

    def confirm_inventory(
        self, proposal_id: str, corrections: Sequence[QuestionCorrection] = (),
    ) -> None:
        """The teacher's confirmation — BLOCKING gate 1 (`§4.2.1`). Applies the
        corrections to the stored proposal and writes the confirmed inventory through
        `M-PKG` in one transaction; the §6.2 lock engages at this write
        (`FR-SETUP-02`), which is why confirmation is deliberate and refuses to be
        anonymous: the `proposal_id` must be the version's stored proposal, so the
        teacher confirms what was actually proposed.

        Returns None by design (`§3.6`'s protocol): the confirmation's observable
        result is the locked inventory, read back through `current_proposal` /
        `steps` / the catalog's question surfaces."""
        v = self._require_draft_version()
        stored = self._catalog.proposal(v)
        if stored is None:
            raise SetupOrderError(
                f"no inventory proposal is recorded for version {v!r} — "
                "propose_inventory first; confirmation confirms a proposal, not an "
                "idea."
            )
        if stored["confirmed_at"] is not None:
            raise SetupOrderError(
                f"the inventory for version {v!r} is already confirmed (at "
                f"{stored['confirmed_at']}) — it is locked (FR-SETUP-02) and cannot "
                "be confirmed again."
            )
        if stored["proposal_id"] != proposal_id:
            raise SetupOrderError(
                f"confirmation names proposal {proposal_id!r} but version {v!r} "
                f"holds {stored['proposal_id']!r} — the teacher confirms what was "
                "proposed, and a stale or foreign id is refused."
            )
        proposal = _proposal_from_row(v, stored)
        entries: dict[str, ProposedQuestion] = {
            question.question_id: question for question in proposal.questions
        }
        for correction in corrections:
            if correction.action not in ("add", "set", "remove"):
                raise SetupError(
                    f"correction for {correction.question_id!r} has unknown action "
                    f"{correction.action!r} — 'add', 'set' or 'remove'."
                )
            if correction.action == "add":
                if correction.question_id in entries:
                    raise SetupError(
                        f"add correction names {correction.question_id!r}, which the "
                        "proposal already carries — a 'set' correction edits it."
                    )
                missing = [
                    field for field in ("question_type", "prompt_text")
                    if getattr(correction, field) is None
                ]
                if missing:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} is missing "
                        f"{', '.join(missing)} — the manual-entry path must carry "
                        "them (CT-SETUP-12)."
                    )
                if correction.question_type not in QUESTION_TYPES:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} carries "
                        f"question_type {correction.question_type!r}, outside the "
                        f"vocabulary {QUESTION_TYPES}."
                    )
                options = correction.options or ()
                if correction.question_type in ("mcq", "mixed") and not options:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} is "
                        f"{correction.question_type} without options — the teacher "
                        "would have nothing to mark."
                    )
                if correction.question_type == "open" and options:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} is open but "
                        "carries options — a typed mismatch is a correction bug."
                    )
                ordinal = correction.ordinal
                if ordinal is None:
                    ordinal = max((q.ordinal for q in entries.values()), default=-1) + 1
                entries[correction.question_id] = ProposedQuestion(
                    question_id=correction.question_id, ordinal=ordinal,
                    prompt_text=correction.prompt_text or "",
                    question_type=correction.question_type,
                    max_points=float(correction.max_points or 0.0),
                    options=tuple(options),
                )
            elif correction.action == "set":
                if correction.question_id not in entries:
                    raise SetupError(
                        f"set correction names {correction.question_id!r}, which the "
                        "proposal does not carry — 'add' contributes a new question."
                    )
                base = entries[correction.question_id]
                if (correction.options is not None
                        and correction.question_type is None
                        and base.question_type == "open" and correction.options):
                    raise SetupError(
                        f"set correction adds options to open question "
                        f"{correction.question_id!r} without retyping it — set "
                        "question_type to 'mcq' or 'mixed' in the same correction."
                    )
                entries[correction.question_id] = ProposedQuestion(
                    question_id=base.question_id,
                    ordinal=base.ordinal if correction.ordinal is None
                    else correction.ordinal,
                    prompt_text=base.prompt_text if correction.prompt_text is None
                    else correction.prompt_text,
                    question_type=base.question_type
                    if correction.question_type is None
                    else correction.question_type,
                    max_points=base.max_points if correction.max_points is None
                    else float(correction.max_points),
                    options=base.options if correction.options is None
                    else tuple(correction.options),
                )
            else:  # remove
                if correction.question_id not in entries:
                    raise SetupError(
                        f"remove correction names {correction.question_id!r}, which "
                        "the proposal does not carry."
                    )
                del entries[correction.question_id]
        questions = tuple(entries.values())
        _assert_confirmed_shape(questions)
        self._catalog.write_confirmed_inventory(
            v, proposal_id=proposal_id,
            questions=[_question_to_dict(question) for question in questions],
            confirmed_at=_now(),
        )
        LOGGER.info(
            "inventory confirmed for version %s (%d question(s), %d correction(s)) — "
            "the question rows are locked (FR-SETUP-02)", v, len(questions),
            len(corrections),
        )

    def set_answer_keys(self, keys: Mapping[str, Sequence[str]]) -> None:
        """The teacher's answer keys — BLOCKING gate 2 (`§4.2.1`). A thin write-through
        to `PackageCatalog.set_answer_key` (`FR-PKG-17`'s single canonical
        representation): `#53` stages S4's full `FR-SETUP-03` semantics on top of this
        surface, so the operation exists and blocks NOW and does not change shape
        later. Requires the confirmed inventory first — the keys name criteria the
        inventory's questions become, and §4.2.1's order is S3 then S4."""
        v = self._require_draft_version()
        stored = self._catalog.proposal(v)
        if stored is None or stored["confirmed_at"] is None:
            raise SetupOrderError(
                "answer keys come after the confirmed inventory (S3 blocks S4, "
                "§4.2.1): confirm_inventory first — the keys name criteria the "
                "confirmed questions become."
            )
        if not keys:
            raise SetupError(
                "set_answer_keys with an empty mapping keys nothing — name at least "
                "one criterion and its acceptable option ids."
            )
        for criterion_id, key in keys.items():
            self._catalog.set_answer_key(v, criterion_id, list(key))
        LOGGER.info(
            "set %d answer key(s) for version %s — blocking step S4 (its full "
            "FR-SETUP-03 validation semantics land with #53)", len(keys), v,
        )

    def publish(self, approved_by: str) -> PackageVersionId:
        """Publish the version — the point the §6.2 lock takes effect (`FR-SETUP-02`).

        Both blocking gates are checked HERE and refused with the gate named: the
        confirmed inventory (gate 1) and every deterministic criterion keyed (gate 2).
        The publication itself is `M-PKG`'s one-transaction lock flip (`FR-PKG-01`) —
        setup assembles and gates; the Tier P writer writes (`CT-PKG-12`)."""
        v = self._require_draft_version()
        self._refuse_unmet_gates(v)
        self._catalog.publish(v, approved_by)
        LOGGER.info(
            "published package version %s by %r — both blocking gates satisfied; the "
            "§6.2 schema lock now holds (FR-SETUP-02)", v, approved_by,
        )
        return v

    # -- internals ----------------------------------------------------------------------------

    def _require_draft_version(self) -> PackageVersionId:
        """The draft the operation works on, or the honest refusal: a package whose
        setup has finished has a published version and no draft, and operating on a
        published version is not setup's business."""
        v = self._catalog.draft_version()
        if v is None:
            raise SetupOrderError(
                f"no unpublished version exists for package {self.package_id!r} — "
                "setup has already finished (its version is published) or the initial "
                "version was never minted: call ensure_version() first."
            )
        return v

    def _refuse_unmet_gates(self, v: PackageVersionId) -> None:
        """The two blocking gates, each refused with its number and its unblocking
        step — the console renders the refusal verbatim (`FR-CONSOLE-06`: exactly two
        screens block)."""
        stored = self._catalog.proposal(v)
        if stored is None or stored["confirmed_at"] is None:
            raise SetupOrderError(
                "publish refused: the question inventory is not confirmed — blocking "
                "gate 1 of 2 (§4.2.1). The teacher's confirmation is the assertion "
                "the §6.2 lock records (FR-SETUP-02): confirm_inventory first."
            )
        unkeyed = [
            row["criterion_id"] for row in self._catalog.criteria(v)
            if row.get("scoring_model") == "atomic" and not row.get("answer_key")
        ]
        if unkeyed:
            raise SetupOrderError(
                "publish refused: answer keys missing for the deterministic criteria "
                f"{', '.join(unkeyed)} — blocking gate 2 of 2 (§4.2.1): "
                "set_answer_keys first."
            )
