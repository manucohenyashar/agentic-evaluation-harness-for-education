"""Opening the store and choosing the provider a run's backend profile names."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping


def _open_store(data_dir: str) -> Any:
    """Open the store. The migration chain is already complete, because this package imports all
    eleven contributing modules, so this is safe to call."""
    from aeh.store import open_store

    return open_store(Path(data_dir))


class _UnitPricedProvider:
    """A provider whose `estimate_cost` takes the orchestrator's work unit.

    `M-ORCH` prices a unit before it is dispatched by calling `estimate_cost(unit)` on the
    provider it holds (`FR-ORCH-15`), and every run with a cost ceiling (`dev-ci`,
    `cloud-hosted`) does that on every claim. The live and fixture providers implement
    `estimate_cost(plan: CallPlan)` (`FR-PROV-09`), and a `WorkUnit` has no `calls` field, so
    before this adapter the first claim of any ceilinged run on a real provider raised
    `AttributeError` and paused the run. No test saw it: every test double prices `unit`.

    So the unit becomes the `CallPlan` of the one model call it stands for, at
    `HARNESS_PIPE_UNIT_TOKENS_IN` / `_OUT` tokens, the same way `M-ORCH` prices a decision
    seat (`HARNESS_ORCH_DECISION_TOKENS_PER_SEAT`). A deterministic unit makes no model call
    and is priced None (not billed). A `CallPlan` passes straight through. Everything else is
    the wrapped provider's own attribute, so the stage workers, the retention gate and the
    counters see the real provider."""

    def __init__(self, provider: Any) -> None:
        self._inner = provider

    def estimate_cost(self, unit: Any) -> Any:
        from aeh.orch import STAGE_DETERMINISTIC
        from aeh.prov import CallPlan

        from .settings import (
            UNIT_TOKENS_IN_DEFAULT, UNIT_TOKENS_IN_ENV, UNIT_TOKENS_OUT_DEFAULT,
            UNIT_TOKENS_OUT_ENV, _int_knob,
        )

        if isinstance(unit, CallPlan):
            return self._inner.estimate_cost(unit)
        if getattr(unit, "stage", None) == STAGE_DETERMINISTIC:
            return None
        plan = CallPlan(
            1,
            _int_knob(UNIT_TOKENS_IN_ENV, UNIT_TOKENS_IN_DEFAULT, minimum=0),
            _int_knob(UNIT_TOKENS_OUT_ENV, UNIT_TOKENS_OUT_DEFAULT, minimum=0),
        )
        return self._inner.estimate_cost(plan)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _provider_for(config: Mapping[str, Any]) -> Any:
    """The provider that the run's backend profile names.

    **A declared resolution of a gap, not a shipped factory.** `FR-PIPE-08` says the command
    resolves its configuration and then drives the run, but nothing in the design says which
    provider object a profile maps to, and `M-PROV` leaves construction to the caller. So the
    mapping is made here, minimally and in the open.

    Reads the RESOLVED `RunConfig.backend_profile` rather than a raw configuration key: the
    profile that matters is the one `resolve_run_config` settled on after the environment won
    (`FR-CONF-14`), and a raw lookup finds nothing when the profile arrives through a
    profile section.

    * `dev-ci` -> OpenRouter, the profile's whole point in the design (development "runs
      entirely on OpenRouter"; provider-pinned builds and a cost ceiling, `FR-CONF-03/07`).
      With `HARNESS_FIXTURE_DIR` set it is the test tier instead, `RecordedFixtureProvider`
      over that directory, with no network (`CT-PROV-10`): the same variable that admits the
      fixture decision provider (`FR-CONF-19`). Before this, `dev-ci` could only replay, so
      no shipped command could grade through OpenRouter (live-test blocker B1).
    * `cloud-hosted` -> OpenRouter.
    * `edge-local` -> `LocalServerProvider`.

    OpenRouter is always `OpenRouterProvider.enforcing_zero_retention()`: every request
    carries `zdr` and `data_collection: "deny"`, so OpenRouter routes student work only to a
    host that keeps none, or refuses it, and the `cloud-hosted` run-start retention gate is
    answered by that enforcement (blocker B6). The consent gate (`FR-CONF-08`) still decides,
    before any of this, whether a cohort's work may leave the machine at all.

    Every provider is wrapped in `_UnitPricedProvider`, so the cost ceiling can price a unit.
    The live providers take their endpoints from their own environment knobs
    (`OPENROUTER_BASE_URL`, `LOCAL_INFERENCE_BASE_URL`) and the key from
    `OPENROUTER_API_KEY`, never from here.
    """
    from aeh.prov import LocalServerProvider, OpenRouterProvider, RecordedFixtureProvider

    profile = str(
        getattr(config, "backend_profile", None)
        or (config.get("backend_profile") if hasattr(config, "get") else None)
        or ""
    )
    if profile == "dev-ci":
        fixture_dir = os.environ.get("HARNESS_FIXTURE_DIR")
        if fixture_dir:
            return _UnitPricedProvider(RecordedFixtureProvider(fixture_dir=Path(str(fixture_dir))))
        return _UnitPricedProvider(OpenRouterProvider.enforcing_zero_retention())
    if profile == "cloud-hosted":
        return _UnitPricedProvider(OpenRouterProvider.enforcing_zero_retention())
    if profile == "edge-local":
        return _UnitPricedProvider(LocalServerProvider())
    raise ValueError(
        f"no backend profile is configured ({profile!r}); set HARNESS_BACKEND_PROFILE or "
        f"declare backend_profile in the config file. The declared profiles are "
        f"'edge-local', 'cloud-hosted' and 'dev-ci'."
    )


def _describe_provider(provider: Any) -> str:
    """One line naming the provider a run will call, for the operator (seam 4). Which
    backend answers is M-PROV's knowledge (CT-PROV-15), so M-PROV words the line."""
    from aeh.prov import describe_provider
    return describe_provider(provider)


def _load_config_file(path: str | None) -> dict[str, Any]:
    """Read the `--config` file with M-CONF's own parser.

    `parse_config_document` is the declared loader: it handles both formats, turns model
    tables into `ModelRef`s and raises `ConfigurationError` with a sentence an operator can
    act on. Hand-rolling a `json.loads` here — the first draft did — meant a TOML config, the
    format the repo's own fixtures are written in, died with a bare `JSONDecodeError` before
    the configuration was ever composed.

    The format is taken from the suffix, which is what an operator passing `harness.toml`
    expects; anything else is read as TOML, the documented default for the file.
    """
    from aeh.conf import parse_config_document

    if not path:
        return {}
    source = Path(path)
    fmt = "json" if source.suffix.lower() == ".json" else "toml"
    return parse_config_document(source.read_text(encoding="utf-8"), fmt)


#: The config-file key naming the real models an escalation seats past the panel. A list of
#: model tables, the same shape as `panel` (`[[profiles.<name>.escalation_judge]]`). Read here,
#: not by `M-CONF`: `RunConfig`'s fields are fixed (`CT-CONF-C02`), and these models are not
#: panel members — they are the `judge_refs` `run_to_completion` already takes for extension arms.
ESCALATION_JUDGES_KEY = "escalation_judge"


#: The two CLI flags that pin a run's extract and synthesis identities (`FR-PIPE-19`), and
#: the role each one fixes. The flag IS the role — there is no `--role` — because the two
#: stages have different callers and an operator pinning an extractor is not asking to
#: reseat the synthesizer.
_PIN_FLAGS: tuple[tuple[str, str], ...] = (
    ("--extractor", "extractor"),
    ("--synthesizer", "synthesizer"),
)


def _parse_pin(raw: str, flag: str, role: str) -> Any:
    """One `--extractor` / `--synthesizer` value as a `ModelRef` of the flag's own role.

    The REF form is `provider|build_id[|quantization]` — the convention
    `HARNESS_EXTRACT_SECOND_FAMILY_MODEL` documents. Splitting on `|` and nothing
    else: a build id may itself contain `:` and `@` (weights paths and digest pins
    do), so anything finer than the three `|` fields would mis-parse a legal ref. A
    value with one or more than three parts — or an empty field, like a trailing `|`
    — is refused, naming the flag and not echoing the value — a `build_id` is caller
    data that can carry a credential in a query string (`NFR-CONF-02`).
    """
    from aeh.conf import ModelRef

    parts = raw.split("|")
    if len(parts) not in (2, 3) or not parts[0].strip() or not parts[1].strip() or (
            len(parts) == 3 and not parts[2].strip()):
        raise ValueError(
            f"{flag} must be provider|build_id[|quantization] — the REF form "
            f"HARNESS_EXTRACT_SECOND_FAMILY_MODEL documents — and this one has "
            f"{len(parts)} '|'-separated part(s)."
        )
    quantization = parts[2].strip() if len(parts) == 3 else None
    return ModelRef(
        role=role,
        provider=parts[0].strip(),
        build_id=parts[1].strip(),
        quantization=quantization or None,
    )


def _model_pins(args: Any, profile: str) -> dict[str, Any]:
    """Parse and resolve the `--extractor` / `--synthesizer` pins (`FR-PIPE-19`).

    A pin resolves through the same check the panel goes through — `_check_resolved`
    (`CT-CONF-03`) — against the backend profile the effective configuration settled on
    (`FR-CONF-14`): the profile decides WHICH build form counts, so a provider-pinned
    slug is a perfectly resolved identity and still wrong on `edge-local`. Called before
    the store opens, so an unresolvable ref is refused with exit 1 and creates no run
    row — the same posture as the `_int_knob` checks (`TC-PIPE-35`).

    Returns a possibly-empty mapping of role to `ModelRef`. Empty when neither flag was
    given: `aeh recover`'s no-flag arm keeps every run's own recorded pin unchanged.
    """
    from aeh.conf.checks import _REQUIRED_BUILD_FORM, _check_resolved

    pins: dict[str, Any] = {}
    for flag, role in _PIN_FLAGS:
        raw = getattr(args, flag.lstrip("-"), None)
        if raw is None:
            continue
        pins[role] = _parse_pin(str(raw), flag, role)
    if pins and profile not in _REQUIRED_BUILD_FORM:
        # Same posture as `_provider_for`: the profile vocabulary is declared there, and
        # a pin cannot be resolved against a profile that does not exist.
        raise ValueError(
            f"a --extractor / --synthesizer pin is resolved against the run's backend "
            f"profile, and no backend profile is configured ({profile!r}); set "
            f"HARNESS_PROFILE to one of {sorted(_REQUIRED_BUILD_FORM)}."
        )
    for role, ref in sorted(pins.items()):
        flag = next(name for name, r in _PIN_FLAGS if r == role)
        _check_resolved(ref, f"the {flag} pin", profile)
    return pins

def _is_live(provider: Any) -> bool:
    """Whether `provider` sends calls to a real model server (OpenRouter or a local one), where a
    derived judge name like `escalation-arm-4` is not a model anyone serves."""
    from aeh.prov import LocalServerProvider, OpenRouterProvider

    return isinstance(getattr(provider, "_inner", provider), (OpenRouterProvider, LocalServerProvider))


def _escalation_judge_refs(config: Mapping[str, Any], run_config: Any, cohort: Any,
                           provider: Any) -> dict[str, Any]:
    """The real model for each judge seat past the panel, keyed by the seat's ledger name
    (`escalation-arm-<k>`), for `run_to_completion(judge_refs=...)`.

    Live-test finding: past the panel, an escalation adds judges on derived names,
    `escalation-arm-<k>`, which the executor turned into the first judge with that name as its
    model, so on OpenRouter the first disagreement sent `model: "escalation-arm-2"` and the call
    failed. With a recording, derivation is how the corpus was captured, so it stays there and
    this returns {}.

    On a live provider the `escalation_judge` list gives seats past the panel real models, in
    order. Each entry is checked by the resolver the panel goes through (pin form, provider,
    role), by resolving it as a one-judge panel, and no model may hold two seats. An escalation
    or a replacement arm with no seat left does not widen (`hooks._aggregate_hook` leaves the
    score provisional, for review). The random-arm sample (`FR-ORCH-11`) widens panels when
    work is enumerated, before any of that, so a live run with the sample on must have the two
    seats it adds: otherwise it is refused here, before it exists. Raises `ValueError`."""
    from aeh.conf import ModelRef, resolve_run_config
    from aeh.orch import ESCALATION_ARM_PREFIX, ORCH_RANDOM_ARM_RATE, RANDOM_ARM_RATE_ENV

    raw = config.get(ESCALATION_JUDGES_KEY, ())
    if raw in (None, ()):
        raw = []
    if not isinstance(raw, list) or not all(isinstance(entry, Mapping) for entry in raw):
        raise ValueError(f"{ESCALATION_JUDGES_KEY} must be a list of model tables "
                         f"([[profiles.<name>.{ESCALATION_JUDGES_KEY}]]), like the panel.")
    if not _is_live(provider):
        return {}
    panel = tuple(run_config.panel)
    refs = []
    for index, entry in enumerate(raw):
        where = f"{ESCALATION_JUDGES_KEY}[{index}]"
        fields = ("role", "provider", "build_id", "quantization")
        unknown = sorted(set(entry) - set(fields))
        missing = [name for name in fields[:3] if name not in entry]
        if unknown or missing:
            raise ValueError(f"{where}: " + "; ".join(
                part for part in (unknown and f"unknown keys {', '.join(unknown)}",
                                  missing and f"missing {', '.join(missing)}") if part))
        ref = ModelRef(**{name: entry.get(name) for name in fields})
        try:
            resolve_run_config({**config, "panel": (ref,)}, cohort)
        except Exception as error:  # noqa: BLE001 - re-raised naming the entry
            raise ValueError(f"{where}: {error}") from error
        refs.append(ref)
    seen = [ref.build_id for ref in panel]
    for index, ref in enumerate(refs):
        if ref.build_id in seen:
            raise ValueError(
                f"{ESCALATION_JUDGES_KEY}[{index}] names {ref.build_id!r}, which already has a "
                f"seat: one model, one seat (a doubled seat lets one model outvote the others).")
        seen.append(ref.build_id)
    raw_rate = os.environ.get(RANDOM_ARM_RATE_ENV, "").strip()
    try:
        rate = float(raw_rate) if raw_rate else ORCH_RANDOM_ARM_RATE
    except ValueError:
        rate = ORCH_RANDOM_ARM_RATE  # M-ORCH refuses the typo itself, naming the knob
    sampled = min(3, len(panel)) + 2
    if rate > 0 and len(panel) + len(refs) < sampled:
        short = sampled - len(panel) - len(refs)
        raise ValueError(
            f"the random-arm sample ({RANDOM_ARM_RATE_ENV}, {rate}) gives some answers "
            f"{sampled} judges, and this live run has {len(panel) + len(refs)} real judge "
            f"model(s). Add {short} [[profiles.<name>.{ESCALATION_JUDGES_KEY}]] table(s), each "
            f"a different model, or turn the sample off with {RANDOM_ARM_RATE_ENV}=0. "
            f"Nothing was started.")
    return {f"{ESCALATION_ARM_PREFIX}-{len(panel) + position}": ref
            for position, ref in enumerate(refs, start=1)}
