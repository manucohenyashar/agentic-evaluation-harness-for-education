"""Opening the store and choosing the provider a run's backend profile names."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping


def _open_store(data_dir: str) -> Any:
    """The store. The migration chain is already complete — this module imports all eleven
    contributors at module scope, which is what makes this entry point safe to open from."""
    from aeh.store import open_store

    return open_store(Path(data_dir))


def _provider_for(config: Mapping[str, Any]) -> Any:
    """The provider the run's backend profile names.

    **A declared resolution of a gap, not a shipped factory.** `FR-PIPE-08` says the command
    resolves its configuration and then drives the run, but nothing in the design says which
    provider object a profile maps to, and no factory exists anywhere in `src/aeh/` —
    `M-PROV` ships the three classes and leaves construction to the caller. So the mapping is
    made here, minimally and in the open:

    Reads the RESOLVED `RunConfig.backend_profile` rather than a raw configuration key: the
    profile that matters is the one `resolve_run_config` settled on after the environment won
    (`FR-CONF-14`), and a raw lookup finds nothing when the profile arrives through a
    profile section.

    * `dev-ci` -> `RecordedFixtureProvider` over `HARNESS_FIXTURE_DIR`. The profile's whole
      point is running with no network (`CT-PROV-10`), and this is the shipped transport for
      that.
    * `edge-local` -> `LocalServerProvider`.
    * `cloud-hosted` -> `OpenRouterProvider`.

    Both live providers are constructed with their own defaults; a deployment that needs
    different endpoints sets them through `M-PROV`'s own seams rather than through this
    function, which knows nothing about backends beyond the profile name.
    """
    from aeh.prov import LocalServerProvider, OpenRouterProvider, RecordedFixtureProvider

    profile = str(
        getattr(config, "backend_profile", None)
        or (config.get("backend_profile") if hasattr(config, "get") else None)
        or ""
    )
    if profile == "dev-ci":
        fixture_dir = os.environ.get("HARNESS_FIXTURE_DIR")
        if not fixture_dir:
            raise ValueError(
                "the dev-ci profile records and replays through a fixture directory; set "
                "HARNESS_FIXTURE_DIR so the provider has somewhere to read"
            )
        return RecordedFixtureProvider(fixture_dir=Path(str(fixture_dir)))
    if profile == "edge-local":
        return LocalServerProvider()
    if profile == "cloud-hosted":
        return OpenRouterProvider()
    raise ValueError(
        f"no backend profile is configured ({profile!r}); set HARNESS_BACKEND_PROFILE or "
        f"declare backend_profile in the config file. The declared profiles are "
        f"'edge-local', 'cloud-hosted' and 'dev-ci'."
    )


def _load_config_file(path: str | None) -> dict[str, Any]:
    """The `--config` file, parsed by `M-CONF`'s own reader.

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
