#!/usr/bin/env python3
"""The band each sample answer was written to earn, per judged rubric line (the sample author's
intended bands).

`tools/live_validity_check.py` (FR-CONFORM-20) marks the blind sample with these bands, standing
in for a teacher. They are the author's intent, not a teacher's marks, and the check says so.

Read off the sheets in `build_sample_materials.py` against the band descriptors in
`../config/eng7-read-01.package.toml` and `../config/ps9-forces-01.package.toml`. Each sheet's
points under these bands, plus its multiple-choice keys, equal its `reference_points`;
`check_intended_bands()` asserts that, so a sample edited without this table fails loudly.
The keys are the full names the sheets and the class list carry (the system matches by name);
sheets that intake parks (Elif Demir's wrong test, Farah Nasser's no-name sheet) have no entry.

    python docs/live-tests/sample-materials/intended_bands.py     # exits 1 on a mismatch
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_DIR = HERE.parent / "config"

INTENDED_BANDS: dict[str, dict[str, str]] = {
    "Ines Moreau": {"C1a": "present", "C1b": "present", "C2": "full", "C3": "evidenced"},
    "Jonas Berg": {"C1a": "present", "C1b": "present", "C2": "adequate", "C3": "change"},
    "Keiko Tanaka": {"C1a": "absent", "C1b": "absent", "C2": "limited", "C3": "retell"},
    "Luis Ortega": {"C1a": "present", "C1b": "absent", "C2": "none", "C3": "none"},
    "Aisha Bello": {"C4": "full", "C6": "full"},
    "Daniel Kim": {"C4": "adequate", "C6": "adequate"},
    "Mateo Rossi": {"C4": "limited", "C6": "limited"},
    "Dalia Haddad": {"C4": "none", "C6": "full"},
}

#: Which package spec each sheet is marked against, by the sheet stem's prefix. The stem —
#: not the page's `Assessment:` line — decides the cohort: S9-005 is in the physics class even
#: though its page carries the English test's answers.
SPECS = {"E7": CONFIG_DIR / "eng7-read-01.package.toml",
         "S9": CONFIG_DIR / "ps9-forces-01.package.toml"}


def _points_for(spec_path: Path) -> tuple[dict[str, int], dict[str, dict[str, int]],
                                          dict[str, str]]:
    """The spec's question points, each banded line's band points, and each keyed line's key."""
    spec = tomllib.loads(spec_path.read_text(encoding="utf-8"))
    points = {question["id"]: question.get("points", 0) for question in spec["question"]}
    band_points = {c["id"]: {b["name"]: b["points"] for b in c["bands"]}
                   for c in spec["criterion"] if "bands" in c}
    keys = {c["question"]: c["key"] for c in spec["criterion"] if "key" in c}
    return points, band_points, keys


def mismatches() -> list[str]:
    """Each sheet whose intended points differ from its `reference_points`, in words."""
    sys.path.insert(0, str(HERE))
    try:
        import build_sample_materials as samples
    finally:
        sys.path.remove(str(HERE))
    sheets = {sheet["name"]: sheet
              for sheet in samples.PHYSICS_SHEETS + samples.ENGLISH_SHEETS}
    by_prefix = {prefix: _points_for(path) for prefix, path in SPECS.items()}
    found = []
    for student, intended in INTENDED_BANDS.items():
        sheet = sheets[student]
        points, band_points, keys = by_prefix[sheet["stem"].split("-", 1)[0]]
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
