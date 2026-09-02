"""`CT-CONF-04` … `CT-CONF-07` — immutability, purity, the round trip and the panel hash.

Test plan §6.11.1, issue #9 (TS-58). Four behaviour clauses, and each is asserted as the *kind*
of oracle §6.11 names for it rather than as a point check:

* `C04` — exact exception type on every field, plus an artifact assertion over the member list;
* `C05` — a **differential**: two resolutions either side of a perturbed process environment;
* `C06` — exact value on the round trip, exact exception on each perturbation;
* `C07` — a differential **across processes**, plus exact inequality per perturbation.

`C06` shares its central assertion with `TC-CONF-04` in §5, and `C07` with `TC-CONF-05`. §6.11 is
explicit that the rows stay: *"the two run at different times, against different implementations,
for different reasons."* The §5 case runs when someone changes the resolver; this one runs on
every `M-CONF` change and against any future implementation of the contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from tests.support.conf_builders import (
    EDGE_JUDGE_2,
    EDGE_JUDGE_4,
    EDGE_OFF_PANEL,
    EDGE_PANEL_3,
    SYNTHETIC_COHORT,
    edge_cfg,
    hosted_cfg,
)
from tests.support.impl import CONF_MODULE, require

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]


# --- TC-CONF-C04 — behaviour -----------------------------------------------------------------


def test_tc_conf_c04_assignment_to_every_public_field_raises_type_error():
    """`CT-CONF-04` — attribute assignment raises `TypeError`, on **every** public field.

    Enumerated from the dataclass rather than spelled out, so a thirteenth field added later is
    covered the day it appears rather than the day someone remembers to add a row.

    `TypeError` exactly, and not by accident: a frozen dataclass raises `FrozenInstanceError`,
    which is an `AttributeError`, and `FR-CONF-02` names `TypeError`. A consumer catching
    `TypeError` around a defensive write — the thing this clause exists to let them *not* do —
    would see the exception pass straight through.
    """
    conf = require(CONF_MODULE, issue="#4")
    from dataclasses import fields

    config = conf.resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)
    names = [f.name for f in fields(conf.RunConfig)]
    assert names, "no fields enumerated, so this asserts nothing"

    for name in names:
        with pytest.raises(TypeError):
            setattr(config, name, getattr(config, name))
        with pytest.raises(TypeError):
            delattr(config, name)


def test_tc_conf_c04_no_public_member_returns_a_config_with_a_different_backend_or_panel():
    """`CT-CONF-04`'s second half — an **artifact assertion over the member list**.

    "No operation on it returns a mutated copy with a different backend or panel." The assertion
    is over the *surface*, so it catches a `with_backend()` convenience helper that exists and is
    never called — which is the point: a method nobody calls today is a method someone wires to a
    console retry control tomorrow (RISK-22).

    Two nets, because either alone leaks. The **runtime** net calls every zero-argument public
    member and asserts no `RunConfig` comes back; it misses `with_backend(profile)`, which needs
    an argument. The **reflective** net reads every public member's signature and return
    annotation; it misses a helper that takes `**kwargs`. Together they cover the shapes a
    convenience helper actually takes.

    The deeper sweep — every back door, and the module's own functions — is `TC-CONF-C14`, which
    is this clause's non-promise twin. This one is the `RunConfig` surface alone.
    """
    conf = require(CONF_MODULE, issue="#4")
    import inspect

    config = conf.resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)

    offenders = []
    for name in dir(conf.RunConfig):
        if name.startswith("_"):
            continue
        member = getattr(conf.RunConfig, name)
        if not callable(member):
            continue

        annotation = getattr(member, "__annotations__", {}).get("return")
        if annotation in (conf.RunConfig, "RunConfig", '"RunConfig"'):
            offenders.append(f"{name}() is annotated to return a RunConfig")

        try:
            signature = inspect.signature(member)
        except (TypeError, ValueError):  # pragma: no cover - builtins without a signature
            continue
        parameters = [p for p in signature.parameters.values() if p.name != "self"]
        if not parameters:
            result = getattr(config, name)()
            if isinstance(result, conf.RunConfig):
                offenders.append(f"{name}() returned a RunConfig")

    assert not offenders, (
        "CT-CONF-04: a member of RunConfig can produce another RunConfig, which is how a run "
        "gets rebound (RISK-22):\n  " + "\n  ".join(offenders)
    )


# --- TC-CONF-C05 — behaviour -----------------------------------------------------------------


def test_tc_conf_c05_two_resolutions_agree_across_a_perturbed_environment(monkeypatch, tmp_path):
    """`CT-CONF-05` — a **differential**: identical inputs, perturbed process state, identical
    result.

    The clause is that the environment enters resolution *only* through the snapshot in `cfg`
    (`NFR-CONF-01`). So this resolves once, then changes everything a leaky implementation could
    be reading — every `HARNESS_*` key in `os.environ` set to a contradictory value, a different
    working directory, a different clock — and resolves again from the same `cfg`.

    **Field-for-field including `panel_build_ref`.** Object equality would pass on a dataclass
    that compared only what it chose to; the hash is compared explicitly because it is the field
    `M-PKG` and `M-STATS` key on, and a hash that drifted with the cwd would produce two
    `package_validation` scopes for one panel and neither would be findable.

    The environment values below **contradict** the `cfg` rather than merely differing from it:
    `HARNESS_PROFILE=cloud-hosted` against an `edge-local` config means a leak does not produce a
    slightly different result, it produces a different backend — which is a legible failure
    rather than a puzzling one.
    """
    conf = require(CONF_MODULE, issue="#4")
    from dataclasses import fields

    cfg = edge_cfg(**{"panel": EDGE_PANEL_3, "off_panel_checker": EDGE_OFF_PANEL})

    first = conf.resolve_run_config(cfg, SYNTHETIC_COHORT)

    # Perturb everything a leak could read.
    for key, value in {
        "HARNESS_PROFILE": "cloud-hosted",
        "HARNESS_HARDWARE_PROFILE": "discrete-gpu",
        "HARNESS_COST_CEILING": "999.99",
        "HARNESS_COST_CURRENCY": "EUR",
        "HARNESS_CONCURRENCY": "1",
        "HARNESS_ALLOW_REMOTE_REAL_WORK": "true",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(time, "time", lambda: 1_900_000_000.0)

    second = conf.resolve_run_config(cfg, SYNTHETIC_COHORT)

    differing = [
        f.name
        for f in fields(conf.RunConfig)
        if getattr(first, f.name) != getattr(second, f.name)
    ]
    assert not differing, (
        "CT-CONF-05: resolution is not a pure function of (cfg, cohort) — these fields changed "
        f"when only the process environment did: {differing}"
    )
    assert first.panel_build_ref == second.panel_build_ref
    assert first == second


# --- TC-CONF-C06 — behaviour -----------------------------------------------------------------


def _run_row(config) -> dict:
    """The `run` row `M-ORCH` writes, assembled from the module's own serialization.

    Design §3.1: *"`RunConfig` is serialized into `run.backend_profile`, `run.panel_config`, and
    `run.provider_config`."* `to_persisted_dict()` already returns those three keys, so the row
    is that dict — building it by hand here would test a shape no caller uses.
    """
    return dict(config.to_persisted_dict())


@pytest.mark.parametrize("profile", ["edge-local", "cloud-hosted", "dev-ci"])
def test_tc_conf_c06_the_round_trip_reproduces_every_field(profile):
    """`CT-CONF-06` — rehydration reconstructs a `RunConfig` **equal field-for-field** to the one
    that produced the row.

    Exact value, per field, rather than `==` alone: a `Decimal` cost ceiling that came back as a
    `float` compares equal at `12.5` and is a different type in every downstream comparison, and
    `NFR-CONF-04` asks for a byte-identical round trip. So the types are asserted too.

    All three backends, because the nullable fields differ per backend and a round trip that
    dropped `retention_setting` would be invisible on the two profiles that do not carry one.
    """
    conf = require(CONF_MODULE, issue="#4")
    from dataclasses import fields

    cfg = edge_cfg() if profile == "edge-local" else hosted_cfg(profile)
    if profile == "dev-ci":
        cfg.pop("retention_setting", None)

    original = conf.resolve_run_config(cfg, SYNTHETIC_COHORT)
    rehydrated = conf.rehydrate_run_config(_run_row(original))

    for f in fields(conf.RunConfig):
        mine = getattr(original, f.name)
        theirs = getattr(rehydrated, f.name)
        assert mine == theirs, f"{f.name} did not survive the round trip"
        assert type(mine) is type(theirs), (
            f"{f.name} came back as {type(theirs).__name__} rather than "
            f"{type(mine).__name__}; NFR-CONF-04 asks for a byte-identical round trip"
        )
    assert rehydrated == original


@pytest.mark.parametrize(
    "what, overrides",
    [
        ("a different backend", {"HARNESS_PROFILE": "cloud-hosted"}),
        ("a different resolved build", {"panel": (EDGE_JUDGE_2,)}),
        ("the same panel in a different order", {"panel": tuple(reversed(EDGE_PANEL_3))}),
    ],
)
def test_tc_conf_c06_every_perturbation_of_current_configuration_refuses(what, overrides):
    """`CT-CONF-06`'s second half — "a mismatch against current configuration raises rather than
    resolving."

    Exact exception type per perturbation, and the type matters: `M-ORCH` branches on
    `BackendMismatchError` to stop the resume and tell the operator the grader changed. A
    `ConfigurationError` on the same input would be handled as a malformed row and the run would
    be reported as corrupt rather than as rebound — a different message to a different person.

    "The same panel in a different order" is the one worth spelling out. It is the perturbation
    that produces an identical *set* of builds and a different grader: judge order decides which
    build answers first and is mixed into `panel_build_ref`, so an implementation comparing
    panels as sets would resume half a cohort under a panel the other half never saw (RISK-22).
    """
    conf = require(CONF_MODULE, issue="#4")

    started_cfg = edge_cfg(**{"panel": EDGE_PANEL_3})
    original = conf.resolve_run_config(started_cfg, SYNTHETIC_COHORT)

    current = dict(started_cfg)
    current.update(overrides)

    with pytest.raises(conf.BackendMismatchError):
        conf.rehydrate_run_config(_run_row(original), cfg=current)


# --- TC-CONF-C07 — data ----------------------------------------------------------------------


_CHILD_PROGRAM = textwrap.dedent(
    """
    import json, sys
    from aeh.conf import ModelRef, compute_panel_build_ref

    panel = tuple(ModelRef(**raw) for raw in json.loads(sys.argv[1]))
    sys.stdout.write(compute_panel_build_ref(panel))
    """
)


def test_tc_conf_c07_the_same_ordered_panel_hashes_identically_in_another_process(tmp_path):
    """`CT-CONF-07` — a **differential across processes**: equal panels produce equal refs across
    processes and machines.

    One subprocess, not one per perturbation: the contract tier has its own 60-second budget and
    a process spawn is the most expensive thing in this file. The child differs from the parent
    in the two ways that can break a hash without breaking a single-process test:

    * **a different working directory** — `tmp_path`, so a ref that folded in a path is caught;
    * **a different `PYTHONHASHSEED`** — which is the real discriminator. Python's built-in
      `hash()` of a `str` is salted per process, so an implementation built on `hash()` or on
      `frozenset` iteration order is stable within one process and *random* between two. Every
      in-process case in this repository passes against it. `M-PKG` uses this ref as a
      primary-key component and `M-CONFORM` compares runs across machines, so a per-process hash
      would silently split one panel's validation records into as many scopes as there were
      processes.

    `PYTHONHASHSEED=0` disables the salt, which would mask exactly that bug — so the child gets a
    fixed *non-zero* seed instead, guaranteed to differ from the parent's random one.
    """
    conf = require(CONF_MODULE, issue="#4")

    panel = EDGE_PANEL_3
    parent_ref = conf.compute_panel_build_ref(panel)

    payload = json.dumps(
        [
            {
                "role": ref.role,
                "provider": ref.provider,
                "build_id": ref.build_id,
                "quantization": ref.quantization,
            }
            for ref in panel
        ]
    )

    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "12345"
    env["PYTHONPATH"] = str(REPO_ROOT / "src")  # the ini's `pythonpath` does not propagate

    completed = subprocess.run(
        [sys.executable, "-c", _CHILD_PROGRAM, payload],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, (
        f"the child process failed rather than producing a ref:\n{completed.stderr}"
    )
    assert completed.stdout == parent_ref, (
        "CT-CONF-07: the same ordered panel hashed differently in another process "
        f"(parent {parent_ref!r}, child {completed.stdout!r}). Consumers use this ref as a "
        "primary-key component across machines."
    )


@pytest.mark.parametrize(
    "why, perturbed",
    [
        (
            "one member swapped",
            (EDGE_PANEL_3[0], EDGE_JUDGE_4, EDGE_PANEL_3[2]),
        ),
        (
            "one member's quantization changed",
            None,  # built in the body: it needs the module's ModelRef
        ),
        (
            "the same members in a different order",
            tuple(reversed(EDGE_PANEL_3)),
        ),
    ],
)
def test_tc_conf_c07_each_perturbation_produces_a_different_ref(why, perturbed):
    """Exact **inequality** per perturbation — a member, a quantization, an order.

    Order is the one the plan singles out, and it is right to: a set is the obvious
    "optimization" for a panel, and `frozenset(panel)` would merge two distinct panels under one
    key. Nothing else in the system would notice — the runs complete, the grades are produced,
    and `package_validation` quietly holds one row where two belong, so `M-STATS` reports a
    sample size that was never graded by that panel.

    "One member swapped" replaces the middle judge with a *fourth* judge, so the change is a
    different build at the same position rather than a longer panel. The guard assertion below —
    that the perturbation perturbed something — earned its place on the first run of this file:
    the swap originally reinstated the judge already at that position and the case asserted
    nothing at all.
    """
    conf = require(CONF_MODULE, issue="#4")

    if perturbed is None:
        head = EDGE_PANEL_3[0]
        requantized = conf.ModelRef(
            role=head.role,
            provider=head.provider,
            build_id=head.build_id,
            quantization="q8" if head.quantization != "q8" else "q4",
        )
        perturbed = (requantized, *EDGE_PANEL_3[1:])

    baseline = conf.compute_panel_build_ref(EDGE_PANEL_3)
    assert tuple(perturbed) != EDGE_PANEL_3, "the perturbation did not perturb anything"

    assert conf.compute_panel_build_ref(tuple(perturbed)) != baseline, (
        f"CT-CONF-07: {why} produced the same panel_build_ref. Two distinct panels sharing one "
        "key is a collision in every package_validation primary key."
    )
