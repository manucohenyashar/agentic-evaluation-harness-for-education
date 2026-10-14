"""TC-E2E-12 — the reload-survival journey: the teacher's progress survives the page
and the process dying under it.

Console redesign test plan §3.6: "*reload survival.* Mid-drafting and mid-review:
reload at each; progress re-attaches from the server (RS-05's positive twin); answered
placeholders survive; **server restart** between review answers also survives
(TC-CONSOLE-62's browser twin)." The journey is the full console drive with three
survival probes riding it, each asserting the store, not the client, holds the
teacher's progress:

* mid-drafting — the browser's draft job is dispatched, the dispatch registers
  server-side, and only then does the page reload; the same job is waited out to its
  draft (the job never belonged to the page).
* mid-review — after the placeholder answer is sent, the page reloads and the review
  screen re-attaches showing nothing left to answer (the answer is in the store).
* server restart — the console process is terminated and re-served on the same store
  between review answers; the reopened review screen still reads the answer answered,
  and the draft read still counts zero missing pieces.

The probes write nothing the twins' differential would see, so the journey keeps the
full machinery — the phase-A capture, the CLI twin, the pairing oracle — and its
oracle is the same differential: the survival legs must not change what the store
holds.

**The replay pin is the corpus's own** (AF-01's recordings, the qwen builds
`console_redesign_world.RECORDED_TRANSCRIBER` / `RECORDED_JUDGE` — the TC-E2E-10
docstring carries the reasoning; a replay asks no endpoint of them).

**Disclosed divergences.** The console's captured AF-01 draft asks exactly one review
answer (`approved_by`; `missing_pieces = 1`), so "between review answers" is realized
as the restart falling between the review walk's answer and its next leg — the answer
must survive the process dying after it, which is the persistence the stage names.
AF-01's corpus contract declares no placeholders and no warnings, so no format oracle
joins the walk. Issue #773 says "Written ahead of implementation: no" and every
dependency is merged, so this test is NOT marked ``writtenahead`` and carries no
``WRITTEN_AHEAD_BLOCKERS`` entry: it must pass when its PR merges.
"""

from __future__ import annotations

import pytest

from tests.support import console_journeys as cj
from tests.support import console_redesign_world as crw

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
]

#: The journey's identity: AF-01's single PDF (the format the console's upload read
#: carries), its own cohort and run names, the corpus's capture pin, and the survival
#: probes switched on (module docstring).
SPEC = cj.JourneySpec(
    label="TC-E2E-12",
    af_id="AF-01",
    documents=("hist7-rome-01-test-and-grading.pdf",),
    cohort_id="coh-reload-survival",
    run_id="run-reload-survival",
    transcriber_build=crw.RECORDED_TRANSCRIBER,
    judge_build=crw.RECORDED_JUDGE,
    survival=True,
)


def test_tc_e2e_12_reload_survival_full_journey(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The journey with its reload and restart probes; the twins still write identical
    stores, the probes notwithstanding."""
    cj.run_full_journey(SPEC, tmp_path_factory, monkeypatch)
