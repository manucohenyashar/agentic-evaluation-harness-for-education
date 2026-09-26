"""OpenJevSmall shim: a loopback `/v1/systemone` server over `AlexWortega/openjev` (Jev design
delta §3.11, FR-PROV-33…36, NFR-PROV-09).

This is a **companion artifact of `M-PROV`**, deliberately outside `src/aeh`. It carries the
torch/transformers stack so the harness never does (CT-PROV-28): `aeh` talks to it over loopback
HTTP only, through `OpenJevSmallLocalProvider`, and nothing here imports `aeh`.

What it does:

- Speaks the Jev §1.2 request/response schema, so the provider reuses `parse_decision`'s
  validation and confidence normalisation unchanged. No answer carries `confidence`; the provider
  always derives it (CT-PROV-27).
- Scores every option of every question as one NLI hypothesis over the state, with the vendor's
  own hypothesis template (`vendor/openjev_decide.py`, `TEMPLATE`), and normalises P(entailment)
  over the options. That is `decide()`'s single-window path: format, score, normalise. The one
  deliberate difference is an all-zero entailment vector, which becomes uniform here rather than
  all-zero, so the answer stays a valid distribution with confidence 0.
- **Never windows.** The vendor wrapper splits a long state into windows and takes the max over
  them, and its encoder silently truncates at `max_len`. Either would change what an answer means
  (later windows lose the criterion prefix). This shim refuses such a request with HTTP 422
  instead (FR-PROV-35). It does not call the vendor `decide()` at all, so the windowing path is
  unreachable.
- Reports a verified build: `GET /v1/build` returns the sha256 of the loaded `model.safetensors`
  (FR-PROV-36).

The pure part (`translate`, `answer`, `handle`) needs no torch and is what the fast tier tests,
with an injected scorer. `OpenJevSmallScorer` is the only code that touches weights.

Run:  python tools/openjev_small_shim/shim.py --model-dir /models/openjev-small --subfolder qwen3.5-4b-nli-v5
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import logging
import os
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Protocol, Sequence

#: The vendor hypothesis template, verbatim from `vendor/openjev_decide.py` line 31 (pinned
#: revision, sha256 in VENDOR.md). Reimplemented here rather than imported because the vendor
#: module imports torch at top level, and because its `decide()` windows long states.
TEMPLATE = 'The answer to "{instr}" is {label}: {crit}'
#: The pinned Hugging Face revision of `AlexWortega/openjev` (see VENDOR.md).
PINNED_REVISION = "058a6c24911b46d908fbe23541390f8af3df3e4d"
REPO = "AlexWortega/openjev"
DEFAULT_SUBFOLDER = "qwen3.5-4b-nli-v5"
#: FR-PROV-35: more than this many Choice options, or questions, is refused (each option is one
#: forward pass, so large sets cost linearly).
MAX_CHOICE_OPTIONS = 16
MAX_QUESTIONS = 64
#: One encoder window, in tokens of the formatted "Premise: …\nHypothesis: …" text. The vendor's
#: decide wrapper describes "the 8k-token encoder"; its encoder truncates silently beyond max_len,
#: which is why the shim checks first and refuses.
DEFAULT_MAX_LEN = 8192

_LOG = logging.getLogger("openjev_small_shim")


class ShimRequestError(Exception):
    """A request the shim refuses with HTTP 422. `code` is the machine-readable reason."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class Scorer(Protocol):
    """What the shim needs from a model. The fast tier injects a fake; `OpenJevSmallScorer` is
    the real one."""

    def entailment(self, pairs: Sequence[tuple[str, str]]) -> list[float]: ...

    def fits(self, premise: str, hypothesis: str) -> bool: ...

    def tokens(self, premise: str, hypothesis: str) -> int: ...

    def build_info(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class Translated:
    """One question, as the options and hypotheses the model will score."""

    key: str
    type: str
    options: tuple[str, ...]
    hypotheses: tuple[str, ...]


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ShimRequestError("invalid_request", f"{where} must be a non-empty string")
    return value


def translate(document: Any) -> tuple[str, list[Translated]]:
    """A §1.2 request document to the state and the per-question hypotheses. Pure (FR-PROV-34).

    - **Noul:** options `no`, `yes`, with `criteria.false`/`criteria.true` as their texts.
    - **Choice:** options are the criteria keys, and a description (or the label itself when null)
      is the text.
    - **Score:** options are the level strings in order; each level is its own text.
    """
    if not isinstance(document, dict):
        raise ShimRequestError("invalid_request", "the request body is not a JSON object")
    state = document.get("state")
    if state is None:
        raise ShimRequestError("invalid_request", "state is required")
    if not isinstance(state, str):
        state = json.dumps(state, ensure_ascii=False)  # the vendor's own handling of object/array state
    _text(state, "state")
    questions = document.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise ShimRequestError("invalid_request", "questions must be a non-empty object")
    if len(questions) > MAX_QUESTIONS:
        raise ShimRequestError("too_many_questions", f"{len(questions)} questions exceed {MAX_QUESTIONS}")
    out: list[Translated] = []
    for key, q in questions.items():
        if not isinstance(q, dict):
            raise ShimRequestError("invalid_request", f"question {key!r} is not an object")
        kind = q.get("type")
        instr = _text(q.get("instructions"), f"{key}.instructions").strip()
        criteria = q.get("criteria")
        if kind == "noul":
            crit = criteria if isinstance(criteria, dict) else {}
            texts = {"no": crit.get("false") or "no", "yes": crit.get("true") or "yes"}
            options = ("no", "yes")
        elif kind == "choice":
            if not isinstance(criteria, dict) or len(criteria) < 2:
                raise ShimRequestError("invalid_request", f"choice {key!r} needs at least two options")
            if len(criteria) > MAX_CHOICE_OPTIONS:
                raise ShimRequestError("too_many_options", f"choice {key!r} has {len(criteria)} options; "
                                       f"at most {MAX_CHOICE_OPTIONS}")
            options = tuple(_text(label, f"{key} option") for label in criteria)
            texts = {label: (criteria[label] or label) for label in options}
        elif kind == "score":
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
                raise ShimRequestError("invalid_request", f"score {key!r} needs 2…10 levels")
            options = tuple(_text(level, f"{key} level") for level in criteria)
            texts = {level: level for level in options}
        else:
            raise ShimRequestError("invalid_request", f"question {key!r} has unknown type {kind!r}")
        hypotheses = tuple(TEMPLATE.format(instr=instr, label=o, crit=texts[o]) for o in options)
        out.append(Translated(str(key), kind, options, hypotheses))
    return state, out


def _normalise(values: Sequence[float]) -> list[float]:
    total = float(sum(values))
    if total <= 0.0:
        return [1.0 / len(values)] * len(values)  # no evidence for any option: uniform, confidence 0
    return [float(v) / total for v in values]


def answer(question: Translated, entailment: Sequence[float]) -> dict[str, Any]:
    """One question's §1.2 answer from its options' P(entailment). Pure (FR-PROV-34). Never
    carries `confidence`."""
    p = _normalise(entailment)
    if question.type == "noul":
        return {"type": "noul", "noul": p[1]}
    if question.type == "choice":
        best = max(range(len(p)), key=lambda i: (p[i], -i))  # first in declared order on a tie
        return {"type": "choice", "choice": question.options[best],
                "probabilities": dict(zip(question.options, p))}
    return {"type": "score", "score": sum(i * pi for i, pi in enumerate(p)),
            "legend": {str(i): level for i, level in enumerate(question.options)},
            "probabilities": {str(i): pi for i, pi in enumerate(p)}}


def handle(document: Any, scorer: Scorer) -> tuple[int, dict[str, Any]]:
    """The whole `/v1/systemone` exchange: `(status, body)`. 422 on any refusal (FR-PROV-35)."""
    try:
        state, questions = translate(document)
        for q in questions:
            # Every hypothesis, by tokens: the longest by characters is not the longest by tokens
            # (a short CJK description can out-token a long ASCII one), and one over-window pair
            # would be silently truncated by the vendor encoder.
            for hypothesis in q.hypotheses:
                if not scorer.fits(state, hypothesis):
                    raise ShimRequestError(
                        "state_exceeds_window",
                        f"question {q.key!r}: the state with one of its hypotheses exceeds one "
                        f"encoder window; refused rather than windowed or truncated")
    except ShimRequestError as error:
        return 422, {"error": error.code, "detail": error.detail}
    answers: dict[str, Any] = {}
    tokens = 0
    for q in questions:
        pairs = [(state, h) for h in q.hypotheses]
        values = scorer.entailment(pairs)
        if len(values) != len(pairs):
            return 500, {"error": "scorer_mismatch", "detail": "scorer returned the wrong count"}
        answers[q.key] = answer(q, values)
        tokens += sum(scorer.tokens(state, h) for h in q.hypotheses)
    info = scorer.build_info()
    return 200, {
        "model": f"openjev-small:{info.get('subfolder', '')}@sha256:{info.get('weights_sha256', '')}",
        "answers": answers,
        "usage": {"input_tokens": tokens, "output_tokens": 0},
    }


def weights_sha256(model_dir: str, subfolder: str) -> str:
    """sha256 of the loaded `model.safetensors`, streamed (FR-PROV-36)."""
    path = os.path.join(model_dir, subfolder, "model.safetensors")
    digest = hashlib.sha256()
    with open(path, "rb") as handle_:
        for chunk in iter(lambda: handle_.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class OpenJevSmallScorer:
    """The real scorer: the vendor cross-encoder, loaded from a local model directory. Imports
    torch lazily, so importing this module stays torch-free."""

    def __init__(self, model_dir: str, subfolder: str = DEFAULT_SUBFOLDER,
                 device: str | None = None, max_len: int = DEFAULT_MAX_LEN) -> None:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
        from modeling_openjev import ENT, OpenJevCrossEncoder  # vendored at PINNED_REVISION

        self._ent = ENT
        self._ce = OpenJevCrossEncoder(model_dir, subfolder=subfolder,
                                       device=device or os.environ.get("OPENJEV_DEVICE"), max_len=max_len)
        self._max_len = max_len
        device_name = str(self._ce.device)
        if device_name == "cuda":  # FR-PROV-36 reports the concrete device, cuda:N
            import torch
            device_name = f"cuda:{torch.cuda.current_device()}"
        self._info = {"repo": REPO, "subfolder": subfolder, "revision": PINNED_REVISION,
                      "weights_sha256": weights_sha256(model_dir, subfolder),
                      "dtype": str(getattr(self._ce.model, "dtype", "")).replace("torch.", ""),
                      "device": device_name}

    def _formatted(self, premise: str, hypothesis: str) -> str:
        return self._ce.template.format(premise=premise.strip(), hypothesis=hypothesis.strip())

    def tokens(self, premise: str, hypothesis: str) -> int:
        return len(self._ce.tok(self._formatted(premise, hypothesis))["input_ids"])

    def fits(self, premise: str, hypothesis: str) -> bool:
        return self.tokens(premise, hypothesis) <= self._max_len

    def entailment(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        return [float(row[self._ent]) for row in self._ce.predict(list(pairs))]

    def build_info(self) -> dict[str, str]:
        return dict(self._info)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def make_handler(scorer: Scorer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/v1/build":
                self._send(200, scorer.build_info())
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/systemone":
                self._send(404, {"error": "not_found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                document = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(400, {"error": "invalid_json"})
                return
            status, body = handle(document, scorer)
            self._send(status, body)

        def log_message(self, fmt: str, *args: Any) -> None:
            # NFR-PROV-09: method, path and status only. Request bodies are student work and are
            # never logged.
            _LOG.info("%s %s", self.command, args[1] if len(args) > 1 else "")

    return Handler


def build_server(scorer: Scorer, host: str = "127.0.0.1", port: int = 3001,
                 allow_remote: bool = False) -> HTTPServer:
    """A server bound to `host`. A non-loopback bind is refused unless `allow_remote`
    (NFR-PROV-09). Single-threaded on purpose: one model, one request at a time."""
    if not allow_remote and not _is_loopback(host):
        raise SystemExit(f"refusing to bind {host!r}: the shim is loopback-only unless --allow-remote")
    return HTTPServer((host, port), make_handler(scorer))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-dir", required=True, help="local directory holding <subfolder>/model.safetensors")
    parser.add_argument("--subfolder", default=DEFAULT_SUBFOLDER, help="qwen3.5-4b-nli-v5 (or the 2B fallback build)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3001)
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--max-len", type=int, default=DEFAULT_MAX_LEN)
    args = parser.parse_args(argv)
    if not args.allow_remote and not _is_loopback(args.host):
        parser.error(f"refusing to bind {args.host!r} without --allow-remote")
    # Weights load from the local directory only; no outbound call is needed or allowed.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    logging.basicConfig(level=logging.INFO)
    scorer = OpenJevSmallScorer(args.model_dir, args.subfolder, max_len=args.max_len)
    server = build_server(scorer, args.host, args.port, args.allow_remote)
    _LOG.info("openjev-small shim on %s:%d (%s)", args.host, args.port, scorer.build_info()["subfolder"])
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
