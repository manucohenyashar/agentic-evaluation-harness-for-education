"""`panel_for_profile` (FR-CONF-33, CT-CONF-23): the profile's ordered judge chain for authoring.

`M-AUTHOR` reads "the run configuration's judge models" the way the directive names it — the
first judge model, then the second, and so on (ADR-42) — without fabricating a cohort or a run
row. The chain is the profile's `[[panel]]` refs in declared order followed by its
`[[escalation_judge]]` refs in declared order, de-duplicated by build identity, each resolved
per CT-CONF-03. The consent gate stays run-scoped: authoring sends teacher text, never student
data, so there is no cohort here and no consent check (`panel_for_profile` takes no cohort).

Deliberately **not** a `RunConfig`: its fields are pinned (`CT-CONF-C02`) and an authoring chain
is not a run's grader identity — the transcriber, the ceilings and the panel build ref do not
apply. This surface reads the same configuration sections the run path reads and stops there.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .checks import _check_resolved, _echo
from .errors import ConfigurationError
from .model_ref import ModelRef, _require_model_ref
from .panel import _build_identity
from .sources import _file_ref, select_profile_config
from .vocabulary import BACKEND_PROFILES


#: The config-file key naming the real models for seats past the panel
#: (`[[profiles.<name>.escalation_judge]]`). `aeh/pipeline/runtime.py` holds its own copy of this
#: literal: `M-CONF` is a leaf by design (`CT-CONF`'s Requires table) and must not import
#: `M-PIPE` to share it. A new key would add a second copy in both places — that is the cost of
#: the leaf rule, paid deliberately.
ESCALATION_JUDGES_KEY = "escalation_judge"


def _judge_refs(section: Mapping[str, Any], key: str) -> tuple[ModelRef, ...]:
    """The named key's judge refs from a profile section, each a `ModelRef` of role `judge`.

    A config file spells a judge as a model table, which `parse_config_document` builds into
    `ModelRef`s for `panel` but leaves raw for `escalation_judge` — and a caller may hand this
    surface a hand-built mapping either way. Both forms are accepted here, converted through the
    same `_file_ref` rules the file parser uses (unknown keys refused, `role`, `provider` and
    `build_id` required), then the role check the panel entries go through in the resolver.

    The failure carries the entry's position, never its value: a `build_id` is caller data that
    can carry a credential (`NFR-CONF-02`).
    """
    raw = section.get(key)
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ConfigurationError(
            f"{key} must be a sequence of model tables, got {type(raw).__name__}."
        )
    refs: list[ModelRef] = []
    for index, entry in enumerate(raw):
        where = f"{key}[{index}]"
        if isinstance(entry, ModelRef):
            ref = entry
        elif isinstance(entry, Mapping):
            ref = _file_ref(entry, where)
        else:
            raise ConfigurationError(
                f"{where} must be a model table or a ModelRef, got {type(entry).__name__}."
            )
        refs.append(_require_model_ref(ref, where, "judge"))
    return tuple(refs)


def panel_for_profile(cfg: Mapping[str, Any], backend_profile: str) -> tuple[ModelRef, ...]:
    """The named profile's ordered judge chain for authoring (FR-CONF-33, CT-CONF-23).

    The profile's `[[panel]]` judge refs in declared order, followed by its
    `[[escalation_judge]]` refs in declared order, de-duplicated by build identity — first seen
    kept, so an escalation judge that is already on the panel is dropped rather than re-ordered.
    Every ref is resolved per CT-CONF-03: pinned build, in the form `backend_profile` requires,
    with the floating-tag refusal the resolver already enforces (`build_form()` returns None for
    `:latest` and friends).

    Pure in `cfg` (`CT-CONF-23`): the environment enters only through whatever snapshot the
    caller already merged into `cfg`, no file is opened, and nothing is written — no cohort, no
    consent gate, no run row, because authoring resolves a chain, not a run.

    The section is selected by the same rules as the run path (`select_profile_config`,
    FR-CONF-13): the shared keys overlaid by `profiles[backend_profile]`, a missing section
    naming the profile and the sections present, and a section that declares a different
    `HARNESS_PROFILE` refused.

    Raises `ConfigurationError` when the profile exists but names no judge model — an empty or
    missing `[[panel]]`, **including the escalation-only case** (test-plan Q-O7): the authoring
    chain is the panel order first, so an empty panel yields no chain and the escalations never
    stand in for it. The refusal precedes any model call by construction — this function makes
    none.
    """
    if not isinstance(cfg, Mapping):
        raise ConfigurationError(
            f"cfg must be a Mapping of configuration keys, got {type(cfg).__name__}."
        )
    if not isinstance(backend_profile, str) or backend_profile not in BACKEND_PROFILES:
        raise ConfigurationError(
            f"HARNESS_PROFILE must be one of {BACKEND_PROFILES}, got "
            f"{_echo('HARNESS_PROFILE', backend_profile)}. There is no default (FR-CONF-01)."
        )
    section = select_profile_config(cfg, backend_profile)

    panel = _judge_refs(section, "panel")
    if not panel:
        raise ConfigurationError(
            f"profile {backend_profile!r} names no judge model: `panel` is empty or absent "
            f"(FR-CONF-33, CT-CONF-23). The authoring chain is the panel's judge order first, "
            f"so the escalation judges never stand in for it (Q-O7)."
        )
    for position, ref in enumerate(panel):
        _check_resolved(ref, f"panel[{position}]", backend_profile)

    escalation = _judge_refs(section, ESCALATION_JUDGES_KEY)
    for position, ref in enumerate(escalation):
        _check_resolved(ref, f"{ESCALATION_JUDGES_KEY}[{position}]", backend_profile)

    chain: list[ModelRef] = []
    seen: set[str] = set()
    for ref in (*panel, *escalation):
        identity = _build_identity(ref)
        if identity not in seen:
            seen.add(identity)
            chain.append(ref)
    return tuple(chain)