"""The manual E4 runs for OpenJevSmall: PERF-17 (NFR-JUDGE-10) and PERF-18 (NFR-SYS-16). #456.

Run this on E4, the `unified-small` reference machine. The OpenJevSmall shim
(`tools/openjev_small_shim`) must be serving on loopback, and the reference 30B-class judge
must be serving on its local server. The script then does four things:

1. Dispatches N decision seats (default 200) through `OpenJevSmallLocalProvider` at the default
   16 citation questions, `--concurrency` at a time (default 2, the `unified-small` ceiling).
   Each unit is an F-JEV cell extended to carry exactly 16 evidence spans, so every request is a
   judge-built `DecisionRequest` with the full citation load NFR-JUDGE-10 is stated at. Each
   unit goes through `decision_eligibility` first, as the seat would.
2. Dispatches the seat-0 LLM call on the same units through the judge's own provider and prompt.
   The figure that matters is the ratio between the two: design NFR-JUDGE-10 says "If
   `openjev-small` is not faster than the LLM it pre-screens, it adds cost without benefit".
3. Samples the peak resident memory of the processes you name (`--pid`, for example the shim and
   the judge server; children are included, each process once) and the growth of swap in use,
   and counts out-of-memory failures. A failed or timed-out call still counts: its elapsed time
   goes into the latency figures and the gate is not "ok" while any call failed.
4. Writes the result to `--out` as JSON. That file is the recorded result the issue asks for,
   and release notes quote it.

Reading the result:

- NFR-JUDGE-10 is `decision_p95_s <= 20`, with the ratio reported beside it.
- NFR-SYS-16 is `peak_memory_bytes` under `--memory-ceiling-gb`, with `oom_count == 0` and swap
  growth under `--swap-tolerance-mb`. PERF-18's full form is the engine-on pipeline over
  F-JEV-PERF at the profile ceiling. For that, start the real run (`python -m aeh ...` with
  `openjev-small`) and run this script with `--watch SECONDS` beside it: it then only samples
  memory and swap for that long and records them.
- If the run fails with the 4B build, re-run with the 2B fallback build (design FR-CONF-27):
  `--decision-build /models/openjev-small/qwen3.5-2b-nli-v5/model.safetensors@sha256:<hex>`.
  That fallback is chosen at configuration time, never at runtime.

`--dry-run` replaces both seats with deterministic fakes, so the plumbing can be checked on any
machine. A dry run records nothing about the hardware.

Usage:
    python tools/e4_openjev_small/run_gate.py \\
        --decision-build /models/openjev-small/qwen3.5-4b-nli-v5/model.safetensors@sha256:<hex> \\
        --judge-build /models/<judge>.gguf@sha256:<hex> --judge-quantization q4 \\
        --memory-ceiling-gb 28 --pid <shim pid> --pid <judge pid> \\
        --out docs/perf/e4-openjev-small-4b.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Sequence

NFR_JUDGE_10_P95_S = 20.0


def _percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile; `None` over no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


class MemorySampler:
    """Samples the summed RSS of `pids` every `interval_s` on a thread; the peak is kept.
    Without psutil, or with no pids, it records nothing and says so."""

    def __init__(self, pids: Sequence[int], interval_s: float = 0.5) -> None:
        self.pids = list(pids)
        self.interval_s = interval_s
        self.peak_bytes: int | None = None
        self.swap_start: int | None = None
        self.swap_peak: int | None = None
        self.note: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "MemorySampler":
        try:
            import psutil  # noqa: F401
        except ImportError:
            self.note = "psutil not installed: peak memory not measured"
            return self
        import psutil

        self.swap_start = self.swap_peak = psutil.swap_memory().used
        if not self.pids:
            self.note = "no --pid given: peak memory not measured"
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        import psutil

        while not self._stop.is_set():
            seen: dict[int, int] = {}
            for pid in self.pids:
                try:
                    process = psutil.Process(pid)
                    family = [process, *process.children(recursive=True)]
                except psutil.Error:
                    continue
                for member in family:
                    try:
                        seen[member.pid] = member.memory_info().rss
                    except psutil.Error:
                        continue
            if seen:  # a sample in which no process could be read is no sample at all
                self.peak_bytes = max(self.peak_bytes or 0, sum(seen.values()))
            self.swap_peak = max(self.swap_peak or 0, psutil.swap_memory().used)
            self._stop.wait(self.interval_s)
        if self.peak_bytes is None and self.note is None:
            self.note = "no --pid could be read: peak memory not measured"

    @property
    def swap_increase_bytes(self) -> int | None:
        if self.swap_start is None or self.swap_peak is None:
            return None
        return max(0, self.swap_peak - self.swap_start)

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def _is_oom(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {error}".lower()
    return "out of memory" in text or "outofmemory" in text or "oom" in text.split()


def measure(units: Sequence[Any], decide: Callable[[Any], Any], llm: Callable[[Any], Any], *,
            sampler: MemorySampler | None = None, clock: Callable[[], float] = time.perf_counter,
            memory_ceiling_bytes: int | None = None, concurrency: int = 1,
            swap_tolerance_bytes: int = 256 * 1024 ** 2) -> dict[str, Any]:
    """Time `decide(unit)` and `llm(unit)` per unit, `concurrency` units at a time, and
    summarise. Errors are counted, never raised: an out-of-memory failure is a result of this
    gate, not a crash of it. A failed call's elapsed time still enters the latency figures, and
    a seat is not "ok" while any of its calls failed."""
    from concurrent.futures import ThreadPoolExecutor

    decision_s: list[float] = []
    llm_s: list[float] = []
    errors: dict[str, int] = {}
    failed = {"decision": 0, "llm": 0}
    oom = 0
    lock = threading.Lock()

    def one(unit: Any) -> None:
        nonlocal oom
        for label, call, bucket in (("decision", decide, decision_s), ("llm", llm, llm_s)):
            start = clock()
            error: Exception | None = None
            try:
                call(unit)
            except Exception as exc:  # noqa: BLE001 - the gate records every failure
                error = exc
            elapsed = clock() - start
            with lock:
                bucket.append(elapsed)
                if error is not None:
                    key = f"{label}:{type(error).__name__}"
                    errors[key] = errors.get(key, 0) + 1
                    failed[label] += 1
                    oom += int(_is_oom(error))

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        list(pool.map(one, units))
    p95_decision = _percentile(decision_s, 0.95)
    p95_llm = _percentile(llm_s, 0.95)
    peak = sampler.peak_bytes if sampler is not None else None
    swap = sampler.swap_increase_bytes if sampler is not None else None
    return {
        "units": len(units),
        "concurrency": concurrency,
        "decision_calls_failed": failed["decision"],
        "llm_calls_failed": failed["llm"],
        "decision_p50_s": _percentile(decision_s, 0.5),
        "decision_p95_s": p95_decision,
        "llm_p95_s": p95_llm,
        # NFR-JUDGE-10's figure that matters: >= 1 means the engine is not faster than the LLM.
        "decision_to_llm_p95_ratio": (None if not p95_decision or not p95_llm
                                      else p95_decision / p95_llm),
        "nfr_judge_10_p95_ok": (None if p95_decision is None
                                else p95_decision <= NFR_JUDGE_10_P95_S and failed["decision"] == 0),
        "oom_count": oom,
        "errors": errors,
        "peak_memory_bytes": peak,
        "memory_note": sampler.note if sampler is not None else "not sampled",
        "memory_ceiling_bytes": memory_ceiling_bytes,
        "swap_increase_bytes": swap,
        "nfr_sys_16_ok": (None if peak is None or memory_ceiling_bytes is None or swap is None
                          else peak < memory_ceiling_bytes and oom == 0
                          and swap <= swap_tolerance_bytes),
    }


def _live_calls(args: argparse.Namespace) -> tuple[list[Any], Callable[[Any], Any], Callable[[Any], Any]]:
    from aeh.conf import DecisionEngine, ModelRef
    from aeh.judge import (JUDGE_TEMPERATURE, Ineligible, decision_eligibility, decision_request,
                           prompt_fields)
    from aeh.prov import SamplingParams, decision_provider_for, provider_for

    engine = DecisionEngine(
        model=ModelRef(role="decision", provider="openjev-small", build_id=args.decision_build,
                       quantization="bf16"),
        confidence_threshold=Decimal("0.85"), cite_threshold=Decimal("0.50"),
        max_citation_questions=16, token_bytes_ratio=3)
    judge = ModelRef(role="judge", provider=args.judge_provider, build_id=args.judge_build,
                     quantization=args.judge_quantization)
    decision_provider = decision_provider_for(engine.model)
    decision_provider.verify_build(engine.model, placement=args.placement)
    llm_provider = provider_for(judge)
    params = SamplingParams(temperature=JUDGE_TEMPERATURE, max_tokens=None)
    units = sixteen_span_units(args.units)
    capabilities = decision_provider.decision_capabilities(engine.model)

    def decide(request: Any) -> Any:
        eligibility = decision_eligibility(request, engine, capabilities)
        if isinstance(eligibility, Ineligible):
            raise RuntimeError(f"ineligible: {eligibility.reason}")
        return decision_provider.decide(decision_request(request, engine), engine.model)

    return (units, decide,
            lambda request: llm_provider.complete(prompt_fields(request), judge, params))


def sixteen_span_units(n: int) -> list[Any]:
    """F-JEV's J4 cells, each extended with sixteen distinct evidence lines that are its sixteen
    spans, so every dispatch asks the default 16 citation questions (NFR-JUDGE-10)."""
    from aeh.conform import load_f_jev_cells
    from aeh.judge import ScoringRequest

    cells = [c for c in load_f_jev_cells() if c.request.criterion.criterion_id == "J4"]
    units = []
    for i in range(n):
        base = cells[i % len(cells)].request
        lines = [f"Step {k + 1}: the force balance along and across the ramp is checked again, "
                 f"case {i}-{k}." for k in range(16)]
        text = base.submission_text + "\n" + "\n".join(lines)
        spans, cursor = [], 0
        for line in lines:
            start = text.index(line, cursor)
            spans.append({"start": start, "end": start + len(line), "text": line,
                          "region_kind": "transcribed_text"})
            cursor = start + len(line)
        units.append(ScoringRequest(
            work_id=f"E4-{i}", criterion=base.criterion, question=base.question, evidence=spans,
            dependency_evidence=[], submission=base.submission, submission_text=text))
    return units


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--decision-build", default="")
    parser.add_argument("--judge-build", default="")
    parser.add_argument("--judge-provider", default="local")
    parser.add_argument("--judge-quantization", default="q4")
    parser.add_argument("--placement", choices=("shared", "cpu"), default="shared",
                        help="cpu on discrete-gpu (FR-CONF-28): the shim must report device cpu")
    parser.add_argument("--units", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=2,
                        help="the profile concurrency ceiling (unified-small: 2)")
    parser.add_argument("--swap-tolerance-mb", type=float, default=256.0)
    parser.add_argument("--watch", type=float, default=None,
                        help="PERF-18 beside a real run: only sample memory and swap for SECONDS")
    parser.add_argument("--pid", type=int, action="append", default=[])
    parser.add_argument("--memory-ceiling-gb", type=float, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    ceiling = None if args.memory_ceiling_gb is None else int(args.memory_ceiling_gb * 1024 ** 3)
    swap_tolerance = int(args.swap_tolerance_mb * 1024 ** 2)
    if args.watch is not None:
        with MemorySampler(args.pid) as sampler:
            time.sleep(args.watch)
        peak, swap = sampler.peak_bytes, sampler.swap_increase_bytes
        result: dict[str, Any] = {
            "mode": "watch", "watched_s": args.watch, "peak_memory_bytes": peak,
            "swap_increase_bytes": swap, "memory_note": sampler.note,
            "memory_ceiling_bytes": ceiling,
            "nfr_sys_16_memory_ok": (None if peak is None or ceiling is None or swap is None
                                     else peak < ceiling and swap <= swap_tolerance),
            "note": "OOM and failures are read from the run's own RunResult, not sampled here",
        }
        return _emit(result, args)
    if args.dry_run:
        units = list(range(args.units))
        decide = llm = lambda unit: None  # noqa: E731
    else:
        if not args.decision_build or not args.judge_build:
            parser.error("--decision-build and --judge-build are required unless --dry-run")
        units, decide, llm = _live_calls(args)
    with MemorySampler(args.pid) as sampler:
        result = measure(units, decide, llm, sampler=sampler, memory_ceiling_bytes=ceiling,
                         concurrency=args.concurrency, swap_tolerance_bytes=swap_tolerance)
    result.update({"dry_run": args.dry_run, "decision_build": args.decision_build,
                   "judge_build": args.judge_build, "placement": args.placement})
    return _emit(result, args)


def _emit(result: dict[str, Any], args: argparse.Namespace) -> int:
    result["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
