"""Auto-discovering CLI registry: `python -m cpa <module> <command> [--flags]`.

Implements guide section 9's cli.py dispatch and build checklist 13.12 ("every module reachable",
R091). No unit ever edits this file: every module or workflow under cpa/ that wants a subcommand
defines a module-level `register(subparsers)` and discovery finds it by walking the cpa/ directory
on disk and importing each module (namespace directories without __init__.py included).

Contract (docs/ARCHITECTURE.md, AGENTS.md):
1. The top-level name a module registers equals its basename (cpa.workflows.charge_forecast ->
   charge_forecast). A package whose __init__.py registers its own name (cpa.sources, cpa.pptx)
   nests its leaves: each leaf defines `register_under(sub)`, never `register`.
2. Every leaf parser sets a callable `func(args) -> int`; a leaf without one raises
   RegisterContractError when the parser is built, so --help fails, not only the leaf.
3. register() is import-cheap: no file I/O, no assumptions, no workspace resolution (D03).
4. Names in docs/research/interfaces.json cli_commands are the contract (checked by tests).
5. CLI paths are type=Path; subprocess calls take list arguments; never shell=True (D13).
6. Help text is ASCII: the first module-docstring line and every help=/description= string.

The built-in `registry` subcommand lists what discovery found (exit 1 when any module failed).
It is registered by this module before discovery runs and is never attributed to a module, so it is
exempt from rule 1. Also the D01(b) mechanism: nested --help exits 0 at every level.

Build-list items: guide 9 cli.py, guide 13.12, R091 (every module reachable), R226 by design (this
module never calls Claude). Hard rules enforced: none of the 15 directly.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

__all__ = [
    "RegistryError",
    "SubcommandCollision",
    "RegisterContractError",
    "Discovered",
    "DiscoveryResult",
    "iter_module_names",
    "discover",
    "build_parser",
    "main",
    "register",
]

_BUILTIN_OWNER = __name__  # owner recorded for subcommands registered by cpa.cli itself


class RegistryError(RuntimeError):
    """Base for registry failures."""


class SubcommandCollision(RegistryError):
    """Two modules registered the same top-level subcommand name (or alias).

    The message names the name, the module that registered it first and the offending module.
    Raised regardless of `strict`; never recorded as a Discovered.error."""


class RegisterContractError(RegistryError):
    """A leaf parser has no callable `func`; the message names the parser path (e.g. 'mod cmd')."""


@dataclass(frozen=True)
class Discovered:
    """One module seen during discovery.

    module: dotted name, e.g. "cpa.workflows.charge_forecast".
    registered: top-level subcommand names it added (usually 0 or 1).
    error: import/registration failure text, None when clean."""

    module: str
    registered: tuple[str, ...]
    error: str | None


@dataclass(frozen=True)
class DiscoveryResult:
    """Everything discovery learned, one Discovered per module name in walk order."""

    modules: tuple[Discovered, ...]

    @property
    def failures(self) -> tuple[Discovered, ...]:
        """The modules whose import or register() failed."""
        return tuple(d for d in self.modules if d.error is not None)

    @property
    def subcommands(self) -> dict[str, str]:
        """Top-level subcommand name -> owning module (the built-in `registry` is not included)."""
        return {name: d.module for d in self.modules for name in d.registered}


def _default_package() -> ModuleType:
    import cpa

    return cpa


def iter_module_names(package: ModuleType) -> list[str]:
    """Dotted names of every module under `package`, found by a filesystem walk with no imports.

    Every *.py under Path(package.__path__[0]) is included except files under __pycache__, the
    package's own __init__.py, `<package>.cli` and `<package>.__main__`. A sub-directory's
    __init__.py yields the directory's dotted name; directories without __init__.py are ordinary
    path segments (they import as namespace packages), so no sibling __init__.py is load-bearing.
    Sorted by dotted name."""
    root = Path(list(package.__path__)[0])
    skip = {f"{package.__name__}.cli", f"{package.__name__}.__main__"}
    names: set[str] = set()
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if "__pycache__" in rel.parts:
            continue
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        name = ".".join([package.__name__, *parts])
        if name not in skip:
            names.add(name)
    return sorted(names)


class _GuardedSubparsers:
    """The object handed to each module's register(): a thin proxy over the real subparsers action.

    add_parser(name, aliases=...) checks `name` and every alias against every name registered so far
    (the built-in `registry`, earlier modules, and earlier calls by this module) and raises
    SubcommandCollision itself, before argparse sees the duplicate, so detection never depends on
    argparse's error text or version. Every name it adds is recorded, so a failed register() can be
    rolled back exactly. Any other attribute is forwarded to the real action."""

    def __init__(self, target: argparse._SubParsersAction, owners: dict[str, str], module: str) -> None:
        self._target = target
        self._owners = owners
        self._module = module
        self.added: list[str] = []  # every key added (names and aliases), in order
        self.primary: list[str] = []  # the first name of each add_parser call

    def add_parser(self, name: str, **kwargs):
        aliases = tuple(kwargs.get("aliases") or ())
        seen: set[str] = set()
        for n in (name, *aliases):
            if n in self._owners or n in self._target.choices or n in seen:
                first = self._owners.get(n, self._module if n in seen else "an earlier registration")
                raise SubcommandCollision(
                    f"subcommand {n!r} is registered by {first} and again by {self._module}; "
                    f"rename it to the module basename (cpa/cli.py rule 1)"
                )
            seen.add(n)
        parser = self._target.add_parser(name, **kwargs)
        for n in (name, *aliases):
            self._owners[n] = self._module
            self.added.append(n)
        self.primary.append(name)
        return parser

    def __getattr__(self, attr: str):
        return getattr(self._target, attr)


def _unregister(subparsers: argparse._SubParsersAction, owners: dict[str, str], names: list[str]) -> None:
    """Remove exactly `names` (added by a register() that then raised) from the parser and the owner map.

    `choices` is public; the help rows live in argparse's private `_choices_actions`, which is filtered
    only when present, so a future argparse without it still rolls back the dispatch table."""
    drop = set(names)
    for name in drop:
        subparsers.choices.pop(name, None)
        owners.pop(name, None)
    rows = getattr(subparsers, "_choices_actions", None)
    if isinstance(rows, list):
        rows[:] = [a for a in rows if getattr(a, "dest", None) not in drop]


def discover(
    subparsers: argparse._SubParsersAction, *, package: ModuleType | None = None, strict: bool = False
) -> DiscoveryResult:
    """Import every module from iter_module_names(package or cpa) and call its `register`.

    For each module with a callable module-level attribute literally named `register`, register() is
    called with a _GuardedSubparsers proxy, and the names it adds are attributed to the module (the
    first name of each add_parser call counts as a registered subcommand; aliases are owned but not
    listed). A name or alias already registered raises SubcommandCollision naming it, the module that
    registered it first and the offending module - always, regardless of `strict`, after rolling back
    the offending module's own additions. Any other import or register() exception is recorded in
    Discovered.error with the module's additions rolled back (strict=False) or re-raised (strict=True).
    Any other hook name (register_under) is ignored here."""
    package = package or _default_package()
    owners: dict[str, str] = {name: _BUILTIN_OWNER for name in subparsers.choices}
    found: list[Discovered] = []
    for name in iter_module_names(package):
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            if strict:
                raise
            found.append(Discovered(name, (), f"{type(exc).__name__}: {exc}"))
            continue
        hook = getattr(module, "register", None)
        if not callable(hook):
            found.append(Discovered(name, (), None))
            continue
        guarded = _GuardedSubparsers(subparsers, owners, name)
        try:
            hook(guarded)
        except SubcommandCollision:
            _unregister(subparsers, owners, guarded.added)
            raise
        except Exception as exc:
            _unregister(subparsers, owners, guarded.added)
            if strict:
                raise
            found.append(Discovered(name, (), f"{type(exc).__name__}: {exc}"))
            continue
        found.append(Discovered(name, tuple(guarded.primary), None))
    return DiscoveryResult(tuple(found))


def _subparser_actions(parser: argparse.ArgumentParser) -> list[argparse._SubParsersAction]:
    return [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]


def _check_leaves(parser: argparse.ArgumentParser, path: tuple[str, ...], seen: set[int]) -> None:
    """Raise RegisterContractError for any leaf under `parser` whose default func is not callable."""
    if id(parser) in seen:
        return
    seen.add(id(parser))
    actions = [a for a in _subparser_actions(parser) if a.choices]
    if not actions:
        if path and not callable(parser.get_default("func")):
            raise RegisterContractError(
                f"leaf parser {' '.join(path)!r} has no callable func; call set_defaults(func=...) (cpa/cli.py rule 2)"
            )
        return
    for action in actions:
        for name, child in action.choices.items():
            _check_leaves(child, (*path, name), seen)


def build_parser(
    *, package: ModuleType | None = None, strict: bool = False
) -> tuple[argparse.ArgumentParser, DiscoveryResult]:
    """Build the top-level parser `cpa <module> <command> [--flags]` and run discovery.

    Adds add_subparsers(dest='module', required=True), registers the built-in `registry`, runs
    discover(), then walks every parser reachable through the subparsers' choices and raises
    RegisterContractError for any leaf whose func is not callable. The leaf check runs on every
    build, not only on the invoked path, so a contract violation fails --help, registry and tests."""
    parser = argparse.ArgumentParser(
        prog="python -m cpa",
        description="CPA automation scripts. Run `python -m cpa registry` to list discovered modules.",
    )
    subparsers = parser.add_subparsers(dest="module", required=True, title="modules")
    register(subparsers)
    result = discover(subparsers, package=package, strict=strict)
    parser.set_defaults(cpa_discovery=result)
    _check_leaves(parser, (), set())
    return parser, result


def _warn_failures(result: DiscoveryResult) -> None:
    failures = result.failures
    if not failures:
        return
    detail = "; ".join(f"{d.module} ({d.error})" for d in failures)
    print(
        f"cpa: warning: {len(failures)} module(s) failed to import and are unavailable: {detail}. "
        "Run `python -m cpa registry` for details.",
        file=sys.stderr,
    )


def _utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("_", "-")
        reconfigure = getattr(stream, "reconfigure", None)
        if encoding in ("utf-8", "utf8") or reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError, AttributeError):
            pass


def main(argv: Sequence[str] | None = None, *, package: ModuleType | None = None, strict: bool = False) -> int:
    """CLI entry point: build the parser, warn once about failed modules, dispatch to args.func.

    stdout/stderr are reconfigured to UTF-8 first (no-op when already UTF-8). argparse's SystemExit
    propagates unchanged: --help exits 0, missing or bad arguments exit 2. Returns func's int exit
    code (None counts as 0)."""
    _utf8_streams()
    parser, result = build_parser(package=package, strict=strict)
    _warn_failures(result)
    args = parser.parse_args(None if argv is None else list(argv))
    from cpa.office import OfficeSafetyError

    try:
        code = args.func(args)
    except OfficeSafetyError as exc:
        print(f"Office safety: {exc}. Output approval is blocked; review the original file.", file=sys.stderr)
        return 2
    return 0 if code is None else int(code)


def _cli_registry(args: argparse.Namespace) -> int:
    """`registry`: list each discovered module, its subcommands and any import error."""
    result: DiscoveryResult = args.cpa_discovery
    if args.json:
        payload = {
            "builtin": ["registry"],
            "modules": [
                {"module": d.module, "registered": list(d.registered), "error": d.error} for d in result.modules
            ],
            "subcommands": result.subcommands,
            "failures": len(result.failures),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        rows = [("module", "subcommands", "status")]
        rows += [
            (d.module, ", ".join(d.registered) or "-", "ok" if d.error is None else f"import error: {d.error}")
            for d in result.modules
        ]
        widths = [max(len(r[i]) for r in rows) for i in range(2)]
        for mod, subs, status in rows:
            print(f"{mod.ljust(widths[0])}  {subs.ljust(widths[1])}  {status}")
        print(f"{len(result.modules)} module(s), {len(result.subcommands)} subcommand(s), "
              f"{len(result.failures)} failure(s); built-in: registry")
    return 1 if result.failures else 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the built-in `registry` subcommand (cpa.cli is otherwise skipped by discovery)."""
    p = subparsers.add_parser(
        "registry", help="List discovered modules, their subcommands and import errors (exit 1 on any failure)."
    )
    p.add_argument("--json", action="store_true", help="Emit JSON for the wave integrator.")
    p.set_defaults(func=_cli_registry)
