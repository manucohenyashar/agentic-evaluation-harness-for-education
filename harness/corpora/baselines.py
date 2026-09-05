"""The §6.9 baseline registry: which artifact, whose signature, and on what grounds.

Test-plan §6.9 opens with the reason this file exists at all:

    *"Snapshot testing degrades into 'regenerate until green' unless the reviewer and the
    grounds are named."*

The plan names them in a table. A table in a document does not stop anybody regenerating a
golden file, so the table is transcribed here, emitted into `fixtures/baselines/registry.json`
by `harness.corpora.build`, and read by the six `TC-REG-*` tests — which put the reviewer and
the grounds **into the failure message**. The person who sees a golden diff sees, in the same
breath, who has to sign it off and what the only acceptable reasons are.

`tests/regression/test_baseline_registry.py` asserts the transcription still matches
`docs/design/test-plan.md` §6.9. That test is green and it is drift detection, not coverage.

The `golden` paths
------------------
Each entry names the file(s) that hold the frozen artifact. **None of them exist yet**, and
that is the honest state of this repository: a golden file is the output of a producer, no
producer has been built, and a golden committed before its producer is a guess frozen into the
repo. Each entry therefore carries `produced_by` — the module and the issue that will emit it
— and the `TC-REG-*` test resolves that producer first, so the failure a reader sees names the
missing implementation rather than the missing file.

`FR-CONFORM-08` makes `TC-REG-05` the odd one out and the registry says so in `oracle`: a
score shift with an unchanged package is *build substitution to be detected*, never a baseline
to update. It is the one row where accepting the diff is itself the defect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Baseline:
    case_id: str
    requirements: tuple[str, ...]
    baseline: str
    reviewer: str
    grounds: str
    oracle: str
    golden: tuple[str, ...]
    produced_by: str
    blocked_on: str

    def as_json(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "requirements": list(self.requirements),
            "baseline": self.baseline,
            "reviewer": self.reviewer,
            "grounds": self.grounds,
            "oracle": self.oracle,
            "golden": list(self.golden),
            "produced_by": self.produced_by,
            "blocked_on": self.blocked_on,
        }


BASELINES: tuple[Baseline, ...] = (
    Baseline(
        case_id="TC-REG-01",
        requirements=("FR-INGEST-04", "FR-INGEST-06"),
        baseline="Canonical assembled Markdown per `F-SYNTH` and `F-GRAPHIC` document",
        reviewer="The ingestion owner",
        grounds=(
            "Accepted only alongside a deliberate transcription-prompt version bump or a "
            "stated assembly-rule change; never \"the model changed its mind\""
        ),
        oracle="Golden file, byte for byte",
        golden=(
            "TC-REG-01/F-SYNTH.canonical.md",
            "TC-REG-01/F-GRAPHIC.canonical.md",
        ),
        produced_by="M-INGEST: one canonical Markdown artifact per logical document",
        blocked_on="#37",
    ),
    Baseline(
        case_id="TC-REG-02",
        requirements=("FR-PKG-10",),
        baseline="The exported package archive for the reference package",
        reviewer="The package owner",
        grounds=(
            "Accepted only with a schema-version bump or a declared export-format change"
        ),
        oracle="Golden file over the archive's canonical listing and per-member digests",
        golden=("TC-REG-02/PKG-REF.archive.json",),
        produced_by="M-PKG: single-file package export",
        blocked_on="#31",
    ),
    Baseline(
        case_id="TC-REG-03",
        requirements=("FR-GRADE-17",),
        baseline="The CSV and per-student PDF exports",
        reviewer="The grading owner",
        grounds=(
            "Accepted only with a declared export-mapping change; a diff in a *mark* is a "
            "defect, not a baseline update"
        ),
        oracle="Golden file, with the mark columns compared separately and never accepted on diff",
        golden=(
            "TC-REG-03/marks.csv",
            "TC-REG-03/per-student-pdf.manifest.json",
        ),
        produced_by="M-GRADE: export from a specified grade revision",
        blocked_on="#104",
    ),
    Baseline(
        case_id="TC-REG-04",
        requirements=("FR-CONSOLE-13", "FR-CONSOLE-15"),
        baseline="Rendered HTML of the review queue, the rollup and the student view",
        reviewer="The console owner",
        grounds=(
            "Accepted for deliberate layout changes; **never** for a change that removes a "
            "§11.6 invariant's rendered element"
        ),
        oracle="Golden file, plus a separate invariant-element check that no diff can waive",
        golden=(
            "TC-REG-04/review-queue.html",
            "TC-REG-04/rollup.html",
            "TC-REG-04/student-view.html",
        ),
        # #125, not #124, and the two are worth distinguishing: `FR-CONSOLE-13` and `-15` are
        # #124's, but the baseline covers *three* surfaces and the rollup is #125's. The
        # `WRITTEN_AHEAD_BLOCKERS` entry keys on #125 for the same reason, and this field is
        # what the failure message prints — the two naming different issues is exactly the
        # drift the registry exists to prevent.
        produced_by="M-CONSOLE: review queue (#124), rollup and student view (#125)",
        blocked_on="#125",
    ),
    Baseline(
        case_id="TC-REG-05",
        requirements=("FR-CONFORM-01", "FR-CONFORM-08"),
        baseline="Per-criterion score distributions of `F-FROZEN` on each backend",
        reviewer="The whole team, at release",
        grounds=(
            "A shift with an unchanged package is build substitution (`FR-CONFORM-08`), not a "
            "baseline to update"
        ),
        oracle=(
            "Statistical: per-criterion distribution over the frozen set, with n and threshold "
            "stated. A shift under an unchanged package must be reported as build substitution"
        ),
        golden=("TC-REG-05/score-distributions.json",),
        produced_by="M-CONFORM: frozen-set re-run and build-substitution detection",
        blocked_on="#134",
    ),
    Baseline(
        case_id="TC-REG-06",
        requirements=("FR-ORCH-01",),
        baseline="The `work_id` reference values",
        reviewer="Nobody may accept a diff casually",
        grounds=(
            "A changed `work_id` means every stored result for that shape is now unreachable. "
            "Requires an explicit migration note"
        ),
        oracle="Golden file over the reference input tuples, plus pairwise distinctness",
        golden=("TC-REG-06/work-id-reference.json",),
        produced_by="M-ORCH: `compute_work_id` over FR-ORCH-01's nine inputs",
        blocked_on="#57",
    ),
)

# `FR-ORCH-01`'s nine inputs, in the order the requirement lists them. The reference tuples
# below are the *inputs* to the baseline; the `work_id` each one hashes to is the baseline
# value, and it cannot be committed before `compute_work_id` exists, because the canonical
# encoding of a tuple into bytes is a choice the implementation has not made yet. Committing a
# guessed digest would freeze that choice from the test side, which is the one thing a
# regression baseline must never do.
WORK_ID_INPUTS: tuple[str, ...] = (
    "run_id",
    "stage",
    "submission_id",
    "criterion_id",
    "judge_id",
    "package_version_id",
    "panel_config",
    "prompt_template_version",
    "extractor_version",
)

_WORK_ID_BASE: dict[str, str] = {
    "run_id": "RUN-0001",
    "stage": "score",
    "submission_id": "SYN-001",
    "criterion_id": "C-01",
    "judge_id": "judge-a",
    "package_version_id": "PKG-REF@1",
    "panel_config": "depth=3;arms=a,b,c",
    "prompt_template_version": "judge/4",
    "extractor_version": "extract/2",
}


def work_id_reference_tuples() -> list[dict[str, Any]]:
    """The baseline population: the base tuple, plus one variant per input field.

    Ten tuples, nine of which differ from the base in exactly one field. That shape is what
    makes the case test `FR-ORCH-01`'s actual promise — *"changing any of those inputs produces
    a different unit, so stale results cannot be reused"* — rather than merely that a hash is
    stable. A `work_id` that ignored `prompt_template_version` would pass a stability-only
    check and silently reuse a result computed under a different prompt.
    """
    tuples: list[dict[str, Any]] = [
        {"label": "base", "varied_field": None, "inputs": dict(_WORK_ID_BASE), "work_id": None}
    ]
    for field_name in WORK_ID_INPUTS:
        variant = dict(_WORK_ID_BASE)
        variant[field_name] = _WORK_ID_BASE[field_name] + "-variant"
        tuples.append(
            {
                "label": f"varied:{field_name}",
                "varied_field": field_name,
                "inputs": variant,
                "work_id": None,
            }
        )
    return tuples
