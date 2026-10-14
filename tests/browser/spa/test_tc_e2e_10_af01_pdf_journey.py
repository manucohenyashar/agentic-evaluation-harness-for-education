"""TC-E2E-10 — the PDF journey: the same lifecycle over AF-01's single paper PDF.

Console redesign test plan §3.6: the same journey TC-E2E-08 names, with the document
being AF-01's single `hist7-rome-01-test-and-grading.pdf` — "Fresh store → create class
(typed) → cohort → upload → preview → draft (recorded) → placeholders answered →
editor edit → approve → upload papers (world fixtures) → preflight → start run →
progress → results → justification → override with reason → exports (CSV + workbook +
readable PDF + backup)".

The journey is driven TWICE into twin stores (the console's served SPA against the
CLI's `aeh` subcommands) and the oracle is the differential (TC-E2E-06's shape): the
stores must hold IDENTICAL tier rows under the §4.7 pairing, because the
console-authored draft is CLI-indistinguishable (ADR-45). The whole drive — the model
boundary, the capture world, the browser legs, the CLI legs, the pairing oracle — is
`tests.support.console_journeys.run_full_journey`; this module carries only what is
THIS journey's: the AF-01 spec and its replay pin.

**The replay pin is the corpus's own.** AF-01's recordings are the F-AUTHOR corpus's
original capture (issue #690's pass), keyed on the qwen builds
`console_redesign_world.RECORDED_TRANSCRIBER` / `RECORDED_JUDGE` — the recorded dev-ci
profile's single `[[panel]]` judge with no escalation section. Those builds can no
longer serve this account live (the zero-retention routing's "Model bloc"; the engine
module's docstring), but a replay asks no endpoint of them — the recordings ARE the
replies — so this journey pins exactly what its recordings were captured under. The
request key hashes the build id, so any other pin would miss.

**No disclosed capture divergence.** AF-01's committed capture satisfies its contract
exactly (`expected.toml`: resolved, `placeholders = []`, the `approved_by` sign-off
only), so the review walk answers the corpus's declared answers and nothing more.
The PDF format itself needs no warning oracle: the corpus declares none for AF-01, and
the console's upload read carries PDFs (`authoring_reads._SUPPORTED_SUFFIXES`).

Issue #773 says "Written ahead of implementation: no" and every dependency is merged,
so this test is NOT marked ``writtenahead`` and carries no ``WRITTEN_AHEAD_BLOCKERS``
entry: it must pass when its PR merges. Its gates still fail in milliseconds — BEFORE
any browser is launched or store built — and name what they are checking.
"""

from __future__ import annotations

import pytest

from tests.support import console_journeys as cj
from tests.support import console_redesign_world as crw

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
]

#: The journey's identity: AF-01's single PDF, its own cohort and run names, and the
#: corpus's own capture pin (module docstring) — NOT the AF-14..21 build the other
#: journeys' recordings were captured under.
SPEC = cj.JourneySpec(
    label="TC-E2E-10",
    af_id="AF-01",
    documents=("hist7-rome-01-test-and-grading.pdf",),
    cohort_id="coh-rome-pdf",
    run_id="run-rome-pdf",
    transcriber_build=crw.RECORDED_TRANSCRIBER,
    judge_build=crw.RECORDED_JUDGE,
)


def test_tc_e2e_10_af01_pdf_full_journey(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The PDF journey, driven through the operator's surface and the CLI's, writes
    identical stores."""
    cj.run_full_journey(SPEC, tmp_path_factory, monkeypatch)
