"""TC-E2E-08 — the .docx journey: the full lifecycle over AF-14's single document.

Console redesign test plan §3.6: "Fresh store → create class (typed) → cohort → upload
AF-14 → preview → draft (recorded) → placeholders answered → editor edit → approve →
upload papers (world fixtures) → preflight → start run → progress → results →
justification → override with reason → exports (CSV + workbook + readable PDF +
backup)" — the journey the other format journeys (TC-E2E-09/10/11) re-run with their
format's document. Here the document is AF-14's one
`hist7-rome-01-test-and-grading.docx`, whose rubric table is carried as table blocks
(TC-AUTHOR-33).

The journey is driven TWICE into twin stores (the console's served SPA against the
CLI's `aeh` subcommands) and the oracle is the differential (TC-E2E-06's shape): the
stores must hold IDENTICAL tier rows under the §4.7 pairing, because the
console-authored draft is CLI-indistinguishable (ADR-45). The whole drive — the model
boundary, the capture world, the browser legs, the CLI legs, the pairing oracle — is
`tests.support.console_journeys.run_full_journey`; this module carries only what is
THIS journey's: the AF-14 spec and its replay pin.

**The replay pin is the console-redesign capture pass's.** AF-14's recordings were
captured on 2026-10-14 by the committed script
(``scripts/capture_authoring_recordings.py`` — the command is documented in
``fixtures/F-AUTHOR/recordings/README.md``), keyed on
`tests.support.console_journeys.JOURNEY_AUTHORING_BUILD` — the build this account's
zero-retention routing actually serves (the corpus's older qwen pin no longer does;
the engine module's docstring carries the evidence). The request key hashes the build
id, so capture and replay pin the same constant.

**No disclosed capture divergence.** AF-14's capture satisfies its contract exactly
(`expected.toml`: resolved, `placeholders = []`, the `approved_by` sign-off only, no
declared warnings), so the review walk answers the corpus's declared answers and
nothing more.

**The honest open finding.** The console's authoring read accepts PDFs only
(``authoring_reads._SUPPORTED_SUFFIXES``), while FR-CONSOLE-50 and the test plan
require the other formats too — reported with file:line evidence, awaiting the
coordinator's defect-fix decision. The format gate raises that finding in
milliseconds, BEFORE any browser is launched or store built; when the three-format
read lands, this journey runs end to end with no other change. Issue #773 says
"Written ahead of implementation: no", so this test is NOT marked ``writtenahead``
and carries no ``WRITTEN_AHEAD_BLOCKERS`` entry.
"""

from __future__ import annotations

import pytest

from tests.support import console_journeys as cj

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
]

#: The journey's identity: AF-14's single `.docx`, its own cohort and run names, and
#: the console-redesign capture pass's build pin (module docstring).
SPEC = cj.JourneySpec(
    label="TC-E2E-08",
    af_id="AF-14",
    documents=("hist7-rome-01-test-and-grading.docx",),
    cohort_id="coh-rome-docx",
    run_id="run-rome-docx",
    transcriber_build=cj.JOURNEY_AUTHORING_BUILD,
    judge_build=cj.JOURNEY_AUTHORING_BUILD,
)


def test_tc_e2e_08_af14_docx_full_journey(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The .docx journey, driven through the operator's surface and the CLI's, writes
    identical stores."""
    cj.run_full_journey(SPEC, tmp_path_factory, monkeypatch)
