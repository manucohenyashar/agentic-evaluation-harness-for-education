"""`TC-AUTHOR-32..42` — the intake unit suite's remainder (#768): the cases #753's fixture
halves do not carry.

#753 landed the *fixture halves* of TC-AUTHOR-32..38
(`tests/unit/author/test_tc_author_32_38_intake_fixtures.py` — one corpus fixture
normalized, its `expected.toml` outcome class asserted). This file is the other half of the
row: the fuller oracles and the service-level limbs the fixture halves deliberately left
out —

- **TC-AUTHOR-32**'s full format-independence oracle: not only equal block *texts* but
  equal stats and ordinals, and an accounted account of the one place the formats differ
  (the `.txt` side's inferred headings — warned, never silent).
- **TC-AUTHOR-35**'s boundary arm (`_b`): a UTF-8 `.txt` produces *no* fallback warning.
- **TC-AUTHOR-36**'s draft limb: the guessed outline still drafts.
- **TC-AUTHOR-37**'s whole seven-arm matrix **at rung 1** (the service refuses before any
  model call and writes nothing — the fixture half asserts the intake level only, and the
  oversize arm's file is knob-generated here).
- **TC-AUTHOR-38**'s rung-2 cross-format carry-over journey — `writtenahead`, see its
  docstring: the corpus holds no recordings for the AF-14/AF-21 document names (a capture
  pass never ran for the intake fixtures), and the plan's journey premise ("answer two
  placeholders") does not match the corpus's declared `resolved` outcome for AF-14.
- **TC-AUTHOR-39/40/41/42** whole: the from-scratch skeleton, the observer/cancel rhythm,
  intake purity, and the CT-AUTHOR-26 leak bound.

(TC-AUTHOR-33, TC-AUTHOR-34 and TC-AUTHOR-35/36's warning limbs live whole in the
fixture-half file, and TC-AUTHOR-32/37 each also have their fixture-half halves there —
unmarked, kept; one case per TC ID across the suite, not two — this file's TC-32 oracle
subsumes the fixture half's, and its TC-37 adds the rung-1 service limbs above the intake
level the fixture half pins.)

Two corpus-vs-implementation divergences were found while landing this suite and are
*disclosed findings*, not weakened assertions: AF-15's `image_not_carried` and AF-17's
`structure_guessed` (both §5.1-declared, both absent from the shipped intake) — the
fixture-half cases that assert them stay marked under a `command`-kind registry entry in
`tests/support/impl.py` naming exactly the behaviour that must arrive before they unmark.

Every case runs headless in-process under the autouse socket guard; the refusals make zero
provider calls (asserted with a call-counting double, `CT-AUTHOR-23`) and the normalizations
make none either (the four seams, headless driver).
"""

from __future__ import annotations

import importlib.util
import random
import re
import tomllib
from pathlib import Path

import pytest

import aeh.author as author
from aeh.author import (
    DOC_MAX_BYTES_ENV,
    AuthoringCancelled,
    DocumentRefusedError,
    document_text,
    normalize_document,
    normalize_documents,
)
from tests.support.author_vocabulary import (
    RECORDINGS,
    CountingProvider,
    chain_from_config,
    make_service,
    scripted_answers,
)

#: §4.6's seeded-per-concern constant (tests/conftest.py's `DEFAULT_SEED`): the ordering
#: sweep's shuffle seed, so a failure reproduces by hand.
ORDER_SEED = 20260101

#: CT-AUTHOR-26's bound, verbatim: no warning message or detail exceeds 200 characters.
WARNING_MAX_CHARS = 200

#: The oversize arm's exact sentence at the lowered knob: `_oversize_sentence(1024)` names
#: the limit in the knob's units ("1 KB"), the same sentence the design pins at 10 MB.
OVERSIZE_SENTENCE_1024 = ("This file is larger than 1 KB. Split it or remove pictures to "
                          "get it under the limit.")

#: The corpus-declared review answer for AF-14's sign-off item (its `expected.toml`'s
#: `[review.answers]`), and the carry-over's fingerprint rendering (the same hex-run shape
#: the clause suite's local regex uses).
TEACHER = "Sample-materials teacher"
_FINGERPRINT_RE = re.compile(r"\b[0-9a-fA-F]{8,64}\b")

#: The `BEGIN DOCUMENT:` markers the assembled request quotes per document — the needles the
#: TC-AUTHOR-38 capture guard scans the recordings for (`_quote_documents`' format).
_DOCX_NEEDLE = b"BEGIN DOCUMENT: hist7-rome-01-test-and-grading.docx"
_TXT_NEEDLE = b"BEGIN DOCUMENT: hist7-rome-01-test-and-grading.txt"

CASE = "TC-AUTHOR-32..42"

CORPUS = RECORDINGS.parent
GENERATOR = CORPUS / "build_authoring_fixtures.py"


def _expected(af_id: str) -> dict:
    return tomllib.loads((CORPUS / af_id / "expected.toml").read_text(encoding="utf-8"))


def _generator():
    """The corpus generator, loaded the way the TC-AUTHOR-28 census loads it."""
    spec = importlib.util.spec_from_file_location("build_authoring_fixtures", GENERATOR)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    return generator


def _service(make_fixture_provider) -> tuple:
    """The service with the recorded provider wrapped in a call-counting double: the
    recordings stay the only egress point and every case can assert how many model calls a
    refusal cost (`CT-AUTHOR-23`'s zero)."""
    provider = CountingProvider(make_fixture_provider(RECORDINGS))
    return make_service(author, chain_from_config(), provider), provider


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def _recordings_quote(needle: bytes) -> bool:
    return any(needle in path.read_bytes() for path in RECORDINGS.glob("*.json"))


# --------------------------------------------------------------------------------------------
# TC-AUTHOR-32 — representation is format-independent (the full oracle)
# --------------------------------------------------------------------------------------------

def test_tc_author_32_af21_pair_normalizes_to_the_same_blocks() -> None:
    """`TC-AUTHOR-32` (FR-AUTHOR-24 / CT-AUTHOR-21): the same content, `.docx` and `.txt`.

    The fixture half asserts the block-*text* sequences are equal; the full oracle adds what
    "equal blocks; `source_format` differs, nothing else does" means beyond the texts: the
    stats are equal, the ordinals are equal, and the one difference the formats can produce —
    the `.txt` side's *inferred* headings, where the `.docx` carries typed ones — is warned
    (`structure_guessed`), never silent. A representation that lost a block, mis-counted a
    table, or invented structure without saying so fails here.
    """
    docx_document = normalize_document(CORPUS / "AF-14" / _expected("AF-14")["documents"][0])
    txt_document = normalize_document(
        CORPUS / "AF-21" / _expected("AF-21")["documents"][-1])

    assert docx_document.source_format == "docx"
    assert txt_document.source_format == "txt"
    assert docx_document.stats == txt_document.stats, (
        f"{CASE}: the cross-format pair's stats differ — the representation is not "
        f"format-independent (docx {docx_document.stats} vs txt {txt_document.stats})"
    )
    assert [block.text for block in docx_document.blocks] == \
        [block.text for block in txt_document.blocks], (
        f"{CASE}: the cross-format pair's normalized block texts differ"
    )
    assert [block.ordinal for block in docx_document.blocks] == \
        [block.ordinal for block in txt_document.blocks], (
        f"{CASE}: the cross-format pair's block ordinals differ"
    )
    divergent = [(docx_block, txt_block)
                 for docx_block, txt_block in zip(docx_document.blocks, txt_document.blocks)
                 if docx_block.kind != txt_block.kind]
    for docx_block, txt_block in divergent:
        assert txt_block.kind == "heading" and txt_block.level is not None, (
            f"{CASE}: the formats disagree at ordinal {docx_block.ordinal} in a way no "
            f"structure inference explains: docx {docx_block.kind!r} vs txt "
            f"{txt_block.kind!r} — the representation is not format-independent"
        )
    if divergent:
        codes = [warning.code for warning in txt_document.warnings]
        assert "structure_guessed" in codes, (
            f"{CASE}: the txt twin's inferred headings produced no structure_guessed "
            f"warning — a guessed outline was presented as read"
        )


# --------------------------------------------------------------------------------------------
# TC-AUTHOR-35 boundary arm — UTF-8 is read as UTF-8, with no fallback warning
# --------------------------------------------------------------------------------------------

def test_tc_author_35_b_utf8_txt_normalizes_without_fallback_warning(
        tmp_path: Path) -> None:
    """`TC-AUTHOR-35` boundary arm (`_b`, FR-AUTHOR-26): a UTF-8 `.txt` gets no
    `encoding_fallback` warning — the warning names a *fallback*, and UTF-8 is not one.
    The accents must render intact either way."""
    source = tmp_path / "lang7-food-01-utf8-vocabulary.txt"
    source.write_text("Le menu: café, crêpe, déjà vu, élève, hôtel, très, août, génie.\n",
                      encoding="utf-8")
    document = normalize_document(source)
    assert document.source_format == "txt"
    fallbacks = [warning for warning in document.warnings
                 if warning.code == "encoding_fallback"]
    assert fallbacks == [], (
        f"{CASE}: a UTF-8 file was read with a fallback warning "
        f"({fallbacks[0].message!r}) — UTF-8 is not a fallback"
    )
    text = document_text(document)
    for word in ("café", "crêpe", "déjà", "élève", "hôtel", "très", "août", "génie"):
        assert word in text, f"{CASE}: the accented word {word!r} did not survive"


# --------------------------------------------------------------------------------------------
# TC-AUTHOR-36 — the guessed outline still drafts
# --------------------------------------------------------------------------------------------

def test_tc_author_36_af17_the_guessed_outline_still_drafts(
        tmp_path, make_fixture_provider) -> None:
    """`TC-AUTHOR-36` (FR-AUTHOR-26): AF-17's heading-less prose produces a draft.

    The plan's expected outcome has two limbs — the `structure_guessed` warning, and the
    draft still building. The warning limb is the fixture half's case
    (`test_tc_author_36_af17_structure_guessed`), which currently stands *marked* under a
    disclosed registry entry: the shipped intake emits no such warning for AF-17 (§5.1
    declares one), and that divergence is this suite's finding, not an assertion to weaken.
    This case is the other limb: the review walk asks the teacher to confirm the outline,
    which presupposes the draft got written at all — the run completes over the guessed
    outline and writes exactly the two artifacts, a parseable draft among them. Disclosed:
    the prose's *questions* cannot reach the draft yet — the corpus holds no recordings for
    the intake fixtures' document names (the capture pass never ran for them; all 80 quote
    only the PDF fixtures AF-01..13), so the reasoning steps find nothing to accept. That
    gap is TC-AUTHOR-38's registry entry's subject; the limb this case pins is that the
    guessed outline does not break the run.
    """
    service, _provider = _service(make_fixture_provider)
    name = _expected("AF-17")["documents"][0]
    result = service.draft([CORPUS / "AF-17" / name], tmp_path)
    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == [result.report_path.name, result.draft_path.name], (
        f"{CASE}: the AF-17 draft run wrote {written} — exactly the two artifacts are the "
        f"contract"
    )
    parsed = tomllib.loads(result.draft_path.read_text(encoding="utf-8"))
    assert "package" in parsed, (
        f"{CASE}: the draft built over the guessed outline is not a package spec: "
        f"{sorted(parsed)}"
    )
    report_text = result.report_path.read_text(encoding="utf-8")
    assert name in report_text, (
        f"{CASE}: the report's Documents section does not name AF-17's source"
    )


# --------------------------------------------------------------------------------------------
# TC-AUTHOR-37 — the refusal matrix at rung 1: refused before any model call, nothing written
# --------------------------------------------------------------------------------------------

#: The fixture-backed arms: the sentences come from the corpus's own declarations (the same
#: pin the census and the fixture-half case read), so this suite cannot drift from the
#: design table. The oversize arm is generated — its file is knob-sized, not committed.
def _refusal_arms() -> list[tuple[str, str, str]]:
    arms: list[tuple[str, str, str]] = []
    for af_id in ("AF-18", "AF-19", "AF-20"):
        expected = _expected(af_id)
        arms.append((af_id, expected["documents"][0], expected["refusal"]))
    adversarial = tomllib.loads(
        (CORPUS / "adversarial" / "expected.toml").read_text(encoding="utf-8"))
    for entry in adversarial["file"]:
        arms.append(("adversarial", entry["name"], entry["refusal"]))
    return arms


REFUSAL_ARMS = [*_refusal_arms(), ("knob", "oversize-1024.txt", OVERSIZE_SENTENCE_1024)]


@pytest.mark.parametrize(("fixture_dir", "name", "sentence"), REFUSAL_ARMS,
                         ids=[f"{directory}-{name}" for directory, name, _ in REFUSAL_ARMS])
def test_tc_author_37_refusals_cost_no_model_call_and_write_nothing(
        fixture_dir: str, name: str, sentence: str,
        tmp_path: Path, make_fixture_provider,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`TC-AUTHOR-37` (FR-AUTHOR-28 / CT-AUTHOR-23), rung 1: the service refuses each arm
    with the exact teacher sentence, **before any model call**, writing nothing.

    The fixture half asserts the intake level; the plan pins the rung-1 oracle on the
    service: a provider call-count double proves the refusal cost zero calls, and an empty
    output directory proves nothing was written. The oversize arm lowers
    `HARNESS_AUTHOR_DOC_MAX_BYTES` to 1024 (seam 3's knob) and expects the same sentence in
    the knob's units.
    """
    output = tmp_path / "out"
    output.mkdir()
    if fixture_dir == "knob":
        source = tmp_path / name
        source.write_bytes(b"x" * 2048)
        monkeypatch.setenv(DOC_MAX_BYTES_ENV, "1024")
    else:
        source = CORPUS / fixture_dir / name
    service, provider = _service(make_fixture_provider)
    with pytest.raises(DocumentRefusedError) as raised:
        service.draft([source], output)
    assert raised.value.sentence == sentence, (
        f"{CASE}: {fixture_dir}/{name} was refused, but not with the exact teacher "
        f"sentence the design table pins (got {raised.value.sentence!r})"
    )
    assert provider.calls == [], (
        f"{CASE}: {fixture_dir}/{name}'s refusal made {len(provider.calls)} model "
        f"call(s) — the matrix is decided by magic bytes and cheap local checks"
    )
    assert list(output.iterdir()) == [], (
        f"{CASE}: {fixture_dir}/{name}'s refusal left artifacts in the output directory"
    )


# --------------------------------------------------------------------------------------------
# TC-AUTHOR-38 — carry-over survives a format change (rung 2; writtenahead)
# --------------------------------------------------------------------------------------------

@pytest.mark.writtenahead
def test_tc_author_38_carry_over_survives_a_format_change(
        tmp_path, make_fixture_provider, network_guard) -> None:
    """`TC-AUTHOR-38` (FR-AUTHOR-23 across formats / RS-03): draft AF-14's `.docx`, answer
    the review, re-draft from AF-21's `.txt` twin — the answer carries, provisional.

    `writtenahead`, held outside `TEST_CMD` by a `command`-kind registry entry whose probe
    is the capture pass this case waits on: the corpus holds **no recordings** for either
    twin's document name — all 80 recordings quote only the PDF fixtures AF-01..13, because
    a capture pass never ran for the intake fixtures — so this journey cannot replay yet,
    and its first failure must say exactly that.

    Two further premise conflicts, disclosed for the unmarking reconcile (the TC-AUTHOR-27
    precedent — the case body reconciles to the shipped vocabulary, the plan's wording
    stands as intent):

    - **Package id embeds the source extension.** The carry-over reads the prior report by
      package id, and the fallback id is the slug of the source *filename* — so a
      cross-format re-draft of the same stem computes a different id and the lookup cannot
      fire as written. The plan's journey is the requirement; if the shipped id rule
      survives review, this case is the one that names the gap.
    - **AF-14's corpus outcome is `resolved`**, not the plan's "answer two placeholders"
      walk: the corpus-declared answer surface is the single `approved_by` sign-off, so the
      boundary arm below encodes "carries only the matching item" the way the corpus
      supports it — the still-matching answer carries the re-draft, and a corrupted
      fingerprint (the TC-AUTHOR-27 variant-3 technique) is dropped and accounted.

    The fingerprint the carry-over matches is defined over the normalized block text
    (§3.1.1), so it must be format-independent — that is this journey's point, and the
    TC-AUTHOR-32 oracle above is what makes the premise sound.
    """
    # --- the capture guard: the red that names the missing capture pass ------------------------
    missing = [needle for needle, found in (
        (_DOCX_NEEDLE, _recordings_quote(_DOCX_NEEDLE)),
        (_TXT_NEEDLE, _recordings_quote(_TXT_NEEDLE)),
    ) if not found]
    assert not missing, (
        "TC-AUTHOR-38: the corpus holds no recordings for the intake fixtures' twin "
        f"documents (missing: {', '.join(n.decode() for n in missing)}) — run the capture "
        "pass for AF-14's and AF-21's document names, then remove the writtenahead marker"
    )

    service, _provider = _service(make_fixture_provider)
    af14_name = _expected("AF-14")["documents"][0]
    af21_name = _expected("AF-21")["documents"][-1]

    # --- the journey: draft .docx, review, re-draft from the .txt twin --------------------------
    journey = tmp_path / "journey"
    journey.mkdir()
    first = service.draft([CORPUS / "AF-14" / af14_name], journey)
    first_review = service.review(
        draft_path=first.draft_path,
        answers=scripted_answers(author, first.draft_path.read_text(encoding="utf-8"),
                                 {"approved_by": TEACHER}))
    assert first_review.ready, (
        f"{CASE}: TC-AUTHOR-38's setup: AF-14's scripted review must reach ready"
    )
    second = service.draft([CORPUS / "AF-21" / af21_name], journey)
    carried_text = second.draft_path.read_text(encoding="utf-8")
    carried_report = second.report_path.read_text(encoding="utf-8")
    assert TEACHER in carried_text, (
        f"{CASE}: the answer recorded against the .docx draft is carried into the .txt "
        f"re-draft (FR-AUTHOR-23 across formats)"
    )
    assert "Provisional" in carried_text, (
        f"{CASE}: the carried answer is provisional in the re-draft, not confirmed "
        f"(FR-AUTHOR-23)"
    )
    reconfirm = service.review(draft_path=second.draft_path, answers=[])
    assert not reconfirm.ready, (
        f"{CASE}: a carried-over answer must not count as confirmed at review "
        f"(FR-AUTHOR-23)"
    )
    assert any("approved_by" in str(item) for item in reconfirm.remaining), (
        f"{CASE}: the carried item must remain to confirm: {reconfirm.remaining}"
    )
    item_lines = [line for line in carried_report.splitlines() if "approved_by" in line]
    assert any(_FINGERPRINT_RE.findall(line) for line in item_lines), (
        f"{CASE}: the carried answer carries a content fingerprint against the "
        f"regenerated .txt content (FR-AUTHOR-23) — the fingerprint is format-independent"
    )

    # --- the boundary: only the matching item carries -------------------------------------------
    boundary = tmp_path / "boundary"
    boundary.mkdir()
    prior = service.draft([CORPUS / "AF-14" / af14_name], boundary)
    prior_report = prior.report_path.read_text(encoding="utf-8")
    prints = sorted({hex_run for line in
                     (line for line in prior_report.splitlines()
                      if "approved_by" in line)
                     for hex_run in _FINGERPRINT_RE.findall(line)})
    assert prints, f"{CASE}: the prior report's answer record carries a fingerprint"
    corrupted = prior_report
    for hex_run in prints:  # corrupt every fingerprint run on the item's lines
        corrupted = corrupted.replace(hex_run, "0" * len(hex_run))
    assert corrupted != prior_report, f"{CASE}: the corruption must actually change it"
    (boundary / prior.report_path.name).write_text(corrupted, encoding="utf-8")
    redraft = service.draft([CORPUS / "AF-21" / af21_name], boundary)
    boundary_text = redraft.draft_path.read_text(encoding="utf-8")
    boundary_report = redraft.report_path.read_text(encoding="utf-8")
    assert TEACHER not in boundary_text, (
        f"{CASE}: a fingerprint-mismatched answer is not carried — the content the answer "
        f"was given against has moved (FR-AUTHOR-23)"
    )
    assert TEACHER in boundary_report, (
        f"{CASE}: the mismatched record is named dropped in the new report — the recorded "
        f"answer is accounted for, never silently gone (FR-AUTHOR-23)"
    )
    network_guard.assert_no_network()


# --------------------------------------------------------------------------------------------
# TC-AUTHOR-39 — the from-scratch skeleton
# --------------------------------------------------------------------------------------------

def test_tc_author_39_from_scratch_skeleton_is_empty_and_created_empty(
        tmp_path, make_fixture_provider) -> None:
    """`TC-AUTHOR-39` (FR-AUTHOR-29): `draft_from_scratch` writes an empty skeleton and a
    created-empty report, and no model call rides any seam.

    The draft holds zero questions and zero criteria — and no placeholder anywhere, because
    nothing is missing yet. The report is marked created empty and its Next step names the
    console's editor (`FROM_SCRATCH_NEXT_STEP`), not the review walk.
    """
    provider = CountingProvider(make_fixture_provider(RECORDINGS))
    service = make_service(author, chain_from_config(), provider)
    result = service.draft_from_scratch(tmp_path, "Roman Empire Test")
    assert result.placeholders == 0 and result.resolved == 0 \
        and result.unresolved == 0 and result.models_used == (), (
        f"{CASE}: the from-scratch result is not the empty skeleton's tallies: {result}"
    )
    draft_text = result.draft_path.read_text(encoding="utf-8")
    parsed = tomllib.loads(draft_text)
    assert parsed["question"] == [] and parsed["criterion"] == [], (
        f"{CASE}: the skeleton is not empty: question={parsed['question']!r} "
        f"criterion={parsed['criterion']!r}"
    )
    assert "<<PLACEHOLDER:" not in draft_text, (
        f"{CASE}: the skeleton carries a placeholder, but nothing is missing yet"
    )
    report_text = result.report_path.read_text(encoding="utf-8")
    assert "created empty" in report_text, (
        f"{CASE}: the report is not marked created empty"
    )
    assert "open it in the console and add questions and grading points" in report_text, (
        f"{CASE}: the report's Next step does not name the console's editor"
    )
    assert provider.calls == [], (
        f"{CASE}: the skeleton cost {len(provider.calls)} model call(s) — it is "
        f"deterministic and rides no seam"
    )


# --------------------------------------------------------------------------------------------
# TC-AUTHOR-40 — the observer and the cancel, at the step boundaries
# --------------------------------------------------------------------------------------------

_AUTHORING_STAGES = {"reading documents", "drafting", "reviewing", "writing draft"}


def _cancelled_from(checks: list[int], at: int):
    """A cancel double: false for the first `at` checks, true from then on — the boundary
    the cancellation lands on is the `at`-th check the service makes."""
    def cancel() -> bool:
        checks.append(1)
        return len(checks) > at
    return cancel


@pytest.mark.parametrize("arm", ["a-observer", "b-cancel-between-steps",
                                 "c-cancel-never-true"])
def test_tc_author_40_observer_and_cancel_at_step_boundaries(
        arm: str, tmp_path, make_fixture_provider) -> None:
    """`TC-AUTHOR-40` (FR-AUTHOR-30 / CT-AUTHOR-24/25), three arms.

    (a) The observer sees every stage of the run, `done` monotone within each stage, and
    the write stage closes at its full denominator. (b) A cancel that turns true at the
    first step boundary stops the run with `AuthoringCancelled` and leaves the output
    directory byte-for-byte as the prior valid draft left it. (c) A cancel checked but
    never true changes nothing: the run completes normally.
    """
    service, _provider = _service(make_fixture_provider)
    documents = [CORPUS / "AF-17" / _expected("AF-17")["documents"][0]]
    if arm == "a-observer":
        seen: list[author.AuthoringProgress] = []
        result = service.draft(documents, tmp_path, observer=seen.append)
        stages = [progress.stage for progress in seen]
        assert stages, f"{CASE}: the observer heard nothing"
        assert set(stages) <= _AUTHORING_STAGES, (
            f"{CASE}: the observer heard a stage outside the closed set: {stages}"
        )
        assert stages[0] == "reading documents", (
            f"{CASE}: the first boundary reported {stages[0]!r}, not the read"
        )
        assert stages[-1] == "writing draft", (
            f"{CASE}: the last boundary reported {stages[-1]!r}, not the write"
        )
        within: dict[str, list[int]] = {}
        for progress in seen:
            within.setdefault(progress.stage, []).append(progress.done)
        for stage, dones in within.items():
            assert dones == sorted(dones), (
                f"{CASE}: stage {stage!r} reported done {dones} — `done` decreased "
                f"within the stage (CT-AUTHOR-25)"
            )
        writes = [progress for progress in seen if progress.stage == "writing draft"]
        assert writes[-1].total == 2 and writes[-1].done == 2, (
            f"{CASE}: the write stage closed at {writes[-1].done}/{writes[-1].total}, "
            f"not 2/2 — the two artifacts are the denominator"
        )
        assert result.draft_path.exists() and result.report_path.exists()
    elif arm == "b-cancel-between-steps":
        service.draft_from_scratch(tmp_path, "Prior Draft")
        before = _snapshot(tmp_path)
        checks: list[int] = []
        with pytest.raises(AuthoringCancelled):
            service.draft(documents, tmp_path,
                          cancel=_cancelled_from(checks, at=1))
        assert checks, f"{CASE}: the cancel was never consulted"
        assert _snapshot(tmp_path) == before, (
            f"{CASE}: the cancelled run changed the output directory — the prior valid "
            f"draft must stand untouched byte-for-byte (CT-AUTHOR-24)"
        )
    else:
        result = service.draft(documents, tmp_path, cancel=lambda: False)
        assert isinstance(result, author.DraftResult), (
            f"{CASE}: a never-true cancel changed the run's outcome"
        )
        assert result.draft_path.exists() and result.report_path.exists(), (
            f"{CASE}: the run with a never-true cancel wrote no artifacts"
        )


# --------------------------------------------------------------------------------------------
# TC-AUTHOR-41 — intake purity (and CT-AUTHOR-21's input-order independence)
# --------------------------------------------------------------------------------------------

def test_tc_author_41_intake_is_pure_and_order_independent(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`TC-AUTHOR-41` (CT-AUTHOR-22): intake is a pure function of the bytes.

    The same fixture normalizes twice to a deep-equal `NormalizedDocument` (the frozen value
    type's `==` is the deep comparison), and equal again after a locale shuffle in-process —
    normalization must not consult ambient locale state. The acceptance criteria's ordering
    property rides the same purity: AF-21's three documents normalize to the same
    per-document results under twenty seeded-random input orders (the batch entry is a
    function of the *set*, its results aligned to the input order).
    """
    docx_path = CORPUS / "AF-14" / _expected("AF-14")["documents"][0]
    txt_path = CORPUS / "AF-16" / _expected("AF-16")["documents"][0]
    for path in (docx_path, txt_path):
        first = normalize_document(path)
        assert first == normalize_document(path), (
            f"{CASE}: normalizing {path.name} twice produced different documents — "
            f"intake is not pure"
        )
        for locale_name in ("de_DE.UTF-8", "fr_FR.UTF-8", "C"):
            monkeypatch.setenv("LC_ALL", locale_name)
            monkeypatch.setenv("LANG", locale_name)
            assert normalize_document(path) == first, (
                f"{CASE}: {path.name} normalized differently under LC_ALL="
                f"{locale_name} — intake consulted the ambient locale"
            )
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LANG", raising=False)

    names = list(_expected("AF-21")["documents"])
    paths = [CORPUS / "AF-21" / name for name in names]
    batch = normalize_documents(paths)
    assert tuple(document.source_name for document in batch) == tuple(names), (
        f"{CASE}: the batch entry's results are not aligned to the input order"
    )
    baseline = {document.source_name: document for document in batch}
    assert len(baseline) == len(names), f"{CASE}: the batch lost a document"
    shuffler = random.Random(ORDER_SEED)
    for _ in range(20):
        order = list(names)
        shuffler.shuffle(order)
        result = {document.source_name: document
                  for document in normalize_documents(
                      [CORPUS / "AF-21" / name for name in order])}
        assert result == baseline, (
            f"{CASE}: the batch's results depend on the input order — a document "
            f"normalized differently when the set was shuffled"
        )


# --------------------------------------------------------------------------------------------
# TC-AUTHOR-42 — a warning leaks at most a sentence (CT-AUTHOR-26)
# --------------------------------------------------------------------------------------------

def _truncation_fixture(generator) -> bytes:
    """A synthetic `.docx`: two long paragraphs (>200 chars) — one beside the image, one
    beside the equation — so a warning that quotes an anchor is quoting text long enough
    to leak if the truncation boundary were wrong. The equation is the anchor whose
    `equation_not_carried` warning is the shipped intake's own behaviour (the
    `image_not_carried` limb is TC-AUTHOR-34's divergence, held marked, not re-asserted
    here)."""
    long_a = ("Describe what the ammeter reads when the switch is closed and explain why "
              "the reading changes as the variable resistor is turned, naming each "
              "component you would include in the circuit diagram you draw for the "
              "examiner, and say where the fuse belongs. ")
    long_b = ("Explain, in sentences the marker can follow, how the readings in your table "
              "show whether the lamp obeys Ohm's law, and what would change if the cell "
              "were replaced by one with a higher electromotive force but the same "
              "internal resistance as before. ")
    blocks = [
        ("heading", 1, "SCI9-TRUNCATION-01 - WARNING BOUNDARY TEST"),
        ("paragraph", long_a + long_a),
        ("image",),
        ("paragraph", long_b + long_b),
        ("equation", "F = m × a"),
    ]
    return generator._docx_document(blocks)


def test_tc_author_42_warnings_leak_at_most_a_sentence(tmp_path: Path) -> None:
    """`TC-AUTHOR-42` (CT-AUTHOR-26): every warning's message and detail stays inside the
    200-character bound and never carries the full document text.

    Two limbs: the corpus scan (every AF-14..21 document's warnings), and the truncation
    boundary — a synthetic document whose long paragraphs stand right beside an image and
    an equation, so the equation warning's anchor text is long enough to leak. A warning
    that outgrew the bound, or one that swallowed a paragraph, fails here.
    """
    corpus_documents = [normalize_document(CORPUS / af_id / name)
                        for af_id in ("AF-14", "AF-15", "AF-16", "AF-17", "AF-21")
                        for name in _expected(af_id)["documents"]]
    generator = _generator()
    synthetic = normalize_bytes(_truncation_fixture(generator),
                                "sci9-truncation-01.docx", tmp_path)
    codes = [warning.code for warning in synthetic.warnings]
    assert "equation_not_carried" in codes, (
        f"{CASE}: the equation beside the long paragraph produced no warning — the "
        f"truncation limb has no anchor to bound"
    )
    for document in (*corpus_documents, synthetic):
        full_text = document_text(document)
        for warning in document.warnings:
            for field in (warning.message, warning.detail):
                assert len(field) <= WARNING_MAX_CHARS, (
                    f"{CASE}: {document.source_name}'s {warning.code} warning's text is "
                    f"{len(field)} characters — the bound is {WARNING_MAX_CHARS}: "
                    f"{field!r}"
                )
                assert not full_text or full_text not in field, (
                    f"{CASE}: {document.source_name}'s {warning.code} warning carries "
                    f"the full document text: {field!r}"
                )
    long_b = [block.text for block in synthetic.blocks if block.kind == "paragraph"][-1]
    for warning in synthetic.warnings:
        assert long_b not in warning.message and long_b not in warning.detail, (
            f"{CASE}: the {warning.code} warning swallowed the long paragraph beside the "
            f"equation — the anchor was not truncated"
        )


def normalize_bytes(data: bytes, name: str, tmp_path: Path):
    """`normalize_document` over in-memory bytes: the synthetic fixtures are written to the
    test's tmp directory, never committed."""
    source = tmp_path / name
    source.write_bytes(data)
    return normalize_document(source)
