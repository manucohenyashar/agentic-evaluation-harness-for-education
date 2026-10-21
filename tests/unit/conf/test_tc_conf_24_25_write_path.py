"""The guided configuration write path and the projection it renders.

Cases: `TC-CONF-24` (`FR-CONF-34` / `CT-CONF-24` / **RS-07**, P0) and `TC-CONF-25`
(`FR-CONF-35`, P1), test plan §3.3. Rung 0/1 (E1) — file-system only: temp-dir profile
files, no provider, no store. Issue #769; the implementation is #756 (`update_profile_edits`,
`configuration_projection`), so everything here is expected to pass.

RS-07 is the risk this suite exists for: a half-written profile takes the teacher's whole
tool down at the next console start, silently. That makes the *oracle* the point, not the
exercise — byte-identity is asserted by hash, never by re-parse; the mid-write arm injects
its fault between the temp file and the `os.replace` commit point rather than checking that
"refusals don't write"; and the refusal oracle is the loader's own message, derived live
from `resolve_run_config` so copy drift fails.
"""

from __future__ import annotations

import hashlib
import os
from decimal import Decimal

import pytest

from aeh.conf import (
    CONSOLE_KEYS,
    DECISION_KEYS,
    EDITABLE_SETTINGS,
    HARNESS_KEYS,
    ConfigurationError,
    ModelRef,
    RunConfigError,
    UnresolvedModelRefError,
    configuration_projection,
    parse_config_document,
    resolve_run_config,
    select_profile_config,
    update_profile_edits,
)
from tests.support.conf_builders import (
    SENTINEL_CREDENTIAL,
    SYNTHETIC_COHORT,
    hosted_cfg,
    seed_credentials,
)

#: A two-profile configuration file in the shape `config/harness.example.toml` spells, with
#: comments and an inline comment on a key the suite edits — the splice must leave every line
#: it does not touch byte-for-byte, comments included, and the loader must resolve both
#: profiles of the result. `dev-ci` is the profile the cases edit; `cloud-hosted` must come
#: through every edit untouched.
TOML_TEXT = """\
# Test configuration: every comment here must survive the splice byte-for-byte.
prompt_template_v = "judge-prompt/3"

[profiles.cloud-hosted]
HARNESS_COST_CEILING = 50
HARNESS_COST_CURRENCY = "USD"
retention_setting = "zero-retention"
HARNESS_DECISION_ENGINE = "jev"
HARNESS_DECISION_PROVIDER = "openrouter-jev"
HARNESS_JEV_BUILD = "openrouter/typesafe/jev-1.13@20260917"

[profiles.cloud-hosted.transcriber]
role = "transcriber"
provider = "openrouter"
build_id = "openrouter/qwen/qwen3-vl-8b-instruct@2026-06-01"

[[profiles.cloud-hosted.panel]]
role = "judge"
provider = "openrouter"
build_id = "openrouter/qwen/qwen3-30b-a3b@2026-06-01"

[profiles.dev-ci]
HARNESS_COST_CEILING = 5  # nightly budget
HARNESS_COST_CURRENCY = "USD"
HARNESS_DECISION_ENGINE = "jev"
HARNESS_DECISION_PROVIDER = "openrouter-jev"
HARNESS_JEV_BUILD = "openrouter/typesafe/jev-1.13@20260917"

[profiles.dev-ci.transcriber]
role = "transcriber"
provider = "openrouter"
build_id = "openrouter/qwen/qwen3-vl-8b-instruct@2026-06-01"

[[profiles.dev-ci.panel]]
role = "judge"
provider = "openrouter"
build_id = "openrouter/qwen/qwen3-30b-a3b@2026-06-01"
"""

#: The edit's model reference for the grader (the panel's judges): a pinned OpenRouter build
#: in the `provider|build_id` form the guided form accepts, one date later than the file's.
NEW_BUILD = "openrouter/qwen/qwen3-30b-a3b@2026-06-02"
NEW_GRADING_MODEL = f"openrouter|{NEW_BUILD}"

#: A legal edit of the cost ceiling, as the guided form sends it.
NEW_CEILING = "7.5"

#: The pinless spelling the loader refuses (arm b) — a real build slug with no `@pin`, so it
#: parses fine and fails only the resolver's `is_resolved` check.
UNPINNED_BUILD = "openrouter/qwen/qwen3-30b-a3b"

#: The credential sentinel (arm d): a value a real key would carry, asserted never to reach
#: the refusal message or the file (`NFR-CONF-02`).
API_KEY_SENTINEL = "sk-sentinel-do-not-echo"


def _write_config(tmp_path, name: str = "harness.toml") -> str:
    path = tmp_path / name
    # Bytes, not text: `write_text` would translate the line endings on Windows, and the
    # splice's byte-level oracle must not depend on the platform's default newline.
    path.write_bytes(TOML_TEXT.encode("utf-8"))
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _changed_paths(before, after, prefix: str = "") -> list[str]:
    """The dotted paths where two parsed documents differ — the "exactly those keys" oracle.

    `panel` recurses per member, so one judge's new build reads as `profiles.dev-ci.panel[0]`
    rather than the whole table. A `ModelRef` is a leaf: its frozen equality covers
    `provider`, `build_id` and `quantization`.
    """
    if isinstance(before, dict) and isinstance(after, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                paths.append(child)
            else:
                paths.extend(_changed_paths(before[key], after[key], child))
        return paths
    if isinstance(before, (list, tuple)) and isinstance(after, (list, tuple)):
        if len(before) != len(after):
            return [prefix]
        paths = []
        for index, (left, right) in enumerate(zip(before, after)):
            paths.extend(_changed_paths(left, right, f"{prefix}[{index}]"))
        return paths
    return [] if before == after else [prefix]


def _load(profile_path: str, profile: str):
    """The configuration a fresh load of the file resolves to — the "next load" the oracle
    names. The synthetic cohort is the one the write path itself validates against."""
    doc = parse_config_document(_read_text(profile_path), "toml")
    return resolve_run_config(select_profile_config(doc, profile), SYNTHETIC_COHORT)


def _read_text(path: str) -> str:
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8")


# --- TC-CONF-24 -----------------------------------------------------------------------------

#: (a) A valid edit — the grader's model and the cost ceiling — lands in the file as a splice,
#: and the next load reflects exactly those keys and nothing else.
def test_tc_conf_24_a_valid_edit_leaves_a_file_the_next_load_reads_exactly_as_edited(tmp_path):
    profile_path = _write_config(tmp_path)
    before_text = _read_text(profile_path)
    before_doc = parse_config_document(before_text, "toml")

    result = update_profile_edits(
        profile_path,
        {"grading_model": NEW_GRADING_MODEL, "cost_ceiling": NEW_CEILING},
        profile="dev-ci",
    )

    after_text = _read_text(profile_path)
    after_doc = parse_config_document(after_text, "toml")

    # Byte-identity is not the oracle here — the edit is meant to land — but the *splice*
    # shape is: the same number of lines, every unedited line byte-identical (comments
    # included), and exactly the two edited key lines rewritten.
    before_lines = before_text.splitlines(keepends=True)
    after_lines = after_text.splitlines(keepends=True)
    assert len(after_lines) == len(before_lines), (
        "the splice must rewrite keys in place, not re-serialize the file"
    )
    rewritten = [
        index for index, (old, new) in enumerate(zip(before_lines, after_lines)) if old != new
    ]
    assert len(rewritten) == 2, (
        f"exactly the two edited key lines should differ, got {len(rewritten)}: "
        f"{[before_lines[i] for i in rewritten]} -> {[after_lines[i] for i in rewritten]}"
    )
    new_lines = [after_lines[index].rstrip("\r\n") for index in rewritten]
    assert sorted(line.split("=")[0].strip() for line in new_lines) == [
        "HARNESS_COST_CEILING", "build_id",
    ]
    assert f'build_id = "{NEW_BUILD}"' in new_lines
    # The inline comment survives, with the gap that separated it from the value.
    assert 'HARNESS_COST_CEILING = "7.5"  # nightly budget' in new_lines
    # The file's leading comment — outside every edited key — survives byte-for-byte.
    assert after_lines[0] == before_lines[0]

    # The next load reflects exactly those keys and nothing else.
    changed = _changed_paths(before_doc, after_doc)
    assert changed == [
        "profiles.dev-ci.HARNESS_COST_CEILING",
        "profiles.dev-ci.panel[0]",
    ], f"the edit changed {changed}, not exactly the named keys"

    config = resolve_run_config(select_profile_config(after_doc, "dev-ci"), SYNTHETIC_COHORT)
    assert config.panel[0].build_id == NEW_BUILD
    assert config.panel[0].provider == "openrouter"
    assert config.panel[0].quantization is None
    assert len(config.panel) == 1  # the panel's member count is preserved, not rewritten
    assert config.cost_ceiling == Decimal(NEW_CEILING)

    # The other profile is untouched by an edit scoped to dev-ci — byte-equal in the parse,
    # and still resolvable as a whole.
    assert _changed_paths(
        select_profile_config(before_doc, "cloud-hosted"),
        select_profile_config(after_doc, "cloud-hosted"),
    ) == []
    resolve_run_config(select_profile_config(after_doc, "cloud-hosted"), SYNTHETIC_COHORT)

    # One outcome row per named edit, showing both the value it replaced and what it became.
    assert [outcome.setting for outcome in result.edits] == ["grading_model", "cost_ceiling"]
    assert result.edits[0].before == "openrouter|openrouter/qwen/qwen3-30b-a3b@2026-06-01"
    assert result.edits[0].after == NEW_GRADING_MODEL
    assert result.edits[1].before == "5"
    assert result.edits[1].after == NEW_CEILING


#: (b) An invalid edit — a model name the loader refuses — is refused with the loader's own
#: message, and the file is byte-identical by hash.
def test_tc_conf_24_b_an_unknown_model_name_is_refused_with_the_loaders_message_and_leaves_the_file_byte_identical(tmp_path):
    profile_path = _write_config(tmp_path)
    hash_before = _sha256(profile_path)

    # The loader's own refusal, derived live: the same document the write path would have
    # spliced, resolved the way the write path validates. Asserting against *this* — not a
    # copied string — is what makes message copy drift fail.
    doc = parse_config_document(TOML_TEXT, "toml")
    doc["profiles"]["dev-ci"]["panel"] = (
        ModelRef(role="judge", provider="openrouter", build_id=UNPINNED_BUILD, quantization=None),
    )
    with pytest.raises(UnresolvedModelRefError) as loader_refusal:
        resolve_run_config(select_profile_config(doc, "dev-ci"), SYNTHETIC_COHORT)
    expected_message = str(loader_refusal.value)

    # The write path does not re-word the loader's refusal: `update_profile_edits` validates
    # the spliced document with the loader itself, and whatever the loader raised propagates.
    # `RunConfigError` is the shared base, because `UnresolvedModelRefError` is deliberately a
    # *sibling* of `ConfigurationError` — the exact type is part of the loader's own message.
    with pytest.raises(RunConfigError) as refusal:
        update_profile_edits(
            profile_path,
            {"grading_model": f"openrouter|{UNPINNED_BUILD}"},
            profile="dev-ci",
        )

    assert type(refusal.value) is type(loader_refusal.value), (
        "the refusal must be the loader's own error, not a re-worded one"
    )
    assert str(refusal.value) == expected_message, (
        "the refusal message must be the loader's own, verbatim"
    )
    # NFR-CONF-02: the caller data is not echoed back.
    assert UNPINNED_BUILD not in str(refusal.value)

    assert _sha256(profile_path) == hash_before, (
        "a refused edit must leave the file byte-identical (CT-CONF-24)"
    )
    # And no write machinery ran at all — nothing half-written on disk either.
    leftovers = [p.name for p in tmp_path.iterdir() if ".aeh-tmp-" in p.name]
    assert leftovers == []


#: (c) A crash after the temp file is written and before the `os.replace` commit point leaves
#: the original file intact and no temp file behind — the arm that catches RS-07 directly.
def test_tc_conf_24_c_a_crash_after_the_temp_file_and_before_the_replace_leaves_the_original_intact(tmp_path, monkeypatch):
    profile_path = _write_config(tmp_path, "faulted.toml")
    twin_path = _write_config(tmp_path, "twin.toml")
    hash_before = _sha256(profile_path)

    # The twin proves what the committed file *would* have been, so the captured temp file
    # can be checked for exactly those bytes: the hook demonstrably fires after the temp
    # file is fully written, not before.
    update_profile_edits(
        twin_path,
        {"grading_model": NEW_GRADING_MODEL, "cost_ceiling": NEW_CEILING},
        profile="dev-ci",
    )
    committed_bytes = open(twin_path, "rb").read()

    observed: dict[str, object] = {"replacements": 0}

    def detonating_replace(source, destination):
        observed["replacements"] += 1
        observed["temp_path"] = source
        observed["temp_bytes"] = open(source, "rb").read()
        raise OSError("simulated: the replace never committed")

    monkeypatch.setattr("os.replace", detonating_replace)

    with pytest.raises(OSError, match="simulated"):
        update_profile_edits(
            profile_path,
            {"grading_model": NEW_GRADING_MODEL, "cost_ceiling": NEW_CEILING},
            profile="dev-ci",
        )

    # The commit point was reached exactly once, with the temp file fully written.
    assert observed["replacements"] == 1, "the replace is the single commit point"
    assert observed["temp_bytes"] == committed_bytes, (
        "the fault must fire after the temp file carries the complete new document"
    )
    # The temp file lived beside the target — the same volume, which is what makes the
    # rename atomic. A temp file in the process directory or the system temp store would
    # cross a volume boundary and lose exactly the guarantee RS-07 exists for.
    assert os.path.dirname(str(observed["temp_path"])) == os.path.dirname(profile_path)

    # The original file is intact and uncommitted — byte-identical, still the old values.
    assert _sha256(profile_path) == hash_before
    config = _load(profile_path, "dev-ci")
    assert config.panel[0].build_id == "openrouter/qwen/qwen3-30b-a3b@2026-06-01"
    assert config.cost_ceiling == Decimal(5)

    # The temp file was unlinked: no half-written profile is ever observable on disk.
    leftovers = [p.name for p in tmp_path.iterdir() if ".aeh-tmp-" in p.name]
    assert leftovers == [], f"the interrupted write left temp files behind: {leftovers}"


#: (d) An edit naming a credential is refused by name, echoes no value, and writes nothing.
def test_tc_conf_24_d_an_edit_naming_a_credential_is_refused_by_name_and_writes_nothing(tmp_path):
    profile_path = _write_config(tmp_path)
    hash_before = _sha256(profile_path)

    with pytest.raises(ConfigurationError) as refusal:
        update_profile_edits(
            profile_path,
            {"OPENROUTER_API_KEY": API_KEY_SENTINEL},
            profile="dev-ci",
        )

    message = str(refusal.value)
    assert "credential" in message and "secret" in message, (
        "the refusal must name the rule — secrets are never writable through this surface — "
        "so the caller is told rather than left guessing"
    )
    # NFR-CONF-02: the refusal echoes no value.
    assert API_KEY_SENTINEL not in message
    assert _sha256(profile_path) == hash_before, "nothing was written"
    # And nothing half-written is on disk either.
    leftovers = [p.name for p in tmp_path.iterdir() if ".aeh-tmp-" in p.name]
    assert leftovers == []


# --- TC-CONF-25 -----------------------------------------------------------------------------

#: FR-CONF-34's teacher-editable subset, as the design delta states it: the model per action
#: role, the cost ceiling, the decision engine choice, and the decision engine's four
#: review-window gates. The literal is the oracle — `EDITABLE_SETTINGS` must equal it, and the
#: projection's `editable` flags must equal it too, so a setting cannot render as editable and
#: refuse the edit (or the reverse).
_EDITABLE_IDS = {
    "grading_model",
    "page_reader_model",
    "qa_assistant_model",
    "decision_engine_model",
    "decision_engine",
    "decision_confidence_gate",
    "decision_citation_gate",
    "decision_citation_question_limit",
    "decision_token_bytes_ratio",
    "cost_ceiling",
}

#: The type tags the form renderer switches on.
_TYPE_TAGS = frozenset({"choice", "text", "number", "secret"})

#: The key names a configuration file spells — everything the loader reads from the file —
#: none of which may appear anywhere in the projection's strings (FR-CONF-35). The
#: `HARNESS_*`/`CONSOLE_*`/`DECISION_*` namespaces come from the module's own constants, so
#: the list cannot drift from the loader; the rest are the file-only keys, spelled literally.
_FILE_KEY_NAMES = (
    *HARNESS_KEYS,
    *CONSOLE_KEYS,
    *DECISION_KEYS,
    "OPENROUTER_API_KEY",
    "profiles",
    "panel",
    "transcriber",
    "off_panel_checker",
    "prompt_template_v",
    "retention_setting",
    "hardware_profiles",
    "decision_model",
    "decision_confidence_threshold",
    "hosted_prefix_token_ceiling",
    "allow_remote_real_work_supplied_by",
    # The keys of a model table, which the file spells and the projection must translate.
    "build_id",
    "quantization",
    "escalation_judge",
    "HARNESS_FIXTURE_DIR",
    # `role` and `provider` are deliberately absent from this list: they are English words the
    # teacher's own vocabulary uses — the projection's label "Model provider key" says
    # "provider" — and the oracle's target is the file's configuration vocabulary leaking
    # through, not a shared word of English. The unambiguous snake_case table keys above are
    # scanned, so a table key added later to the file's model grammar is still caught.
    # (The three namespace tuples above are taken from the loader's own constants; the literal
    # entries here are pinned to the keys this module reads from a file today.)
)


def test_tc_conf_25_the_projection_renders_every_setting_safely(monkeypatch):
    # A real secret to not leak: seeded in the environment *and* placed in the composed
    # configuration itself. Without the second half the "never a value" oracle below is
    # vacuous — an implementation echoing whatever it finds in `cfg` would find nothing and
    # pass, whatever it did (`TC-CONF-11`'s vacuous-pass warning, verbatim).
    sentinel = seed_credentials(monkeypatch)
    cfg_with_secret = hosted_cfg(**{"OPENROUTER_API_KEY": SENTINEL_CREDENTIAL})

    views = configuration_projection(cfg_with_secret)

    # Every setting present, with a teacher label, a type tag and an editable flag — 20
    # settings (FR-CONF-36 added the second-opinion budget and the random extra-grader
    # sample), each named once.
    assert len(views) == 20, f"the projection carries {len(views)} settings, not 20"
    assert len({view.setting for view in views}) == 20, "a setting is named twice"
    for view in views:
        assert isinstance(view.label, str) and view.label.strip(), (
            f"{view.setting} has no teacher label"
        )
        assert view.type in _TYPE_TAGS, (
            f"{view.setting} has type {view.type!r}, not a tag the form renderer knows"
        )
        assert isinstance(view.editable, bool), f"{view.setting}'s editable flag is not a bool"

    # The editable set is FR-CONF-34's subset exactly — the same list the write path
    # accepts, and neither more nor less.
    assert set(EDITABLE_SETTINGS) == _EDITABLE_IDS, (
        "the write path's allow-list is not FR-CONF-34's subset"
    )
    assert {view.setting for view in views if view.editable} == _EDITABLE_IDS, (
        "the projection's editable flags are not FR-CONF-34's subset"
    )

    # The secret projects as a boolean configured state, never a value.
    secrets = [view for view in views if view.type == "secret"]
    assert len(secrets) == 1, f"exactly one secret is projected, got {len(secrets)}"
    configured_view = configuration_projection(
        cfg_with_secret, secrets_configured={"model_provider_key": True}
    )
    configured_secret = next(
        view for view in configured_view if view.type == "secret")
    unconfigured_secret = secrets[0]
    assert configured_secret.setting == "model_provider_key"
    assert unconfigured_secret.setting == "model_provider_key"
    assert configured_secret.value == "" and unconfigured_secret.value == "", (
        "a secret's projected value must always be the empty string"
    )
    assert configured_secret.configured is True
    assert unconfigured_secret.configured is False

    # No key name from the configuration file appears anywhere in the projection's strings —
    # and neither does the sentinel credential itself, which the scan above cannot see
    # because it is a value, not a key name.
    emitted: list[str] = []
    for projected in (views, configured_view):
        for view in projected:
            emitted.extend((view.setting, view.label, view.value, view.type, *view.choices))
    for key in _FILE_KEY_NAMES:
        offenders = [text for text in emitted if key in text]
        assert not offenders, (
            f"the file key {key!r} appears in the projection's strings: {offenders}"
        )
    assert not [text for text in emitted if sentinel in text], (
        "the seeded credential leaked into the projection's strings"
    )
