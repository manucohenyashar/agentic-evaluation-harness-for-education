"""Making frozen value objects raise on assignment, deletion and `replace`."""

from __future__ import annotations

from typing import Any


# --- immutability --------------------------------------------------------------------------


def _typeerror_on_mutation(cls):
    """Make assignment, deletion and `replace` on a frozen value object raise `TypeError`.

    More detail: `docs/code-notes/conf.md`, section `frozen.py: _typeerror_on_mutation`.
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
