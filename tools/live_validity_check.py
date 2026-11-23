#!/usr/bin/env python3
"""The live validity check (FR-CONFORM-20): ENG7 and PS9 through a profile and the console.

    python tools/live_validity_check.py --profile smoke|panel [--data-dir DIR]

Builds both sample tests, reads in their synthetic answer sheets, grades them on the named
profile through the console's `start run`, marks the blind sample from the sample author's
intended bands through the console's API, and prints: cells scored per sheet, the
verification-refusal rate, the cited share, the confidence distribution, the labels, the
administration record, the routing verdict and the purge outcome.

It sends only the synthetic sample materials (R31) and refuses a class that is not `synthetic`.
Its "teacher" bands are the sample author's intended bands, not a teacher's marks. With
`HARNESS_FIXTURE_DIR` set the pipeline uses the recorded provider and nothing leaves the machine;
otherwise the profile's real models are called and the run costs money.

The logic lives in `aeh.conform.validity_check`; this file is the command.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeh.conform.validity_check import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
