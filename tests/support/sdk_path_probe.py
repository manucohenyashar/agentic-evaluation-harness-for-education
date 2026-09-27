"""Exit 0 once #498 routes `JevOpenRouterProvider` through the TypeSafe SDK, 1 while not.

The `command` blocker for TS-124/125's written-ahead arms (`tests/support/impl.py`). The SDK
stamps every request with `X-TypeSafe-SDK: typesafe-sdk/<version>`, so the probe sends one
decision through the provider's public surface onto a capturing transport and asks whether
that header, and the SDK's `/api/v1/systemone` URL, reached it. Any exception reads as "not
landed", which keeps the arms marked rather than letting a red case into TEST_CMD.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


def landed() -> bool:
    from aeh.conf import ModelRef
    from aeh.prov import DecisionRequest, HttpResponse, JevOpenRouterProvider, NoulQuestion

    body = {"model": "typesafe/jev-1.13", "usage": {"input_tokens": 1, "output_tokens": 0},
            "answers": {"ok": {"type": "noul", "noul": 0.9}}}
    seen = []

    class Capture:
        def send(self, request):  # noqa: ANN001
            seen.append(request)
            return HttpResponse(200, {}, json.dumps(body).encode("utf-8"))

    ref = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-01", quantization=None)
    JevOpenRouterProvider(api_key="k", transport=Capture()).decide(
        DecisionRequest(state="s", questions=(NoulQuestion("ok", "x"),)), ref)
    if len(seen) != 1:
        return False
    headers = {str(k).lower(): str(v) for k, v in dict(seen[0].headers).items()}
    return (headers.get("x-typesafe-sdk", "").startswith("typesafe-sdk/")
            and seen[0].url.endswith("/api/v1/systemone"))


if __name__ == "__main__":
    try:
        ok = landed()
    except Exception:  # noqa: BLE001 - any failure reads as "not landed"
        ok = False
    sys.exit(0 if ok else 1)
