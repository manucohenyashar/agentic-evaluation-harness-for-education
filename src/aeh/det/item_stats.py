"""Per-question item statistics: how often each option was chosen, and the top distractor."""

from __future__ import annotations

from typing import Any

from .errors import DeterministicError
from .schema import DET_STATEMENTS
from .records import ItemOptionCount, ItemStatsEntry, ItemStatsReport


class ItemStatisticsMixin:
    """Writes and reads back per-question item statistics."""

    def item_stats(self, cohort_id: str) -> ItemStatsReport:
        """Read back one cohort's item statistics exactly as the cohort pass wrote them: per
        question, the summary figures and the per-option counts (FR-DET-07, CT-DET-08).

        Blank and unresolved counts stay separate; an unresolved count is a scanning problem, never
        item difficulty. A cohort with no runs gives an empty report with a None version; a cohort
        whose runs name several package versions is refused (see docs/code-notes/det.md)."""
        runs = self._cohort_runs(cohort_id)
        if not runs:
            return ItemStatsReport(
                cohort_id=cohort_id, package_version_id=None, items=()
            )
        versions = sorted({row["package_version_id"] for row in runs})
        if len(versions) > 1:
            raise DeterministicError(
                f"cohort {cohort_id!r}'s runs name several package versions "
                f"({versions}); one report cannot mix two instruments' figures "
                "and this module will not pick for you."
            )
        version = versions[0]
        durable_handle = self._store.durable()
        option_counts: dict[str, list[ItemOptionCount]] = {}
        for row in durable_handle.query(
            DET_STATEMENTS["select_item_stats_for_version"], v=version
        ):
            option_counts.setdefault(row["criterion_id"], []).append(
                ItemOptionCount(
                    criterion_id=row["criterion_id"],
                    option=row["option"],
                    chosen=row["chosen"],
                    is_key=bool(row["is_key"]),
                )
            )
        items = tuple(
            ItemStatsEntry(
                criterion_id=row["criterion_id"],
                n=row["n"],
                correct_rate=row["correct_rate"],
                blank_count=row["blank_count"],
                unresolved_count=row["unresolved_count"],
                options=tuple(option_counts.get(row["criterion_id"], ())),
            )
            for row in durable_handle.query(
                DET_STATEMENTS["select_item_summary_for_version"], v=version
            )
        )
        return ItemStatsReport(
            cohort_id=cohort_id, package_version_id=version, items=items
        )

    def _most_chosen_distractor(
        self, chosen: dict[str, int], key: tuple[str, ...]
    ) -> str | None:
        """The most-chosen option that is not in the key, with ties broken alphabetically so the
        report is deterministic (CT-DET-13)."""
        key_set = set(key)
        distractors = {
            option_id: count
            for option_id, count in chosen.items()
            if option_id not in key_set and count > 0
        }
        if not distractors:
            return None
        return sorted(distractors.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _write_item_statistics(
        self, tallies: dict[str, dict[str, Any]], version: str
    ) -> None:
        """Rewrite `mcq_item_stats` (per-option counts and key flag) and `mcq_item_summary` (n,
        correct rate, blank and unresolved counts) for each criterion, so a redelivery is
        idempotent (CT-DET-08). Tier D gets its own transaction: the store refuses cross-tier
        transactions, and the score rows are already committed in Tier C."""
        durable_handle = self._store.durable()
        with durable_handle.transaction() as tx:
            for criterion_id, tally in sorted(tallies.items()):
                tx.execute(
                    DET_STATEMENTS["delete_item_stats"],
                    v=version,
                    criterion_id=criterion_id,
                )
                key_set = set(tally["key"])
                option_ids = set(tally["chosen"]) | key_set | set(tally["options"])
                for option_id in sorted(option_ids):
                    tx.execute(
                        DET_STATEMENTS["insert_item_stat"],
                        v=version,
                        criterion_id=criterion_id,
                        option=option_id,
                        chosen=tally["chosen"].get(option_id, 0),
                        is_key=1 if option_id in key_set else 0,
                    )
                tx.execute(
                    DET_STATEMENTS["delete_item_summary"],
                    v=version,
                    criterion_id=criterion_id,
                )
                n = tally["n"]
                tx.execute(
                    DET_STATEMENTS["insert_item_summary"],
                    v=version,
                    criterion_id=criterion_id,
                    n=n,
                    correct_rate=(tally["correct"] / n) if n else 0.0,
                    blank_count=tally["blank"],
                    unresolved_count=tally["unresolved"],
                )
