"""No credential value reaches any persisted dict, log line or exception message.

Cases: `TC-CONF-11` (`FR-CONF-11`, `NFR-CONF-02`, **P0**, RISK-10 **Critical**) and `SEC-01`
(§6.5). Rung 0, with a log capture handler installed.

Oracle, verbatim from `FR-CONF-11`: *"a test asserting that the serialized `provider_config`
matches no credential pattern is the acceptance form of this requirement."*

**Why the sentinel goes into `cfg` and not only into the environment.** `TC-CONF-11`'s
precondition says "an environment snapshot carrying the sentinel credential in
`OPENROUTER_API_KEY`" — but `environment_snapshot()` lifts only the six `HARNESS_*` keys, so a
credential seeded in the environment alone never reaches the module. A scan built that way finds
nothing **whatever the module does**, and stays green against an implementation that copies the
key straight into `to_persisted_dict()`. The two halves test different claims: the environment
half that the module never *reaches for* a credential, the `cfg` half that it never *passes one
through*. Both are here.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.parse

import pytest

from aeh.conf import (
    BackendMismatchError,
    CohortRef,
    ConfigurationError,
    ConsentGateError,
    ModelRef,
    UnresolvedModelRefError,
    log_run_start,
    rehydrate_run_config,
    resolve_run_config,
)
from tests.support.conf_builders import (
    CREDENTIAL_ENV_VARS,
    HOSTED_PANEL_3,
    SENTINEL_CREDENTIAL,
    SENTINEL_WITH_METACHARACTERS,
    SYNTHETIC_COHORT,
    edge_cfg,
    hosted_cfg,
    seed_credentials,
)


#: Credential *shapes*, for the pattern scan `FR-CONF-11` names as its acceptance form. Chosen to
#: match a key this suite never planted — which is the whole difference between a pattern scan and
#: a sentinel scan, and the reason the requirement asks for one.
CREDENTIAL_PATTERNS = {
    "openrouter / openai key": re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    "bearer token": re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    "hugging face token": re.compile(r"hf_[A-Za-z0-9]{16,}"),
    "aws access key id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "long opaque hex": re.compile(r"\b[0-9a-f]{32,}\b"),
    "secret-ish assignment": re.compile(
        r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+"
    ),
}


def encodings_of(sentinel: str) -> dict[str, str]:
    """The forms `TC-CONF-11` step 2 names: *"in raw, base64 and URL-encoded form"*.

    A value that survives a redaction pass in one encoding and not another is the failure this
    exists to catch — a filter matching `sk-or-` misses the base64 of the same string entirely.
    """
    return {
        "raw": sentinel,
        "base64": base64.b64encode(sentinel.encode()).decode(),
        "url-encoded": urllib.parse.quote(sentinel, safe=""),
    }


@pytest.fixture
def captured_records():
    """A log capture handler on the module's own logger, at `DEBUG` — `TC-CONF-18` and `SEC-01`
    both specify "at every log level including DEBUG", which is where a careless
    `logger.debug(cfg)` would put the whole configuration."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("aeh.conf")
    handler = _Capture()
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _cfg_with_credential_in_every_field(sentinel: str) -> dict:
    """A `cloud-hosted` config carrying the sentinel in every caller-supplied string the module
    touches — the places a credential actually arrives from, as opposed to the places it is
    supposed to.

    A key pasted into a `build_id` query string is not hypothetical: that is how a self-hosted
    endpoint is usually addressed.
    """
    poisoned_judge = ModelRef(
        role="judge",
        provider="openrouter",
        build_id=f"proxy/llama-3.3-70b?key={sentinel}@2024-12-06",
        quantization=None,
    )
    return hosted_cfg(
        "cloud-hosted",
        panel=(poisoned_judge,),
        prompt_template_v=f"conf-v1.0.0-{sentinel}",
        # The override is on so this config resolves against a `real` cohort, which is what puts
        # the sentinel into the *supplier* field — the one caller-supplied string that
        # `FR-CONF-08` requires be recorded somewhere. It must still not reach the `run` row.
        HARNESS_ALLOW_REMOTE_REAL_WORK="true",
        allow_remote_real_work_supplied_by=sentinel,
    )


def _render(value) -> str:
    """Everything a scan should see, flattened. JSON for the structural surfaces so nesting
    cannot hide a value, `repr` as a backstop for anything JSON refuses."""
    try:
        return json.dumps(value, sort_keys=True, default=repr)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return repr(value)


# --- TC-CONF-11 -------------------------------------------------------------------------------


@pytest.mark.parametrize("sentinel", [SENTINEL_CREDENTIAL, SENTINEL_WITH_METACHARACTERS])
def test_tc_conf_11_step_2_the_persisted_dict_carries_no_credential(monkeypatch, sentinel):
    """TC-CONF-11 step 2 — *"assert the sentinel appears nowhere in the JSON encoding, at any
    nesting depth, in raw, base64 and URL-encoded form."*

    This is the requirement's own named acceptance form: the serialized `provider_config`
    matching no credential pattern.

    The second parametrization is `TC-CONF-11`'s stated variant — *"a credential containing
    regex metacharacters does not break the scan"*. A scanner that compiled the sentinel as a
    pattern would raise or silently mis-match here and nowhere else.
    """
    seed_credentials(monkeypatch, sentinel)
    config = resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3), SYNTHETIC_COHORT)

    rendered = _render(config.to_persisted_dict())

    for form, needle in encodings_of(sentinel).items():
        assert needle not in rendered, f"{form} sentinel reached to_persisted_dict()"


def test_tc_conf_11_step_3_the_run_start_log_line_carries_no_credential(
    monkeypatch, captured_records
):
    """TC-CONF-11 step 3 — *"assert the same over captured log records including their
    structured `extra` fields."*

    `extra` is the half that gets missed: the formatted message is what a reader sees, but the
    structured fields are what a log shipper forwards, and a credential in `extra` reaches the
    aggregator without ever appearing on anyone's console.
    """
    sentinel = seed_credentials(monkeypatch)
    config = resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3), SYNTHETIC_COHORT)

    log_run_start(config)

    assert captured_records, "the run-start line was not emitted at all"
    rendered = _render([(r.getMessage(), r.__dict__) for r in captured_records])
    for form, needle in encodings_of(sentinel).items():
        assert needle not in rendered, f"{form} sentinel reached a log record"


def test_tc_conf_11_step_3_the_profile_summary_carries_no_credential(monkeypatch):
    """`CT-CONF-10` names `profile_summary()` alongside `to_persisted_dict()`: consumers *"may
    persist and display both without redaction"*, and `CT-CONSOLE-10` puts the summary under
    every grade a teacher reads."""
    sentinel = seed_credentials(monkeypatch)
    config = resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3), SYNTHETIC_COHORT)

    rendered = config.profile_summary().to_canonical_json()
    for form, needle in encodings_of(sentinel).items():
        assert needle not in rendered, f"{form} sentinel reached profile_summary()"


def _provoke_each_declared_error(sentinel: str, run_row: dict) -> dict[type, BaseException]:
    """One instance of each of `CT-CONF-08`'s four types, every one provoked by input that
    *carries the sentinel* — provoking them with clean input would assert nothing."""
    poisoned = _cfg_with_credential_in_every_field(sentinel)
    # The consent gate can only refuse a config whose override is *off*, and the poisoned config
    # carries one so the rest of the suite can resolve it. Same sentinel, override removed.
    unauthorised = {k: v for k, v in poisoned.items() if k != "HARNESS_ALLOW_REMOTE_REAL_WORK"}

    provocations = [
        (ConfigurationError, lambda: resolve_run_config(
            {**poisoned, "retention_setting": sentinel}, SYNTHETIC_COHORT)),
        (UnresolvedModelRefError, lambda: resolve_run_config(
            {**poisoned, "panel": (ModelRef("judge", "openrouter", f"Friendly-{sentinel}", None),)},
            SYNTHETIC_COHORT)),
        (ConsentGateError, lambda: resolve_run_config(unauthorised, CohortRef("c-real", "real"))),
        (BackendMismatchError, lambda: rehydrate_run_config(run_row, poisoned)),
    ]

    raised: dict[type, BaseException] = {}
    for expected, call in provocations:
        try:
            call()
        except BaseException as exc:  # noqa: BLE001
            raised[expected] = exc
        assert expected in raised, f"failed to provoke {expected.__name__}"
        assert type(raised[expected]) is expected, (
            f"expected {expected.__name__}, got {type(raised[expected]).__name__}"
        )
    return raised


def test_tc_conf_11_step_4_no_declared_exception_message_carries_a_credential(monkeypatch):
    """TC-CONF-11 step 4 — each of the four declared errors forced *with the credential
    present*; the sentinel absent from `str(exc)`, `repr(exc)` and `exc.args`.

    All three surfaces, because they diverge: `str` may be overridden, `repr` is what a
    traceback prints, and `args` is what a structured logger serializes. A message that redacts
    on the way to `str` while leaving the raw value in `args` leaks through the log pipeline and
    nowhere a human would notice.
    """
    sentinel = seed_credentials(monkeypatch)
    run_row = resolve_run_config(edge_cfg(), SYNTHETIC_COHORT).to_persisted_dict()

    raised = _provoke_each_declared_error(sentinel, run_row)

    for expected, exc in raised.items():
        rendered = _render([str(exc), repr(exc), [repr(a) for a in exc.args]])
        for form, needle in encodings_of(sentinel).items():
            assert needle not in rendered, (
                f"{form} sentinel reached {expected.__name__}'s message, repr or args"
            )


def test_tc_conf_11_the_serialized_provider_config_matches_no_credential_pattern(monkeypatch):
    """The acceptance form `FR-CONF-11` names **verbatim**: *"a test asserting that the
    serialized `provider_config` matches no credential pattern is the acceptance form of this
    requirement."*

    Two things differ from the steps above and both are the requirement's wording, not a
    weakening: **`provider_config`** specifically, and by **pattern** rather than by sentinel. A
    pattern scan catches a credential this test never planted, which is the only form of the
    assertion that survives someone adding a field to that dict.
    """
    seed_credentials(monkeypatch)
    poisoned = _cfg_with_credential_in_every_field(SENTINEL_CREDENTIAL)
    config = resolve_run_config(poisoned, CohortRef("c-real", "real"))

    provider_config = _render(config.to_persisted_dict()["provider_config"])

    for name, pattern in CREDENTIAL_PATTERNS.items():
        assert not pattern.search(provider_config), (
            f"serialized provider_config matches the {name} credential pattern"
        )


@pytest.mark.parametrize(
    "currency",
    [SENTINEL_CREDENTIAL, "sk-or-v1-abcdefghijklmnop", "usd", "US", "USDX", "", "  ", "$"],
)
def test_tc_conf_11_no_free_text_can_reach_provider_config_through_the_currency(currency):
    """The assertion above is only meaningful if something *could* have reached that dict.

    `HARNESS_COST_CURRENCY` was the one caller free-text field landing in `provider_config`
    verbatim — planting a sentinel there put it straight into the `run` row and the pattern scan
    caught it, which is how this case was found. `_resolve_cost` now requires an ISO-4217 alpha
    code, so every value in `provider_config` is a validated enum, an integer, a `Decimal` string
    or three uppercase letters.

    That turns `FR-CONF-11`'s acceptance form from "a scan that happened to find nothing" into a
    structural property, which is the difference between a test that passes and a guarantee.
    """
    with pytest.raises(ConfigurationError):
        resolve_run_config(
            hosted_cfg("cloud-hosted", HARNESS_COST_CURRENCY=currency), SYNTHETIC_COHORT
        )


def test_tc_conf_11_provider_config_holds_no_free_text_at_all():
    """The structural statement itself, asserted rather than left to the reader.

    Every value in `provider_config` is drawn from a closed set, an integer, or a canonical
    numeric string. A field added later that carries caller free text fails here — which is the
    only assertion that survives someone extending the dict.
    """
    from aeh.conf import HARDWARE_PROFILES, RETENTION_SETTINGS

    config = resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3), SYNTHETIC_COHORT)
    provider_config = config.to_persisted_dict()["provider_config"]

    closed_sets = {
        "hardware_profile": set(HARDWARE_PROFILES) | {None},
        "retention_setting": set(RETENTION_SETTINGS) | {None},
    }
    for key, value in provider_config.items():
        if key in closed_sets:
            assert value in closed_sets[key], f"{key} is outside its closed set"
        elif key == "cost_currency":
            assert value is None or re.fullmatch(r"[A-Z]{3}", value), f"{key} is free text"
        elif key == "cost_ceiling":
            assert value is None or re.fullmatch(r"[-+0-9.eE]+", value), f"{key} is free text"
        else:
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"provider_config gained a non-numeric field {key!r} that is not a closed set — "
                f"if it can carry caller text, FR-CONF-11's acceptance form no longer holds "
                f"structurally"
            )


def test_tc_conf_11_step_4_every_mismatch_message_is_scanned_not_just_the_first(monkeypatch):
    """Step 4 again, one level down: `BackendMismatchError` is raised from **several** places,
    and provoking it once only scans whichever check happens to fire first.

    Found by mutation: the step-4 case above trips the *backend* comparison, so the transcriber
    message — the one that had both `build_id`s in it — was never reached with a sentinel
    present. Each distinct refusal is provoked here on its own, with the credential in the field
    that message would echo.
    """
    sentinel = seed_credentials(monkeypatch)
    base = hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3)
    row = resolve_run_config(base, SYNTHETIC_COHORT).to_persisted_dict()

    poisoned_transcriber = ModelRef(
        "transcriber", "openrouter", f"proxy/whisper?key={sentinel}@2024-11-02", None
    )
    poisoned_judge = ModelRef(
        "judge", "openrouter", f"proxy/llama?key={sentinel}@2024-12-06", None
    )

    refusals = {
        "backend": {**base, "HARNESS_PROFILE": "dev-ci"},
        "panel": {**base, "panel": (poisoned_judge,) + HOSTED_PANEL_3[1:]},
        "transcriber": {**base, "transcriber": poisoned_transcriber},
        "prompt template": {**base, "prompt_template_v": f"v-{sentinel}"},
    }

    for what, current in refusals.items():
        with pytest.raises(BackendMismatchError) as caught:
            rehydrate_run_config(row, current)
        rendered = _render([str(caught.value), repr(caught.value), [repr(a) for a in caught.value.args]])
        for form, needle in encodings_of(sentinel).items():
            assert needle not in rendered, (
                f"{form} sentinel reached the {what} mismatch message"
            )


def test_tc_conf_11_variant_a_credential_from_a_secret_store_behaves_identically(monkeypatch):
    """TC-CONF-11's variant: *"a credential supplied by an OS secret store rather than the
    environment behaves identically."*

    There is no secret-store reader to stub, and that is the answer rather than a gap: the
    module reads **no** credential from any source, so a secret store and the environment are
    equally absent from every surface.

    Asserted differentially — resolve with the credential environment populated, then with it
    deleted, and require the persisted row to be identical. If anything were being read from the
    environment, removing it would change what came out. A sentinel scan alone cannot make that
    distinction; this can.
    """
    seed_credentials(monkeypatch)
    with_env = resolve_run_config(hosted_cfg("cloud-hosted"), SYNTHETIC_COHORT).to_persisted_dict()

    for var in CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    without_env = resolve_run_config(
        hosted_cfg("cloud-hosted"), SYNTHETIC_COHORT
    ).to_persisted_dict()

    assert with_env == without_env, (
        "the persisted row changed when the credential environment did, so something in it is "
        "being read from there"
    )
    assert SENTINEL_CREDENTIAL not in _render(with_env)


def test_tc_conf_11_a_credential_a_caller_embeds_in_a_build_id_is_persisted_verbatim():
    """**The boundary of this guarantee, asserted so it is not mistaken for a leak this suite
    missed.**

    `build_id` is persisted exactly as supplied, so a caller who pastes an API key into a
    self-hosted endpoint's build id — `proxy/llama?key=sk-…` — puts it in the `run` row. That is
    not `FR-CONF-11` failing:

    * `CT-CONF-03` requires `build_id` be sufficient to identify what answered, and
      `panel_build_ref` hashes it, so rewriting it would break the module's central promise and
      every stored `package_validation` key;
    * `FR-CONF-11`'s own named acceptance form is scoped to **`provider_config`**, which carries
      no build ids — they live in `panel_config`;
    * the module cannot tell a secret substring from an endpoint parameter.

    So the guarantee is "no credential **this module reads**" — which is total — plus "no
    credential pattern in `provider_config`", which is the requirement's form. A credential a
    caller embeds in an identity field is a real disclosure path that no `FR-*` currently owns;
    reported on the PR rather than silently absorbed here.
    """
    embedded = _cfg_with_credential_in_every_field(SENTINEL_CREDENTIAL)
    config = resolve_run_config(embedded, CohortRef("c-real", "real"))
    persisted = config.to_persisted_dict()

    # Only the clean-surface half is asserted. Whether an embedded credential should be
    # *refused at construction* is an open question -- an implementation that rejected a
    # `build_id` matching a credential pattern would satisfy `CT-CONF-03` (what it accepts still
    # round-trips verbatim) and `FR-CONF-11`'s normative clause both, and pinning today's
    # behaviour here would fail it for no requirement's sake. Raised on the PR instead.
    assert SENTINEL_CREDENTIAL not in _render(persisted["provider_config"]), (
        "provider_config is the surface FR-CONF-11 names, and it must stay clean"
    )
    assert config.panel[0].build_id == embedded["panel"][0].build_id, (
        "build_id must round-trip verbatim (CT-CONF-03): if the module starts rewriting "
        "identities, panel_build_ref no longer identifies what answered"
    )


# --- SEC-01 -----------------------------------------------------------------------------------


def test_sec_01_the_process_to_disk_and_logs_boundary_leaks_nothing(monkeypatch, captured_records):
    """SEC-01 (§6.5) — trust boundary: **process to disk and logs**. Threat: information
    disclosure / OWASP A02.

    Probe, verbatim: *"Run with sentinel credentials at DEBUG; scrape every persisted row, log
    record and exception."* Expected defense: *"No credential value anywhere; credentials read
    only from environment or OS secret store."*

    Written as a **boundary sweep** rather than as a list of the surfaces that exist today: it
    collects everything this module can put across the boundary — the persisted row, the
    summary, the canonical serialization, every emitted record, every declared exception — and
    scans the lot in one pass. A surface added later and forgotten fails here, which is the
    thing `TC-CONF-11`'s enumerated steps cannot do.
    """
    sentinel = seed_credentials(monkeypatch)
    logging.getLogger("aeh.conf").setLevel(logging.DEBUG)

    # The poisoned config's `panel_config` is out of this sweep on purpose: a caller who embeds a
    # credential in a `build_id` gets it persisted, because `CT-CONF-03` requires the identity to
    # round-trip verbatim — see the dedicated case above for that boundary. What crosses *this*
    # boundary is everything the module itself contributes.
    poisoned = _cfg_with_credential_in_every_field(sentinel)
    clean = hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3)
    config = resolve_run_config(clean, SYNTHETIC_COHORT)
    poisoned_config = resolve_run_config(poisoned, CohortRef("c-real", "real"))
    run_row = config.to_persisted_dict()

    log_run_start(config)

    crossings = {
        "persisted row": run_row,
        "provider_config (poisoned cfg)": poisoned_config.to_persisted_dict()["provider_config"],
        "profile summary": config.profile_summary(),
        "canonical json": config.profile_summary().to_canonical_json(),
        "log records": [(r.getMessage(), r.__dict__) for r in captured_records],
        "declared exceptions": {
            name.__name__: [str(exc), repr(exc), [repr(a) for a in exc.args]]
            for name, exc in _provoke_each_declared_error(sentinel, run_row).items()
        },
    }

    for surface, value in crossings.items():
        rendered = _render(value)
        for form, needle in encodings_of(sentinel).items():
            assert needle not in rendered, f"{form} sentinel crossed the boundary via {surface}"


def test_sec_01_the_module_reads_no_credential_from_the_environment(monkeypatch):
    """SEC-01's second clause — *"credentials read only from environment or OS secret store."*

    Satisfied here in its strongest form: `environment_snapshot()` lifts only the six `HARNESS_*`
    keys, so no credential-bearing variable is read at all. Asserted over the snapshot rather
    than over intent — a future key that started lifting `*_API_KEY` would fail this and nothing
    else, and it is exactly the kind of convenience someone adds to "make the provider work".
    """
    from aeh.conf import HARNESS_KEYS, environment_snapshot
    from tests.support.conf_builders import CREDENTIAL_ENV_VARS

    sentinel = seed_credentials(monkeypatch)
    snapshot = environment_snapshot()

    assert sentinel not in _render(snapshot)
    assert set(snapshot) <= set(HARNESS_KEYS), "the snapshot lifted a key outside HARNESS_KEYS"
    for var in CREDENTIAL_ENV_VARS:
        assert var not in snapshot, f"{var} was lifted into the config snapshot"
