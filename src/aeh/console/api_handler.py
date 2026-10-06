"""The request handling behind `/api/` and the same-origin SPA (FR-CONSOLE-45, CT-CONSOLE-30).

A mixin on the console's request handler, kept apart from `server.py` so the server-rendered
routes and the API's routes can each be read on their own. It owns no write: every API
mutation reaches the control surface through `ConsoleApp.perform`, looked up on the running
app at request time — the same door `POST /actions/<slug>` uses.
"""

from __future__ import annotations

import json
from typing import Any

from .api import (
    API_ROUTES,
    UPLOAD_CONTROL,
    allowed_methods,
    ApiRoute,
    bundle_file,
    content_type_for,
    controls_payload,
    match_route,
)
from .errors import ConsoleBindRefused
from .routes import SCREENS

JSON_TYPE = "application/json; charset=utf-8"
ASSETS_PREFIX = "/assets/"
#: The largest refused body read off the socket before closing it; anything bigger is left
#: unread rather than spending a read on a request already refused.
REFUSED_BODY_DRAIN_BYTES = 64 * 1024


def outcome_json(action: str, outcome: Any) -> bytes:
    """A control outcome as the JSON both transports answer with."""
    return json.dumps({
        "action": action,
        "dispatched": bool(getattr(outcome, "dispatched", False)),
        "refused": bool(getattr(outcome, "refused", False)),
        "detail": str(getattr(outcome, "detail", "")),
        "rows_written": len(getattr(outcome, "rows_written", ()) or ()),
    }).encode("utf-8")


#: The reads the API answers, by the name a read route carries. Each is a pure function of
#: the declared tables — no store is opened, so no read can create or touch a stored byte.
_READS = {
    "controls": controls_payload,
    "screens": lambda: {"screens": dict(SCREENS)},
}


class ApiRequestsMixin:
    """`/api/` routed from `API_ROUTES`, and the SPA bundle served from `spa_dir`."""

    # -- the SPA ----------------------------------------------------------------------------

    def _serve_spa_index(self) -> bool:
        """Serve the bundle's `index.html` at `/`, if the bundle is there."""
        index = bundle_file(self._console.spa_dir, "index.html")
        if index is None:
            return False
        self._respond(200, index.read_bytes(), content_type_for(index))
        return True

    def _serve_bundle_asset(self, route: str) -> bool:
        """Serve `/assets/<file>` from the bundle's `assets/` directory, if the file is there."""
        if not route.startswith(ASSETS_PREFIX):
            return False
        relative = "assets/" + route[len(ASSETS_PREFIX):]
        found = bundle_file(self._console.spa_dir, relative)
        if found is None:
            return False
        self._respond(200, found.read_bytes(), content_type_for(found))
        return True

    # -- the API ----------------------------------------------------------------------------

    def _serve_api(self, method: str, route: str) -> None:
        """Dispatch one `/api/` request through the route table, and nothing else."""
        matched, params, other_verb = match_route(method, route)
        if matched is None:
            # The connection is closed after the answer (see `_not_found`). A small declared
            # body is drained first: closing a Windows socket with unread bytes resets it, and
            # the client then never sees the 404/405 it was owed.
            self._drain_small_body()
            if other_verb:
                self._respond(405, b'{"error":"method not allowed"}', JSON_TYPE, close=True,
                              headers={"Allow": ", ".join(allowed_methods(route))})
            else:
                self._respond(404, b'{"error":"not found"}', JSON_TYPE, close=True)
            return
        if matched.control is None:
            self._api_read(matched)
            return
        try:
            self._console.recheck_environment()
        except ConsoleBindRefused as refusal:
            body = json.dumps({"error": str(refusal)}).encode("utf-8")
            self._drain_small_body()
            self._respond(403, body, JSON_TYPE, close=True)
            return
        if matched.control == UPLOAD_CONTROL:
            self._upload()
            return
        self._api_control(matched, params)

    def _api_read(self, route: ApiRoute) -> None:
        payload = _READS[str(route.read)]()
        self._respond(200, json.dumps(payload).encode("utf-8"), JSON_TYPE)

    def _api_control(self, route: ApiRoute, path_params: dict[str, str]) -> None:
        """Pass the request's parameters to the door unvalidated: refusing a malformed request
        is `perform`'s job, and it reports the refusal (FR-CONSOLE-34)."""
        if self.headers.get("Transfer-Encoding"):
            # A chunked body is not decoded here; left on the socket it would be parsed as the
            # next request, so the refusal closes the connection (the `_upload` precedent).
            self._respond(411, b'{"error":"a JSON body requires Content-Length"}', JSON_TYPE,
                          close=True)
            return
        length = self._declared_length()
        if length is None:
            self._respond(400, b'{"error":"invalid Content-Length"}', JSON_TYPE, close=True)
            return
        body = self._read_json_object(length)
        if body is None:
            self._respond(400, b'{"error":"the body must be a JSON object"}', JSON_TYPE)
            return
        action = str(route.control)
        try:
            outcome = self._console.app.perform(action, **{**body, **path_params})
        except (TypeError, ValueError, KeyError) as refusal:
            answer = json.dumps({"action": action, "error": str(refusal)}).encode("utf-8")
            self._respond(400, answer, JSON_TYPE)
            return
        except Exception as error:  # noqa: BLE001 — a failed action is a 500, never a dropped socket
            answer = json.dumps({"action": action, "error": str(error)}).encode("utf-8")
            self._respond(500, answer, JSON_TYPE, close=True)
            return
        self._respond(200, outcome_json(action, outcome), JSON_TYPE)

    def _declared_length(self) -> int | None:
        """The declared `Content-Length`: 0 when absent, `None` when it is not a
        non-negative integer (a negative one would read to EOF and hold the thread)."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        return length if length >= 0 else None

    def _drain_small_body(self) -> None:
        """Read and discard a refused request's body when it declares a length within
        `REFUSED_BODY_DRAIN_BYTES`; a larger or undeclared one is left unread."""
        length = self._declared_length()
        if length and length <= REFUSED_BODY_DRAIN_BYTES and not self.headers.get(
            "Transfer-Encoding"
        ):
            self.rfile.read(length)

    def _read_json_object(self, length: int) -> dict[str, Any] | None:
        """The request body as a JSON object; an empty body is `{}`, anything else `None`."""
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None


__all__ = ["API_ROUTES", "ApiRequestsMixin", "outcome_json"]
