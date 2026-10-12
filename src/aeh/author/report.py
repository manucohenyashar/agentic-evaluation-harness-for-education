"""The authoring report: the teacher-facing description of state and quality (FR-AUTHOR-12).

Sections, in the pinned order (`CT-AUTHOR-05`): **Documents** (each document, its page count,
how its text was obtained), **Steps** (per step and per item: outcome, model, attempts, the
failure reasons in fallback order), **Items** (per question: resolved / placeholder /
unresolved), the **Unresolved** list in review order, and the **Next command**. The report is
written even when every reasoning step failed, provided at least one document's text was
extracted (FR-AUTHOR-12) — a failed run is exactly when the teacher needs the trace.

Determinism (FR-AUTHOR-15) shapes the content: no timestamps, no absolute paths — the same
documents, chain and recordings produce a byte-identical report wherever it is written. No
credential, page image or wholesale document text appears at any level (FR-AUTHOR-19,
NFR-AUTHOR-04): the Documents section counts pages and names sources, it never quotes them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .extraction import AuthoringDocument
from .spec import Assembly, Gap, sentinel

#: The report's file name for a package: `<package>.authoring-report.md` (FR-AUTHOR-01).
def report_filename(package_id: str) -> str:
    return f"{package_id}.authoring-report.md"


#: The draft's file name for a package: `<package>.package.draft.toml` (FR-AUTHOR-01).
def draft_filename(package_id: str) -> str:
    return f"{package_id}.package.draft.toml"


def render_report(assembly: Assembly, documents: tuple[AuthoringDocument, ...],
                  outcomes: list[dict[str, Any]], models_used: list[str],
                  draft_path: Path) -> str:
    """The report's markdown. `outcomes` are the Steps section's records, in run order: each
    a mapping with `step`, `item_id`, `status`, `model`, `attempts`, `failures`."""
    lines: list[str] = [f"# Authoring report — {assembly.package_id}", ""]
    lines.extend(_documents(documents))
    lines.extend(_steps(outcomes))
    lines.extend(_items(assembly))
    lines.extend(_unresolved(assembly, outcomes))
    lines.extend(_next_command(assembly, draft_path))
    return "\n".join(lines)


def _documents(documents: tuple[AuthoringDocument, ...]) -> list[str]:
    lines = ["## Documents", ""]
    for document in documents:
        sources: list[str] = []
        text_layer = sum(1 for page in document.pages if page.source == "text layer")
        transcribed = sum(1 for page in document.pages if page.source == "transcriber")
        if text_layer:
            sources.append(f"{text_layer} page(s) from the text layer")
        if transcribed:
            sources.append(f"{transcribed} page(s) transcribed")
        missing = [page for page in document.pages if page.source == "missing"]
        for page in missing:
            sources.append(f"page {page.page_no} missing ({page.failure})")
        how = "; ".join(sources) if sources else "no text extracted"
        lines.append(f"- **{document.name}** — {document.page_count} page(s): {how}.")
    lines.append("")
    return lines


def _steps(outcomes: list[dict[str, Any]]) -> list[str]:
    lines = ["## Steps", ""]
    by_step: dict[str, list[dict[str, Any]]] = {}
    for outcome in outcomes:
        by_step.setdefault(outcome["step"], []).append(outcome)
    for step, records in by_step.items():
        lines.append(f"### {step}")
        lines.append("")
        for record in records:
            model = record["model"] or "—"
            line = (f"- **{record['item_id']}** — {record['status']}, model `{model}`, "
                    f"{record['attempts']} attempt(s).")
            lines.append(line)
            for reason in record["failures"]:
                lines.append(f"  - rejected: {reason}")
        lines.append("")
    return lines


def _items(assembly: Assembly) -> list[str]:
    lines = ["## Items", ""]
    for qid, status in assembly.statuses.items():
        detail = assembly.details.get(qid, "")
        suffix = f" — {detail}" if detail else ""
        lines.append(f"- **{qid}** — {status}{suffix}.")
    if not assembly.statuses:
        lines.append("No question was inventoried: every reasoning step failed (the report "
                     "is still written, FR-AUTHOR-12).")
    lines.append("")
    return lines


def _unresolved(assembly: Assembly, outcomes: list[dict[str, Any]]) -> list[str]:
    """The review walk's order: the items whose reasoning did not converge first (flagged
    first, `AF-09`'s oracle), then the named placeholders — each question's in-draft
    sentinels before its report-only omissions. The non-converged items are the run's
    unresolved outcome rows (CT-AUTHOR-03): a step-level record (the inventory, the grades
    table) whose reasoning never converged is listed beside the per-question rubric
    failures, whether or not a sentinel gap stands for it. Each entry carries what it is
    that did not converge — the sentinel string the review answers name, when a gap stands
    for it."""
    lines = ["## Unresolved", ""]
    unresolved_rows = [row for row in outcomes if row["status"] == "unresolved"]
    for row in unresolved_rows:
        failures = "; ".join(row["failures"]) or "every model in the chain was exhausted"
        lines.append(f"- {row['item_id']} — the reasoning did not converge: {failures}.")
    def priority(gap: Gap) -> tuple[int, int]:
        qid = gap.item_id.rsplit(" ", 1)[1] if " " in gap.item_id else None
        unresolved = qid is not None and assembly.statuses.get(qid) == "unresolved"
        return (0 if unresolved else 1, 0 if gap.in_draft else 1)

    ordered = sorted((gap for gap in assembly.gaps if gap.item_id != "approved_by"),
                     key=priority)  # stable: the assembly's order decides ties
    if not unresolved_rows and not ordered:
        lines.append("Nothing: every item resolved. The draft is ready for review.")
    for gap in ordered:
        lines.append(f"- {sentinel(gap.item_id)} — {gap.reason}. What to supply: "
                     f"{gap.supply}.")
    lines.append("")
    return lines


def _next_command(assembly: Assembly, draft_path: Path) -> list[str]:
    lines = ["## Next command", "",
             f"`aeh author review --draft {draft_path.name}`",
             "",
             "The review walk asks for every item above, one at a time, and for the "
             "approval (`approved_by`) — then, when nothing is left:",
             "",
             f"`aeh package build --spec {draft_path.name}`",
             ""]
    return lines


def summary_paragraph(assembly: Assembly, models_used: list[str], draft_path: Path,
                      outcomes: list[dict[str, Any]]) -> str:
    """FR-AUTHOR-18's one-paragraph summary: how many items resolved, how many are
    placeholders, which models were used, and the exact next commands — naming the actual
    draft file the review command will open. The counts are over the steps' own items
    (the outcome rows), the same denominator `DraftResult` reports."""
    resolved = sum(1 for row in outcomes if row["status"] in ("resolved", "derived"))
    placeholders = assembly.placeholder_count
    unresolved = sum(1 for row in outcomes if row["status"] == "unresolved")
    models = ", ".join(models_used) if models_used else "none (every call failed)"
    return (f"Drafted {assembly.package_id}: {resolved} item(s) resolved, "
            f"{placeholders} placeholder(s) to fill, {unresolved} unresolved. "
            f"Models used: {models}. Next: `aeh author review --draft {draft_path.name}`, "
            f"then `aeh package build --spec {draft_path.name}`.")