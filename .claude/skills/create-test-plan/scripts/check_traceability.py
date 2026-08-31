#!/usr/bin/env python3
"""Check a test plan's coverage of a design document's requirements.

Traceability is the part of a test plan that is tedious to verify by eye and easy to get
wrong -- a matrix built by walking the test cases always looks complete. This walks the
requirements instead, and reports what the plan misses.

Usage
-----
    python check_traceability.py --design DESIGN [DESIGN ...] --plan PLAN [PLAN ...]

DESIGN and PLAN may each be a file or a directory (directories are searched recursively for
.md/.markdown/.txt/.rst files).

Checks
------
1. Uncovered requirements -- a requirement ID in the design that is never associated with a
   test case ID in the plan, and is not listed under a "known gaps" heading.
2. Unknown requirements -- a requirement ID referenced by the plan that does not exist in
   the design (usually a typo, sometimes a requirement the plan invented).
3. Orphan test cases -- a test case ID that never appears alongside a requirement ID and is
   not declared cross-cutting.
4. Duplicate test case IDs -- the same TC ID defined in two places.

Contract clauses (`CT-*`) are checked the same way but counted and reported separately, because
they answer a different question: a requirement asks whether the design was built, a clause asks
what breaks when a module changes. Both must be covered for the check to pass. Use --contracts-only
while writing the contract suite, or --no-contracts for a design with no contract scheme.

Exit code is 1 if any check fails, so it can be used as a gate.

How association works
---------------------
A requirement is considered covered by a test case when they appear on the same line (the
RTM-row case: `| FR-AUTH-01 | ... | TC-AUTH-01, TC-AUTH-02 |`) or when the requirement
appears inside a section whose heading names a test case (the case-block form:
`#### TC-AUTH-01 - ...` followed by `| Requirements | FR-AUTH-01 |`). If you get a false
"uncovered" report, that is usually the reason -- move the requirement ID into the case's
own section or its RTM row.

Cross-cutting test cases (smoke, resilience, observability) legitimately trace to no single
requirement. Mark them by putting `cross-cutting` on the same line, or list them in a
section whose heading contains "cross-cutting".

ID patterns are configurable; the defaults match the conventions used by the
detailed-design-generator and create-test-plan skills, plus bare `R12`-style requirement IDs.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst"}

DEFAULT_REQ_PATTERN = r"\b(?:FR|NFR)(?:-[A-Z0-9]+)*-\d+\b|\bR\d+\b"
DEFAULT_CONTRACT_PATTERN = r"\bCT(?:-[A-Z0-9]+)*-\d+\b"
# The final segment allows an optional letter prefix so clause-suite cases can be named after the
# clause they verify -- TC-STORE-C02 verifies CT-STORE-02 -- which is worth the extra character in
# the pattern because it makes a failing test name point straight at the broken promise.
DEFAULT_TC_PATTERN = r"\b(?:TC|UAT|PERF|SEC|ADV|FUZZ|RES|OBS|CS)(?:-[A-Z0-9]+)*-[A-Z]?\d+\b"

GAP_HEADING = re.compile(r"^#{1,6}\s.*\b(known gaps?|gaps? and|not covered|out of scope|"
                         r"testability gaps?|open questions?)\b", re.I)
CROSS_CUTTING_HEADING = re.compile(r"^#{1,6}\s.*\bcross[- ]cutting\b", re.I)
HEADING = re.compile(r"^#{1,6}\s")
# "TC-X-01..09" / "TC-X-01-09" / "TC-X-01 to 09" -- a range shorthand used in story tables.
RANGE = re.compile(r"\b([A-Z]+(?:-[A-Z0-9]+)*-)(\d+)\s*(?:\.\.\.?|-|to)\s*(\d+)\b")


def collect_files(paths: list[str], label: str) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            sys.exit(f"error: {label} path does not exist: {p}")
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.suffix.lower() in TEXT_SUFFIXES))
        else:
            files.append(p)
    if not files:
        sys.exit(f"error: no readable {label} documents found")
    return files


def read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def expand_ranges(line: str) -> str:
    """Rewrite `TC-SCORE-01..04` into the individual IDs so they are counted."""
    def sub(m: re.Match[str]) -> str:
        prefix, start, end = m.group(1), m.group(2), m.group(3)
        width = len(start)
        lo, hi = int(start), int(end)
        if hi < lo or hi - lo > 200:
            return m.group(0)
        return " ".join(f"{prefix}{n:0{width}d}" for n in range(lo, hi + 1))
    return RANGE.sub(sub, line)


def scan_design(files: list[Path], req_re: re.Pattern[str]) -> dict[str, str]:
    """Return {requirement_id: "file:line" where first seen}."""
    found: dict[str, str] = {}
    for path in files:
        for n, line in enumerate(read(path), 1):
            for rid in req_re.findall(line):
                found.setdefault(rid, f"{path.name}:{n}")
    return found


def scan_plan(files: list[Path], req_re: re.Pattern[str], tc_re: re.Pattern[str]):
    """Return (covered_reqs, plan_reqs, tc_to_reqs, tc_definitions, gap_reqs)."""
    covered: set[str] = set()
    plan_reqs: set[str] = set()
    tc_reqs: dict[str, set[str]] = {}
    tc_defs: dict[str, list[str]] = {}
    gap_reqs: set[str] = set()

    for path in files:
        section_tcs: set[str] = set()
        in_gap_section = False
        in_cross_section = False

        for n, raw in enumerate(read(path), 1):
            line = expand_ranges(raw)
            is_heading = bool(HEADING.match(line))

            if is_heading:
                in_gap_section = bool(GAP_HEADING.match(line))
                in_cross_section = bool(CROSS_CUTTING_HEADING.match(line))
                section_tcs = set(tc_re.findall(line))
                for tc in section_tcs:
                    tc_defs.setdefault(tc, []).append(f"{path.name}:{n}")

            line_tcs = set(tc_re.findall(line))
            line_reqs = set(req_re.findall(line))
            plan_reqs |= line_reqs

            if in_gap_section:
                gap_reqs |= line_reqs
                continue

            scope_tcs = line_tcs or section_tcs
            if line_reqs and scope_tcs:
                covered |= line_reqs
                for tc in scope_tcs:
                    tc_reqs.setdefault(tc, set()).update(line_reqs)

            for tc in line_tcs:
                tc_reqs.setdefault(tc, set())
                if in_cross_section or "cross-cutting" in raw.lower():
                    tc_reqs[tc].add("<cross-cutting>")

    return covered, plan_reqs, tc_reqs, tc_defs, gap_reqs


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check test plan coverage of design requirements.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--design", nargs="+", required=True, help="design doc file(s) or dir(s)")
    ap.add_argument("--plan", nargs="+", required=True, help="test plan file(s) or dir(s)")
    ap.add_argument("--req-pattern", default=DEFAULT_REQ_PATTERN)
    ap.add_argument("--contract-pattern", default=DEFAULT_CONTRACT_PATTERN,
                    help="pattern for contract clause IDs (default matches CT-MODULE-NN)")
    ap.add_argument("--tc-pattern", default=DEFAULT_TC_PATTERN)
    ap.add_argument("--no-contracts", action="store_true",
                    help="ignore contract clauses entirely (design has no contract scheme)")
    ap.add_argument("--contracts-only", action="store_true",
                    help="check contract clause coverage only, ignoring FR/NFR requirements")
    ap.add_argument("--quiet", action="store_true", help="only print failures")
    args = ap.parse_args()

    if args.no_contracts and args.contracts_only:
        sys.exit("error: --no-contracts and --contracts-only are mutually exclusive")

    ct_re = re.compile(args.contract_pattern)
    # One scan over both ID families keeps the association logic identical for each; they are
    # split apart at report time so the two coverage questions stay distinguishable.
    parts = []
    if not args.contracts_only:
        parts.append(args.req_pattern)
    if not args.no_contracts:
        parts.append(args.contract_pattern)
    req_re = re.compile("|".join(parts))
    tc_re = re.compile(args.tc_pattern)

    is_clause = (lambda i: False) if args.no_contracts else (lambda i: bool(ct_re.fullmatch(i)))

    design_files = collect_files(args.design, "design")
    plan_files = collect_files(args.plan, "plan")

    requirements = scan_design(design_files, req_re)
    if not requirements:
        kind = "contract clause" if args.contracts_only else "requirement"
        print(f"error: no {kind} IDs found in the design documents.")
        print(f"       pattern was: {req_re.pattern}")
        print("       if the design uses a different ID scheme, pass --req-pattern or")
        print("       --contract-pattern, or assign IDs in the plan's inventory and re-run.")
        if not args.contracts_only and not args.no_contracts:
            print("       if the design defines no module contracts, pass --no-contracts.")
        return 1

    covered, plan_reqs, tc_reqs, tc_defs, gap_reqs = scan_plan(plan_files, req_re, tc_re)

    uncovered = sorted(r for r in requirements if r not in covered and r not in gap_reqs)
    unknown = sorted(r for r in plan_reqs if r not in requirements)
    orphans = sorted(tc for tc, reqs in tc_reqs.items() if not reqs)
    duplicates = sorted(tc for tc, locs in tc_defs.items() if len(locs) > 1)

    def split(ids):
        """(requirements, contract clauses) -- reported separately, gated together."""
        ids = list(ids)
        return [i for i in ids if not is_clause(i)], [i for i in ids if is_clause(i)]

    req_ids, clause_ids = split(requirements)
    traced_reqs, traced_clauses = split(covered & set(requirements))

    def line(label, traced, total):
        pct = 100.0 * len(traced) / len(total) if total else 0.0
        return f"{label:<12}: {len(traced)}/{len(total)} traced ({pct:.1f}%)"

    if not args.quiet:
        print(f"design docs : {len(design_files)}   plan docs: {len(plan_files)}")
        print(f"test cases  : {len(tc_reqs)}")
        if req_ids:
            print(line("requirements", traced_reqs, req_ids))
        if clause_ids:
            print(line("clauses", traced_clauses, clause_ids))
        if gap_reqs:
            print(f"known-gaps  : {len(gap_reqs & set(requirements))}")
        print()

    ok = True

    unc_reqs, unc_clauses = split(uncovered)

    if unc_reqs:
        ok = False
        print(f"FAIL  {len(unc_reqs)} requirement(s) with no test case and no known-gaps entry:")
        for r in unc_reqs:
            print(f"        {r:<20} (design {requirements[r]})")
        print()

    if unc_clauses:
        ok = False
        print(f"FAIL  {len(unc_clauses)} contract clause(s) with no test case and no known-gaps entry:")
        for r in unc_clauses:
            print(f"        {r:<20} (design {requirements[r]})")
        print("      (a clause with no case is a promise nobody is holding the module to --")
        print("       add a case that goes red when the clause is violated, or record the gap)")
        print()

    if unknown:
        ok = False
        print(f"FAIL  {len(unknown)} requirement/clause ID(s) referenced by the plan but absent from the design:")
        for r in unknown:
            print(f"        {r}")
        print("      (typo, or an ID the plan introduced -- reconcile with the design)")
        print()

    if orphans:
        ok = False
        print(f"FAIL  {len(orphans)} test case(s) tracing to no requirement:")
        for tc in orphans:
            where = tc_defs.get(tc, ["not defined as a section heading"])[0]
            print(f"        {tc:<20} ({where})")
        print("      (add the requirement ID to the case, or mark it cross-cutting)")
        print()

    if duplicates:
        ok = False
        print(f"FAIL  {len(duplicates)} duplicate test case ID(s):")
        for tc in duplicates:
            print(f"        {tc:<20} {', '.join(tc_defs[tc])}")
        print()

    if ok:
        what = "requirement"
        if clause_ids and req_ids:
            what = "requirement and contract clause"
        elif clause_ids:
            what = "contract clause"
        print(f"PASS  every {what} traces to a test case or a known-gaps entry;"
              " no orphan or duplicate test IDs.")
        return 0

    print("Traceability check failed. Fix the gaps above and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
