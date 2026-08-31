#!/usr/bin/env python3
# a360-stack-kit — metamorphic testing SKELETON (a REFERENCE to copy + fill in, not a runnable suite).
#
# Metamorphic relations (MRs) assert properties that must hold across input transforms WITHOUT needing a
# golden output — ideal for a pure transform / mapping / rules endpoint. Copy this into your stack, then
# fill the three stack-specific bits: ENDPOINT, BASE (a valid request), and `comparable(resp)` (how to
# normalize the response for equality). The six MRs below are the generic patterns; keep the ones that
# apply and delete the rest.
import json, urllib.request, copy, sys

# ---- FILL IN (stack-specific) ---------------------------------------------------------------
ENDPOINT = "http://localhost:PORT/YourEndpoint"           # the live endpoint (auth off, DB seeded)
HEADERS  = {"Content-Type": "application/json", "api-version": "1.0"}
BASE     = {                                              # a valid baseline request for your endpoint
    # "SourceData": json.dumps({...}), ...
}
def comparable(resp):                                     # normalize the response for equality compares
    # e.g. return json.dumps(resp.get("targetData"), sort_keys=True)
    return json.dumps(resp, sort_keys=True)
# The field a "localized change" should move (MR5) — adapt or drop MR5 if N/A:
def localized_change(req): pass                           # mutate `req` in place for the localized test
# ---------------------------------------------------------------------------------------------

def call(req):
    data = json.dumps(req).encode()
    r = urllib.request.Request(ENDPOINT, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(r, timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode())

results = []
def rec(name, ok, detail=""):
    results.append((name, ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — '+detail) if detail else ''}")

try:
    st, base = call(BASE)
except Exception as e:
    print("BASELINE call failed:", e); sys.exit(1)
base_c = comparable(base)
print(f"baseline: HTTP {st}")
rec("baseline returns 200", st == 200)

# MR1 determinism: same input N times -> identical output
outs = {comparable(call(BASE)[1]) for _ in range(5)}
rec("MR1 determinism (5x identical output)", outs == {base_c}, f"{len(outs)} distinct")

# MR2 additive unmapped-field invariance: adding fields the transform ignores must not change output.
# (Fill: add an obviously-unmapped field to a copy of BASE, then compare.)
# MR3 whitespace/reformat invariance: re-serialize the same content differently -> same output.
# MR4 key-reorder invariance: reorder top-level keys -> same output.
# MR5 localized change: a single-field change moves only the corresponding output field.
# MR6 idempotence / no-side-effects: re-run BASE after all mutations -> still identical to base_c.
_, o6 = call(BASE)
rec("MR6 baseline reproducible after mutation calls (no side effects)", comparable(o6) == base_c)

passed = sum(1 for _, ok in results if ok)
print(f"\nSUMMARY: {passed}/{len(results)} MR checks passed")
sys.exit(0 if passed == len(results) else 1)
