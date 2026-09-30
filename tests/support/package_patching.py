"""Make `monkeypatch.setattr(aeh.<package>, name, value)` reach the package's own files.

Every `aeh` module is a package of several files. A name like `aeh.judge.assemble` is defined
in one file (`aeh/judge/assembly.py`) and re-exported by the package's `__init__.py`. Other
files in the package use it through `from .assembly import assemble`, so each of them holds
its own reference.

A test that patches `aeh.judge.assemble` expects every caller to see the patch, as it did when
the package was one file. `pytest.MonkeyPatch.setattr` only replaces the package attribute. So
this module wraps `setattr` and `delattr`: when the target is an `aeh` package, the same change
is also applied to each file of that package that holds the *same object* under the same name.
Undo restores all of them, because each change goes through the original `setattr`.

Files of other packages are left alone. A `from aeh.judge import assemble` in `aeh.pipeline`
was not reached by the patch before the split either.
"""
from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest
from _pytest.compat import NOTSET as notset

_MISSING = object()
_original_setattr = pytest.MonkeyPatch.setattr
_original_delattr = pytest.MonkeyPatch.delattr


def _is_aeh_package(target: object) -> bool:
    return (isinstance(target, ModuleType) and hasattr(target, "__path__")
            and target.__name__.startswith("aeh."))


def _files_holding(package: ModuleType, name: str) -> list[ModuleType]:
    """The package's submodules whose `name` is the same object as the package's."""
    original = vars(package).get(name, _MISSING)
    if original is _MISSING:
        return []
    prefix = package.__name__ + "."
    return [module for module_name, module in list(sys.modules.items())
            if module_name.startswith(prefix) and isinstance(module, ModuleType)
            and vars(module).get(name, _MISSING) is original]


def _resolve_dotted(path: str) -> tuple[object, str]:
    """`"aeh.judge.assemble"` -> (the `aeh.judge` module, "assemble")."""
    module_path, _, attr = path.rpartition(".")
    return importlib.import_module(module_path), attr


def _setattr(self, target, name, value=notset, raising=True):
    if isinstance(target, str) and value is notset:  # the `setattr("aeh.x.name", value)` form
        value = name
        target, name = _resolve_dotted(target)
    if _is_aeh_package(target):
        for module in _files_holding(target, name):
            _original_setattr(self, module, name, value, raising=raising)
    return _original_setattr(self, target, name, value, raising=raising)


def _delattr(self, target, name=notset, raising=True):
    if isinstance(target, str) and name is notset:  # the `delattr("aeh.x.name")` form
        target, name = _resolve_dotted(target)
    if _is_aeh_package(target):
        for module in _files_holding(target, name):
            _original_delattr(self, module, name, raising=raising)
    return _original_delattr(self, target, name, raising=raising)


def install() -> None:
    pytest.MonkeyPatch.setattr = _setattr
    pytest.MonkeyPatch.delattr = _delattr
