"""TC-E2E-11 — the mixed journey: one upload set carrying both formats.

Console redesign test plan §3.6: the same journey TC-E2E-08 names, with the upload set
being AF-21's — the `.docx` test, the `.txt` marking memo, and AF-14's content
re-encoded as `.txt`, uploaded TOGETHER ("both formats normalize together, and the
third document is AF-14's content re-encoded as `.txt` — the cross-format twin
TC-AUTHOR-32/TC-AUTHOR-38 assert against"). The preview must name every uploaded
document, the draft must merge them into ONE package, and the lifecycle then proceeds
as every other journey's.

The journey is driven TWICE into twin stores (the console's served SPA against the
CLI's `aeh` subcommands) and the oracle is the differential (TC-E2E-06's shape): the
stores must hold IDENTICAL tier rows under the §4.7 pairing, because the
console-authored draft is CLI-indistinguishable (ADR-45). The whole drive — the model
boundary, the capture world, the browser legs, the CLI legs, the pairing oracle — is
`tests.support.console_journeys.run_full_journey`; this module carries only what is
THIS journey's: the AF-21 spec, its replay pin, and the disclosed divergences below.

**The replay pin is the console-redesign capture pass's.** AF-21's recordings were
captured on 2026-10-14 by the committed script
(``scripts/capture_authoring_recordings.py`` — the command is documented in
``fixtures/F-AUTHOR/recordings/README.md``), keyed on
`tests.support.console_journeys.JOURNEY_AUTHORING_BUILD` — the build this account's
zero-retention routing actually serves (the corpus's older qwen pin no longer does;
the engine module's docstring carries the evidence). The request key hashes the build
id, so capture and replay pin the same constant.

**The disclosed capture divergence.** The captured draft asks the four grade
boundaries (`grades A`…`grades D`) even though the memo states them ("A: 8-9. B: 6-7.
C: 4-5. D: 0-3.") and AF-21's `expected.toml` declares `placeholders = []`: the
capture model read the memo's tables as boundaries not numerically stated, and the
extraction never invents one (FR-AUTHOR-08). The corpus contract and the capture
disagree; this journey answers the boundaries the way the memo's own lines read them
(A=8, B=6, C=4, D=0), reports the divergence to the coordinator, and does not edit the
corpus's generated `expected.toml` to match.

**The defect this journey found, fixed in this PR.** The console's authoring read
accepted PDFs only (``authoring_reads._SUPPORTED_SUFFIXES``), while FR-CONSOLE-50 and
the test plan require the other formats too — this journey's format gate raised the
finding in milliseconds, before any browser leg, with file:line evidence. The fix
routes `.docx`/`.txt` previews through the library's own intake entry (the same
normalization the draft job runs); its regression case is
`tests/unit/console/test_tc_ui_10_preview_formats.py` (`TC-UI-10` arm (d)), added to
`docs/design/test-plan.md` in this same PR. Issue #773 says "Written ahead of
implementation: no", so this test is NOT marked ``writtenahead`` and carries no
``WRITTEN_AHEAD_BLOCKERS`` entry.
"""

from __future__ import annotations

import pytest

from tests.support import console_journeys as cj

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
]

#: The journey's identity: AF-21's three-document mixed set, its own cohort and run
#: names, the console-redesign capture pass's build pin, and the disclosed boundary
#: answers (module docstring).
SPEC = cj.JourneySpec(
    label="TC-E2E-11",
    af_id="AF-21",
    documents=(
        "mus8-instruments-01-test.docx",
        "mus8-instruments-01-marking-memo.txt",
        "hist7-rome-01-test-and-grading.txt",
    ),
    cohort_id="coh-instruments-mixed",
    run_id="run-instruments-mixed",
    transcriber_build=cj.JOURNEY_AUTHORING_BUILD,
    judge_build=cj.JOURNEY_AUTHORING_BUILD,
    extra_answers={"grades A": "8", "grades B": "6", "grades C": "4", "grades D": "0"},
)


def test_tc_e2e_11_af21_mixed_full_journey(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The mixed journey, driven through the operator's surface and the CLI's, writes
    identical stores."""
    cj.run_full_journey(SPEC, tmp_path_factory, monkeypatch)
