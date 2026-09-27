"""Exit 0 once design 1.8's confidence rule (#497) has landed, 1 while it has not.

The `command` blocker for TS-123's written-ahead arms (`tests/support/impl.py`). No new name
marks the change, since 1.8 changes what shipped code does, not what it is called. So the probe
asks the behaviour itself, through the fixture double's public `decide`, the most stable surface
the rule is visible on:

- a Noul answered 0.05 carries confidence 0.05 (1.6: `|2p − 1|` = 0.90), and
- a Score recorded without `confidence` is refused under a Jev ref (1.6: derived 0.8667).

Both halves must hold. Any other exception means "not landed", so the probe errs toward keeping
the tests marked; the gate test fires the moment both halves hold.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


def landed() -> bool:
    from aeh.conf import ModelRef
    from aeh.prov import (DecisionRequest, MalformedResponseError, NoulQuestion, RecordedFixtureProvider,
                          ScoreQuestion)

    ref = ModelRef(role="decision", provider="fixture",
                   build_id="/models/jev-fixture/model.safetensors@sha256:" + "cd" * 32, quantization="bf16")
    usage = {"input_tokens": 1, "output_tokens": 0}
    with tempfile.TemporaryDirectory() as tmp:
        fixture = RecordedFixtureProvider(fixture_dir=Path(tmp))
        noul = DecisionRequest(state="s", questions=(NoulQuestion("ok", "x"),))
        fixture.record_decision(noul, ref, {"model": "m", "usage": usage,
                                            "answers": {"ok": {"type": "noul", "noul": 0.05}}})
        if abs(fixture.decide(noul, ref).answers["ok"].confidence - 0.05) > 1e-12:
            return False
        score = DecisionRequest(state="s", questions=(ScoreQuestion("band", "x", ("a", "b")),))
        answer = {"type": "score", "score": 0.1, "probabilities": {"0": 0.9, "1": 0.1},
                  "legend": {"0": "a", "1": "b"}}
        # Public surface only: a correct #497 may refuse the confidence-less Score when it is
        # recorded or when it is replayed, and either counts as landed.
        try:
            fixture.record_decision(score, ref, {"model": "m", "usage": usage, "answers": {"band": answer}})
            fixture.decide(score, ref)
        except MalformedResponseError:
            return True
        return False


if __name__ == "__main__":
    try:
        ok = landed()
    except Exception:  # noqa: BLE001 - any failure reads as "not landed"
        ok = False
    sys.exit(0 if ok else 1)
