"""The models the live-test configuration names, read from the file rather than hard-coded.

`docs/live-tests/config/live-test.dev-ci.toml` is an operator's file: the live-test README tells
the operator to change its models (any OpenRouter model with a zero-retention host is legitimate
on `dev-ci`; only the local profiles require weights that can run on the machine). Tests that
drive the CLI over that file with a stand-in OpenRouter must therefore expect whatever models it
names, or they fail the moment an operator edits it — as they did when `gpt-6-luna` replaced the
shipped `qwen` models.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def openrouter_slug(build_id: str) -> str:
    """The model name OpenRouter is sent for a pinned build: `openrouter/vendor/model@date` ->
    `vendor/model` (the same reduction the live provider applies to the wire)."""
    slug = build_id.removeprefix("openrouter/")
    return slug.split("@", 1)[0]


def configured_builds(config: Path, profile: str = "dev-ci") -> tuple[str, str]:
    """`(transcriber, first panel judge)` as the pinned build ids the config file names."""
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    section = data["profiles"][profile]
    return section["transcriber"]["build_id"], section["panel"][0]["build_id"]


def configured_models(config: Path, profile: str = "dev-ci") -> tuple[str, str]:
    """`(transcriber, first panel judge)` as OpenRouter model names, from the config file."""
    transcriber, judge = configured_builds(config, profile)
    return openrouter_slug(transcriber), openrouter_slug(judge)
