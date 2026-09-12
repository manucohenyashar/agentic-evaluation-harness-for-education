"""`TC-CALIB-16` — a full elicitation cycle leaves a complete, append-only trail.

Test plan §5.17, `TC-CALIB-16` (FR-CALIB-14, Integration / rung 2 — oracle: *append-only
assertion*).

The store-level refusals are green in the contract suite (`TC-CALIB-C11` twice over: a
row refused on update and on delete through the standalone history fixture, `TC-PKG-20`'s
no-update-no-delete-door surface) — the refusal lives in the data layer, migration 005's
unconditional trigger pair, so every writer meets it or crashes. What no green test
carried before this file is the case's **cycle**: one ask → one answer → one edit, driven
end to end over a real catalog, with the trail read back through a *fresh* store open and
reconstructed from the history alone:

* **every question asked is on the record** — each row's `question` is the question
  `elicit` returned, not a paraphrase: the trail joins to the session the teacher
  actually sat through;
* **every option offered is on the record** — `options_offered` carries the full option
  set on every row, so the trail shows the choice the teacher was given, not just the
  word they said;
* **the teacher's answer is on the record** — including the *keep as is* answer, whose
  row is the only evidence the teacher confirmed the band and chose not to edit;
* **the resulting edit is on the record** — the edit answer's row names the version it
  produced (`FR-PKG-04`'s revision flow: one new version per edit, each copy parented on
  the previous), and the keep-as-is row names none (`resulting_edit` empty) — the
  distinction the audit needs to tell "the teacher kept the rubric" from "the row was
  written sloppily";
* and the trail is on the **published base** — appends are always allowed on a published
  version (`FR-PKG-20`), which is what makes a conversation about the rubric as it
  stands recordable at all.

Nothing updated or deleted, in both senses the case names: by **observation** (the
read-back after the full cycle is exactly the rows the cycle appended — nothing else
landed), and by **refusal** (one raw-SQL UPDATE and one raw-SQL DELETE aimed at the
cycle's own rows are aborted by the store's trigger pair — the data layer's refusal,
reached through a fresh handle with no catalog in the way, the same mechanism
`TC-CALIB-C11` asserts at the store level and this cycle's rows inherit).

The read-back is deliberately a fresh `open_store` on the cycle's own file — not a read
through the facade that performed the writes. A warm handle would make "the trail is in
the store" indistinguishable from "the trail is in the process"; the reopen is what makes
the read a fact about the file.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests.support.impl import CALIB_MODULE, require


def _finding_on(calib, *, band_ordinal: int, submissions: int):
    """An edit-eligible ambiguity on the fixture package's one criterion (`CRIT-1`).

    Built on the rubric's real criterion id — `findings_fixture`'s `CRIT-00x` ids would
    resolve against nothing this version carries — with distinct band ordinals so the
    two questions address the two bands the criterion carries, and distinct affected
    counts so the ranking (and with it the question order) is deterministic."""
    return calib.Finding(
        criterion_id="CRIT-1",
        category="rubric_ambiguity",
        submissions_affected=submissions,
        examples=(
            f"student response A for criterion CRIT-1 (band {band_ordinal})",
            f"student response B for criterion CRIT-1 (band {band_ordinal})",
        ),
        band_ordinal=band_ordinal,
    )


def _run_cycle(calib, elicit, apply_answers, catalog):
    """One full cycle: elicit two ambiguities, answer one edit and one keep-as-is.

    Returns `(questions, base, revised)` — the session, the published base the trail
    records conversations against, and the version the edit produced (`None` would mean
    no edit landed, which would make the cycle's edit half vacuous)."""
    questions = elicit(
        [
            _finding_on(calib, band_ordinal=1, submissions=17),
            _finding_on(calib, band_ordinal=0, submissions=9),
        ]
    )
    assert len(questions) == 2, (
        f"the cycle elicited {len(questions)} questions from two eligible findings; "
        "two are needed — one edit answer and one keep-as-is answer — for the trail to "
        "carry both shapes"
    )
    base = catalog.latest_version()
    assert base is not None, "the fixture package published no version to calibrate"
    revised = apply_answers(
        {"q1": "broaden", "q2": "keep as is"}, catalog=catalog
    )
    assert revised is not None, (
        "the edit answer produced no version — the cycle's edit half never happened"
    )
    return questions, base, revised


def _fresh_store(data_dir: Path, package_id: str):
    """Open the cycle's Tier P file fresh, with the full migration chain imported.

    The chain rule (`CLAUDE.md`) binds the first open in a process — the cycle's own
    catalog build (`catalog_for_test`) has already imported all eleven contributors by
    the time this runs, and the explicit imports here keep the file honest about it.
    """
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.review  # noqa: F401
    import aeh.synth  # noqa: F401

    from aeh.store import open_store

    return open_store(data_dir)


def test_tc_calib_16_the_cycle_leaves_a_complete_trail_a_fresh_open_can_reconstruct():
    """Every question asked, every option offered, the answer, the resulting edit.

    Read back through a fresh store open and matched against the session `elicit`
    returned — the trail alone reconstructs the conversation. Row order is append
    order (`apply_answers` walks the answers in question-id order), so the edit row
    precedes the keep-as-is row and each column is asserted exactly.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")
    apply_answers = require(CALIB_MODULE, "apply_answers", issue="#138")

    tier_p_path = calib.tier_p_path_for_test()
    catalog = calib.catalog_for_test(tier_p_path=tier_p_path)
    questions, base, revised = _run_cycle(calib, elicit, apply_answers, catalog)
    assert catalog.latest_version() == revised, (
        "the version the edit answer produced is not the file's latest version — the "
        "cycle's edit landed somewhere the revision flow cannot see"
    )

    store = _fresh_store(tier_p_path.parent.parent, tier_p_path.name.removesuffix(".pkg.sqlite"))
    try:
        handle = store.package(tier_p_path.name.removesuffix(".pkg.sqlite"))
        rows = handle.query(
            "SELECT elicitation_id, package_version_id, question, options_offered, "
            "answer_given, resulting_edit FROM elicitation_history ORDER BY rowid"
        )
    finally:
        store.close()

    assert len(rows) == 2, (
        f"the cycle appended {len(rows)} history rows for two answered questions; the "
        "trail carries one row per answered question, edit or not"
    )
    assert [row["question"] for row in rows] == [q.question for q in questions], (
        "the history's questions are not the questions the session asked — the trail "
        "must join to the elicitation the teacher sat through, not to a paraphrase"
    )
    for row in rows:
        offered = json.loads(row["options_offered"])
        assert offered == list(calib.QUESTION_OPTIONS), (
            f"row {row['elicitation_id']!r} records options {offered}; every row must "
            f"record the full option set {list(calib.QUESTION_OPTIONS)} — a trail that "
            "cannot show what the teacher was offered cannot show what their answer meant"
        )
    assert [row["answer_given"] for row in rows] == ["broaden", "keep as is"], (
        f"the trail records answers {[row['answer_given'] for row in rows]}; the teacher "
        "answered 'broaden' then 'keep as is' — both the edit and the kept rubric belong "
        "on the record"
    )
    assert [row["resulting_edit"] for row in rows] == [revised, ""], (
        f"the trail records edits {[row['resulting_edit'] for row in rows]}; the edit "
        f"answer's row must name the version it produced ({revised!r}) and the keep-as-is "
        "row must name none — the distinction between 'the teacher kept the rubric' and "
        "'the row was written sloppily' lives in this column"
    )
    assert all(row["package_version_id"] == base for row in rows), (
        "the trail is not on the published base — appends are allowed on published "
        "versions precisely so the conversation is recorded against the rubric as it "
        "stands (FR-PKG-20)"
    )


def test_tc_calib_16_the_trail_refuses_update_and_delete_on_its_own_rows():
    """Nothing is updated or deleted — the store refuses it on the cycle's own rows.

    The attempts are deliberately raw SQL through a fresh handle: the refusal lives in
    the data layer (migration 005's unconditional trigger pair), so every writer meets
    it — the catalog never offers an update or delete at all (`FR-PKG-20`), and a
    caller reaching around it finds the same wall. `TC-CALIB-C11` asserts this refusal
    at the store level on the standalone fixture; here the rows the refusal protects
    are the ones a real cycle just wrote. After both refused attempts, the rows are
    read back and must be exactly as the cycle appended them.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")
    apply_answers = require(CALIB_MODULE, "apply_answers", issue="#138")

    tier_p_path = calib.tier_p_path_for_test()
    package_id = tier_p_path.name.removesuffix(".pkg.sqlite")
    catalog = calib.catalog_for_test(tier_p_path=tier_p_path)
    _run_cycle(calib, elicit, apply_answers, catalog)

    store = _fresh_store(tier_p_path.parent.parent, package_id)
    try:
        handle = store.package(package_id)
        rows = handle.query(
            "SELECT elicitation_id, question, answer_given, resulting_edit "
            "FROM elicitation_history ORDER BY rowid"
        )
        assert len(rows) == 2, "the cycle left no trail to protect"

        first_id = rows[0]["elicitation_id"]
        for statement, label in (
            ("UPDATE elicitation_history SET answer_given = 'overwritten' "
             "WHERE elicitation_id = :row_id", "update"),
            ("DELETE FROM elicitation_history WHERE elicitation_id = :row_id", "delete"),
        ):
            try:
                with handle.transaction() as tx:
                    tx.execute(statement, row_id=first_id)
                refused = False
            except sqlite3.IntegrityError:
                refused = True
            assert refused, (
                f"a raw {label} on a history row the cycle just appended was not "
                "refused by the store — elicitation_history is append-only in practice, "
                "not by convention (FR-PKG-20): migration 005's unconditional trigger "
                "pair aborts every writer, catalog or not"
            )

        after = handle.query(
            "SELECT elicitation_id, question, answer_given, resulting_edit "
            "FROM elicitation_history ORDER BY rowid"
        )
        assert [tuple(row) for row in after] == [tuple(row) for row in rows], (
            "the trail changed across the refused attempts — a refusal that mutates is "
            "not a refusal"
        )
    finally:
        store.close()