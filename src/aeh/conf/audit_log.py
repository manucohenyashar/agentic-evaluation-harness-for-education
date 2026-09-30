"""The one structured log line a run start emits."""

from __future__ import annotations

import logging

from .run_config import ProfileSummary, RunConfig


# --- observability ---------------------------------------------------------------------------

#: The module's only logger. Design §3.1: "One structured log line per run start containing
#: `profile_summary()`. No metrics of its own."
LOGGER_NAME = "aeh.conf"


#: The single event this module emits. Named so a log pipeline can select on it without parsing.
RUN_START_EVENT = "run_start"


def log_run_start(config: RunConfig, logger: logging.Logger | None = None) -> ProfileSummary:
    """Emit the one structured log line a run start produces, and return what it carried.

    **Why this is not inside `resolve_run_config`.** `CT-CONF-12` gives `M-CONSOLE` the right to
    resolve on the request path, and `M-ORCH` resolves again when it constructs the run. If
    resolution logged, one run would produce two lines and `CT-CONF-13`'s "exactly one structured
    log line per run start" would be false — not because anything was wrong, but because the
    line was attached to the wrong event. Resolution is a pure function; a *run start* is a
    moment, and only the caller knows when it happened. Keeping the two apart also preserves
    `CT-CONF-05` purity and `CT-CONF-09`'s "writes nothing".

    Returns the summary so `M-ORCH` stores **the same record it logged** rather than building a
    second one — which is what makes `TC-CONF-17`'s differential ("byte-identical to the one
    logged at run start") a property of the code rather than a hope about it.

    Emits **no metric**, deliberately: `CT-CONF-13` names that as a non-promise, and the reason
    is that a telemetry surface here becomes something ops depends on and this module then
    cannot change.

    Takes no argument that could rebind an existing run (`CT-CONF-14`).
    """
    summary = config.profile_summary()
    (logger or logging.getLogger(LOGGER_NAME)).info(
        RUN_START_EVENT,
        extra={
            "event": RUN_START_EVENT,
            "backend_profile": summary.backend_profile,
            "panel_build_ref": summary.panel_build_ref,
            "profile_summary": summary.to_canonical_json(),
        },
    )
    return summary
