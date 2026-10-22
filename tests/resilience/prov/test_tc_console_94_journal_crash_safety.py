"""`TC-CONSOLE-94` (issue #820): the AI-call journal's file sink survives a torn line and
concurrent writers.

Console clarity test plan §3.3, story T7. FR-CONSOLE-77, ADR-51.

| Arm | What is asserted |
|---|---|
| torn line | append 3 records, then write half a 4th line (a simulated crash): the reader returns exactly the 3; a fresh append afterwards starts on its own line — the torn bytes stay alone on theirs — and the reader then returns exactly 4, the fresh one last |
| two processes | two OS processes, started together, each append 500 records to the same file: exactly 1000 raw lines, every one a JSON object, and the (process, sequence) ids are exactly the 1000 written |

**Isolation.** Rung 1: the real `JsonlCallJournal` over a `tmp_path` data folder, the real
`read_journal_file`. Every record carries one fixed `at`, so every append lands in the same
`<YYYY-MM-DD>.jsonl` and no UTC midnight can split the file.

**Markers.** `integration` (two subprocesses; the fast tier excludes it). Not written ahead:
#807 is merged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aeh.prov import CallRecord, JsonlCallJournal, read_journal_file

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
AT = "2026-10-21T12:00:00.000+00:00"
COHORT = "c-crash"
PER_PROCESS = 500


def _record(call_id: str) -> CallRecord:
    return CallRecord(
        call_id=call_id, attempt=1, at=AT, kind="answer_extraction", cohort_id=COHORT,
        run_id="r1", work_id="w1", submission_id="s1", criterion_id="C1", package_id=None,
        model="fixture/m@1", resolved_build=None, request=[["instruction", "read the answer"]],
        response="an answer", outcome="ok", error=None, tokens_in=10, tokens_out=5,
        latency_ms=7, cost=None)


def test_tc_console_94_a_torn_last_line_is_skipped_and_the_next_append_is_clean(tmp_path):
    """Three records, half a fourth, then one more: the reader sees 3, then 4."""
    sink = JsonlCallJournal(tmp_path)
    for n in range(3):
        sink(_record(f"call-{n}"))
    path = sink.path_for(_record("probe"))
    assert path.is_file(), f"the sink wrote no file at {path}"

    whole = json.dumps(_record("call-torn").to_dict()).encode("utf-8")
    torn = whole[: len(whole) // 2]
    with open(path, "ab") as handle:  # the crash: half a line, no newline
        handle.write(torn)

    after_crash = read_journal_file(path)
    assert [r["call_id"] for r in after_crash] == ["call-0", "call-1", "call-2"], after_crash

    sink(_record("call-fresh"))
    lines = path.read_bytes().split(b"\n")
    assert lines[-1] == b"", "the file does not end in a newline after a clean append"
    assert lines[-3] == torn, (
        "the torn bytes are not alone on their line: the fresh append was glued onto them")
    assert json.loads(lines[-2])["call_id"] == "call-fresh", lines[-2][:200]

    after_append = read_journal_file(path)
    assert [r["call_id"] for r in after_append] == [
        "call-0", "call-1", "call-2", "call-fresh"], after_append


_WRITER = r"""
import sys
from aeh.prov import CallRecord, JsonlCallJournal
data_dir, tag, count, at, cohort = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
sink = JsonlCallJournal(data_dir)
padding = "x" * 2000  # a long line, so an interleaved write would show
for seq in range(count):
    sink(CallRecord(
        call_id=f"{tag}-{seq}", attempt=1, at=at, kind="answer_extraction", cohort_id=cohort,
        run_id="r1", work_id="w1", submission_id="s1", criterion_id="C1", package_id=None,
        model="fixture/m@1", resolved_build=None, request=[["instruction", padding]],
        response=padding, outcome="ok", error=None, tokens_in=1, tokens_out=1,
        latency_ms=1, cost=None))
"""


def test_tc_console_94_b_two_processes_appending_500_each_leave_1000_parseable_lines(tmp_path):
    """Two writers at once on one file: 1000 lines, every one parses, none lost or doubled."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(REPO)])}
    writers = [
        subprocess.Popen(
            [sys.executable, "-c", _WRITER, str(tmp_path), tag, str(PER_PROCESS), AT, COHORT],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for tag in ("p1", "p2")
    ]
    for writer in writers:
        _out, err = writer.communicate(timeout=300)
        assert writer.returncode == 0, err.decode("utf-8", "replace")[-2000:]

    path = JsonlCallJournal(tmp_path).path_for(_record("probe"))
    files = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    assert files == [path.relative_to(tmp_path)], f"the writers wrote {files}, not one file"
    raw = path.read_bytes()
    assert raw.endswith(b"\n"), "the file does not end in a newline"
    lines = raw[:-1].split(b"\n")
    assert len(lines) == 2 * PER_PROCESS, f"{len(lines)} lines, not {2 * PER_PROCESS}"
    ids: list[str] = []
    for number, line in enumerate(lines, 1):
        try:
            document = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            pytest.fail(f"line {number} does not parse ({error}): {line[:120]!r}")
        assert isinstance(document, dict), f"line {number} is not a JSON object"
        ids.append(document["call_id"])
    expected = {f"{tag}-{seq}" for tag in ("p1", "p2") for seq in range(PER_PROCESS)}
    assert len(ids) == len(set(ids)) and set(ids) == expected, (
        f"ids lost: {sorted(expected - set(ids))[:5]}, doubled: "
        f"{len(ids) - len(set(ids))}")
    assert len(read_journal_file(path)) == 2 * PER_PROCESS
