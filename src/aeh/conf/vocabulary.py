"""The fixed vocabulary of run configuration: backend profiles, model roles, panel sizes."""

from __future__ import annotations

from typing import Literal


# --- types ---------------------------------------------------------------------------------

BackendProfile = Literal["edge-local", "cloud-hosted", "dev-ci"]


HardwareProfileName = Literal["unified-large", "unified-small", "discrete-gpu"]


ModelRole = Literal["judge", "transcriber", "extractor", "off_panel", "synthesizer", "decision"]


BuildForm = Literal["edge-weights", "provider-pinned"]


BACKEND_PROFILES: tuple[str, ...] = ("edge-local", "cloud-hosted", "dev-ci")


#: `CT-CONF-02`: "`panel` has length 1, 3, or 5 — never even, never 0."
PANEL_SIZES: frozenset[int] = frozenset({1, 3, 5})
