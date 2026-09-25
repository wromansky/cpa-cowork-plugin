"""CRF (recruitment cost) report (B15, guide 5/9, Build List :197-203).

`build(export, prior=...)` reads this period's A6 CRF export through the `cognos.crf` adapter
(R143: never hand-parsed), then rolls forward last period's `Commitments` sheet -- the report this
same module wrote -- rather than starting from nothing every month ("rebuild the report structure
from the prior file"):

- a provider in both the prior report and this period's export stays (or becomes) Open, with this
  period's compensation package / startup funds / commitment amount;
- a provider that was Open in the prior report and is absent from this period's export is marked
  Closed here, with a note saying why -- never silently dropped (acceptance: "every prior commitment
  present or explicitly closed", R073/R123);
- a provider already Closed in the prior report and still absent from the export is carried forward
  unchanged;
- a provider only in this period's export is a new commitment, Open.

Because every Open row's amount comes straight from this period's export, the report's Open total
ties to the export by construction; `manifest.add_figure` and `cpa.verify`'s Verification tab (C1)
record and re-check that. `cognos.CRF_COLUMNS` does not require `commitment_amount` (only `provider`
is), so a real export row can carry a blank one: that row's amount stays None (never coerced to
0.0), gets a `MISSING: commitment_amount not supplied` Note and a yellow-filled amount cell, and is
excluded from the total -- hard rule 8, the row reads as missing, never as a confirmed zero. Department
labels go through `cpa.crosswalk.normalize` (an unmatched label fails loudly, hard rule). Nothing
here posts, sends, or writes to a source system.
"""
from __future__ import annotations

from cpa import office

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "CrfError", "PriorReportError",
    "COMMITMENTS_SHEET", "COMMITMENT_HEADER", "STATUS_OPEN", "STATUS_CLOSED",
    "Commitment", "BuildResult",
    "load_prior_commitments", "build", "register",
]

COMMITMENTS_SHEET = "Commitments"
COMMITMENT_HEADER: tuple[str, ...] = (
    "Provider", "Department", "Compensation Package", "Startup Funds", "Commitment Amount",
    "Status", "Note",
)
STATUS_OPEN = "Open"
STATUS_CLOSED = "Closed"
_CLOSED_NOTE = "closed: not present in this period's CRF export"
_REOPEN_NOTE = "reopened: present again in this period's CRF export"
_NEW_NOTE = "new this period"
_MISSING_COMMITMENT_NOTE = "MISSING: commitment_amount not supplied"
EXIT_OK, EXIT_STOPPED = 0, 1


class CrfError(RuntimeError):
    """The CRF build stopped before writing anything; the message says why."""


class PriorReportError(CrfError):
    """Last period's CRF report is not one this module can read (missing/garbled Commitments sheet)."""


@dataclass(frozen=True)
class Commitment:
    """One row of the `Commitments` sheet."""

    provider: str
    department: str | None
    compensation_package: float | None
    startup_funds: float | None
    commitment_amount: float | None
    status: str
    note: str

    def as_row(self) -> tuple:
        return (self.provider, self.department, self.compensation_package, self.startup_funds,
                self.commitment_amount, self.status, self.note)


@dataclass(frozen=True)
class BuildResult:
    """What `build()` wrote."""

    output: Path
    period: str
    total_commitment_amount: float
    open_count: int
    closed_count: int
    newly_closed: tuple[str, ...] = field(default_factory=tuple)
    new: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, Any]:
        return {
            "output": str(self.output), "period": self.period,
            "total_commitment_amount": self.total_commitment_amount,
            "open_count": self.open_count, "closed_count": self.closed_count,
            "newly_closed": list(self.newly_closed), "new": list(self.new),
        }


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        import pandas as pd

        if value is pd.NA:
            return None
    except ImportError:  # pragma: no cover - pandas is a hard dependency (D09)
        pass
    return float(value)


def load_prior_commitments(path: Path | str) -> dict[str, Commitment]:
    """Read the `Commitments` sheet of a CRF report this module wrote earlier. Raises PriorReportError
    when the file is not readable, over 15 MB (hard rule 11 -- CRF reports are never legitimately
    that size; the check is defensive), or has no `Commitments` sheet with `COMMITMENT_HEADER`."""
    import openpyxl

    from cpa import bigxlsx

    p = Path(path)
    if not p.is_file():
        raise PriorReportError(f"prior CRF report not found: {p}")
    if bigxlsx.is_large(p):
        raise PriorReportError(f"{p.name} is over 15 MB; a CRF report is never that size (hard rule 11)")
    try:
        wb = openpyxl.load_workbook(str(p), data_only=True)
    except Exception as exc:  # openpyxl raises several exception types for a garbled file
        raise PriorReportError(f"{p.name} could not be read as a workbook: {exc}") from exc
    if COMMITMENTS_SHEET not in wb.sheetnames:
        raise PriorReportError(f"{p.name} has no {COMMITMENTS_SHEET!r} sheet; sheets are {wb.sheetnames}")
    ws = wb[COMMITMENTS_SHEET]
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows, ()))
    if header != list(COMMITMENT_HEADER):
        raise PriorReportError(f"{p.name} {COMMITMENTS_SHEET!r} header is {header}; expected "
                               f"{list(COMMITMENT_HEADER)} (a CRF report from an earlier version of this module?)")
    out: dict[str, Commitment] = {}
    for row in rows:
        if row is None or all(v is None for v in row):
            continue
        provider, department, comp, startup, commitment, status, note = row
        if not provider:
            raise PriorReportError(f"{p.name} {COMMITMENTS_SHEET!r} has a row with no provider")
        out[str(provider)] = Commitment(
            provider=str(provider), department=department, compensation_package=_num(comp),
            startup_funds=_num(startup), commitment_amount=_num(commitment), status=str(status),
            note=note or "",
        )
    return out


def _load_current(export: Path) -> dict[str, Commitment]:
    from cpa import crosswalk, sources

    frame = sources.get("cognos.crf").load(export)
    if len(frame) and "department" in frame.columns:
        frame = frame.assign(department=crosswalk.normalize(frame["department"]))
    current: dict[str, Commitment] = {}
    for record in frame.to_dict("records"):
        provider = record.get("provider")
        if not provider:
            raise CrfError(f"{export.name}: a row has no provider name")
        current[str(provider)] = Commitment(
            provider=str(provider), department=record.get("department"),
            compensation_package=_num(record.get("compensation_package")),
            startup_funds=_num(record.get("startup_funds")),
            commitment_amount=_num(record.get("commitment_amount")),
            status=STATUS_OPEN, note="",
        )
    return current


def _roll_forward(prior: dict[str, Commitment], current: dict[str, Commitment]
                   ) -> tuple[list[Commitment], list[str], list[str]]:
    rows: list[Commitment] = []
    newly_closed: list[str] = []
    remaining = dict(current)
    for provider, was in prior.items():
        now = remaining.pop(provider, None)
        if now is not None:
            note = _REOPEN_NOTE if was.status == STATUS_CLOSED else ""
            rows.append(Commitment(provider=provider, department=now.department,
                                   compensation_package=now.compensation_package,
                                   startup_funds=now.startup_funds, commitment_amount=now.commitment_amount,
                                   status=STATUS_OPEN, note=note))
        elif was.status == STATUS_OPEN:
            rows.append(Commitment(provider=provider, department=was.department,
                                   compensation_package=was.compensation_package,
                                   startup_funds=was.startup_funds, commitment_amount=was.commitment_amount,
                                   status=STATUS_CLOSED, note=_CLOSED_NOTE))
            newly_closed.append(provider)
        else:
            rows.append(was)  # already closed, still absent: carried forward unchanged
    new = sorted(remaining)
    for provider in new:
        c = remaining[provider]
        rows.append(Commitment(provider=c.provider, department=c.department,
                               compensation_package=c.compensation_package, startup_funds=c.startup_funds,
                               commitment_amount=c.commitment_amount, status=STATUS_OPEN, note=_NEW_NOTE))
    return rows, newly_closed, new


def _flag_missing_commitment(rows: list[Commitment]) -> list[Commitment]:
    """An Open row whose export had no `commitment_amount` (`cognos.crf`'s CRF_COLUMNS does not
    require it -- only `provider` is required) stays None -- never coerced to 0.0 -- and gets an
    explicit Note flag so the row reads as missing, not as a confirmed zero commitment (hard rule 8:
    a missing figure is flagged, never silently defaulted or estimated)."""
    out: list[Commitment] = []
    for r in rows:
        if r.status == STATUS_OPEN and r.commitment_amount is None:
            note = f"{r.note}; {_MISSING_COMMITMENT_NOTE}" if r.note else _MISSING_COMMITMENT_NOTE
            out.append(Commitment(provider=r.provider, department=r.department,
                                  compensation_package=r.compensation_package, startup_funds=r.startup_funds,
                                  commitment_amount=None, status=r.status, note=note))
        else:
            out.append(r)
    return out


def _write_workbook(out: Path, rows: list[Commitment], total: float, missing_count: int) -> None:
    import openpyxl
    from openpyxl.styles import PatternFill

    from cpa import config, fsutil

    # A flagged row (Open, commitment_amount missing) gets its blank amount cell filled yellow, the
    # same brand.flag_yellow convention cpa.activity_block uses for the M2 block (DECISIONS D08/D24):
    # fetched only when actually needed, so a build with nothing missing never touches the assumption.
    fill = None
    if any(r.status == STATUS_OPEN and r.commitment_amount is None for r in rows):
        from cpa.pptx import brand

        yellow = brand.color("flag_yellow").lstrip("#")
        fill = PatternFill(fill_type="solid", fgColor=yellow, bgColor=yellow)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = COMMITMENTS_SHEET
    ws.append(list(COMMITMENT_HEADER))
    amount_col = COMMITMENT_HEADER.index("Commitment Amount") + 1
    for c in sorted(rows, key=lambda r: r.provider):
        ws.append(list(c.as_row()))
        if fill is not None and c.status == STATUS_OPEN and c.commitment_amount is None:
            ws.cell(row=ws.max_row, column=amount_col).fill = fill
    summary = wb.create_sheet("Summary")
    summary.append(["Figure", "Value"])
    summary.append(["Total commitment amount (open rows with supplied amounts)", total])
    summary.append(["Open rows missing commitment amount", missing_count])
    from cpa.pptx import brand

    for sheet in wb.worksheets:
        brand.style_generated_sheet(sheet)
    office.save_workbook(wb, out)


def _write_figure_evidence(path: Path, open_rows: list[Commitment]) -> str:
    """Write auditable row-level evidence for the open-commitment total and missing count."""
    import csv

    from cpa import fsutil

    table = [["Provider", "Commitment Amount", "Missing Amount Flag"]]
    table.extend([r.provider, r.commitment_amount, int(r.commitment_amount is None)] for r in open_rows)
    if not open_rows:
        # Explicit empty-set evidence allows both aggregates to sum to zero without inventing a provider.
        table.append(["(no open commitments)", 0, 0])
    def write(tmp: Path) -> None:
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(table)
    fsutil.atomic_write(path, write)
    end_row = len(table)
    return f"B2:B{end_row}", f"C2:C{end_row}"


def _export_amount_ref(export: Path) -> str:
    """Return the A1 range for the export's actual commitment-amount column (D21)."""
    from openpyxl.utils import get_column_letter

    from cpa import bigxlsx, sources

    adapter = sources.get("cognos.crf")
    header, body = adapter.read(export)
    try:
        columns, _missing = adapter.match(header)
        if "commitment_amount" not in columns:
            raise CrfError(f"{export.name}: CRF export has no commitment amount column")
        amount_column = header.index(columns["commitment_amount"]) + 1
        row_count = sum(1 for _ in body)
    finally:
        body.close()
    sheet = bigxlsx.sheet_names(export)[0]
    quoted_sheet = "'" + sheet.replace("'", "''") + "'"
    column = get_column_letter(amount_column)
    end_row = max(row_count + 1, 2)
    return f"{quoted_sheet}!{column}2:{column}{end_row}"


def build(export: Path | str, *, prior: Path | str | None = None, period: str | None = None,
          root: Path | None = None) -> BuildResult:
    """Build this period's CRF report from `export` (an A6 `crf_<FYMM>.xlsx`), rolling forward
    `prior`'s `Commitments` sheet when given. Nothing is written until every input is read and
    checked (crosswalk failures, a malformed prior report, or a bad export all raise first)."""
    from cpa import config, manifest, periods, verify

    export_path = Path(export)
    fymm = period if period is not None else periods.fymm_from_filename(export_path.name)
    periods.parse_fymm(fymm)
    prior_path = Path(prior) if prior is not None else None

    prior_commitments = load_prior_commitments(prior_path) if prior_path is not None else {}
    current = _load_current(export_path)
    rows, newly_closed, new = _roll_forward(prior_commitments, current)
    rows = _flag_missing_commitment(rows)

    ws = Path(root) if root is not None else config.workspace()
    out = ws / "outbox" / "crf" / fymm / f"CRF_{fymm}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    open_rows = [r for r in rows if r.status == STATUS_OPEN]
    # A missing commitment_amount is flagged (above), never folded into the total as 0.0 (hard rule 8).
    total = sum(r.commitment_amount for r in open_rows if r.commitment_amount is not None)
    missing_count = sum(1 for r in open_rows if r.commitment_amount is None)
    _write_workbook(out, rows, total, missing_count)

    from datetime import date

    inputs = [export_path] + ([prior_path] if prior_path is not None else [])
    manifest.write(out, source="cognos.crf", report="crf", filters="", as_of=date.today().isoformat(),
                   row_count=len(rows), inputs=inputs, status="actual", period=fymm)
    evidence_path = out.with_name(f"CRF_{fymm}_figure_evidence.csv")
    total_ref, missing_ref = _write_figure_evidence(evidence_path, open_rows)
    # This derived evidence is only assigned a source-system lineage when the export has one. With no
    # source manifest, verify reports SOURCE_UNKNOWN rather than manufacturing provenance.
    if manifest.exists(export_path):
        manifest.write(
            evidence_path, source="derived", report="CRF figure evidence", filters="open commitments only",
            as_of=date.today().isoformat(), row_count=len(open_rows), inputs=[export_path],
            status="actual", period=fymm,
        )
    manifest.add_figure(
        out, "crf.total_commitment_amount", total, source_file=export_path,
        source_ref=_export_amount_ref(export_path), cell="Summary!B2", status="actual", period=fymm,
    )
    manifest.add_figure(
        out, "crf.missing_commitment_amount_count", missing_count, source_file=evidence_path,
        source_ref=missing_ref, cell="Summary!B3", status="actual", period=fymm,
    )

    verify.build_verification_tab(out, prior=prior_path)

    return BuildResult(output=out, period=fymm, total_commitment_amount=total, open_count=len(open_rows),
                       closed_count=len(rows) - len(open_rows), newly_closed=tuple(newly_closed),
                       new=tuple(new))


def _cmd_build(args: argparse.Namespace) -> int:
    from cpa import config, sources
    from cpa.crosswalk import CrosswalkError

    try:
        result = build(args.export, prior=args.prior, period=args.period, root=args.root)
    except (CrfError, CrosswalkError, sources.SourceError, config.ConfigError, ValueError, OSError) as exc:
        print(f"cpa crf: {exc}", file=sys.stderr)
        return EXIT_STOPPED
    if args.json:
        print(__import__("json").dumps(result.to_json()))
    else:
        print(f"{result.period}: {result.output} -- {result.open_count} open, {result.closed_count} closed "
              f"({len(result.newly_closed)} newly closed, {len(result.new)} new), "
              f"total {result.total_commitment_amount:,.2f}")
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `crf build`. Import-cheap: no file access here (D03)."""
    top = subparsers.add_parser("crf", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    p = sub.add_parser(
        "build", help="Build this period's CRF report, rolling forward last period's commitments.",
        description="Read the A6 CRF export, roll last period's Commitments sheet forward (present or "
                    "explicitly Closed), write outbox/crf/<period>/CRF_<period>.xlsx with a Verification "
                    "tab (C1). Exit 0 done, 1 stopped.")
    p.add_argument("--export", required=True, type=Path, help="This period's crf_<FYMM>.xlsx export (A6).")
    p.add_argument("--prior", type=Path, default=None, help="Last period's CRF_<FYMM>.xlsx report.")
    p.add_argument("--period", default=None, help="FYMM (default: inferred from --export's filename).")
    p.add_argument("--root", type=Path, default=None, help="Workspace root (default: cpa.config.workspace()).")
    p.add_argument("--json", action="store_true", help="Print the result as one JSON object.")
    p.set_defaults(func=_cmd_build)
