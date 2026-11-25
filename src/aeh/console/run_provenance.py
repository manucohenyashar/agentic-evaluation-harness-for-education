"""What produced a run's grades, in the teacher's words (FR-UI-51, R66; #878).

Every SPA view that shows a band or a total carries one footer line: *"Marked with <test name>
version <version label> · settings <profile in teacher words> · graders <panel in teacher
words>"*. The context read serves the parts per run (the test's name is the run's own
`package_id`, which the SPA already names), from the run's own row and its frozen
configuration (FR-CONF-15) — never today's configuration — so the line names what actually
graded the run. No build id, package-version hash or profile key reaches the teacher
(FR-UI-23): the profile is named by what it means for the school, the panel by how many AI
graders it held (and Jev, when the decision engine graded beside them).
"""

from __future__ import annotations

import json
from typing import Any, Callable

#: Each backend profile (`aeh.conf.BACKEND_PROFILES`) in the teacher's words.
PROFILE_WORDS: dict[str, str] = {
    "edge-local": "on this computer, nothing sent out",
    "cloud-hosted": "an online AI service",
    "dev-ci": "an online AI service, test setup",
}

#: What a profile this console cannot name reads as (never the raw key).
UNKNOWN_PROFILE_WORDS = "not recorded for this test"

#: The run row's columns the line is read from.
_SELECT_RUN_CONFIG = (
    "SELECT backend_profile, panel_config, run_config FROM run WHERE run_id = :run_id"
)


def _number_words(count: int) -> str:
    return {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}.get(count, str(count))


def graders_words(panel_size: int, jev: bool) -> str:
    """The panel in the teacher's words: ``"three AI graders"``, ``"... and Jev"``."""
    if panel_size <= 0:
        words = "not recorded for this test"
    else:
        words = f"{_number_words(panel_size)} AI grader{'' if panel_size == 1 else 's'}"
    return f"{words} and Jev" if jev and panel_size > 0 else words


def _frozen(row: Any) -> tuple[str, int, bool]:
    """The run's profile key, panel size and whether Jev graded, from its frozen configuration
    when it has one, else from the row's own `backend_profile` and `panel_config` arms."""
    profile = str(row["backend_profile"] or "")
    raw = row["run_config"]
    if isinstance(raw, str) and raw.strip():
        try:
            from aeh.conf import rehydrate_run_config

            config = rehydrate_run_config(json.loads(raw))
            return (str(config.backend_profile or profile), len(config.panel),
                    config.decision_engine is not None)
        except Exception:  # noqa: BLE001 — an unreadable freeze falls back to the row
            pass
    try:
        panel = json.loads(str(row["panel_config"] or "{}"))
        arms = panel.get("arms") or []
        # `panel_config_json` records the decision engine beside the arms when it was on.
        jev = bool(panel.get("decision_engine"))
    except (TypeError, ValueError, AttributeError):
        arms, jev = [], False
    return profile, len(arms) if isinstance(arms, list) else 0, jev


def run_provenance(app: Any, cohort_id: str, run_id: str, package_version_id: str,
                   version_label: Callable[[str], str | None]) -> dict[str, str] | None:
    """The footer's parts for one run, or None when its row cannot be read."""
    try:
        rows = list(app._store.cohort(cohort_id).query(_SELECT_RUN_CONFIG, run_id=run_id))
    except Exception:  # noqa: BLE001 — an unreadable ledger names nothing
        return None
    if not rows:
        return None
    profile, panel_size, jev = _frozen(rows[0])
    label = version_label(package_version_id) or ""
    return {
        # "1" of "version 1" (FR-CONSOLE-74); empty when the catalog cannot name it.
        "version_label": label.removeprefix("version ").strip(),
        "settings": PROFILE_WORDS.get(profile, UNKNOWN_PROFILE_WORDS),
        "graders": graders_words(panel_size, jev),
    }


__all__ = ["PROFILE_WORDS", "graders_words", "run_provenance"]
