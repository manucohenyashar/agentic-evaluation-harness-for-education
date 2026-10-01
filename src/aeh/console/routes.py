"""The thirteen screens and the role-scoped routes that reach them."""

from __future__ import annotations


# --- the screens (HLD §11.5) --------------------------------------------------------------------------

#: The fourteen screens: the HLD's thirteen, in the HLD's numbering, plus the provenance
#: gate — `CT-CONSOLE-16` requires the export decision to be *a reachable screen*, not an
#: internal check, so the gate has a route the teacher can open (`FR-CONSOLE-23`).
#: `BLOCKING_SCREENS` are the two that hold run start until completed; `OPERATOR_SCREENS`
#: are the operator surface quarantine triage and run monitoring live on (§7.7).
SCREENS: dict[str, str] = {
    "S1": "/packages",
    "S2": "/packages/new",
    "S3": "/setup/inventory",
    "S4": "/setup/answer-keys",
    "S5": "/setup/optional",
    "S6": "/cohorts/{id}/preflight",
    "S7": "/runs/{id}/monitor",
    "S8": "/quarantine",
    "S9": "/runs/{id}/review",
    "S10": "/runs/{id}/sample",
    "S11": "/runs/{id}/blind",
    "S12": "/runs/{id}/rollup",
    "S13": "/students/{ref}",
    "S14": "/packages/{version}/export-gate",
}


BLOCKING_SCREENS = frozenset({"S3", "S4"})


#: CT-CONSOLE-07 (#532): M-SETUP's blocking steps, and the screen each renders on. The
#: console's blocking set is derived from M-SETUP's enumeration; a blocking step with no
#: screen here is still counted, under its own step id. `BLOCKING_SCREENS` stays the
#: storeless double's answer (no store, no setup to ask).
SETUP_STEP_SCREENS = {"inventory": "S3", "answer_keys": "S4"}


OPERATOR_SCREENS = frozenset({"S6", "S7", "S8"})


#: The route tables, verbatim from the settled vocabulary, plus the provenance gate —
#: §3.19's teacher table with the one route `CT-CONSOLE-16` adds: the export decision is
#: a screen the teacher reaches, not an internal check (`FR-CONSOLE-23`). No auth route
#: exists anywhere: authN/authZ is none, deliberately, bounded by the loopback refusal
#: (`CT-CONSOLE-23`).
TEACHER_ROUTES = (
    "/packages",
    "/packages/new",
    "/packages/{version}/export-gate",
    "/setup/*",
    "/runs/{id}/review",
    "/runs/{id}/blind",
    "/runs/{id}/sample",
    "/runs/{id}/rollup",
    "/students/{ref}",
)


OPERATOR_ROUTES = (
    "/cohorts",
    "/cohorts/{id}/preflight",
    "/runs/{id}/monitor",
    "/quarantine",
)


#: The screen routes that carry grades and audit records — the audit surface (`CT-CONSOLE-23`).
AUDIT_ROUTES = ("/runs/{id}/rollup", "/runs/{id}/monitor")


#: Loopback addresses a legal bind may name.
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1", "localhost"})


#: The deployment profile whose every setting combination refuses to start (`CT-CONSOLE-05`).
CLOUD_HOSTED_PROFILE = "cloud-hosted"


#: The replay routes §11.8 names. All three dedupe to no additional row (`FR-CONSOLE-02`).
REPLAY_ROUTES: tuple[str, ...] = ("double_click", "retried_request", "back_navigation")
