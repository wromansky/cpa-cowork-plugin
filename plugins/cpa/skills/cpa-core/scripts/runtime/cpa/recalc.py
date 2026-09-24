"""Recalculation status and cached formula-error scans for CPA workbooks.

C1 verification (R018, R033, R098) must not claim recalculation without a verified backend.
LibreOffice is excluded from the workflow on every platform, including Cowork sandboxes.
No replacement engine is implemented. Calls return NOT_RECALCULATED without executing an
external program or modifying the input. Cached error scanning is not recalculation.
Hard rule 11: scan large workbooks with read-only streaming.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

RECALC_TIMEOUT_S = 120
RECALCULATED = "RECALCULATED"
NOT_RECALCULATED = "NOT_RECALCULATED"
FAILED = "FAILED"
UNSUPPORTED_REASON = "Automatic workbook recalculation is unsupported; no approved backend is implemented."
ERROR_VALUES = ("#VALUE!", "#DIV/0!", "#REF!", "#NAME?", "#NULL!", "#NUM!", "#N/A")
VERIFICATION_SHEET = "Verification"


class RecalcError(RuntimeError):
    """An invalid recalculation request, not a workbook finding."""


@dataclass(frozen=True)
class ErrorCell:
    """One cached Excel error cell."""

    sheet: str
    cell: str
    value: str

    def to_json(self) -> dict:
        """Return the cell location and cached error."""
        return {"sheet": self.sheet, "cell": self.cell, "value": self.value}


@dataclass
class RecalcResult:
    """Recalculation outcome; unsupported is never successful."""

    status: str
    reason: str = ""
    output: Path | None = None
    soffice: Path | None = None  # Legacy result compatibility only; never used to execute anything.
    errors: list[ErrorCell] = field(default_factory=list)

    @property
    def recalculated(self) -> bool:
        """Whether an actual recalculation succeeded."""
        return self.status == RECALCULATED

    def to_json(self) -> dict:
        """Return the outcome without implying an engine is available."""
        return {"status": self.status, "reason": self.reason,
                "output": str(self.output) if self.output else None,
                "errors": [e.to_json() for e in self.errors]}


def find_soffice() -> None:
    """Retired compatibility hook: never probes, reads configuration, or locates an engine."""
    return None


def recalc(path: Path | str, out_dir: Path | str, *, timeout: int = RECALC_TIMEOUT_S,
           soffice: Path | None = None) -> RecalcResult:
    """Return unsupported without writing files or executing a program.

    Legacy timeout and executable arguments cannot enable the removed backend.
    """
    path, out_dir = Path(path), Path(out_dir)
    if path.suffix.lower() != ".xlsx":
        raise RecalcError(f"{path.name}: recalc handles .xlsx only")
    if out_dir.resolve() == path.parent.resolve():
        raise RecalcError("out_dir must differ from the input folder")
    return RecalcResult(NOT_RECALCULATED, UNSUPPORTED_REASON)


def recalc_in_place(path: Path | str, *, timeout: int = RECALC_TIMEOUT_S,
                    soffice: Path | None = None) -> RecalcResult:
    """Preserve the workbook on unsupported or failed recalculation.

    The result protocol is retained for a future approved backend and fixture verification tests.
    """
    from cpa import fsutil

    path = Path(path)
    with tempfile.TemporaryDirectory(prefix="cpa_rc_") as temporary:
        result = recalc(path, Path(temporary), timeout=timeout, soffice=soffice)
        if result.recalculated and result.output is not None:
            fsutil.atomic_write(path, lambda tmp: shutil.copyfile(result.output, tmp))
            result.output = path
        return result


def scan_errors(path: Path | str, skip_sheets: tuple[str, ...] = (VERIFICATION_SHEET,)) -> list[ErrorCell]:
    """Stream cached Excel errors; this does not calculate formulas or validate cache freshness."""
    import openpyxl

    found: list[ErrorCell] = []
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True, keep_links=False)
    try:
        for ws in wb.worksheets:
            if ws.title in skip_sheets:
                continue
            for row in ws.iter_rows():
                for cell in row:
                    if getattr(cell, "data_type", None) == "e" and cell.value is not None:
                        found.append(ErrorCell(ws.title, cell.coordinate, str(cell.value)))
    finally:
        wb.close()
    return found


def _cmd_find(args: argparse.Namespace) -> int:
    print(json.dumps({"available": False, "status": NOT_RECALCULATED, "reason": UNSUPPORTED_REASON}))
    return 1


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        result = recalc(args.workbook, args.out_dir)
    except (RecalcError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result.to_json(), indent=2))
    return 0 if result.recalculated and not result.errors else 1


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the recalculation status interface without probing the host."""
    top = subparsers.add_parser("recalc", help="Workbook recalculation status and cached error scans.")
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    p = sub.add_parser("find", help="Report unsupported automatic recalculation (exit 1).")
    p.set_defaults(func=_cmd_find)
    p = sub.add_parser("run", help="Report recalculation status; no automatic backend is implemented.")
    p.add_argument("workbook", type=Path)
    p.add_argument("--out-dir", type=Path, required=True, dest="out_dir", help="Requested output folder.")
    p.set_defaults(func=_cmd_run)
