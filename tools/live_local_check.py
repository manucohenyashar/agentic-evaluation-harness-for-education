#!/usr/bin/env python3
"""The local smoke (FR-CONFORM-21): ENG7's four sheets on edge-local against a local model server.

    python tools/live_local_check.py [--config FILE] [--base-url URL] [--data-dir DIR]
                                     [--record [--record-dir DIR]] [--panel-bands FILE]

Probes every `served_as` name once, then builds the sample English test, reads its four answer
sheets with the local vision model, grades them with the local judge (decision engine off), and
prints: the probes, the sheets read, cells scored per sheet, the refusal rate, the cited share,
the band agreement with a recorded panel run (consistency between graders, not accuracy), the
wall clock and the peak memory, and that this is a smoke of the wire path, not the hardware gate.

`--record` writes every reply the server gave to `fixtures/F-LOCAL/` (captured, never
hand-written), with the configuration the capture ran under, for the air-gapped journey.

Set `LOCAL_INFERENCE_BASE_URL` (or pass `--base-url`) and fill in the model blocks of
`docs/live-tests/config/live-test.edge-local.toml` first. Nothing leaves the machine.

The logic lives in `aeh.conform.local_check`; this file is the command.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The source tree, and the repository root: `aeh.conform` reads the committed corpora's
# selection from `harness.corpora`, which is not an installed package.
_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "src"), str(_ROOT)]

from aeh.conform.local_check import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
