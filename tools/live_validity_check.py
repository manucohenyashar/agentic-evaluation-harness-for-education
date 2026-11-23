#!/usr/bin/env python3
"""The live validity check (FR-CONFORM-20): ENG7 and PS9 through a profile and the console.

    python tools/live_validity_check.py --profile smoke|panel [--data-dir DIR]

Builds both sample tests, reads in their synthetic answer sheets, grades them on the named
profile through the console's `start run`, marks the blind sample from the sample author's
intended bands through the console's API, and prints: cells scored per sheet, the
verification-refusal rate, the cited share, the confidence distribution, the labels, the
administration record, the routing verdict and the purge outcome.

It sends only the synthetic sample materials (R31) and refuses a class that is not `synthetic`.
Its "teacher" bands are the sample author's intended bands, not a teacher's marks. With
`HARNESS_FIXTURE_DIR` set the pipeline uses the recorded provider and nothing leaves the machine;
otherwise the profile's real models are called and the run costs money.

The logic lives in `aeh.conform.validity_check`; this file is the command, and the loopback HTTP
client it speaks to the console with (the console runs in this process, on 127.0.0.1).
"""

from __future__ import annotations

import http.client
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeh.conform.validity_check import main  # noqa: E402

#: The timeout for one console request (seconds). Env-gated: a slow box may need more.
HTTP_TIMEOUT_ENV = "HARNESS_LIVE_CHECK_HTTP_TIMEOUT_S"
HTTP_TIMEOUT_DEFAULT_S = 120.0


def _timeout() -> float:
    try:
        value = float(os.environ.get(HTTP_TIMEOUT_ENV, "") or HTTP_TIMEOUT_DEFAULT_S)
    except ValueError:
        return HTTP_TIMEOUT_DEFAULT_S
    return value if value > 0 else HTTP_TIMEOUT_DEFAULT_S


def loopback_request(port: int, method: str, path: str,
                     body: Mapping[str, Any] | None = None) -> tuple[int, Any]:
    """One request to the console on 127.0.0.1:`port`; the reply decoded as JSON, else text."""
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=_timeout())
    try:
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
    finally:
        connection.close()
    try:
        return response.status, json.loads(raw) if raw else None
    except ValueError:
        return response.status, raw.decode("utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main(console_request=loopback_request))
