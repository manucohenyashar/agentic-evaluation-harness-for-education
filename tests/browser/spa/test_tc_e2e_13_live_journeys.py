"""TC-E2E-13 — the nightly live journeys: the four acceptance journeys against the
REAL provider.

Console redesign test plan §3.6: "the four journeys against the real provider; skips
cleanly without the key; asserts the same user-visible behavior; no recording write."
The four are the same formats the recorded journeys walk — single `.docx` (AF-14),
single `.txt` (AF-17), single PDF (AF-01), mixed pair (AF-21) — over the SAME console
drive, `_serve_and_drive`, so a screen the recorded journeys assert is asserted here
against the live provider's own outputs: the wizard's stage flips, the review walk's
declared answers, the editor's structured edit, the amendment's required-reason
refusal and its history, the four exports, TC-CONSOLE-74's raw-vocabulary scan over
every visited screen, and CT-PROV-15's no-egress check over the browser's requests.

**The standing live-test rules, and where each is enforced.** The key gate runs
FIRST (the TC-AUTHOR-31 rule — a box with no key spends nothing): `_require_live_key`
skips, naming the nightly tier, when `OPENROUTER_API_KEY` is unset, before any gate,
any browser, any byte of model spend. The fixture binding is DELETED from the
environment, not merely never set — with `HARNESS_FIXTURE_DIR` absent,
`runtime._provider_for`'s declared mapping resolves the production
`OpenRouterProvider.enforcing_zero_retention()` at every seam, so no boundary can
replay and none can record — and the committed recordings corpus is fingerprinted
(path, size, sha256) before the pass and checked after it, in a `finally`, so even a
mid-journey failure reports contamination. The corpus's own README documents capture;
nothing here captures.

**What is deliberately different from the recorded journeys, and why.** The capture
leg and the CLI twin are absent: the capture world exists to produce the recordings
the twins replay, and the differential asserts the console-authored draft is
CLI-indistinguishable (ADR-45) over byte-identical replays — a property a
non-deterministic live model cannot underwrite, since two live drafts are two model
outputs, not one. So there is ONE live draft per journey — the browser's own — and
the journey reads its question id and edit text off the draft the browser just
committed, and writes the papers from the shape of the package the browser's own
approve leg published (the run grades papers consistent with the very package that
grades them). The oracle is what the plan names for this case: the SAME user-visible
assertions, sampled nightly — the plan's own honest limit on what the recorded path
proves ("live-model behavior ... is only nightly-sampled. This story is that
sampling").

**A live failure is a finding, never papered over.** No assertion is widened for the
live tier: a run that does not complete, a draft asking what the corpus's declared
contract does not declare, a refusal the recorded path never produced — each fails
here, naming what happened (the score trace, the pause reason, the screen), exactly
as the recorded journeys would. The one disclosed deviation from the recorded specs'
pins: the live journeys all ride `JOURNEY_AUTHORING_BUILD` — including the PDF
journey, whose committed recordings pin the corpus's older qwen build, which this
account's zero-retention routing no longer serves at all (the engine module's
docstring carries the evidence); a live pin names a build the live provider can
actually serve, not a replay key.

Issue #775 says "Written ahead of implementation: no" — the recorded journeys (#773,
PR #800) exist — so nothing here is marked ``writtenahead`` and no
``WRITTEN_AHEAD_BLOCKERS`` entry is added. The markers are the established live
convention (`integration`, `live`, `slow` — TC-AUTHOR-31's set), deliberately NOT the
``browser`` marker: the plan's browser tier (§4.7) runs ``-m browser`` on every push,
and a live-marked browser case selected there would spend the nightly tier's budget
on every push; ``-m live`` — the nightly tier's own selector — is what picks these
up. The ``live`` marker keeps all four out of the fast tier (`scripts/test.sh`);
they run only where the key is set, nightly.
"""

from __future__ import annotations

import pytest

from tests.support import console_journeys as cj

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live,
    pytest.mark.slow,
]

#: The live journeys' shared build pin: the build this account's zero-retention
#: routing actually serves — the same build the console-redesign capture pass rode,
#: and NOT the corpus's older qwen pin (module docstring).
LIVE_BUILD = cj.JOURNEY_AUTHORING_BUILD


def _live_spec(label: str, af_id: str, documents: tuple[str, ...], cohort: str,
               run: str, *, expected_warning: str | None = None,
               extra_answers: dict[str, str] | None = None) -> cj.JourneySpec:
    """One live journey's identity: the recorded journey's fixture and ids under
    live-suffixed names, the live build pin, and the corpus's declared contract
    (warnings and review answers) unchanged."""
    return cj.JourneySpec(
        label=label,
        af_id=af_id,
        documents=documents,
        cohort_id=cohort,
        run_id=run,
        transcriber_build=LIVE_BUILD,
        judge_build=LIVE_BUILD,
        expected_warning=expected_warning,
        extra_answers=extra_answers or {},
    )


#: TC-E2E-13's four journeys, in the recorded family's order (TC-E2E-08..11).
DOCX_SPEC = _live_spec(
    "TC-E2E-13 (docx)", "AF-14", ("hist7-rome-01-test-and-grading.docx",),
    "coh-rome-docx-live", "run-rome-docx-live")
TXT_SPEC = _live_spec(
    "TC-E2E-13 (txt)", "AF-17", ("hist6-great-fire-01-prose-test.txt",),
    "coh-great-fire-live", "run-great-fire-live",
    expected_warning=(
        "We guessed where the headings are — check the outline on the next screen."),
    extra_answers={"grades D": "0"})
PDF_SPEC = _live_spec(
    "TC-E2E-13 (pdf)", "AF-01", ("hist7-rome-01-test-and-grading.pdf",),
    "coh-rome-pdf-live", "run-rome-pdf-live")
MIXED_SPEC = _live_spec(
    "TC-E2E-13 (mixed)", "AF-21",
    (
        "mus8-instruments-01-test.docx",
        "mus8-instruments-01-marking-memo.txt",
        "hist7-rome-01-test-and-grading.txt",
    ),
    "coh-instruments-mixed-live", "run-instruments-mixed-live",
    extra_answers={"grades A": "8", "grades B": "6", "grades C": "4",
                   "grades D": "0"})


def test_tc_e2e_13_live_docx_journey(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The .docx journey against the real provider — the same user-visible drive as
    TC-E2E-08, skipping cleanly without the key and writing no recording."""
    cj.run_live_journey(DOCX_SPEC, tmp_path_factory, monkeypatch)


def test_tc_e2e_13_live_txt_journey(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The .txt journey against the real provider — the same user-visible drive as
    TC-E2E-09, outline-guessing warning and boundary answer included."""
    cj.run_live_journey(TXT_SPEC, tmp_path_factory, monkeypatch)


def test_tc_e2e_13_live_pdf_journey(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The PDF journey against the real provider — the same user-visible drive as
    TC-E2E-10, under the live build pin (module docstring)."""
    cj.run_live_journey(PDF_SPEC, tmp_path_factory, monkeypatch)


def test_tc_e2e_13_live_mixed_journey(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The mixed-pair journey against the real provider — the same user-visible drive
    as TC-E2E-11, the merged grade tables' declared boundaries included."""
    cj.run_live_journey(MIXED_SPEC, tmp_path_factory, monkeypatch)
