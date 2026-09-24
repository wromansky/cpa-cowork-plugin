"""Archive sweep and retention status (E2, Build List :366-368): move processed inbox files to
dated archive via `cpa.state.archive`, report retention status, never delete (R102, R157).

Cycle-tag recovery is not implemented in this module. Workday stays a stub until the cutover;
see `docs/OPEN_ITEMS.md` for acceptance gates.
"""

from __future__ import annotations

import argparse
from pathlib import Path


class ArchiveError(Exception):
    """Base for archive failures."""


def retention_status() -> str:
    """`retention.rules` (H-08-retention) is a Hopkins fact that ships null. Unconfirmed -> nothing
    enforced. Even once confirmed, this module still never deletes (enforcement is not implemented;
    archive only ever moves via `cpa.state.archive`)."""
    from cpa import config

    try:
        value = config.assumption("retention", "rules")
    except config.MissingAssumption:
        return "[UNCONFIRMED] retention.rules not set; nothing enforced, nothing deleted"
    return f"retention.rules set ({value!r}); enforcement not built -- archive never deletes"


def _processed_inbox_files(ws: Path) -> list[Path]:
    """Inbox files that were inputs of at least one `done` run and still sit under inbox/."""
    from cpa import state

    data = state.load_state()
    processed: set[Path] = set()
    for run in data["runs"].values():
        if run.get("status") != "done":
            continue
        for rel in run.get("input_hashes", {}):
            p = ws / Path(*rel.split("/"))
            try:
                p.relative_to(ws / "inbox")
            except ValueError:
                continue
            if p.is_file():
                processed.add(p)
    return sorted(processed)


def sweep() -> list[Path]:
    """Move every inbox file that a done run consumed to archive/<system>/<date>/ (R102: never
    deleted; the mover is `cpa.state.archive`, the single owner of the move, never `os.remove`,
    `Path.unlink` or `shutil.rmtree` here)."""
    from cpa import config, state

    ws = config.workspace()
    processed = _processed_inbox_files(ws)
    if not processed:
        return []
    return state.archive(processed)


# ---------------------------------------------------------------- CLI


def _cmd_sweep(a: argparse.Namespace) -> int:
    moved = sweep()
    for p in moved:
        print(p)
    return 0


def _cmd_retention(a: argparse.Namespace) -> int:
    print(retention_status())
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `archive sweep|retention`. Import-cheap (D03)."""
    top = subparsers.add_parser("archive", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    p = sub.add_parser("sweep", help="Move processed inbox files to dated archive (never deletes).")
    p.set_defaults(func=_cmd_sweep)

    p = sub.add_parser("retention", help="Print retention status (E2; never deletes either way).")
    p.set_defaults(func=_cmd_retention)
