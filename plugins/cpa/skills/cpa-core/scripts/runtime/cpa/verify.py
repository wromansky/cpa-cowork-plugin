"""Verification tab for every CPA workbook: one row per reported figure, summary CLEAN or N ISSUES.

Build-list items: C1 Verification tab (guide 5.2 cpa-verify, guide 9 verify.py). Hard rules enforced: 7 (every
figure shows period, status, source system and as-of; a figure without a source manifest is SOURCE UNKNOWN and
an issue), 11 (a workbook over 15 MB is streamed and its verification goes to a sibling file), "never alter a
figure to make it tie" and "never suppress a flag" (only the Verification sheet is ever written).

Figures come from the workbook's manifest `figures` (cpa.manifest; location from the record's `cell`, else a
figure id shaped `Sheet!A1`); a workbook without recorded figures gets one SOURCE UNKNOWN row per numeric cell.
Tie-out re-reads the source cell or range (`A1`, `Sheet!A1`, `Sheet!A1:B9` summed). Recalculation is cpa.recalc
(D07). M2 presence is checked on every tab whose name contains "P&L" or "PnL" (DECISIONS D20); the conventions
for issues, passes and the large-file sibling are DECISIONS D21.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator

from cpa import office, recalc

VERIFICATION_SHEET = recalc.VERIFICATION_SHEET
SUMMARY_LABEL_CELL, SUMMARY_CELL = "A1", "B1"
HEADER_ROW = 3  # figure rows start on row 4
CLEAN = "CLEAN"
SOURCE_UNKNOWN = "SOURCE UNKNOWN"
SIBLING_SUFFIX = "_Verification.xlsx"
FIGURE_STATUSES = ("actual", "budget", "forecast", "projected", "restated")
COLUMNS = (
    "figure", "tab", "cell", "value", "period", "status", "source_system", "source_file", "source_ref", "as_of",
    "recalc_check", "tie_out", "prior_value", "variance_pct", "threshold_flag", "m2_check", "issue",
)
ISSUE_COLUMNS = ("issue", "tab", "cell", "expected", "found", "figure")
ABOVE_THRESHOLD = "ABOVE THRESHOLD"

# DECISIONS D20: the M2 activity block U08 writes and this module checks. U08 imports these; never copy them.
PNL_TAB_MARKERS = ("p&l", "pnl")
M2_TITLE = "Activity metrics (M2)"
M2_TITLE_PREFIX = "activity metrics"
M2_METRICS = ("wRVUs", "cFTE", "Collections", "Charges")
M2_MISSING_MARKER = "MISSING"
M2_SEARCH_ROWS = 12
M2_PRESENT = "M2 PRESENT"

_LOC_RE = re.compile(r"^(?:'((?:[^']|'')+)'|([^!]+))!\$?([A-Za-z]{1,3})\$?(\d+)$")
_REF_RE = re.compile(
    r"^(?:(?:'((?:[^']|'')+)'|([^!]+))!)?\$?([A-Za-z]{1,3})\$?(\d+)(?::\$?([A-Za-z]{1,3})\$?(\d+))?$")

__all__ = [
    "VERIFICATION_SHEET", "CLEAN", "SOURCE_UNKNOWN", "COLUMNS", "ISSUE_COLUMNS", "FIGURE_STATUSES",
    "PNL_TAB_MARKERS", "M2_TITLE", "M2_METRICS", "M2_MISSING_MARKER", "M2_SEARCH_ROWS", "M2_PRESENT",
    "VerifyError", "UnsupportedWorkbook", "Issue", "FigureRow", "VerifyResult", "build_verification_tab",
    "is_pnl_tab", "m2_check", "sibling_path", "register",
]


class VerifyError(RuntimeError):
    """A verify failure that is not a workbook finding (bad arguments, unsupported file)."""


class UnsupportedWorkbook(VerifyError):
    """Only .xlsx is verified: the recalculation round trip would strip macros from .xlsm."""


@dataclass
class Issue:
    """One finding: what was expected at tab!cell and what was found (R034)."""

    code: str
    tab: str
    cell: str
    expected: str
    found: str
    figure_id: str = ""

    def to_json(self) -> dict:
        return {"code": self.code, "tab": self.tab, "cell": self.cell, "expected": self.expected,
                "found": self.found, "figure": self.figure_id}

    def to_row(self) -> list:
        return [self.code, self.tab, self.cell, self.expected, self.found, self.figure_id]

    def line(self) -> str:
        where = f"{self.tab}!{self.cell}" if self.cell else (self.tab or "workbook")
        return f"{where}: {self.code} expected {self.expected}, found {self.found}"


@dataclass
class FigureRow:
    """One Verification row, in COLUMNS order. Plain constants only."""

    figure: str
    tab: str
    cell: str
    value: Any = None
    period: str = ""
    status: str = ""
    source_system: str = ""
    source_file: str = ""
    source_ref: str = ""
    as_of: str = ""
    recalc_check: str = ""
    tie_out: str = ""
    prior_value: Any = "n/a"
    variance_pct: Any = "n/a"
    threshold_flag: str = ""
    m2_check: str = "n/a"
    issue: str = ""

    def to_row(self) -> list:
        return [getattr(self, name) for name in COLUMNS]

    def to_json(self) -> dict:
        return {name: getattr(self, name) for name in COLUMNS}


@dataclass
class VerifyResult:
    """What verify found. `clean` only when there is no issue (NOT_RECALCULATED is an issue, D07)."""

    workbook: Path
    verification_file: Path
    figure_rows: list[FigureRow] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    recalc_status: str = ""
    recalc_reason: str = ""
    threshold_pct: float = 0.0
    verified_at: str = ""
    notes: list[str] = field(default_factory=list)
    office_checks: dict[str, str] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.issues

    @property
    def rows(self) -> int:
        return len(self.figure_rows)

    @property
    def summary(self) -> str:
        return CLEAN if self.clean else f"{len(self.issues)} ISSUES"

    def to_json(self) -> dict:
        return {
            "workbook": str(self.workbook),
            "verification_file": str(self.verification_file),
            "summary": self.summary,
            "clean": self.clean,
            "rows": self.rows,
            "issues": [i.to_json() for i in self.issues],
            "issue_lines": [i.line() for i in self.issues],
            "figures": [r.to_json() for r in self.figure_rows],
            "recalc": {"status": self.recalc_status, "reason": self.recalc_reason},
            "threshold_pct": self.threshold_pct,
            "verified_at": self.verified_at,
            "notes": self.notes,
            "acceptance": office.acceptance(
                financial=self.summary if self.recalc_status == recalc.RECALCULATED else (
                    self.recalc_status or "NOT_CHECKED"), **self.office_checks),
        }


# ---------------------------------------------------------------- small helpers


def is_pnl_tab(name: str) -> bool:
    """True for a tab whose name contains "P&L" or "PnL", any case (D20)."""
    low = name.casefold()
    return any(marker in low for marker in PNL_TAB_MARKERS)


def sibling_path(workbook: Path | str) -> Path:
    """Where a large workbook's verification is written: <stem>_Verification.xlsx beside it."""
    p = Path(workbook)
    return p.with_name(p.stem + SIBLING_SUFFIX)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _fmt(value: Any) -> str:
    n = _num(value)
    if n is None:
        return "empty" if value is None or value == "" else str(value)
    return f"{n:,.2f}"


def _col_index(letters: str) -> int:
    from openpyxl.utils import column_index_from_string

    return column_index_from_string(letters.upper())


def _coord(row: int, col: int) -> str:
    from openpyxl.utils import get_column_letter

    return f"{get_column_letter(col)}{row}"


def _rc(coord: str) -> tuple[int, int]:
    """'B10' -> (10, 2), for sorting cells in reading order."""
    from openpyxl.utils.cell import coordinate_from_string

    letters, row = coordinate_from_string(coord)
    return row, _col_index(letters)


def _parse_loc(text: Any) -> tuple[str, str] | None:
    """'P&L!B5' or "'My tab'!B5" -> (sheet, 'B5'); anything else None."""
    if not isinstance(text, str):
        return None
    m = _LOC_RE.match(text.strip())
    if not m:
        return None
    sheet = m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2)
    return sheet, f"{m.group(3).upper()}{int(m.group(4))}"


def _parse_ref(text: Any) -> tuple[str | None, int, int, int, int] | None:
    """Source ref -> (sheet or None, row1, col1, row2, col2); None when not A1 notation."""
    if not isinstance(text, str):
        return None
    m = _REF_RE.match(text.strip())
    if not m:
        return None
    sheet = m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2)
    r1, c1 = int(m.group(4)), _col_index(m.group(3))
    r2, c2 = (int(m.group(6)), _col_index(m.group(5))) if m.group(5) else (r1, c1)
    return sheet, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def _safe(value: Any) -> Any:
    """Keep the tab constants-only: text that Excel would read as a formula or an error value stays text."""
    if isinstance(value, str) and (value.startswith("=") or value in recalc.ERROR_VALUES):
        return f"'{value}"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


# ---------------------------------------------------------------- workbook values


class _Values:
    """Cached values of one workbook by (sheet, A1). Full openpyxl load, or streaming for a large file."""

    def __init__(self, path: Path, *, large: bool) -> None:
        self.path, self.large = path, large
        self._wb = None
        self._cache: dict[tuple[str, str], Any] = {}
        if large:
            from cpa import bigxlsx

            self.sheetnames = bigxlsx.sheet_names(path)
        else:
            import openpyxl

            self._wb = openpyxl.load_workbook(str(path), data_only=True)
            self.sheetnames = list(self._wb.sheetnames)

    def prefetch(self, cells: Iterable[tuple[str, str]]) -> None:
        if not self.large:
            return
        from openpyxl.utils.cell import coordinate_from_string

        from cpa import bigxlsx

        wanted: dict[str, dict[tuple[int, int], str]] = {}
        for sheet, coord in cells:
            if sheet in self.sheetnames and (sheet, coord) not in self._cache:
                letters, row = coordinate_from_string(coord)
                wanted.setdefault(sheet, {})[(row, _col_index(letters))] = coord
        for sheet, spots in wanted.items():
            last = max(r for r, _ in spots)
            gen = bigxlsx.iter_rows(self.path, sheet)
            try:
                for r, row in enumerate(gen, start=1):
                    for (sr, sc), coord in spots.items():
                        if sr == r:
                            self._cache[(sheet, coord)] = row[sc - 1] if sc - 1 < len(row) else None
                    if r >= last:
                        break
            finally:
                gen.close()

    def get(self, sheet: str, coord: str) -> Any:
        if self._wb is not None:
            return self._wb[sheet][coord].value if sheet in self.sheetnames else None
        return self._cache.get((sheet, coord))

    def rows(self, sheet: str) -> Iterator[list]:
        if self._wb is not None:
            for row in self._wb[sheet].iter_rows(values_only=True):
                yield list(row)
            return
        from cpa import bigxlsx

        gen = bigxlsx.iter_rows(self.path, sheet)
        try:
            yield from gen
        finally:
            gen.close()

    def numeric_cells(self, skip: set[str]) -> Iterator[tuple[str, str, Any]]:
        """(sheet, A1, value) for every numeric cached value on sheets not in skip."""
        for sheet in self.sheetnames:
            if sheet in skip:
                continue
            for r, row in enumerate(self.rows(sheet), start=1):
                for c, value in enumerate(row, start=1):
                    if _num(value) is not None and not isinstance(value, str):
                        yield sheet, _coord(r, c), value

    def close(self) -> None:
        if self._wb is not None:
            self._wb.close()


def _formula_cells(path: Path) -> dict[tuple[str, str], str]:
    """Every formula cell of a normal-size workbook (streamed, formulas not values)."""
    import openpyxl

    found: dict[tuple[str, str], str] = {}
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=False, keep_links=False)
    try:
        for ws in wb.worksheets:
            if ws.title == VERIFICATION_SHEET:
                continue
            for row in ws.iter_rows():
                for cell in row:
                    if getattr(cell, "data_type", None) == "f":
                        found[(ws.title, cell.coordinate)] = str(cell.value)
    finally:
        wb.close()
    return found


# ---------------------------------------------------------------- M2 check


def m2_check(rows: Any, tab: str = "") -> tuple[str, list[Issue]]:
    """R190/R205 on one P&L tab: is the M2 block there, and does every missing metric carry a flag?

    `rows` is an openpyxl worksheet or any iterable of row value lists. Returns (status text, issues); the status
    is M2 PRESENT (with the flagged metrics named) when there are no issues. Pure read."""
    if hasattr(rows, "iter_rows"):
        tab = tab or rows.title
        rows = rows.iter_rows(values_only=True)
    grid = [list(r) for r in rows]
    title = None
    for r, row in enumerate(grid):
        for c, value in enumerate(row):
            if isinstance(value, str) and value.strip().casefold().startswith(M2_TITLE_PREFIX):
                title = (r, c)
                break
        if title:
            break
    if title is None:
        issue = Issue("M2_BLOCK_MISSING", tab, "", f"an '{M2_TITLE}' block on this P&L tab", "no block")
        return "M2 BLOCK MISSING", [issue]
    tr, tc = title
    issues: list[Issue] = []
    problems: list[str] = []
    flagged: list[str] = []
    for metric in M2_METRICS:
        hit = None
        for r in range(tr + 1, min(tr + 1 + M2_SEARCH_ROWS, len(grid))):
            row = grid[r]
            label = row[tc] if tc < len(row) else None
            if isinstance(label, str) and label.strip().casefold().startswith(metric.casefold()):
                hit = r
                break
        if hit is None:
            issues.append(Issue("M2_METRIC_MISSING", tab, _coord(tr + 1, tc + 1), f"a '{metric}' row in the M2 block",
                                "no row"))
            problems.append(f"M2 METRIC MISSING {metric}")
            continue
        row = grid[hit]
        value = row[tc + 1] if tc + 1 < len(row) else None
        where = _coord(hit + 1, tc + 2)
        if isinstance(value, str) and value.strip().casefold().startswith(M2_MISSING_MARKER.casefold()):
            flagged.append(metric)
        elif _num(value) is None or isinstance(value, str) and value.strip() in recalc.ERROR_VALUES:
            issues.append(Issue("M2_METRIC_UNFLAGGED", tab, where,
                                f"a {metric} value or a '{M2_MISSING_MARKER} ...' flag", _fmt(value)))
            problems.append(f"M2 METRIC UNFLAGGED {metric}")
    if issues:
        return "; ".join(problems), issues
    return M2_PRESENT + (f" (flagged: {', '.join(flagged)})" if flagged else ""), []


# ---------------------------------------------------------------- sources


def _resolve_source(recorded: str, sources_dir: Path | None) -> Path | None:
    from cpa import manifest

    path = manifest.from_rel(recorded)
    if path.is_file():
        return path
    if sources_dir is not None:
        name = Path(recorded.replace("\\", "/").split("/")[-1]).name
        direct = sources_dir / name
        if direct.is_file():
            return direct
        hits = [p for p in sources_dir.rglob(name) if p.is_file()]
        if len(hits) == 1:
            return hits[0]
    return None


def _json_pointer(document: Any, pointer: str) -> Any:
    """Resolve a strict RFC 6901 JSON Pointer; the empty pointer selects the document root."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must be empty or start with '/'")
    current = document
    for encoded in pointer[1:].split("/"):
        if re.search(r"~(?![01])", encoded):
            raise ValueError(f"invalid JSON Pointer escape in {encoded!r}")
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise ValueError(f"JSON Pointer member {token!r} is missing")
            current = current[token]
        elif isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token) or int(token) >= len(current):
                raise ValueError(f"JSON Pointer array index {token!r} is missing or invalid")
            current = current[int(token)]
        else:
            raise ValueError(f"JSON Pointer cannot traverse through {type(current).__name__}")
    return current


def _finite_number(value: Any, where: str) -> float:
    """Accept only finite JSON numeric scalars (not booleans or numeric strings)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a non-null JSON number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{where} must be finite, got {value!r}")
    return number


def _read_json_source(path: Path, ref: str) -> tuple[float | None, str]:
    """Read a direct JSON scalar or evaluate a bounded typed control record."""
    from cpa import manifest

    try:
        sidecar = manifest.read(path)
        if not sidecar.get("source") or not sidecar.get("as_of"):
            return None, "JSON source manifest must contain source and as_of"
        date.fromisoformat(str(sidecar["as_of"]))
        if not sidecar.get("sha256") or sidecar["sha256"] != manifest.sha256_of(path):
            return None, "JSON source manifest sha256 does not match source file"
        document = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"invalid {x}")))
        if ref.startswith("json:"):
            return _finite_number(_json_pointer(document, ref[5:]), ref), ""
        if not ref.startswith("calc:"):
            return None, "JSON refs must use json:/pointer or calc:/pointer"
        def evaluate(calc_ref: str, active: set[str], depth: int) -> float:
            if depth > 8:
                raise ValueError("calculation nesting exceeds maximum depth 8")
            pointer = calc_ref[5:]
            if pointer in active:
                raise ValueError(f"calculation self-reference/cycle at {pointer!r}")
            active.add(pointer)
            try:
                spec = _json_pointer(document, pointer)
                if not isinstance(spec, dict) or set(spec) != {"op", "args"} or not isinstance(spec["args"], list):
                    raise ValueError("calculation record must contain exactly 'op' and list 'args'")
                op, args = spec["op"], spec["args"]
                if not all(isinstance(arg, str) and arg.startswith(("json:", "calc:")) for arg in args):
                    raise ValueError("calculation operands must be json:/pointer or calc:/pointer refs")
                values = []
                for arg in args:
                    raw = _json_pointer(document, arg[5:]) if arg.startswith("json:") else evaluate(arg, active, depth + 1)
                    values.append(_finite_number(raw, arg))
                if op == "sum" and len(values) >= 1:
                    result = sum(values)
                elif op == "difference" and len(values) == 2:
                    result = values[0] - values[1]
                elif op == "product" and len(values) == 2:
                    result = values[0] * values[1]
                elif op == "weighted_allocation" and len(values) == 3:
                    pool, weight, total_weight = values
                    if total_weight == 0:
                        raise ValueError("weighted_allocation total weight must not be zero")
                    result = pool * weight / total_weight
                else:
                    raise ValueError(f"unsupported operation/arity {op!r}/{len(values)}")
                return _finite_number(result, "calculation result")
            finally:
                active.remove(pointer)

        return evaluate(ref, set(), 1), ""
    except Exception as exc:
        # Include missing sidecars and malformed inputs as visible unreadable findings.
        return None, f"JSON source {path.name}: {exc}"


def _read_source(path: Path, ref: str) -> tuple[float | None, str]:
    """(value, '') re-read from A1 or explicit JSON provenance, or (None, why)."""
    if ref.startswith(("json:", "calc:")):
        return _read_json_source(path, ref)
    parsed = _parse_ref(ref)
    if parsed is None:
        return None, f"source ref {ref!r} is not A1 notation (A1, Sheet!A1 or Sheet!A1:B9)"
    sheet, r1, c1, r2, c2 = parsed
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv", ".txt"):
        delim = "\t" if suffix == ".tsv" else ","
        with path.open(encoding="utf-8-sig", newline="") as fh:
            grid = list(csv.reader(fh, delimiter=delim))
        rows = iter(grid)
    elif suffix in (".xlsx", ".xlsm", ".xlsb"):
        from cpa import bigxlsx

        try:
            rows = bigxlsx.iter_rows(path, sheet)
        except bigxlsx.BigXlsxError as exc:
            return None, str(exc)
    else:
        return None, f"cannot re-read a {suffix or 'suffix-less'} source"
    values: list[float] = []
    text_seen = False
    try:
        for r, row in enumerate(rows, start=1):
            if r > r2:
                break
            if r < r1:
                continue
            for c in range(c1, c2 + 1):
                value = row[c - 1] if c - 1 < len(row) else None
                n = _num(value)
                if n is not None:
                    values.append(n)
                elif value not in (None, ""):
                    text_seen = True
    finally:
        close = getattr(rows, "close", None)
        if close:
            close()
    if not values:
        return None, f"no number at {ref}" + (" (text found)" if text_seen else "")
    if r1 == r2 and c1 == c2 and text_seen:
        return None, f"no number at {ref}"
    return sum(values), ""


def _lineage_source(workbook: Path, figure_id: str, resolved: Path | None) -> tuple[str, str] | None:
    """(source system, as_of) from the figure's lineage, else the resolved source's own manifest, else None."""
    from cpa import manifest

    try:
        chain = manifest.lineage(workbook, figure_id)
        end = chain[-1]
        if end.get("source") and end.get("as_of"):
            return str(end["source"]), str(end["as_of"])
    except manifest.ManifestError:
        pass
    if resolved is not None and manifest.exists(resolved):
        data = manifest.read(resolved)
        if data.get("source") and data.get("as_of"):
            return str(data["source"]), str(data["as_of"])
    return None


# ---------------------------------------------------------------- build


def _prior_lookup(prior: Path, specs: list[tuple[str, str | None, str | None]]) -> dict[str, Any]:
    """figure id -> prior value; by the prior manifest's location for that id, else by the same tab and cell."""
    from cpa import bigxlsx, manifest

    prior_figs: dict = {}
    if manifest.exists(prior):
        prior_figs = manifest.read(prior).get("figures") or {}
    locs: dict[str, tuple[str, str]] = {}
    for fid, sheet, coord in specs:
        rec = prior_figs.get(fid)
        loc = _parse_loc(rec.get("cell") or fid) if isinstance(rec, dict) else None
        if loc is None and sheet and coord:
            loc = (sheet, coord)
        if loc is not None:
            locs[fid] = loc
    values = _Values(prior, large=bigxlsx.is_large(prior))
    try:
        values.prefetch(locs.values())
        return {fid: values.get(*loc) for fid, loc in locs.items()}
    finally:
        values.close()


def build_verification_tab(workbook, prior=None, sources_dir=None, threshold=None) -> VerifyResult:
    """Attach or refresh the Verification tab (C1) and return what was found; never changes another cell.

    `prior`: an earlier version of the same workbook (variance column); `sources_dir`: where to look for a source
    file no longer at its recorded path; `threshold`: variance flag in percent, default
    verification.variance_threshold_pct. A workbook over 15 MB gets its verification in sibling_path(workbook)."""
    from cpa import bigxlsx, config, manifest

    path = Path(workbook)
    if path.suffix.lower() != ".xlsx":
        raise UnsupportedWorkbook(f"{path.name}: verify handles .xlsx only (recalculation would strip macros from "
                                  f"{path.suffix or 'this file'})")
    if not path.is_file():
        raise FileNotFoundError(f"workbook not found: {path}")
    src_dir = Path(sources_dir) if sources_dir is not None else None
    if src_dir is not None and not src_dir.is_dir():
        raise VerifyError(f"--sources {src_dir} is not a folder")
    thr = float(threshold) if threshold is not None else float(config.assumption("verification",
                                                                                  "variance_threshold_pct"))
    tolerance = float(config.assumption("verification", "tie_out_tolerance_abs"))
    large = bigxlsx.is_large(path)
    result = VerifyResult(workbook=path, verification_file=sibling_path(path) if large else path,
                          threshold_pct=thr, verified_at=manifest.utc_now_iso())
    work = Path(tempfile.mkdtemp(prefix="cpa_vf_"))
    try:
        rc = recalc.recalc(path, work)
        result.recalc_status, result.recalc_reason = rc.status, rc.reason
        _collect(result, path, rc, large=large, prior=Path(prior) if prior else None, src_dir=src_dir,
                 tolerance=tolerance)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if large:
        bigxlsx.write_rows(result.verification_file, _tab_rows(result), sheet_title=VERIFICATION_SHEET)
        result.notes.append("workbook over 15 MB: verification written to the sibling file; the workbook is unchanged")
        result.office_checks = {"package": "SIBLING_CHECKED_SCOPE", "preservation": "SOURCE_NOT_EDITED"}
    else:
        _write_tab(path, result)
        if result.recalc_status == recalc.RECALCULATED:
            rc2 = recalc.recalc_in_place(path)
            if not rc2.recalculated:
                result.issues.append(Issue("RECALC_FAILED", VERIFICATION_SHEET, SUMMARY_CELL,
                                           "recalculated after the tab was written", rc2.reason or rc2.status))
                _write_tab(path, result)
        else:
            result.notes.append("not recalculated: cached formula values are not accepted as verified results")
    if manifest.exists(path):
        manifest.update(path, verification={"summary": result.summary, "issues": len(result.issues),
                                            "verified_at": result.verified_at,
                                            "file": manifest.to_rel(result.verification_file),
                                            "acceptance": result.to_json()["acceptance"]})
    return result


def _collect(result: VerifyResult, path: Path, rc: recalc.RecalcResult, *, large: bool, prior: Path | None,
             src_dir: Path | None, tolerance: float) -> None:
    from cpa import manifest

    issues = result.issues
    recalculated = rc.recalculated
    if rc.status == recalc.NOT_RECALCULATED:
        issues.append(Issue("NOT_RECALCULATED", VERIFICATION_SHEET, SUMMARY_CELL, "verified recalculation",
                            rc.reason))
    elif not recalculated:
        issues.append(Issue("RECALC_FAILED", VERIFICATION_SHEET, SUMMARY_CELL, "verified recalculation",
                            rc.reason))
    values_path = rc.output if recalculated and rc.output else path
    errors = rc.errors if recalculated else recalc.scan_errors(path)
    error_at = {(e.sheet, e.cell): e.value for e in errors}
    for e in errors:
        issues.append(Issue("FORMULA_ERROR", e.sheet, e.cell, "a value (zero formula errors)", e.value))

    values = _Values(values_path, large=large)
    cached = _Values(path, large=large) if recalculated and not large else None
    formulas = {} if large else _formula_cells(path)
    try:
        data = manifest.read(path) if manifest.exists(path) else {}
        figures = data.get("figures") or {}
        rows: list[FigureRow] = []
        row_issues: list[list[Issue]] = []
        if figures:
            locs = {fid: _parse_loc(rec.get("cell") if isinstance(rec, dict) and rec.get("cell") else fid)
                    for fid, rec in figures.items()}
            values.prefetch(loc for loc in locs.values() if loc)
            for fid, rec in figures.items():
                rec = rec if isinstance(rec, dict) else {}
                loc = locs[fid]
                no_cache = loc is not None and loc in formulas and not recalculated
                row, found = _manifest_row(path, fid, rec, loc, data, values, src_dir, tolerance, no_cache)
                rows.append(row)
                row_issues.append(found)
        else:
            skip = {VERIFICATION_SHEET}
            spots = list(values.numeric_cells(skip))
            seen = {(s, c) for s, c, _ in spots}
            for (s, c) in formulas:
                if (s, c) not in seen:
                    spots.append((s, c, values.get(s, c)))
            spots.sort(key=lambda t: (values.sheetnames.index(t[0]), *_rc(t[1])))
            for sheet, coord, value in spots:
                if isinstance(value, str) and value not in recalc.ERROR_VALUES:
                    continue
                row = FigureRow(figure=f"{sheet}!{coord}", tab=sheet, cell=coord, value=value, period="",
                                status="", source_system=SOURCE_UNKNOWN, source_file=SOURCE_UNKNOWN,
                                source_ref="", as_of="", tie_out="n/a (no source)")
                rows.append(row)
                row_issues.append([Issue("SOURCE_UNKNOWN", sheet, coord, "a source manifest recording this figure",
                                         "none", row.figure)])
        # recalculation check per row
        for row, found in zip(rows, row_issues):
            key = (row.tab, row.cell)
            if not row.tab:
                row.recalc_check = "n/a (no location)"
            elif key in error_at:
                row.recalc_check = f"ERROR {error_at[key]}"
            elif not recalculated:
                row.recalc_check = "NOT RECALCULATED"
            elif cached is not None and key in formulas:
                before = cached.get(*key)
                if before is not None and _num(before) != _num(row.value):
                    row.recalc_check = f"STALE (file showed {_fmt(before)})"
                    found.append(Issue("STALE_VALUE", row.tab, row.cell, f"{_fmt(row.value)} (recalculated)",
                                       f"{_fmt(before)} (cached in the file)", row.figure))
                else:
                    row.recalc_check = "OK"
            else:
                row.recalc_check = "OK"
        # variance vs prior
        if prior is not None:
            if not prior.is_file():
                result.notes.append(f"prior version {prior} not found: variance columns show n/a")
            else:
                prior_values = _prior_lookup(prior, [(r.figure, r.tab or None, r.cell or None) for r in rows])
                for row, found in zip(rows, row_issues):
                    _variance(row, found, prior_values.get(row.figure), result.threshold_pct)
        # M2 on every P&L tab
        m2_status: dict[str, str] = {}
        for sheet in values.sheetnames:
            if sheet != VERIFICATION_SHEET and is_pnl_tab(sheet):
                status, found = m2_check(values.rows(sheet), sheet)
                m2_status[sheet] = status
                issues.extend(found)
        for row, found in zip(rows, row_issues):
            if row.tab in m2_status:
                row.m2_check = m2_status[row.tab]
            row.issue = "; ".join(i.code for i in found)
            issues.extend(found)
        result.figure_rows = rows
        if not rows:
            result.notes.append("no figures found on any output tab")
    finally:
        values.close()
        if cached is not None:
            cached.close()


def _manifest_row(path: Path, fid: str, rec: dict, loc: tuple[str, str] | None, data: dict, values: _Values,
                  src_dir: Path | None, tolerance: float, no_cache: bool) -> tuple[FigureRow, list[Issue]]:
    from cpa import manifest

    found: list[Issue] = []
    sheet, coord = loc if loc else ("", "")
    row = FigureRow(figure=fid, tab=sheet, cell=coord)
    if loc is None:
        found.append(Issue("FIGURE_LOCATION_UNKNOWN", "", "", "a cell (record 'cell' or figure id 'Sheet!A1')",
                           str(rec.get("cell") or fid), fid))
    elif sheet not in values.sheetnames:
        found.append(Issue("FIGURE_LOCATION_UNKNOWN", sheet, coord, f"tab {sheet!r} in the workbook", "no such tab",
                           fid))
        row.tab, row.cell = sheet, coord
        loc = None
    row.value = values.get(sheet, coord) if loc else rec.get("value")
    row.period = str(rec.get("period") or data.get("period") or "")
    row.status = str(rec.get("status") or data.get("status") or "")
    if not row.period:
        found.append(Issue("PERIOD_MISSING", sheet, coord, "a period label for the figure", "none", fid))
    if row.status.casefold() not in FIGURE_STATUSES:
        found.append(Issue("STATUS_MISSING" if not row.status else "STATUS_INVALID", sheet, coord,
                           "one of " + "/".join(FIGURE_STATUSES), row.status or "none", fid))
    recorded = str(rec.get("source_file") or "")
    row.source_file = recorded or SOURCE_UNKNOWN
    row.source_ref = str(rec.get("ref") or "")
    resolved = _resolve_source(recorded, src_dir) if recorded else None
    origin = _lineage_source(path, fid, resolved) if recorded else None
    if origin is None:
        row.source_system = SOURCE_UNKNOWN
        found.append(Issue("SOURCE_UNKNOWN", sheet, coord, "a source manifest with source system and as-of",
                           f"none for {recorded or 'this figure'}", fid))
    else:
        row.source_system, row.as_of = origin
    # tie-out
    current = _num(row.value)
    if resolved is None:
        row.tie_out = "SOURCE FILE NOT FOUND" if recorded else "n/a (no source)"
        if recorded:
            found.append(Issue("SOURCE_FILE_NOT_FOUND", sheet, coord, f"source file {recorded}", "not found", fid))
    else:
        if resolved != manifest.from_rel(recorded):
            row.source_file = f"{recorded} (found at {resolved})"
        src_value, why = _read_source(resolved, row.source_ref)
        if src_value is None:
            row.tie_out = "UNREADABLE"
            found.append(Issue("TIE_OUT_UNREADABLE", sheet, coord, f"a number at {row.source_ref or '(no ref)'}",
                               why, fid))
        elif current is None and row.value is None and no_cache:
            row.tie_out = f"NOT CHECKED (formula not recalculated; source {_fmt(src_value)})"
        elif current is None:
            row.tie_out = f"MISMATCH (source {_fmt(src_value)})"
            found.append(Issue("TIE_OUT_FAILED", sheet, coord, f"{_fmt(src_value)} from {Path(recorded).name} "
                               f"{row.source_ref}", _fmt(row.value), fid))
        elif abs(current - src_value) <= tolerance:
            row.tie_out = f"OK (source {_fmt(src_value)})"
        else:
            row.tie_out = f"MISMATCH (source {_fmt(src_value)})"
            found.append(Issue("TIE_OUT_FAILED", sheet, coord, f"{_fmt(src_value)} from {Path(recorded).name} "
                               f"{row.source_ref}", _fmt(row.value), fid))
    return row, found


def _variance(row: FigureRow, found: list[Issue], prior_value: Any, threshold: float) -> None:
    current, before = _num(row.value), _num(prior_value)
    if before is None:
        row.prior_value = "n/a (not in prior)" if prior_value is None else _fmt(prior_value)
        return
    row.prior_value = before
    if current is None:
        row.variance_pct = "n/a"
        return
    if before == 0:
        if current == 0:
            row.variance_pct = 0.0
            return
        row.variance_pct = "n/a (prior 0)"
        pct_text = "from 0"
    else:
        pct = (current - before) / abs(before) * 100.0
        row.variance_pct = round(pct, 2)
        if abs(pct) <= threshold:
            return
        pct_text = f"{pct:+.1f}%"
    row.threshold_flag = ABOVE_THRESHOLD
    found.append(Issue("VARIANCE_ABOVE_THRESHOLD", row.tab, row.cell,
                       f"within {threshold:g}% of prior {_fmt(before)}", f"{_fmt(current)} ({pct_text})", row.figure))


# ---------------------------------------------------------------- writing


def _tab_rows(result: VerifyResult) -> list[list]:
    rows: list[list] = [
        ["Summary", result.summary, "verified_at", result.verified_at, "threshold_pct", result.threshold_pct],
        ["workbook", result.workbook.name, "recalc", result.recalc_status, "figures", result.rows],
        list(COLUMNS),
    ]
    rows += [r.to_row() for r in result.figure_rows]
    rows += [[], ["Issues", len(result.issues)], list(ISSUE_COLUMNS)]
    rows += [i.to_row() for i in result.issues]
    rows += [[], ["Acceptance", "Package/preservation: see run result", "Financial", result.summary,
                  "Visual", "NOT_REVIEWED"]]
    return [[_safe(v) for v in row] for row in rows]


def _write_tab(path: Path, result: VerifyResult) -> None:
    """Replace Verification and add absent source notes; leave original financial sheets untouched."""
    import openpyxl
    from openpyxl.styles import Font

    from cpa import fsutil

    from cpa import office

    wb = office.load_workbook(path)
    added = {VERIFICATION_SHEET, "Source & Notes"} - set(wb.sheetnames)
    try:
        if VERIFICATION_SHEET in wb.sheetnames:
            wb.remove(wb[VERIFICATION_SHEET])
        ws = wb.create_sheet(VERIFICATION_SHEET, 0)
        bold = Font(name="Arial", bold=True)
        plain = Font(name="Arial")
        for r, values in enumerate(_tab_rows(result), start=1):
            for c, value in enumerate(values, start=1):
                cell = ws.cell(row=r, column=c)
                cell.value = value
                if isinstance(value, str):
                    cell.data_type = "s"
                cell.font = bold if r in (1, HEADER_ROW) or (c == 1 and value in ("Issues",)) else plain
        from cpa.pptx import brand

        brand.style_generated_sheet(ws, header_rows=(HEADER_ROW,), role="reference")
        # Never replace analyst-maintained source notes or touch the original financial sheets.
        if "Source & Notes" not in wb.sheetnames:
            notes = wb.create_sheet("Source & Notes")
            notes.append(["Figure", "Source system", "Source file", "Source reference", "Period", "Status", "As of"])
            for figure in result.figure_rows:
                notes.append([_safe(v) for v in (figure.figure, figure.source_system, figure.source_file,
                              figure.source_ref, figure.period, figure.status, figure.as_of)])
                for cell in notes[notes.max_row]:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
            if not result.figure_rows:
                notes.append(["No figure provenance recorded; analyst review required."])
            brand.style_generated_sheet(notes, role="reference")
        wb.active = 0
        for sheet in wb.worksheets:
            sheet.sheet_view.tabSelected = sheet.title == VERIFICATION_SHEET
        wb.calculation.fullCalcOnLoad = True
        office.save_workbook(wb, path, changed_sheets={VERIFICATION_SHEET}, added_sheets=added)
        result.office_checks = {"package": "CHECKED_SCOPE", "preservation": "CHECKED_SCOPE"}
    finally:
        wb.close()


# ---------------------------------------------------------------- CLI


def _cmd_verify(args: argparse.Namespace) -> int:
    from cpa import config

    try:
        result = build_verification_tab(args.workbook, prior=args.prior, sources_dir=args.sources)
    except (VerifyError, FileNotFoundError, config.ConfigError, recalc.RecalcError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result.to_json(), indent=2, ensure_ascii=False, default=str))
    return 0 if result.clean else 1


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the top-level `verify` command. Import-cheap: no file access here."""
    p = subparsers.add_parser(
        "verify",
        help="Attach or refresh the Verification tab; print JSON; exit 1 when there are issues.",
        description="Recalculate, tie every reported figure to its source, compare with a prior version, check "
                    "the M2 block on P&L tabs, and write the Verification tab (CLEAN or N ISSUES). Never changes "
                    "a figure. Exit 0 clean, 1 issues, 2 could not verify.",
    )
    p.add_argument("workbook", type=Path, help="The .xlsx workbook to verify.")
    p.add_argument("--prior", type=Path, default=None, help="Prior version of the same workbook (variance column).")
    p.add_argument("--sources", type=Path, default=None,
                   help="Folder to search for a source file that is no longer at its recorded path.")
    p.set_defaults(func=_cmd_verify)
