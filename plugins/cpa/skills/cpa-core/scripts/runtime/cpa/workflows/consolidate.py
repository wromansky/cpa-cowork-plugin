"""File consolidation (E1, Build List :361-364): inventory scattered locations, propose one master
tree under the naming convention `<Workflow>_<Scope>_<FYMM>_v<N>.xlsx`, move only on her approved
plan, always leave a pointer file at each old location (R081, R158).

`inventory` and `plan` write only under `<workspace>/outbox/consolidate/<stamp>/` and move nothing.
`apply` refuses (`PlanNotApproved`) unless the plan file's top-level `"approved"` key is exactly
`True` -- a value only a human edits into the file, never this code. Consult the real code of
dependencies (`cpa.manifest`, `cpa.fsutil`), not the U23 hygiene plan's stale symbol names.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

SKIP_NAMES = {"Thumbs.db", "desktop.ini"}
SKIP_PREFIXES = ("~$",)
# Build List E1 naming convention: Workflow_Scope_FYMM_vN.ext (FYMM is D02's 4-digit yymm, e.g. "2703").
NAMING_RE = re.compile(r"^(?P<workflow>[A-Za-z0-9]+)_(?P<scope>[A-Za-z0-9]+)_(?P<fymm>\d{4})_v(?P<version>\d+)(?P<ext>\.[A-Za-z0-9]+)$")
# A trailing version-ish token stripped to compute a duplicate/version "chain key": " v2", " (1)", " - Copy".
_CHAIN_TOKEN_RE = re.compile(r"(?:[ _]v(?:ersion)?\d+|\s*\(\d+\)|\s*-\s*copy(?:\s*\(\d+\))?)$", re.IGNORECASE)
_VERSION_RE = re.compile(r"v(?:ersion)?(\d+)$", re.IGNORECASE)

EXIT_OK = 0
EXIT_ISSUES = 1


class ConsolidateError(Exception):
    """Base for consolidate failures."""


class PlanNotApproved(ConsolidateError):
    """`apply` was called on a plan whose `approved` field is not exactly True. Names the plan file."""


def _skip(p: Path) -> bool:
    from cpa import manifest

    if manifest.is_sidecar(p):
        return True
    if p.name in SKIP_NAMES:
        return True
    return any(p.name.startswith(pref) for pref in SKIP_PREFIXES)


def _chain_key(stem: str) -> tuple[str, int]:
    """Casefold name with a trailing version/duplicate token stripped, and that token's version number
    (0 when the stripped part named no number, e.g. plain " - Copy" or " (1)" without a leading v)."""
    m = _CHAIN_TOKEN_RE.search(stem)
    if not m:
        return stem.casefold(), 0
    token = m.group(0)
    base = stem[: m.start()].casefold()
    vm = _VERSION_RE.search(token.strip())
    version = int(vm.group(1)) if vm else 0
    return base, version


@dataclass
class _Item:
    path: Path
    sha256: str
    size: int
    mtime: float
    chain_key: str
    version: int


def _walk(source: Path) -> list[Path]:
    if not source.is_dir():
        return []
    return sorted(p for p in source.rglob("*") if p.is_file() and not _skip(p))


def inventory(sources: list[Path], *, out: Path | None = None) -> Path:
    """Hash every file under each source (skipping locks, sidecars, system files); write the raw
    listing as JSON under outbox/consolidate/<stamp>/inventory.json (or `out`). Touches nothing else."""
    from cpa import config, manifest

    items: list[dict[str, Any]] = []
    for source in sources:
        for p in _walk(Path(source)):
            try:
                digest = manifest.sha256_of(p)
            except OSError:
                items.append({"path": str(p), "status": "unavailable"})
                continue
            stat = p.stat()
            key, version = _chain_key(p.stem)
            m = NAMING_RE.match(p.name)
            if m:
                version = max(version, int(m.group("version")))
            items.append({
                "path": str(p), "name": p.name, "status": "ok", "sha256": digest, "size": stat.st_size,
                "mtime": stat.st_mtime, "chain_key": key, "version": version,
            })
    target = Path(out) if out is not None else config.workspace() / "outbox" / "consolidate" / _stamp() / "inventory.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {"sources": [str(s) for s in sources], "items": items}
    from cpa import fsutil

    fsutil.atomic_write(target, lambda tmp: tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n"))
    return target


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def plan(inventory_path: Path, *, default_dest: str = "templates", out: Path | None = None) -> Path:
    """Group inventory items by sha256 (exact duplicate) and chain_key (version chain); for each chain
    the highest version (tie: newest mtime) is `move_master`, the rest `archive_copy`. Writes a JSON
    plan with `"approved": false` under outbox/consolidate/<stamp>/move_plan.json (or `out`). Moves
    nothing -- `apply` is the only function that moves a file."""
    from cpa import config

    data = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    ok_items = [i for i in data["items"] if i.get("status") == "ok"]
    by_chain: dict[str, list[dict]] = {}
    for item in ok_items:
        by_chain.setdefault(item["chain_key"], []).append(item)
    stamp = _stamp()
    rows: list[dict[str, Any]] = []
    for chain_key, group in sorted(by_chain.items()):
        group.sort(key=lambda i: (i["version"], i["mtime"]), reverse=True)
        master = group[0]
        note = "" if NAMING_RE.match(master["name"]) else "does not match the naming convention Workflow_Scope_FYMM_vN"
        rows.append({
            "source": master["path"], "action": "move_master", "sha256": master["sha256"],
            "destination": str(Path(default_dest) / master["name"]), "note": note,
        })
        for dup in group[1:]:
            rows.append({
                "source": dup["path"], "action": "archive_copy", "sha256": dup["sha256"],
                "destination": str(Path("archive") / "consolidate" / date.today().isoformat() / dup["name"]),
                "note": f"duplicate/older version of {master['name']}",
            })
    target = Path(out) if out is not None else config.workspace() / "outbox" / "consolidate" / stamp / "move_plan.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"approved": False, "inventory": str(inventory_path), "rows": rows}
    from cpa import fsutil

    fsutil.atomic_write(target, lambda tmp: tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n"))
    return target


def _pointer_text(dest: Path) -> str:
    from cpa import manifest

    return (f"MOVED by cpa consolidate apply on {manifest.utc_now_iso()}\n"
            f"This file now lives at: {dest}\n"
            "This pointer file is left in place per Build List E1; it is never treated as the artifact.\n")


def apply(plan_path: Path) -> list[dict]:
    """Move every row of an approved plan (`approved` must be exactly True) and always leave a
    pointer file at the old location (R081, R158). A row whose source no longer exists is skipped
    (already applied) rather than failing the whole run."""
    from cpa import config, fsutil, manifest

    data = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if data.get("approved") is not True:
        raise PlanNotApproved(f"{plan_path}: not approved (set \"approved\": true after review to apply it)")
    ws = config.workspace()
    moved: list[dict] = []
    for row in data["rows"]:
        source = Path(row["source"])
        if not source.is_file():
            moved.append({**row, "skipped": "source not found (already applied?)"})
            continue
        dest = ws / row["destination"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            n = 2
            while (dest.with_name(f"{dest.stem}_{n}{dest.suffix}")).exists():
                n += 1
            dest = dest.with_name(f"{dest.stem}_{n}{dest.suffix}")
        shutil.move(str(source), str(dest))
        # row_count is not meaningful for an arbitrary consolidated artifact (it may not even be a
        # workbook or CSV); 0 records that the manifest exists per policy, not a data-row count.
        manifest.write(dest, "consolidate", "E1 consolidation", "", date.today().isoformat(), row_count=0)
        pointer = source.with_name(fsutil.safe_filename(source.name + ".pointer.txt"))
        fsutil.atomic_write(pointer, lambda tmp, d=dest: tmp.write_text(_pointer_text(d), encoding="utf-8", newline="\n"))
        moved.append({**row, "destination": str(dest), "pointer": str(pointer)})
    return moved


# ---------------------------------------------------------------- CLI


def _cmd_inventory(a: argparse.Namespace) -> int:
    path = inventory([Path(s) for s in a.source])
    print(path)
    return EXIT_OK


def _cmd_plan(a: argparse.Namespace) -> int:
    path = plan(a.inventory, default_dest=a.default_dest)
    print(path)
    return EXIT_OK


def _cmd_apply(a: argparse.Namespace) -> int:
    try:
        rows = apply(a.plan)
    except PlanNotApproved as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return EXIT_ISSUES
    for row in rows:
        print(f"{row['action']}\t{row['source']}\t{row.get('skipped') or row['destination']}")
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `consolidate inventory|plan|apply`. Import-cheap (D03)."""
    top = subparsers.add_parser("consolidate", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    p = sub.add_parser("inventory", help="Hash and list files under one or more source folders.")
    p.add_argument("source", nargs="+")
    p.set_defaults(func=_cmd_inventory)

    p = sub.add_parser("plan", help="Propose a move plan from an inventory (writes approved: false).")
    p.add_argument("inventory", type=Path)
    p.add_argument("--default-dest", default="templates", dest="default_dest")
    p.set_defaults(func=_cmd_plan)

    p = sub.add_parser("apply", help="Move an approved plan's rows and leave a pointer at each old location.")
    p.add_argument("--plan", required=True, dest="plan", type=Path)
    p.set_defaults(func=_cmd_apply)
