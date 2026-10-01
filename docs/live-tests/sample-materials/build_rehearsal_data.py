#!/usr/bin/env python3
"""Build a practice data folder: a finished run over three demo students, for rehearsing the console.

    python docs/live-tests/sample-materials/build_rehearsal_data.py [folder]

The folder defaults to ~/aeh-rehearsal. Afterwards:

    python -m aeh console --data-dir ~/aeh-rehearsal

and open the address it prints (see docs/tutorials/operating-tutorial.md).

What you get: the repository's own small reference corpus (3 students, 3 rubric lines, one
multiple-choice) driven through the real pipeline from start to finish, with recorded model
answers, so every console screen has something to show. It makes no network call and spends no
money. It is a rehearsal of the SCREENS, not of the sample tests in this folder: the three demo
students are not the sample answer sheets.

For engineers: it needs a repository checkout (it imports `tests.support` and `harness`) and the
dev requirements (`pip install -r requirements-dev.txt`). The recorded replies in the repository's
corpus depend on the exact page-rendering library version, so this script records a fresh set on
your machine first (about a minute) and replays that, which always matches.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ  # noqa: E401,E402,F401
import aeh.judge, aeh.orch, aeh.pkg, aeh.review, aeh.synth  # noqa: E401,E402,F401

from tests.support import pipe_world  # noqa: E402


def main(argv: list[str]) -> int:
    target = Path(argv[0]).expanduser() if argv else Path.home() / "aeh-rehearsal"
    if target.exists() and any(target.iterdir()):
        print(f"{target} already holds files. Choose an empty or new folder (or delete it).")
        return 1
    scratch = Path(tempfile.mkdtemp(prefix=".aeh-rehearsal-", dir=Path.home()))
    try:
        recordings = scratch / "recordings"
        print("1/3 recording model replies for the demo corpus (about a minute) ...")
        count = pipe_world.capture(recordings)
        print(f"    {count} recordings")
        target.mkdir(parents=True, exist_ok=True)
        os.chmod(target, 0o700)
        print("2/3 building the package, cohort and submissions ...")
        world = pipe_world.replay_world(target, recordings=recordings)
        world.build_run()
        world.start_run()
        print("3/3 driving the run to completion ...")
        result = pipe_world.drive_composed(world)
        print(f"    run status: {result.status}")
        print(f"\nrun id ............ {world.run_id}")
        print(f"cohort id ......... {world.cohort_id}")
        print(f"package version ... {world.version}")
        print(f"\nstart the console:  python -m aeh console --data-dir {target}")
        world.store.close()
        return 0 if result.status == "complete" else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
