"""Sidecar manifests for every landed or produced file, and figure lineage from export to slide.

Build-list items: C12 manifest and lineage writer; the A-series manifest contract
(source, report, filters, as_of, exported_at, row_count). Hard rules enforced: 7 (every figure
carries its source system and as-of date: the manifest is where that provenance lives), 11 (row
counts for workbooks stream through cpa.bigxlsx, never a full load).

A manifest is `<file>.manifest.json` beside the file. Paths stored inside it are workspace-relative
POSIX strings when the file sits in the workspace, absolute otherwise, so a manifest survives the
workspace moving between machines.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SIDECAR_SUFFIX = ".manifest.json"
REQUIRED_KEYS = ("source", "report", "filters", "as_of", "exported_at", "row_count", "sha256")
_WORKBOOK_SUFFIXES = {".xlsx", ".xlsm", ".xlsb"}

__all__ = [
    "ManifestError", "MissingManifest", "BrokenLineage", "sidecar", "is_sidecar", "exists", "sha256_of",
    "write", "read", "update", "add_figure", "lineage", "to_rel", "from_rel", "register",
]


class ManifestError(Exception):
    """Base for manifest failures."""


class MissingManifest(ManifestError, FileNotFoundError):
    """The file has no sidecar manifest."""


class BrokenLineage(ManifestError):
    """A figure's chain cannot be followed back to its source export."""


def sidecar(path: Path | str) -> Path:
    """The manifest path for a file: report.xlsx -> report.xlsx.manifest.json."""
    p = Path(path)
    return p.with_name(p.name + SIDECAR_SUFFIX)


def is_sidecar(path: Path | str) -> bool:
    return Path(path).name.endswith(SIDECAR_SUFFIX)


def exists(path: Path | str) -> bool:
    return sidecar(path).is_file()


def sha256_of(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def utc_now_iso() -> str:
    """Current UTC time as ISO 8601 with a Z suffix (a value, never a filename)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _workspace() -> Path | None:
    from cpa.config import WorkspaceNotFound, workspace

    try:
        return workspace()
    except WorkspaceNotFound:
        return None


def to_rel(path: Path | str) -> str:
    """Workspace-relative POSIX string when inside the workspace, else the absolute POSIX path."""
    p = Path(path)
    ws = _workspace()
    if ws is not None:
        try:
            return p.resolve().relative_to(ws.resolve()).as_posix()
        except ValueError:
            pass
    return p.resolve().as_posix()


def from_rel(value: str) -> Path:
    """Inverse of to_rel: a stored path back to a filesystem Path."""
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    ws = _workspace()
    base = ws if ws is not None else Path.cwd()
    return base.joinpath(*value.split("/"))


def _count_rows(path: Path) -> int | None:
    """Data rows (header excluded) for workbooks and CSV; None when the type is unknown."""
    suffix = path.suffix.lower()
    if suffix in _WORKBOOK_SUFFIXES:
        from cpa import bigxlsx

        return max(bigxlsx.row_count(path, None) - 1, 0)
    if suffix in {".csv", ".tsv", ".txt"}:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return max(sum(1 for line in fh if line.strip()) - 1, 0)
    return None


def _save(path: Path, data: dict) -> Path:
    from cpa import fsutil

    target = sidecar(path)
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    fsutil.atomic_write(target, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))
    return target


def write(
    path: Path | str,
    source: str,
    report: str,
    filters: str,
    as_of: str,
    *,
    row_count: int | None = None,
    inputs: list[Path | str] | tuple = (),
    **extra: Any,
) -> Path:
    """Write the sidecar manifest for a file and return its path.

    as_of is an ISO date (YYYY-MM-DD). row_count is counted for workbooks (streamed) and CSV when not
    given; any other file type must pass it. `inputs` lists the files this one was built from."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"cannot write a manifest for {p}: the file does not exist")
    try:
        date.fromisoformat(as_of)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"as_of must be an ISO date YYYY-MM-DD, got {as_of!r}") from exc
    if row_count is None:
        row_count = _count_rows(p)
        if row_count is None:
            raise ValueError(f"row_count must be given for {p.suffix or 'this'} files; it cannot be counted")
    data = {
        "source": source,
        "report": report,
        "filters": filters,
        "as_of": as_of,
        "exported_at": utc_now_iso(),
        "row_count": row_count,
        "sha256": sha256_of(p),
        "path": to_rel(p),
        "inputs": [to_rel(i) for i in inputs],
        "figures": {},
        **extra,
    }
    return _save(p, data)


def read(path: Path | str) -> dict:
    side = sidecar(path)
    try:
        return json.loads(side.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise MissingManifest(f"{Path(path).name} has no manifest ({side.name}); write one with `python -m cpa manifest write`") from exc


def update(path: Path | str, **changes: Any) -> Path:
    """Merge changes into an existing manifest and refresh its sha256 to the file's current bytes."""
    data = read(path)
    data.update(changes)
    data["sha256"] = sha256_of(path)
    return _save(Path(path), data)


def add_figure(
    artifact: Path | str,
    figure_id: str,
    value: Any,
    source_file: Path | str,
    source_ref: str,
    *,
    cell: str | None = None,
    status: str | None = None,
    period: str | None = None,
) -> Path:
    """Record where one reported figure in `artifact` came from (file and cell, row, or range).

    Optional (U07, additive): `cell` is where the figure sits in the artifact ("Sheet!B5"), `status` one of
    actual/budget/forecast/projected/restated, `period` its period label. cpa.verify reads all three."""
    data = read(artifact)
    record: dict[str, Any] = {"value": value, "source_file": to_rel(source_file), "ref": source_ref}
    for key, extra in (("cell", cell), ("status", status), ("period", period)):
        if extra is not None:
            record[key] = extra
    data.setdefault("figures", {})[figure_id] = record
    src = to_rel(source_file)
    if src not in data.setdefault("inputs", []):
        data["inputs"].append(src)
    return _save(Path(artifact), data)


def lineage(artifact: Path | str, figure_id: str) -> list[dict]:
    """Follow one figure from the artifact back to the raw export: one entry per file, newest first."""
    chain: list[dict] = []
    current = Path(artifact)
    seen: set[str] = set()
    while True:
        rel = to_rel(current)
        if rel in seen:
            raise BrokenLineage(f"figure {figure_id!r}: lineage loops at {rel}")
        seen.add(rel)
        try:
            data = read(current)
        except MissingManifest as exc:
            raise BrokenLineage(f"figure {figure_id!r}: {rel} has no manifest, so the chain stops there") from exc
        fig = (data.get("figures") or {}).get(figure_id)
        entry = {"path": rel, "source": data.get("source"), "report": data.get("report"), "as_of": data.get("as_of")}
        if fig is None:
            if not chain:
                raise BrokenLineage(f"figure {figure_id!r} is not recorded in {rel}")
            chain.append({**entry, "ref": None})
            return chain
        chain.append({**entry, "ref": fig.get("ref"), "value": fig.get("value")})
        current = from_rel(fig["source_file"])


# ---------------------------------------------------------------- CLI


def _cmd_write(a: argparse.Namespace) -> int:
    print(write(a.file, a.source, a.report, a.filters, a.as_of, row_count=a.row_count, inputs=a.input or ()))
    return 0


def _cmd_show(a: argparse.Namespace) -> int:
    print(json.dumps(read(a.file), indent=2, ensure_ascii=False))
    return 0


def _cmd_lineage(a: argparse.Namespace) -> int:
    for hop in lineage(a.file, a.figure):
        print(f"{hop['path']}\t{hop.get('ref') or '-'}\t{hop.get('source')}\t{hop.get('as_of')}")
    return 0


def _cmd_add_figure(a: argparse.Namespace) -> int:
    print(add_figure(a.file, a.figure, a.value, a.source_file, a.ref, cell=a.cell, status=a.status, period=a.period))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `manifest write|show|lineage|add-figure`. Import-cheap."""
    top = subparsers.add_parser("manifest", help="Sidecar manifests and figure lineage.")
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    p = sub.add_parser("write", help="Write the sidecar manifest for a landed or produced file.")
    p.add_argument("file")
    p.add_argument("--source", required=True, help="System, e.g. tableau, or 'derived' for built artifacts.")
    p.add_argument("--report", required=True)
    p.add_argument("--filters", default="")
    p.add_argument("--as-of", required=True, dest="as_of", help="YYYY-MM-DD")
    p.add_argument("--row-count", type=int, default=None, dest="row_count")
    p.add_argument("--input", action="append", help="A file this one was built from (repeatable).")
    p.set_defaults(func=_cmd_write)
    p = sub.add_parser("show", help="Print a file's manifest as JSON.")
    p.add_argument("file")
    p.set_defaults(func=_cmd_show)
    p = sub.add_parser("lineage", help="Trace one figure back to its source export.")
    p.add_argument("file")
    p.add_argument("figure")
    p.set_defaults(func=_cmd_lineage)
    p = sub.add_parser("add-figure", help="Record where one reported figure came from.")
    p.add_argument("file")
    p.add_argument("figure")
    p.add_argument("value")
    p.add_argument("source_file")
    p.add_argument("ref")
    p.add_argument("--cell", default=None, help="Where the figure sits in this file, e.g. P&L!C5.")
    p.add_argument("--status", default=None, help="actual, budget, forecast, projected or restated.")
    p.add_argument("--period", default=None, help="Period label, e.g. FY27 M03.")
    p.set_defaults(func=_cmd_add_figure)
