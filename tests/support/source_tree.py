"""Read the source of an `aeh` module, whether it is one file or a package of files.

Static tests (write-set audits, "no SQL here" checks, census walks) read module source. Each
`aeh` module is a package: `src/aeh/judge/` holds `__init__.py` plus the files that implement
it. A test that read `src/aeh/judge.py`, or called `inspect.getsource(judge)` (which returns
only `__init__.py` for a package), would scan almost nothing and pass for the wrong reason.

Use these helpers instead:

- `module_files("judge")`: every `.py` file of the module.
- `module_source("judge")`: all of those files joined into one text. `ast.parse` accepts it.
- `aeh_modules()`: every top-level `aeh` module, as `(name, files)`, where `name` keeps the
  old file-name spelling (`"judge.py"`), so allow-lists keyed on file names still read the same.
- `package_source(module)`: the drop-in for `inspect.getsource(module)` on a module object.
"""
from __future__ import annotations

from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_AEH = REPO_ROOT / "src" / "aeh"


def _files_under(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)


def module_files(name: str, src_root: Path = SRC_AEH) -> list[Path]:
    """Every source file of `aeh.<name>`. `name` may be `"judge"` or `"judge.py"`."""
    stem = name.removesuffix(".py")
    package = src_root / stem
    if package.is_dir():
        files = _files_under(package)
    else:
        files = [src_root / f"{stem}.py"]
    missing = [f for f in files if not f.is_file()]
    if not files or missing:
        raise FileNotFoundError(f"aeh.{stem} has no source under {src_root}")
    return files


def read_files(files: list[Path]) -> str:
    return "\n\n".join(f.read_text(encoding="utf-8") for f in files)


def module_source(name: str, src_root: Path = SRC_AEH) -> str:
    """The full source of `aeh.<name>`: every file of the module, joined."""
    return read_files(module_files(name, src_root))


def aeh_modules(src_root: Path = SRC_AEH) -> list[tuple[str, list[Path]]]:
    """Every top-level module of `aeh` as `("<name>.py", files)`, sorted by name.

    A package `src/aeh/judge/` is reported as `"judge.py"` with all of its files, so rules
    written against the one-file layout keep their meaning. `aeh/__init__.py` and
    `aeh/__main__.py` are reported as themselves.
    """
    found: list[tuple[str, list[Path]]] = []
    for entry in sorted(src_root.iterdir()):
        if entry.is_file() and entry.suffix == ".py":
            found.append((entry.name, [entry]))
        elif entry.is_dir() and (entry / "__init__.py").is_file():
            found.append((f"{entry.name}.py", _files_under(entry)))
    return found


def aeh_module_sources(src_root: Path = SRC_AEH) -> list[tuple[str, str]]:
    """`(name, source)` for every top-level `aeh` module; see `aeh_modules`."""
    return [(name, read_files(files)) for name, files in aeh_modules(src_root)]


def top_module_of(path: Path, src_root: Path = SRC_AEH) -> str:
    """The top-level module a source file belongs to, spelled `"judge.py"`."""
    first = Path(path).resolve().relative_to(src_root.resolve()).parts[0]
    return first if first.endswith(".py") else f"{first}.py"


def package_source(module: ModuleType) -> str:
    """`inspect.getsource(module)`, extended to every file of a package."""
    path = getattr(module, "__path__", None)
    if path:
        return read_files(sorted(f for d in path for f in _files_under(Path(d))))
    return Path(module.__file__).read_text(encoding="utf-8")


def defined_in(obj: object, module: ModuleType | str) -> bool:
    """True when `obj` was defined in `module` or in one of its files.

    The drop-in for `obj.__module__ == module.__name__`: a class defined in
    `aeh/judge/assembly.py` has `__module__ == "aeh.judge.assembly"`.
    """
    name = module if isinstance(module, str) else module.__name__
    owner = getattr(obj, "__module__", None) or ""
    return owner == name or owner.startswith(name + ".")


class ModuleSource:
    """One `aeh` module seen as a single file, for scanners written against `src/aeh/*.py`.

    It answers `.name` (`"judge.py"`), `.stem` (`"judge"`) and `.read_text()` (every file of
    the module, joined), which is all such a scanner asks of a `Path`.
    """

    def __init__(self, name: str, files: list[Path]):
        self.name = name
        self.stem = name.removesuffix(".py")
        self.files = files

    def read_text(self, encoding: str = "utf-8") -> str:
        return "\n\n".join(f.read_text(encoding=encoding) for f in self.files)

    def exists(self) -> bool:
        return all(f.is_file() for f in self.files)

    is_file = exists

    def __fspath__(self) -> str:
        return str(self.files[0].parent if len(self.files) > 1 else self.files[0])

    def __str__(self) -> str:
        return self.__fspath__()

    def __repr__(self) -> str:
        return f"ModuleSource({self.name!r}, {len(self.files)} files)"


def aeh_module_paths(src_root: Path = SRC_AEH) -> list[ModuleSource]:
    """Every top-level `aeh` module as a `ModuleSource`: the drop-in for `sorted(src.glob("*.py"))`."""
    return [ModuleSource(name, files) for name, files in aeh_modules(Path(src_root))]


def module_path(name: str, src_root: Path = SRC_AEH) -> ModuleSource:
    """`aeh.<name>` as a `ModuleSource`: the drop-in for `src_root / "<name>.py"`."""
    return ModuleSource(f"{name.removesuffix('.py')}.py", module_files(name, Path(src_root)))


def top_module(name: str) -> str:
    """`"aeh.judge.assembly"` -> `"aeh.judge"`: the top-level module a file belongs to.

    For code that attributes work by `frame.f_globals["__name__"]` or `__module__` and compares
    against a module name such as `"aeh.pipeline"`.
    """
    parts = name.split(".")
    return ".".join(parts[:2]) if parts[0] == "aeh" else name


def class_members(cls: type) -> list[tuple[str, object]]:
    """`vars(cls).items()` including what `cls` gets from its mixins, nearest definition first.

    A large class is split into mixins, one file each, so its methods no longer all sit in
    `vars(cls)`. `object`'s members are left out.
    """
    seen: dict[str, object] = {}
    for klass in cls.__mro__:
        if klass is object:
            continue
        for name, member in vars(klass).items():
            seen.setdefault(name, member)
    return list(seen.items())


def bindings(package: ModuleType, name: str) -> list[object]:
    """What `name` is bound to in `package` and in each of its loaded files, where it is bound.

    For checks about a name a module *imported*: after the split, `from aeh.ingest import X`
    sits in the file of the package that uses `X`, not in the package namespace.
    """
    import sys

    prefix = package.__name__ + "."
    holders = [package] + [m for n, m in list(sys.modules.items())
                           if n.startswith(prefix) and isinstance(m, ModuleType)]
    return [vars(m)[name] for m in holders if name in vars(m)]
