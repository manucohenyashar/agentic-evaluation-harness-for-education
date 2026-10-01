"""Grade states, routings, the export directory knob, and the registry of each run's store."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Mapping

from aeh.store import Store


# --- vocabulary ------------------------------------------------------------------------------------

#: The three state literals a `submission_grade` row carries (design §3.14's state
#: model, enforced by the migration's CHECK). `incomplete` is caused exclusively by
#: ingestion failure (`CT-GRADE-08`) — judgment uncertainty reads `provisional`.
STATE_PROVISIONAL = "provisional"


STATE_FINAL = "final"


STATE_INCOMPLETE = "incomplete"


GRADE_STATES = (STATE_PROVISIONAL, STATE_FINAL, STATE_INCOMPLETE)


#: The coverage classes' routing sources (`CT-AGG-06`'s closed column vocabulary).
#: `queued` groups with `provisional` (unsettled acceptance, scored input); `triage`
#: groups with absence (`criteria_missing`) — an unresolved extraction is exactly the
#: ingestion-failure population the incomplete state names.
ROUTING_AUTO = "auto"


ROUTING_REVIEWED = "reviewed"


ROUTING_PROVISIONAL = "provisional"


ROUTING_QUEUED = "queued"


ROUTING_TRIAGE = "triage"


_PROVISIONAL_ROUTINGS = (ROUTING_PROVISIONAL, ROUTING_QUEUED)


#: The completion status a run must read for the completion finalization path
#: (`FR-GRADE-10`; the shipped `run` DDL's CHECK in aeh/orch.py).
STATUS_COMPLETE = "complete"


#: The operator routing reason's action word — the pinned reading of `TC-GRADE-07`'s
#: routing clause (the design leaves the wording implicit; the case pins `rescan`).
_RESCAN_DIRECTIVE = (
    "missing criterion score: extraction quarantined or ingestion failed — "
    "rescan the submission's document for this criterion"
)


#: Env knobs for the export directory (CLAUDE.md seam 3, read at call time).
HARNESS_EXPORT_DIR_ENV = "HARNESS_GRADE_EXPORT_DIR"


#: The design §3.14 Configuration name — the deployment-facing spelling of the same
#: knob; the HARNESS_ form wins when both are set.
GRADE_EXPORT_DIR_ENV = "GRADE_EXPORT_DIR"


_DEFAULT_EXPORT_SUBDIR = "aeh-grade-exports"


def export_dir(environ: Mapping[str, str] | None = None) -> Path:
    """The directory exports are written to, read from its knob at call time.

    `HARNESS_GRADE_EXPORT_DIR` wins, then the design §3.14 configuration name
    `GRADE_EXPORT_DIR`, then a subdirectory of the platform temp dir — a default that
    exists and is writable on every platform this suite runs on, never a hard-coded
    path a slower box cannot adjust."""
    source = os.environ if environ is None else environ
    raw = source.get(HARNESS_EXPORT_DIR_ENV) or source.get(GRADE_EXPORT_DIR_ENV)
    if raw:
        return Path(raw)
    return Path(tempfile.gettempdir()) / _DEFAULT_EXPORT_SUBDIR


_GRADE_RUN_STORES: dict[str, Store] = {}
