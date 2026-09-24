"""cpa.sources: source adapters (C8, C13, A-series validators) behind one registry.

`python -m cpa sources <source> validate <file>` and friends. This __init__.py owns the top-level `sources`
subcommand (cpa/cli.py rule 1: a package registers its own name once). It finds every leaf module on disk
(cpa/sources/*.py except base) and calls the leaf's register_under(sub), so a new adapter module needs no edit
here; see cpa/sources/base.py for how a module registers its adapters and its CLI.

Consumers never import a leaf to parse a file: `from cpa import sources; sources.get("sap.salary").load(p)`.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys

from cpa.sources.base import (
    SchemaMismatch,
    SourceAdapter,
    SourceError,
    UnknownSource,
    Validation,
    adapter_class,
    get,
    leaf_errors,
    leaf_modules,
    load_leaves,
    names,
)

__all__ = [
    "register", "get", "names", "adapter_class", "leaf_modules", "load_leaves", "leaf_errors",
    "SourceAdapter", "Validation", "SourceError", "UnknownSource", "SchemaMismatch",
]


def _broken_leaf(sub: argparse._SubParsersAction, leaf: str, error: str) -> None:
    """A leaf that failed to import still appears, and says why, instead of vanishing from --help."""
    p = sub.add_parser(leaf, help=f"(unavailable: the {leaf} adapter failed to import)")

    def _func(args: argparse.Namespace) -> int:
        print(f"cpa sources: the {leaf} adapter failed to import: {error}", file=sys.stderr)
        return 1

    p.add_argument("rest", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    p.set_defaults(func=_func)


def _cmd_list(args: argparse.Namespace) -> int:
    errors = load_leaves()
    rows = []
    for name in names():
        cls = adapter_class(name)
        rows.append({"name": name, "source": cls.SOURCE, "dataset": cls.DATASET, "prefix": cls.PREFIX,
                     "implemented": bool(cls.IMPLEMENTED), "fixture_from": cls.FIXTURE_FROM})
    if args.json:
        print(json.dumps({"adapters": rows, "leaf_errors": errors}, indent=2, ensure_ascii=False))
    else:
        for r in rows:
            flag = "" if r["implemented"] else "  (not implemented)"
            print(f"{r['name']:<32} prefix {r['prefix'] or '-'}{flag}")
        for leaf, err in sorted(errors.items()):
            print(f"{leaf}: import error: {err}")
    return 1 if errors else 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `sources` and nest each leaf's commands. Import-cheap: leaves import only stdlib and base at
    module level; no file other than the leaf modules themselves is read."""
    top = subparsers.add_parser("sources", help="Validate and read landed source exports (SAP, Epic, ...).")
    sub = top.add_subparsers(dest="source", required=True, title="sources")
    for leaf in leaf_modules():
        try:
            module = importlib.import_module(f"cpa.sources.{leaf}")
        except Exception as exc:  # shown as an unavailable leaf and by `sources list`; never silent
            _broken_leaf(sub, leaf, f"{type(exc).__name__}: {exc}")
            continue
        hook = getattr(module, "register_under", None)
        if callable(hook):
            hook(sub)
    p = sub.add_parser("list", help="List registered adapters, their file prefixes and leaf import errors.")
    p.add_argument("--json", action="store_true", help="Print JSON.")
    p.set_defaults(func=_cmd_list)
