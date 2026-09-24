"""Epic adapter (A9) with the patient-level grain guard (C13): aggregate reports only, quarantine on detection.

Epic pulls are aggregate by rule (wRVU, PB encounters, charges, collections at department, division or provider
grain). Every Epic export is scanned before its data is used:
- header scan: identifier or postal-code columns (MRN, patient name/ID, DOB, SSN, CSN, encounter ID, address,
  zip/postal, phone, e-mail, guarantor, member ID), checked on the header row before any data row is read;
- value scan: a column that is neither a known aggregate column nor listed as expected for the pinned report,
  whose non-blank values are at least 90% ZIP-shaped (12345 or 12345-6789) or SSN-shaped.
On detection validate() moves the file (and its sidecar manifest) to
<workspace>/archive/epic/quarantine/<YYYY-MM-DD>/, writes <name>.quarantine.json (column names and reasons only,
never a cell value), marks the sidecar `validation: quarantined`, and the CLI exits 3 so she is notified. load()
always runs the guard and raises PatientLevelData; it never moves anything (R230).

Pinned navigation (R103, R194): the report token (file name `<report>_<FYMM>`) must be a key of `reports:` in
reference/epic_paths.yaml (U25 ships the template; `reports: {<token>: {expected_columns: [...]}}`); a missing
list or an unpinned report fails validation. The pull is refused while
`sources.epic.patient_level_grain_recurs` (INV-764) is unconfirmed. Aggregate column aliases and the value
patterns are FIXTURE - confirm against her file.
"""
from __future__ import annotations

import argparse
import re
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from cpa.sources.base import (
    QUARANTINED,
    Column,
    SourceError,
    TabularAdapter,
    Validation,
    add_source_parser,
    as_text,
    fold,
    register_adapter,
)

if TYPE_CHECKING:
    from pandas import DataFrame

__all__ = ["PatientLevelData", "IDENTIFIER_PATTERNS", "VALUE_PATTERNS", "EPIC_COLUMNS", "EpicAggregate",
           "scan_grain", "grain_guard", "quarantine", "report_token", "pinned_reports", "register_under"]

ROUTE_OUTSIDE = "route this extract outside the automated pipeline"

# Header patterns, matched against fold(header) (lower case, punctuation as spaces).
IDENTIFIER_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bmrn\b|\bmedical record\b", "medical record number"),
    (r"\bpatient\b.*\b(id|identifier|name|first|last|number|no|mrn|dob|birth|address|street|phone|email|zip|"
     r"postal)\b", "patient identifier"),
    (r"\bcsn\b", "contact serial number (encounter identifier)"),
    (r"\bencounter (id|identifier|number|no|csn)\b", "encounter identifier"),
    (r"\b(har|hospital account)\b", "hospital account identifier"),
    (r"\b(dob|date of birth|birth date|birthdate)\b", "date of birth"),
    (r"\b(ssn|social security)\b", "social security number"),
    (r"\b(zip|zipcode|zip code|postal|postcode|post code)\b", "postal code"),
    (r"\b(address|street)\b", "street address"),
    (r"\b(phone|telephone)\b", "phone number"),
    (r"\b(email|e mail)\b", "e-mail address"),
    (r"\bguarantor\b", "guarantor"),
    (r"\b(member|subscriber) (id|number|no)\b", "insurance member identifier"),
)
# FIXTURE - confirm against her file: value shapes for an unlabeled identifier column.
VALUE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^\d{5}(-\d{4})?$", "postal code values"),
    (r"^\d{3}-\d{2}-\d{4}$", "SSN-shaped values"),
)
VALUE_MATCH_FRACTION = 0.9
VALUE_MIN_COUNT = 3

# FIXTURE - confirm against her file: known aggregate columns (exempt from the value scan).
EPIC_COLUMNS: tuple[Column, ...] = (
    Column("department", ("department", "dept"), key=True),
    Column("division", ("division",), key=True),
    Column("provider", ("provider", "provider name"), dtype="str"),
    Column("provider_id", ("provider id", "npi"), key=True),
    Column("period", ("period", "fiscal period", "month"), dtype="str"),
    Column("wrvu", ("wrvu", "wrvus", "work rvu", "work rvus"), dtype="number"),
    Column("pb_encounters", ("pb encounters", "pb visits"), dtype="number"),
    Column("patient_count", ("patient count", "unique patients", "patients"), dtype="number"),
    Column("charges", ("charges", "gross charges"), dtype="number"),
    Column("gross_collections", ("gross collections",), dtype="number"),
    Column("net_collections", ("net collections",), dtype="number"),
    Column("collections", ("collections",), dtype="number"),  # as exported: gross vs net not stated (rule 6)
)
GRAIN_COLUMNS = ("department", "division", "provider", "provider_id")

_ID_RES = tuple((re.compile(p), reason) for p, reason in IDENTIFIER_PATTERNS)
_VALUE_RES = tuple((re.compile(p), reason) for p, reason in VALUE_PATTERNS)
_TOKEN_RE = re.compile(r"^(.*)_(\d{4})$")


class PatientLevelData(SourceError):
    """Identifier or postal-code data in an Epic export. `.columns` maps column -> reason (never values)."""

    def __init__(self, columns: dict[str, str], where: str = "") -> None:
        self.columns = dict(columns)
        listed = "; ".join(f"{c} ({r})" for c, r in self.columns.items())
        super().__init__(f"{where + ': ' if where else ''}patient-level data: {listed}; {ROUTE_OUTSIDE}")


def _header_reason(column: str) -> str | None:
    folded = fold(column)
    for regex, reason in _ID_RES:
        if regex.search(folded):
            return reason
    return None


def _exempt(columns: Sequence[str], expected: Iterable[str]) -> set[str]:
    """Columns the value scan skips: known aggregate columns and the pinned report's expected columns."""
    known = set(EpicAggregate().match(list(columns))[0].values())
    wanted = {fold(e) for e in expected}
    return known | {c for c in columns if fold(c) in wanted}


class _ValueScan:
    """Streaming value scan over the non-exempt columns (row_check protocol: feed(row), issues())."""

    def __init__(self, header: Sequence[str], expected: Iterable[str] = ()) -> None:
        skip = _exempt(header, expected)
        self.cols = [(i, c) for i, c in enumerate(header) if c not in skip and _header_reason(c) is None]
        self.counts = {c: [0] + [0] * len(_VALUE_RES) for _, c in self.cols}

    def feed(self, row: Sequence[Any]) -> None:
        for i, col in self.cols:
            text = as_text(row[i]) if i < len(row) else None
            if text is None:
                continue
            tally = self.counts[col]
            tally[0] += 1
            for k, (regex, _) in enumerate(_VALUE_RES, start=1):
                if regex.match(text):
                    tally[k] += 1

    def flagged(self) -> dict[str, str]:
        out = {}
        for col, tally in self.counts.items():
            total = tally[0]
            if total < VALUE_MIN_COUNT:
                continue
            for k, (_, reason) in enumerate(_VALUE_RES, start=1):
                if tally[k] / total >= VALUE_MATCH_FRACTION:
                    out[col] = f"{reason} in {tally[k]} of {total} cells"
                    break
        return out

    def issues(self) -> list[str]:
        return []  # findings are read by EpicAggregate.after_validate and quarantine, not failed


def scan_grain(columns: Sequence[str], rows: Iterable[Sequence[Any]] | None = None, *,
               expected: Iterable[str] = ()) -> dict[str, str]:
    """{column: reason} for every patient-level column: header patterns, then (when rows are given) the value
    scan on columns that are neither known aggregate columns nor in `expected`. Pure: reads no config."""
    columns = [str(c) for c in columns]
    flagged = {c: r for c in columns if (r := _header_reason(c)) is not None}
    if rows is not None:
        scan = _ValueScan(columns, expected)
        for row in rows:
            scan.feed(list(row))
        flagged.update(scan.flagged())
    return flagged


def grain_guard(df: DataFrame, *, expected: Iterable[str] = ()) -> None:
    """Guide 9: raise PatientLevelData when scan_grain flags any column of the frame."""
    rows = df.astype(object).where(df.notna(), None).values.tolist()
    flagged = scan_grain(list(df.columns), rows, expected=expected)
    if flagged:
        raise PatientLevelData(flagged)


def report_token(path: Path) -> str:
    """`fake_aggregate_2703.xlsx` -> `fake_aggregate` (the file name minus a trailing _<FYMM>)."""
    stem = Path(path).stem
    m = _TOKEN_RE.match(stem)
    return m.group(1) if m else stem


def pinned_reports() -> dict[str, list[str]] | None:
    """{report token: expected columns} from reference/epic_paths.yaml, or None when there is no list."""
    import yaml

    from cpa.config import MissingReference, reference_file

    try:
        path = reference_file("epic_paths.yaml")
    except MissingReference:
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    reports = data.get("reports") if isinstance(data, dict) else None
    if not isinstance(reports, dict) or not reports:
        return None
    return {str(k): list((v or {}).get("expected_columns") or []) if isinstance(v, dict) else []
            for k, v in reports.items()}


def _free_name(folder: Path, name: str) -> Path:
    dest = folder / name
    n = 2
    while dest.exists() or Path(f"{dest}.quarantine.json").exists():
        p = Path(name)
        dest = folder / f"{p.stem}_{n}{p.suffix}"
        n += 1
    return dest


def _move(src: Path, dest: Path) -> None:
    """shutil.move (the cpa.state archive convention), one retry on PermissionError (Excel, OneDrive)."""
    import shutil

    try:
        shutil.move(str(src), str(dest))
    except PermissionError:
        time.sleep(1.0)
        try:
            shutil.move(str(src), str(dest))
        except PermissionError as exc:
            raise SourceError(f"cannot move {src.name} to quarantine: it is open in Excel or locked by OneDrive; "
                              "close it and run validate again") from exc


def quarantine(path: Path, flagged: dict[str, str], *, root: Path | None = None, policy: Any = None) -> Path:
    """Move an Epic export (and its sidecar) to <root>/archive/epic/quarantine/<YYYY-MM-DD>/ and write
    <name>.quarantine.json beside it. Never deletes or overwrites: a name clash gets _2, _3. Returns the new path."""
    import json

    from cpa import fsutil, manifest
    from cpa.config import workspace

    path = Path(path)
    folder = Path(root or workspace()) / "archive" / "epic" / "quarantine" / date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    dest = _free_name(folder, path.name)
    digest = manifest.sha256_of(path)
    side = manifest.sidecar(path)
    _move(path, dest)
    if side.is_file():
        _move(side, manifest.sidecar(dest))
        manifest.update(dest, quarantined_to=manifest.to_rel(dest))  # `path` keeps the landing path (lineage)
    note = {
        "original": str(path),
        "quarantined_to": str(dest),
        "sha256": digest,
        "flagged": dict(flagged),
        "moved_at": manifest.utc_now_iso(),
        "patient_level_grain_recurs": policy,
        "action": ROUTE_OUTSIDE,
    }
    text = json.dumps(note, indent=2, ensure_ascii=False) + "\n"
    target = folder / f"{dest.name}.quarantine.json"
    fsutil.atomic_write(target, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))
    return dest


@register_adapter
class EpicAggregate(TabularAdapter):
    """A9 aggregate report export, guarded (C13)."""

    SOURCE = "epic"
    DATASET = "aggregate"
    PREFIX = ""
    COLUMNS = EPIC_COLUMNS

    def __init__(self) -> None:
        self._quarantine = True
        self._policy: Any = None
        self._pinned: dict[str, list[str]] | None = None
        self._path: Path | None = None
        self._scan: _ValueScan | None = None

    def _expected(self) -> list[str]:
        if self._pinned is None or self._path is None:
            return []
        return self._pinned.get(report_token(self._path), [])

    def before_read(self, path: Path) -> dict[str, Any]:
        from cpa.config import assumption

        self._policy = assumption("sources", "epic", "patient_level_grain_recurs")
        self._pinned = pinned_reports()
        self._path = Path(path)
        return {"patient_level_grain_recurs": self._policy, "report": report_token(path)}

    def _flag(self, result: Validation, flagged: dict[str, str]) -> None:
        result.status = QUARANTINED
        result.extra.setdefault("flagged", {}).update(flagged)
        result.issues += [f"patient-level column {c!r}: {r}" for c, r in flagged.items()]
        why = ("patient-level grain recurs (sources.epic.patient_level_grain_recurs is true)" if self._policy
               else "patient-level data in an export expected to be aggregate")
        result.issues.append(f"{why}: {ROUTE_OUTSIDE}")

    def header_check(self, result: Validation, header: list[str], column_map: dict[str, str]) -> None:
        flagged = scan_grain(header)
        if flagged:
            self._flag(result, flagged)
            return
        if not any(g in column_map for g in GRAIN_COLUMNS):
            result.issues.append("no aggregate grain column (department, division, provider or provider ID)")
        token = report_token(self._path) if self._path else ""
        if self._pinned is None:
            result.issues.append("no pinned Epic report list: reference/epic_paths.yaml is missing or has no "
                                 "`reports:`; only pinned reports are accepted")
        elif token not in self._pinned:
            result.issues.append(f"report {token!r} is not a pinned Epic report (reference/epic_paths.yaml: "
                                 f"{', '.join(sorted(self._pinned))})")

    def row_check(self, header: list[str], column_map: dict[str, str]) -> _ValueScan:
        self._scan = _ValueScan(header, self._expected())
        return self._scan

    def after_validate(self, path: Path, result: Validation) -> Path | None:
        if self._scan is not None and result.status != QUARANTINED:
            found = self._scan.flagged()
            if found:
                self._flag(result, found)
        result.extra.setdefault("quarantined_to", None)
        if result.status != QUARANTINED or not self._quarantine:
            return None
        dest = quarantine(path, result.extra["flagged"], policy=self._policy)
        result.extra["quarantined_to"] = str(dest)
        return dest

    def validate(self, path: Path, *, quarantine: bool = True) -> Validation:
        """Validate and, on patient-level data, quarantine (unless quarantine=False: report only)."""
        self._quarantine = quarantine
        return super().validate(path)

    def check_header_for_load(self, header: list[str], column_map: dict[str, str]) -> None:
        flagged = scan_grain(header)
        if flagged:
            raise PatientLevelData(flagged, where=self._path.name if self._path else "")

    def load(self, path: Path) -> DataFrame:
        """The aggregate frame; PatientLevelData (file untouched) when the guard flags anything (R230)."""
        frame = super().load(path)
        try:
            grain_guard(frame, expected=self._expected())
        except PatientLevelData as exc:
            raise PatientLevelData(exc.columns, where=Path(path).name) from None
        return frame


def register_under(sub: argparse._SubParsersAction) -> None:
    """`sources epic validate <file> [--no-quarantine]`. Import-cheap."""

    def args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--no-quarantine", action="store_true",
                       help="Report patient-level data (exit 3) but leave the file where it is.")

    add_source_parser(sub, "epic", "Epic aggregate exports (A9): validate with the patient-level grain guard "
                                   "(C13). Read only; pinned reports only.",
                      validate_args=args, validate_kwargs=lambda a: {"quarantine": not a.no_quarantine})
