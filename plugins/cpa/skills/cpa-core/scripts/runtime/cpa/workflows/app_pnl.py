"""APP P&L populate (B4): fill the APP P&L v5 template for one position; locked cells never change.

FIXTURE — confirm against her file: every address in reference/template_maps/app_pnl_v5.yaml describes the
generated fixture template (tests/fixtures/gen_app_pnl_template.py), and the shapes of pnl_inputs.json,
collection_rate.json and sc_points.json are this unit's contract until a source reader exists (U09, SullivanCotter).

Build-list items: B4 APP P&L populate (guide 5.6 cpa-app-pnl, guide 9 app_pnl.py, guide 13.16), the guide 7.2
cpa-app-pnl readiness rule (READINESS_RULES, DECISIONS D19). Hard rules enforced: 1 (TCC = base + supplements, never
fringe: cpa.benchmarks.tcc, and the supplements input cell is TCC - base), 2 and 3 (SullivanCotter 2025 AMC only,
specific interpolated percentiles: cpa.benchmarks), 5/7 (a missing narrative metric is a yellow MISSING flag, never
blank, never estimated; every figure carries period, status, source and as-of), 15 (a null rate stops the run; an
unmapped specialty stops for a human). Rules: R046 (the department never gets a benchmark cell), R048/R093/R232
(locked-cell diff against the template is zero, checked before the workbook reaches outbox and again after
verify's recalculation), R050 (a missing collection rate is a yellow placeholder and the run continues), R111
(inputs go only into unlocked, input-filled cells), R171 (three years only).

Order (build_detailed): read and validate every input, the map, the rates and the specialty (nothing copied yet);
write the inputs into the in-memory template and save a work copy under staging/app/<position>/work/; recalculate a
temp copy to read the named rows and Year-1 activity; write the SullivanCotter rows and the M2 block (cpa.
activity_block); gate 1 (locked-cell diff); copy to outbox/app/<cycle>/<position>/PnL.xlsx with its manifest and
pnl_figures.csv; verify (cpa.verify); gate 2; pnl_flags.json for the slide unit. Conventions: DECISIONS D26.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from cpa import state

__all__ = [
    "WORKFLOW", "MAP_NAME", "OUTPUT_NAME", "FAILED_NAME", "YEARS", "TRIAGE_NAME", "INPUTS_NAME", "RATE_NAME",
    "POINTS_NAME", "FLAGS_NAME", "FIGURES_NAME", "READY_CLASSES", "BENCHMARK_WORDS", "READINESS_RULES",
    "AppPnlError", "TemplateMapError", "TemplateMismatch", "NotAnInputCell", "BenchmarkInputCell",
    "PositionInputError", "MissingInput", "AmbiguousInput", "ScPointsMismatch", "LockedCellChanged",
    "CellChange", "PnlFlag", "PositionInputs", "BuildResult",
    "load_map", "load_inputs", "triage_class", "find_cpt_profile", "read_cpt_profile", "read_collection_rate",
    "read_points", "diff_locked_cells", "inspect_template", "build_detailed", "build", "register",
]

WORKFLOW = "cpa-app-pnl"
MAP_NAME = "app_pnl_v5"
OUTPUT_NAME = "PnL.xlsx"
FAILED_NAME = "PnL.LOCKED_CELLS_CHANGED.xlsx"
YEARS = 3  # inventory :327 "Three years only"
TRIAGE_NAME = "triage.md"
INPUTS_NAME = "pnl_inputs.json"
RATE_NAME = "collection_rate.json"
POINTS_NAME = "sc_points.json"
FLAGS_NAME = "pnl_flags.json"
FIGURES_NAME = "pnl_figures.csv"
READY_CLASSES = ("COMPLETE", "FIXABLE")
BENCHMARK_WORDS = ("benchmark", "percentile", "sullivancotter", "sullivan cotter")  # R046 label guard
RATE_UNITS = ("pct", "fraction")
COLLECTION_BASES = ("gross", "net")
REPORT = "APP P&L v5"
STATUS = "projected"
BENCH_TITLE = "SullivanCotter benchmarks (2025 AMC)"
BENCH_HEADERS = ("Metric", "Value (Year 1)", "Percentile", "Statement", "Specialty (survey column)")
BENCH_LABELS = {"TCC": "TCC (base + supplements, no fringe)", "Work RVUs": "Work RVUs"}
NAMED_ROWS = ("jhu_contribution_margin", "division_surplus")
READ_ROWS = ("jhu_contribution_margin", "division_surplus", "wrvus", "charges", "collections")
CPT_FIELDS = ("cpt", "description", "volume", "wrvu", "charge")
CPT_NUMERIC = ("volume", "wrvu", "charge")
EXIT_OK, EXIT_ISSUES, EXIT_STOPPED, EXIT_UNMAPPED = 0, 1, 2, 3
_TRIAGE_RE = re.compile(r"^Classification: \*\*([A-Z]+)\*\*", re.MULTILINE)
_REF_RE = re.compile(r"^(?:'((?:[^']|'')+)'|([^!]+))!\$?([A-Za-z]{1,3})\$?(\d+)$")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class AppPnlError(RuntimeError):
    """Base for every app_pnl failure. Raised before anything reaches outbox, except a gate-2 LockedCellChanged."""


class TemplateMapError(AppPnlError):
    """reference/template_maps/app_pnl_v5.yaml is missing a field or holds a malformed one."""


class TemplateMismatch(AppPnlError):
    """The template disagrees with the map or with v5 (not three years, a label or sheet absent, an appended region
    not empty, the fixture map pointed at a non-fixture template), or a source does not fit the template."""


class NotAnInputCell(AppPnlError):
    """A mapped input cell is locked, or unlocked without the template's input fill (R111)."""


class BenchmarkInputCell(AppPnlError):
    """The template offers the department a benchmark cell: an unlocked cell labelled benchmark/percentile/
    SullivanCotter, or an unlocked cell inside the benchmark region (R046)."""


class PositionInputError(AppPnlError):
    """pnl_inputs.json, collection_rate.json, sc_points.json or the CPT profile is present but malformed."""


class MissingInput(AppPnlError):
    """A required input (template, triage, pnl_inputs.json, the division's CPT profile) is absent or not ready."""


class AmbiguousInput(AppPnlError):
    """Two CPT profiles for the division share the newest as-of date."""


class ScPointsMismatch(AppPnlError):
    """sc_points.json names a different SullivanCotter specialty than the specialty map resolves (R002)."""


class LockedCellChanged(AppPnlError):
    """The locked-cell diff against the template is not empty (R232). `.changes` lists them; `.stage` is
    'before recalc' (nothing reached outbox) or 'after recalc' (the output was renamed FAILED_NAME)."""

    def __init__(self, message: str, changes: list, stage: str) -> None:
        super().__init__(message)
        self.changes = list(changes)
        self.stage = stage


@dataclass(frozen=True)
class CellChange:
    """One locked-cell difference between the template and an output."""

    sheet: str
    cell: str
    kind: str  # value | formula | protection | sheet protection | sheet removed | sheet added
    before: Any = None
    after: Any = None

    def line(self) -> str:
        where = f"{self.sheet}!{self.cell}" if self.cell else self.sheet
        return f"{where}: {self.kind} changed (template {self.before!r}, output {self.after!r})"

    def to_json(self) -> dict:
        return {"sheet": self.sheet, "cell": self.cell, "kind": self.kind, "before": _jsonable(self.before),
                "after": _jsonable(self.after)}


@dataclass(frozen=True)
class PnlFlag:
    """Something the build could not fill (or dropped) and says so: kind collection_rate | benchmark | m2 |
    fringe_excluded | locked_cells_changed."""

    kind: str
    cell: str
    text: str

    def to_json(self) -> dict:
        return {"kind": self.kind, "cell": self.cell, "text": self.text}


@dataclass(frozen=True)
class PositionInputs:
    """staging/app/<position>/pnl_inputs.json, written by the cpa-app-pnl skill from her confirmed figures.
    `supplements` are non-fringe cash components only (the skill classifies; benchmarks.tcc is the backstop)."""

    path: Path
    position_id: str
    cycle: str | None
    department: str
    division: str
    role: str
    plan_period: str
    as_of: str
    base_salary: float
    supplements: dict
    cfte: dict | None


@dataclass
class BuildResult:
    """What build_detailed produced. `values[row][year]` are read from this run's own recalculation (None when
    not recalculated); `statements` holds one cpa.benchmarks PercentileResult per metric that could be stated."""

    workbook: Path
    verify_summary: str = ""
    verify_issues: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    statements: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    excluded_fringe: tuple = ()
    included_supplements: tuple = ()
    warnings: list = field(default_factory=list)
    recalc_reason: str = ""

    def to_json(self) -> dict:
        from cpa import manifest

        return {
            "workbook": manifest.to_rel(self.workbook), "summary": self.verify_summary,
            "verify_issues": list(self.verify_issues), "flags": [f.to_json() for f in self.flags],
            "statements": {m: r.statement for m, r in self.statements.items()},
            "values": {k: {str(y): v for y, v in d.items()} for k, d in self.values.items()},
            "excluded_fringe": list(self.excluded_fringe), "included_supplements": list(self.included_supplements),
            "warnings": list(self.warnings), "recalc_reason": self.recalc_reason,
        }


# ---------------------------------------------------------------- small helpers


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _ref(text: Any, what: str) -> tuple[str, str]:
    m = _REF_RE.match(str(text or "").strip())
    if not m:
        raise TemplateMapError(f"{what}: {text!r} is not a Sheet!A1 reference")
    sheet = (m.group(1) or "").replace("''", "'") or m.group(2)
    return sheet, f"{m.group(3).upper()}{m.group(4)}"


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _as_number(v: Any) -> float | None:
    return float(v) if _is_number(v) else None


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


def _slug(text: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text or "").casefold())


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise PositionInputError(f"{path.name} is not valid JSON ({exc}); fix {what} and rerun") from exc


def _iso(value: Any, what: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise PositionInputError(f"{what} must be an ISO date YYYY-MM-DD, got {value!r}") from exc


def _rgb(cell) -> str:
    fill = cell.fill
    if fill is None or fill.fill_type is None:
        return ""
    rgb = getattr(fill.fgColor, "rgb", None)
    return rgb.upper() if isinstance(rgb, str) else ""


def _money(v: float | None) -> str:
    return "n/a" if v is None else (f"-${-v:,.0f}" if v < 0 else f"${v:,.0f}")


def _stage(ws: Path, position_id: str) -> Path:
    return ws / "staging" / "app" / position_id


# ---------------------------------------------------------------- map and inputs


def load_map() -> dict:
    """The template map (workspace copy first, cpa.config.template_map); TemplateMapError lists every problem."""
    from cpa import config

    tmap = config.template_map(MAP_NAME)
    problems: list[str] = []
    for key in ("template", "input_fill", "pnl_sheet", "label_column", "years", "inputs", "rates",
                "collection_rate", "cpt_profile", "rows", "benchmarks", "m2"):
        if tmap.get(key) is None:
            problems.append(f"{key} is missing")
    if not problems:
        cols = (tmap["years"] or {}).get("columns")
        if not isinstance(cols, list) or not (tmap["years"] or {}).get("header_row"):
            problems.append("years needs header_row and a columns list")
        for name in ("base_salary", "supplements_total"):
            if not (tmap["inputs"] or {}).get(name):
                problems.append(f"inputs.{name} is missing")
        if not isinstance(tmap["rates"], list):
            problems.append("rates must be a list of {key, cell, unit}")
        else:
            for i, r in enumerate(tmap["rates"]):
                if not isinstance(r, dict) or not r.get("key") or not r.get("cell") or r.get("unit") not in RATE_UNITS:
                    problems.append(f"rates[{i}] needs key, cell and unit pct|fraction")
        cr = tmap["collection_rate"] or {}
        if not cr.get("cell") or cr.get("unit") not in RATE_UNITS:
            problems.append("collection_rate needs cell and unit pct|fraction")
        cpt = tmap["cpt_profile"] or {}
        if not cpt.get("sheet") or not cpt.get("first_row") or not cpt.get("last_row") or \
                set(cpt.get("columns") or {}) < set(CPT_FIELDS) or \
                set(((cpt.get("source") or {}).get("headers")) or {}) < set(CPT_FIELDS):
            problems.append(f"cpt_profile needs sheet, first_row, last_row, columns and source.headers for "
                            f"{', '.join(CPT_FIELDS)}")
        rows = tmap["rows"] or {}
        for name in READ_ROWS:
            spec = rows.get(name) or {}
            if not spec.get("row") or not spec.get("label"):
                problems.append(f"rows.{name} needs row and label")
        if (rows.get("collections") or {}).get("basis") not in COLLECTION_BASES:
            problems.append("rows.collections.basis must be gross or net (hard rule: always labelled)")
        if not (tmap["benchmarks"] or {}).get("region"):
            problems.append("benchmarks.region is missing")
        if not (tmap["m2"] or {}).get("anchor") or not (tmap["m2"] or {}).get("region"):
            problems.append("m2 needs anchor and region")
    if problems:
        raise TemplateMapError(f"template map {MAP_NAME}.yaml: " + "; ".join(problems) +
                               ". Fill it from `python -m cpa app_pnl inspect --template <her v5>`")
    return tmap


def load_inputs(position_id: str, ws: Path | None = None) -> PositionInputs:
    """Read and validate staging/app/<position>/pnl_inputs.json."""
    from cpa import config, fsutil

    try:
        fsutil.safe_filename(position_id)
    except fsutil.UnsafeFilename as exc:
        raise PositionInputError(f"position id {position_id!r} is not usable as a folder name: {exc}") from exc
    ws = ws or config.workspace()
    path = _stage(ws, position_id) / INPUTS_NAME
    if not path.is_file():
        raise MissingInput(f"{manifest_rel(path)} not found: the cpa-app-pnl skill writes it from the confirmed "
                           "submission figures before `app_pnl build`")
    data = _read_json(path, INPUTS_NAME)
    if not isinstance(data, dict):
        raise PositionInputError(f"{path.name} must be a JSON object")
    missing = [k for k in ("position_id", "department", "division", "role", "plan_period", "as_of", "base_salary",
                           "supplements") if data.get(k) in (None, "")]
    if missing:
        raise PositionInputError(f"{path.name} is missing {', '.join(missing)}")
    if str(data["position_id"]) != position_id:
        raise PositionInputError(f"{path.name} is for position {data['position_id']!r}, not {position_id!r}")
    if not _is_number(data["base_salary"]):
        raise PositionInputError(f"{path.name}: base_salary must be a number, got {data['base_salary']!r}")
    if not isinstance(data["supplements"], dict):
        raise PositionInputError(f"{path.name}: supplements must be an object of name -> amount")
    cfte = data.get("cfte")
    if cfte is not None and not isinstance(cfte, dict):
        raise PositionInputError(f"{path.name}: cfte must be null or an object with value, period, status, "
                                 "source and as_of")
    cycle = data.get("cycle")
    return PositionInputs(path=path, position_id=position_id, cycle=_iso(cycle, "cycle") if cycle else None,
                          department=str(data["department"]), division=str(data["division"]),
                          role=str(data["role"]), plan_period=str(data["plan_period"]),
                          as_of=_iso(data["as_of"], f"{path.name} as_of"), base_salary=float(data["base_salary"]),
                          supplements=dict(data["supplements"]), cfte=cfte)


def manifest_rel(path: Path) -> str:
    from cpa import manifest

    return manifest.to_rel(path)


def triage_class(stage: Path) -> str | None:
    """The classification U11 wrote in staging/app/<position>/triage.md, or None when there is none."""
    path = stage / TRIAGE_NAME
    if not path.is_file():
        return None
    m = _TRIAGE_RE.search(path.read_text(encoding="utf-8-sig"))
    return m.group(1) if m else None


def _profile_division(path: Path) -> str:
    from cpa import manifest

    if manifest.exists(path):
        try:
            div = manifest.read(path).get("division")
        except (OSError, ValueError, manifest.ManifestError):
            div = None
        if div:
            return str(div)
    stem = path.name.split(".")[0][len("cpt_profile_"):]
    m = _DATE_RE.search(stem)
    return stem[:m.start()].rstrip("_") if m else stem


def _profile_as_of(path: Path) -> str:
    from cpa import manifest

    if manifest.exists(path):
        try:
            as_of = manifest.read(path).get("as_of")
        except (OSError, ValueError, manifest.ManifestError):
            as_of = None
        if as_of:
            return str(as_of)
    m = _DATE_RE.search(path.name)
    return m.group(1) if m else ""


def find_cpt_profile(ws: Path, division: str) -> Path:
    """The newest inbox/medvitals/cpt_profile_*.xlsx for the division (A7: the manifest's `division`, else the
    filename token, compared ignoring case, spaces and punctuation). None -> MissingInput; a tie -> AmbiguousInput."""
    from cpa import manifest

    folder = ws / "inbox" / "medvitals"
    found = sorted(p for p in folder.glob("cpt_profile_*") if p.is_file() and not manifest.is_sidecar(p)
                   and p.suffix.lower() in (".xlsx", ".xlsm", ".xlsb")) if folder.is_dir() else []
    want = _slug(division)
    hits = [p for p in found if _slug(_profile_division(p)) == want]
    if not hits:
        raise MissingInput(f"no MedVitals CPT Billing Profile for division {division!r} in inbox/medvitals "
                           f"(cpt_profile_<division>_<date>.xlsx with the division in its manifest, A7); "
                           f"seen: {', '.join(p.name for p in found) or 'none'}")
    hits.sort(key=_profile_as_of, reverse=True)
    if len(hits) > 1 and _profile_as_of(hits[0]) == _profile_as_of(hits[1]):
        raise AmbiguousInput(f"{hits[0].name} and {hits[1].name} are both the newest CPT profile for {division!r}; "
                             "archive one and rerun")
    return hits[0]


def read_cpt_profile(path: Path, spec: dict) -> list[dict]:
    """Rows of the CPT profile export as {field: value}, streamed (hard rule 11). Blank rows are skipped; a row
    with amounts but no CPT code, or a non-numeric amount, stops the run naming the row."""
    from cpa import bigxlsx

    src = spec.get("source") or {}
    headers = {f: _norm(src["headers"][f]) for f in CPT_FIELDS}
    header_row = int(src.get("header_row") or 1)
    rows = bigxlsx.iter_rows(path, src.get("sheet"))
    out: list[dict] = []
    index: dict[str, int] = {}
    try:
        for n, row in enumerate(rows, start=1):
            if n < header_row:
                continue
            if n == header_row:
                seen = [_norm(v) for v in row]
                missing = [src["headers"][f] for f in CPT_FIELDS if headers[f] not in seen]
                if missing:
                    raise PositionInputError(f"{path.name} row {n} lacks the header(s) {missing} (seen: "
                                             f"{[v for v in row if v not in (None, '')]}); correct cpt_profile."
                                             "source.headers in the template map")
                index = {f: seen.index(headers[f]) for f in CPT_FIELDS}
                continue
            rec = {f: (row[i] if i < len(row) else None) for f, i in index.items()}
            if all(v in (None, "") for v in rec.values()):
                continue
            if rec["cpt"] in (None, ""):
                raise PositionInputError(f"{path.name} row {n} has amounts but no CPT code (a total row?); remove it "
                                         "from the export or fix the row, then rerun")
            for f in CPT_NUMERIC:
                if not _is_number(rec[f]):
                    raise PositionInputError(f"{path.name} row {n}: {src['headers'][f]} must be a number, got "
                                             f"{rec[f]!r}")
            out.append(rec)
    finally:
        rows.close()
    if not index:
        raise PositionInputError(f"{path.name} has no header row {header_row}")
    return out


def read_collection_rate(path: Path) -> dict | None:
    """collection_rate.json (A2): {value, unit pct|fraction, bill_area, as_of}; None when the file is absent."""
    if not path.is_file():
        return None
    data = _read_json(path, RATE_NAME)
    if not isinstance(data, dict):
        raise PositionInputError(f"{path.name} must be a JSON object")
    value, unit = data.get("value"), data.get("unit")
    if not _is_number(value):
        raise PositionInputError(f"{path.name}: value must be a number, got {value!r}")
    if unit not in RATE_UNITS:
        raise PositionInputError(f"{path.name} must state unit 'pct' (62) or 'fraction' (0.62) next to the value; "
                                 f"got {unit!r}")
    ok = 0 < value <= 1 if unit == "fraction" else 1 < value <= 100
    if not ok:
        bounds = "0 < value <= 1" if unit == "fraction" else "1 < value <= 100"
        raise PositionInputError(f"{path.name}: value {value} is not a {unit} ({bounds}); correct the value or unit")
    for key in ("bill_area", "as_of"):
        if not data.get(key):
            raise PositionInputError(f"{path.name} is missing {key} (A2: bill area named, as-of captured)")
    data["as_of"] = _iso(data["as_of"], f"{path.name} as_of")
    return data


def read_points(path: Path, specialty: str) -> dict:
    """sc_points.json -> {metric: {percentile: value}} for the 2025 AMC column only (cpa.benchmarks); {} when absent.
    A metric left out of the file is simply absent (a flagged placeholder row later)."""
    from cpa import benchmarks

    if not path.is_file():
        return {}
    data = _read_json(path, POINTS_NAME)
    if not isinstance(data, dict):
        raise PositionInputError(f"{path.name} must be a JSON object")
    if _norm(data.get("specialty")) != _norm(specialty):
        raise ScPointsMismatch(f"{path.name} holds points for {data.get('specialty')!r} but the specialty map resolves "
                               f"this position to {specialty!r}; transcribe that specialty's {benchmarks.SURVEY_COLUMN} "
                               "points")
    out: dict = {}
    for metric in benchmarks.METRICS:
        table = data.get(metric)
        if table is None:
            continue
        if not isinstance(table, dict):
            raise PositionInputError(f"{path.name}: {metric} must be an object of survey column -> points")
        out[metric] = benchmarks.select_2025_amc(table)
    return out


def _convert(value: float, have: str, want: str) -> float:
    if have == want:
        return float(value)
    return float(value) / 100.0 if want == "fraction" else float(value) * 100.0


# ---------------------------------------------------------------- template checks


def _regions(tmap: dict) -> tuple[str, str]:
    sheet = str(tmap["pnl_sheet"])
    return f"{sheet}!{tmap['benchmarks']['region']}", f"{sheet}!{tmap['m2']['region']}"


def _split_region(text: str) -> tuple[str | None, tuple[int, int, int, int]]:
    from openpyxl.utils.cell import range_boundaries

    sheet, _, rng = str(text).rpartition("!")
    return (sheet.strip("'") or None), range_boundaries(rng)


def _in(regions: list, sheet: str, row: int, col: int) -> bool:
    for rsheet, (c1, r1, c2, r2) in regions:
        if (rsheet is None or rsheet == sheet) and r1 <= row <= r2 and c1 <= col <= c2:
            return True
    return False


def _input_cells(tmap: dict) -> list[tuple[str, str, str]]:
    """(what, sheet, cell) for every cell the map says the script writes."""
    cells = [(f"inputs.{k}", *_ref(v, f"inputs.{k}")) for k, v in (tmap["inputs"] or {}).items() if v]
    cells += [(f"rates {r['key']}", *_ref(r["cell"], f"rates {r['key']}")) for r in tmap["rates"]]
    cells.append(("collection_rate", *_ref(tmap["collection_rate"]["cell"], "collection_rate.cell")))
    cpt = tmap["cpt_profile"]
    for f in CPT_FIELDS:
        letter = str(cpt["columns"][f]).upper()
        for r in range(int(cpt["first_row"]), int(cpt["last_row"]) + 1):
            cells.append((f"cpt_profile.{f}", str(cpt["sheet"]), f"{letter}{r}"))
    return cells


def _check_template(wb, tmap: dict, template: Path, warnings: list[str]) -> None:
    """Every structural check, on the in-memory template, before anything is written (R046, R111, R171)."""
    from openpyxl.utils import column_index_from_string, get_column_letter

    if tmap.get("fixture"):
        marker = tmap.get("fixture_marker") or {}
        msheet, mcell = _ref(marker.get("cell"), "fixture_marker.cell")
        value = wb[msheet][mcell].value if msheet in wb.sheetnames else None
        if not str(value or "").startswith(str(marker.get("startswith") or "FIXTURE")):
            raise TemplateMismatch(
                f"the template map is still the FIXTURE map (fixture: true) but {template.name} is not the fixture "
                f"template ({msheet}!{mcell} = {value!r}); fill the map from `python -m cpa app_pnl inspect` and set "
                "fixture: false")
    sheet = str(tmap["pnl_sheet"])
    if sheet not in wb.sheetnames:
        raise TemplateMismatch(f"{template.name} has no tab {sheet!r} (pnl_sheet in the template map)")
    ws = wb[sheet]
    years = tmap["years"]
    cols = [str(c).upper() for c in years["columns"]]
    if len(cols) != YEARS:
        raise TemplateMismatch(f"APP P&L v5 has three years only (R171); the template map lists {len(cols)} year "
                               f"columns {cols}")
    hrow = int(years["header_row"])
    for c in cols:
        if ws[f"{c}{hrow}"].value in (None, ""):
            raise TemplateMismatch(f"{sheet}!{c}{hrow} is empty; the map says it heads a year column")
    nxt = f"{get_column_letter(column_index_from_string(cols[-1]) + 1)}{hrow}"
    if ws[nxt].value not in (None, ""):
        raise TemplateMismatch(f"APP P&L v5 has three years only (R171); {sheet}!{nxt} holds {ws[nxt].value!r}, a "
                               "fourth year column")
    label_col = str(tmap["label_column"]).upper()
    for name in READ_ROWS:
        spec = tmap["rows"][name]
        text = ws[f"{label_col}{spec['row']}"].value
        if not _norm(text).startswith(_norm(spec["label"])):
            raise TemplateMismatch(f"{sheet}!{label_col}{spec['row']} reads {text!r}; the map expects the "
                                   f"{spec['label']!r} row there")
        if name in NAMED_ROWS:
            for c in cols:
                v = ws[f"{c}{spec['row']}"].value
                if not (isinstance(v, str) and v.startswith("=")):
                    raise TemplateMismatch(f"{sheet}!{c}{spec['row']} ({spec['label']}) is not a template formula; "
                                           "the named rows are computed by her formulas, never written")
    fill = str(tmap["input_fill"]).lstrip("#").upper()[-6:]
    for what, s, c in _input_cells(tmap):
        if s not in wb.sheetnames:
            raise TemplateMismatch(f"{what}: {template.name} has no tab {s!r}")
        cell = wb[s][c]
        if cell.protection.locked:
            raise NotAnInputCell(f"{what} maps to {s}!{c}, which is locked in the template; the script writes only "
                                 "unlocked input cells (R111). Correct the template map")
        if not _rgb(cell).endswith(fill):
            raise NotAnInputCell(f"{what} maps to {s}!{c}, which is unlocked but its fill {_rgb(cell) or 'none'} is "
                                 f"not the input fill {fill}; correct the template map (R111)")
    bench, m2 = _regions(tmap)
    for which, region in (("benchmarks", bench), ("m2", m2)):
        rsheet, (c1, r1, c2, r2) = _split_region(region)
        target = wb[rsheet or sheet]
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cell = target.cell(row=r, column=c)
                if not cell.protection.locked:
                    if which == "benchmarks":
                        raise BenchmarkInputCell(f"{target.title}!{cell.coordinate} in the benchmark region is "
                                                 "unlocked: the department must never get a cell to enter its own "
                                                 "benchmark (R046); lock it in the template")
                    raise TemplateMismatch(f"{target.title}!{cell.coordinate} in the M2 region is unlocked; lock it")
                if cell.value not in (None, ""):
                    raise TemplateMismatch(f"{target.title}!{cell.coordinate} in the {which} region holds "
                                           f"{cell.value!r}; the region must be empty in the template")
    bench_region = [_split_region(bench)]
    for w in wb.worksheets:
        if not w.protection.sheet:
            warnings.append(f"tab {w.title!r} is not protected in the template; v5 locks its formula cells")
        unlocked_formulas = []
        for row in w.iter_rows():
            labels: list[str] = []
            for cell in row:
                v = cell.value
                if not cell.protection.locked:
                    if _in(bench_region, w.title, cell.row, cell.column) or \
                            any(word in _norm(" ".join(labels)) for word in BENCHMARK_WORDS):
                        raise BenchmarkInputCell(
                            f"{w.title}!{cell.coordinate} is an unlocked cell labelled as a benchmark "
                            f"({' '.join(labels)!r}): the department must never get a cell to enter its own "
                            "benchmark (R046); lock or remove it in the template")
                    if isinstance(v, str) and v.startswith("="):
                        unlocked_formulas.append(cell.coordinate)
                if isinstance(v, str) and not v.startswith("="):
                    labels.append(v)
        if unlocked_formulas:
            warnings.append(f"tab {w.title!r} has unlocked formula cells {unlocked_formulas[:10]}; v5 locks every "
                            "formula cell (R171)")


# ---------------------------------------------------------------- locked-cell diff


def _val(v: Any) -> Any:
    text = getattr(v, "text", None)
    return text if isinstance(text, str) else v


def diff_locked_cells(template: Path | str, output: Path | str, *, appended=()) -> list[CellChange]:
    """Every locked-cell difference between the template and an output (R048, R232).

    A cell locked in the template must keep its value or formula text and stay locked. A template-empty locked
    cell may be written only inside an `appended` region ('Sheet!A1:E4', or 'A1:E4' for any tab). Each tab's
    protection flag must be unchanged, no template tab may be removed, and the only tabs an output may add are
    Verification and Source & Notes. Existing source notes remain fully protected. Unlocked (input) cells may change freely."""
    import openpyxl

    from cpa import verify

    regions = [_split_region(r) for r in appended]
    twb = openpyxl.load_workbook(str(template))
    owb = openpyxl.load_workbook(str(output))
    changes: list[CellChange] = []
    try:
        for name in twb.sheetnames:
            if name not in owb.sheetnames:
                changes.append(CellChange(name, "", "sheet removed"))
                continue
            wt, wo = twb[name], owb[name]
            if bool(wt.protection.sheet) != bool(wo.protection.sheet):
                changes.append(CellChange(name, "", "sheet protection", bool(wt.protection.sheet),
                                          bool(wo.protection.sheet)))
            for key in sorted(set(wt._cells) | set(wo._cells)):
                tc, oc = wt._cells.get(key), wo._cells.get(key)
                if tc is not None and not tc.protection.locked:
                    continue
                tv = _val(tc.value) if tc is not None else None
                ov = _val(oc.value) if oc is not None else None
                coord = (oc or tc).coordinate
                if tv != ov and not (tv in (None, "") and _in(regions, name, key[0], key[1])):
                    is_formula = any(isinstance(v, str) and v.startswith("=") for v in (tv, ov))
                    changes.append(CellChange(name, coord, "formula" if is_formula else "value", tv, ov))
                    continue
                if oc is not None and not oc.protection.locked:
                    changes.append(CellChange(name, coord, "protection", True, False))
        for name in owb.sheetnames:
            if name not in twb.sheetnames and name not in (verify.VERIFICATION_SHEET, "Source & Notes"):
                changes.append(CellChange(name, "", "sheet added"))
    finally:
        twb.close()
        owb.close()
    return changes


# ---------------------------------------------------------------- inspect


def inspect_template(template: Path | str) -> dict:
    """Read-only survey for filling the template map: per tab protection and formula counts, and every unlocked
    cell with its fill and row label (the nearest text to its left)."""
    import openpyxl

    wb = openpyxl.load_workbook(str(template))
    try:
        sheets: dict = {}
        unlocked: list[dict] = []
        for ws in wb.worksheets:
            formulas, unlocked_formulas = 0, []
            for row in ws.iter_rows():
                label = ""
                for cell in row:
                    v = cell.value
                    is_formula = isinstance(v, str) and v.startswith("=")
                    formulas += is_formula
                    if not cell.protection.locked:
                        unlocked.append({"sheet": ws.title, "cell": cell.coordinate, "fill": _rgb(cell),
                                         "label": label, "value": _jsonable(v)})
                        if is_formula:
                            unlocked_formulas.append(cell.coordinate)
                    elif isinstance(v, str) and not is_formula and v.strip():
                        label = v.strip()
            sheets[ws.title] = {"protected": bool(ws.protection.sheet), "formulas": formulas,
                                "unlocked_formulas": unlocked_formulas}
        return {"template": str(template), "sheets": sheets, "unlocked": unlocked}
    finally:
        wb.close()


# ---------------------------------------------------------------- build


def _flag_fill(yellow: str):
    from openpyxl.styles import PatternFill

    hexcode = str(yellow).lstrip("#")
    return PatternFill(fill_type="solid", fgColor=hexcode, bgColor=hexcode)


def _recalc_values(work: Path, tmap: dict) -> tuple[dict, str]:
    """Recalculate a temp copy and read the mapped rows per year; ({name: {year: None}}, reason) when not possible."""
    import shutil
    import tempfile

    import openpyxl

    from cpa import recalc

    cols = [str(c).upper() for c in tmap["years"]["columns"]]
    values = {name: {n: None for n in range(1, YEARS + 1)} for name in READ_ROWS}
    tmp = Path(tempfile.mkdtemp(prefix="cpa_ap_"))
    try:
        rc = recalc.recalc(work, tmp)
        if not rc.recalculated or rc.output is None:
            return values, f"not recalculated: {rc.reason or rc.status}"
        wb = openpyxl.load_workbook(str(rc.output), data_only=True)
        try:
            ws = wb[str(tmap["pnl_sheet"])]
            for name in READ_ROWS:
                row = int(tmap["rows"][name]["row"])
                for n, c in enumerate(cols, start=1):
                    values[name][n] = _as_number(ws[f"{c}{row}"].value)
        finally:
            wb.close()
        return values, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _missing_text(what: str, why: str, source: str) -> str:
    from cpa import verify

    return f"{verify.M2_MISSING_MARKER}: {what} not supplied; needed for {why}; source {source}"


def _write_benchmarks(work: Path, tmap: dict, rows: list[tuple], yellow: str | None) -> list[PnlFlag]:
    """Write the benchmark region: title, header, one row per metric (label, value, percentile, statement, specialty).
    `rows` are (metric, value or None, PercentileResult or None, missing text or None)."""
    import openpyxl
    from openpyxl.styles import Font

    from cpa import fsutil

    rsheet, (c1, r1, _c2, _r2) = _split_region(_regions(tmap)[0])
    flags: list[PnlFlag] = []
    wb = openpyxl.load_workbook(str(work))
    try:
        ws = wb[rsheet or str(tmap["pnl_sheet"])]
        ws.cell(row=r1, column=c1, value=BENCH_TITLE).font = Font(name="Arial", bold=True)
        for i, head in enumerate(BENCH_HEADERS):
            ws.cell(row=r1 + 1, column=c1 + i, value=head).font = Font(name="Arial", bold=True)
        for k, (metric, value, res, missing) in enumerate(rows):
            r = r1 + 2 + k
            ws.cell(row=r, column=c1, value=BENCH_LABELS[metric])
            if res is not None:
                m = re.search(r"\((P[\d.]+)\)", res.statement)
                shown = m.group(1) if m else ("greater than P%d" % max(p for p, _ in res.points)
                                              if res.above_all_points else "below P%d" % min(p for p, _ in res.points))
                broader = "; broader category" if res.broader else ""
                for j, v in enumerate((res.value, shown, res.statement, f"{res.specialty} ({res.survey_column}{broader})"),
                                      start=1):
                    ws.cell(row=r, column=c1 + j, value=v)
                continue
            if value is not None:
                ws.cell(row=r, column=c1 + 1, value=value)
            else:
                cell = ws.cell(row=r, column=c1 + 1, value=missing)
                if yellow:
                    cell.fill = _flag_fill(yellow)
            cell = ws.cell(row=r, column=c1 + 2, value=missing)
            if yellow:
                cell.fill = _flag_fill(yellow)
            flags.append(PnlFlag("benchmark", f"{ws.title}!{cell.coordinate}", missing))
        fsutil.atomic_write(work, lambda tmp: wb.save(str(tmp)))
    finally:
        wb.close()
    return flags


def _m2_metrics(inputs: PositionInputs, values: dict, tmap: dict, cpt_as_of: str, reason: str) -> dict:
    basis = tmap["rows"]["collections"]["basis"]
    period = f"{inputs.plan_period} Year 1"
    extra = f" ({reason})" if reason else ""
    specs = (
        ("wRVUs", "wrvus", "the productivity narrative and the Work RVU benchmark",
         "MedVitals CPT Billing Profile via the APP P&L Work RVUs row"),
        (f"Collections ({basis})", "collections", "the revenue narrative",
         "APP P&L Collections row (CPT profile charges x Tableau gross collection rate)"),
        ("Charges", "charges", "the revenue narrative", "MedVitals CPT Billing Profile via the APP P&L Charges row"),
    )
    metrics: dict = {}
    for key, row, why, source in specs:
        v = values[row][1]
        if v is None:
            metrics[key] = {"why": why + extra, "source": source}
        else:
            metrics[key] = {"value": v, "period": period, "status": STATUS, "source": source, "as_of": cpt_as_of}
    metrics["cFTE"] = dict(inputs.cfte) if inputs.cfte else {
        "why": "the productivity per cFTE narrative",
        "source": "cFTE consolidated reference (B19) or the confirmed submission (pnl_inputs.json cfte)"}
    return metrics


def _write_figures(path: Path, figures: list[tuple[str, float | None]]) -> dict[str, str]:
    import csv
    import io

    from cpa import fsutil

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["figure", "value"])
    refs = {}
    for i, (fid, v) in enumerate(figures, start=2):
        w.writerow([fid, "" if v is None else repr(float(v))])
        refs[fid] = f"B{i}"
    text = buf.getvalue()

    def write(tmp: Path) -> None:
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    fsutil.atomic_write(path, write)
    return refs


def _write_flags(path: Path, result: BuildResult, inputs: PositionInputs) -> None:
    from cpa import fsutil, manifest

    payload = {"position_id": inputs.position_id, **result.to_json()}
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fsutil.atomic_write(path, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))
    manifest.write(path, "derived", f"{REPORT} flags", f"position {inputs.position_id}", inputs.as_of,
                   row_count=len(result.flags), inputs=[result.workbook])


def _move(src: Path, dst: Path) -> None:
    import shutil

    from cpa import fsutil

    fsutil.atomic_write(dst, lambda tmp: shutil.copyfile(src, tmp))
    src.unlink()


def build_detailed(position_id: str, *, cycle: str | None = None) -> BuildResult:
    """Build outbox/app/<cycle>/<position>/PnL.xlsx for one triaged position and return what was found.

    Raises before anything is copied when an input, the map, a rate (MissingAssumption) or the specialty
    (benchmarks.UnmappedSpecialty) is missing; LockedCellChanged when a locked cell differs from the template."""
    import openpyxl

    from cpa import activity_block, benchmarks, config, fsutil, manifest, verify

    ws_root = config.workspace()
    stage = _stage(ws_root, position_id)
    tmap = load_map()
    inputs = load_inputs(position_id, ws_root)
    klass = triage_class(stage)
    if klass not in READY_CLASSES:
        raise MissingInput(f"triage for {position_id} is {klass or 'absent'} ({manifest.to_rel(stage / TRIAGE_NAME)}); "
                           f"the P&L is built only for {' or '.join(READY_CLASSES)} (run cpa-app-triage first)")
    cycle = _iso(cycle, "cycle") if cycle else inputs.cycle
    if not cycle:
        raise PositionInputError(f"no cycle: pass --cycle YYYY-MM-DD or set cycle in {INPUTS_NAME}")
    template = ws_root / "templates" / str(tmap["template"])
    if not template.is_file():
        raise MissingInput(f"template not found: {manifest.to_rel(template)} (guide 5.6: templates/{tmap['template']})")
    if template.suffix.lower() != ".xlsx":
        raise TemplateMismatch(f"{template.name}: the APP P&L template must be .xlsx")
    rates = [(r, _convert(config.assumption(r["key"]), "pct", r["unit"])) for r in tmap["rates"]]
    match = benchmarks.resolve_match(inputs.department, inputs.division, inputs.role)
    tcc_value = benchmarks.tcc(inputs.base_salary, inputs.supplements)
    excluded = benchmarks.excluded_fringe(inputs.supplements)
    included = tuple(k for k in inputs.supplements if k not in excluded)
    cpt_path = find_cpt_profile(ws_root, inputs.division)
    cpt_rows = read_cpt_profile(cpt_path, tmap["cpt_profile"])
    cpt = tmap["cpt_profile"]
    capacity = int(cpt["last_row"]) - int(cpt["first_row"]) + 1
    if len(cpt_rows) > capacity:
        raise TemplateMismatch(f"{cpt_path.name} has {len(cpt_rows)} rows but the template's {cpt['sheet']} tab holds "
                               f"{capacity} (rows {cpt['first_row']}-{cpt['last_row']}); nothing is truncated")
    rate_path, points_path = stage / RATE_NAME, stage / POINTS_NAME
    rate = read_collection_rate(rate_path)
    points = read_points(points_path, match.sc_specialty)
    cpt_as_of = _profile_as_of(cpt_path) or inputs.as_of
    warnings: list[str] = []
    flags: list[PnlFlag] = [PnlFlag("fringe_excluded", "", f"{name!r} was dropped from TCC as fringe (hard rule 1)")
                            for name in excluded]
    yellow: str | None = None
    from cpa.pptx import brand

    if rate is None or set(points) != set(benchmarks.METRICS):
        yellow = brand.color("flag_yellow")

    wb = openpyxl.load_workbook(str(template))
    try:
        _check_template(wb, tmap, template, warnings)
        sets: list[tuple[str, Any]] = [(tmap["inputs"]["base_salary"], inputs.base_salary),
                                       (tmap["inputs"]["supplements_total"], tcc_value - inputs.base_salary)]
        if tmap["inputs"].get("position_id"):
            sets.append((tmap["inputs"]["position_id"], position_id))
        sets += [(r["cell"], v) for r, v in rates]
        cr = tmap["collection_rate"]
        if rate is not None:
            sets.append((cr["cell"], _convert(rate["value"], rate["unit"], cr["unit"])))
        for ref, value in sets:
            s, c = _ref(ref, "input cell")
            wb[s][c].value = value
        if rate is None:
            s, c = _ref(cr["cell"], "collection_rate.cell")
            text = _missing_text("gross collection rate", "collections, the tax rows and both named rows",
                                 "Tableau JHM PB KPIs Dashboard, 12-month gross collection rate by bill area (A2)")
            wb[s][c].value = text
            wb[s][c].fill = _flag_fill(yellow)
            flags.append(PnlFlag("collection_rate", f"{s}!{c}", text))
        cs = wb[str(cpt["sheet"])]
        for i, rec in enumerate(cpt_rows):
            r = int(cpt["first_row"]) + i
            for f in CPT_FIELDS:
                cs[f"{str(cpt['columns'][f]).upper()}{r}"].value = rec[f]
        wb.calculation.fullCalcOnLoad = True
        work_dir = stage / "work"
        work_dir.mkdir(parents=True, exist_ok=True)
        work = work_dir / OUTPUT_NAME
        fsutil.atomic_write(work, lambda tmp: wb.save(str(tmp)))
    finally:
        wb.close()

    try:
        values, reason = _recalc_values(work, tmap)
        bench_rows: list[tuple] = []
        statements: dict = {}
        for metric, value in (("TCC", tcc_value), ("Work RVUs", values["wrvus"][1])):
            if metric in points and value is not None:
                res = benchmarks.percentile_statement(value, points[metric], inputs.department, inputs.division,
                                                      inputs.role, metric)
                statements[metric] = res
                bench_rows.append((metric, value, res, None))
                continue
            if value is None:
                text = _missing_text(f"{metric} Year 1 value", f"the {metric} benchmark row",
                                     f"the APP P&L {metric} row ({reason or 'not read'})")
            else:
                text = _missing_text(f"SullivanCotter {benchmarks.SURVEY_COLUMN} {metric} points for "
                                     f"{match.sc_specialty}", f"the {metric} percentile statement",
                                     f"SullivanCotter {benchmarks.SURVEY_COLUMN} survey ({POINTS_NAME})")
            if yellow is None:
                yellow = brand.color("flag_yellow")
            bench_rows.append((metric, value, None, text))
        flags += _write_benchmarks(work, tmap, bench_rows, yellow)
        metrics = _m2_metrics(inputs, values, tmap, cpt_as_of, reason)
        m2_flags = activity_block.build(work, str(tmap["pnl_sheet"]), metrics, set(activity_block.METRICS),
                                        anchor=str(tmap["m2"]["anchor"]))
        flags += [PnlFlag("m2", f"{f.tab}!{f.cell}", f.text) for f in m2_flags]
    except BaseException:
        work.unlink(missing_ok=True)
        if not any(work_dir.iterdir()):
            work_dir.rmdir()
        raise

    appended = _regions(tmap)
    changes = diff_locked_cells(template, work, appended=appended)
    if changes:
        raise LockedCellChanged(
            f"{len(changes)} locked cell(s) differ from the template before recalculation: "
            + "; ".join(c.line() for c in changes[:5]) + f". Nothing reached outbox; the work copy stays at "
            f"{manifest.to_rel(work)} for inspection (it has no manifest by design)", changes, "before recalc")

    out_dir = ws_root / "outbox" / "app" / fsutil.safe_filename(cycle) / position_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / OUTPUT_NAME
    _move(work, out)
    if not any(work_dir.iterdir()):
        work_dir.rmdir()

    cols = [str(c).upper() for c in tmap["years"]["columns"]]
    fig_list = [(f"{name}_y{n}", values[name][n], f"{tmap['pnl_sheet']}!{cols[n - 1]}{tmap['rows'][name]['row']}",
                 f"{inputs.plan_period} Year {n}") for name in NAMED_ROWS for n in range(1, YEARS + 1)]
    figures_path = stage / FIGURES_NAME
    refs = _write_figures(figures_path, [(fid, v) for fid, v, _, _ in fig_list])
    filters = f"position {position_id}; division {inputs.division}"
    src_head = tmap["cpt_profile"]["source"]
    cpt_ref = f"A{int(src_head.get('header_row') or 1)}"
    manifest.write(figures_path, "derived", f"{REPORT} figures", filters, inputs.as_of, inputs=[cpt_path, inputs.path])
    for fid, v, _, period in fig_list:
        manifest.add_figure(figures_path, fid, v, cpt_path, cpt_ref, status=STATUS, period=period)
    sources = [template, cpt_path, inputs.path] + [p for p in (rate_path, points_path) if p.is_file()]
    manifest.write(out, "derived", REPORT, filters, inputs.as_of, inputs=sources, status=STATUS,
                   period=inputs.plan_period, position=position_id, cycle=cycle, specialty=match.sc_specialty)
    for fid, v, cell, period in fig_list:
        manifest.add_figure(out, fid, v, figures_path, refs[fid], cell=cell, status=STATUS, period=period)

    vres = verify.build_verification_tab(out)
    result = BuildResult(workbook=out, verify_summary=vres.summary, verify_issues=[i.to_json() for i in vres.issues],
                         flags=flags, statements=statements, values=values, excluded_fringe=excluded,
                         included_supplements=included, warnings=warnings, recalc_reason=reason)
    if (out_dir / FAILED_NAME).exists():
        warnings.append(f"{FAILED_NAME} from an earlier failed run is still in {manifest.to_rel(out_dir)}; do not send it")

    changes = diff_locked_cells(template, out, appended=appended)
    if changes:
        failed = out_dir / FAILED_NAME
        _move(out, failed)
        side_old, side_new = manifest.sidecar(out), manifest.sidecar(failed)
        if side_old.is_file():
            data = manifest.read(out)
            data["path"] = manifest.to_rel(failed)
            data["locked_cells_changed"] = [c.to_json() for c in changes]
            text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            fsutil.atomic_write(side_new, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))
            side_old.unlink()
        result.workbook = failed
        result.flags.append(PnlFlag("locked_cells_changed", "", f"DO NOT SEND - locked cells changed after "
                                    f"recalculation; see {FAILED_NAME}"))
        _write_flags(stage / FLAGS_NAME, result, inputs)
        raise LockedCellChanged(
            f"{len(changes)} locked cell(s) differ from the template after recalculation: "
            + "; ".join(c.line() for c in changes[:5]) + f". The output was renamed {manifest.to_rel(failed)}; "
            "do not send it", changes, "after recalc")
    _write_flags(stage / FLAGS_NAME, result, inputs)
    return result


def build(position_id: str, *, cycle: str | None = None) -> Path:
    """guide 9: build the position's P&L and return its path; enforces the locked-cell diff against the template."""
    return build_detailed(position_id, cycle=cycle).workbook


# ---------------------------------------------------------------- readiness (guide 7.2, D19)


def _ready_extra(ws: Path, key: str) -> list[Path] | None:
    """cpa-app-pnl is ready when triage is COMPLETE/FIXABLE and the division's CPT profile has landed."""
    try:
        stage = _stage(ws, key)
        if triage_class(stage) not in READY_CLASSES:
            return None
        data = json.loads((stage / INPUTS_NAME).read_text(encoding="utf-8-sig"))
        return [find_cpt_profile(ws, str(data["division"]))]
    except Exception:  # a readiness probe never raises: anything unreadable is simply not ready
        return None


READINESS_RULES = (
    state.Rule(WORKFLOW, ("staging/app/{key}/" + TRIAGE_NAME, "staging/app/{key}/" + INPUTS_NAME,
                          "staging/app/{key}/" + RATE_NAME), "folder", extra=_ready_extra),
)


# ---------------------------------------------------------------- CLI


def _stop(exc: BaseException) -> int:
    print(f"stopped: {exc}", file=sys.stderr)
    return EXIT_STOPPED


def _stoppers() -> tuple:
    from cpa import activity_block, benchmarks, config, fsutil, manifest, recalc, verify

    return (AppPnlError, config.ConfigError, benchmarks.BenchmarkError, activity_block.ActivityBlockError,
            manifest.ManifestError, verify.VerifyError, recalc.RecalcError, fsutil.UnsafeFilename, FileNotFoundError,
            PermissionError)


def _report(result: BuildResult) -> list[str]:
    lines = [f"workbook: {result.workbook}", f"verify: {result.verify_summary}"]
    for name, label in (("jhu_contribution_margin", "JHU Contribution Margin"),
                        ("division_surplus", "Division Surplus / Deficit")):
        vals = result.values.get(name, {})
        if all(v is None for v in vals.values()):
            lines.append(f"{label}: n/a ({result.recalc_reason or 'not read'}); open the workbook in Excel to read it")
        else:
            lines.append(f"{label}: " + ", ".join(f"Year {y} {_money(v)}" for y, v in sorted(vals.items())))
    for metric in ("TCC", "Work RVUs"):
        res = result.statements.get(metric)
        lines.append(f"{metric}: {res.statement}" if res else f"{metric}: no percentile stated (flagged below)")
    lines.append("TCC supplements included: " + (", ".join(result.included_supplements) or "none")
                 + "; excluded as fringe: " + (", ".join(result.excluded_fringe) or "none"))
    lines += [f"flag {f.kind} {f.cell}: {f.text}".replace("  ", " ") for f in result.flags]
    lines += [f"warning: {w}" for w in result.warnings]
    lines += [f"issue: {i['tab']}!{i['cell']} {i['code']} expected {i['expected']}, found {i['found']}"
              for i in result.verify_issues]
    return lines


def _cmd_build(args: argparse.Namespace) -> int:
    from cpa import benchmarks

    try:
        result = build_detailed(args.position, cycle=args.cycle)
    except benchmarks.UnmappedSpecialty as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return EXIT_UNMAPPED
    except _stoppers() as exc:
        return _stop(exc)
    if args.json:
        print(json.dumps(result.to_json(), indent=2, ensure_ascii=False))
    else:
        print("\n".join(_report(result)))
    return EXIT_OK if result.verify_summary == "CLEAN" else EXIT_ISSUES


def _cmd_diff(args: argparse.Namespace) -> int:
    try:
        appended = _regions(load_map())
        changes = diff_locked_cells(args.template, args.output, appended=appended)
    except _stoppers() as exc:
        return _stop(exc)
    if not changes:
        print("no locked cell changed")
        return EXIT_OK
    for c in changes:
        print(c.line())
    return EXIT_ISSUES


def _cmd_inspect(args: argparse.Namespace) -> int:
    try:
        survey = inspect_template(args.template)
    except _stoppers() as exc:
        return _stop(exc)
    if args.json:
        print(json.dumps(survey, indent=2, ensure_ascii=False))
        return EXIT_OK
    for name, info in survey["sheets"].items():
        print(f"tab {name}: protected {'yes' if info['protected'] else 'NO'}, {info['formulas']} formula cells"
              + (f", unlocked formulas {info['unlocked_formulas']}" if info["unlocked_formulas"] else ""))
    for u in survey["unlocked"]:
        print(f"{u['sheet']}!{u['cell']}  fill {u['fill'] or 'none'}  label {u['label']!r}")
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `app_pnl build|diff|inspect`. Import-cheap (D03)."""
    top = subparsers.add_parser("app_pnl", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    p = sub.add_parser("build", help="Build outbox/app/<cycle>/<position>/PnL.xlsx from the APP P&L v5 template.",
                       description="Writes only unlocked input cells, adds the SullivanCotter 2025 AMC rows and the M2 "
                                   "block, diffs every locked cell against the template, attaches the Verification "
                                   "tab. Exit 0 verify CLEAN, 1 built with issues, 2 stopped, 3 unmapped specialty "
                                   "(ask which SullivanCotter specialty applies, add the map row, rerun).")
    p.add_argument("--position", required=True, help="Position id (the staging/app/<position> folder name).")
    p.add_argument("--cycle", default=None, help="SOM cycle date YYYY-MM-DD (default: cycle in pnl_inputs.json).")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_build)

    p = sub.add_parser("diff", help="List locked cells that differ between the template and an output.",
                       description="Exit 0 when no locked cell changed, 1 when some did, 2 when it could not run.")
    p.add_argument("--template", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(func=_cmd_diff)

    p = sub.add_parser("inspect", help="Survey a template (read-only): protection, unlocked input cells, labels.",
                       description="Lists every unlocked cell with its fill and row label so the template map can be "
                                   "filled from her real APP P&L v5. Never writes.")
    p.add_argument("--template", type=Path, required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_inspect)
