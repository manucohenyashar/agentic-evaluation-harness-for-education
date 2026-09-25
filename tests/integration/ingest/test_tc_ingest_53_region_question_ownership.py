"""`TS-92` (issue #386) — `TC-INGEST-53`: a region's question is a PARSED fact, carried
forward, not reconstructed from position order (`#373`, delta §3.14, Q-21).

| Input | Expected |
|---|---|
| a 2-question page with one graphic after Q2's text | the stored graphic region carries `question_id = 'Q2'` |
| — | a consumer reading ownership uses the column (source scan: no preceding-region inference in storage consumers) |

**Why the column exists.** A transcript names a question once — on the region carrying its
text — and everything after it belongs to that question until the next one is named: a graphic,
a selection mark, a continuation. Without the column every consumer has to rebuild that by
walking regions in position order, and each one rebuilds it slightly differently. The first
consumer to sort by something else, or to filter before walking, silently attributes a
student's diagram to the wrong question.

**`None` before the first named question is deliberate and is asserted.** A header or a name
field genuinely precedes every question, and adopting it into the first question that happens
to follow would be the same inference by another name. Absence is the honest value.

**The static half scans for the inference, not for the column.** A consumer that reads
`question_id` and *also* falls back to "the last region that had one" is the defect: it works
on every document where the column is populated and diverges on exactly the ones where it is
not. So the scan looks for position-ordered ownership reconstruction in the modules that read
`document_region`, and it is a census with its own control — the same shape as `TC-ORCH-48`'s.

**Isolation: rung 2** — a real cohort ledger and the real ingest gateway.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
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
from aeh.store import Statement, open_store

pytestmark = pytest.mark.integration

COHORT = "c-ingest53"

#: Two questions, and a graphic that follows Q2's text with no question of its own — the
#: ordinary shape of a page where a student drew their answer.
TRANSCRIPT = (
    "<!-- region: kind=transcribed_text conf=0.95 -->\n"
    "Physics paper 1 — Student: A. Candidate\n"
    "<!-- /region -->\n"
    "<!-- region: kind=transcribed_text question_id=Q1 state=present conf=0.95 -->\n"
    "the worked answer to Q1\n"
    "<!-- /region -->\n"
    "<!-- region: kind=transcribed_text question_id=Q2 state=present conf=0.95 -->\n"
    "the worked answer to Q2\n"
    "<!-- /region -->\n"
    "<!-- region: kind=described_graphic element_kind=free_body_diagram conf=0.92 -->\n"
    "a free-body diagram: arrow W downward from the block's centre\n"
    "<!-- /region -->"
)

_REGIONS = Statement(
    "SELECT position, region_kind, question_id, content FROM document_region "
    "WHERE document_id = :d ORDER BY position"
)


@pytest.fixture
def parsed(tmp_data_dir):
    """The transcript above, ingested through the real gateway."""
    from aeh.ingest import Ingestor
    from aeh.prov import SamplingParams
    from tests.integration.ingest.test_ingest_gateway import (
        OnePageRasterizer,
        THROUGH_SANITIZER,
        _model,
        _region_provider,
    )

    store = open_store(tmp_data_dir)
    try:
        handle = store.cohort(COHORT)
        source = store.blobs().put(b"fixture pdf")
        ingestor = Ingestor(
            handle, store.blobs(), _region_provider([TRANSCRIPT]), _model(),
            SamplingParams(temperature=0.0), OnePageRasterizer(),
            sanitizer=THROUGH_SANITIZER,
        )
        document_id = ingestor.ingest_document(
            [source], kind="submission", filenames={source: "scan-01.md"}
        )
        rows = [dict(row) for row in handle.query(_REGIONS, d=document_id)]
        yield rows
    finally:
        store.close()


# --- TC-INGEST-53, the parsed fact ---------------------------------------------------------


def test_tc_ingest_53_the_graphic_after_q2_belongs_to_q2(parsed):
    """The `described_graphic` region carries `question_id = 'Q2'`.

    The case. The graphic names no question of its own — a transcript names a question once —
    so the only way the column can hold `Q2` is if the parser carried it forward.
    """
    graphics = [row for row in parsed if row["region_kind"] == "described_graphic"]

    assert len(graphics) == 1, (
        f"the page parsed {len(graphics)} graphic regions, not one: "
        f"{[r['region_kind'] for r in parsed]}"
    )
    assert graphics[0]["question_id"] == "Q2", (
        f"the graphic carries question_id {graphics[0]['question_id']!r}, not 'Q2'. It "
        "follows Q2's text and names no question itself, so the parser must carry the "
        "current question forward — otherwise every consumer rebuilds that from position "
        "order, and each rebuilds it slightly differently"
    )


def test_tc_ingest_53_each_text_region_carries_its_own_question(parsed):
    """Q1's and Q2's text regions carry their own ids.

    The control for the carry-forward: if every region were stamped with the *last* id seen,
    Q1's region would be right by accident and Q2's would be too. Asserting both, in order,
    is what makes the graphic's `Q2` meaningful rather than "whatever the last write was".
    """
    owners = [(row["region_kind"], row["question_id"]) for row in parsed]

    assert ("transcribed_text", "Q1") in owners, f"Q1's text has no owner: {owners}"
    assert ("transcribed_text", "Q2") in owners, f"Q2's text has no owner: {owners}"

    named = [row["question_id"] for row in parsed if row["question_id"]]
    assert named == ["Q1", "Q2", "Q2"], (
        f"the parsed ownership sequence is {named}, not ['Q1', 'Q2', 'Q2'] — the header "
        "unowned, then Q1, then Q2 and the graphic that follows it"
    )


def test_tc_ingest_53_a_region_before_any_question_records_no_owner(parsed):
    """The header region's `question_id` is `None`, not `Q1`.

    Adopting a region that genuinely precedes every question into the first one that happens
    to follow it is the same positional inference the column exists to remove — just applied
    at the top of the page. Absence is the honest value.
    """
    header = parsed[0]

    assert header["question_id"] is None, (
        f"the region before the first named question carries "
        f"{header['question_id']!r}. It is a header, not an answer: a name field adopted by "
        "Q1 becomes part of Q1's evidence"
    )


# --- TC-INGEST-53, the static half ------------------------------------------------------------

#: The modules that read `document_region` and could reconstruct ownership positionally.
STORAGE_CONSUMERS = ("integ.py", "extract.py", "det.py", "grade.py")

#: The shape the scan forbids: a variable that remembers the last seen question across a loop
#: over regions. Named here so the control below can build one.
_CARRY_NAMES = re.compile(
    r"(last|previous|prior|current)_?(question|q)(_id)?$", re.IGNORECASE
)


def _positional_owner_inference(
    module_name: str, source_text: str | None = None
) -> list[tuple[str, int]]:
    """Functions in `module_name` that assign a carry-forward question variable inside a loop.

    Parsed rather than grepped: the modules discuss `question_id` in prose constantly, and a
    text search would report every docstring. What counts is an assignment to a
    carry-shaped name that happens *inside* a `for`/`while` — which is what rebuilding
    ownership from position order looks like.
    """
    if source_text is None:
        source = pathlib.Path(aeh.ingest.__file__).parent / module_name
        if not source.exists():
            return []
        source_text = source.read_text(encoding="utf-8")
    tree = ast.parse(source_text)

    scope: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                scope.setdefault(id(inner), node.name)

    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.While)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Assign):
                continue
            for target in inner.targets:
                name = getattr(target, "id", None) or getattr(target, "attr", None)
                if name and _CARRY_NAMES.search(str(name)):
                    found.append((scope.get(id(inner), "<module>"), inner.lineno))
    return found


@pytest.mark.parametrize("module_name", STORAGE_CONSUMERS)
def test_tc_ingest_53_no_storage_consumer_rebuilds_ownership_from_position(module_name):
    """No consumer of `document_region` carries a question forward across a loop.

    The column is the answer; a consumer that also reconstructs it works on every document
    where the column is populated and diverges on exactly the ones where it is not — a header
    region, a page whose first question is unnamed. That divergence attributes a student's
    diagram to the wrong question and nothing reports it.
    """
    offenders = _positional_owner_inference(module_name)

    assert offenders == [], (
        f"{module_name} rebuilds question ownership positionally at {offenders}. "
        "`document_region.question_id` is a parsed fact (#373); a consumer that re-derives it "
        "will disagree with the parser on the documents where it matters"
    )


def test_tc_ingest_53_the_ownership_scan_recognises_the_inference_it_forbids():
    """The scan's control, run through `_positional_owner_inference` itself.

    Exercised through the real function — the source is passed in rather than the filesystem
    patched — so a scan that stopped matching fails here instead of leaving the four module
    cases passing over nothing. (Patching `Path.read_text` was the first attempt and it
    recursed: the replacement read the probe file through the patch it had just installed.)
    """
    probe = (
        "def owners(regions):\n"
        "    current_question = None\n"
        "    out = []\n"
        "    for region in regions:\n"
        "        if region.get('question_id'):\n"
        "            current_question = region['question_id']\n"
        "        out.append(current_question)\n"
        "    return out\n"
    )

    found = _positional_owner_inference("probe_consumer.py", probe)

    assert [name for name, _line in found] == ["owners"], (
        f"the scan reported {found} for a function that plainly carries the question "
        "forward inside its loop — every module case above is passing over a pattern it "
        "cannot see"
    )
