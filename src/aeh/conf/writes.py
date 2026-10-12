"""`update_profile_edits` (FR-CONF-34): the guided write path into a configuration file.

The console's `update configuration` action is the only caller in this delta. It accepts only
the teacher-editable subset — `projection.EDITABLE_SETTINGS`, the same list the projection
marks editable — applies only the named keys to the current file, validates the result with the
loader's own parser and resolver, and writes atomically: a temporary file in the same
directory, then one `os.replace` — the commit point. A validation failure writes nothing, so a
refused update leaves the file byte-identical; a mid-write failure (the replace raising after
the temp file exists) leaves the original intact and unlinks the temp file, so a reader never
observes a half-written profile (CT-CONF-24).

The edit is a **splice, not a re-serialization**: every line outside the edited keys survives
byte-for-byte, comments included — the file stays the operator's editing surface, and the next
load reflects exactly the edited keys and nothing else. Anything the splice cannot apply
confidently (a model spelled as an inline array rather than its own table, a key inside a
multi-line value) is refused with a sentence naming the file, never half-applied: a splice
that cannot parse confidently would corrupt on write, so it refuses instead. `JSON` files are
re-serialized deterministically (`sort_keys`, two-space indent) because JSON has no comments
to lose.

Secrets and non-teacher settings are not writable through this surface: an edit id that names
a credential is refused with that named, and any other unknown id is refused with the
projection's rule. Neither refusal echoes a value (`NFR-CONF-02`).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .decision_engine import DECISION_PROVIDERS_BY_PROFILE
from .errors import ConfigurationError
from .model_ref import ModelRef, _ref_to_dict
from .projection import EDITABLE_SETTINGS, _ref_of, _ref_text
from .qa_model import QA_MODEL_KEY, QA_MODEL_PROVIDER, QA_MODEL_ROLE
from .run_config import CohortRef
from .resolution import resolve_run_config
from .sources import parse_config_document, select_profile_config


#: The cohort the post-edit validation resolves against. Validation must refuse everything the
#: run path would refuse except the consent verdict — which is a property of the cohort, not of
#: the file — so a synthetic cohort resolves the whole configuration without answering a
#: consent question no edit can change. Never surfaced anywhere.
_VALIDATION_COHORT = CohortRef("configuration-check", "synthetic")


# --- the result types ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EditOutcome:
    """One edit as it landed: the setting, its previous value as the file spelled it (empty when
    the file did not carry it), and its new value. Model settings render in the same
    `provider|build_id[|quantization]` form the edit accepted."""

    setting: str
    before: str
    after: str


@dataclass(frozen=True)
class UpdateResult:
    """What `update_profile_edits` did: the file written, the profile the edits targeted, and
    one outcome per named edit. `detail` is the sentence the console shows the teacher."""

    path: str
    profile: str | None
    edits: tuple[EditOutcome, ...]
    detail: str


# --- the edit plan -------------------------------------------------------------------------------

#: The model settings whose file spelling is a model table: id → (role, the table's name).
#: The panel edit rewrites every member to the named build and preserves the member count — a
#: panel of one, three or five stays that panel (`CT-CONF-02`) — which is why the panel is one
#: setting and not one per judge.
_MODEL_SETTINGS: Mapping[str, tuple[str, str]] = {
    "grading_model": ("judge", "panel"),
    "page_reader_model": ("transcriber", "transcriber"),
}

#: The decision engine's build is a model edit whose file spelling is three flat keys: the
#: provider binding (`FR-CONF-27`: `openjev-small` is opt-in by naming its provider), the
#: build, and the quantization a weights build requires — written when the new ref carries
#: one, removed when it does not.
_DECISION_MODEL_KEYS: tuple[str, ...] = (
    "HARNESS_DECISION_PROVIDER", "HARNESS_JEV_BUILD", "HARNESS_JEV_QUANTIZATION")

#: The scalar settings: id → (the file key, the kind). `decimal` and `int` values are spelled
#: as bare TOML numbers and their domains are the loader's own checks; `str` values are spelled
#: quoted, and their validity (engine choice, build form) the loader refuses, not this module.
#: `money` parses like a decimal but is spelled quoted: a bare TOML `7.5` reaches the loader as
#: a Python float, and `_resolve_cost` refuses a float ceiling — a spend ceiling is money
#: (`FR-CONF-07`), so the file spelling must survive the parse as a decimal-typed value.
#: `qa_assistant_model` is deliberately not here: its file key takes the bare OpenRouter build
#: string (`resolve_qa_model` hard-wires the provider), while the guided form names the whole
#: `provider|build_id` reference the projection shows — so the edit is parsed as a model
#: reference and only the build is spelled into the file (`_ops_for`).
_SCALAR_SETTINGS: Mapping[str, tuple[str, str]] = {
    "decision_engine": ("HARNESS_DECISION_ENGINE", "str"),
    "decision_confidence_gate": ("decision_confidence_threshold", "decimal"),
    "decision_citation_gate": ("HARNESS_JEV_CITE_THRESHOLD", "decimal"),
    "decision_citation_question_limit": ("HARNESS_JEV_MAX_CITATION_QUESTIONS", "int"),
    "decision_token_bytes_ratio": ("HARNESS_JEV_TOKEN_BYTES_RATIO", "int"),
    "cost_ceiling": ("HARNESS_COST_CEILING", "money"),
}

#: Name fragments of an edit id that say "credential": such an id is refused by name, because
#: "not a guided setting" alone would invite the caller to retry it another way.
_SECRET_NAME_PATTERN = re.compile(r"(?:api_key|password|credential|secret)", re.IGNORECASE)


@dataclass(frozen=True)
class _Plan:
    """One validated edit: the setting, the value as it is shown back (`after`) and as the file
    will spell it (`spelling`), and for the model edits the `ModelRef` the tables are rewritten
    to."""

    setting: str
    after: str
    spelling: str = ""
    model: ModelRef | None = None
    scalar_key: str | None = None
    scalar_kind: str | None = None
    scalar_value: Any = None


def _parse_ref(value: Any, setting: str) -> ModelRef:
    """The `provider|build_id[|quantization]` reference the guided form sends, as `ModelRef`.

    The same convention `pipeline/runtime._parse_pin` documents for
    `HARNESS_EXTRACT_SECOND_FAMILY_MODEL`: split on `|` and nothing else, because a build id
    may itself contain `:` and `@` (weights paths and digest pins do). A value with one or more
    than three parts — or an empty field, like a trailing `|` — is refused, naming the setting
    and not echoing the value (`NFR-CONF-02`: a build id can carry a credential in a query
    string). `M-CONF` is a leaf by design and does not import `M-PIPE` to share the parser;
    the convention lives in both places, as `ESCALATION_JUDGES_KEY` already does.
    """
    if not isinstance(value, str):
        raise ConfigurationError(
            f"{setting} must be a model reference of the form 'provider|build_id[|quantization]', "
            f"got {type(value).__name__}."
        )
    parts = value.split("|")
    if len(parts) not in (2, 3) or any(not part.strip() for part in parts):
        raise ConfigurationError(
            f"{setting} must be 'provider|build_id[|quantization]' with no empty field; "
            f"the value is not echoed here (NFR-CONF-02)."
        )
    if setting == "qa_assistant_model":
        # The assistant's file key is a bare OpenRouter build string (`resolve_qa_model`
        # hard-wires the provider and builds its ref with no quantization), so the guided
        # form is `openrouter|build_id` and nothing else: another provider names a model
        # no call would use, and a quantization field has no file key to land in.
        if parts[0].strip() != QA_MODEL_PROVIDER or len(parts) == 3:
            raise ConfigurationError(
                f"{setting} must be '{QA_MODEL_PROVIDER}|build_id' — the assistant runs on "
                f"{QA_MODEL_PROVIDER}, and it takes no quantization."
            )
        return ModelRef(role=QA_MODEL_ROLE, provider=QA_MODEL_PROVIDER,
                        build_id=parts[1].strip(), quantization=None)
    role = "decision" if setting == "decision_engine_model" else _MODEL_SETTINGS[setting][0]
    return ModelRef(
        role=role,  # type: ignore[arg-type]
        provider=parts[0].strip(),
        build_id=parts[1].strip(),
        quantization=parts[2].strip() if len(parts) == 3 else None,
    )


def _parse_scalar(value: Any, setting: str, kind: str) -> tuple[Any, str, str]:
    """The value for a scalar setting as `(python value, file spelling, shown value)`.

    Decimals and integers are pre-parsed so a value the TOML writer could not spell
    (`"yesterday"`) is refused naming the setting, rather than surfacing later as a broken
    file; the loader's own domain checks (ranges, engine choice, build form) run on the edited
    document and carry their own messages. A boolean is refused: `True` is an `int` in Python,
    but no guided setting is a switch.
    """
    if isinstance(value, bool):
        raise ConfigurationError(f"{setting} must be a number or a string, got a boolean.")
    if kind == "int":
        try:
            parsed: Any = int(str(value).strip())
        except (ValueError, TypeError):
            raise ConfigurationError(
                f"{setting} must be a whole number, got {type(value).__name__}.") from None
        return parsed, str(parsed), str(parsed)
    if kind in ("decimal", "money"):
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, TypeError):
            raise ConfigurationError(
                f"{setting} must be a decimal number, got {type(value).__name__}.") from None
        if not number.is_finite():
            raise ConfigurationError(f"{setting} must be a finite decimal number.")
        text = format(number.normalize(), "f")
        # The value handed to the loader is the canonical text — a `str`, which every decimal
        # reader accepts and a float never would for the ceiling.
        spelling = text if kind == "decimal" else _toml_string(text)
        return text, spelling, text
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(
            f"{setting} must be a non-empty string, got {type(value).__name__}.")
    return value.strip(), _toml_string(value.strip()), value.strip()


def _toml_string(value: str) -> str:
    """The value as a TOML basic string: the two escapes a build id or currency can carry."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _plan_edits(edits: Mapping[str, Any]) -> tuple[_Plan, ...]:
    """Validate every edit id and value before anything is read or written. An id outside
    `EDITABLE_SETTINGS` is refused — a credential-named one with that named, so the caller is
    told the rule rather than left guessing — and all the bad ids are reported at once, so a
    form with three mistakes does not take three round trips to learn them."""
    bad: list[str] = []
    for name in edits:
        if not isinstance(name, str) or name not in EDITABLE_SETTINGS:
            reason = (
                "it names a credential or secret, and secrets are never writable through this "
                "surface"
                if isinstance(name, str) and _SECRET_NAME_PATTERN.search(name)
                else "it is not one of the settings the guided form can change (the editable "
                     f"subset is {', '.join(EDITABLE_SETTINGS)})"
            )
            bad.append(f"{name!r}: {reason}")
    if bad:
        raise ConfigurationError(
            "the update was refused and nothing was written: " + "; ".join(bad))

    plans: list[_Plan] = []
    for setting, value in edits.items():
        if setting in _MODEL_SETTINGS or setting in ("decision_engine_model",
                                                     "qa_assistant_model"):
            ref = _parse_ref(value, setting)
            if setting == "qa_assistant_model":
                # The file spells the bare build; what is shown back is the whole reference
                # the projection renders, so the outcome row and `/settings` agree.
                plans.append(_Plan(setting=setting, after=_ref_text(ref),
                                   spelling=_toml_string(ref.build_id),
                                   model=ref, scalar_key=QA_MODEL_KEY, scalar_kind="str",
                                   scalar_value=ref.build_id))
                continue
            plans.append(_Plan(setting=setting, after=value, spelling=value, model=ref))
            continue
        key, kind = _SCALAR_SETTINGS[setting]
        parsed, spelling, shown = _parse_scalar(value, setting, kind)
        plans.append(_Plan(setting=setting, after=shown, spelling=spelling,
                           scalar_key=key, scalar_kind=kind, scalar_value=parsed))
    return tuple(plans)


# --- the TOML splice -----------------------------------------------------------------------------

#: One `key = value` line at a table's top level. A deeper dotted key (`a.b = 1`) does not
#: match (the key group rejects dots), so a dotted key is never edited in place — the edit
#: inserts a fresh plain key instead, which shadows nothing and is what the loader reads.
_KEY_LINE = re.compile(
    r"\A(?P<prefix>\s*(?:\"(?P<qk>[^\"]*)\"|'(?P<lqk>[^']*)'|(?P<bk>[A-Za-z0-9_-]+))\s*=\s*)"
    r"(?P<value>.+)\Z")


def _split_header(line: str) -> tuple[str, str] | None:
    """The header line as `(kind, inner)`: `("table", "profiles.dev-ci")` or
    `("array", "profiles.dev-ci.panel")`, or None when the line is not a table header."""
    stripped = line.strip()
    if stripped.startswith("[["):
        end = stripped.find("]]")
        return ("array", stripped[2:end].strip()) if end != -1 else None
    if stripped.startswith("["):
        end = stripped.find("]")
        return ("table", stripped[1:end].strip()) if end != -1 else None
    return None


def _header_parts(inner: str) -> tuple[str, ...]:
    """The header's dotted key as its parts, unquoted — so `[profiles."dev-ci"]` and
    `[profiles.dev-ci]` target the same section."""
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for char in inner:
        if quote is not None:
            if escaped:
                current.append(char)
                escaped = False
            elif char == "\\" and quote == '"':
                current.append(char)
                escaped = True
            elif char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in "\"'":
            quote = char
            continue
        if char == ".":
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return tuple(parts)


def _split_value(value: str) -> tuple[str, str]:
    """A scalar line's value as `(value_text, comment_text_with_leading_gap)`, so a replaced
    value keeps the inline comment that explains it. A quoted value runs to its closing quote
    (backslash escapes honoured in basic strings); a bare value's comment starts at the first
    `#` preceded by whitespace."""
    if value[:1] in ("\"", "'"):
        quote = value[0]
        index = 1
        while index < len(value):
            char = value[index]
            if quote == '"' and char == "\\":
                index += 2
                continue
            if char == quote:
                return value[:index + 1], value[index + 1:]
            index += 1
        return value, ""  # unterminated: left untouched, the round-trip refuses it
    for position, char in enumerate(value):
        if char == "#" and (position == 0 or value[position - 1] in " \t"):
            # The comment keeps the gap that separated it from the value, so `5  # nightly`
            # stays two spaces wide after the value is replaced.
            start = position
            while start > 0 and value[start - 1] in " \t":
                start -= 1
            return value[:start], value[start:]
    return value, ""


def _split_line_ending(line: str) -> tuple[str, str]:
    for ending in ("\r\n", "\n", "\r"):
        if line.endswith(ending):
            return line[: -len(ending)], ending
    return line, ""


def _split_lines(text: str) -> list[str]:
    """The text split on TOML's three line endings only, endings kept — `str.splitlines` also
    splits on the control characters TOML refuses, which would mangle a line tomllib would
    have refused anyway."""
    lines: list[str] = []
    start = 0
    index = 0
    size = len(text)
    while index < size:
        char = text[index]
        if char == "\r" and index + 1 < size and text[index + 1] == "\n":
            lines.append(text[start:index + 2])
            start = index = index + 2
            continue
        if char in "\r\n":
            lines.append(text[start:index + 1])
            index += 1
            start = index
            continue
        index += 1
    if start < size:
        lines.append(text[start:])
    return lines


@dataclass(frozen=True)
class _Block:
    """One contiguous region of the file: the preamble (lines before the first header) or one
    table/array-of-tables block from its header line to just before the next."""

    start: int
    end: int                     # exclusive, in line indices
    header: str | None           # the header's inner text; None for the preamble
    kind: str                    # "preamble", "table" or "array"


def _blocks(lines: list[str]) -> tuple[_Block, ...]:
    starts: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        header = _split_header(line)
        if header is not None:
            starts.append((index, header[0], header[1]))
    if not starts:
        return (_Block(0, len(lines), None, "preamble"),)
    blocks: list[_Block] = [_Block(0, starts[0][0], None, "preamble")]
    for position, (index, kind, inner) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        blocks.append(_Block(index, end, inner, kind))
    return tuple(blocks)


def _ops_for(plan: _Plan) -> tuple[tuple[str, str] | None, dict[str, Any]]:
    """The edit's (block selector, key operations): the selector names the kind of block the
    operations apply to — `None` for the scalar block (the profile's section, or a flat file's
    preamble), or `(kind, table name)` for a model table. The operations are file key →
    `("set", spelling)` or `("remove", None)`, in a fixed order per setting."""
    if plan.model is not None:
        ref = plan.model
        quantization = (("set", _toml_string(ref.quantization)) if ref.quantization
                        else ("remove", None))
        if plan.setting == "decision_engine_model":
            return None, {
                "HARNESS_DECISION_PROVIDER": ("set", _toml_string(ref.provider)),
                "HARNESS_JEV_BUILD": ("set", _toml_string(ref.build_id)),
                "HARNESS_JEV_QUANTIZATION": quantization,
            }
        if plan.setting == "qa_assistant_model":
            # The bare build string: `resolve_qa_model` hard-wires the provider, so spelling
            # the whole reference would grow a prefix on every round-trip.
            return None, {QA_MODEL_KEY: ("set", plan.spelling)}
        _, table = _MODEL_SETTINGS[plan.setting]
        return ("array" if table == "panel" else "table", table), {
            "provider": ("set", _toml_string(ref.provider)),
            "build_id": ("set", _toml_string(ref.build_id)),
            "quantization": quantization,
        }
    return None, {plan.scalar_key: ("set", plan.spelling)}  # type: ignore[dict-item]


def _target_blocks(blocks: tuple[_Block, ...], selector: tuple[str, str] | None,
                   has_sections: bool, profile: str | None, setting: str) -> tuple[_Block, ...]:
    """The blocks one setting's operations apply to. Inside a `profiles` table the scope is the
    named profile's section and its sub-tables; a flat file edits its top-level keys. A model
    table the file does not spell as its own table is a refusal, not a guess: the splice would
    otherwise have to invent structure, and inventing structure is how a config file gets
    corrupted."""
    prefix: tuple[str, ...] = ("profiles", profile) if has_sections else ()
    if selector is None:
        matches = [block for block in blocks
                   if (block.kind == "preamble" and not prefix)
                   or (block.kind == "table" and _header_parts(block.header or "") == prefix)]
        if matches:
            return (matches[0],)
        raise ConfigurationError(
            f"the config file has no section for profile {profile!r} to edit; "
            "edit the file directly."
        )
    kind, name = selector
    wanted = prefix + (name,)
    matches = [block for block in blocks
               if block.kind == kind and _header_parts(block.header or "") == wanted]
    if not matches:
        raise ConfigurationError(
            f"the config file does not spell the {name} as its own table"
            + (f" for profile {profile!r}" if profile else "")
            + "; edit the file directly."
        )
    return tuple(matches)


def _rewrite_block(block_lines: list[str], ops: Mapping[str, Any], newline: str) -> list[str]:
    """One block's lines with the operations applied: matching keys replaced in place (the
    inline comment kept with its original gap), removals dropped, and keys the block lacks
    appended at the end of its content — before trailing blank lines — in the operations'
    order. The result is deterministic: the same file and the same edits give the same bytes."""
    out: list[str] = []
    seen: set[str] = set()
    for line in block_lines:
        body, ending = _split_line_ending(line)
        match = _KEY_LINE.match(body)
        if match is not None:
            key = next(group for group in (match.group("qk"), match.group("lqk"),
                                           match.group("bk")) if group is not None)
            if key in ops:
                seen.add(key)
                action, spelling = ops[key]
                if action == "remove":
                    continue
                _, comment = _split_value(match.group("value"))
                out.append(f"{match.group('prefix')}{spelling}{comment}{ending}")
                continue
        out.append(line)
    for name, (action, spelling) in ops.items():
        if name in seen or action == "remove":
            continue
        position = len(out)
        while position > 0 and not out[position - 1].strip():
            position -= 1
        if position > 0 and not out[position - 1].endswith(("\r\n", "\n", "\r")):
            # The file's last line carries no line ending: give it one before inserting,
            # or the two lines would concatenate into one broken key.
            out[position - 1] = out[position - 1] + newline
        out.insert(position, f"{name} = {spelling}{newline}")
    return out


def _refuse_multiline(text: str) -> None:
    """A file that carries a triple-quoted multi-line string is beyond the splice's
    confidence: a key-shaped line inside such a string would be edited like code, and a
    header-shaped one would split the block structure, while the line-wise scan cannot tell
    string body from code — escapes included, since a backslash-escaped terminator reads as a
    close to any line scan. Rather than guess, refuse: the file stays byte-identical and the
    teacher edits it directly. A configuration file that needs multi-line values is outside
    the guided form's reach by design."""
    if '"""' in text or "'''" in text:
        raise ConfigurationError(
            "the config file carries a multi-line string; the guided edit cannot apply to it "
            "confidently; edit the file directly."
        )


def _apply_toml(text: str, plans: tuple[_Plan, ...], has_sections: bool,
                profile: str | None) -> str:
    """The spliced text: every line outside the edited keys byte-identical, each edit applied
    to its target block, blocks rebuilt bottom-up so the line indices stay valid."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = _split_lines(text)
    blocks = _blocks(lines)
    merged: dict[tuple[str, str] | None, dict[str, Any]] = {}
    for plan in plans:
        selector, ops = _ops_for(plan)
        merged.setdefault(selector, {}).update(ops)  # type: ignore[arg-type]
    replacements: list[tuple[int, int, list[str]]] = []
    for selector, ops in merged.items():
        setting = next(plan.setting for plan in plans if _ops_for(plan)[0] == selector)
        for block in _target_blocks(blocks, selector, has_sections, profile, setting):
            rebuilt = _rewrite_block(lines[block.start:block.end], ops, newline)
            replacements.append((block.start, block.end, rebuilt))
    new_lines = list(lines)
    for start, end, rebuilt in sorted(replacements, key=lambda item: item[0], reverse=True):
        new_lines[start:end] = rebuilt
    return "".join(new_lines)


# --- the JSON path -------------------------------------------------------------------------------

def _to_plain(value: Any) -> Any:
    """The parsed document as plain JSON data: `ModelRef`s back to tables, tuples to lists. A
    model table's absent quantization stays absent — `_ref_to_dict` spells it `null`, which
    would add a key the file never carried."""
    if isinstance(value, ModelRef):
        table = _ref_to_dict(value)
        if table.get("quantization") is None:
            table.pop("quantization", None)
        return table
    if isinstance(value, tuple):
        return [_to_plain(entry) for entry in value]
    if isinstance(value, Mapping):
        return {name: _to_plain(entry) for name, entry in value.items()}
    return value


def _no_table(setting: str, profile: str | None) -> ConfigurationError:
    name = "panel" if setting == "grading_model" else _MODEL_SETTINGS.get(setting, ("", setting))[1]
    return ConfigurationError(
        f"the config file does not spell the {name} as a table"
        + (f" for profile {profile!r}" if profile else "")
        + "; edit the file directly."
    )


def _apply_json(doc: Mapping[str, Any], plans: tuple[_Plan, ...], has_sections: bool,
                profile: str | None) -> str:
    plain = _to_plain(doc)
    scope = plain["profiles"][profile] if has_sections else plain
    for plan in plans:
        if plan.model is not None:
            ref = plan.model
            if plan.setting == "decision_engine_model":
                scope[_DECISION_MODEL_KEYS[0]] = ref.provider
                scope[_DECISION_MODEL_KEYS[1]] = ref.build_id
                if ref.quantization:
                    scope[_DECISION_MODEL_KEYS[2]] = ref.quantization
                else:
                    scope.pop(_DECISION_MODEL_KEYS[2], None)
                continue
            if plan.setting == "qa_assistant_model":
                # The bare build string: `resolve_qa_model` hard-wires the provider.
                scope[QA_MODEL_KEY] = ref.build_id
                continue
            _, table = _MODEL_SETTINGS[plan.setting]
            if plan.setting == "page_reader_model":
                # The transcriber is one table, not an array: rewrite it in place, keeping
                # whatever else the file's table carried (the same rule the TOML splice
                # follows — exactly the edited keys and nothing else).
                current = scope.get(table)
                if not isinstance(current, Mapping):
                    raise _no_table(plan.setting, profile)
                entry = dict(current)
                entry["provider"] = ref.provider
                entry["build_id"] = ref.build_id
                if ref.quantization:
                    entry["quantization"] = ref.quantization
                else:
                    entry.pop("quantization", None)
                scope[table] = entry
                continue
            entries = scope.get(table)
            if not isinstance(entries, list) or not entries:
                raise _no_table(plan.setting, profile)
            for entry in entries:
                entry["provider"] = ref.provider
                entry["build_id"] = ref.build_id
                if ref.quantization:
                    entry["quantization"] = ref.quantization
                else:
                    entry.pop("quantization", None)
            continue
        scope[plan.scalar_key] = plan.scalar_value  # type: ignore[index]
    return json.dumps(plain, indent=2, sort_keys=True) + "\n"


# --- current values, validation, the atomic write --------------------------------------------------

def _scope_of(doc: Mapping[str, Any], has_sections: bool, profile: str | None) -> Mapping[str, Any]:
    return doc["profiles"][profile] if has_sections else doc  # type: ignore[index]


def _current_text(doc: Mapping[str, Any], has_sections: bool, profile: str | None,
                  plan: _Plan) -> str:
    """The value the file carries today, as the projection renders it — empty when it does not
    carry one. Read from the parsed document, so it is the file's own value, not an
    environment-overridden one."""
    scope = _scope_of(doc, has_sections, profile)
    if plan.model is not None:
        if plan.setting == "decision_engine_model":
            raw_model = scope.get("decision_model")
            if isinstance(raw_model, (ModelRef, Mapping)):
                return _ref_text(_ref_of(raw_model, "decision_model"))
            build = scope.get("HARNESS_JEV_BUILD")
            if build is None or (isinstance(build, str) and not build.strip()):
                return ""
            backend = profile if has_sections else doc.get("HARNESS_PROFILE")
            provider = (scope.get("HARNESS_DECISION_PROVIDER")
                        or (DECISION_PROVIDERS_BY_PROFILE[backend][0]
                            if backend in DECISION_PROVIDERS_BY_PROFILE else ""))
            if not provider:
                return str(build)
            return _ref_text(ModelRef(role="decision", provider=provider,
                                      build_id=str(build).strip(),
                                      quantization=scope.get("HARNESS_JEV_QUANTIZATION") or None))
        if plan.setting == "qa_assistant_model":
            # The file spells the bare build; the outcome row shows the reference the
            # projection renders, so what was shown is what was edited.
            build = scope.get(QA_MODEL_KEY)
            if build is None or (isinstance(build, str) and not build.strip()):
                return ""
            return _ref_text(ModelRef(role=QA_MODEL_ROLE, provider=QA_MODEL_PROVIDER,
                                      build_id=str(build).strip(), quantization=None))
        _, table = _MODEL_SETTINGS[plan.setting]
        entries = scope.get(table)
        if not entries:
            return ""
        first = entries[0] if isinstance(entries, (list, tuple)) else entries
        return _ref_text(_ref_of(first, table))
    raw = scope.get(plan.scalar_key)  # type: ignore[arg-type]
    if raw is None:
        return ""
    return str(raw)


def _validation_config(doc: Mapping[str, Any], profile: str | None,
                       has_sections: bool) -> Mapping[str, Any]:
    """The mapping `resolve_run_config` validates the edited document under: the named
    profile's section of a multi-profile file; a flat file as itself, with the caller's profile
    supplying `HARNESS_PROFILE` for validation only when the file relies on the environment to
    name it."""
    if has_sections:
        return select_profile_config(doc, profile)  # type: ignore[arg-type]
    cfg = dict(doc)
    if cfg.get("HARNESS_PROFILE") is None:
        if profile is None:
            raise ConfigurationError(
                "the config file does not name a profile (HARNESS_PROFILE); name the profile "
                "the edit targets."
            )
        cfg["HARNESS_PROFILE"] = profile
    return cfg


def _write_atomic(path: str, text: str) -> None:
    """Write the text so a reader sees either the old file or the new one, never a mixture: a
    temporary file in the same directory (same volume, so the rename is atomic), then one
    `os.replace` — the commit point. A failure anywhere before or at the replace unlinks the
    temp file and leaves the original untouched. The temporary file is created exclusively
    (`O_EXCL`, owner-only permissions) under a name derived from the target and this process,
    so two concurrent updates cannot share one temp file and a reader never opens the
    half-written one.

    The machinery is hand-rolled from `os` primitives rather than `tempfile`, and the path is
    handled with `os.path` rather than `pathlib`: TC-CONF-13 refuses this module any file
    capability by import, so the write stays spelled directly on the interface it uses."""
    payload = text.encode("utf-8")
    directory, name = os.path.split(path)
    stem = os.path.join(directory, f".{name}.aeh-tmp-{os.getpid()}")
    temp: str | None = None
    handle: Any = None
    try:
        for attempt in range(10000):
            candidate = stem if attempt == 0 else f"{stem}-{attempt}"
            try:
                descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                continue
            try:
                handle = os.fdopen(descriptor, "wb")
            except BaseException:
                os.close(descriptor)
                raise
            temp = candidate
            break
        if handle is None or temp is None:
            raise ConfigurationError(f"no temporary file could be created beside {path}.")
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temp, path)
        temp = None
    finally:
        if handle is not None:
            with contextlib.suppress(OSError):
                handle.close()
        if temp is not None:
            with contextlib.suppress(OSError):
                os.remove(temp)


def update_profile_edits(
    profile_path: str | os.PathLike[str],
    edits: Mapping[str, Any],
    *,
    profile: str | None = None,
) -> UpdateResult:
    """Apply the teacher-editable `edits` to the configuration file at `profile_path`.

    `edits` maps `projection.EDITABLE_SETTINGS` ids to values: model settings take the
    `provider|build_id[|quantization]` reference, the engine choice takes `"jev"` or `"off"`,
    and the scalar settings take numbers or strings. `profile` names the profile section a
    multi-profile file edits (required there — one file serves every profile, so an unnamed
    edit would not say which section it means); a flat file edits its own keys, and if it
    relies on the environment to name its profile, the caller's `profile` is used to validate
    the result but never written into the file.

    Every edit is validated twice: here, against the projection's allow-list, and then — after
    the splice — by the loader itself (`parse_config_document` and `resolve_run_config`), so a
    refusal carries the loader's own message and the file stays byte-identical. Only a fully
    validated document is written, and it is written atomically. Returns one `EditOutcome` per
    named edit.
    """
    path = os.fspath(profile_path)
    if not isinstance(edits, Mapping) or isinstance(edits, (str, bytes)) or not edits:
        raise ConfigurationError("edits must be a non-empty mapping of setting ids to values.")
    if not os.path.isfile(path):
        raise ConfigurationError(f"no configuration file at {path}.")
    fmt = "json" if os.path.splitext(path)[1].lower() == ".json" else "toml"
    with open(path, "rb") as handle:
        text = handle.read().decode("utf-8")
    doc = parse_config_document(text, fmt)
    plans = _plan_edits(edits)

    sections = doc.get("profiles")
    has_sections = isinstance(sections, Mapping) and len(sections) > 0
    if has_sections:
        if profile is None:
            present = ", ".join(repr(name) for name in sorted(sections)) or "none"  # type: ignore[union-attr]
            raise ConfigurationError(
                "profile is required to edit a multi-profile configuration file; "
                f"sections present: {present}."
            )
        # Up front, so the loader's own section refusals (no such section; a section naming
        # another profile) fire before anything is spliced.
        select_profile_config(doc, profile)
    else:
        own = doc.get("HARNESS_PROFILE")
        if own is not None and profile is not None and own != profile:
            raise ConfigurationError(
                f"the config file configures HARNESS_PROFILE {own!r}, not {profile!r}.")

    if fmt == "json":
        new_text = _apply_json(doc, plans, has_sections, profile)
    else:
        _refuse_multiline(text)
        new_text = _apply_toml(text, plans, has_sections, profile)

    new_doc = parse_config_document(new_text, fmt)
    resolve_run_config(_validation_config(new_doc, profile, has_sections), _VALIDATION_COHORT)

    _write_atomic(path, new_text)

    outcomes = tuple(
        EditOutcome(setting=plan.setting,
                    before=_current_text(doc, has_sections, profile, plan),
                    after=plan.after)
        for plan in plans
    )
    names = ", ".join(outcome.setting for outcome in outcomes)
    return UpdateResult(
        path=path,
        profile=profile if has_sections else (profile or doc.get("HARNESS_PROFILE")),
        edits=outcomes,
        detail=(f"{len(outcomes)} setting(s) updated in {path}: {names}. New grading runs use "
                "them; runs already graded keep the configuration they were frozen with."),
    )
