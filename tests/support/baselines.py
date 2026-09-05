"""The golden-file comparison the §6.9 baselines are asserted with.

One helper, and the shape of its failure message is the point of it. Test-plan §6.9:

    *"Snapshot testing degrades into 'regenerate until green' unless the reviewer and the
    grounds are named."*

So a golden diff here does not report "files differ". It reports which baseline, who has to
review a change to it, and the only grounds on which a change may be accepted — read out of
`fixtures/baselines/registry.json`, which is generated from `harness.corpora.baselines` and
checked against the plan by `tests/regression/test_baseline_registry.py`.

**There is deliberately no `record_golden()` here.** A one-call "accept the new output" helper
is exactly the affordance that turns a baseline suite into a rubber stamp: it makes
regenerating cheaper than reading the diff, and the reviewer named in the registry never finds
out a baseline moved. Capturing a baseline for the first time is a deliberate act — run the
producer, inspect what it emitted, commit it with the reviewer on the PR — and it should cost
more than pressing a key.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tests.support.impl import NotImplementedYet, require_path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BASELINE_ROOT = REPO_ROOT / "fixtures" / "baselines"
REGISTRY_PATH = BASELINE_ROOT / "registry.json"

CORPORA_ISSUE = "#2"


@dataclass(frozen=True)
class BaselineEntry:
    case_id: str
    requirements: tuple[str, ...]
    baseline: str
    reviewer: str
    grounds: str
    oracle: str
    golden: tuple[str, ...]
    produced_by: str
    blocked_on: str

    def governance(self) -> str:
        return (
            f"{self.case_id} baseline: {self.baseline}\n"
            f"  reviewer: {self.reviewer}\n"
            f"  grounds for accepting a diff: {self.grounds}\n"
            f"  oracle: {self.oracle}\n"
            f"(test plan §6.9. Regenerating this file without the named reviewer and one of "
            f"those grounds is the failure mode the table exists to prevent.)"
        )


def registry() -> Mapping[str, BaselineEntry]:
    path = require_path(REGISTRY_PATH, "the §6.9 baseline registry", issue=CORPORA_ISSUE)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["case_id"]: BaselineEntry(
            case_id=entry["case_id"],
            requirements=tuple(entry["requirements"]),
            baseline=entry["baseline"],
            reviewer=entry["reviewer"],
            grounds=entry["grounds"],
            oracle=entry["oracle"],
            golden=tuple(entry["golden"]),
            produced_by=entry["produced_by"],
            blocked_on=entry["blocked_on"],
        )
        for entry in raw["baselines"]
    }


def entry_for(case_id: str) -> BaselineEntry:
    found = registry().get(case_id)
    if found is None:
        raise AssertionError(
            f"{case_id} has no entry in {REGISTRY_PATH.name}. Every §6.9 baseline names its "
            f"reviewer and its grounds; a golden file with neither is a snapshot nobody owns."
        )
    return found


def golden_bytes(case_id: str, relative_path: str) -> bytes:
    """The frozen artifact, or a stated reason it is not there yet.

    A baseline is the output of a producer. None of the six producers exist in this repository
    yet, so every call here currently raises `NotImplementedYet` naming the issue that will
    emit the artifact — which is the honest red state (§8.2), and is distinguishable from the
    file having been deleted, because the registry says which issue owes it.
    """
    entry = entry_for(case_id)
    if relative_path not in entry.golden:
        raise AssertionError(
            f"{relative_path!r} is not one of {case_id}'s declared golden files "
            f"({', '.join(entry.golden)}). The registry is the list; a test comparing against "
            f"an unregistered file is comparing against something nobody reviews."
        )
    path = BASELINE_ROOT / relative_path
    if not path.exists():
        raise NotImplementedYet(
            f"{case_id}: no baseline recorded at fixtures/baselines/{relative_path} yet "
            f"(blocked on {entry.blocked_on} — {entry.produced_by}). The artifact is the "
            f"output of a producer that does not exist, and a golden committed before its "
            f"producer freezes a guess. Written ahead of implementation, test plan §8.2."
        )
    return path.read_bytes()


def assert_matches_golden(case_id: str, relative_path: str, actual: bytes) -> None:
    """Compare a produced artifact against its frozen baseline, byte for byte."""
    expected = golden_bytes(case_id, relative_path)
    if expected == actual:
        return

    entry = entry_for(case_id)
    diff = "\n".join(
        list(
            difflib.unified_diff(
                expected.decode("utf-8", errors="replace").splitlines(),
                actual.decode("utf-8", errors="replace").splitlines(),
                fromfile=f"baseline/{relative_path}",
                tofile="produced",
                lineterm="",
            )
        )[:60]
    )
    raise AssertionError(
        f"{relative_path} no longer matches its baseline.\n\n{entry.governance()}\n\n{diff}"
    )


def load_json_baseline(case_id: str, relative_path: str) -> Any:
    return json.loads(golden_bytes(case_id, relative_path).decode("utf-8"))


def work_id_reference_inputs() -> Mapping[str, Any]:
    """`TC-REG-06`'s baseline population — the input tuples, committed; the digests, not yet.

    Committed separately from the golden digests on purpose. The *inputs* are `FR-ORCH-01`'s
    nine fields and are knowable today; the *digest* depends on a canonical encoding `M-ORCH`
    has not chosen, and a guessed encoding frozen into a baseline would dictate the
    implementation from the test side rather than pin its behaviour.
    """
    path = require_path(
        BASELINE_ROOT / "TC-REG-06" / "work-id-reference.inputs.json",
        "the TC-REG-06 work_id reference inputs",
        issue=CORPORA_ISSUE,
    )
    return json.loads(path.read_text(encoding="utf-8"))
