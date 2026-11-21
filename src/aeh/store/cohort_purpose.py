"""What a cohort file is for, told from its key without opening it (FR-CALIB-17, CT-CALIB-18).

Cohort migration 38 records `cohort.purpose`: `'class'` for a teacher's class, `'calibration'`
for the teacher's marked examples graded under the package's current version. The stored column
is the record. But a reader that must never *touch* a calibration file (`aeh.stats`, the
console's class lists) cannot open each file to read the column first — the open is already the
touch. So a calibration cohort's key carries a reserved prefix that no class may use
(`aeh.orch.check_cohort_id` refuses it for a class), and the enumerators that serve teachers'
classes list cohort files through `class_cohort_keys`, which skips the prefix by name.

The enumerators that find a cohort *by its run* (M-DET, M-GRADE, M-REVIEW's run-scoped reads,
M-ORCH's recovery, the store's blob reclamation) still see every file: a calibration run is a
run like any other while it grades, and recovery must resume it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: The reserved prefix of every calibration cohort's key. A class may not start with it.
CALIBRATION_COHORT_PREFIX = "calibration-"

#: The two values `cohort.purpose` admits (migration 38's CHECK).
COHORT_PURPOSES: tuple[str, ...] = ("class", "calibration")


def is_calibration_cohort(cohort_id: Any) -> bool:
    """Whether a cohort key names a calibration cohort, by its reserved prefix."""
    return str(cohort_id or "").startswith(CALIBRATION_COHORT_PREFIX)


def class_cohort_keys(data_dir: Any) -> tuple[str, ...]:
    """The keys of the cohort files under `<data_dir>/cohorts/` that hold a teacher's class,
    sorted. Calibration cohorts are skipped by name, so no calibration file is opened."""
    if data_dir is None:
        return ()
    return tuple(sorted(
        path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite")
        if not is_calibration_cohort(path.stem)
    ))
