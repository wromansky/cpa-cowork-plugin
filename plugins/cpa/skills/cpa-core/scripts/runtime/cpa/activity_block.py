"""The M2 activity metrics block (C2): wRVUs, cFTE, Collections (gross or net, always labelled), Charges.

Build-list items: C2 M2 activity metrics block (guide 5 cpa-activity-block, guide 9 activity_block.py, guide
13.9). Hard rules enforced: a missing narrative-relevant metric is flagged visibly, never silently omitted,
never estimated (hard rule "never omitted / never estimated", R008/R058/R099/R135/R164); gross vs net
collections are always labelled (R006/R162/R181); every present figure carries period, status (one of
`verify.FIGURE_STATUSES`), source system and as-of (R007/R097/R163).

The block's marker text and search window are owned once by `cpa.verify` (DECISIONS D20): `M2_TITLE`,
`M2_METRICS`, `M2_MISSING_MARKER`, `M2_SEARCH_ROWS`. This module imports them, never copies them, so a block
`build()` writes always passes `verify.m2_check`. Layout, the narrative_relevant contract and the
`brand.flag_yellow` fill (D08's precedent, extended here from slides to workbook cells) are DECISIONS D24.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cpa import verify

__all__ = [
    "METRICS", "COLLECTION_BASES", "HEADERS", "BLOCK_ROWS", "BLOCK_COLS",
    "ActivityBlockError", "UnknownMetric", "DuplicateMetric", "InvalidMetric", "TabNotFound",
    "UnsupportedWorkbook", "BlockAreaOccupied", "DuplicateBlock",
    "Flag", "canonical_metric", "build", "register",
]

METRICS: tuple[str, ...] = verify.M2_METRICS  # ("wRVUs", "cFTE", "Collections", "Charges"), D20
COLLECTION_BASES: tuple[str, ...] = ("gross", "net")  # R006/R162/R181: gross vs net always labelled
HEADERS: tuple[str, ...] = ("Metric", "Value", "Period", "Status", "Source", "As of")
BLOCK_COLS: int = len(HEADERS)  # 6
BLOCK_ROWS: int = 2 + len(METRICS)  # title + header + one row per metric


class ActivityBlockError(ValueError):
    """Base for every activity-block failure. Nothing is written to the workbook when this is raised."""


class UnknownMetric(ActivityBlockError):
    """A metrics or narrative_relevant key is not one of METRICS (or a valid Collections basis variant)."""


class DuplicateMetric(ActivityBlockError):
    """Two metrics keys resolve to the same base metric (for example two Collections entries)."""


class InvalidMetric(ActivityBlockError):
    """A supplied metric entry has a missing field, an invalid status, a bad as_of, or an unlabelled Collections
    value. Names the metric and the field."""


class TabNotFound(ActivityBlockError):
    """`tab` is not a sheet in the workbook. This module never creates one: build() runs after the artifact's
    own sheet exists (guide:538)."""


class UnsupportedWorkbook(ActivityBlockError):
    """Only .xlsx is written here (the same macro-safety reasoning as cpa.verify D21)."""


class BlockAreaOccupied(ActivityBlockError):
    """The computed block area already holds content that is not a prior M2 block at the same anchor."""


class DuplicateBlock(ActivityBlockError):
    """The tab already carries an M2 title somewhere other than the target anchor."""


@dataclass
class Flag:
    """One metric that was not supplied: what was written, whether it matters to this narrative, and where."""

    metric: str
    label: str
    tab: str
    cell: str
    narrative_relevant: bool
    why: str
    source: str
    text: str

    def to_json(self) -> dict:
        return {"metric": self.metric, "label": self.label, "tab": self.tab, "cell": self.cell,
                "narrative_relevant": self.narrative_relevant, "why": self.why, "source": self.source,
                "text": self.text}


def canonical_metric(key: str) -> str:
    """The base metric (a METRICS entry) a `metrics` key resolves to; raises UnknownMetric otherwise."""
    if key in METRICS:
        return key
    for basis in COLLECTION_BASES:
        if key == f"Collections ({basis})":
            return "Collections"
    raise UnknownMetric(
        f"{key!r} is not one of {METRICS}; Collections must say 'Collections (gross)' or 'Collections (net)'"
    )


@dataclass
class _Row:
    base: str
    label: str
    missing: bool
    value: Any = None
    period: str = ""
    status: str = ""
    source: str = ""
    as_of: str = ""
    why: str = ""


def _coerce_missing_text(entry: Any) -> tuple[str, str]:
    """(why, source) for a missing entry; entry may be None or a dict with those optional keys."""
    if entry is None:
        return "", ""
    why = str(entry.get("why") or "")
    source = str(entry.get("source") or "")
    return why, source


def _resolve_metrics(metrics: dict, narrative_relevant: set) -> list[_Row]:
    """Validate `metrics` and `narrative_relevant`; return one _Row per METRICS entry, in METRICS order.

    Pure: raises before anything is opened or written. Never fabricates why/source (hard rule 15's spirit
    applied here: a caller must supply real reasons, not this module)."""
    if not isinstance(metrics, dict):
        raise ActivityBlockError(f"metrics must be a dict, got {type(metrics).__name__}")
    by_base: dict[str, tuple[str, Any]] = {}
    for key, entry in metrics.items():
        base = canonical_metric(str(key))
        if base in by_base:
            raise DuplicateMetric(f"both {by_base[base][0]!r} and {key!r} resolve to metric {base!r}")
        by_base[base] = (str(key), entry)
    unknown_nr = {m for m in narrative_relevant if m not in METRICS}
    if unknown_nr:
        raise UnknownMetric(f"narrative_relevant names unknown metric(s) {sorted(unknown_nr)}; expected {METRICS}")

    rows: list[_Row] = []
    for base in METRICS:
        key, entry = by_base.get(base, (base, None))
        value = entry.get("value") if isinstance(entry, dict) else None
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidMetric(f"{base}: value must be a number, got {value!r}")
            if base == "Collections" and key == "Collections":
                raise InvalidMetric(
                    "Collections: a value requires a stated basis - use the key 'Collections (gross)' or "
                    "'Collections (net)' (gross vs net must always be labelled)"
                )
            period = str(entry.get("period") or "")
            status = str(entry.get("status") or "")
            source = str(entry.get("source") or "")
            as_of = str(entry.get("as_of") or "")
            if not period:
                raise InvalidMetric(f"{base}: period is required when a value is supplied")
            if status.casefold() not in verify.FIGURE_STATUSES:
                raise InvalidMetric(f"{base}: status must be one of {verify.FIGURE_STATUSES}, got {status!r}")
            if not source:
                raise InvalidMetric(f"{base}: source is required when a value is supplied")
            if not as_of:
                raise InvalidMetric(f"{base}: as_of is required when a value is supplied")
            try:
                date.fromisoformat(as_of)
            except ValueError as exc:
                raise InvalidMetric(f"{base}: as_of must be an ISO date YYYY-MM-DD, got {as_of!r}") from exc
            rows.append(_Row(base=base, label=key, missing=False, value=value, period=period, status=status,
                             source=source, as_of=as_of))
        else:
            why, source = _coerce_missing_text(entry if isinstance(entry, dict) else None)
            if base in narrative_relevant and not (why and source):
                raise InvalidMetric(
                    f"{base} is narrative-relevant and was not supplied: give 'why' (why it matters to this "
                    "narrative) and 'source' (which system would supply it) - activity_block never invents them"
                )
            label = key if key != base else base
            rows.append(_Row(base=base, label=label, missing=True, why=why, source=source))
    return rows


def _last_used_row(ws) -> int:
    last = 0
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                last = max(last, cell.row)
    return last


def _find_title(ws) -> tuple[int, int] | None:
    """(row, col) of the first cell whose text starts the M2 title prefix, reading order; None if absent."""
    for row in ws.iter_rows():
        for cell in row:
            value = cell.value
            if isinstance(value, str) and value.strip().casefold().startswith(verify.M2_TITLE_PREFIX):
                return cell.row, cell.column
    return None


def _parse_anchor(text: str):
    from openpyxl.utils.cell import coordinate_from_string
    from openpyxl.utils import column_index_from_string

    letters, row = coordinate_from_string(text.strip())
    return row, column_index_from_string(letters)


def _region_clear(ws, row: int, col: int, *, allow_existing: bool) -> None:
    for r in range(row, row + BLOCK_ROWS):
        for c in range(col, col + BLOCK_COLS):
            value = ws.cell(row=r, column=c).value
            if value is not None and not allow_existing:
                raise BlockAreaOccupied(
                    f"{ws.title}!{ws.cell(row=r, column=c).coordinate} already holds {value!r}; the M2 block "
                    f"needs a clear {BLOCK_ROWS}x{BLOCK_COLS} area (give an explicit anchor elsewhere)"
                )


def build(workbook: Path | str, tab: str, metrics: dict, narrative_relevant: set, *,
          anchor: str | None = None) -> list["Flag"]:
    """Write the M2 block (title, header row, one row per verify.M2_METRICS) onto an existing tab.

    `metrics`: dict keyed by a METRICS name, or for Collections 'Collections (gross)'/'Collections (net)';
    each value a dict with 'value', 'period', 'status', 'source', 'as_of' when supplied, or optional 'why'/
    'source' when not. `narrative_relevant`: METRICS names that require a real 'why' and 'source' when
    missing (never invented here) and are marked on the returned Flag; every metric still gets a row and a
    missing one is always flagged, regardless of this set (D20, D24). `anchor`: A1 text for the title cell;
    default: the tab's existing M2 title if there is one (refreshed in place), else two rows below the tab's
    last used row, column A. Returns one Flag per metric not supplied, in METRICS order. Raises before any
    write: a bad metrics dict, a missing/wrong-type workbook, an absent tab, an occupied block area or a
    second title on the tab are all checked before brand.flag_yellow is even read, so a bad --tab is never
    masked by a null assumption; a null brand.flag_yellow is the last gate, checked only when actually needed
    (a fully supplied block never reads it)."""
    rows = _resolve_metrics(metrics, set(narrative_relevant))
    path = Path(workbook)
    if path.suffix.lower() != ".xlsx":
        raise UnsupportedWorkbook(f"{path.name}: activity_block writes .xlsx only (macro safety, D21/D24)")
    if not path.is_file():
        raise FileNotFoundError(f"workbook not found: {path}")

    import openpyxl
    from openpyxl.styles import Font, PatternFill

    from cpa import fsutil

    wb = openpyxl.load_workbook(str(path))
    try:
        if tab not in wb.sheetnames:
            raise TabNotFound(f"{path.name} has no tab {tab!r}; build a P&L tab before adding the M2 block")
        ws = wb[tab]
        anchor_rc = _parse_anchor(anchor) if anchor else None
        existing = _find_title(ws)
        if anchor_rc is None:
            if existing is not None:
                anchor_rc = existing  # refresh the block already there, in place
            else:
                last = _last_used_row(ws)
                anchor_rc = (last + 2, 1) if last else (1, 1)
        if existing is not None and existing != anchor_rc:
            raise DuplicateBlock(
                f"{tab} already has an M2 title at row {existing[0]} col {existing[1]}, different from the "
                f"target anchor row {anchor_rc[0]} col {anchor_rc[1]}; pass that anchor to refresh it"
            )
        row0, col0 = anchor_rc
        _region_clear(ws, row0, col0, allow_existing=existing == anchor_rc)

        flag_yellow = None
        if any(r.missing for r in rows):
            from cpa import config

            from cpa.pptx import brand

            flag_yellow = brand.color("flag_yellow").lstrip("#")

        bold = Font(name="Arial", bold=True)
        plain = Font(name="Arial")
        fill = PatternFill(fill_type="solid", fgColor=flag_yellow, bgColor=flag_yellow) if flag_yellow else None

        title_cell = ws.cell(row=row0, column=col0, value=verify.M2_TITLE)
        title_cell.font = bold
        for i, head in enumerate(HEADERS):
            ws.cell(row=row0 + 1, column=col0 + i, value=head).font = bold

        flags: list[Flag] = []
        for i, r in enumerate(rows):
            row_n = row0 + 2 + i
            ws.cell(row=row_n, column=col0, value=r.label).font = plain
            if not r.missing:
                ws.cell(row=row_n, column=col0 + 1, value=r.value).font = plain
                ws.cell(row=row_n, column=col0 + 2, value=r.period).font = plain
                ws.cell(row=row_n, column=col0 + 3, value=r.status).font = plain
                ws.cell(row=row_n, column=col0 + 4, value=r.source).font = plain
                ws.cell(row=row_n, column=col0 + 5, value=r.as_of).font = plain
                continue
            text = f"{verify.M2_MISSING_MARKER}: {r.base} not supplied"
            if r.why:
                text += f"; needed for {r.why}"
            if r.source:
                text += f"; source {r.source}"
            value_cell = ws.cell(row=row_n, column=col0 + 1, value=text)
            value_cell.font = plain
            if fill is not None:
                value_cell.fill = fill
            flags.append(Flag(metric=r.base, label=r.label, tab=tab, cell=value_cell.coordinate,
                              narrative_relevant=r.base in narrative_relevant, why=r.why, source=r.source,
                              text=text))
        fsutil.atomic_write(path, lambda tmp: wb.save(str(tmp)))
    finally:
        wb.close()
    return flags


# ---------------------------------------------------------------- CLI


def _cmd_build(args: argparse.Namespace) -> int:
    from cpa import config

    try:
        metrics = json.loads(args.metrics.read_text(encoding="utf-8-sig"))
        if not isinstance(metrics, dict):
            raise ActivityBlockError(f"{args.metrics}: must be a JSON object")
        if args.narrative_relevant:
            nr = {m.strip() for m in args.narrative_relevant.split(",") if m.strip()}
        else:
            nr = set(METRICS)
        flags = build(args.workbook, args.tab, metrics, nr, anchor=args.anchor)
    except (ActivityBlockError, FileNotFoundError, config.ConfigError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([f.to_json() for f in flags], indent=2, ensure_ascii=False))
    elif not flags:
        print(f"{args.tab}: M2 block written; all four metrics supplied")
    else:
        for f in flags:
            print(f"{f.cell}: {'NARRATIVE' if f.narrative_relevant else 'info'} {f.text}")
    return 1 if flags else 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `activity_block build`. Import-cheap: no file access here."""
    top = subparsers.add_parser(
        "activity_block",
        help="Write the M2 activity metrics block (wRVUs, cFTE, Collections, Charges) onto a P&L tab.",
    )
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    p = sub.add_parser(
        "build",
        help="Write the block; a missing metric gets a yellow MISSING placeholder, never estimated.",
        description="Writes the M2 block onto an existing tab (never creates one). Exit 0 when every metric "
                    "was supplied, 1 when one or more were flagged missing, 2 on a bad argument or a null "
                    "brand.flag_yellow assumption.",
    )
    p.add_argument("--workbook", type=Path, required=True, help="The .xlsx workbook to write into.")
    p.add_argument("--tab", required=True, help="Existing sheet name to add the block to.")
    p.add_argument("--metrics", type=Path, required=True,
                   help="JSON file: object keyed by wRVUs/cFTE/Charges/'Collections (gross)'/'Collections "
                        "(net)', each a dict with value/period/status/source/as_of, or why/source when the "
                        "metric was not supplied.")
    p.add_argument("--narrative-relevant", default="",
                   help="Comma-separated metric names that must carry a real why/source when missing "
                        "(default: all four).")
    p.add_argument("--anchor", default=None, help="A1 cell for the title (default: the tab's existing M2 "
                                                   "title if there is one, else two rows below the last used "
                                                   "row, column A).")
    p.add_argument("--json", action="store_true", help="Emit the returned flags as JSON.")
    p.set_defaults(func=_cmd_build)
