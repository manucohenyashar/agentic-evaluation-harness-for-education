"""Agentic Evaluation Harness for Education — the implementation package.

Modules land here one per design §3 module, named by the module's short key: `aeh.conf`
(`M-CONF`), `aeh.prov` (`M-PROV`), `aeh.store` (`M-STORE`), and so on.

The package name is fixed in one place outside this file — `tests/support/impl.py`'s
`IMPLEMENTATION_PACKAGE` — so a rename is a one-line change there and a directory move here.
`pyproject.toml` puts `src` on `pythonpath` for pytest; the sibling `harness.*` package at the
repository root is the tooling package test-plan §4.7 reserves and is deliberately separate.
"""

__all__: list[str] = []
