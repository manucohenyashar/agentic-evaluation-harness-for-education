"""`OBS-10` (issue #148, TS-55) — one structured log line per run start, credential-free, and
byte-identical to the profile the audit record stores behind every grade.

Test plan §6.10: *"OBS-10 | FR-CONF-09, NFR-SYS-11 | One structured log line per run start containing
`profile_summary()`; the profile recorded in the audit record behind every grade | Any run start |
Emitted exactly once, credential-free, and byte-identical to what the audit record stores"*.

**What this adds over `TC-CONF-17`.** That case checks that the two serialization paths agree: the
test calls `log_run_start()` itself, then `record_run_start()`, and compares the bytes. It cannot
see whether a *run start* emits the line, because the test is the caller. `log_run_start`'s own
docstring says the line belongs to the run-start moment and "only the caller knows when it
happened", and that caller is `M-ORCH`. This case starts a run the way production does
(`Orchestrator.create_run` then `start`, over a real store), with a credential in the environment,
and reads what was actually emitted:

1. **Exactly once.** Across `create_run` and `start`, the `aeh.conf` logger carries exactly one
   `run_start` event. Zero means no run start is logged. Two means it is logged at resolution as
   well as start, which `CT-CONF-13` forbids.
2. **Credential-free.** The API key set in the environment appears in neither the log line nor the
   audit record. This clause guards against environment leakage into the summary only: on this
   `edge-local` path no provider is built, so nothing reads the key. It cannot catch a serializer
   that copies a credential it was handed.
3. **Byte-identical.** The line's `profile_summary` equals the `profile_summary` of the run's audit
   record, byte for byte.

Markers: `integration` (a real store). When written, the case is red on clause 1: no code path in
`src/` calls `log_run_start`, so a run start emits no line. That is a defect in landed code, not a
missing symbol, so the case carries no `writtenahead` marker. It stays red under `pytest -q`, and the
PR reports it so a defect story can be filed through `/plan-to-issues`.
"""

from __future__ import annotations

import logging

import pytest

from aeh.conf import LOGGER_NAME, RUN_START_EVENT
from aeh.store import open_store
from tests.support.orch_run import seed_run
from tests.support.store_api import statement

pytestmark = [pytest.mark.integration]

ISSUE = "#148"
#: A credential that must never reach the log line or the audit record.
SECRET = "sk-or-obs10-never-logged-7f3a9c"


def test_obs_10_a_run_start_emits_one_credential_free_line_identical_to_the_audit_record(
    tmp_data_dir, monkeypatch
):
    """`OBS-10`: exactly one `run_start` line per run start, no credential in it or in the audit
    record, and its profile summary byte-identical to the stored one."""
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    capture = _Capture(level=logging.DEBUG)
    logger = logging.getLogger(LOGGER_NAME)
    previous_level = logger.level
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _version = seed_run(
            store, submissions=("S001", "S002"),
            criteria=({"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},))
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        stored = [row[0] for row in store.durable().query(statement(
            "SELECT profile_summary FROM audit_record ORDER BY rowid", issue=ISSUE))]
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)
        store.close()

    lines = [r for r in records if getattr(r, "event", r.getMessage()) == RUN_START_EVENT]
    emitted = [str(getattr(r, "profile_summary", "")) for r in lines]
    report = (f"{len(lines)} run_start line(s) emitted; {len(stored)} audit record(s) stored for "
              f"run {run_id}")
    print(report)

    assert stored, f"fixture: create_run stored no audit record. {report}"
    problems = []
    if len(lines) != 1:
        problems.append(
            f"a run start emitted {len(lines)} run_start log lines, not exactly one (FR-CONF-09, "
            f"CT-CONF-13). [When written: nothing in src/ calls aeh.conf.log_run_start; "
            f"Orchestrator.create_run writes the audit record through record_run_start, but no "
            f"run-start path emits the line.]")
    leaked = [where for where, texts in (("log line", emitted + [r.getMessage() for r in lines]),
                                          ("audit record", stored))
              if any(SECRET in str(text) for text in texts)]
    if leaked:
        problems.append(f"the credential appears in the {' and the '.join(leaked)}")
    if len(lines) == 1 and emitted[0] != stored[-1]:
        problems.append("the logged profile_summary is not byte-identical to the audit record's")
    assert not problems, "\n".join(problems) + f"\n{report}"


def test_obs_10_control_the_capture_sees_a_run_start_line_when_one_is_emitted(monkeypatch):
    """Positive control: the same capture, around a direct `log_run_start()`, records one
    credential-free `run_start` line. A zero count above is a missing emission, not a blind
    capture."""
    from aeh.conf import log_run_start, resolve_run_config
    from tests.support.conf_builders import HOSTED_PANEL_3, SYNTHETIC_COHORT, hosted_cfg

    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    capture = _Capture(level=logging.DEBUG)
    logger = logging.getLogger(LOGGER_NAME)
    previous_level = logger.level
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)
    try:
        log_run_start(resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3),
                                         SYNTHETIC_COHORT))
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)
    lines = [r for r in records if getattr(r, "event", r.getMessage()) == RUN_START_EVENT]
    assert len(lines) == 1 and getattr(lines[0], "profile_summary", None)
    assert SECRET not in str(lines[0].__dict__)
