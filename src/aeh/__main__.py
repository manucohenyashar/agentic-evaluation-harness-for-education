"""`python -m aeh` — the same entry point the installed `aeh` command runs (`FR-STORE-15`).

Two spellings, one implementation: `[project.scripts] aeh = "aeh.pipeline:main"` gives an
installed console script, and this module gives the form that needs no `PATH` entry — useful
inside a venv, a container, or a `pipx run`. Both call `aeh.pipeline.main`, so neither can
drift from the other.

`aeh.pipeline` lands with the M-PIPE composition story; until then BOTH spellings fail with the
same `ImportError`, which is the honest state and the one the issue's technical note describes.
Catching it here to print something friendlier would make `python -m aeh` and the installed
`aeh` command behave differently — the drift this module exists to prevent — and a stub that
printed a version and exited 0 would report a pipeline that cannot run as installed and
working.
"""

from __future__ import annotations

import sys

if __name__ == "__main__":  # pragma: no cover — exercised as a subprocess
    # Imported HERE, not at module scope: `aeh.__main__` is imported (never run) by the
    # module-enumerating suites, and a top-level import of a module that does not exist yet
    # would fail those rather than this entry point. Running it still raises the same
    # `ImportError` the installed `aeh` command raises, which is the point.
    from aeh.pipeline import main

    raise SystemExit(main(sys.argv[1:]))
