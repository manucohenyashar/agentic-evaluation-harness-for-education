# RES-17 — The pipeline runs with no network interface

| Field | Value |
|---|---|
| ID | RES-17 |
| Req | NFR-SYS-01 |
| Injected failure | No network interface available on the host |
| Where | Whole pipeline |
| Promised behavior (design ref) | The full pipeline runs to completion (`edge-local`) |
| Assertion | An end-to-end run completes on E5 with networking disabled |

## What this is

`NFR-SYS-01`: the full pipeline runs to completion with no network interface available, and its
acceptance form is an end-to-end run with networking disabled *on the host*. The in-process socket
guard every CI test runs under shows the code makes no network call. It cannot show that nothing
underneath (the serving stack, a model loader, a certificate check) needs a network, because the
host still has one. E5 removes it: the E4 or E3 machine with networking disabled at the host level
(test plan §4.5). It runs weekly and before every release.

## Who takes part

- **Release engineer.** Disables networking, runs the journeys, and signs off.

## Setup

- **Machine.** E5: the E4 reference machine, or an E3 box, with the target models and serving stack
  already installed. Record which.
- **Before disconnecting,** install the release build, its dependencies, the models and the
  corpora. Nothing may be downloaded after step 1.
- **Networking off at the host.** Disable every network adapter (Wi-Fi, Ethernet, any VPN or virtual
  adapter) in the operating system, or physically unplug. Loopback stays, since the console binds to
  it. A firewall rule is not enough: the claim is about a missing interface, not a blocked one.

## Procedure

1. Disable networking as above. Confirm it: list the network interfaces and record that only
   loopback is up, then try to reach any external host and record the failure.
2. Run the end-to-end tier against the fixture provider: `pytest -q -m e2e` (test plan §4.7,
   "Air-gapped"). Record the pass/fail counts and the duration against the 30-minute budget.
3. On any E5 host with a local serving stack installed (always on E4, and on E3 too), also run
   one end-to-end run with the live local model server, from package setup to finalized grades, on a
   synthetic cohort. This is the `edge-local` pipeline the promise
   is about. Record where it stopped if it did not complete.
4. Re-enable networking only after recording the results.

## Record

| Record | Entry |
|---|---|
| Executed by |  |
| Date |  |
| Build |  |
| Machine (E4 or E3) |  |
| Interfaces up during the run |  |
| External reach attempt result |  |
| E2E tier result and duration |  |
| Live local end-to-end run result |  |
| Verdict |  |

**Verdict.** Pass when the interface list shows only loopback, the external reach attempt failed,
the E2E tier passed in full, and the live local run completed. The fixture tier alone cannot show
the serving stack needs no network, so a host without a serving stack gives a partial result,
recorded as such rather than as a pass. Anything that stopped the run
and names a network address, DNS lookup or download is a fail, and is recorded verbatim.
