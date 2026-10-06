"""Negative and positive controls for `tests/support/help_vocabulary.py` (issue #637, TS-150).

The `M-HELP` cases are written ahead of #636 and cannot run yet, but the instruments they read
through — the request sweep, the all-tier write snapshot, the recorded QA double, the manual
helpers — are pure and can be proven today. A sweep that cannot find a planted token, or a
snapshot that cannot see a planted row, would let every one of those cases pass vacuously the
day they are unmarked. Fast tier, unmarked.
"""

from __future__ import annotations

import sqlite3

import pytest

from tests.support import help_vocabulary as hv


# --- the sweep ---------------------------------------------------------------------------


def test_sweep_finds_every_planted_token_case_insensitively():
    text = "passage ... cohort C-HELP-7Q and ref zq-7731-HELP ... Ignatius brackenridge"
    hits = hv.sweep(text, {"cohort": "c-help-7Q", "ref": "zq-7731-help", "n": "Ignatius Brackenridge",
                           "absent": "pkg-help-7Q"})
    assert hits == ["cohort: 'c-help-7Q'", "ref: 'zq-7731-help'", "n: 'Ignatius Brackenridge'"]


def test_sweep_allows_a_name_only_inside_the_exact_question():
    q = hv.STUDENT_T.question
    assert hv.sweep(f"<q>{q}</q>", {"n": "Zelda Quartermaine"}, allow_in=q) == []
    assert hv.sweep(f"<q>{q}</q> roster: Zelda Quartermaine", {"n": "Zelda Quartermaine"}, allow_in=q)


def test_wrapped_requires_delimiters_on_both_sides():
    q = "Start the run for me."
    assert hv.wrapped(f"<question>\n{q}\n</question>", q)
    assert not hv.wrapped(q, q)
    assert not hv.wrapped(f"Question: {q}", q)


def test_contains_window_matches_a_section_across_markdown_and_whitespace():
    section = "The **blind sample** is graded\nwithout seeing the system's grade, so agreement can be measured."
    prompt = hv.norm("PASSAGE [a]: The blind sample is graded without seeing the system s grade, so agreement can be measured.")
    assert hv.contains_window(prompt, section)
    assert not hv.contains_window(hv.norm("an unrelated passage about exports"), section)


# --- the all-tier write snapshot ---------------------------------------------------------


def test_snapshot_sees_one_tier_d_row_and_flags_any_other_write(tmp_data_dir):
    from aeh.store import open_store

    store = open_store(tmp_data_dir)
    world = hv.seed_student_world(store)
    hv.open_every_tier(store, packages=[world.package_id], cohorts=[world.cohort_id])
    store.close()
    before = hv.store_snapshot(tmp_data_dir)
    assert any(k.startswith("durable.sqlite::") for k in before)
    assert any(k.startswith("cohorts/") and k.endswith("::roster") for k in before)

    durable = sqlite3.connect(tmp_data_dir / "durable.sqlite")
    durable.execute("CREATE TABLE planted_log (q TEXT)")
    durable.execute("INSERT INTO planted_log VALUES ('one')")
    durable.commit()
    durable.close()
    log_only = hv.snapshot_diff(before, hv.store_snapshot(tmp_data_dir))
    assert hv.only_the_log_grew(log_only, added=1) == []
    assert hv.only_the_log_grew(log_only, added=2)

    cohort_file = next((tmp_data_dir / "cohorts").glob("*.sqlite"))
    cohort = sqlite3.connect(cohort_file)
    cohort.execute("UPDATE roster SET student_ref = student_ref || '-x' WHERE student_ref = ?",
                   (hv.IGNATIUS["ref"],))
    cohort.commit()
    cohort.close()
    both = hv.snapshot_diff(before, hv.store_snapshot(tmp_data_dir))
    assert hv.only_the_log_grew(both, added=1), "a same-count row EDIT in Tier C went unseen"

    # The store reopens after `settled_snapshot` closes it, as the rig relies on.
    assert hv.IGNATIUS["ref"] + "-x" in {
        r["student_ref"] for r in store.cohort(world.cohort_id).query(
            "SELECT student_ref FROM roster WHERE cohort_id = :c", c=world.cohort_id)}
    store.close()


def test_seeded_world_tokens_are_really_in_the_store(tmp_data_dir):
    """The sweep's forbidden tokens must be things the store actually holds, or a clean sweep
    proves nothing."""
    from aeh.store import open_store

    store = open_store(tmp_data_dir)
    world = hv.seed_student_world(store)
    store.close()
    rows = []
    for path in (tmp_data_dir / "cohorts").glob("*.sqlite"):
        connection = sqlite3.connect(path)
        try:
            rows += connection.execute(
                "SELECT cohort_id, student_ref FROM roster "
                "UNION ALL SELECT submission_id, student_ref FROM submission").fetchall()
        finally:
            connection.close()
    dump = "\n".join(repr(r) for r in rows)
    for label in ("cohort id", "Zelda's ref", "Ignatius's ref", "submission 1", "submission 1 ref"):
        assert world.forbidden[label] in dump, label


# --- the recorded QA double --------------------------------------------------------------


def _prompt(*values: str):
    from aeh.prov import PromptPayload

    return PromptPayload(fields=tuple((f"f{i}", v) for i, v in enumerate(values)))


def test_the_double_replays_the_declared_reply_through_the_recorded_provider(tmp_path):
    from aeh.prov import SamplingParams
    from tests.support.conf_builders import EDGE_JUDGE, HOSTED_JUDGE

    double = hv.QaDouble(tmp_path / "rec")
    prompt = _prompt("Answer only from the passages.", f"<question>{hv.ACTION_T.question}</question>")
    cloud = double.complete(prompt, HOSTED_JUDGE, SamplingParams(temperature=0.0))
    edge = double.complete(prompt, EDGE_JUDGE, SamplingParams(temperature=0.0))
    assert cloud.text == hv.ACTION_T.reply and cloud.cost is None
    assert (cloud.latency_ms, edge.latency_ms) == (hv.ACTION_T.latency_ms["cloud"], hv.ACTION_T.latency_ms["edge"])
    assert len(list((tmp_path / "rec").glob("*.json"))) == 2, "not replayed from recordings"
    assert [c.transcript for c in double.calls] == [hv.ACTION_T, hv.ACTION_T]


def test_the_double_refuses_an_undeclared_question(tmp_path):
    from aeh.prov import SamplingParams
    from tests.support.conf_builders import HOSTED_JUDGE

    with pytest.raises(AssertionError, match="no declared transcript"):
        hv.QaDouble(tmp_path / "rec").complete(_prompt("<q>What is the capital of Peru?</q>"),
                                               HOSTED_JUDGE, SamplingParams(temperature=0.0))


def test_every_declared_question_is_distinct():
    questions = [t.question for t in hv.TRANSCRIPTS]
    assert len(set(questions)) == len(questions)


# --- manual helpers ------------------------------------------------------------------------


def test_seeded_phrase_comes_from_prose_under_its_heading():
    raw = ("# Guide\n\n## Review\n\n- a list item that is long enough to be picked by mistake here\n"
           "```\ncode line that is very long and must never be chosen as the phrase\n```\n"
           "The blind sample is graded without seeing the system grade at all.\n\n## Export\nShort.\n")
    phrase, heading = hv.seeded_phrase(raw)
    assert (phrase, heading) == ("the blind sample is graded without seeing the", "Review")


def test_problems_with_manual_flags_a_missing_toc_and_dangling_or_duplicate_anchors():
    good = {"manual_id": "m", "toc": [{"anchor": "a", "heading": "A"}],
            "sections": [{"anchor": "a", "heading": "A", "text": "t"}]}
    assert hv.problems_with_manual(good) == []
    assert hv.problems_with_manual({**good, "toc": []})
    assert hv.problems_with_manual({**good, "toc": [{"anchor": "zz"}]})
    assert hv.problems_with_manual({**good, "sections": good["sections"] * 2})


def test_percentile_95_is_nearest_rank():
    assert hv.percentile_95(list(range(1, 21))) == 19
    assert hv.percentile_95([5.0]) == 5.0


def test_the_reference_envelope_sits_inside_the_budget():
    """The recorded envelope alone must pass, so a red TC-HELP-05 is the assistant's time."""
    for profile, budget in hv.P95_BUDGET_MS.items():
        assert max(t.latency_ms[profile] for t in hv.REFERENCE_SET) < budget
    assert len(hv.REFERENCE_SET) >= 20
