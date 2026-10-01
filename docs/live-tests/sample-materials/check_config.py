#!/usr/bin/env python3
"""Check that a harness configuration file will be accepted, before you start anything.

    python docs/live-tests/sample-materials/check_config.py <config-file> [profile] [consent-class]

* profile, if you give one, is used as if you had set HARNESS_PROFILE in the terminal. If you
  give none, the checker does what a real run does: it takes HARNESS_PROFILE from the terminal,
  else from the config file's own top-level HARNESS_PROFILE line, else it refuses (there is no
  default profile).
* consent-class is the consent class of the cohort you intend to grade: synthetic, consented or
  real. It defaults to "synthetic". A real cohort is refused for dev-ci and cloud-hosted unless
  HARNESS_ALLOW_REMOTE_REAL_WORK and allow_remote_real_work_supplied_by are both given.

It uses the system's own configuration code, so what it accepts is exactly what a run will
accept. It reads your environment but never prints a secret: it only says whether
OPENROUTER_API_KEY is set. It sends nothing anywhere and writes nothing.

What it cannot tell you: whether the model names exist at OpenRouter, whether your key works, or
whether your account has credit. Those need a real call.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from aeh.conf import CohortRef, ConfigurationError, effective_config, parse_config_document  # noqa: E402
from aeh.conf import resolve_run_config  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    path = Path(argv[0])
    consent = argv[2] if len(argv) > 2 else "synthetic"
    if len(argv) > 1:
        os.environ["HARNESS_PROFILE"] = argv[1]
    source = ("the argument you gave" if len(argv) > 1 else
              "the terminal" if os.environ.get("HARNESS_PROFILE") else "the config file")
    try:
        raw = parse_config_document(path.read_text(encoding="utf-8"),
                                    "json" if path.suffix.lower() == ".json" else "toml")
        config = effective_config(raw)
        run_config = resolve_run_config(dict(config), CohortRef(cohort_id="check", consent_class=consent))
    except Exception as error:  # noqa: BLE001 - say what is wrong, in the system's own words
        print(f"NOT ACCEPTED  ({type(error).__name__})\n  {error}")
        return 1
    summary = run_config.profile_summary()
    print("ACCEPTED")
    print(f"  profile ............ {summary.backend_profile}   (from {source}; cohort consent class: {consent})")
    print(f"  page reader ........ {summary.transcriber.build_id}")
    for index, member in enumerate(summary.panel, start=1):
        print(f"  judge {index} ............ {member.build_id}")
    engine = summary.decision_engine
    print(f"  decision engine .... {'off' if engine is None else engine.build_id}")
    print(f"  cost ceiling ....... {run_config.cost_ceiling} {run_config.cost_currency}")
    print(f"  concurrency ........ {run_config.concurrency_ceiling} calls at a time")
    key_set = bool(os.environ.get("OPENROUTER_API_KEY"))
    print(f"  OPENROUTER_API_KEY . {'set' if key_set else 'NOT SET in this terminal'}")
    if summary.backend_profile in ("dev-ci", "cloud-hosted") and not key_set:
        print("\nWARNING: a run through OpenRouter needs OPENROUTER_API_KEY in the same terminal.")
    print("\nThis only proves the file is well formed. It did not contact OpenRouter.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
