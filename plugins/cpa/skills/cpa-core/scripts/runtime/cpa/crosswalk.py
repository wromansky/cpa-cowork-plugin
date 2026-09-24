"""Department crosswalk (C4): raw label -> canonical department, fails loudly on unmatched.

Build-list items: C4 department crosswalk normalizer (guide 9 crosswalk.py). Hard rule enforced:
"unmatched department labels fail loudly" (AGENTS.md); no fuzzy matching, no guessed canonical name
(hard rule 15). `reference/dept_crosswalk.csv` is seeded only from the recurring department names in
`FPA_Work_Inventory_CPA.md` section A (line 54); it grows only when normalize() fails and she adds a
row -- code never invents one.

Read policy (D10): the crosswalk CSV is read with encoding="utf-8-sig"; key/label values are folded
(stripped, casefolded) before lookup, never fuzzy-matched. A blank label is an offender, never a
silently dropped row.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

from cpa import config

__all__ = [
    "CROSSWALK_NAME", "CrosswalkError", "UnmatchedDepartment", "CrosswalkNotReadable",
    "CrosswalkConflict", "Crosswalk", "crosswalk_path", "fold", "load", "version",
    "normalize", "unmatched", "register",
]

CROSSWALK_NAME = "dept_crosswalk.csv"


class CrosswalkError(Exception):
    """Base for every crosswalk failure."""


class UnmatchedDepartment(CrosswalkError):
    """One or more labels have no row in the crosswalk. Carries `.offenders` (sorted, deduped)."""

    def __init__(self, offenders: list[str], path: Path) -> None:
        self.offenders = sorted(set(offenders))
        self.path = path
        listing = ", ".join(repr(o) for o in self.offenders)
        super().__init__(
            f"{len(self.offenders)} unmatched department label(s) not found in {path}: {listing}. "
            "Add a row (add a raw_label -> canonical_department mapping) and re-run; never guessed."
        )


class CrosswalkNotReadable(CrosswalkError):
    """The crosswalk file could not be decoded or parsed."""


class CrosswalkConflict(CrosswalkError):
    """Two rows fold to the same key but map to different canonical names."""


@dataclass
class Crosswalk:
    """A loaded crosswalk: folded raw label -> canonical department, plus a content-addressed version."""

    path: Path
    rows: list[tuple[str, str]] = field(default_factory=list)  # (raw_label, canonical_department), file order
    _by_fold: dict[str, str] = field(default_factory=dict)

    def lookup(self, label: object) -> str | None:
        """The canonical department for `label`, or None when unmatched."""
        return self._by_fold.get(fold(label))

    @property
    def version(self) -> str:
        return version(crosswalk=self)


def fold(label: object) -> str:
    """Case- and whitespace-only folding key; no fuzzy matching. None/NA/'' fold to ''."""
    if label is None:
        return ""
    text = str(label)
    if text.lower() == "nan":
        return ""
    return text.strip().casefold()


def crosswalk_path(path: "Path | str | None" = None) -> Path:
    """`path` if given, else `reference/dept_crosswalk.csv` via cpa.config.reference_file (workspace copy wins)."""
    if path is not None:
        return Path(path)
    return config.reference_file(CROSSWALK_NAME)


def _resolve(crosswalk: "Path | str | Crosswalk | None") -> Crosswalk:
    if isinstance(crosswalk, Crosswalk):
        return crosswalk
    return load(crosswalk)


def load(path: "Path | str | None" = None) -> Crosswalk:
    """Read the crosswalk CSV (encoding='utf-8-sig'); raises CrosswalkError or config.MissingReference."""
    p = crosswalk_path(path)
    if not p.is_file():
        raise config.MissingReference(f"crosswalk file {p} does not exist")
    try:
        text = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CrosswalkNotReadable(
            f"{p} could not be decoded as UTF-8 (with or without a BOM): {exc}. "
            "Re-save it as UTF-8 (Excel: Save As > CSV UTF-8)."
        ) from exc
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None or {"raw_label", "canonical_department"} - set(reader.fieldnames):
        raise CrosswalkNotReadable(
            f"{p} must have columns raw_label,canonical_department; found {reader.fieldnames}"
        )
    rows: list[tuple[str, str]] = []
    by_fold: dict[str, str] = {}
    for row in reader:
        raw = (row.get("raw_label") or "").strip()
        canonical = (row.get("canonical_department") or "").strip()
        if not raw:
            continue
        rows.append((raw, canonical))
        key = fold(raw)
        if key in by_fold and by_fold[key] != canonical:
            raise CrosswalkConflict(
                f"{p}: {raw!r} folds to a key already mapped to {by_fold[key]!r}, but this row maps it to "
                f"{canonical!r}. Fix the duplicate row."
            )
        by_fold[key] = canonical
    return Crosswalk(path=p, rows=rows, _by_fold=by_fold)


def version(*, crosswalk: "Path | str | Crosswalk | None" = None) -> str:
    """Short content-addressed version of the crosswalk (raw_label,canonical_department rows, in file order)."""
    cw = _resolve(crosswalk)
    payload = "\n".join(f"{raw}\t{canonical}" for raw, canonical in cw.rows).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def normalize(series, *, crosswalk: "Path | str | Crosswalk | None" = None) -> "object":
    """Canonical names for a label Series, same length/index/order. Raises UnmatchedDepartment (every offender)."""
    import pandas as pd

    cw = _resolve(crosswalk)
    offenders = unmatched(series, crosswalk=cw)
    if offenders:
        raise UnmatchedDepartment(offenders, cw.path)
    return pd.Series([cw.lookup(v) for v in series], index=series.index, name=series.name)


def unmatched(series, *, crosswalk: "Path | str | Crosswalk | None" = None) -> list[str]:
    """Every raw label in `series` with no crosswalk row (a blank label counts); never drops a row."""
    cw = _resolve(crosswalk)
    return [str(v) if v is not None else "" for v in series if cw.lookup(v) is None]


# ---------------------------------------------------------------- CLI


def _read_input(path: Path, column: str, sheet):
    import pandas as pd

    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from cpa import bigxlsx

        if bigxlsx.is_large(path):
            print(
                f"{path} is a large workbook (>= {bigxlsx.STREAM_THRESHOLD_BYTES} bytes uncompressed); "
                "cpa.bigxlsx streams it instead. Use `python -m cpa` tooling built on bigxlsx.iter_rows "
                "for this file."
            )
            return None
        df = pd.read_excel(
            path, sheet_name=sheet if sheet is not None else 0, engine="openpyxl",
            dtype_backend="numpy_nullable", dtype={column: "string"},
        )
    else:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype_backend="numpy_nullable", dtype={column: "string"})
    if column not in df.columns:
        print(f"column {column!r} not found in {path}; columns are {list(df.columns)}")
        return None
    return df


def _cmd_normalize(a: argparse.Namespace) -> int:
    from cpa import fsutil

    df = _read_input(Path(a.input), a.column, a.sheet)
    if df is None:
        return 1
    series = df[a.column].astype("string").str.strip()
    try:
        normalized = normalize(series, crosswalk=a.crosswalk)
    except UnmatchedDepartment as exc:
        print(str(exc))
        return 1
    except CrosswalkError as exc:
        print(str(exc))
        return 1
    if a.out:
        df[a.column] = normalized
        out_path = Path(a.out)

        def _write(tmp: Path) -> None:
            df.to_csv(tmp, index=False, encoding="utf-8", newline="", lineterminator="\n")

        fsutil.atomic_write(out_path, _write)
        print(f"wrote {len(df)} normalized row(s) to {out_path}")
    else:
        print(f"all {len(df)} label(s) matched the crosswalk")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `crosswalk normalize`. Import-cheap: no file access here (D03)."""
    top = subparsers.add_parser("crosswalk", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    p = sub.add_parser(
        "normalize",
        help="Map a column of raw department labels to canonical names; unmatched labels fail loudly.",
        description="Every unmatched label is listed with the crosswalk path; nothing is written when any "
                    "label is unmatched. Exit 0 all matched, 1 unmatched labels listed.",
    )
    p.add_argument("--input", required=True, type=Path, help="CSV or .xlsx file (refused if bigxlsx.is_large()).")
    p.add_argument("--column", required=True, help="Column of raw department labels.")
    p.add_argument("--sheet", default=None, help="Sheet name for .xlsx input (default: first sheet).")
    p.add_argument("--out", default=None, type=Path, help="Write the normalized table here (CSV).")
    p.add_argument("--crosswalk", default=None, type=Path, help="Crosswalk CSV (default: reference/dept_crosswalk.csv).")
    p.set_defaults(func=_cmd_normalize)
