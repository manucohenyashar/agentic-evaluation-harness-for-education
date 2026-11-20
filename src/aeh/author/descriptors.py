"""Every judged band says what earns it (FR-AUTHOR-33/34, CT-AUTHOR-28).

A judged line's band with no descriptor leaves the judge choosing among bare names (R40).
The rubric prompt still never invents one ("Omit descriptor when the teacher gives none"):
the draft instead carries a placeholder in that band's `descriptor`, and the teacher
answers it as an open question — *"What earns '<band>' on <question>? Say what the answer
does, not how good it is."* — whose sentence becomes the descriptor. A draft with any
judged band still lacking one is not approvable (`open_descriptors` is the gate's list).

Which bands are judged: every band of a criterion that carries a `bands` list and no
`key`. Exempt are the deterministic `correct`/`incorrect` bands (a `key` line carries no
bands in the draft; the build makes them) and an evidence checklist's `absent` band — the
binary aspect's other half, whose meaning is its `present` band's descriptor negated.

The descriptor lint (FR-AUTHOR-34) is a note, never a refusal: a descriptor naming how
good the answer is (`AUTHOR_EVALUATIVE_TERMS`, whole words, extended by
`HARNESS_AUTHOR_EVALUATIVE_TERMS`) is shown on the review screen with a suggestion.

Everything here is a pure function of the draft spec, never stored.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

from .settings import extra_evaluative_terms

#: The evaluative or magnitude words a descriptor should not lean on (FR-AUTHOR-34),
#: matched as whole words, case-insensitively.
AUTHOR_EVALUATIVE_TERMS: tuple[str, ...] = (
    "good", "excellent", "poor", "weak", "strong", "adequate", "correct", "appropriate",
    "properly", "well", "clearly",
)

#: The longest descriptor the teacher's answer may be, in characters.
DESCRIPTOR_MAX_CHARS = 300

#: The field id a band's descriptor placeholder carries: `descriptor <band> <qid>` — the
#: house shape `<field> <qid>` the report's scope attribution reads by suffix.
DESCRIPTOR_FIELD = "descriptor"

#: The aspect band that needs no descriptor of its own (the present band's, negated).
_ABSENT_BAND = "absent"

_PLACEHOLDER_PREFIX = "<<PLACEHOLDER:"
#: Characters a band name may not carry into a placeholder id: the sentinel's own
#: delimiters and the TOML string escapes, which would make the draft text and its parsed
#: value disagree.
_ID_UNSAFE = re.compile(r'[<>"\\\n\r\t]')


def is_placeholder(value: Any) -> bool:
    """Whether `value` is a draft placeholder sentinel."""
    return isinstance(value, str) and value.startswith(_PLACEHOLDER_PREFIX)


def descriptor_item_id(band: str, qid: str) -> str:
    """The placeholder id of band `band`'s descriptor on question `qid`."""
    safe = " ".join(_ID_UNSAFE.sub(" ", str(band)).split())
    return f"{DESCRIPTOR_FIELD} {safe} {qid}"


def parse_descriptor_item_id(item_id: str, spec: Mapping[str, Any],
                             owner_qid: str | None = None) -> tuple[str, str | None]:
    """`(band, qid)` for a `descriptor <band> <qid>` id. The question is `owner_qid` when
    the caller knows it, else the longest question id of the draft the id ends with (a
    question id may carry spaces), else the id's last word."""
    rest = str(item_id).strip()[len(DESCRIPTOR_FIELD):].strip()
    qids = [str(block.get("id")) for block in _blocks(spec, "question")
            if block.get("id") is not None]
    if owner_qid is not None:
        qids = [str(owner_qid), *qids]
    qid = max((q for q in qids if rest.endswith(" " + q)), key=len, default=None)
    if qid is None:
        band, _sep, last = rest.rpartition(" ")
        return (band or rest), (last if band else owner_qid)
    return rest[:-len(qid)].strip(), qid


def _blocks(spec: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    raw = spec.get(name)
    if not isinstance(raw, list):
        return []
    return [block for block in raw if isinstance(block, Mapping)]


def judged_bands(spec: Mapping[str, Any]) -> Iterator[tuple[Mapping[str, Any], dict[str, Any]]]:
    """Every judged band of the draft that needs a descriptor, as `(criterion, band)`, in
    document order: a band of a criterion carrying a `bands` list and no `key`, except an
    evidence checklist aspect's `absent` band."""
    for criterion in _blocks(spec, "criterion"):
        bands = criterion.get("bands")
        if criterion.get("key") is not None or not isinstance(bands, list):
            continue
        for band in bands:
            if not isinstance(band, dict):
                continue
            if criterion.get("component_of") and \
                    str(band.get("name") or "").strip().lower() == _ABSENT_BAND:
                continue
            yield criterion, band


def lacks_descriptor(band: Mapping[str, Any]) -> bool:
    """Whether a band still says nothing about what earns it: no descriptor, an empty
    one, or its placeholder still standing."""
    descriptor = band.get("descriptor")
    return not isinstance(descriptor, str) or not descriptor.strip() \
        or is_placeholder(descriptor)


def open_descriptors(spec: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The judged bands still lacking a descriptor, as `(qid, band name)` in document
    order — what the approval gate refuses on (FR-AUTHOR-33, CT-AUTHOR-28)."""
    return [(str(criterion.get("question") or ""), str(band.get("name") or ""))
            for criterion, band in judged_bands(spec) if lacks_descriptor(band)]


def mark_missing_descriptors(spec: Mapping[str, Any]) -> list[str]:
    """Put the descriptor placeholder into every judged band with no descriptor, in place;
    the placeholder ids it wrote, in document order. A band already carrying its own
    placeholder is left as it stands; one whose placeholder names another band or question
    (the band renamed, the line re-pointed at another question) is re-keyed, so the open
    question always names the band and question as they now stand."""
    written: list[str] = []
    for criterion, band in judged_bands(spec):
        if not lacks_descriptor(band):
            continue
        item_id = descriptor_item_id(str(band.get("name") or ""),
                                     str(criterion.get("question") or ""))
        sentinel = f"<<PLACEHOLDER: {item_id}>>"
        if band.get("descriptor") == sentinel:
            continue
        band["descriptor"] = sentinel
        written.append(item_id)
    return written


def descriptor_gap_reason() -> str:
    """The placeholder comment's reason: the audit record, never shown to the teacher."""
    return ("the documents name the band but do not say what earns it, and a descriptor "
            "is never invented")


def descriptor_gap_supply(band: str, question_label: str) -> str:
    """What the teacher supplies, in their words (no ids)."""
    return f"what an answer does to earn '{band}' on {question_label}"


# --- the lint (FR-AUTHOR-34) -------------------------------------------------------------------------


def evaluative_terms() -> tuple[str, ...]:
    """The words the lint looks for: the built-in list plus the configured extras
    (`HARNESS_AUTHOR_EVALUATIVE_TERMS`, read at call time)."""
    extra = [word for word in extra_evaluative_terms() if word not in AUTHOR_EVALUATIVE_TERMS]
    return (*AUTHOR_EVALUATIVE_TERMS, *extra)


def descriptor_note(descriptor: Any, terms: tuple[str, ...] | None = None) -> str | None:
    """The review screen's note for a descriptor that says how good the answer is rather
    than what it does — any evaluative word as a whole word — or `None`. Never a refusal."""
    if not isinstance(descriptor, str) or not descriptor.strip() or is_placeholder(descriptor):
        return None
    words = terms if terms is not None else evaluative_terms()
    pattern = r"\b(?:" + "|".join(re.escape(word) for word in words) + r")\b"
    if not words or re.search(pattern, descriptor, re.IGNORECASE) is None:
        return None
    text = " ".join(descriptor.split())
    return (f"'{text}' says how good the answer is; the grader does better with what the "
            "answer does, for example 'names the law and applies it to the case'.")
