"""`TC-REG-07` — a module's declared statements resolve to ITS dict, not the shared registry.

Regression for a defect found while building `M-PIPE` (#364). No `TC-*` case covered it, so the
test lands with the fix, as CLAUDE.md's defect exception requires.

**The defect.** `aeh.extract` and `aeh.judge` both did::

    from aeh.ingest import STATEMENTS as INGEST_STATEMENTS

`STATEMENTS` is `aeh.store`'s **shared registry**, merely visible in `aeh.ingest`'s namespace;
the alias made it read as that module's own dict. Every module merges its statements into that
one registry (`ingest.py`'s `STATEMENTS.update(INGEST_STATEMENTS)`, `det.py`'s
`STATEMENTS.update(DET_STATEMENTS)`, and six more), so a name two modules declare differently
resolves to whichever module was imported LAST.

`select_document_head` is declared twice with different columns:

* `aeh.ingest` — eight columns **including `markdown`**, the canonical transcript.
* `aeh.det` — five columns, no `markdown`.

So a process whose first `aeh` import was `aeh.orch` resolved det's spelling, and extraction
died far from the cause at `extract.py`'s ``head["markdown"]`` with
``IndexError: No item with that key`` — against a store whose schema was complete and whose
`document` rows were present. It worked at all only because CLAUDE.md's canonical import list
is alphabetical, putting `ingest` after `det`: correct by accident, not by construction.

**Why this shape of assertion.** Identity, not behaviour. A test that drove extraction would
pass or fail on whatever import order pytest happened to produce, which is the very thing that
made the defect invisible. `is` against the owning module's dict holds in every import order
and states the rule directly: a module reading `INGEST_STATEMENTS` means M-INGEST's.

**The wider finding is NOT fixed here.** Nine names carry conflicting SQL across module dicts
(`select_run` has six distinct spellings, `select_work_unit` two). Those are latent for the
same reason and are reported separately; this case pins only the two call sites that were
resolving through the shared registry, because those are the two the defect ran through.
"""

from __future__ import annotations

import aeh.det
import aeh.extract
import aeh.ingest
import aeh.judge
import aeh.store


def test_tc_reg_07_consumers_of_ingest_statements_hold_ingests_own_dict() -> None:
    """The two modules that read `INGEST_STATEMENTS` hold M-INGEST's dict, not the registry."""
    for module in (aeh.extract, aeh.judge):
        resolved = getattr(module, "INGEST_STATEMENTS", None)
        assert resolved is not None, (
            f"{module.__name__} no longer binds INGEST_STATEMENTS; if the read moved, move "
            "this case with it rather than deleting it")
        assert resolved is aeh.ingest.INGEST_STATEMENTS, (
            f"{module.__name__} binds something other than M-INGEST's own statement dict. If "
            "it is the shared `aeh.store.STATEMENTS` registry, the statement it resolves "
            "depends on which module was imported last — the defect this case exists for."
        )
        assert resolved is not aeh.store.STATEMENTS, (
            f"{module.__name__} binds the SHARED registry under a module-scoped name")


def test_tc_reg_07_the_document_head_read_still_carries_the_transcript() -> None:
    """The statement those modules resolve selects `markdown` — the column the defect lost.

    The failure was not "a different statement ran"; it was that the row came back without the
    canonical transcript and the caller raised on the missing key. This asserts the column is
    there, which is what the caller actually needs.
    """
    sql = aeh.extract.INGEST_STATEMENTS["select_document_head"].sql
    assert "markdown" in sql, (
        f"the resolved select_document_head carries no markdown column: {sql}")


def test_tc_reg_07_the_two_declarations_really_do_differ() -> None:
    """The positive control: `aeh.det` still declares the same NAME with different columns.

    Without this the two cases above could pass on a tree where the conflict had quietly gone
    away, and would then be asserting nothing. If this ever fails because the names were made
    distinct, that is the better fix and these cases retire with it.
    """
    ingest_sql = aeh.ingest.INGEST_STATEMENTS["select_document_head"].sql
    det_sql = aeh.det.DET_STATEMENTS["select_document_head"].sql
    assert ingest_sql != det_sql, (
        "aeh.det and aeh.ingest now declare select_document_head identically; the collision "
        "this case guards is gone and the guard can go with it")
    assert "markdown" not in det_sql, (
        "aeh.det's select_document_head now selects markdown too, so the collision is no "
        "longer observable through this column")
