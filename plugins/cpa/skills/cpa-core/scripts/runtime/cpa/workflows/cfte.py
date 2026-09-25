"""cFTE calculator refresh (B19): APP, Clinical Associate and Faculty calculators plus the consolidated
reference; a cFTE value is never present without every one of its inputs.

Build List B19 (CPA_Cowork_Build_List.md "B19 cFTE calculator refresh"), guide section 6 row
`cpa-cag-match` (B18, B19 share the skill), hard rule 5/AGENTS.md ("cFTE is left blank without proper
inputs. cFTE and effort are synonyms."). Rules: R005/R129/R130/R161/R175 (blank without inputs, union row
count), R219 (CU per session against target, values from reference data - never hard-coded).

Inventory section K (FPA_Work_Inventory_CPA.md "cFTE and CU assessment"): Clinical Units per session,
multiplied by sessions, compared against a target for 1.0 cFTE. The example numbers there (1.20/1.25
CU per session, 440 target, for DOM Medicine General Internal Medicine) are seeded into
`reference/cu_per_session.csv` as a FIXTURE row, never a literal in this module.

Inputs:
- Sessions export(s) `inbox/qgenda/sessions_<dept>_<YYYY-MM-DD>.*` (FIXTURE - confirm against her file;
  the inventory marks a sessions source `[UNCONFIRMED]`). No `cpa.sources` adapter exists for this data
  (only `qgenda.tasks` is built), so it is read directly, the same fold-header-alias approach as
  cag_match's masterlist reader, never through `cpa.sources`.
- `reference/cu_per_session.csv` (mine; `config.reference_file`): department, division, activity ->
  CU per session and the target CU for 1.0 cFTE. A session row whose key is absent, or whose
  cu_per_session/target cell is blank, leaves cFTE blank rather than estimating it.
- B18's `outbox/cag/<date>/CAG_Task_Combined_v<N>.xlsx` `Combined` sheet (optional): attaches the CAG a
  session row's (department, division, activity) matched to, for reference only; its absence never
  blocks a run (B19 does not own CAG matching, R075).

Every department label goes through `crosswalk.load().lookup`; unmatched -> `UnmatchedDepartment`
(hard rule 10). Role labels are compared folded against `ROLES`; anything else is `UnknownRole`
(FIXTURE - confirm her exact three labels).
"""
from __future__ import annotations

from cpa import office

import argparse
import csv
import json
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Any

__all__ = [
    "ROLES", "SESSION_COLUMNS", "SESSION_REQUIRED", "CU_REF_NAME", "CU_REF_COLUMNS", "COMBINED_CAG_COLUMNS",
    "OUTPUT_STEM", "ROLE_SHEETS", "OUTPUT_SHEETS", "ROW_HEADER",
    "CfteError", "SessionFileError", "CuRefError", "UnknownRole",
    "SessionRow", "CfteRow", "RunResult",
    "compute_cfte", "load_sessions", "load_cu_ref", "load_combined_cags", "build_rows", "split_by_role",
    "consolidate", "default_sessions", "next_version", "write_workbook", "run", "register",
]

ROLES: tuple[str, ...] = ("APP", "Clinical Associate", "Faculty")  # FIXTURE - confirm her exact labels

# FIXTURE - confirm against her file: header spellings of the sessions export.
SESSION_COLUMNS: dict[str, tuple[str, ...]] = {
    "provider": ("provider", "provider name", "name"),
    "role": ("role", "provider type", "provider role"),
    "department": ("department", "dept"),
    "division": ("division", "div"),
    "activity": ("activity",),
    "sessions": ("sessions", "session count", "# sessions", "num sessions"),
}
SESSION_REQUIRED = ("provider", "role", "department", "division", "activity", "sessions")
_SESSION_FILE_RE = re.compile(r"^sessions_(.+)_(\d{4}-\d{2}-\d{2})\.(xlsx|xlsm|xlsb|csv)$", re.IGNORECASE)

CU_REF_NAME = "cu_per_session.csv"
CU_REF_COLUMNS = ("department", "division", "activity", "cu_per_session", "target_cu_per_1_0_fte")
COMBINED_CAG_COLUMNS = ("department", "division", "activity", "cag")  # folded lookup into cag_match's Combined sheet

OUT = ("outbox", "cfte")
OUTPUT_STEM = "CFTE_Calculators"
ROLE_SHEETS: dict[str, str] = {"APP": "APP", "Clinical Associate": "Clinical Associate", "Faculty": "Faculty"}
OUTPUT_SHEETS = (*ROLE_SHEETS.values(), "Consolidated", "Summary")
ROW_HEADER = ("Provider", "Role", "Department", "Division", "Activity", "Sessions", "CU per Session",
             "Target CU", "cFTE", "CAG", "Source File", "Source Row", "Flags")
SOURCE_LABEL = "QGenda sessions; cu_per_session reference; CAG_Task_Combined (B18)"


class CfteError(RuntimeError):
    """Base for every cFTE refresh failure the analyst can fix (exit 3)."""


class SessionFileError(CfteError):
    """A sessions export is missing a required column."""


class CuRefError(CfteError):
    """reference/cu_per_session.csv is not UTF-8 or has the wrong header."""


class UnknownRole(CfteError):
    """A sessions row's Role is not APP, Clinical Associate or Faculty (folded)."""

    def __init__(self, role: str, where: str) -> None:
        super().__init__(f"{where}: role {role!r} is none of {', '.join(ROLES)} (add it to cfte.ROLES if she "
                         "uses a fourth label; never guessed)")


# -- primitives -----------------------------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    """Stripped text; None for None, pandas NA, NaN, blank and the literal 'nan' (same defect as cag_match's,
    tests/test_sources_qgenda.py)."""
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except (TypeError, ValueError):
        return None
    if type(value).__name__ == "NAType":
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if not text or text == "nan":
        return None
    return text


def _number(value: Any) -> float | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fold(value: Any) -> str:
    from cpa.sources.base import fold

    return fold(_text(value) or "")


def _key(department: str, division: str | None, activity: str | None) -> tuple[str, str, str]:
    return (department, _fold(division), _fold(activity))


def compute_cfte(sessions: float | None, cu_per_session: float | None, target: float | None) -> float | None:
    """cFTE = sessions * cu_per_session / target, rounded to 4 places; None unless all three inputs are present,
    sessions and CU/session are nonnegative, and target > 0 (never estimated or defaulted)."""
    if (sessions is None or cu_per_session is None or target is None
            or not all(math.isfinite(value) for value in (sessions, cu_per_session, target))
            or sessions < 0 or cu_per_session < 0 or target <= 0):
        return None
    return round(sessions * cu_per_session / target, 4)


# -- data -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionRow:
    """One sessions export row. `sessions` is exactly the source cell (None when blank)."""

    provider: str
    role: str
    department: str
    division: str | None
    activity: str | None
    sessions: float | None
    source_file: str
    source_row: int


@dataclass
class CfteRow:
    """One calculator/consolidated output row."""

    provider: str
    role: str
    department: str
    division: str | None
    activity: str | None
    sessions: float | None
    cu_per_session: float | None
    target: float | None
    cag: str | None
    source_file: str
    source_row: int
    flags: list[str] = field(default_factory=list)

    @property
    def cfte(self) -> float | None:
        return compute_cfte(self.sessions, self.cu_per_session, self.target)


@dataclass
class RunResult:
    workbook: Path
    version: int
    date: str
    by_role: dict[str, list[CfteRow]]
    consolidated: list[CfteRow]
    inputs: list[Path]

    def to_json(self) -> dict:
        from cpa import manifest

        counts = {role: len(rows) for role, rows in self.by_role.items()}
        blanks = {role: sum(1 for r in rows if r.cfte is None) for role, rows in self.by_role.items()}
        return {"workbook": manifest.to_rel(self.workbook), "version": self.version, "date": self.date,
                "row_counts": counts, "blank_counts": blanks, "consolidated_rows": len(self.consolidated),
                "inputs": [manifest.to_rel(p) for p in self.inputs]}


# -- loading --------------------------------------------------------------------------------------------------


def _canonical_department(labels: Sequence[str | None]):
    from cpa import crosswalk

    cw = crosswalk.load()
    offenders = [lab or "" for lab in labels if cw.lookup(lab) is None]
    if offenders:
        raise crosswalk.UnmatchedDepartment(offenders, cw.path)
    return cw


def _canonical_role(role: str | None, where: str) -> str:
    folded = {_fold(r): r for r in ROLES}
    canon = folded.get(_fold(role))
    if canon is None:
        raise UnknownRole(role or "", where)
    return canon


def _rows_from_path(path: Path) -> tuple[list[str], list[list]]:
    """Header row plus data rows of one sessions export, .xlsx/.xlsm/.xlsb via bigxlsx, .csv directly."""
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        return (rows[0] if rows else []), rows[1:]
    from cpa import bigxlsx

    it = bigxlsx.iter_rows(path, None)
    try:
        header = next(it, [])
        return list(header), list(it)
    finally:
        it.close()


def _where(name: str, aliases: dict[str, tuple[str, ...]], header: Sequence[str], required: Sequence[str]) -> dict[str, int]:
    folded = [_fold(h) for h in header]
    where: dict[str, int] = {}
    for col, accepted in aliases.items():
        for i, f in enumerate(folded):
            if f and f in accepted and i not in where.values():
                where[col] = i
                break
    missing = [c for c in required if c not in where]
    if missing:
        raise SessionFileError(f"{name}: no column for {', '.join(missing)} "
                               f"(accepted headers: {'; '.join('/'.join(aliases[c]) for c in missing)})")
    return where


def load_sessions(paths: Sequence[Path]) -> list[SessionRow]:
    """Every non-blank row of each sessions export; departments and roles canonicalised."""
    raw: list[dict] = []
    for p in paths:
        path = Path(p)
        header, data = _rows_from_path(path)
        where = _where(path.name, SESSION_COLUMNS, header, SESSION_REQUIRED)
        for n, row in enumerate(data, start=2):
            rec = {c: (row[i] if i < len(row) else None) for c, i in where.items()}
            vals = {c: _text(v) for c, v in rec.items() if c != "sessions"}
            if not any(vals.values()):
                continue
            raw.append({**vals, "sessions": _number(rec.get("sessions")), "source_file": path.name,
                       "source_row": n})
    cw = _canonical_department([r["department"] for r in raw])
    return [SessionRow(provider=r["provider"] or "", role=_canonical_role(r["role"], f"{r['source_file']} row {r['source_row']}"),
                       department=cw.lookup(r["department"]), division=r["division"], activity=r["activity"],
                       sessions=r["sessions"], source_file=r["source_file"], source_row=r["source_row"])
           for r in raw]


def load_cu_ref(path: Path) -> dict[tuple[str, str, str], tuple[float | None, float | None]]:
    """department/division/activity (folded division and activity) -> (cu_per_session, target). A row whose
    cu_per_session or target cell is blank keeps that side None rather than dropping the row."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise CuRefError(f"{path} does not exist") from exc
    except UnicodeDecodeError as exc:
        raise CuRefError(f"{path} is not UTF-8 ({exc}); re-save it in Excel as 'CSV UTF-8'") from exc
    reader = csv.DictReader(text.splitlines())
    if tuple(reader.fieldnames or ()) != CU_REF_COLUMNS:
        raise CuRefError(f"{path} header must be {','.join(CU_REF_COLUMNS)}; found {reader.fieldnames}")
    out: dict[tuple[str, str, str], tuple[float | None, float | None]] = {}
    for row in reader:
        dept = _text(row.get("department"))
        if dept is None:
            continue
        key = _key(dept, row.get("division"), row.get("activity"))
        out[key] = (_number(row.get("cu_per_session")), _number(row.get("target_cu_per_1_0_fte")))
    return out


def load_combined_cags(path: Path | None) -> dict[tuple[str, str, str], str]:
    """B18's Combined sheet, folded to (department, division, activity) -> CAG. Absent path/file/sheet ->
    empty mapping (R075: cFTE never blocks on B18; enrichment only)."""
    if path is None or not Path(path).is_file():
        return {}
    from cpa import bigxlsx

    path = Path(path)
    try:
        names = bigxlsx.sheet_names(path)
    except Exception:
        return {}
    if "Combined" not in names:
        return {}
    it = bigxlsx.iter_rows(path, "Combined")
    try:
        header = next(it, [])
        folded = [_fold(h) for h in header]
        idx = {}
        for want in ("department", "division", "activity", "cag"):
            for i, f in enumerate(folded):
                if f == want:
                    idx[want] = i
                    break
        if not {"department", "activity", "cag"} <= idx.keys():
            return {}
        out: dict[tuple[str, str, str], str] = {}
        for row in it:
            dept = row[idx["department"]] if idx.get("department") is not None and idx["department"] < len(row) else None
            div = row[idx["division"]] if "division" in idx and idx["division"] < len(row) else None
            act = row[idx["activity"]] if idx["activity"] < len(row) else None
            cag = row[idx["cag"]] if idx["cag"] < len(row) else None
            dept_t, cag_t = _text(dept), _text(cag)
            if dept_t is None or cag_t is None:
                continue
            out[_key(dept_t, div, act)] = cag_t
        return out
    finally:
        it.close()


# -- computation (pure) -----------------------------------------------------------------------------------------


def build_rows(sessions: Sequence[SessionRow], cu_ref: dict[tuple[str, str, str], tuple[float | None, float | None]],
              cag_by_key: dict[tuple[str, str, str], str]) -> list[CfteRow]:
    """One CfteRow per SessionRow; cFTE left blank (via .cfte) unless sessions, cu_per_session and target are
    all present. Never estimated, never defaulted (R005/R129/R161/R175)."""
    rows = []
    for s in sessions:
        key = _key(s.department, s.division, s.activity)
        ref = cu_ref.get(key)
        flags: list[str] = []
        cu = target = None
        if ref is None:
            flags += ["MISSING_CU_PER_SESSION", "MISSING_TARGET"]
        else:
            cu, target = ref
            if cu is None:
                flags.append("MISSING_CU_PER_SESSION")
            if target is None:
                flags.append("MISSING_TARGET")
        if s.sessions is None:
            flags.append("MISSING_SESSIONS")
        cag = cag_by_key.get(key)
        if cag is None:
            flags.append("CAG_NOT_FOUND")
        rows.append(CfteRow(provider=s.provider, role=s.role, department=s.department, division=s.division,
                            activity=s.activity, sessions=s.sessions, cu_per_session=cu, target=target, cag=cag,
                            source_file=s.source_file, source_row=s.source_row, flags=flags))
    return rows


def split_by_role(rows: Sequence[CfteRow]) -> dict[str, list[CfteRow]]:
    """The three calculators: rows grouped by role, in `ROLES` order."""
    return {role: [r for r in rows if r.role == role] for role in ROLES}


def consolidate(by_role: dict[str, list[CfteRow]]) -> list[CfteRow]:
    """The consolidated reference: the union of the three calculators (R130) - one row per session row,
    whichever role it fell under, in ROLES order then source order."""
    out: list[CfteRow] = []
    for role in ROLES:
        out.extend(by_role.get(role, ()))
    return out


# -- files ----------------------------------------------------------------------------------------------------


def _root(root: Path | None) -> Path:
    if root is not None:
        return Path(root)
    from cpa import config

    return config.workspace()


def _session_files(root: Path) -> list[tuple[Path, str]]:
    folder = root / "inbox" / "qgenda"
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.iterdir()):
        m = _SESSION_FILE_RE.match(p.name)
        if m and p.is_file():
            out.append((p, m.group(2)))
    return out


def default_sessions(root: Path, date: str | None) -> tuple[list[Path], str]:
    """Sessions exports for `date` (YYYY-MM-DD); with no date, those for the latest date present."""
    files = _session_files(root)
    if date is None:
        if not files:
            raise CfteError(f"no sessions export (sessions_<dept>_<YYYY-MM-DD>.xlsx) in "
                            f"{root / 'inbox' / 'qgenda'}; land one or pass --sessions")
        date = max(d for _, d in files)
    chosen = [p for p, d in files if d == date]
    if not chosen:
        raise CfteError(f"no sessions export dated {date} in {root / 'inbox' / 'qgenda'}; pass --sessions")
    return chosen, date


def next_version(root: Path) -> int:
    """1 + the highest N over outbox/cfte/*/CFTE_Calculators_v<N>.xlsx; 1 when there is none."""
    pat = re.compile(rf"^{OUTPUT_STEM}_v(\d+)\.xlsx$")
    base = root.joinpath(*OUT)
    found = [int(m.group(1)) for p in base.glob("*/*.xlsx") if (m := pat.match(p.name))] if base.is_dir() else []
    return max(found, default=0) + 1


def _default_combined(root: Path) -> Path | None:
    """The newest cag_match Combined workbook under outbox/cag, else None (R075: optional enrichment)."""
    base = root / "outbox" / "cag"
    if not base.is_dir():
        return None
    hits = sorted(base.glob("*/CAG_Task_Combined_v*.xlsx"))
    return hits[-1] if hits else None


def _row_values(r: CfteRow) -> list:
    return [r.provider, r.role, r.department, r.division, r.activity, r.sessions, r.cu_per_session, r.target,
           r.cfte, r.cag, r.source_file, r.source_row, "; ".join(dict.fromkeys(r.flags)) or None]


def write_workbook(by_role: dict[str, list[CfteRow]], consolidated: list[CfteRow], path: Path, *, period: str,
                   as_of: str) -> dict[str, tuple[str, str, int]]:
    """Write the calculator, consolidated and summary sheets. Returns {figure id: (Summary cell, source ref,
    value)} for figures that tie to a detail sheet's row count."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    from cpa import fsutil
    from cpa.pptx import brand

    header_fill = PatternFill("solid", fgColor=brand.color("navy").lstrip("#"))
    header_font = Font(name=brand.FONT, bold=True, color="FFFFFF")
    body_font = Font(name=brand.FONT)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    cfte_col = ROW_HEADER.index("cFTE") + 1

    def head(ws, header: Sequence[str]) -> None:
        ws.append(list(header))
        for c in range(1, len(header) + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill, cell.font = header_fill, header_font
            ws.column_dimensions[get_column_letter(c)].width = max(12, len(header[c - 1]) + 2)

    def put(ws, values: Sequence[Any]) -> None:
        ws.append(list(values))
        r = ws.max_row
        for c in range(1, len(values) + 1):
            ws.cell(row=r, column=c).font = body_font
            if c == cfte_col and values[c - 1] is None:
                ws.cell(row=r, column=c).value = None  # genuinely empty, never 0 or a formula

    for role, name in ROLE_SHEETS.items():
        ws = wb.create_sheet(name)
        head(ws, ROW_HEADER)
        for r in by_role.get(role, ()):
            put(ws, _row_values(r))
        # Verification's row-count tie-out needs a numeric source cell, not the Flags text column.
        ws["O1"] = len(by_role.get(role, ()))
        ws.column_dimensions["O"].hidden = True

    ws = wb.create_sheet("Consolidated")
    head(ws, ROW_HEADER)
    for r in consolidated:
        put(ws, _row_values(r))
    ws["O1"] = len(consolidated)
    ws.column_dimensions["O"].hidden = True

    metrics = [("Source session rows", None, len(consolidated))]
    detail_refs: dict[str, tuple[str, int, int]] = {"consolidated": ("Consolidated", len(consolidated), len(ROW_HEADER))}
    for role, name in ROLE_SHEETS.items():
        rows = by_role.get(role, ())
        blanks = sum(1 for r in rows if r.cfte is None)
        fid = f"rows_{role.lower().replace(' ', '_')}"
        metrics.append((f"{name} rows", fid, len(rows)))
        metrics.append((f"{name} rows with blank cFTE", None, blanks))
        detail_refs[fid] = (name, len(rows), len(ROW_HEADER))
    metrics.append(("Consolidated rows", "consolidated", len(consolidated)))
    metrics.append(("Consolidated rows with blank cFTE", None, sum(1 for r in consolidated if r.cfte is None)))

    ws = wb.create_sheet("Summary")
    head(ws, ("Metric", "Value", "Period", "Status", "Source", "As of"))
    figures: dict[str, tuple[str, str, int]] = {}
    for label, fid, value in metrics:
        put(ws, [label, value, period, "actual", SOURCE_LABEL, as_of])
        if fid:
            sheet, _, _ = detail_refs[fid]
            figures[fid] = (f"Summary!B{ws.max_row}", f"{sheet}!O1", value)
    ws.column_dimensions["A"].width = 32

    for sheet in wb.worksheets:
        brand.style_generated_sheet(sheet)
    path.parent.mkdir(parents=True, exist_ok=True)
    office.save_workbook(wb, path)
    wb.close()
    return figures


def run(*, root: Path | None = None, date: str | None = None, sessions: Sequence[Path] | None = None,
       cu_per_session: Path | None = None, combined: Path | None = None) -> RunResult:
    """Load, compute the three calculators and the consolidated reference, write
    outbox/cfte/<date>/CFTE_Calculators_v<N>.xlsx with its manifest and Verification tab. Never overwrites
    an earlier version."""
    from cpa import config, fsutil, manifest, verify

    ws = _root(root)
    if date is not None:
        _date.fromisoformat(date)
    if sessions:
        session_paths = [Path(p) for p in sessions]
        date = date or _date.today().isoformat()
    else:
        session_paths, date = default_sessions(ws, date)
    cu_ref_path = Path(cu_per_session) if cu_per_session else config.reference_file(CU_REF_NAME)
    combined_path = Path(combined) if combined else _default_combined(ws)

    session_rows = load_sessions(session_paths)
    cu_ref = load_cu_ref(cu_ref_path)
    cag_by_key = load_combined_cags(combined_path)
    rows = build_rows(session_rows, cu_ref, cag_by_key)
    by_role = split_by_role(rows)
    consolidated = consolidate(by_role)

    version = next_version(ws)
    out = ws.joinpath(*OUT, date) / fsutil.safe_filename(f"{OUTPUT_STEM}_v{version}.xlsx")
    if out.exists():
        raise CfteError(f"{out} already exists; never overwritten")
    figures = write_workbook(by_role, consolidated, out, period=date, as_of=date)
    inputs = [cu_ref_path, *session_paths, *([combined_path] if combined_path else [])]
    manifest.write(out, SOURCE_LABEL, OUTPUT_STEM, f"date={date}", date, inputs=inputs, period=date,
                   status="actual", version=version)
    for fid, (cell, ref, value) in figures.items():
        manifest.add_figure(out, fid, value, out, ref, cell=cell, status="actual", period=date)
    verify.build_verification_tab(out)
    return RunResult(out, version, date, by_role, consolidated, inputs)


# -- CLI ------------------------------------------------------------------------------------------------------


def _cmd_refresh(args: argparse.Namespace) -> int:
    from cpa import config, crosswalk, manifest
    from cpa.sources.base import SourceError

    try:
        res = run(root=Path(args.root) if args.root else None, date=args.date,
                 sessions=[Path(p) for p in args.sessions] if args.sessions else None,
                 cu_per_session=Path(args.cu_per_session) if args.cu_per_session else None,
                 combined=Path(args.combined) if args.combined else None)
    except (CfteError, config.ConfigError, crosswalk.CrosswalkError, SourceError, manifest.ManifestError,
           FileNotFoundError, ValueError) as exc:
        print(f"cfte: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(res.to_json(), indent=2))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """`cfte refresh`. Import-cheap: no I/O and no third-party import here."""
    top = subparsers.add_parser("cfte", help="cFTE calculator refresh (B19).")
    sub = top.add_subparsers(dest="command", required=True)
    p = sub.add_parser(
        "refresh",
        help="Refresh the APP, Clinical Associate and Faculty cFTE calculators plus the consolidated "
            "reference; cFTE is blank without every input.",
        description="Writes outbox/cfte/<date>/CFTE_Calculators_v<N>.xlsx and prints JSON with row and "
                    "blank-cFTE counts per calculator. Exit 0 clean, 3 input error.",
    )
    p.add_argument("--date", help="YYYY-MM-DD of the sessions exports (default: latest in inbox/qgenda).")
    p.add_argument("--sessions", nargs="+", help="Sessions export files (default: inbox/qgenda for --date).")
    p.add_argument("--cu-per-session", help=f"CU-per-session reference (default: reference/{CU_REF_NAME}).")
    p.add_argument("--combined", help="B18 CAG_Task_Combined workbook for CAG enrichment (default: newest "
                                      "under outbox/cag; optional).")
    p.add_argument("--root", help="Workspace folder (default: the configured workspace).")
    p.set_defaults(func=_cmd_refresh)
