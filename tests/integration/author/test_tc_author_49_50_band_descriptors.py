"""`TC-AUTHOR-49`, `TC-AUTHOR-50` (issue #904; FR-AUTHOR-33, FR-AUTHOR-34, CT-AUTHOR-28):
every judged band says what earns it before the test is approved, and a descriptor that
says how good the answer is gets a note, never a refusal.

Statistical validity test plan r2 §3.21, story T20.

| Case | Expected |
|---|---|
| 49 | plain-bands draft: the draft read asks exactly one question per judged band, with the delta's wording; `approve draft package` is refused naming every question (and so every band); answering puts each sentence into its band's `descriptor`, in the draft and in the published package; the evidence checklist's `absent` bands, the described `general` line and the multiple-choice key's `correct`/`incorrect` bands raise no question |
| 50 (served) | the four lint-table descriptors answered on the console: the draft read serves the note on `score_levels[].note` and in `draft.notes` for exactly the two evaluative ones, and approval publishes regardless |

The lint table itself (rung 1, the fast tier) is `tests/unit/author/test_tc_author_50_descriptor_lint.py`.

**Plan deviation, disclosed (the draft).** The plan names AF-07 ("plain bands, no
descriptors"), but none of the 23 F-AUTHOR fixtures' recorded rubric replies drafts a band
without a descriptor (AF-07's carry them; it asks only `model_answer`), and a recording is
never hand-written. The draft is the shipped assembler's over the ENG7 inventory with Q2's
bands stated plain (`tests.support.descriptor_world`), written into the console's authoring
folder.

**The mutation arm.** With the approval gate's descriptor check skipped, approval is *still*
refused — the build trips on the placeholders, and M-PKG's own check (CT-PKG-25) backs that
up — but with the generic "N unanswered pieces" sentence. So the oracle is the refusal's `why`
carrying each literal question, not merely `refused is True`: a skipped gate turns 49 red.

**Isolation: rung 3** — a real store, the real console over HTTP, M-PKG's own build.
**Written ahead of implementation: no, in effect.** The issue says `yes`, but #870 (the
descriptor questions, gate and lint) and #876 (M-PKG's refusal) are merged, so every case
passes and none carries `writtenahead`.

Markers. `integration`.
"""

from __future__ import annotations

import tomllib

import pytest

import aeh.agg  # noqa: F401 — the full migration chain before the first store open (CLAUDE.md)
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
from tests.support import rubric_methods as rm
from tests.support.console_redesign_world import _action, draft_read, served_console
from tests.support.descriptor_world import APPROVER, PACKAGE, PLAIN_BANDS, \
    write_plain_bands_draft

pytestmark = pytest.mark.integration

__all__ = ["served_console"]  # the fixture, imported for pytest

#: The delta's question (FR-AUTHOR-33), written out — never built from the implementation.
QUESTIONS: dict[str, str] = {
    band: (f"What earns '{band}' on question 2? Say what the answer does, not how good "
           "it is.")
    for band, _points in PLAIN_BANDS
}
#: What the teacher answers, one behavioural sentence per band.
ANSWERS: dict[str, str] = {
    "none": "Gives no reason, or a reason unrelated to the lamp.",
    "limited": "Repeats the passage without giving a reason.",
    "adequate": "Gives a reason with no evidence from the passage.",
    "full": "Gives a reason and supports it with the small boat from the passage.",
}
#: TC-AUTHOR-50's four descriptors, on Q2's four bands: two notes, two none.
LINT_ANSWERS: dict[str, tuple[str, bool]] = {
    "none": ("unclear", False),
    "limited": ("a good answer", True),
    "adequate": ("clearly states the conclusion", True),
    "full": ("names the law and applies it", False),
}
NEXT = "Answer the remaining questions on the review screen, then press Approve again."


def _note(descriptor: str) -> str:
    """FR-AUTHOR-34's note, as the delta words it."""
    return (f"'{descriptor}' says how good the answer is; the grader does better with what "
            "the answer does, for example 'names the law and applies it to the case'.")


def _item(band: str) -> str:
    return f"descriptor {band} Q2"


def _answer(port: int, answers: dict[str, str]) -> None:
    outcome = _action(port, "answer authoring review", {
        "package_id": PACKAGE,
        "answers": [{"item_id": k, "value": v} for k, v in answers.items()]})
    assert outcome["refused"] is False, outcome


def _approve(port: int, **extra) -> dict:
    return _action(port, "approve draft package", {"package_id": PACKAGE, **extra})


def _q2_bands(draft_path) -> dict[str, object]:
    spec = tomllib.loads(draft_path.read_text(encoding="utf-8-sig"))
    (line,) = [c for c in spec["criterion"] if c["id"] == "C_Q2"]
    return {band["name"]: band.get("descriptor") for band in line["bands"]}


def _published_bands(store) -> dict[str, dict[str, str]]:
    path = store.package_path(PACKAGE)
    (version,) = rm.locked_versions(path)
    return {cid: {str(b["band"]): str(b["descriptor"] or "") for b in bands}
            for cid, bands in rm.bands_by_criterion(path, version).items()}


# --- TC-AUTHOR-49 ---------------------------------------------------------------------------


def test_tc_author_49_one_question_per_judged_band_and_approval_waits_on_them(
        served_console) -> None:
    _server, port, store, data_dir = served_console
    draft = write_plain_bands_draft(data_dir / "authoring")

    read = draft_read(port)["draft"]
    asked = {p["item_id"]: p for p in read["placeholders"]
             if p["item_id"].startswith("descriptor")}
    # Exactly Q2's four bands: no question for the checklist's `absent` bands, the described
    # `general` line, or the multiple-choice key's correct/incorrect bands.
    assert sorted(asked) == sorted(_item(band) for band in QUESTIONS), sorted(asked)
    for band, question in QUESTIONS.items():
        assert asked[_item(band)]["question"] == question, asked[_item(band)]
    (q2,) = [c for c in read["criteria"] if c["id"] == "C_Q2"]
    assert [level["descriptor"] for level in q2["score_levels"]] == ["", "", "", ""], (
        "an unanswered descriptor is served empty, never as the placeholder's text")

    # Approve with only the approver answered: refused, naming every open band's question.
    _answer(port, {"approved_by": APPROVER})
    refused = _approve(port)
    assert refused["refused"] is True and refused["dispatched"] is False, refused
    assert refused["what"] == f"{PACKAGE} was not published."
    assert refused["why"] == (
        "4 score levels do not yet say what earns them, and the grader needs that to choose "
        "between levels. Still to answer: " + " ".join(QUESTIONS.values())), refused["why"]
    assert refused["next_action"] == NEXT
    assert not store.package_path(PACKAGE).exists(), "a refused approval built a package"

    # Three answered: still refused, naming the one band left.
    _answer(port, {_item(band): ANSWERS[band] for band in ("none", "limited", "adequate")})
    still = _approve(port)
    assert still["refused"] is True, still
    assert still["why"] == (
        "1 score level does not yet say what earns it, and the grader needs that to choose "
        "between levels. Still to answer: " + QUESTIONS["full"]), still["why"]
    assert not store.package_path(PACKAGE).exists()

    # The last answer: the sentences stand in the bands' descriptors, and approval publishes.
    _answer(port, {_item("full"): ANSWERS["full"]})
    assert _q2_bands(draft) == ANSWERS
    assert not [p for p in draft_read(port)["draft"]["placeholders"]
                if p["item_id"].startswith("descriptor")], "a descriptor question still stands"

    approved = _approve(port)
    assert approved["refused"] is False, approved
    published = _published_bands(store)
    assert published["C_Q2"] == ANSWERS, published["C_Q2"]
    # The exempt bands published as the documents gave them: the key line's deterministic
    # pair with no descriptor, and each aspect's `absent` band likewise.
    assert set(published["C_Q4_key"]) == {"incorrect", "correct"}, published["C_Q4_key"]
    assert published["C_Q1_aspect1"]["absent"] == ""
    assert published["C_Q1_aspect2"]["absent"] == ""


# --- TC-AUTHOR-50 (served) ------------------------------------------------------------------


def test_tc_author_50_the_note_is_served_on_the_review_read_and_never_refuses(
        served_console, monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_AUTHOR_EVALUATIVE_TERMS", raising=False)
    _server, port, store, data_dir = served_console
    write_plain_bands_draft(data_dir / "authoring")
    before = draft_read(port)["draft"]
    assert before["notes"] == [], "the draft's own descriptors carry no evaluative word"

    _answer(port, {"approved_by": APPROVER,
                   **{_item(band): text for band, (text, _noted) in LINT_ANSWERS.items()}})

    read = draft_read(port)["draft"]
    (q2,) = [c for c in read["criteria"] if c["id"] == "C_Q2"]
    served = {level["name"]: level["note"] for level in q2["score_levels"]}
    assert served == {band: (_note(text) if noted else None)
                      for band, (text, noted) in LINT_ANSWERS.items()}, served
    assert read["notes"] == [
        {"criterion": "C_Q2", "question": "Q2", "level": band, "note": _note(text)}
        for band, (text, noted) in LINT_ANSWERS.items() if noted], read["notes"]

    approved = _approve(port)
    assert approved["refused"] is False, approved
    assert _published_bands(store)["C_Q2"] == {
        band: text for band, (text, _noted) in LINT_ANSWERS.items()}
