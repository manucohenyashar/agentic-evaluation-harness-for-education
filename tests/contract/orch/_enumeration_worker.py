"""The child process for `TC-ORCH-C02` (`test_ct_orch_c02_two_process_enumeration.py`).

A separate module rather than a `-c` one-liner because the full migration chain must be
imported BEFORE the store opens (see `CLAUDE.md`'s "Store opens require the full migration
chain" — `IncompleteMigrationChainError` refuses a short chain at the open), and an
explicit import block is that requirement stated where it is met:

    import aeh.agg, aeh.det, aeh.extract, aeh.ingest, aeh.judge, aeh.orch, aeh.pkg, aeh.synth

Not test scaffolding beyond the harness: the child runs the shipped `Orchestrator` against
the shipped store — the same call a second dispatcher process would make. Its only job is
to re-enumerate one pinned run and print the report as JSON, so the parent test can
compare the two processes' enumerations byte for byte.
"""

from __future__ import annotations

import json
import sys

# The eight migration contributors, imported before the first store open in THIS process
# (aeh.agg owns Cohort's last migration, #92's agg_confidence_columns).
import aeh.agg  # noqa: F401,E402
import aeh.det  # noqa: F401,E402
import aeh.extract  # noqa: F401,E402
import aeh.ingest  # noqa: F401,E402
import aeh.judge  # noqa: F401,E402
import aeh.orch  # noqa: F401,E402
import aeh.pkg  # noqa: F401,E402
import aeh.synth  # noqa: F401,E402
from aeh.orch import Orchestrator
from aeh.store import open_store


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: _enumeration_worker.py <data_dir> <run_id>", file=sys.stderr)
        return 2
    data_dir, run_id = argv[1], argv[2]
    store = open_store(data_dir)
    try:
        report = Orchestrator(store).enumerate_units(run_id)
        print(
            json.dumps(
                {
                    "work_ids": sorted(report.work_ids),
                    "status": report.status,
                    "units_enumerated": report.units_enumerated,
                    "units_inserted": report.units_inserted,
                    "units_already_present": report.units_already_present,
                }
            )
        )
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
