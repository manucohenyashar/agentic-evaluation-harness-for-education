"""Making frozen value objects raise on assignment, deletion and `replace`."""

from __future__ import annotations

from typing import Any


# --- immutability --------------------------------------------------------------------------


def _typeerror_on_mutation(cls):
    """Make assignment, deletion and `replace` on a frozen value object raise `TypeError`.

    `FR-CONF-02` and `CT-CONF-04` both name `TypeError` specifically, and a plain
    `@dataclass(frozen=True)` raises `dataclasses.FrozenInstanceError` — which subclasses
    `AttributeError`, not `TypeError`. A `pytest.raises(TypeError)` written from the requirement
    would fail against a correct implementation.

    `__replace__` is closed too, which shuts `copy.replace` (Python 3.13+): a copy carrying a
    different `backend_profile` or `panel` is precisely the rebinding `CT-CONF-04` forbids and
    RISK-22 describes.

    `dataclasses.replace` does **not** route through `__replace__` — verified on CPython 3.14,
    where it calls `obj.__class__(**changes)` directly — so this decorator cannot see it. It is
    narrowed from the other end instead: `RunConfig.__post_init__` enforces `CT-CONF-02`,
    `CT-CONF-03` and `CT-CONF-07` on the *type*, so a replace that rebinds the backend, the
    hardware profile, either cost field, or the panel raises. Direct construction of a legal
    literal keeps working, which design §3.1's Compatibility note requires in as many words:
    *"Consumers test against a literal `RunConfig` value rather than a double — the type is
    frozen and cheap to construct."*

    Precisely what stays open, so nobody reads more into this than it does:

    - a *self-consistent* rebuild (`replace(cfg, backend_profile=…, hardware_profile=None,
      panel=<hosted builds>, cost_ceiling=…, cost_currency=…, panel_build_ref=…)`), which is
      indistinguishable from constructing the literal directly and so cannot be closed without
      forbidding both;
    - `replace(cfg, concurrency_ceiling=999)`, because the ceiling a config was resolved under
      depends on the hardware table used at resolution time, which the value does not carry;
    - pickle's `__setstate__` and a hand-edited `run` row.

    All three belong to `TC-CONF-C14`'s back-door sweep — see the module docstring's note on
    which issue owns that clause.

    The decorator is applied *after* `@dataclass(frozen=True)`, which is required: assigning
    `__setattr__` inside the class body makes the dataclass decorator itself raise. The
    generated `__init__` writes through `object.__setattr__`, so construction is unaffected.
    """

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError(
            f"{cls.__name__} is frozen: cannot assign to {name!r}. A consumer needing a "
            f"different value creates a new run (CT-CONF-04, CT-CONF-14)."
        )

    def __delattr__(self, name: str) -> None:
        raise TypeError(f"{cls.__name__} is frozen: cannot delete {name!r}.")

    def __replace__(self, /, **changes: Any):
        raise TypeError(
            f"{cls.__name__} does not support replace(): no operation returns a copy with a "
            f"different backend, panel or ceiling (CT-CONF-14)."
        )

    cls.__setattr__ = __setattr__
    cls.__delattr__ = __delattr__
    cls.__replace__ = __replace__
    return cls
