"""Capture the authoring recordings a console-redesign journey replays.

The authoring corpus (`fixtures/F-AUTHOR/recordings/`) holds the model replies a
complete authoring run asks for, captured once from a live run — "captured, not
generated" (`fixtures/F-AUTHOR/recordings/README.md`). The intake fixtures AF-14..21
had no recordings until their capture pass ran (the corpus README's own note); this
script is that capture pass for one fixture at a time, so the command a journey's
recordings came from is written down and repeatable.

What it does, per invocation:

1. Renders the capture config — the dev-ci profile pinned to the corpus's capture
   build for these fixtures (`tests.support.console_journeys.JOURNEY_AUTHORING_BUILD`),
   the same TOML the journey tests render, so the assembled requests
   — and therefore the `request_key` hashes — match what the tests replay.
2. Wraps the live provider (`OpenRouterProvider.enforcing_zero_retention()`, keyed by
   `OPENROUTER_API_KEY`) in a recording boundary: every reply the authoring chain asks
   for is recorded through `RecordedFixtureProvider.record()` — with the cost nulled,
   as `record()` requires (CT-PROV-03: a fixture's cost is null) — and then returned
   so the live run proceeds normally.
3. Drives the real `AuthoringService.draft` over the given documents into an output
   directory you name (scratch; the draft is not committed).

Nothing is fabricated: every recorded reply is what the live backend answered. The
capture is one-shot per fixture — re-running it over the same documents asks the same
requests, which now REPLAY from the recordings written by the first pass (the
recording boundary records only on a live answer; a replayed request never reaches the
live provider), so a second run is a replay check, not a second capture.

Usage (from the repository root):

    set OPENROUTER_API_KEY=...        (the key the live tier already uses)
    python scripts/capture_authoring_recordings.py \
        --docs fixtures/F-AUTHOR/AF-17/hist6-great-fire-01-prose-test.txt \
        --out %TEMP%\af17-capture

The recordings land in `fixtures/F-AUTHOR/recordings/` (the default fixture dir);
`--fixture-dir` redirects them for a dry run. Commit what the run wrote together with
the journey test that replays it.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.support import console_journeys as cj  # noqa: E402


def _config_toml(path: Path) -> None:
    """The journey tests' config, rendered from the same pinned build — one source
    of the identity the request keys hash. The build is the corpus's capture pin for
    AF-14..21; see `tests.support.console_journeys` for why it is not the older qwen
    pin."""
    cj.journey_config_toml(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docs", required=True, nargs="+", metavar="DOC",
                        help="the teacher documents to draft from (fixture paths)")
    parser.add_argument("--out", required=True, metavar="DIR",
                        help="scratch directory for the draft and report")
    parser.add_argument("--fixture-dir", default=str(REPO_ROOT / "fixtures" / "F-AUTHOR" / "recordings"),
                        help="where the recordings are written (default: the corpus)")
    args = parser.parse_args()

    import tomllib

    from aeh.author.service import authoring_service
    from aeh.prov import OpenRouterProvider, RecordedFixtureProvider

    capture_dir = Path(args.out)
    capture_dir.mkdir(parents=True, exist_ok=True)
    config_path = capture_dir / "capture.dev-ci.toml"
    _config_toml(config_path)
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))

    live = OpenRouterProvider.enforcing_zero_retention()
    recorded = RecordedFixtureProvider(fixture_dir=Path(args.fixture_dir))

    class RecordingLive:
        """The live backend with a recording boundary: reply, record, return."""

        def __init__(self) -> None:
            self.recorded = 0
            self.replayed = 0

        def complete(self, prompt, model_ref, params):
            completion = live.complete(prompt, model_ref, params)
            recorded.record(prompt, model_ref, params,
                            dataclasses.replace(completion, cost=None))
            self.recorded += 1
            return completion

        def __getattr__(self, name):
            return getattr(live, name)

    boundary = RecordingLive()
    service = authoring_service(cfg, "dev-ci", provider=boundary)
    result = service.draft([Path(doc) for doc in args.docs], capture_dir)
    print(f"captured {boundary.recorded} recording(s) under {args.fixture_dir}")
    print(f"draft: {result.draft_path}")
    print(f"report: {result.report_path}")
    print(f"unresolved placeholders: {result.unresolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
