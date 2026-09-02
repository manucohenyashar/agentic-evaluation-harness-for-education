"""The run-start log line, at every level, with credentials present.

Case: `TC-CONF-18` (`NFR-CONF-02`, **P0**), test plan §5.1. Rung 1 — in-memory fakes.
Oracle: pattern scan.

Two claims, and they fail differently. *"No credential-shaped token in any emitted record"* is
the disclosure half — `DEBUG` is where a careless `logger.debug(cfg)` would dump the whole
configuration, and nobody runs at `DEBUG` until they are debugging something else at 3am.
*"The run-start line is emitted exactly once"* is the accounting half: `CT-CONF-13` promises ops
one line per run start, and a second line means either two runs or a double-count in whatever is
watching.
"""

from __future__ import annotations

import json
import logging

import pytest

from aeh.conf import LOGGER_NAME, RUN_START_EVENT, log_run_start, resolve_run_config
from tests.support.conf_builders import (
    HOSTED_PANEL_3,
    SENTINEL_CREDENTIAL,
    SYNTHETIC_COHORT,
    edge_cfg,
    hosted_cfg,
    seed_credentials,
)

#: Every level `TC-CONF-18` means by "at every log level including DEBUG".
LEVELS = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]

#: Token shapes rather than the sentinel alone — the oracle is a *pattern scan*. A record
#: carrying a key this test never planted is the case it exists to catch.
import re  # noqa: E402

CREDENTIAL_TOKEN = re.compile(
    r"(sk-[A-Za-z0-9_\-]{16,}|hf_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}"
    r"|(?i:bearer)\s+[A-Za-z0-9._\-]{16,}|\b[0-9a-f]{40,}\b)"
)


@pytest.fixture
def capture():
    """Attach a handler to the module's logger and return the record list.

    Attached to `aeh.conf`'s own logger rather than the root, so a record emitted by anything
    else in the process cannot make this pass or fail. `propagate` is left alone: the assertion
    is about what this module emits, not about where the application routes it.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger(LOGGER_NAME)
    handler = _Capture()
    handler.setLevel(logging.NOTSET)
    previous = logger.level
    logger.addHandler(handler)
    try:
        yield logger, records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _rendered(records: list[logging.LogRecord]) -> str:
    """Message **and** structured fields. `extra` is the half that gets missed: the message is
    what a console shows, the fields are what a shipper forwards to an aggregator."""
    return json.dumps(
        [(r.getMessage(), {k: repr(v) for k, v in r.__dict__.items()}) for r in records],
        sort_keys=True,
    )


@pytest.mark.parametrize("level", LEVELS, ids=lambda lv: logging.getLevelName(lv))
def test_tc_conf_18_no_credential_shaped_token_is_emitted_at_any_level(monkeypatch, capture, level):
    """TC-CONF-18 — *"Run start with credentials present, at every log level including DEBUG. No
    credential-shaped token in any emitted record."*

    Parametrized over every level rather than run once at `DEBUG`, because the failure mode is
    level-dependent by construction: a diagnostic line guarded by `if logger.isEnabledFor(DEBUG)`
    is invisible to a test that only runs at `INFO`, and that guard is where configuration dumps
    get added.
    """
    sentinel = seed_credentials(monkeypatch)
    logger, records = capture
    logger.setLevel(level)

    config = resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3), SYNTHETIC_COHORT)
    log_run_start(config, logger)

    rendered = _rendered(records)
    assert sentinel not in rendered, f"the sentinel was emitted at {logging.getLevelName(level)}"
    match = CREDENTIAL_TOKEN.search(rendered)
    assert match is None, (
        f"a credential-shaped token was emitted at {logging.getLevelName(level)}: "
        f"{match.group(0)[:12]}…"
    )


@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO], ids=["DEBUG", "INFO"])
def test_tc_conf_18_the_run_start_line_is_emitted_exactly_once(capture, level):
    """TC-CONF-18's second clause — *"the run-start line is emitted exactly once."*

    **Scoped to the levels the line passes, and that is a reading of the plan rather than a
    weakening.** `log_run_start` emits at `INFO`, so at `WARNING` and above the standard level
    filter drops it and the count is zero. Requiring one at `CRITICAL` would require emitting a
    routine run start at `CRITICAL` severity, which is worse than the problem it solves.

    So "at every log level" is read as qualifying the *credential* clause — no token leaks
    whatever level you are running at — and "exactly once" as the normal-operation claim. If the
    plan meant the line must survive any level, that is a change to `log_run_start`'s severity
    and an `ops` decision, not something to assert into existence here. Raised on the PR.

    The half that holds at **every** level is asserted separately below: never *two*.
    """
    logger, records = capture
    logger.setLevel(level)

    config = resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)
    log_run_start(config, logger)

    run_starts = [r for r in records if r.getMessage() == RUN_START_EVENT]
    assert len(run_starts) == 1, (
        f"expected exactly one run-start record at {logging.getLevelName(level)}, got "
        f"{len(run_starts)}"
    )
    assert len(records) == 1, (
        f"the module emitted {len(records)} records for one run start; CT-CONF-13 says one line "
        f"and 'nothing else'"
    )


@pytest.mark.parametrize("level", LEVELS, ids=lambda lv: logging.getLevelName(lv))
def test_tc_conf_18_a_run_start_never_emits_more_than_one_record_at_any_level(capture, level):
    """The half of "exactly once" that does hold at every level: **never more than one.**

    Level filtering can only ever remove records, so a count above one at any level is the
    module emitting twice — a double-count in whatever ops is watching, or a second line added
    "just for debugging" that nobody removed. That failure is level-independent, so this
    assertion is too.
    """
    logger, records = capture
    logger.setLevel(level)

    log_run_start(resolve_run_config(edge_cfg(), SYNTHETIC_COHORT), logger)

    assert len(records) <= 1, (
        f"one run start produced {len(records)} records at {logging.getLevelName(level)}"
    )


def test_tc_conf_18_two_run_starts_produce_two_lines_and_not_one(capture):
    """The other direction, so "at most one" cannot be satisfied by emitting nothing.

    A `log_run_start` that silently did nothing would pass every count assertion above. Two
    calls must produce two records, each carrying its own run's summary — otherwise ops sees one
    run where two started.
    """
    logger, records = capture
    logger.setLevel(logging.INFO)

    first = log_run_start(resolve_run_config(edge_cfg(), SYNTHETIC_COHORT), logger)
    second = log_run_start(
        resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3), SYNTHETIC_COHORT),
        logger,
    )

    assert len(records) == 2
    emitted = [r.__dict__["profile_summary"] for r in records]
    assert emitted == [first.to_canonical_json(), second.to_canonical_json()]
    assert emitted[0] != emitted[1], "both runs logged the same summary"


def test_tc_conf_18_the_record_carries_the_profile_summary(capture):
    """`CT-CONF-13`: the line contains `profile_summary()`. A record that is correctly singular
    and carries nothing useful satisfies the count and fails ops."""
    logger, records = capture
    logger.setLevel(logging.INFO)

    config = resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3), SYNTHETIC_COHORT)
    summary = log_run_start(config, logger)

    (record,) = records
    assert record.__dict__.get("profile_summary") == summary.to_canonical_json(), (
        "the emitted record must carry the same serialization M-ORCH stores, or TC-CONF-17's "
        "differential cannot hold"
    )
    for build in config.panel:
        assert build.build_id in record.__dict__["profile_summary"]


def test_tc_conf_18_resolution_itself_emits_nothing(capture):
    """`CT-CONF-13`'s "exactly one **per run start**" only holds if resolution is silent.

    `CT-CONF-12` lets `M-CONSOLE` resolve on the request path, so a line emitted from
    `resolve_run_config` would produce one record per *resolution* — several per run — and the
    count above would be a property of how many times someone opened a console page.
    """
    logger, records = capture
    logger.setLevel(logging.DEBUG)

    for _ in range(3):
        resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)

    assert records == [], f"resolution emitted {len(records)} log records"


def test_tc_conf_18_the_module_emits_no_metric_of_its_own(capture):
    """`CT-CONF-13`'s explicit non-promise: *"Nothing else, and no metric of its own."*

    Asserted over the module's public surface, because a metric is a thing that would have to be
    *exported* to be useful — a counter, a registry, a histogram someone can scrape. The reason
    it is a contract clause rather than a preference: ops depending on a metric this module never
    promised is how the module stops being free to change.
    """
    import aeh.conf

    metric_ish = [
        name
        for name in aeh.conf.__all__
        if any(word in name.lower() for word in ("metric", "counter", "gauge", "histogram", "registry"))
    ]
    assert not metric_ish, f"aeh.conf exports metric surfaces: {metric_ish}"
