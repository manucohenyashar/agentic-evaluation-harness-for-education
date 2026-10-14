"""TC-E2E-09 — the .txt journey: the same lifecycle over AF-17's single plain-text paper.

Console redesign test plan §3.6 (line 407): the same journey TC-E2E-08 names, with the
document being AF-17's single `.txt` — "Fresh store → create class (typed) → cohort →
upload AF-14 → preview → draft (recorded) → placeholders answered → editor edit →
approve → upload papers (world fixtures) → preflight → start run → progress → results →
justification → override with reason → exports (CSV + workbook + readable PDF + backup)".
Here the document is AF-17's one `hist6-great-fire-01-prose-test.txt`, and the format's
own oracle joins the walk: the `.txt` intake's `structure_guessed` warning — the corpus
declares it (`expected.toml`'s `warnings`) — surfaces in the wizard's stage 2 as the
preview's own warning card, in the teacher's language.

The journey is driven TWICE into twin stores (the console's served SPA against the
CLI's `aeh` subcommands) and the oracle is the differential (TC-E2E-06's shape): the
stores must hold IDENTICAL tier rows under the §4.7 pairing, because the
console-authored draft is CLI-indistinguishable (ADR-45). The whole drive — the model
boundary, the capture world, the browser legs, the CLI legs, the pairing oracle — is
`tests.support.console_journeys.run_full_journey`; this module carries only what is
THIS journey's: the AF-17 spec, the `.txt` format oracle, and the disclosed divergences
below.

**Disclosed divergences** (each deliberate, each named in the PR; the shared ones are
the engine module's):

* The stage-2 preview must carry AF-17's declared `structure_guessed` warning verbatim
  — the format oracle this journey exists to carry.
* One review answer is journey-disclosed rather than corpus-declared: the captured
  draft (the only kind there is — the recordings replay it byte-exactly) asks
  `grades D` in addition to `approved_by`, because the capture model read "a D is less"
  as no stated numeric boundary and the extraction never invents one (FR-AUTHOR-08),
  where AF-17's `expected.toml` declares `placeholders = []`. The corpus contract and
  the capture disagree; this journey answers the boundary the way the document's own
  sentence reads it (a D is everything below C's floor of two, so the minimum mark is
  0), reports the divergence to the coordinator, and does not edit the corpus's
  generated `expected.toml` to match.

Issue #773 says "Written ahead of implementation: no" and every dependency is merged,
so this test is NOT marked ``writtenahead`` and carries no ``WRITTEN_AHEAD_BLOCKERS``
entry: it must pass when its PR merges. Its gates still fail in milliseconds — BEFORE
any browser is launched or store built — and name what they are checking. One gate
guards the defect this journey family found and this PR fixes: the console's preview
read once accepted PDFs only (``authoring_reads._SUPPORTED_SUFFIXES``); the fix routes
`.docx`/`.txt` through the library's own intake entry, and the gate now asserts the
read carries every format the journey uploads — losing one again fails here, before
any browser leg (regression case:
``tests/unit/console/test_tc_ui_10_preview_formats.py``). The F-AUTHOR capture pass
for AF-17 ran (the recordings are committed; ``scripts/capture_authoring_recordings.py``
is the command).
"""

from __future__ import annotations

import pytest

from tests.support import console_journeys as cj
from tests.support.author_vocabulary import RECORDINGS

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
]

#: The journey's identity: AF-17's single `.txt`, its own cohort and run names, and the
#: build pin its committed recordings were captured under (the engine module's
#: docstring explains why that is not the corpus's older qwen pin).
SPEC = cj.JourneySpec(
    label="TC-E2E-09",
    af_id="AF-17",
    documents=("hist6-great-fire-01-prose-test.txt",),
    cohort_id="coh-great-fire",
    run_id="run-great-fire",
    transcriber_build=cj.JOURNEY_AUTHORING_BUILD,
    judge_build=cj.JOURNEY_AUTHORING_BUILD,
    expected_warning=(
        "We guessed where the headings are — check the outline on the next screen."),
    extra_answers={"grades D": "0"},
)


def test_tc_e2e_09_af17_txt_full_journey(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The .txt journey, driven through the operator's surface and the CLI's, writes
    identical stores."""
    assert RECORDINGS.is_dir()
    cj.run_full_journey(SPEC, tmp_path_factory, monkeypatch)
