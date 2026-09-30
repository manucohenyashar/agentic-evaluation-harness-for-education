"""The provenance line under a grade: which package version, profile and run produced it."""

from __future__ import annotations

from typing import Any, Mapping


#: The provenance footer, rendered with every grade on every grade-bearing screen
#: (`CT-CONSOLE-10`): the values, not three empty labels — a footer that reads
#: "Package version:" alone satisfies a substring check and defends nothing in a dispute.
#: The headless driver's deterministic context; a real store's audit record carries the
#: same three figures and the console renders what that record holds.
GRADE_PROVENANCE: dict[str, str] = {
    "package_version": "pkg-v1",
    "rubric_version": "rub-v1",
    "backend_profile": "edge-local-q4",
}


_PROVENANCE_FOOTER = (
    f"package version {GRADE_PROVENANCE['package_version']} "
    f"· rubric version {GRADE_PROVENANCE['rubric_version']} "
    f"· backend profile {GRADE_PROVENANCE['backend_profile']}"
)


#: FR-CONSOLE-40 (#533): the run's persisted `ProfileSummary` (M-ORCH's run-start audit
#: record) and the newest run that holds a package version or a submission's scores.
_SELECT_RUN_PROFILE_SUMMARY = (
    "SELECT profile_summary FROM audit_record WHERE run_id = :run_id "
    "AND profile_summary IS NOT NULL ORDER BY recorded_at LIMIT 1"
)


_SELECT_NEWEST_RUN_FOR_VERSION = (
    "SELECT run_id, COALESCE(started_at, '') AS started_at FROM run "
    "WHERE package_version_id = :package_version_id "
    "ORDER BY COALESCE(started_at, '') DESC, run_id DESC LIMIT 1"
)


#: The run S13's scores come from (`_SELECT_SCORES`' own subselect), so the provenance line
#: names the run whose scores are shown (#533 review).
_SELECT_NEWEST_RUN_FOR_SUBMISSION = (
    "SELECT run_id FROM criterion_score WHERE submission_id = :submission_id "
    "AND run_id = (SELECT run_id FROM run "
    "ORDER BY COALESCE(started_at, '') DESC, run_id DESC LIMIT 1) LIMIT 1"
)


_NO_PROVENANCE = (
    "provenance: no run has produced these grades yet, so there is no package, rubric or "
    "backend to name"
)


def _provenance_from(row: Mapping[str, Any], summary: Mapping[str, Any] | None) -> str:
    """The provenance line of one run (FR-CONSOLE-40): the run row's package version and
    rubric revision, and the persisted summary's backend profile and panel, plus the decision
    engine and build when the summary carries one. Credential-free by construction: the
    summary holds build identities only (CT-CONF-10)."""
    version = str(row.get("package_version_id") or "")
    rubric = version.rpartition("@")[2] or version
    parts = [f"package version {version}", f"rubric version {rubric}"]
    if summary:
        parts.append(f"backend profile {summary.get('backend_profile')}")
        panel = [str(ref.get("build_id")) for ref in summary.get("panel") or ()
                 if isinstance(ref, Mapping)]
        if panel:
            parts.append("panel " + ", ".join(panel))
        engine = summary.get("decision_engine")
        if isinstance(engine, Mapping):
            parts.append(f"decision engine {engine.get('provider')} {engine.get('build_id')}")
    else:
        parts.append("backend profile not recorded for this run")
    return " · ".join(parts)
