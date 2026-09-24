"""SullivanCotter benchmark interpolator (C3): TCC, percentile interpolation, specialty resolution.

Build-list items: C3 SullivanCotter interpolator (guide 5 cpa-benchmark, guide 9 benchmarks.py, guide 13.6).
Hard rules enforced: 1 (TCC = base salary + supplements; fringe is never included), 2 (SullivanCotter 2025 AMC
column only; TCC for compensation, Work RVUs for productivity; most specific sub-specialty, broader category only
when the sub-specialty is not reported and then stated), 3 (percentiles are specific interpolated numbers; "greater
than P<max>" only when the value exceeds every reported point), 15 (nothing guessed: an unmapped specialty stops
for a human to add the row).

FIXTURE - confirm against her file: no SullivanCotter survey-file reader exists (access method and layout are
unconfirmed, docs/FIXTURE_SWAP.md Q7). Percentile points are supplied by the caller; `select_2025_amc` picks the
2025 AMC column from a column-label -> points table once a reader exists.

The specialty map, reference/sullivancotter_specialty_map.csv (guide 10, R236), has the columns
department, division, role, sc_specialty, broader. One row per department/division/role she has benchmarked;
`*` in division or role (never department) matches anything. `broader` is true only when SullivanCotter does not
report the sub-specialty separately and the broader category is used instead. The repository copy ships the
header only (no source states a triple); she keeps the live copy in <workspace>/reference/, and it grows each
time C3 raises UnmappedSpecialty. Conventions: DECISIONS D23.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from numbers import Real
from pathlib import Path

__all__ = [
    "SURVEY_COLUMN", "METRICS", "MAP_NAME", "MAP_COLUMNS", "WILDCARD", "FRINGE_TERMS", "NEGATION_TERMS",
    "BenchmarkError", "UnmappedSpecialty", "SpecialtyMapError", "InvalidPercentilePoints", "UnknownMetric",
    "SurveyColumnMissing", "AmbiguousSupplement", "MapRow", "PercentileResult",
    "tcc", "excluded_fringe", "select_2025_amc", "normalize_points", "interpolate_percentile", "ordinal",
    "normalize_metric", "map_path", "load_specialty_map", "resolve_match", "resolve_specialty",
    "percentile_statement", "statement_for_specialty", "register",
]

SURVEY_COLUMN = "2025 AMC"
METRICS: tuple[str, ...] = ("TCC", "Work RVUs")
MAP_NAME = "sullivancotter_specialty_map.csv"
MAP_COLUMNS: tuple[str, ...] = ("department", "division", "role", "sc_specialty", "broader")
WILDCARD = "*"
# Tool settings (D23). A backstop only: callers pass supplements, never fringe.
FRINGE_TERMS: frozenset[str] = frozenset({"fringe", "fringes", "benefit", "benefits"})
NEGATION_TERMS: frozenset[str] = frozenset({"non", "no", "not", "excl", "excluding", "without"})
_METRIC_ALIASES = {
    "tcc": "TCC", "totalcashcompensation": "TCC",
    "workrvus": "Work RVUs", "workrvu": "Work RVUs", "wrvus": "Work RVUs", "wrvu": "Work RVUs",
}
_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}
_POINT_KEY = re.compile(r"^\s*[Pp]?\s*(\d{1,3})\s*$")

EXIT_OK = 0
EXIT_STOPPED = 2
EXIT_UNMAPPED = 3


class BenchmarkError(Exception):
    """Base for every C3 failure."""


class UnmappedSpecialty(BenchmarkError):
    """No map row covers the specialty: stop, ask the analyst, add the row, rerun (R049, R137)."""

    def __init__(self, message: str, *, department=None, division=None, role=None, specialty=None,
                 path: Path | None = None) -> None:
        super().__init__(message)
        self.department, self.division, self.role, self.specialty, self.path = (
            department, division, role, specialty, path)


class SpecialtyMapError(BenchmarkError):
    """The specialty map is missing, unreadable, or has a bad header or row."""


class InvalidPercentilePoints(BenchmarkError):
    """Percentile points are too few, out of range, non-numeric, or not strictly increasing."""


class UnknownMetric(BenchmarkError):
    """A metric other than TCC or Work RVUs (R176)."""


class SurveyColumnMissing(BenchmarkError):
    """The 2025 AMC column is absent (or present twice) in a survey table; no other column is used."""


class AmbiguousSupplement(BenchmarkError):
    """A supplement name mentions fringe/benefit together with a negation; it is neither dropped nor kept."""


@dataclass(frozen=True)
class MapRow:
    """One specialty-map row as she wrote it, with its 1-based file line."""

    department: str
    division: str
    role: str
    sc_specialty: str
    broader: bool
    line: int


@dataclass(frozen=True)
class PercentileResult:
    """A percentile finding with the citation every slide and P&L row prints (specialty, survey column,
    broader-category flag). `percentile` is None only when the value is outside every reported point."""

    value: float
    metric: str
    specialty: str
    broader: bool
    survey_column: str
    percentile: float | None
    above_all_points: bool
    below_all_points: bool
    points: tuple[tuple[int, float], ...]
    statement: str


# ------------------------------------------------------------------ numbers


def _number(x, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (Real, Decimal)):
        raise TypeError(f"{what} must be a number, got {x!r}")
    value = float(x)
    if not math.isfinite(value):
        raise ValueError(f"{what} must be finite, got {x!r}")
    return value


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^0-9a-z]+", str(name).casefold()) if t}


def _split_supplements(supplements) -> tuple[list[float], list[str]]:
    """(amounts kept, names dropped as fringe)."""
    if supplements is None or isinstance(supplements, (str, bytes)):
        raise TypeError(f"supplements must be a number, an iterable of numbers or a name->amount mapping, "
                        f"got {supplements!r}")
    if isinstance(supplements, (Real, Decimal)) and not isinstance(supplements, bool):
        return [_number(supplements, "supplements")], []
    if isinstance(supplements, Mapping):
        kept: list[float] = []
        dropped: list[str] = []
        for name, amount in supplements.items():
            tokens = _tokens(name)
            if tokens & FRINGE_TERMS:
                if tokens & NEGATION_TERMS:
                    raise AmbiguousSupplement(
                        f"supplement {name!r} mentions fringe/benefits and a negation; rename it (or pass it as "
                        "a plain amount) so it is neither dropped nor kept silently")
                dropped.append(str(name))
                continue
            kept.append(_number(amount, f"supplement {name!r}"))
        return kept, dropped
    if isinstance(supplements, Iterable):
        return [_number(a, "supplement") for a in supplements], []
    raise TypeError(f"supplements must be a number, an iterable of numbers or a name->amount mapping, "
                    f"got {supplements!r}")


def tcc(base, supplements, *, fringe=None) -> float:
    """Total cash compensation (TCC) = base salary + supplements only. Fringe is never included (hard rule 1).

    `supplements` is a number, an iterable of numbers, or a name -> amount mapping. `fringe=` is accepted and
    ignored so a caller holding a whole compensation record cannot add it by accident. As a backstop, a mapping
    key whose words include fringe/benefit(s) is dropped (see excluded_fringe); one that also carries a negation
    ("Non-benefit stipend") raises AmbiguousSupplement. The backstop is not a classifier: fringe labelled "FICA"
    or "Retirement" would be kept, so callers must pass supplements only."""
    del fringe  # never part of TCC
    kept, _ = _split_supplements(supplements)
    return _number(base, "base") + sum(kept)


def excluded_fringe(supplements) -> tuple[str, ...]:
    """Names of the supplement components tcc() drops as fringe, in input order, so a caller can say so."""
    return tuple(_split_supplements(supplements)[1])


# ------------------------------------------------------------------ percentiles


def select_2025_amc(columns: Mapping) -> dict[int, float]:
    """The 2025 AMC points from a survey table {column label: {percentile: value}}. No other column is ever
    used as a fallback (hard rule 2); absent or duplicated raises SurveyColumnMissing."""
    want = " ".join(SURVEY_COLUMN.split()).casefold()
    hits = [label for label in columns if " ".join(str(label).split()).casefold() == want]
    if not hits:
        raise SurveyColumnMissing(
            f"the SullivanCotter {SURVEY_COLUMN} column is not in the table (columns seen: "
            f"{', '.join(repr(str(c)) for c in columns) or 'none'}); no other column is used")
    if len(hits) > 1:
        raise SurveyColumnMissing(f"the {SURVEY_COLUMN} column appears more than once: {hits!r}")
    return normalize_points(columns[hits[0]])


def _point_key(key) -> int:
    if isinstance(key, bool):
        raise InvalidPercentilePoints(f"percentile key {key!r} is not a percentile")
    if isinstance(key, int):
        p = key
    elif isinstance(key, str) and _POINT_KEY.match(key):
        p = int(_POINT_KEY.match(key).group(1))
    else:
        raise InvalidPercentilePoints(f"percentile key {key!r} must be an integer 1-99 or a label like 'P50'")
    if not 1 <= p <= 99:
        raise InvalidPercentilePoints(f"percentile key {key!r} is outside 1-99")
    return p


def normalize_points(points: Mapping) -> dict[int, float]:
    """Validate reported percentile points and return them sorted {percentile: value}.

    Needs at least two points, integer percentiles 1-99 (or 'P50' labels), finite numeric values, and values
    strictly increasing with the percentile; anything else is a transcription error and fails loudly."""
    if not isinstance(points, Mapping):
        raise InvalidPercentilePoints(f"points must be a mapping of percentile -> value, got {points!r}")
    out: dict[int, float] = {}
    for key, raw in points.items():
        p = _point_key(key)
        if p in out:
            raise InvalidPercentilePoints(f"percentile P{p} is given twice")
        try:
            out[p] = _number(raw, f"P{p} value")
        except (TypeError, ValueError) as exc:
            raise InvalidPercentilePoints(str(exc)) from None
    if len(out) < 2:
        raise InvalidPercentilePoints(f"at least two reported percentile points are needed, got {len(out)}")
    ordered = dict(sorted(out.items()))
    pairs = list(ordered.items())
    for (p1, v1), (p2, v2) in zip(pairs, pairs[1:]):
        if not v2 > v1:
            raise InvalidPercentilePoints(
                f"values must rise with the percentile: P{p1}={v1:g} but P{p2}={v2:g}; check the survey figures")
    return ordered


def interpolate_percentile(value, points: dict[int, float]) -> float | None:
    """Linear interpolation between the two reported points around `value` (raw float, not rounded).

    An exact hit returns that point's percentile. A value above the highest or below the lowest point returns
    None: nothing is ever extrapolated (hard rule 3)."""
    v = _number(value, "value")
    pts = list(normalize_points(points).items())
    for p, pv in pts:
        if v == pv:
            return float(p)
    for (lo_p, lo_v), (hi_p, hi_v) in zip(pts, pts[1:]):
        if lo_v < v < hi_v:
            return lo_p + (v - lo_v) * (hi_p - lo_p) / (hi_v - lo_v)
    return None


def ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th ... 11th, 12th, 13th ... 21st."""
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _half_up(x: float, places: str) -> Decimal:
    return Decimal(repr(x)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def normalize_metric(metric) -> str:
    """Canonical metric name, TCC or Work RVUs; anything else raises UnknownMetric (R176)."""
    key = re.sub(r"[^a-z]", "", str(metric).casefold())
    if key not in _METRIC_ALIASES:
        raise UnknownMetric(f"metric {metric!r} is not benchmarked: use {METRICS[0]} for compensation or "
                            f"{METRICS[1]} for productivity")
    return _METRIC_ALIASES[key]


def _fmt_value(value: float, metric: str) -> str:
    if metric == "TCC":
        return f"${value:,.0f}"
    if value.is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------ specialty map


def map_path() -> Path:
    """The specialty map in use: <workspace>/reference/ copy when present, else the repository template."""
    from cpa import config

    try:
        return config.reference_file(MAP_NAME)
    except config.MissingReference as exc:
        raise SpecialtyMapError(str(exc)) from None


def _workspace_target() -> Path | None:
    from cpa import config

    try:
        return config.workspace() / "reference" / MAP_NAME
    except config.WorkspaceNotFound:
        return None


def _norm(text) -> str:
    return " ".join(str(text).split()).casefold()


def _strip_trailing(row: list[str]) -> list[str]:
    cells = [c.strip() for c in row]
    while cells and not cells[-1]:
        cells.pop()
    return cells


def load_specialty_map(path=None) -> tuple[MapRow, ...]:
    """Read the specialty map (utf-8-sig, as Excel saves it) into rows. `path=None` uses map_path().

    Blank rows, `#` comment rows and Excel's trailing empty cells are ignored. The header must be exactly the
    five MAP_COLUMNS; every row needs department, division, role and sc_specialty, a broader value of
    true/false/yes/no/1/0, no `*` in department, and a department/division/role not already used."""
    path = Path(path) if path is not None else map_path()
    if not path.is_file():
        raise SpecialtyMapError(
            f"specialty map not found: {path}. Create it with the header {','.join(MAP_COLUMNS)} "
            f"(template: reference/{MAP_NAME} in the plugin), add the row and rerun")
    rows: list[MapRow] = []
    seen: dict[tuple[str, str, str], int] = {}
    header: list[str] | None = None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            for raw in reader:
                cells = _strip_trailing(raw)
                if not cells or cells[0].lstrip('"').startswith("#"):
                    continue
                line = reader.line_num
                if header is None:
                    header = [c.casefold() for c in cells]
                    if tuple(header) != MAP_COLUMNS:
                        missing = [c for c in MAP_COLUMNS if c not in header]
                        extra = [c for c in header if c not in MAP_COLUMNS]
                        raise SpecialtyMapError(
                            f"{path} line {line}: header must be {','.join(MAP_COLUMNS)}; missing "
                            f"{missing or 'none'}, unexpected {extra or 'none'}")
                    continue
                if len(cells) != len(MAP_COLUMNS):
                    raise SpecialtyMapError(
                        f"{path} line {line} has {len(cells)} cells; expected {len(MAP_COLUMNS)} "
                        f"({','.join(MAP_COLUMNS)})")
                record = dict(zip(MAP_COLUMNS, cells))
                for col in MAP_COLUMNS[:4]:
                    if not record[col]:
                        raise SpecialtyMapError(f"{path} line {line}: {col} is empty")
                if record["department"] == WILDCARD:
                    raise SpecialtyMapError(f"{path} line {line}: department cannot be {WILDCARD!r}; name it")
                flag = record["broader"].casefold()
                if flag not in _TRUE | _FALSE:
                    raise SpecialtyMapError(
                        f"{path} line {line}: broader must be true or false, got {record['broader']!r}")
                key = (_norm(record["department"]), _norm(record["division"]), _norm(record["role"]))
                if key in seen:
                    raise SpecialtyMapError(
                        f"{path} line {line}: duplicate department/division/role (first on line {seen[key]})")
                seen[key] = line
                rows.append(MapRow(record["department"], record["division"], record["role"],
                                   record["sc_specialty"], flag in _TRUE, line))
    except UnicodeDecodeError:
        raise SpecialtyMapError(
            f"{path} is not UTF-8: in Excel use Save As > CSV UTF-8 (Comma delimited) and rerun") from None
    if header is None:
        raise SpecialtyMapError(f"{path} is empty; it needs the header {','.join(MAP_COLUMNS)}")
    return tuple(rows)


def _unmapped_hint(path: Path) -> str:
    target = _workspace_target()
    where = f"to {path}"
    if target is not None and path != target and not target.is_file():
        where = f"to {target} (copy the template {path} there first)"
    return (f"Stop and ask the analyst which SullivanCotter {SURVEY_COLUMN} specialty applies: the most specific "
            "sub-specialty reported (for example Neurological Surgery NP/PA rather than Neurology), broader=true "
            "only when the sub-specialty is not reported separately. Add a row "
            f"{','.join(MAP_COLUMNS)} {where} and rerun.")


def resolve_match(department, division, role, *, path=None) -> MapRow:
    """The most specific map row for a department/division/role.

    Exact match after casefolding and collapsing spaces; tiers, most specific first: department+division+role,
    department+division+*, department+*+role, department+*+*. The broader flag is the row's, never inferred."""
    path = Path(path) if path is not None else map_path()
    rows = load_specialty_map(path)
    d, v, r = _norm(department), _norm(division), _norm(role)
    for want_div, want_role in ((v, r), (v, WILDCARD), (WILDCARD, r), (WILDCARD, WILDCARD)):
        for row in rows:
            if (_norm(row.department), _norm(row.division), _norm(row.role)) == (d, want_div, want_role):
                return row
    raise UnmappedSpecialty(
        f"no SullivanCotter specialty is mapped for department={department!r}, division={division!r}, "
        f"role={role!r} in {path}. " + _unmapped_hint(path),
        department=department, division=division, role=role, path=path)


def resolve_specialty(department, division, role) -> tuple[str, bool]:
    """(SullivanCotter specialty, broader) for a department/division/role; raises UnmappedSpecialty."""
    row = resolve_match(department, division, role)
    return row.sc_specialty, row.broader


# ------------------------------------------------------------------ statements


def _result(value, points, specialty: str, broader: bool, metric: str) -> PercentileResult:
    v = _number(value, "value")
    pts = normalize_points(points)
    pct = interpolate_percentile(v, pts)
    above = pct is None and v > max(pts.values())
    below = pct is None and v < min(pts.values())
    subject = f"{metric} {_fmt_value(v, metric)} is"
    cite = f"of SullivanCotter {SURVEY_COLUMN}, {specialty}."
    if pct is not None:
        shown = _half_up(pct, "0.1")
        n = int(shown.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        text = f"{subject} at approximately the {ordinal(n)} percentile (P{shown}) {cite}"
    elif above:
        text = f"{subject} greater than P{max(pts)} (above every reported point) {cite}"
    else:
        text = f"{subject} below P{min(pts)} (under every reported point) {cite}"
    if broader:
        text += " Broader category used: the sub-specialty is not separately reported."
    return PercentileResult(v, metric, specialty, broader, SURVEY_COLUMN, pct, above, below,
                            tuple(pts.items()), text)


def percentile_statement(value, points, department, division, role, metric, *, path=None) -> PercentileResult:
    """Resolve the specialty, interpolate, and phrase the finding as a specific number, never a range
    (a "greater than P<max>" only above every point); cites the survey column and specialty."""
    metric = normalize_metric(metric)
    row = resolve_match(department, division, role, path=path)
    return _result(value, points, row.sc_specialty, row.broader, metric)


def statement_for_specialty(value, points, specialty, metric, *, path=None) -> PercentileResult:
    """percentile_statement for a SullivanCotter specialty named directly. It must appear as an sc_specialty
    in the map (else UnmappedSpecialty); the broader flag comes from those rows, which must agree."""
    metric = normalize_metric(metric)
    path = Path(path) if path is not None else map_path()
    rows = [r for r in load_specialty_map(path) if _norm(r.sc_specialty) == _norm(specialty)]
    if not rows:
        raise UnmappedSpecialty(
            f"SullivanCotter specialty {specialty!r} is not in {path}. " + _unmapped_hint(path),
            specialty=specialty, path=path)
    flags = {r.broader for r in rows}
    if len(flags) > 1:
        lines = ", ".join(str(r.line) for r in rows)
        raise SpecialtyMapError(
            f"{path} maps {specialty!r} as broader on some rows and not others (lines {lines}); "
            "benchmark by --dept/--div/--role instead")
    return _result(value, points, rows[0].sc_specialty, rows[0].broader, metric)


# ------------------------------------------------------------------ CLI


def _parse_points(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in (s for s in text.split(",") if s.strip()):
        key, sep, raw = item.partition("=")
        if not sep:
            raise InvalidPercentilePoints(f"--points item {item!r} must look like P50=120000")
        try:
            out[key.strip()] = float(raw.strip())
        except ValueError:
            raise InvalidPercentilePoints(f"--points value {raw.strip()!r} is not a number "
                                          "(no thousands separators or currency signs)") from None
    return out


def _parse_supplements(items: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in items:
        name, sep, raw = item.rpartition("=")
        if not sep or not name.strip():
            raise ValueError(f"--supplement {item!r} must look like NAME=AMOUNT")
        out[name.strip()] = float(raw)
    return out


def _cmd_percentile(args: argparse.Namespace) -> int:
    triple = (args.dept, args.div, args.role)
    try:
        if args.specialty and any(t is not None for t in triple):
            raise ValueError("give --specialty or --dept/--div/--role, not both")
        if not args.specialty and any(t is None for t in triple):
            raise ValueError("give --specialty, or all three of --dept, --div and --role")
        metric = normalize_metric(args.metric)
        notes: list[str] = []
        if args.value is not None:
            if args.supplement:
                raise ValueError("--supplement adds to --base; with --value pass the full TCC instead")
            value = args.value
        else:
            if metric != "TCC":
                raise ValueError("--base/--supplement build TCC only; use --value for Work RVUs")
            supplements = _parse_supplements(args.supplement or [])
            value = tcc(args.base, supplements, fringe=args.fringe)
            dropped = excluded_fringe(supplements)
            fringe_bits = ([f"--fringe {args.fringe:,.0f} ignored"] if args.fringe is not None else []) + \
                          [f"supplement {name!r} dropped" for name in dropped]
            notes.append(f"TCC = base + supplements = {_fmt_value(value, 'TCC')}; fringe excluded"
                         + (f" ({'; '.join(fringe_bits)})" if fringe_bits else ""))
        points = _parse_points(args.points)
        if args.specialty:
            result = statement_for_specialty(value, points, args.specialty, metric, path=args.map)
        else:
            result = percentile_statement(value, points, *triple, metric, path=args.map)
    except UnmappedSpecialty as exc:
        print(f"unmapped specialty: {exc}", file=sys.stderr)
        return EXIT_UNMAPPED
    except (BenchmarkError, ValueError, TypeError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return EXIT_STOPPED
    if args.json:
        payload = asdict(result)
        payload["notes"] = notes
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for note in notes:
            print(note)
        print(result.statement)
    return EXIT_OK


def _cmd_resolve(args: argparse.Namespace) -> int:
    try:
        path = Path(args.map) if args.map is not None else map_path()
        row = resolve_match(args.dept, args.div, args.role, path=path)
    except UnmappedSpecialty as exc:
        print(f"unmapped specialty: {exc}", file=sys.stderr)
        return EXIT_UNMAPPED
    except BenchmarkError as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return EXIT_STOPPED
    if args.json:
        print(json.dumps({"specialty": row.sc_specialty, "broader": row.broader, "department": row.department,
                          "division": row.division, "role": row.role, "map": str(path), "line": row.line},
                         indent=2, ensure_ascii=False))
    elif row.broader:
        print(f"{row.sc_specialty} (broader category: the sub-specialty is not separately reported; state this "
              f"on the slide) - map line {row.line} of {path}")
    else:
        print(f"{row.sc_specialty} (most specific sub-specialty) - map line {row.line} of {path}")
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `benchmarks percentile|resolve`. Import-cheap: no file access here (D03)."""
    top = subparsers.add_parser("benchmarks", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    codes = "Exit 0 ok, 2 stopped, 3 unmapped specialty (ask the analyst, add the map row, rerun)."
    p = sub.add_parser(
        "percentile", help="State a value's SullivanCotter 2025 AMC percentile as a specific interpolated number.",
        description="Linear interpolation between the reported 2025 AMC points; 'greater than P<max>' only above "
                    "every point, 'below P<min>' only under every point. TCC is base + supplements, never "
                    "fringe. " + codes)
    value = p.add_mutually_exclusive_group(required=True)
    value.add_argument("--value", type=float, help="The TCC (base + supplements, no fringe) or Work RVU value.")
    value.add_argument("--base", type=float, help="Base salary; TCC is then built from --base and --supplement.")
    p.add_argument("--supplement", action="append", metavar="NAME=AMOUNT",
                   help="A supplement added to --base (repeatable). Names mentioning fringe are dropped.")
    p.add_argument("--fringe", type=float, default=None, help="Accepted and ignored: fringe is never in TCC.")
    p.add_argument("--metric", required=True, help="TCC (compensation) or 'Work RVUs' (productivity).")
    p.add_argument("--points", required=True, metavar="P25=V,P50=V,...",
                   help="Reported 2025 AMC points for the specialty and metric, e.g. P25=100000,P50=120000,"
                        "P75=150000,P90=180000 (no thousands separators).")
    p.add_argument("--specialty", help="SullivanCotter specialty as written in the specialty map.")
    p.add_argument("--dept", help="Department (with --div and --role, resolves the specialty from the map).")
    p.add_argument("--div", help="Division.")
    p.add_argument("--role", help="Role, e.g. NP/PA or Physician.")
    p.add_argument("--map", type=Path, default=None,
                   help="Specialty map CSV (default: reference/sullivancotter_specialty_map.csv in the workspace).")
    p.add_argument("--json", action="store_true", help="Print the full result as JSON.")
    p.set_defaults(func=_cmd_percentile)
    r = sub.add_parser(
        "resolve", help="Resolve department/division/role to the most specific SullivanCotter specialty.",
        description="Reads the specialty map; prints the specialty and whether it is the broader category. "
                    + codes)
    r.add_argument("--dept", required=True, help="Department.")
    r.add_argument("--div", required=True, help="Division.")
    r.add_argument("--role", required=True, help="Role, e.g. NP/PA or Physician.")
    r.add_argument("--map", type=Path, default=None,
                   help="Specialty map CSV (default: reference/sullivancotter_specialty_map.csv in the workspace).")
    r.add_argument("--json", action="store_true", help="Print the result as JSON.")
    r.set_defaults(func=_cmd_resolve)
