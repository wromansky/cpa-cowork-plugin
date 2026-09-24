"""Workspace init and period rollover (B21, guide:656, guide:847, Build List:245-249).

`init` materialises the Build List 0.1 tree under the workspace root and writes the workspace
`.gitignore` from `cpa.WORKSPACE_GITIGNORE`; the `.gitignore` write is the one stated exception to
"never overwrite" (it is a generated file, rewritten to match the constant every time so a stale or
hand-edited copy self-heals). `init` seeds no reference file: `cpa.config.reference_file` and
`cpa.config.template_map` already fall back to the repository copy when the workspace has none, so
there is nothing this part needs to copy in (D03).

`run --fymm` makes this fiscal month's `outbox/<workflow>/<fymm>/` and `staging/<workflow>/<fymm>/`
folders for every name in `MONTHLY_WORKFLOW_DIRS`, then copies last month's `bog` and `fc` outputs
into `templates/<workflow>/` when a same-named file is not already there (copy only, never overwrite).
Nothing here ever deletes, renames or overwrites an existing file (R077): a prior period's folders and
files are left exactly as found.

This module owns `rollover init` and `rollover run --fymm` (B21), including advancing the fiscal-
period label: `run` records `fymm` as `current_fymm` in the dashboard registry (`logs/cycles.json`,
via `cpa.workflows.dashboard.load_registry`/`save_registry`), never in `assumptions.yaml` (D03
forbids automation editing it; D30 makes the redirect explicit). Registering the month's committee
deadlines (B9, real dates from a calendar) stays out of scope here: those dates are not knowable from
a fymm alone and are registered separately, by `dashboard register-cycle` (called by a human or the
U24 skill once a real meeting date is known).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from cpa import config, fsutil, manifest, periods

EXIT_OK = 0
EXIT_STOPPED = 1
EXIT_ARGPARSE = 2

# FIXTURE -- confirm against her actual workflow folder names once U10 (forecast), U15 (bog/fc) and
# U20/U22 (budget) land; Build List :91, :98, :186, :218 name these as FYMM-keyed outbox folders today.
MONTHLY_WORKFLOW_DIRS: tuple[str, ...] = ("bog", "fc", "forecast", "budget")

# Build List :24: "templates/ holds ... last month's BOG and FC decks and workbooks".
COPY_FORWARD_DIRS: tuple[str, ...] = ("bog", "fc")

_LOCK_PREFIX = "~$"  # Excel lock files (cpa.WORKSPACE_GITIGNORE)

__all__ = [
    "RolloverError", "InitResult", "RolloverResult", "init", "run", "previous_fymm", "register",
]


class RolloverError(RuntimeError):
    """Rollover cannot proceed; the message names the missing thing and the fix."""


@dataclass(frozen=True)
class InitResult:
    """What `init` did. `created`/`existing` are workspace-relative POSIX dir strings, sorted."""

    path: str
    created: tuple[str, ...]
    existing: tuple[str, ...]
    gitignore_written: bool

    def to_json(self) -> dict:
        return {
            "path": self.path, "created": list(self.created), "existing": list(self.existing),
            "gitignore_written": self.gitignore_written,
        }


@dataclass(frozen=True)
class RolloverResult:
    """What `run` did for one fymm. Every path a workspace-relative POSIX string, sorted."""

    fymm: str
    sap_label: str
    previous_fymm: str
    created: tuple[str, ...] = field(default_factory=tuple)
    copied: tuple[str, ...] = field(default_factory=tuple)
    kept_existing: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict:
        return {
            "fymm": self.fymm, "sap_label": self.sap_label, "previous_fymm": self.previous_fymm,
            "created": list(self.created), "copied": list(self.copied),
            "kept_existing": list(self.kept_existing),
        }


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _mkdir(root: Path, parts: tuple[str, ...], created: list[str], existing: list[str]) -> None:
    target = root.joinpath(*parts)
    was_there = target.is_dir()
    target.mkdir(parents=True, exist_ok=True)
    (existing if was_there else created).append(target.relative_to(root).as_posix())


def init(path: Path | str | None = None) -> InitResult:
    """Materialise the Build List 0.1 tree at `path` (default `config.workspace()`) and write `.gitignore`."""
    root = Path(path) if path is not None else config.workspace()
    root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    existing: list[str] = []
    for top in cpa_top():
        _mkdir(root, (top,), created, existing)
    for system in cpa_inbox_systems():
        _mkdir(root, ("inbox", system), created, existing)
    for parts in cpa_subdirs():
        _mkdir(root, parts, created, existing)
    gitignore_text = "\n".join(cpa_gitignore()) + "\n"
    gitignore_path = root / ".gitignore"
    fsutil.atomic_write(gitignore_path, lambda tmp: tmp.write_text(gitignore_text, encoding="utf-8", newline="\n"))
    return InitResult(
        path=str(root), created=tuple(sorted(created)), existing=tuple(sorted(existing)),
        gitignore_written=True,
    )


# Indirection so this module never hardcodes cpa's constants twice; kept as tiny functions for testability.
def cpa_top() -> tuple[str, ...]:
    import cpa

    return cpa.WORKSPACE_TOP


def cpa_inbox_systems() -> tuple[str, ...]:
    import cpa

    return cpa.INBOX_SYSTEMS


def cpa_subdirs() -> tuple[tuple[str, ...], ...]:
    import cpa

    return cpa.WORKSPACE_SUBDIRS


def cpa_gitignore() -> tuple[str, ...]:
    import cpa

    return cpa.WORKSPACE_GITIGNORE


def previous_fymm(value: str) -> str:
    """The fymm of the calendar month before `value`'s calendar month."""
    year, month = periods.calendar_month(value)
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    return periods.fymm(date(prev_year, prev_month, 1))


def _assert_workspace_exists(root: Path) -> None:
    missing = [top for top in cpa_top() if not (root / top).is_dir()]
    if missing:
        raise RolloverError(
            f"{root} is missing {', '.join(missing)}; run `python -m cpa rollover init` first"
        )


def _copy_forward_one(source_dir: Path, target_dir: Path, root: Path, copied: list[str], kept: list[str]) -> None:
    if not source_dir.is_dir():
        return
    for src in sorted(source_dir.iterdir()):
        if not src.is_file() or src.name.startswith(_LOCK_PREFIX) or manifest.is_sidecar(src):
            continue
        for candidate in (src, manifest.sidecar(src)):
            if not candidate.is_file():
                continue
            dest = target_dir / candidate.name
            if dest.exists():
                kept.append(_rel(root, dest))
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = candidate.read_bytes()
            fsutil.atomic_write(dest, lambda tmp, data=data: tmp.write_bytes(data))
            copied.append(_rel(root, dest))


def _advance_period(ws: Path, fymm: str, sap_label: str) -> None:
    """Record `fymm` as the current fiscal period in the dashboard registry (`logs/cycles.json`),
    never in `assumptions.yaml` (D03/D30). `current_fymm` always moves to `fymm`; `periods[fymm]` is
    written once, the first time this fymm is rolled, so `rolled_at` stays at its first value and a
    rerun of the same fymm is a true no-op here, matching the copy-forward and folder steps."""
    from cpa.workflows import dashboard

    registry = dashboard.load_registry(ws)
    registry["current_fymm"] = fymm
    periods_seen = registry.setdefault("periods", {})
    if fymm not in periods_seen:
        periods_seen[fymm] = {"sap_label": sap_label, "rolled_at": manifest.utc_now_iso()}
    dashboard.save_registry(registry, ws)


def run(fymm: str, *, root: Path | None = None) -> RolloverResult:
    """Roll the workspace into fiscal month `fymm`: month folders, copy-forward, then advance the
    fiscal period label in the dashboard registry. Idempotent, never deletes."""
    periods.parse_fymm(fymm)  # ValueError on a bad token, before anything is touched
    ws = root if root is not None else config.workspace()
    _assert_workspace_exists(ws)

    created: list[str] = []
    existing: list[str] = []
    for name in MONTHLY_WORKFLOW_DIRS:
        _mkdir(ws, ("outbox", name, fymm), created, existing)
        _mkdir(ws, ("staging", name, fymm), created, existing)

    prev = previous_fymm(fymm)
    copied: list[str] = []
    kept: list[str] = []
    for name in COPY_FORWARD_DIRS:
        _copy_forward_one(ws / "outbox" / name / prev, ws / "templates" / name, ws, copied, kept)

    sap_label = periods.sap_label(fymm)
    _advance_period(ws, fymm, sap_label)

    return RolloverResult(
        fymm=fymm, sap_label=sap_label, previous_fymm=prev,
        created=tuple(sorted(created)), copied=tuple(sorted(copied)), kept_existing=tuple(sorted(kept)),
    )


def _cmd_init(args: argparse.Namespace) -> int:
    result = init(args.path)
    if args.json:
        print(json.dumps(result.to_json()))
    else:
        print(f"workspace ready at {result.path}: {len(result.created)} folder(s) created, "
              f"{len(result.existing)} already there")
    return EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        result = run(args.fymm, root=args.root)
    except (ValueError, RolloverError, config.ConfigError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return EXIT_STOPPED
    if args.json:
        print(json.dumps(result.to_json()))
    else:
        print(f"{result.fymm} ({result.sap_label}): {len(result.created)} folder(s) created, "
              f"{len(result.copied)} template(s) copied forward from {result.previous_fymm}")
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `rollover init|run`. Import-cheap: no file access here (D03)."""
    top = subparsers.add_parser("rollover", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    p = sub.add_parser(
        "init", help="Create the workspace tree (Build List 0.1) and write its .gitignore.",
        description="Materialise inbox/<system>, staging/, outbox/, archive/, reference/, templates/, "
                    "requests/, logs/ (and reference/proposed/, logs/runs/) under the workspace root, "
                    "and write .gitignore from cpa.WORKSPACE_GITIGNORE. Exit 0 always (idempotent).")
    p.add_argument("--path", type=Path, default=None,
                   help="Workspace root (default: cpa.config.workspace()'s resolution).")
    p.add_argument("--json", action="store_true", help="Print the result as one JSON object.")
    p.set_defaults(func=_cmd_init)

    r = sub.add_parser(
        "run", help="Create this fiscal month's folders and copy last month's bog/fc outputs forward.",
        description="Create outbox/<workflow>/<FYMM>/ and staging/<workflow>/<FYMM>/ for every monthly "
                    "workflow, then copy prior-period bog/fc outputs into templates/<workflow>/ when "
                    "absent there. Never deletes or overwrites. Exit 0 done, 1 stopped.")
    r.add_argument("--fymm", required=True, help="Fiscal period, yymm (cpa.periods.fymm format).")
    r.add_argument("--root", type=Path, default=None, help="Workspace root (default: cpa.config.workspace()).")
    r.add_argument("--json", action="store_true", help="Print the result as one JSON object.")
    r.set_defaults(func=_cmd_run)
