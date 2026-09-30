"""Second descriptions of graphics, the facts they must agree on, and text similarity."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .errors import IngestError
from .schema import INGEST_STATEMENTS


#: The printed page-number pattern the page-number tier parses (`FR-INGEST-06`'s
#: second preference tier): a leading "Page N of M" header, which is what a pinned
#: transcription prompt asks the model to carry over verbatim.
_PAGE_NUMBER_PATTERN = re.compile(r"\bPage\s+(\d+)\s+of\s+(\d+)\b", re.IGNORECASE)


#: The fiducial-marker pattern (the same tier's other form): an explicit marker the
#: print shop placed at the top of every sheet — the line starts with it, and body
#: text may follow on the same line.
_FIDUCIAL_PATTERN = re.compile(r"^\[fiducial:([A-Za-z0-9._-]+)\]", re.MULTILINE)


#: The similarity measure for duplicates and divergence: word-level Jaccard over
#: lowercased whitespace-split tokens. Declared here so both thresholds measure the
#: same thing and the two TBDs stay comparable.
def _tokens(text: str) -> set[str]:
    return frozenset(text.lower().split())


# --- the second-description pass (FR-INGEST-14, Phase 2, #233) ----------------------------------
#
# For a described graphic on a criterion the injected high-risk register names (Q-12: the
# register's contents are operator policy, so the list is a constructor argument), the SAME
# crop is described a second time by a DIFFERENT model family, and the two descriptions are
# compared on their load-bearing facts. The second description is stored in
# `document_region.description_secondary`; the comparison is derived from the two stored
# texts by `description_disagreement`, so `M-INTEG` reads it from the region rows
# (`description_integrity_signals`) and nothing about it is auto-resolved.
#
# **"Load-bearing fact" is not defined by the design** (FR-INGEST-14 names the term only).
# Recorded interpretation: the load-bearing facts of a graphic description are its NUMBERS
# (values, labels like 30°, 5 N, 2.5) — the facts a scoring decision reads off a diagram —
# compared as normalized multisets, plus a lexical floor on the content words so two
# descriptions of different things do not agree merely by sharing no numbers. The floor is
# the env knob below; production default 0.35.

SECOND_DESCRIPTION_PROMPT = (
    "Describe the graphic in this image crop factually and neutrally: what is drawn, every "
    "label, every number with its unit, and how the parts relate. Do not evaluate, grade or "
    "judge correctness. Reply with the description only."
)


SECOND_DESCRIPTION_PROMPT_VERSION = "second-description-v1"


#: The lexical floor under which two descriptions of one crop disagree even when their
#: numbers match (content-word Jaccard, 0.0..1.0). Read at call time (seam 3).
SECOND_DESCRIPTION_MIN_SIMILARITY_ENV = "HARNESS_INGEST_SECOND_DESCRIPTION_MIN_SIMILARITY"


DEFAULT_SECOND_DESCRIPTION_MIN_SIMILARITY = 0.35


_NUMBER_PATTERN = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?")


def load_bearing_facts(description: str | None) -> tuple[str, ...]:
    """The description's load-bearing facts: its numbers, normalized (`2,50` and `2.5`
    are one fact) and sorted, duplicates kept — a diagram with two 30° angles states a
    different fact from one with a single 30° angle."""
    facts = []
    for raw in _NUMBER_PATTERN.findall(description or ""):
        value = raw.replace(",", ".")
        if "." in value:
            value = value.rstrip("0").rstrip(".") or "0"
        facts.append(value)
    return tuple(sorted(facts))


def _second_description_min_similarity() -> float:
    raw = os.environ.get(SECOND_DESCRIPTION_MIN_SIMILARITY_ENV)
    if not raw:
        return DEFAULT_SECOND_DESCRIPTION_MIN_SIMILARITY
    try:
        value = float(raw)
    except ValueError as error:
        raise IngestError(
            f"{SECOND_DESCRIPTION_MIN_SIMILARITY_ENV}={raw!r} is not a number.") from error
    if not 0.0 <= value <= 1.0:
        raise IngestError(
            f"{SECOND_DESCRIPTION_MIN_SIMILARITY_ENV}={value} is outside 0.0..1.0.")
    return value


def description_disagreement(primary: str | None, secondary: str | None) -> dict:
    """Compare two descriptions of one crop (FR-INGEST-14). Returns the integrity
    signal's body: `disagrees`, the `reasons` (`facts` when the load-bearing facts
    differ, `similarity` when the content words fall under the floor), both fact
    multisets, the facts only one side states, and the similarity. Never resolves
    which description is right — that is `M-INTEG`'s and the human's."""
    left, right = load_bearing_facts(primary), load_bearing_facts(secondary)
    left_words = set(re.findall(r"[a-z]+", (primary or "").lower())) - _V4_STOPWORDS
    right_words = set(re.findall(r"[a-z]+", (secondary or "").lower())) - _V4_STOPWORDS
    similarity = (len(left_words & right_words) / len(left_words | right_words)
                  if left_words and right_words else 0.0)
    floor = _second_description_min_similarity()
    reasons = []
    if left != right:
        reasons.append("facts")
    if similarity < floor:
        reasons.append("similarity")
    only_primary = list(left)
    only_secondary = []
    for fact in right:
        if fact in only_primary:
            only_primary.remove(fact)
        else:
            only_secondary.append(fact)
    return {
        "disagrees": bool(reasons),
        "reasons": reasons,
        "facts_primary": list(left),
        "facts_secondary": list(right),
        "facts_only_primary": only_primary,
        "facts_only_secondary": only_secondary,
        "similarity": round(similarity, 3),
        "min_similarity": floor,
    }


@dataclass(frozen=True)
class DescriptionIntegritySignal:
    """One second-described region, as `M-INTEG` reads it (FR-INGEST-14): both
    descriptions and their comparison. `disagreement` is `description_disagreement`'s
    body; nothing here says which description is right."""

    region_id: str
    document_id: str
    element_kind: str
    crop_ref: str | None
    description: str | None
    description_secondary: str | None
    disagreement: dict | None
    status: str = "described"
    error: str | None = None


def description_integrity_signals(handle: Any, document_id: str
                                  ) -> tuple["DescriptionIntegritySignal", ...]:
    """The FR-INGEST-14 integrity signals of one document, for `M-INTEG`: every region
    that carries a second description, with the comparison derived from the two stored
    texts. A disagreement is reported, never swallowed or resolved."""
    rows = handle.query(INGEST_STATEMENTS["select_document_second_described_regions"],
                        document_id=document_id)
    record = second_description_pass(handle, document_id, rows=rows) or {}
    outcomes = {entry["region_id"]: entry for entry in record.get("regions", [])}
    signals = []
    for row in rows:
        entry = outcomes.get(row["region_id"])
        if row["description_secondary"] is not None:
            # The verdict frozen at ingest wins; a row written before verdicts were
            # stored is compared now.
            verdict = (entry or {}).get("disagreement") or description_disagreement(
                row["description"], row["description_secondary"])
            signals.append(DescriptionIntegritySignal(
                region_id=row["region_id"], document_id=document_id,
                element_kind=row["element_kind"], crop_ref=row["crop_ref"],
                description=row["description"],
                description_secondary=row["description_secondary"],
                disagreement=verdict))
        elif entry is not None and entry.get("status") == "failed":
            # A failed second description is a signal too, with no comparison, so it
            # can never read as agreement (or as "not high-risk").
            signals.append(DescriptionIntegritySignal(
                region_id=row["region_id"], document_id=document_id,
                element_kind=row["element_kind"], crop_ref=row["crop_ref"],
                description=row["description"], description_secondary=None,
                disagreement=None, status="failed", error=entry.get("error")))
    return tuple(signals)


def second_description_pass(handle: Any, document_id: str, *, rows: Any = None
                            ) -> dict | None:
    """The FR-INGEST-14 pass record stored with the document: `status` `ran` (with
    the declared criteria, matched and failed counts and per-region outcomes) or
    `not_run` (a revision), or `None` when no high-risk register was injected. Lets
    `M-INTEG` tell "not high-risk" from "the pass did not run"."""
    if rows is None:
        rows = handle.query(
            INGEST_STATEMENTS["select_document_second_described_regions"],
            document_id=document_id)
    for row in rows:
        if row["source_blobs"]:
            return json.loads(row["source_blobs"]).get("second_description_pass")
        return None
    return None


def _jaccard_similarity(a: str, b: str) -> float:
    left, right = _tokens(a), _tokens(b)
    if not left and not right:
        return 1.0  # two empty pages are identical for these purposes
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


#: V4's lexical measure (`FR-INGEST-25`'s aggregate semantic correspondence, ADR-7's
#: "shared-vocabulary and notation overlap") runs over CONTENT words: a bare
#: whitespace Jaccard is dominated by function words, and two papers from different
#: subjects share enough "the/of/and" to clear any usable floor. Closed list,
#: deterministic; the duplicate and divergence measures keep their unfiltered
#: tokenizer — their thresholds are calibrated against it (TC-INGEST-03/08/09).
_V4_STOPWORDS: frozenset[str] = frozenset(
    "a an the of and or is are was were be been being to in on at for with by from "
    "as that this it its into than then so such not no nor but if when while which "
    "what who whom whose where why how all any both each few more most other some "
    "only own same too very can will just should now has had have do does did doing "
    "would could may might must shall there their them they he she we you your i me "
    "my we our us out up down over under again further once here about above below "
    "between during before after s t don now".split())


def _v4_lexical_affinity(a: str, b: str) -> float:
    """Content-word Jaccard: the shared-vocabulary half of V4's semantic measure."""
    left = frozenset(_tokens(a)) - _V4_STOPWORDS
    right = frozenset(_tokens(b)) - _V4_STOPWORDS
    if not left and not right:
        return 0.0  # two contents-less texts share nothing: not a perfect match
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
