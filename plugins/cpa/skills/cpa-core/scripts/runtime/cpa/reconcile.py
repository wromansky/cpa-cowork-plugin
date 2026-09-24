"""Reconciliation harness (C5): compare two frames within an explicit tolerance, detect paste errors,
validate dates, and reconcile a plan against an actual across a period mismatch.

Build-list items: C5 multi-source reconciliation harness (guide 9 reconcile.py). Hard rules enforced:
"unmatched department labels fail loudly" via cpa.crosswalk at the CLI boundary; "period mismatches
are prorated explicitly with a label" (compare_plan_actual calls cpa.periods.prorate, D06) -- this
module never computes a proration itself. R060: compare() never drops an unmatched or duplicate-keyed
row; every one is listed in only_in_a/only_in_b, never summed, averaged or silently paired.

Tolerance (DECISIONS D05): `Tolerance(abs, pct)`; a measure ties when |a-b| <= abs OR
|a-b| / max(|a|,|b|,1e-9) * 100 <= pct. compare() takes a Tolerance explicitly -- no default.

Read policy (D10): dtype_backend="numpy_nullable"; key columns compared as stripped strings; never
dropna; never pd.to_numeric (numeric comparison only through Tolerance).
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from cpa import config

__all__ = [
    "ReconcileError", "PeriodMismatch", "Tolerance", "ReconResult",
    "compare", "detect_paste_errors", "check_dates", "compare_plan_actual",
    "tolerance_from_assumptions", "register",
]

_NUMERIC_NAME_RE = re.compile(r"wrvu|collect|amount|budget|actual|revenue|cost|rvu|fte|volume|count|total|pct|%", re.I)
_LABEL_NAME_RE = re.compile(r"dept|department|label|name|key|division", re.I)


class ReconcileError(Exception):
    """Base for every reconciliation failure."""


class PeriodMismatch(ReconcileError):
    """A plan and an actual cover a different number of months and the caller did not opt into proration."""


@dataclass
class Tolerance:
    """D05: a measure ties when |a-b| <= abs OR |a-b| / max(|a|,|b|,1e-9) * 100 <= pct. No default tolerance."""

    abs: float
    pct: float

    def ties(self, a: float, b: float) -> bool:
        abs_diff, pct_diff = _diffs(a, b)
        return abs_diff <= self.abs or pct_diff <= self.pct


def _diffs(a: float, b: float) -> tuple[float, float]:
    abs_diff = abs(float(a) - float(b))
    denom = max(abs(float(a)), abs(float(b)), 1e-9)
    return abs_diff, abs_diff / denom * 100.0


@dataclass
class ReconResult:
    """One comparison: tied only when there are no differences and no one-sided rows."""

    differences: "object"
    only_in_a: "object"
    only_in_b: "object"
    matched: "object"
    tied: bool
    notes: tuple = ()
    crosswalk_version: "str | None" = None

    def to_rows(self) -> list[dict]:
        """Every difference and one-sided row as dicts, for the Verification tab and logs."""
        rows: list[dict] = []
        for frame in (self.differences, self.only_in_a, self.only_in_b):
            rows.extend(frame.to_dict("records"))
        return rows

    def summary(self) -> str:
        if self.tied:
            return "RECONCILED: tied within tolerance."
        return (
            f"NOT RECONCILED: {len(self.differences)} difference(s), "
            f"{len(self.only_in_a)} row(s) only in a, {len(self.only_in_b)} row(s) only in b."
        )


def _strip_keys(df, keys):
    import pandas as pd

    df = df.copy()
    for k in keys:
        df[k] = df[k].astype("string").str.strip()
    return df


def compare(a, b, keys, measures, tolerance: Tolerance, *,
            crosswalk_version: "str | None" = None, notes: "tuple | list" = ()) -> ReconResult:
    """Compare `a` and `b` on shared `keys`, within `tolerance`, for every column in `measures`.

    Never drops a row: an unmatched or duplicate-keyed row is listed in only_in_a/only_in_b, never
    summed, averaged, or paired across a duplicate."""
    import pandas as pd

    if not isinstance(tolerance, Tolerance):
        raise TypeError("compare() requires a cpa.reconcile.Tolerance instance (D05: no bare number)")
    keys = list(keys)
    measures = list(measures)
    notes = list(notes)

    a = _strip_keys(a, keys)
    b = _strip_keys(b, keys)

    a_na = a[a[keys].isna().any(axis=1)]
    b_na = b[b[keys].isna().any(axis=1)]
    a_rest = a.drop(index=a_na.index)
    b_rest = b.drop(index=b_na.index)
    if len(a_na):
        notes.append(f"{len(a_na)} row(s) in a have a blank key and were never joined")
    if len(b_na):
        notes.append(f"{len(b_na)} row(s) in b have a blank key and were never joined")

    a_dup_mask = a_rest.duplicated(subset=keys, keep=False)
    b_dup_mask = b_rest.duplicated(subset=keys, keep=False)
    a_dup, a_unique = a_rest[a_dup_mask], a_rest[~a_dup_mask]
    b_dup, b_unique = b_rest[b_dup_mask], b_rest[~b_dup_mask]
    if len(a_dup):
        notes.append(f"{len(a_dup)} row(s) in a share a duplicated key and were never joined or aggregated")
    if len(b_dup):
        notes.append(f"{len(b_dup)} row(s) in b share a duplicated key and were never joined or aggregated")

    merged = a_unique.merge(b_unique, on=keys, how="outer", suffixes=("_a", "_b"), indicator=True)

    a_rename = {f"{c}_a" if f"{c}_a" in merged.columns else c: c for c in a.columns if c not in keys}
    left_only = merged.loc[merged["_merge"] == "left_only"].rename(columns=a_rename)
    left_only = left_only[[c for c in a.columns if c in left_only.columns]]
    b_rename = {f"{c}_b" if f"{c}_b" in merged.columns else c: c for c in b.columns if c not in keys}
    right_only = merged.loc[merged["_merge"] == "right_only"].rename(columns=b_rename)
    right_only = right_only[[c for c in b.columns if c in right_only.columns]]

    only_a_parts = [p for p in (a_na, a_dup, left_only) if len(p)]
    only_in_a = pd.concat(only_a_parts, ignore_index=True) if only_a_parts else a.iloc[0:0]
    only_b_parts = [p for p in (b_na, b_dup, right_only) if len(p)]
    only_in_b = pd.concat(only_b_parts, ignore_index=True) if only_b_parts else b.iloc[0:0]

    both = merged.loc[merged["_merge"] == "both"].copy()
    diff_rows = []
    for _, row in both.iterrows():
        row_diff = {k: row[k] for k in keys}
        listed = False
        for m in measures:
            av, bv = row.get(f"{m}_a", row.get(m)), row.get(f"{m}_b", row.get(m))
            tie, av_num, bv_num = _measure_ties(av, bv, tolerance)
            if not tie:
                listed = True
                row_diff[f"a_{m}"] = av
                row_diff[f"b_{m}"] = bv
        if listed:
            diff_rows.append(row_diff)
    differences = pd.DataFrame(diff_rows) if diff_rows else pd.DataFrame(columns=keys)

    matched_cols = keys + [f"{m}_a" for m in measures] + [f"{m}_b" for m in measures]
    matched = both[[c for c in matched_cols if c in both.columns]].reset_index(drop=True)

    tied = differences.empty and only_in_a.empty and only_in_b.empty
    return ReconResult(
        differences=differences, only_in_a=only_in_a, only_in_b=only_in_b, matched=matched,
        tied=tied, notes=tuple(notes), crosswalk_version=crosswalk_version,
    )


def _measure_ties(av, bv, tolerance: Tolerance) -> tuple[bool, object, object]:
    import pandas as pd

    a_na, b_na = pd.isna(av), pd.isna(bv)
    if a_na and b_na:
        return True, av, bv
    if a_na or b_na:
        return False, av, bv
    try:
        return tolerance.ties(float(av), float(bv)), av, bv
    except (TypeError, ValueError):
        return str(av) == str(bv), av, bv


def detect_paste_errors(df, expected_columns, *, expected_rows: "int | None" = None) -> list[str]:
    """Findings for shifted columns, duplicated row blocks and truncated rows; empty means none found."""
    findings: list[str] = []
    expected_columns = list(expected_columns)
    if list(df.columns) != expected_columns and set(df.columns) == set(expected_columns):
        findings.append(
            f"columns are out of order (found {list(df.columns)}, expected {expected_columns}); "
            "a paste may have shifted them"
        )
    for col in df.columns:
        if col not in expected_columns:
            continue
        try:
            import pandas as pd

            series = df[col].dropna()
        except Exception:
            continue
        if series.empty:
            continue
        numeric_ratio = sum(1 for v in series if _looks_numeric(v)) / len(series)
        if _NUMERIC_NAME_RE.search(col) and not _LABEL_NAME_RE.search(col) and numeric_ratio < 0.5:
            findings.append(
                f"column {col!r} expected numeric values but mostly holds non-numeric data; "
                "columns may be shifted from a paste error"
            )
        if _LABEL_NAME_RE.search(col) and numeric_ratio > 0.5:
            findings.append(
                f"column {col!r} expected label/text values but mostly holds numeric data; "
                "columns may be shifted from a paste error"
            )
    dup_mask = df.duplicated(keep=False)
    if dup_mask.any():
        findings.append(f"{int(dup_mask.sum())} row(s) form duplicated row blocks (an exact repeat within the data)")
    if expected_rows is not None and len(df) < expected_rows:
        findings.append(f"truncated: expected {expected_rows} row(s), found {len(df)} -- the paste may have cut off rows")
    return findings


def _looks_numeric(v) -> bool:
    if isinstance(v, (int, float)):
        return True
    try:
        float(str(v))
        return True
    except (TypeError, ValueError):
        return False


def check_dates(series, start: date, end: date) -> list[str]:
    """Findings for values outside [start, end] or unparseable as a date; empty means none found."""
    import pandas as pd

    findings: list[str] = []
    for value in series:
        if pd.isna(value):
            continue
        text = str(value)
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            findings.append(f"{text}: not a parseable date")
            continue
        d = parsed.date()
        if not (start <= d <= end):
            findings.append(f"{text}: outside expected period [{start.isoformat()}, {end.isoformat()}]")
    return findings


def compare_plan_actual(plan, actual, keys, measures, tolerance: Tolerance, *,
                         prorate: bool = False, plan_months: "int | None" = None,
                         actual_months: "int | None" = None,
                         crosswalk_version: "str | None" = None, notes: "tuple | list" = ()) -> ReconResult:
    """compare(), but raises PeriodMismatch instead of silently comparing a plan and actual over different
    spans; when the caller opts into `prorate=True`, scales the plan's measures to the actual span via
    cpa.periods.prorate and carries its label onto the result's notes and every row it lists."""
    notes = list(notes)
    if plan_months is not None and actual_months is not None and plan_months != actual_months:
        if not prorate:
            raise PeriodMismatch(
                f"plan covers {plan_months} month(s), actual covers {actual_months} month(s); "
                "pass prorate=True to scale the plan explicitly (never compared silently)"
            )
        from cpa.periods import prorate as _prorate

        plan = plan.copy()
        label = None
        for m in measures:
            if m not in plan.columns:
                continue
            scaled_values = []
            for v in plan[m]:
                scaled, label = _prorate(float(v), plan_months, actual_months)
                scaled_values.append(scaled)
            plan[m] = scaled_values
        if label is not None:
            notes.append(label)
    elif prorate and (plan_months is None or actual_months is None):
        raise ValueError("prorate=True requires both plan_months and actual_months")
    return compare(plan, actual, keys, measures, tolerance, crosswalk_version=crosswalk_version, notes=tuple(notes))


def tolerance_from_assumptions() -> Tolerance:
    """Tolerance built from reconcile.tolerance_abs/tolerance_pct (D04, shipped in assumptions.yaml)."""
    return Tolerance(
        abs=float(config.assumption("reconcile", "tolerance_abs")),
        pct=float(config.assumption("reconcile", "tolerance_pct")),
    )


# ---------------------------------------------------------------- CLI


def _read_table(path: Path, sheet, key_cols):
    import pandas as pd

    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from cpa import bigxlsx

        if bigxlsx.is_large(path):
            print(f"{path} is a large workbook; cpa.bigxlsx streams it (hard rule 11). Not read here.")
            return None
        return pd.read_excel(
            path, sheet_name=sheet if sheet is not None else 0, engine="openpyxl",
            dtype_backend="numpy_nullable", dtype={k: "string" for k in key_cols},
        )
    return pd.read_csv(path, encoding="utf-8-sig", dtype_backend="numpy_nullable", dtype={k: "string" for k in key_cols})


def _cmd_compare(a: argparse.Namespace) -> int:
    keys = [k.strip() for k in a.keys.split(",") if k.strip()]
    measures = [m.strip() for m in a.measures.split(",") if m.strip()]

    if (a.tolerance_abs is None) != (a.tolerance_pct is None):
        print("--tolerance-abs and --tolerance-pct must be given together")
        return 2
    if a.tolerance_abs is not None:
        tolerance = Tolerance(abs=a.tolerance_abs, pct=a.tolerance_pct)
    else:
        try:
            tolerance = tolerance_from_assumptions()
        except config.MissingAssumption as exc:
            print(str(exc))
            return 1

    import pandas as pd

    frames = []
    for path, sheet in ((Path(a.a), a.sheet_a), (Path(a.b), a.sheet_b)):
        try:
            frames.append(_read_table(path, sheet, keys))
        except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
            print(f"Could not read reconciliation input {path}: {exc}")
            return 1
    df_a, df_b = frames
    if df_a is None or df_b is None:
        return 1

    requested_columns = list(dict.fromkeys([*keys, *measures]))
    for path, frame in ((Path(a.a), df_a), (Path(a.b), df_b)):
        missing = [column for column in requested_columns if column not in frame.columns]
        if missing:
            print(
                f"Input {path} is missing requested column(s): {missing}; "
                f"available columns are {list(frame.columns)}"
            )
            return 1

    crosswalk_version = None
    if a.dept_key:
        if a.dept_key not in keys:
            print(f"--dept-key {a.dept_key!r} must name one of --keys {keys}")
            return 1
        from cpa import crosswalk

        try:
            cw = crosswalk.load(a.crosswalk)
            offenders = sorted(set(crosswalk.unmatched(df_a[a.dept_key], crosswalk=cw))
                                | set(crosswalk.unmatched(df_b[a.dept_key], crosswalk=cw)))
            if offenders:
                raise crosswalk.UnmatchedDepartment(offenders, cw.path)
            df_a = df_a.copy()
            df_b = df_b.copy()
            df_a[a.dept_key] = crosswalk.normalize(df_a[a.dept_key], crosswalk=cw)
            df_b[a.dept_key] = crosswalk.normalize(df_b[a.dept_key], crosswalk=cw)
            crosswalk_version = cw.version
        except crosswalk.CrosswalkError as exc:
            print(str(exc))
            return 1
        except config.MissingReference as exc:
            print(str(exc))
            return 1

    result = compare(df_a, df_b, keys, measures, tolerance, crosswalk_version=crosswalk_version)

    if a.out:
        from cpa import fsutil

        rows = result.to_rows()
        import pandas as pd

        def _write(tmp: Path) -> None:
            pd.DataFrame(rows).to_csv(tmp, index=False, encoding="utf-8", newline="", lineterminator="\n")

        fsutil.atomic_write(Path(a.out), _write)

    if a.json:
        import json as _json

        print(_json.dumps({
            "tied": result.tied,
            "crosswalk_version": result.crosswalk_version,
            "notes": list(result.notes),
            "differences": result.differences.to_dict("records"),
            "only_in_a": result.only_in_a.to_dict("records"),
            "only_in_b": result.only_in_b.to_dict("records"),
        }, default=str))
    else:
        print(result.summary())
        for row in result.to_rows():
            print(row)
        for note in result.notes:
            print(f"note: {note}")

    return 0 if result.tied else 1


def _cmd_paste_errors(a: argparse.Namespace) -> int:
    expected = [c.strip() for c in a.expected_columns.split(",") if c.strip()]
    df = _read_table(Path(a.input), None, [])
    if df is None:
        return 1
    findings = detect_paste_errors(df, expected, expected_rows=a.expected_rows)
    if not findings:
        print("no paste-error findings")
        return 0
    for f in findings:
        print(f)
    return 1


def _cmd_check_dates(a: argparse.Namespace) -> int:
    df = _read_table(Path(a.input), None, [])
    if df is None:
        return 1
    if a.column not in df.columns:
        print(f"column {a.column!r} not found in {a.input}; columns are {list(df.columns)}")
        return 1
    findings = check_dates(df[a.column], date.fromisoformat(a.start), date.fromisoformat(a.end))
    if not findings:
        print("no date findings")
        return 0
    for f in findings:
        print(f)
    return 1


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `reconcile compare|paste-errors|check-dates`. Import-cheap: no file access here (D03)."""
    top = subparsers.add_parser("reconcile", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    p = sub.add_parser(
        "compare", help="Compare two tables on shared keys and measures within a tolerance (D05).",
        description="Exit 0 tied, 1 differences or unmatched rows listed, 2 on argument errors. "
                    "--dept-key runs both sides' department column through the crosswalk first; any "
                    "unmatched label exits 1 before anything is compared.",
    )
    p.add_argument("--a", required=True, type=Path)
    p.add_argument("--b", required=True, type=Path)
    p.add_argument("--keys", required=True, help="Comma-separated shared key columns.")
    p.add_argument("--measures", required=True, help="Comma-separated measure columns to compare.")
    p.add_argument("--dept-key", default=None, help="A --keys column to normalize through the crosswalk first.")
    p.add_argument("--crosswalk", default=None, type=Path, help="Crosswalk CSV (default: reference/dept_crosswalk.csv).")
    p.add_argument("--tolerance-abs", type=float, default=None)
    p.add_argument("--tolerance-pct", type=float, default=None)
    p.add_argument("--sheet-a", default=None)
    p.add_argument("--sheet-b", default=None)
    p.add_argument("--out", default=None, type=Path, help="Write every listed row here (CSV).")
    p.add_argument("--json", action="store_true", help="Print the full result as JSON.")
    p.set_defaults(func=_cmd_compare)

    pe = sub.add_parser(
        "paste-errors", help="Detect shifted columns, duplicated row blocks and truncated rows in a file.",
    )
    pe.add_argument("--input", required=True, type=Path)
    pe.add_argument("--expected-columns", required=True, help="Comma-separated expected column names.")
    pe.add_argument("--expected-rows", type=int, default=None)
    pe.set_defaults(func=_cmd_paste_errors)

    cd = sub.add_parser("check-dates", help="Flag values outside an expected period or unparseable as a date.")
    cd.add_argument("--input", required=True, type=Path)
    cd.add_argument("--column", required=True)
    cd.add_argument("--start", required=True, help="YYYY-MM-DD")
    cd.add_argument("--end", required=True, help="YYYY-MM-DD")
    cd.set_defaults(func=_cmd_check_dates)
