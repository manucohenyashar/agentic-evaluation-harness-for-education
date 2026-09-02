"""A synthetic roster with real-shaped names, and the scan that must never find one.

`NFR-PROV-04` names its own acceptance form: *"Request bodies shall carry `student_ref` only
and shall contain no student name; an assertion over assembled payloads is the acceptance
form."* `NFR-JUDGE-04` says the same thing from the other side of the boundary, and `SEC-04`
makes it a security case: *"Scan every assembled payload in a full run against the roster's
real names."*

This module supplies both halves that scan needs — a roster to scan **against**, and a
shape-agnostic walk over an assembled request to scan **in**.

It stands in for `F-SYNTH`'s roster
------------------------------------
§4.4 describes `F-SYNTH` as *"350 generated submissions ... deterministically generated from a
seed so the whole suite reproduces"*, and issue #2 (TS-01) owns the corpus. The roster here is
generated the same way and to the same size, so a case written against it needs no rewrite when
the corpus lands — only a change of source. Nothing about the pseudonymization property depends
on the submission *content*, which is why this case does not have to wait for #2.

The names are deliberately unusual, and that is the design
-----------------------------------------------------------
A pattern scan against a list of *common* given names is a scan that fires on ordinary rubric
prose: a criterion reading "the student must show their work" contains no name, but a roster
holding `Mark`, `Grace` or `Will` turns "mark the diagram", "grace period" and "will not"
into three findings. The response to that is always the same — someone adds an exclusion list,
the exclusion list grows, and the case stops being able to see a real leak.

So the roster is generated from a syllable table that produces pronounceable, plausibly-real,
and near-collision-free names. That keeps the failure mode on the right side: the scan reports
a name **only** when a name is actually present, which is what makes a red result actionable.
`test_payload_pseudonymization.py` carries the control that proves the scan still catches one.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any, Iterator, Sequence

#: §4.4: `F-SYNTH` is 350 submissions. The roster is the same size so a scan over it is the
#: scan `TC-PROV-21`'s precondition describes ("across a 350-submission run").
ROSTER_SIZE = 350

#: The same constant `tests/conftest.py` uses, so a roster built here reproduces exactly.
#: §4.6 forbids `random.seed()`; this module seeds its own `Random` instance and never the
#: module-global.
ROSTER_SEED = 20260101

_GIVEN_STEMS = (
    "Alvenn", "Brellis", "Cordwyn", "Dravelle", "Emberis", "Fenwold", "Gallowin",
    "Harnisse", "Ildreth", "Jorvast", "Kestrile", "Lumbreck", "Mardovin", "Nyxelle",
    "Orbenth", "Pellwick", "Quorvane", "Rasmyre", "Sablewyn", "Torvelle", "Umbriel",
    "Vandrick", "Wrenhollow", "Xanthrop", "Ysolde", "Zephrant",
)
_FAMILY_STEMS = (
    "Ashcombe", "Bramblewick", "Cinderhalt", "Duskmoor", "Eldergrove", "Fallowmere",
    "Grimsdale", "Hollowbrook", "Ironvale", "Jessamy", "Kirkwynd", "Larkspire",
    "Mosswarden", "Netherfield", "Oakenshaw", "Pinebarrow", "Quillhaven", "Ravenscar",
    "Stonebridle", "Thistlewood", "Ulverston", "Vellacourt", "Whitmarsh", "Yarrowden",
)


@dataclass(frozen=True)
class Student:
    """One roster entry: the pseudonym that may travel, and the name that may not."""

    student_ref: str  #: the opaque handle a payload is allowed to carry
    given_name: str  #: never permitted in a payload
    family_name: str  #: never permitted in a payload

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}"

    @property
    def names(self) -> tuple[str, ...]:
        """Every form of the name a payload could leak.

        The full name is included as well as its parts, because a scan that looked only for
        `"Alvenn Ashcombe"` would miss a payload carrying `"Ashcombe, Alvenn"` — and a leak in
        either direction is the same disclosure.
        """
        return (self.given_name, self.family_name, self.full_name)


def build_roster(size: int = ROSTER_SIZE, seed: int = ROSTER_SEED) -> tuple[Student, ...]:
    """A deterministic roster of `size` students.

    `student_ref` is a zero-padded opaque handle carrying no name material, which is what
    `NFR-PROV-04` means by pseudonymization: the reference is stable and resolvable *outside*
    the payload, by whoever holds the roster.
    """
    rng = random.Random(seed)
    seen: set[str] = set()
    students: list[Student] = []
    index = 0
    while len(students) < size:
        given = rng.choice(_GIVEN_STEMS)
        family = rng.choice(_FAMILY_STEMS)
        full = f"{given} {family}"
        if full in seen:
            continue
        seen.add(full)
        index += 1
        students.append(
            Student(student_ref=f"stu-{index:04d}", given_name=given, family_name=family)
        )
    return tuple(students)


def roster_name_patterns(roster: Sequence[Student]) -> dict[str, re.Pattern[str]]:
    """One compiled word-boundary pattern per distinct name in the roster.

    Word-boundary anchored and case-insensitive. Anchoring matters in both directions: without
    it `Ash` inside `Ashcombe` would be reported for a roster containing neither, and a payload
    lowercasing a name before embedding it would escape a case-sensitive scan while disclosing
    just as much.
    """
    patterns: dict[str, re.Pattern[str]] = {}
    for student in roster:
        for name in student.names:
            if name not in patterns:
                patterns[name] = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    return patterns


@dataclass(frozen=True)
class NameHit:
    """One disclosure: which payload, whose name, and the text around it.

    `student_refs` is a tuple rather than a single ref because a name is not unique to a
    student. Real cohorts contain two Wrenhollows, and the roster here is generated the same
    way; a hit on `"Wrenhollow"` identifies a *set* of students whose name was disclosed. An
    earlier draft reported one ref — whichever won a dict lookup — and named the wrong student
    in the failure report whenever a surname was shared, which is the sort of detail that makes
    a P0 security failure look like a test bug.
    """

    payload_id: str
    student_refs: tuple[str, ...]
    name: str
    excerpt: str

    def __str__(self) -> str:
        who = ", ".join(self.student_refs)
        return f"{self.payload_id}: {self.name!r} (student(s) {who}) in {self.excerpt!r}"


def strings_in(value: Any, _depth: int = 0) -> Iterator[str]:
    """Every string reachable inside an assembled request, whatever shape it has.

    Shape-agnostic on purpose. `NFR-PROV-04` is *"no field carrying a student name"* — a
    property of the whole assembled object, not of a field list somebody remembered to
    enumerate. A scan written against named fields goes quietly blind the moment a field is
    added, which is the direction this case cannot afford: it is the acceptance form of a P0
    security requirement.

    Walks dataclasses, mappings, and sequences. Bytes are decoded leniently, because a payload
    that has already been serialized is still a payload.
    """
    if _depth > 12:  # cycles are not expected in a frozen request; this bounds a surprise
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, (bytes, bytearray)):
        yield bytes(value).decode("utf-8", errors="replace")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from strings_in(key, _depth + 1)
            yield from strings_in(item, _depth + 1)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from strings_in(item, _depth + 1)
        return
    fields = getattr(value, "__dataclass_fields__", None)
    if fields is not None:
        for name in fields:
            yield from strings_in(getattr(value, name), _depth + 1)
        return
    slots = getattr(value, "__slots__", None)
    if slots:
        for name in slots:
            yield from strings_in(getattr(value, name, None), _depth + 1)
        return
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        yield from strings_in(attributes, _depth + 1)


def scan_for_names(
    payload_id: str,
    payload: Any,
    roster: Sequence[Student],
    patterns: dict[str, re.Pattern[str]] | None = None,
) -> list[NameHit]:
    """Every roster name appearing anywhere in one assembled payload.

    The oracle `TC-PROV-21` names: *"a pattern scan over assembled artifacts"*, run against the
    roster's name list.
    """
    patterns = patterns if patterns is not None else roster_name_patterns(roster)
    hits: list[NameHit] = []
    for text in strings_in(payload):
        for name, pattern in patterns.items():
            match = pattern.search(text)
            if match is None:
                continue
            start = max(0, match.start() - 30)
            hits.append(
                NameHit(
                    payload_id=payload_id,
                    student_refs=students_named(roster, name),
                    name=name,
                    excerpt=text[start : match.end() + 30],
                )
            )
    return hits


def students_named(roster: Sequence[Student], name: str) -> tuple[str, ...]:
    """Every `student_ref` whose name matches `name`, in roster order.

    A shared surname means one disclosed string names several students, and the report has to
    say so — see `NameHit`.
    """
    return tuple(s.student_ref for s in roster if name in s.names)


def carries_student_ref(payload: Any, student: Student) -> bool:
    """Whether the payload carries the pseudonymous handle it is supposed to.

    The other half of `TC-PROV-21`'s expected result — *"Every payload carries `student_ref`"*.
    Asserted separately from the name scan because the two fail differently: a payload carrying
    neither the name nor the ref is not a privacy success, it is an unattributable judgment.
    """
    return any(student.student_ref in text for text in strings_in(payload))
