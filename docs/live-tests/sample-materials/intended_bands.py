#!/usr/bin/env python3
"""The band each sample answer was written to earn, per judged rubric line (the sample author's
intended bands).

`tools/live_validity_check.py` (FR-CONFORM-20) marks the blind sample with these bands, standing
in for a teacher. They are the author's intent, not a teacher's marks, and the check says so.

Read off the sheets in `build_sample_materials.py` against the band descriptors in
`../config/eng7-read-01.package.toml` and `../config/ps9-forces-01.package.toml`. Each sheet's
points under these bands, plus its multiple-choice keys, equal its `reference_points`;
`check_intended_bands()` asserts that, so a sample edited without this table fails loudly.
Sheets that intake parks (S9-005 wrong test, S9-006 no name) have no entry.

    python docs/live-tests/sample-materials/intended_bands.py     # exits 1 on a mismatch
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_DIR = HERE.parent / "config"

INTENDED_BANDS: dict[str, dict[str, str]] = {
    "E7-001": {"C1a": "present", "C1b": "present", "C2": "full", "C3": "evidenced"},
    "E7-002": {"C1a": "present", "C1b": "present", "C2": "adequate", "C3": "change"},
    "E7-003": {"C1a": "absent", "C1b": "absent", "C2": "limited", "C3": "retell"},
    "E7-004": {"C1a": "present", "C1b": "absent", "C2": "none", "C3": "none"},
    "S9-001": {"C4": "full", "C6": "full"},
    "S9-002": {"C4": "adequate", "C6": "adequate"},
    "S9-003": {"C4": "limited", "C6": "limited"},
    "S9-004": {"C4": "none", "C6": "full"},
}

#: Which package spec each sheet prefix is marked against.
SPECS = {"E7": CONFIG_DIR / "eng7-read-01.package.toml",
         "S9": CONFIG_DIR / "ps9-forces-01.package.toml"}


def mismatches() -> list[str]:
    """Each sheet whose intended points differ from its `reference_points`, in words."""
    sys.path.insert(0, str(HERE))
    try:
        import build_sample_materials as samples
    finally:
        sys.path.remove(str(HERE))
    sheets = {sheet["student"]: sheet
              for sheet in samples.PHYSICS_SHEETS + samples.ENGLISH_SHEETS if sheet["student"]}
    found = []
    for prefix, spec_path in SPECS.items():
        spec = tomllib.loads(spec_path.read_text(encoding="utf-8"))
        points = {question["id"]: question.get("points", 0) for question in spec["question"]}
        band_points = {c["id"]: {b["name"]: b["points"] for b in c["bands"]}
                       for c in spec["criterion"] if "bands" in c}
        keys = {c["question"]: c["key"] for c in spec["criterion"] if "key" in c}
        for student, intended in INTENDED_BANDS.items():
            if not student.startswith(prefix):
                continue
            sheet = sheets[student]
            earned = sum(band_points[criterion][band] for criterion, band in intended.items())
            earned += sum(points[question] for question, key in keys.items()
                          if sheet["mcq"].get(question) == [key])
            expected = sheet["reference_points"]
            if expected is not None and earned != expected:
                found.append(f"{student}: the intended bands earn {earned} points, the sheet is "
                             f"written to earn {expected}")
    return found


if __name__ == "__main__":
    problems = mismatches()
    print("\n".join(problems) or "every sheet's intended bands earn its reference points")
    raise SystemExit(1 if problems else 0)
