"""Agentic Evaluation Harness for Education — the implementation package.

Each design §3 module is a package here, named by the module's short key: `aeh.conf`
(`M-CONF`), `aeh.prov` (`M-PROV`), `aeh.store` (`M-STORE`), and so on. A package's
`__init__.py` lists its files and re-exports its public names, so callers import from the
package (`from aeh.orch import Orchestrator`) rather than from a file inside it. The longer design
notes for each package are in `docs/code-notes/<package>.md`.

The package name is fixed in one place outside this file — `tests/support/impl.py`'s
`IMPLEMENTATION_PACKAGE` — so a rename is a one-line change there and a directory move here.
`pyproject.toml` puts `src` on `pythonpath` for pytest; the sibling `harness.*` package at the
repository root is the tooling package test-plan §4.7 reserves and is deliberately separate.
"""

__all__: list[str] = []
