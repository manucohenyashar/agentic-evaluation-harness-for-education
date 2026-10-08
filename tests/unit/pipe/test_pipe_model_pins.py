"""`FR-PIPE-19` (#664) — the CLI's `--extractor` / `--synthesizer` pins: recorded, hashed,
refused.

| Case | Input | Expected |
|---|---|---|
| `TC-PIPE-34` | `aeh run ... --extractor P1\\|B1 --synthesizer P1\\|B2` over a real store (edge-local, fixture provider), and the same command with no flags | The run row's persisted config carries `model_pins` with both refs; every enumerated unit's `work_id == compute_work_id(..., extractor_version=<pinned build>)`; the unpinned row carries **no** `model_pins` key (NFR-CONF-04); a fresh `Orchestrator` re-enumerates the same ids |
| `TC-PIPE-35` | `--extractor` / `--synthesizer` ∈ {no separator, floating tag, weights path with no quantization, provider-pinned slug on edge-local}, through `main` | Each arm exits 1, stderr names the flag, and no run row exists — the store is never opened, asserted by a store opened afterwards counting 0 runs |
| `TC-PIPE-36` | A run created with pins; then `aeh recover --extractor <same>` / `<different>` / none; and `aeh run` with a different build | (a) exit 0; (b) exit 1 before recovery writes, naming both builds; (c) exit 0, the run keeps its own pin; the `aeh run` arm is refused as the profile switch is (FR-CONF-15 posture) |

**Why the pins here are weights builds.** These cases resolve against `edge-local`, whose
required build form is an edge-weights path plus hash plus quantization (`CT-CONF-03`) —
so the pinned refs take the same shape `EDGE_JUDGE` does, and the refusal arms can show
a *resolved* provider-pinned slug being refused for its form.

**What is not here.** The run-through-`F-DEV-PIPE` smoke (`TC-SMOKE-12`) is rung 4 and
stays blocked on F-DEV-PIPE, as `tests/support/impl.py` records; the replay-pinning flag
contract it will name is the one these cases pin at unit level.

**Green, not written ahead.** The implementation lands in the same change as these cases
(#664), so they run in the fast tier with no marker and no `WRITTEN_AHEAD_BLOCKERS`
entry (the `test_pipe_knobs.py` precedent).
"""

from __future__ import annotations

import json

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md), for the seeded store
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.conf import CohortRef, ModelRef, resolve_run_config
from aeh.conf.model_ref import ModelRef as _TypedRef  # noqa: F401 — type only
from aeh.orch import (
    EXTRACTOR_VERSION,
    Orchestrator,
    compute_work_id,
)
from aeh.pipeline.results import RunResult
from aeh.store import Statement, open_store
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.orch_run import seed_cohort, seed_package
from tests.support.profile_switching import f_profiles_toml

ISSUE = "#664"

CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)
SUBMISSIONS = ("S01",)

#: The pins a pinned run freezes, in the build form `edge-local` requires (weights path
#: + hash + quantization). The digests are distinct so a refusal naming "both builds"
#: cannot name one of them twice by accident.
EXTRACTOR_PIN = ModelRef(
    role="extractor",
    provider="ollama",
    build_id="/models/reader-x.gguf@sha256:11aa22bb",
    quantization="q8_0",
)
SYNTHESIZER_PIN = ModelRef(
    role="synthesizer",
    provider="ollama",
    build_id="/models/summarizer-y.gguf@sha256:33cc44dd",
    quantization="q5_k",
)
#: A DIFFERENT extractor build — same path, another digest — for the mismatch arms.
OTHER_EXTRACTOR_PIN = ModelRef(
    role="extractor",
    provider="ollama",
    build_id="/models/reader-x.gguf@sha256:55ee66ff",
    quantization="q8_0",
)
#: A DIFFERENT synthesizer build, same shape — `recover`'s mismatch check is per role, and
#: only the flag decides which role a ref is checked against, so the synthesizer arm needs
#: its own other-build to show a `--synthesizer` mismatch refuses too.
OTHER_SYNTHESIZER_PIN = ModelRef(
    role="synthesizer",
    provider="ollama",
    build_id="/models/summarizer-y.gguf@sha256:77aa88bb",
    quantization="q5_k",
)


def _ref_string(ref: ModelRef) -> str:
    """The flag form of a ref: `provider|build_id[|quantization]` (FR-PIPE-19)."""
    parts = f"{ref.provider}|{ref.build_id}"
    return f"{parts}|{ref.quantization}" if ref.quantization else parts


def _seed_corpus(store) -> tuple[str, str]:
    """Seed the cohort and package version a run reads. Returns `(cohort_id, version)`.

    Called once per store: `seed_cohort` INSERTs the cohort unconditionally, so a second
    call for a same-store second run would hit the cohort's UNIQUE constraint.
    """
    return seed_cohort(store, SUBMISSIONS), seed_package(store, CRITERIA)


def _seed_run(
    store, *, pins: dict[str, ModelRef] | None, run_id: str, cohort_id: str, version: str,
) -> tuple[str, str]:
    """A real run over a real store, with or without pins. Returns `(cohort_id, version)`.

    The corpus must already be seeded (`_seed_corpus`).
    """
    resolved = resolve_run_config(
        edge_cfg(panel=edge_panel(1)),
        CohortRef(cohort_id=cohort_id, consent_class="synthetic"),
    )
    Orchestrator(store).create_run(
        cohort_id, version, resolved, run_id=run_id, model_pins=pins or None)
    return cohort_id, version


def _run_config_json(store, run_id: str) -> dict:
    rows = store.cohort("c-2026-7B-orch").query(
        Statement("SELECT provider_config FROM run WHERE run_id = :r"), r=run_id
    )
    assert rows, f"fixture bug: run {run_id} has no row"
    return json.loads(rows[0]["provider_config"])


def _units(store, run_id: str) -> list:
    return store.cohort("c-2026-7B-orch").query(
        Statement("SELECT work_id, stage, submission_id, criterion_id, judge_id "
                  "FROM work_unit WHERE run_id = :r ORDER BY work_id"), r=run_id
    )


# --- TC-PIPE-34 — the pin is recorded, and it feeds the hash --------------------------------


def test_tc_pipe_34_a_pinned_run_records_both_refs_and_hashes_them(
    tmp_data_dir, monkeypatch
):
    """`TC-PIPE-34` — the run row's persisted config carries `model_pins`, and every unit
    hashes with the recorded extractor build exactly as `EXTRACTOR_VERSION` would hash.

    The oracle is the recomputed hash, not the row: a pin recorded but not hashed would
    look recorded and replay under the wrong corpus — the very gap #392/#393 are blocked
    on. The fresh-orchestrator arm pins the read-from-the-row property: a resumed run
    keeps its pin without any flag being given.
    """
    monkeypatch.setenv("HARNESS_PROFILE", "edge-local")
    store = open_store(tmp_data_dir)
    try:
        cohort_id, version = _seed_corpus(store)
        _cohort, version = _seed_run(
            store, pins={"extractor": EXTRACTOR_PIN, "synthesizer": SYNTHESIZER_PIN},
            run_id="run-pin-34", cohort_id=cohort_id, version=version,
        )
        run_row_config = _run_config_json(store, "run-pin-34")
        assert run_row_config["model_pins"] == {
            "extractor": {
                "provider": EXTRACTOR_PIN.provider,
                "build_id": EXTRACTOR_PIN.build_id,
                "quantization": EXTRACTOR_PIN.quantization,
            },
            "synthesizer": {
                "provider": SYNTHESIZER_PIN.provider,
                "build_id": SYNTHESIZER_PIN.build_id,
                "quantization": SYNTHESIZER_PIN.quantization,
            },
        }, (
            "TC-PIPE-34: the pinned run's persisted config does not carry both refs. "
            "FR-PIPE-19: the pins are recorded in the run's frozen config — the row is "
            "what a replay reads, and a pin that never reached the row replays nothing"
        )

        Orchestrator(store).enumerate_units("run-pin-34")
        panel_config, prompt_v = _frozen_inputs(store, "run-pin-34")
        expected = {
            compute_work_id(
                run_id="run-pin-34",
                stage=row["stage"],
                submission_id=SUBMISSIONS[0],
                criterion_id=row["criterion_id"],
                judge_id=row["judge_id"],
                package_version_id=version,
                panel_config=panel_config,
                prompt_template_version=prompt_v,
                extractor_version=EXTRACTOR_PIN.build_id,
            )
            for row in _units(store, "run-pin-34")
        }
        assert {row["work_id"] for row in _units(store, "run-pin-34")} == expected, (
            "TC-PIPE-34: a unit's work_id does not hash the recorded extractor pin. The "
            "pin feeds compute_work_id's extractor_version input exactly as the module "
            "constant does — a hash that ignored it would replay the wrong corpus "
            "(TC-SMOKE-12, RES-19)"
        )

        # The pin is read from the run row, not from a caller: a FRESH orchestrator with
        # no flags re-enumerates byte-identical ids, and INSERT OR IGNORE reports the
        # pass a no-op rather than writing a second, differently-hashed population.
        fresh = Orchestrator(store).enumerate_units("run-pin-34")
        assert fresh.status == "no-op" and fresh.units_inserted == 0, (
            "TC-PIPE-34: a fresh orchestrator with no flags re-hashed the pinned run's "
            "units. The pin is a property of the run row — a re-enumeration that needs "
            "the flag repeated would fork the id space on every resume (NFR-ORCH-05)"
        )

        # The no-pin control: byte-identical to a pre-feature row (NFR-CONF-04).
        _seed_run(
            store, pins=None, run_id="run-nopin-34", cohort_id=cohort_id, version=version,
        )
        unpinned_config = _run_config_json(store, "run-nopin-34")
        assert "model_pins" not in unpinned_config, (
            "TC-PIPE-34: a run created without pins grew a model_pins key. NFR-CONF-04: "
            "the record is additive — an unpinned row must be byte-identical to its "
            "pre-feature shape, or every stored-row reader can tell which code wrote it"
        )
        Orchestrator(store).enumerate_units("run-nopin-34")
        panel_config, prompt_v = _frozen_inputs(store, "run-nopin-34")
        expected = {
            compute_work_id(
                run_id="run-nopin-34",
                stage=row["stage"],
                submission_id=SUBMISSIONS[0],
                criterion_id=row["criterion_id"],
                judge_id=row["judge_id"],
                package_version_id=version,
                panel_config=panel_config,
                prompt_template_version=prompt_v,
                extractor_version=EXTRACTOR_VERSION,
            )
            for row in _units(store, "run-nopin-34")
        }
        assert {row["work_id"] for row in _units(store, "run-nopin-34")} == expected, (
            "TC-PIPE-34: an unpinned run's work_ids do not hash the module constant. "
            "TC-REG-06's committed reference population is unchanged — a run without a "
            "pin keeps the pre-feature identity, byte for byte"
        )
    finally:
        store.close()


def test_tc_pipe_34_the_cli_records_the_pins_it_was_given(
    tmp_data_dir, tmp_path, monkeypatch
):
    """`TC-PIPE-34`'s stated input — the run is CREATED BY `aeh run` with both flags.

    `_seed_run`'s direct-`create_run` arms pin what M-ORCH records once a caller hands it
    pins; this arm pins the seam the flags themselves added: `main` resolving the two
    `--extractor` / `--synthesizer` values and threading them into `create_run`. If the
    CLI call dropped `model_pins=`, the direct arms would still pass while `aeh run
    --extractor` recorded nothing — so the oracle here is the ROW after `main` returns.

    The store this drives is edge-local's, and the seeded corpus has no ingested
    documents: the drive faults at the extract stage with a composition fault, which exits
    1 by design (#365's deliberate narrowing of FR-PIPE-08's "3 on paused"). The case's
    oracle is what the CLI did BEFORE the first stage ran — the run row exists, carrying
    both pins — plus the units `run_to_completion` enumerated hashing the pinned build,
    which the CLI-threaded identity produced.
    """
    from aeh.pipeline.cli import main

    monkeypatch.setenv("HARNESS_PROFILE", "edge-local")
    monkeypatch.setenv("HARNESS_HARDWARE_PROFILE", "unified-large")
    store = open_store(tmp_data_dir)
    try:
        cohort_id, version = _seed_corpus(store)
    finally:
        store.close()
    config_file = tmp_path / "profiles.toml"
    config_file.write_text(f_profiles_toml(), encoding="utf-8")

    code = main([
        "run",
        "--data-dir", str(tmp_data_dir),
        "--config", str(config_file),
        "--cohort", cohort_id,
        "--package-version", version,
        "--extractor", _ref_string(EXTRACTOR_PIN),
        "--synthesizer", _ref_string(SYNTHESIZER_PIN),
    ])
    assert code == 1, (
        f"TC-PIPE-34: the pinned run's drive exited {code!r}; the seeded corpus has no "
        "ingested documents, so the drive faults at extraction and a composition fault "
        "exits 1 by design — the case pins the recording and the hash, not the drive's "
        "completion"
    )

    store = open_store(tmp_data_dir)
    try:
        rows = store.cohort(cohort_id).query(
            Statement("SELECT run_id, provider_config FROM run"))
        assert len(rows) == 1, f"TC-PIPE-34: expected one run row, got {rows!r}"
        run_id = rows[0]["run_id"]
        config = json.loads(rows[0]["provider_config"])
        assert config["model_pins"] == {
            "extractor": {
                "provider": EXTRACTOR_PIN.provider,
                "build_id": EXTRACTOR_PIN.build_id,
                "quantization": EXTRACTOR_PIN.quantization,
            },
            "synthesizer": {
                "provider": SYNTHESIZER_PIN.provider,
                "build_id": SYNTHESIZER_PIN.build_id,
                "quantization": SYNTHESIZER_PIN.quantization,
            },
        }, (
            "TC-PIPE-34: `aeh run --extractor/--synthesizer` did not record both refs in "
            "the run's frozen config. FR-PIPE-19 threads the flags into create_run — a "
            "CLI that dropped the kwarg would leave every pinned replay unpinned"
        )
        Orchestrator(store).enumerate_units(run_id)
        panel_config, prompt_v = _frozen_inputs(store, run_id)
        expected = {
            compute_work_id(
                run_id=run_id,
                stage=row["stage"],
                submission_id=row["submission_id"],
                criterion_id=row["criterion_id"],
                judge_id=row["judge_id"],
                package_version_id=version,
                panel_config=panel_config,
                prompt_template_version=prompt_v,
                extractor_version=EXTRACTOR_PIN.build_id,
            )
            for row in _units(store, run_id)
        }
        assert expected, "TC-PIPE-34: the CLI-driven run enumerated no units at all"
        assert {row["work_id"] for row in _units(store, run_id)} == expected, (
            "TC-PIPE-34: the units `aeh run` enumerated do not hash the pinned build. "
            "The CLI threads the ref into run_to_completion, whose executor drives the "
            "same _unit the row's pin feeds — a dropped thread would hash EXTRACTOR_VERSION"
        )
    finally:
        store.close()


def _frozen_inputs(store, run_id: str) -> tuple[str, str]:
    """The run's frozen `panel_config` and prompt-template version, for recomputation."""
    rows = store.cohort("c-2026-7B-orch").query(
        Statement("SELECT panel_config, prompt_template_v FROM run WHERE run_id = :r"),
        r=run_id,
    )
    return rows[0]["panel_config"], rows[0]["prompt_template_v"]


# --- TC-PIPE-35 — an unresolvable ref exits 1 with no run row -------------------------------


#: The plan's three refusal values, plus a fourth that is RESOLVED but in the wrong
#: form for `edge-local` (a provider-pinned slug where a weights build is required) —
#: the form-discrimination half of `CT-CONF-03`.
BAD_PINS = (
    "no-separator-here",
    "P1|B1@latest",
    "P1|/models/m.gguf@sha256:abcd",
    "P1|B1@sha256:abcd",
)


@pytest.mark.parametrize("flag", ("--extractor", "--synthesizer"))
@pytest.mark.parametrize("bad", BAD_PINS)
def test_tc_pipe_35_an_unresolvable_pin_exits_1_before_the_store_opens(
    flag, bad, tmp_data_dir, monkeypatch, capsys
):
    """`TC-PIPE-35` — each bad value exits 1, names the flag, and creates no run row.

    "The store is never opened" is the assertion a store opened AFTERWARDS makes: the
    refusal runs before `_open_store`, so the data directory the command was pointed at
    holds a store with zero runs — not a store with a half-created one.
    """
    from aeh.pipeline.cli import main

    monkeypatch.setenv("HARNESS_PROFILE", "edge-local")
    argv = [
        "run",
        "--data-dir", str(tmp_data_dir),
        "--cohort", "c-2026-7B-orch",
        "--package-version", "pv-pins",
        flag, bad,
    ]
    code = main(list(argv))
    output = "".join(capsys.readouterr())
    assert code == 1, (
        f"TC-PIPE-35: main returned {code!r} for {flag}={bad!r}; the plan pins exit 1 "
        "for an unresolvable ref"
    )
    assert flag in output, (
        f"TC-PIPE-35: the refusal for {flag}={bad!r} does not name the flag. An operator "
        f"reading {output!r} has to guess which of the two pins they set wrong"
    )

    store = open_store(tmp_data_dir)
    try:
        rows = store.cohort("c-2026-7B-orch").query(Statement("SELECT COUNT(*) AS n FROM run"))
        assert rows[0]["n"] == 0, (
            f"TC-PIPE-35: a run row exists after {flag}={bad!r} was refused. The store is "
            "never opened for an unresolvable ref — a refusal that created the row first "
            "would leave a run the operator cannot resume or see in any console"
        )
    finally:
        store.close()


@pytest.mark.parametrize("bad", BAD_PINS)
def test_tc_pipe_35_recover_with_an_unresolvable_pin_exits_1_before_the_store_opens(
    bad, tmp_data_dir, monkeypatch, capsys
):
    """`TC-PIPE-35`'s recover arm — the same three refusals on `aeh recover`.

    The AC's refusal is stated for `aeh run` OR `aeh recover`, and recovery resolves its
    pins through the same `_model_pins` call before its own `_open_store`. The refusal is
    asserted the way the plan states it: a store opened afterwards counts 0 runs. A
    cohort ledger file is the other thing an open would have written, so its absence is
    checked too — `tmp_data_dir`'s fixture scaffolding (packages/cohorts/blobs) is
    pre-created, so a bare empty-directory assert would assert the fixture, not the
    command.
    """
    from aeh.pipeline.cli import main

    monkeypatch.setenv("HARNESS_PROFILE", "edge-local")
    code = main(["recover", "--data-dir", str(tmp_data_dir), "--extractor", bad])
    output = "".join(capsys.readouterr())
    assert code == 1, (
        f"TC-PIPE-35: main returned {code!r} for recover --extractor {bad!r}; the plan "
        "pins exit 1 for an unresolvable ref"
    )
    assert "--extractor" in output, (
        f"TC-PIPE-35: the recover refusal for {bad!r} does not name the flag: {output!r}"
    )
    assert list(tmp_data_dir.rglob("*.sqlite")) == [], (
        f"TC-PIPE-35: the refused recover opened a store — a ledger file exists in the "
        f"data directory ({[str(p) for p in tmp_data_dir.rglob('*.sqlite')]}) — the "
        "store was opened before the pin was resolved, the posture the AC refuses"
    )
    store = open_store(tmp_data_dir)
    try:
        rows = store.cohort("c-2026-7B-orch").query(
            Statement("SELECT COUNT(*) AS n FROM run"))
        assert rows[0]["n"] == 0, (
            f"TC-PIPE-35: a run row exists after recover --extractor {bad!r} was "
            "refused. The store is never opened for an unresolvable ref — a refusal "
            "that created the row first would leave a run the operator cannot resume "
            "or see in any console"
        )
    finally:
        store.close()


# --- TC-PIPE-36 — recover and resume keep the pin the run froze ------------------------------


@pytest.fixture
def pinned_run(tmp_data_dir, monkeypatch):
    """A run created WITH pins, over a real store; the store is returned open for reads.

    `HARNESS_HARDWARE_PROFILE` is set alongside `HARNESS_PROFILE` because `main` resolves
    the effective configuration from the environment alone, and `edge-local` requires the
    hardware profile (`FR-CONF-06`) — without it a `ConfigurationError` fires before the
    pin checks the case is about. It is the same hardware profile `edge_cfg` seeded the
    run under, so the backend-profile refusal cannot be the thing that fires instead.
    """
    monkeypatch.setenv("HARNESS_PROFILE", "edge-local")
    monkeypatch.setenv("HARNESS_HARDWARE_PROFILE", "unified-large")
    store = open_store(tmp_data_dir)
    try:
        cohort_id, version = _seed_corpus(store)
        cohort_id, version = _seed_run(
            store, pins={"extractor": EXTRACTOR_PIN, "synthesizer": SYNTHESIZER_PIN},
            run_id="run-pin-36", cohort_id=cohort_id, version=version,
        )
        yield store, tmp_data_dir, cohort_id, version
    finally:
        store.close()


def test_tc_pipe_36_recover_with_the_same_pin_exits_0(pinned_run, capsys):
    """`TC-PIPE-36` (a) — `aeh recover --extractor <same>` agrees with the frozen pin."""
    from aeh.pipeline.cli import main

    code = main(["recover", "--data-dir", str(pinned_run[1]),
                 "--extractor", _ref_string(EXTRACTOR_PIN)])
    assert code == 0, (
        f"TC-PIPE-36(a): recover with the pin the run froze exited {code!r}. "
        f"{capsys.readouterr()!r}"
    )


@pytest.mark.parametrize(
    "flag, frozen_ref, other", (
        ("--extractor", EXTRACTOR_PIN, OTHER_EXTRACTOR_PIN),
        ("--synthesizer", SYNTHESIZER_PIN, OTHER_SYNTHESIZER_PIN),
    ))
def test_tc_pipe_36_recover_with_a_different_pin_is_refused_before_it_writes(
    pinned_run, flag, frozen_ref, other, capsys
):
    """`TC-PIPE-36` (b) — exit 1, both builds named, nothing written, for EITHER role.

    The role a flag names is the role `recover`'s mismatch check compares — a typo that
    wired the synthesizer's flag to the extractor's comparison would leave only this
    second arm to catch it.

    "Before it writes" is the run row's own state: recovery's first writes are the sweep
    and the resume, and the refusal precedes both, so the row the seeded run left is
    exactly the row the refusal leaves.
    """
    from aeh.pipeline.cli import main

    _store, data_dir, _cohort, _version = pinned_run
    code = main(["recover", "--data-dir", str(data_dir),
                 flag, _ref_string(other)])
    output = "".join(capsys.readouterr())
    assert code == 1, f"TC-PIPE-36(b): a mismatched pin exited {code!r}; the plan pins 1"
    assert frozen_ref.build_id in output and other.build_id in output, (
        f"TC-PIPE-36(b): the refusal does not name both builds. An operator who typed "
        f"the flag to 'set' a pin needs to see which build the run actually froze: "
        f"{output!r}"
    )
    rows = _store.cohort("c-2026-7B-orch").query(
        Statement("SELECT status, pause_reason FROM run WHERE run_id = 'run-pin-36'")
    )
    assert rows[0]["status"] == "pending" and rows[0]["pause_reason"] is None, (
        f"TC-PIPE-36(b): the refusal wrote to the run row first ({rows[0]!r}). Recovery "
        "refuses BEFORE the sweep — the first write it can make — so a rejected flag "
        "changes nothing the operator can see"
    )


def test_tc_pipe_36_recover_with_no_flags_keeps_the_run_pin(pinned_run):
    """`TC-PIPE-36` (c) — recovery keeps the run's own recorded pin when it re-enumerates.

    The pin is read from the run row by the enumeration itself (`_unit`), so the no-flag
    recovery neither needs nor takes a pin: the ids the run hashes stay the pinned ones.
    """
    from aeh.pipeline.cli import main

    store, data_dir, _cohort, _version = pinned_run
    code = main(["recover", "--data-dir", str(data_dir)])
    assert code == 0, f"TC-PIPE-36(c): a no-flag recovery exited {code!r}"
    Orchestrator(store).enumerate_units("run-pin-36")
    panel_config, prompt_v = _frozen_inputs(store, "run-pin-36")
    expected = {
        compute_work_id(
            run_id="run-pin-36",
            stage=row["stage"],
            submission_id=SUBMISSIONS[0],
            criterion_id=row["criterion_id"],
            judge_id=row["judge_id"],
            package_version_id=_version,
            panel_config=panel_config,
            prompt_template_version=prompt_v,
            extractor_version=EXTRACTOR_PIN.build_id,
        )
        for row in _units(store, "run-pin-36")
    }
    assert {row["work_id"] for row in _units(store, "run-pin-36")} == expected, (
        "TC-PIPE-36(c): re-enumeration after a no-flag recovery did not hash the run's "
        "own recorded pin. The pin is the run's, not the process's — a recovery pass "
        "that fell back to the module constant would fork the id space"
    )


def test_tc_pipe_36_run_with_a_different_pin_is_refused_as_the_profile_switch_is(
    pinned_run, tmp_path, capsys
):
    """`TC-PIPE-36`'s `aeh run` arm — a different build on an existing run is refused.

    Same posture the backend-profile refusal has (`_run_command`, FR-CONF-15): the run
    froze its identities and this process names another. The refusal names both builds.

    The invocation carries a `--config` file because `main` resolves a FRESH `RunConfig`
    from the effective configuration — env keys carry no panel, and the resolution
    (`resolve_run_config`) runs before the pin check, so without a resolvable panel the
    ConfigurationError about the panel would fire first and the case would pin nothing.
    The file's edge-local section supplies it; the environment's hardware profile
    (`unified-large`, the one the run was seeded under) wins over the file's.
    """
    from aeh.pipeline.cli import main

    _store, data_dir, cohort_id, version = pinned_run
    config_file = tmp_path / "profiles.toml"
    config_file.write_text(f_profiles_toml(), encoding="utf-8")
    code = main([
        "run",
        "--data-dir", str(data_dir),
        "--config", str(config_file),
        "--cohort", cohort_id,
        "--package-version", version,
        "--extractor", _ref_string(OTHER_EXTRACTOR_PIN),
    ])
    output = "".join(capsys.readouterr())
    assert code == 1, f"TC-PIPE-36: the mismatched run flag exited {code!r}; the plan pins 1"
    assert EXTRACTOR_PIN.build_id in output and OTHER_EXTRACTOR_PIN.build_id in output, (
        f"TC-PIPE-36: the refusal does not name both builds: {output!r}"
    )
