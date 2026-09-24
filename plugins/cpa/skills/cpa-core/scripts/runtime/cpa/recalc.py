"""LibreOffice headless recalculation and formula-error scan for CPA workbooks.

Build-list items: C1 recalculation check (the Verification tab's "recalculation check" column), artifact
standard "recalculated with zero errors before delivery" (R018, R033, R098).
Hard rules enforced: 11 (a workbook over 15 MB is scanned by streaming, never loaded whole).
DECISIONS D07: soffice is found in the order CPA_SOFFICE -> tools.libreoffice_path -> shutil.which over
cpa.SOFFICE_NAMES -> the default Windows install directory; no binary gives status NOT_RECALCULATED, never an
exception. Method (docs/research/methods/xlsx-formulas.md section 5): `--convert-to xlsx` round trip with a
fresh per-call profile, a 120 s timeout, and the output file checked to exist and be non-empty (the exit code
alone is never trusted). Errors are cells whose cached value is an Excel error (data type "e"), so a text label
that merely reads "#N/A" is not counted.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cpa

RECALC_TIMEOUT_S = 120
RECALCULATED = "RECALCULATED"
NOT_RECALCULATED = "NOT_RECALCULATED"
FAILED = "FAILED"
ERROR_VALUES = ("#VALUE!", "#DIV/0!", "#REF!", "#NAME?", "#NULL!", "#NUM!", "#N/A")
VERIFICATION_SHEET = "Verification"  # skipped by scan_errors; cpa.verify owns the tab

__all__ = [
    "RECALCULATED", "NOT_RECALCULATED", "FAILED", "ERROR_VALUES", "RecalcError", "ErrorCell", "RecalcResult",
    "find_soffice", "recalc", "recalc_in_place", "scan_errors", "register",
]


class RecalcError(RuntimeError):
    """A caller error (unsupported file, output dir equal to the input's dir), never a workbook finding."""


@dataclass(frozen=True)
class ErrorCell:
    """One cell whose cached value is an Excel error."""

    sheet: str
    cell: str
    value: str

    def to_json(self) -> dict:
        return {"sheet": self.sheet, "cell": self.cell, "value": self.value}


@dataclass
class RecalcResult:
    """Outcome of one LibreOffice round trip. `output` is the recalculated copy when status is RECALCULATED."""

    status: str
    reason: str = ""
    output: Path | None = None
    soffice: Path | None = None
    errors: list[ErrorCell] = field(default_factory=list)

    @property
    def recalculated(self) -> bool:
        return self.status == RECALCULATED

    def to_json(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "output": str(self.output) if self.output else None,
            "soffice": str(self.soffice) if self.soffice else None,
            "errors": [e.to_json() for e in self.errors],
        }


def _exists(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _assumption_soffice() -> Path | None:
    """D07 step 2. Any config problem (no file, bad YAML, null key) means "probe on"; never raises."""
    try:
        from cpa import config

        value = config.assumption("tools", "libreoffice_path")
    except Exception:  # noqa: BLE001 - find_soffice is read-only and must never raise (conftest collection)
        return None
    candidate = Path(str(value))
    return candidate if _exists(candidate) else None


def find_soffice() -> Path | None:
    """Locate soffice per DECISIONS D07. Read-only: creates, writes and deletes nothing, and never raises."""
    env = os.environ.get("CPA_SOFFICE")
    if env and _exists(Path(env)):
        return Path(env)
    configured = _assumption_soffice()
    if configured is not None:
        return configured
    for name in cpa.SOFFICE_NAMES:
        hit = shutil.which(name)
        if hit:
            return Path(hit)
    base = Path(*cpa.SOFFICE_WINDOWS_DIR)
    for name in cpa.SOFFICE_WINDOWS_EXES:
        if _exists(base / name):
            return base / name
    return None


def _run_soffice(argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    """The one subprocess call (test seam). List arguments, never a shell."""
    return subprocess.run(argv, timeout=timeout, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _check_suffix(path: Path) -> None:
    if path.suffix.lower() != ".xlsx":
        raise RecalcError(
            f"{path.name}: recalc handles .xlsx only; a --convert-to xlsx round trip would strip macros from "
            f"{path.suffix or 'this file'}"
        )


def recalc(path: Path | str, out_dir: Path | str, *, timeout: int = RECALC_TIMEOUT_S,
           soffice: Path | None = None) -> RecalcResult:
    """Recalculate `path` into `<out_dir>/<stem>.xlsx` with LibreOffice; the input is never modified.

    Returns NOT_RECALCULATED when no soffice is found, FAILED when LibreOffice times out, exits non-zero with no
    output, or writes an empty file; otherwise RECALCULATED with `errors` scanned from the output."""
    path, out_dir = Path(path), Path(out_dir)
    _check_suffix(path)
    if out_dir.resolve() == path.parent.resolve():
        raise RecalcError(f"out_dir must differ from {path.name}'s folder, or the round trip overwrites the input")
    exe = soffice or find_soffice()
    if exe is None:
        return RecalcResult(NOT_RECALCULATED, "LibreOffice (soffice) not found; set tools.libreoffice_path or "
                                              "CPA_SOFFICE, or install LibreOffice")
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / (path.stem + ".xlsx")
    profile = Path(tempfile.mkdtemp(prefix="cpa_lo_"))
    argv = [str(exe), "--headless", "--norestore", f"-env:UserInstallation={profile.resolve().as_uri()}",
            "--convert-to", "xlsx", "--outdir", str(out_dir), str(path)]
    try:
        proc = _run_soffice(argv, timeout)
    except subprocess.TimeoutExpired:
        return RecalcResult(FAILED, f"LibreOffice did not finish within {timeout} s", soffice=exe)
    except OSError as exc:
        return RecalcResult(FAILED, f"could not run {exe}: {exc}", soffice=exe)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if not output.is_file() or output.stat().st_size == 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        return RecalcResult(FAILED, f"LibreOffice exited {proc.returncode} and wrote no output. {detail}".strip(),
                            soffice=exe)
    return RecalcResult(RECALCULATED, "", output=output, soffice=exe, errors=scan_errors(output))


def recalc_in_place(path: Path | str, *, timeout: int = RECALC_TIMEOUT_S, soffice: Path | None = None) -> RecalcResult:
    """Recalculate `path` and replace it with the recalculated copy (atomic; the file is untouched on failure).

    The returned `output` is `path` itself."""
    from cpa import fsutil

    path = Path(path)
    work = Path(tempfile.mkdtemp(prefix="cpa_rc_"))
    try:
        result = recalc(path, work, timeout=timeout, soffice=soffice)
        if result.recalculated and result.output is not None:
            produced = result.output
            fsutil.atomic_write(path, lambda tmp: shutil.copyfile(produced, tmp))
            result.output = path
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def scan_errors(path: Path | str, skip_sheets: tuple[str, ...] = (VERIFICATION_SHEET,)) -> list[ErrorCell]:
    """Every cell whose cached value is an Excel error, in sheet then row order. Streams (openpyxl read_only)."""
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


# ---------------------------------------------------------------- CLI


def _cmd_find(args: argparse.Namespace) -> int:
    exe = find_soffice()
    print(json.dumps({"soffice": str(exe) if exe else None}))
    return 0 if exe else 1


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        result = recalc(args.workbook, args.out_dir)
    except (RecalcError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result.to_json(), indent=2))
    return 0 if result.recalculated and not result.errors else 1


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `recalc find|run`. Import-cheap: no file access here."""
    top = subparsers.add_parser("recalc", help="LibreOffice headless recalculation and formula-error scan.")
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    p = sub.add_parser("find", help="Print where soffice was found as JSON (exit 1 when not found).")
    p.set_defaults(func=_cmd_find)
    p = sub.add_parser("run", help="Recalculate a .xlsx into another folder and list formula errors as JSON.")
    p.add_argument("workbook", type=Path)
    p.add_argument("--out-dir", type=Path, required=True, dest="out_dir",
                   help="Folder for the recalculated copy (not the workbook's own folder).")
    p.set_defaults(func=_cmd_run)
