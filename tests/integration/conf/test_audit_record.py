"""The stored `profile_summary()` matches the one logged at run start.

Case: `TC-CONF-17` (`FR-CONF-09`, `NFR-SYS-11`, P1), test plan §5.1.
**Isolation: rung 2** — real SQLite, real blob directory. Oracle: **differential**.

**Written ahead of implementation, and the only case in TS-04 that is.** Its rung is not
achievable today: rung 2 means a *finished run's* audit record, which needs `M-STORE` (#10–13)
for the store and `M-ORCH` (#57–62) to write the record. Neither exists.

Registered on **#57**, not #10, and the distinction matters. `M-STORE` alone would let this file
import and the marker come off — and the case would then report as covered while comparing a
value to itself, because the test would still be the thing writing the row. The blocker is the
producer, not the storage.

A rung-0 stand-in — comparing `log_run_start`'s record against `to_persisted_dict()` in memory —
would be green today and would assert the wrong thing. What this case exists to catch is the two
*paths* diverging: `M-ORCH` serializing the summary its own way when it writes the audit record,
so the stored bytes and the logged bytes differ. Both paths have to be real for that to be
visible, which is why the plan says rung 2.

Remove the `writtenahead` marker — not the test — when `M-STORE` lands, and drop the entry from
`WRITTEN_AHEAD_BLOCKERS`.

`ProfileSummary.to_canonical_json()` exists so this comparison is possible at all: one serializer
called by both paths. If `M-ORCH` reaches for `json.dumps(asdict(...))` instead, this case is
what says so.
"""

from __future__ import annotations

import json
import logging

import pytest

from aeh.conf import log_run_start, resolve_run_config
from tests.support.conf_builders import HOSTED_PANEL_3, SYNTHETIC_COHORT, hosted_cfg
from tests.support.impl import ORCH_MODULE, STORE_MODULE, require

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#57"


def test_tc_conf_17_the_stored_profile_summary_matches_the_one_logged_at_run_start(tmp_data_dir):
    """TC-CONF-17 — oracle: **differential**. *"The stored `profile_summary()` is byte-identical
    to the one logged at run start."*

    Byte-identical, not merely equivalent: the audit record is what a data-protection enquiry
    reads six months later, and "the logged one said `q4` and the stored one said `q4.0`" is the
    kind of difference that turns a straightforward answer into an investigation.

    **Interface this case assumes of #10 and the orchestrator**, listed so it is reconciled
    deliberately rather than discovered:

    | Name | Status |
    |---|---|
    | `aeh.store.open_store(data_dir)` | **invented here** — `M-STORE`'s entry point is unnamed in §3.3's Interfaces |
    | `aeh.orch.record_run_start(store, config)` | **invented here** — the orchestrator's write of the audit record |
    | `store.durable()` | design §3.3 names the tier handle |
    | an `audit_record` row carrying the run's `profile_summary` | design §9.6 names the table, not the column |

    Until those exist this fails with `NotImplementedYet`, which is the correct red.
    """
    # **Both** are required, and that is the point of the case. The audit record must be written
    # by whatever writes audit records in production -- if this test writes the row itself, then
    # `stored == logged` compares `summary.to_canonical_json()` against `summary
    # .to_canonical_json()` and the only defect it can see is SQLite mangling a TEXT column.
    open_store = require(STORE_MODULE, "open_store", issue="#10")
    record_run_start = require(ORCH_MODULE, "record_run_start", issue=ISSUE)

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("aeh.conf.tc_conf_17")
    logger.addHandler(_Capture())
    logger.setLevel(logging.INFO)

    config = resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3), SYNTHETIC_COHORT)
    summary = log_run_start(config, logger)
    logged_bytes = records[-1].__dict__["profile_summary"]

    # Rung 2: a real store on a real directory, not a double. §4.2 forbids an in-memory
    # stand-in for the store contract outright, and this case is one of the reasons —
    # a fake that round-trips a Python object never exercises the serialization step.
    store = open_store(tmp_data_dir)
    record_run_start(store, config)

    stored_bytes = store.durable().query(
        "SELECT profile_summary FROM audit_record ORDER BY rowid DESC LIMIT 1"
    )[0][0]

    assert stored_bytes == logged_bytes, (
        "the audit record and the run-start line disagree about what graded this run"
    )
    assert json.loads(stored_bytes) == json.loads(logged_bytes)
