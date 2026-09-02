"""`CT-CONF-08` … `CT-CONF-13` — the errors, the write ban, credentials, config, latency, logs.

Test plan §6.11.1, issue #9 (TS-58). Six clauses that are each a *promise a consumer relies on
without checking*: `M-ORCH` branches on the exception taxonomy, `M-STORE` assumes this module
never touched its rows, `M-CONSOLE` renders `profile_summary()` unredacted and resolves on the
request path, and ops alerts on one log line per run start.

Three of these overlap a §5 case — `C08` with `TC-CONF-15`, `C10` with `TC-CONF-11`/`SEC-01`,
`C13` with `TC-CONF-18`. §6.11 sanctions the overlap by name (*"the row stays, because the two run
at different times, against different implementations, for different reasons"*), and each case
below carries the half its §5 companion does not: `C08` the state assertion over a real store,
`C10` `exc.args` and `repr()` alongside `str()`, `C13` the "no metric of its own" scan.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

import pytest

from tests.support.conf_builders import (
    CREDENTIAL_ENV_VARS,
    EDGE_PANEL_3,
    HOSTED_JUDGE,
    HOSTED_PANEL_3,
    SENTINEL_CREDENTIAL,
    SENTINEL_WITH_METACHARACTERS,
    SYNTHETIC_COHORT,
    edge_cfg,
    hosted_cfg,
    seed_credentials,
)
from tests.support.guards import open_audit, write_audit
from tests.support.impl import CONF_MODULE, require

pytestmark = pytest.mark.contract


REAL_COHORT_KWARGS = {"cohort_id": "c-2026-9A-biology", "consent_class": "real"}


def _empty_run_store(root: Path) -> Path:
    """A real SQLite database with a real `run` table, and no rows.

    `M-STORE` does not exist yet (#10), so the table is created here — with the three columns
    design §3.1 says a `RunConfig` is serialized into. That is honest at rung 0: the assertion is
    "no row appeared in a real database", and a real database is what makes it an assertion
    rather than a restatement. When `M-STORE` lands, the schema it owns replaces this literal and
    the assertion does not change.
    """
    database = root / "harness.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE run ("
            "  run_id TEXT PRIMARY KEY,"
            "  backend_profile TEXT NOT NULL,"
            "  panel_config TEXT NOT NULL,"
            "  provider_config TEXT NOT NULL)"
        )
        connection.commit()
    finally:
        connection.close()
    return database


def _run_row_count(database: Path) -> int:
    connection = sqlite3.connect(database)
    try:
        return connection.execute("SELECT count(*) FROM run").fetchone()[0]
    finally:
        connection.close()


def _tree_snapshot(root: Path) -> dict[str, tuple[int, float]]:
    """Every file under `root`, with its size and mtime. The independent oracle for `C09`."""
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime)
        for path in root.rglob("*")
        if path.is_file()
    }


# --- TC-CONF-C08 — error ---------------------------------------------------------------------


def _provocations(conf, extra: dict | None = None):
    """One provocation per named error, as `(name, expected_type, call)`.

    Each reaches its exception through the **public** surface. Routing to a private helper would
    prove the type exists, not that a caller can meet it — and `M-ORCH` branches on these four
    from the two entry points and nothing else.

    `extra` is merged into every `cfg` these calls pass in. `TC-CONF-C10` uses it to seed the
    credential sentinel, and that parameter is not decoration: without it the scan runs against
    configs that hold no credential, so it passes against an implementation that copies the whole
    `cfg` into `exc.args`. A mutation harness caught exactly that — the docstring claimed the
    provocations carried credentials and the code did not.
    """
    extra = dict(extra or {})

    def cfg_with(base: dict) -> dict:
        merged = dict(base)
        merged.update(extra)
        return merged

    started = conf.resolve_run_config(edge_cfg(**{"panel": EDGE_PANEL_3}), SYNTHETIC_COHORT)
    row = dict(started.to_persisted_dict())
    real_cohort = conf.CohortRef(**REAL_COHORT_KWARGS)

    return [
        (
            "ConfigurationError",
            conf.ConfigurationError,
            # FR-CONF-01: absent HARNESS_PROFILE raises rather than defaulting.
            lambda: conf.resolve_run_config(cfg_with({}), SYNTHETIC_COHORT),
        ),
        (
            "UnresolvedModelRefError",
            conf.UnresolvedModelRefError,
            # A provider-pinned slug is a perfectly resolved identity and still wrong on
            # edge-local, where only a weights path names what ran.
            lambda: conf.resolve_run_config(
                cfg_with(edge_cfg(**{"panel": (HOSTED_JUDGE,)})), SYNTHETIC_COHORT
            ),
        ),
        (
            "BackendMismatchError",
            conf.BackendMismatchError,
            # A resume whose current configuration names a different backend.
            lambda: conf.rehydrate_run_config(
                row,
                cfg=cfg_with(
                    edge_cfg(**{"panel": EDGE_PANEL_3, "HARNESS_PROFILE": "cloud-hosted"})
                ),
            ),
        ),
        (
            "ConsentGateError",
            conf.ConsentGateError,
            # RISK-10: real student work bound to a remote provider with no override.
            lambda: conf.resolve_run_config(cfg_with(hosted_cfg()), real_cohort),
        ),
    ]


def test_tc_conf_c08_each_named_error_is_exact_not_retryable_and_leaves_no_run_row(tmp_path):
    """`CT-CONF-08` — all four named errors, each raised **before** the `run` row is written,
    none retryable, none leaving partial state.

    **The third assertion is the case.** Asserting the type is what a §5 case does; asserting
    that *no `run` row exists afterwards* is what catches a resolver that wrote the row first and
    validated second — a partial write that leaves an orphaned run for `M-ORCH` to resume into,
    and the assertion the plan calls "the one usually skipped".

    **What carries "no run row exists afterwards", and what does not.** The plan's oracle is a
    *state assertion over the store*, and at rung 0 that is not literally reachable: `M-CONF` is a
    leaf taking `(cfg, cohort)`, so no implementation — correct or broken — can be handed the
    database path, and `_run_row_count(database) == 0` is therefore true for every possible
    implementation. Review flagged it as decorative and was right.

    The assertion that does the work is `write_audit`, which patches `sqlite3.connect` to raise:
    a resolver that opened *any* database would surface as a `DiskWriteError` escaping the
    `pytest.raises` below, and a resolver that wrote a cache file instead lands in the write log.
    Both can fail; the row count cannot.

    The real store is kept as the **seam**, not as the oracle, and the row count with it: when
    `M-STORE` lands (#10) the schema it owns replaces this literal, the module can be handed a
    store, and the same line becomes an assertion. Deleting it now would mean rediscovering that
    this case needs one. The docstring says which is which so nobody mistakes the count for
    coverage — recorded in the PR as a finding about the plan's rung, not smuggled.

    `type(exc) is expected`, not `isinstance`. The four errors are deliberate **siblings** under a
    neutral base rather than a chain, so `isinstance` would let a `ConsentGateError` satisfy a
    `ConfigurationError` assertion if someone reparented them — and `M-ORCH` raising
    consent-required UX branches on exactly that distinction.
    """
    conf = require(CONF_MODULE, issue="#4")

    database = _empty_run_store(tmp_path)
    provocations = _provocations(conf)
    assert len(provocations) == 4, "CT-CONF-08 names four errors"

    # The taxonomy is **flat**: four siblings under a neutral base, never a chain. `type(x) is T`
    # below cannot catch a reparent — reparenting does not change an instance's type, it changes
    # what `except` catches — so the shape is asserted directly. `M-ORCH` branches on
    # `ConsentGateError` to raise consent-required UX; if it were a subclass of
    # `ConfigurationError`, an earlier `except ConfigurationError` would swallow it and RISK-10's
    # refusal would surface to the operator as "bad config".
    taxonomy = [expected for _, expected, _ in provocations]
    for error in taxonomy:
        assert error.__bases__ == (conf.RunConfigError,), (
            f"{error.__name__} does not descend directly from RunConfigError: "
            f"{[b.__name__ for b in error.__bases__]}"
        )
        for other in taxonomy:
            if other is not error:
                assert not issubclass(error, other), (
                    f"{error.__name__} is a subclass of {other.__name__}. CT-CONF-08's four "
                    "errors are siblings, so a consumer catching one never catches another."
                )

    for name, expected, call in provocations:
        before = _run_row_count(database)

        # `write_audit` patches `sqlite3.connect`, so the database is counted outside the block.
        with write_audit() as writes:
            with pytest.raises(conf.RunConfigError) as caught:
                call()

        assert type(caught.value) is expected, (
            f"{name}: expected exactly {expected.__name__}, got "
            f"{type(caught.value).__name__}. CT-CONF-08 is a closed taxonomy consumers branch on."
        )
        assert caught.value.retryable is False, (
            f"{name} reports itself retryable. None of these is: retrying a refused consent gate "
            "or an unrecognized profile produces the same refusal and a second audit entry."
        )
        assert writes == [], (
            f"{name} wrote to disk before raising: "
            + ", ".join(f"{w.api}({w.target!r})" for w in writes)
        )
        assert _run_row_count(database) == before == 0, (
            f"{name} left a run row behind. A failed resolution must leave nothing to clean up "
            "(CT-CONF-08)."
        )


# --- TC-CONF-C09 — state (rung 2) ------------------------------------------------------------


def test_tc_conf_c09_a_full_resolution_writes_nothing_anywhere(tmp_data_dir, tmp_path):
    """`CT-CONF-09` — writes nothing. No database, no file, no blob.

    **Rung 2**: a real SQLite database, a real blob directory and a real data directory, not
    doubles. `tmp_data_dir` already builds `packages/`, `cohorts/` and `blobs/`; the database is
    created here. Marked `contract` and not `integration` — `-m "contract and integration"` is
    reserved for §6.13's pairwise `Requires` cases, and a temp-dir SQLite file costs
    milliseconds.

    **The negative half is the case.** A module that "helpfully" caches its resolution to disk —
    a memoized hardware table, a written `panel_build_ref` — passes every functional test in this
    repository. It also makes `M-STORE`'s ownership of those rows a fiction and breaks
    `CT-CONF-05` purity the moment the cache goes stale.

    Two independent oracles again. `write_audit` catches a write through the APIs it patches; the
    directory snapshot catches one that went around them (`os.open`, a C extension), and it is
    taken over the *whole* tree so a new file counts as much as a modified one.

    Every surface is exercised, not just `resolve_run_config`: `to_persisted_dict`,
    `profile_summary`, `log_run_start` and `rehydrate_run_config` are each a plausible place for
    a cache to appear, and `log_run_start` is the one that actually emits something.
    """
    conf = require(CONF_MODULE, issue="#4")

    database = _empty_run_store(tmp_data_dir)
    before = _tree_snapshot(tmp_data_dir)
    assert before, "the data directory is empty, so the snapshot would pass vacuously"

    cfg = edge_cfg(**{"panel": EDGE_PANEL_3})

    with write_audit() as writes:
        config = conf.resolve_run_config(cfg, SYNTHETIC_COHORT)
        persisted = config.to_persisted_dict()
        config.profile_summary()
        conf.log_run_start(config)
        conf.rehydrate_run_config(dict(persisted))

    assert writes == [], (
        "CT-CONF-09: M-CONF wrote to disk — "
        + ", ".join(f"{w.api}({w.target!r})" for w in writes)
    )
    assert _tree_snapshot(tmp_data_dir) == before, (
        "CT-CONF-09: the data directory changed on disk during resolution, even though no "
        "audited write API was called. Something went around the audit."
    )
    assert _run_row_count(database) == 0


# --- TC-CONF-C10 — security ------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentinel", [SENTINEL_CREDENTIAL, SENTINEL_WITH_METACHARACTERS], ids=["plain", "metachars"]
)
def test_tc_conf_c10_no_credential_reaches_any_of_the_four_surfaces(monkeypatch, caplog, sentinel):
    """`CT-CONF-10` — the sentinel appears in no `to_persisted_dict()`, no `profile_summary()`, no
    exception message from any of the four errors, and no emitted log line.

    **Assert over the artifacts, never over intent.** The oracle is a scan of four rendered
    surfaces, so it holds against an implementation that redacts correctly *and* against one that
    never held a credential to begin with — and it fails against one that filters `str(exc)` and
    leaves the value in `exc.args`, which is the gap `str()`-only scanning leaves open. So each
    exception is scanned three ways: `str`, `repr`, and every element of `args`.

    The sentinel is seeded into **both** the process environment and `cfg`, under
    credential-shaped keys. Either alone is vacuous in a different direction:
    `environment_snapshot()` lifts only the six `HARNESS_*` keys, so an environment-only seed never
    reaches the module and the scan would pass against an implementation that copied the key
    straight into `provider_config`. A `cfg`-only seed proves nothing about the module reaching
    out for a credential on its own.

    It is **not** seeded into `HARNESS_PROFILE` or the other echoable keys. Those are config
    values the module deliberately echoes to make a refusal actionable; a credential does not live
    in them, and putting one there would assert that the module must stop naming the bad profile.
    """
    conf = require(CONF_MODULE, issue="#4")

    seed_credentials(monkeypatch, sentinel)
    credentials = {var: sentinel for var in CREDENTIAL_ENV_VARS}

    surfaces: dict[str, str] = {}

    config = conf.resolve_run_config(
        hosted_cfg(**{"panel": HOSTED_PANEL_3, **credentials}), SYNTHETIC_COHORT
    )
    surfaces["to_persisted_dict()"] = repr(config.to_persisted_dict())

    summary = config.profile_summary()
    surfaces["profile_summary()"] = repr(summary) + summary.to_canonical_json()

    for name, _expected, call in _provocations(conf, extra=credentials):
        # Each provocation re-run with credentials merged into its config, so the message is
        # rendered from a mapping that actually holds one.
        try:
            call()
        except conf.RunConfigError as exc:
            surfaces[f"{name}.str"] = str(exc)
            surfaces[f"{name}.repr"] = repr(exc)
            surfaces[f"{name}.args"] = repr(exc.args)

    with caplog.at_level(logging.DEBUG, logger=conf.LOGGER_NAME):
        conf.log_run_start(config)
    surfaces["log"] = "\n".join(
        record.getMessage() + repr(record.__dict__) for record in caplog.records
    )
    assert caplog.records, "no log record was captured, so the log surface is unscanned"

    leaked = sorted(where for where, rendered in surfaces.items() if sentinel in rendered)
    assert not leaked, (
        f"CT-CONF-10: the credential sentinel reached {leaked}. Callers persist and display "
        "these surfaces without redaction (NFR-CONF-02)."
    )


# --- TC-CONF-C11 — config --------------------------------------------------------------------


def test_tc_conf_c11_the_snapshot_lifts_exactly_the_six_documented_keys(monkeypatch):
    """`CT-CONF-11` names six `HARNESS_*` keys. `environment_snapshot()` lifts those and nothing
    else — in particular, no credential.

    Set equality against the clause's own list, transcribed here rather than read from
    `HARNESS_KEYS`, so a seventh key added to the module is a failure rather than a silently
    widened surface. A key that reaches `cfg` without appearing in the clause is a configuration
    input no operator was told about.
    """
    conf = require(CONF_MODULE, issue="#4")

    documented = {
        "HARNESS_PROFILE",
        "HARNESS_HARDWARE_PROFILE",
        "HARNESS_COST_CEILING",
        "HARNESS_COST_CURRENCY",
        "HARNESS_CONCURRENCY",
        "HARNESS_ALLOW_REMOTE_REAL_WORK",
    }
    assert set(conf.HARNESS_KEYS) == documented

    seed_credentials(monkeypatch)
    for key in documented:
        monkeypatch.setenv(key, "x")

    snapshot = conf.environment_snapshot()

    assert set(snapshot) == documented
    for var in CREDENTIAL_ENV_VARS:
        assert var not in snapshot


def test_tc_conf_c11_with_no_key_set_resolution_raises_rather_than_selecting_a_backend():
    """"The negative that matters" — with **no** key set, resolution raises.

    A silent default here selects a grader by accident: an operator who forgot to export
    `HARNESS_PROFILE` gets a run graded by whichever backend the default named, and nothing in
    the record says the choice was not theirs. `FR-CONF-01` is explicit that absence raises
    rather than defaults, and `ConfigurationError` exactly — `M-CONSOLE` renders it as a
    preflight refusal.
    """
    conf = require(CONF_MODULE, issue="#4")

    with pytest.raises(conf.ConfigurationError):
        conf.resolve_run_config({}, SYNTHETIC_COHORT)


def test_tc_conf_c11_a_key_present_only_in_the_environment_does_not_select_a_backend(monkeypatch):
    """Absence raises **even when the environment could have answered** — which is the half that
    makes the previous case mean something.

    `resolve_run_config({}, cohort)` raises in a process whose environment is also empty, so it
    passes against an implementation that falls back to `os.environ.get("HARNESS_PROFILE")`. That
    fallback is the exact shape `NFR-CONF-01` and `CT-CONF-05` forbid: resolution stops being a
    pure function of its arguments, `M-CONFORM` cannot construct two configs differing only in
    backend, and the operator's shell decides the grader.

    So the key is exported and the call is made with a `cfg` that omits it. The environment is
    lifted by `environment_snapshot()` — the caller's job — and never read by the resolver.
    """
    conf = require(CONF_MODULE, issue="#4")

    monkeypatch.setenv("HARNESS_PROFILE", "cloud-hosted")
    monkeypatch.setenv("HARNESS_HARDWARE_PROFILE", "unified-large")
    monkeypatch.setenv("HARNESS_COST_CEILING", "10.00")
    monkeypatch.setenv("HARNESS_COST_CURRENCY", "USD")

    with pytest.raises(conf.ConfigurationError):
        conf.resolve_run_config({}, SYNTHETIC_COHORT)

    # And a cfg missing only the profile is refused too, so the fallback has no partial form.
    cfg = edge_cfg()
    cfg.pop("HARNESS_PROFILE")
    with pytest.raises(conf.ConfigurationError):
        conf.resolve_run_config(cfg, SYNTHETIC_COHORT)

    # The same leak on the consent flag, which is the one that costs something. A
    # `cfg.get(key, os.environ.get(key))` fallback is invisible to every other case in this file:
    # `TC-CONF-C05` sets the flag in the environment but pairs it with a synthetic cohort and an
    # edge-local config, both of which return before the flag is read, and the default-false case
    # below never touches the environment at all. The failure mode is RISK-10 at its worst — an
    # operator who once exported HARNESS_ALLOW_REMOTE_REAL_WORK dispatches a `real` cohort's work
    # to a remote provider from a config that says nothing about consent. Found by review.
    monkeypatch.setenv("HARNESS_ALLOW_REMOTE_REAL_WORK", "true")
    monkeypatch.setenv("allow_remote_real_work_supplied_by", "an-operator-shell")

    hosted = hosted_cfg()
    assert "HARNESS_ALLOW_REMOTE_REAL_WORK" not in hosted

    with pytest.raises(conf.ConsentGateError):
        conf.resolve_run_config(hosted, conf.CohortRef(**REAL_COHORT_KWARGS))


def test_tc_conf_c11_allow_remote_real_work_defaults_to_false():
    """The one key the clause gives a documented default: `HARNESS_ALLOW_REMOTE_REAL_WORK`
    (default false).

    Asserted at the parse and at the **gate**, because they are separable and only the second
    matters. A parse that returns `False` while the gate reads the raw value would pass the first
    assertion and dispatch non-consented student work to a remote provider (RISK-10, Critical).
    So: absent key plus a `real` cohort plus a remote backend must raise `ConsentGateError`.
    """
    conf = require(CONF_MODULE, issue="#4")

    assert conf.parse_allow_remote_real_work(None) is False

    cfg = hosted_cfg()
    assert "HARNESS_ALLOW_REMOTE_REAL_WORK" not in cfg

    with pytest.raises(conf.ConsentGateError):
        conf.resolve_run_config(cfg, conf.CohortRef(**REAL_COHORT_KWARGS))


@pytest.mark.parametrize(
    "key, first, second, field",
    [
        ("HARNESS_PROFILE", "cloud-hosted", "dev-ci", "backend_profile"),
        ("HARNESS_HARDWARE_PROFILE", "unified-large", "unified-small", "hardware_profile"),
        ("HARNESS_COST_CEILING", "12.50", "3.25", "cost_ceiling"),
        ("HARNESS_COST_CURRENCY", "USD", "EUR", "cost_currency"),
        ("HARNESS_CONCURRENCY", "2", "1", "concurrency_ceiling"),
    ],
)
def test_tc_conf_c11_moving_each_key_changes_externally_visible_behaviour(key, first, second, field):
    """"Assert the externally-visible behaviour change when it moves" — per key.

    A key the module reads and then ignores is worse than a key it does not read: the operator
    sets it, the value appears in the environment, and the run behaves as though it were never
    set. Nothing in `profile_summary()` contradicts them.

    So each key is moved between two legal values and the resulting `RunConfig` field must
    differ. `HARNESS_ALLOW_REMOTE_REAL_WORK` is absent from this table because its externally
    visible change is an exception rather than a field — asserted in the case above.
    """
    conf = require(CONF_MODULE, issue="#4")

    def resolve(value):
        if key == "HARNESS_HARDWARE_PROFILE":
            cfg = edge_cfg(**{key: value})
        else:
            cfg = hosted_cfg(**{key: value})
            if key == "HARNESS_PROFILE" and value == "dev-ci":
                cfg.pop("retention_setting", None)
        return getattr(conf.resolve_run_config(cfg, SYNTHETIC_COHORT), field)

    assert resolve(first) != resolve(second), (
        f"CT-CONF-11: moving {key} from {first!r} to {second!r} left {field} unchanged, so the "
        "key is read and ignored."
    )


# --- TC-CONF-C12 — perf ----------------------------------------------------------------------


#: `CT-CONF-12`'s stated bound, in milliseconds. **A literal, deliberately, and not an env-gated
#: knob** — the repo's convention 3 asks for a knob on every environment-sensitive constant, and
#: the plan overrides it here for a reason worth keeping: *"A loosened bound must edit this number
#: in review (RISK-33)."* A knob is precisely a way to loosen the bound without editing the number.
RESOLUTION_BUDGET_MS = 50.0


def test_tc_conf_c12_resolution_completes_under_50ms_and_touches_no_io(network_guard):
    """`CT-CONF-12` — under 50 ms, and no model call, no network call, no database read.

    **The second half is the durable one.** The latency figure could be met by a warm cache that
    still reads the database on every call — fast, and it would take away `M-CONSOLE`'s right to
    resolve on the request path the moment the database is under load. So the I/O assertion runs
    on its own, outside the timed section, using `open_audit` (which records `sqlite3.connect`
    alongside file reads) and the autouse socket guard.

    **Best-of-N, not mean or single-shot.** A single measurement on a loaded CI box fails for
    reasons that have nothing to do with `M-CONF`, and a flaky P1 case gets weakened rather than
    investigated (§4.6's flake policy makes that a defect, which is exactly the pressure to
    avoid). The minimum over `N` runs is the honest measure of what the function costs when the
    scheduler is not interfering; it does not loosen the bound, it removes the noise. The number
    stays 50.
    """
    conf = require(CONF_MODULE, issue="#4")

    cfg = edge_cfg(**{"panel": EDGE_PANEL_3})

    # No I/O — asserted separately so the timing is not distorted by the audit's patches.
    with open_audit() as reads:
        conf.resolve_run_config(cfg, SYNTHETIC_COHORT)
    assert reads == [], (
        "CT-CONF-12: resolution read a file or opened a database — "
        + ", ".join(f"{r.api}({r.target!r})" for r in reads)
    )
    network_guard.assert_no_network()

    conf.resolve_run_config(cfg, SYNTHETIC_COHORT)  # warm the import-time paths

    best_ms = min(
        (
            (lambda start: (conf.resolve_run_config(cfg, SYNTHETIC_COHORT),
                            (time.perf_counter() - start) * 1000.0)[1])(time.perf_counter())
        )
        for _ in range(7)
    )

    assert best_ms < RESOLUTION_BUDGET_MS, (
        f"CT-CONF-12: resolution took {best_ms:.2f} ms, over the {RESOLUTION_BUDGET_MS} ms bound "
        "M-CONSOLE resolves on the request path against (RISK-33). Loosening this number is a "
        "review decision, not a fix."
    )


# --- TC-CONF-C13 — observe -------------------------------------------------------------------


def test_tc_conf_c13_exactly_one_structured_line_per_run_start_carrying_the_summary(caplog):
    """`CT-CONF-13`, first half — exactly one structured log line per run start, containing
    `profile_summary()`.

    "Exactly one" is asserted at `DEBUG`, so a second line emitted at a lower level than `INFO`
    counts. Ops alerts on this event; two lines per start double every rate.

    The line must *carry* the summary rather than merely mention the run: the assertion is that
    the record's `profile_summary` field parses back to the same canonical JSON the summary
    renders, which is what makes the log line a record rather than a notification.
    """
    conf = require(CONF_MODULE, issue="#4")

    config = conf.resolve_run_config(edge_cfg(**{"panel": EDGE_PANEL_3}), SYNTHETIC_COHORT)

    with caplog.at_level(logging.DEBUG, logger=conf.LOGGER_NAME):
        summary = conf.log_run_start(config)

    records = [r for r in caplog.records if r.name == conf.LOGGER_NAME]
    assert len(records) == 1, (
        f"CT-CONF-13: a run start emitted {len(records)} records, not one: "
        + ", ".join(r.getMessage() for r in records)
    )
    assert records[0].__dict__.get("event") == conf.RUN_START_EVENT
    assert records[0].__dict__.get("profile_summary") == summary.to_canonical_json()


def test_tc_conf_c13_resolution_and_rehydration_emit_nothing_at_all(caplog):
    """The half that makes "exactly one **per run start**" true rather than approximately true.

    A run start is a moment only the caller knows about. If `resolve_run_config` logged, then
    `M-CONSOLE` resolving on the request path (`CT-CONF-12` gives it that right) would emit a run
    start for a run that never began, and ops would see starts that outnumber runs.
    """
    conf = require(CONF_MODULE, issue="#4")

    cfg = edge_cfg(**{"panel": EDGE_PANEL_3})

    with caplog.at_level(logging.DEBUG):
        config = conf.resolve_run_config(cfg, SYNTHETIC_COHORT)
        conf.rehydrate_run_config(dict(config.to_persisted_dict()))

    assert [r for r in caplog.records if r.name.startswith("aeh")] == []


def test_tc_conf_c13_the_module_emits_no_metric_of_its_own(repo_root):
    """`CT-CONF-13`, second half — "Nothing else, and no metric of its own."

    **Both halves are contract**, and this is the one that is not a behaviour: it is a promise
    about what will *not* grow here. A counter added for a good reason becomes something ops
    alerts on, and then this module cannot change it — the clause is what keeps the module free.

    A source scan, because there is nothing to observe at runtime: a metric that is registered
    and never incremented is already the dependency. Every metrics library the repo could plausibly
    reach for is named, plus the bare instrument names that a hand-rolled registry uses.
    """
    conf = require(CONF_MODULE, issue="#4")
    import ast

    source_path = Path(conf.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))

    forbidden_modules = {
        "prometheus_client", "statsd", "datadog", "opentelemetry", "newrelic", "metrics",
    }
    forbidden_names = {
        "Counter", "Gauge", "Histogram", "Summary", "Meter", "incr", "increment", "timing",
        "observe", "gauge", "record_metric", "emit_metric",
    }

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [
                f"import {a.name}" for a in node.names
                if a.name.split(".")[0] in forbidden_modules
            ]
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in forbidden_modules:
                offenders.append(f"from {node.module} import ...")
            offenders += [
                f"from {node.module} import {a.name}" for a in node.names
                if a.name in forbidden_names
            ]
        elif isinstance(node, ast.Call):
            called = node.func
            name = getattr(called, "attr", None) or getattr(called, "id", None)
            if name in forbidden_names:
                offenders.append(f"call to {name}() at line {node.lineno}")

    assert not offenders, (
        "CT-CONF-13: M-CONF has grown a metric surface, which ops will come to depend on and "
        "this module then cannot change:\n  " + "\n  ".join(offenders)
    )

    # And nothing metric-shaped on the public surface either.
    exported = [name for name in conf.__all__ if name.lower().replace("_", "").find("metric") >= 0]
    assert not exported, f"CT-CONF-13: the module exports {exported}"
