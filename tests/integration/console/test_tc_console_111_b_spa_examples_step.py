"""Validity T9 (issue #902): `TC-CONSOLE-111`'s SPA arm — *"The legacy upload page's copy makes
no claim the SPA lacks"* (FR-CONSOLE-86).

The legacy upload page (`/packages/new`) and the setup step's copy offer the teacher the
marked-examples step: upload unmarked copies, enter the marks in a form, check them, or skip.
The console serves every one of those (`examples upload|mark|grade|skip` and the three
`/api/v1/calibration/*` reads, asserted green in
`test_tc_console_111_112_115_examples_console.py`); the SPA does not call any of them yet. The
SPA examples step is S18 (#888, open), so this arm is written ahead on it:
`WRITTEN_AHEAD_BLOCKERS` key "#888 SPA examples step — TC-CONSOLE-111's SPA arm"; the probe
resolves when the SPA source names the examples read.

Rung 0: a census over `ui/src` (the SPA's source; the bundle is built from it).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: What the legacy copy offers, as the SPA would have to call it.
OFFERED = (
    "/api/v1/calibration/examples",
    "/api/v1/calibration/differences",
    "/api/v1/calibration/questions",
    "examples upload",
    "examples mark",
    "examples grade",
    "examples skip",
)


def test_tc_console_111_b_the_spa_offers_every_examples_affordance_the_legacy_copy_claims():
    source = "\n".join(path.read_text(encoding="utf-8")
                       for path in (REPO / "ui" / "src").rglob("*.ts*"))
    missing = [name for name in OFFERED if name not in source]
    assert not missing, (
        f"the legacy upload page and setup copy offer the marked-examples step, and the SPA "
        f"does not call {missing} (S18, #888)")
