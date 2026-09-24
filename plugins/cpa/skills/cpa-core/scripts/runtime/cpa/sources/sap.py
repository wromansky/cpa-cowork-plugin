"""SAP adapter (C8; A10-A12): salary extract, CO line item detail, misposting locator. Read and export only.

Hard rule 12: SAP access goes through this module, reached by name through the registry
(`cpa.sources.get("sap.salary")`, `get("sap.co_lineitems")`) so the Workday adapter can replace it at cutover
(cpa/sources/workday.py shares these COLUMNS). Nothing here writes to SAP or opens a session; `locate` reads an
export she already landed and the only file it can write is the --out result.

The header aliases are FIXTURE - confirm against her file: spellings follow the Build List (A10, A11) and U05's
CO_LINEITEMS_HEADER; the swap step is `python -m cpa sources sap validate <her export>` and adding her spellings
to the aliases below.

Salary extract (A10) is gated by `sources.sap.salary_extract_format` (INV-269): until she confirms the layout,
validate/load stop naming the key before any byte is read.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from cpa.sources.base import (
    Column,
    SchemaMismatch,
    SourceError,
    TabularAdapter,
    add_source_parser,
    as_text,
    register_adapter,
    run_guarded,
)

__all__ = ["SALARY_COLUMNS", "CO_COLUMNS", "SapSalary", "SapCoLineItems", "LocateResult", "locate", "register_under"]

# FIXTURE - confirm against her file (A10 salary extract layout).
SALARY_COLUMNS: tuple[Column, ...] = (
    Column("provider_id", ("provider id", "personnel number", "pernr", "employee id"), required=True, key=True),
    Column("provider", ("provider", "provider name", "employee name"), dtype="str"),
    Column("base_salary", ("base salary", "base", "annual base", "annual base salary"), required=True,
           dtype="number"),
    Column("supplements", ("supplements", "supplement", "supplemental pay"), required=True, dtype="number"),
)

# FIXTURE - confirm against her file (A11: the ten named columns are required; A12 needs amount, document, line).
CO_COLUMNS: tuple[Column, ...] = (
    Column("cost_center", ("cost center", "cost center number", "cost centre"), required=True, key=True),
    Column("internal_order", ("internal order", "internal order number", "order"), required=True, key=True),
    Column("cost_element", ("cost element", "cost element number"), required=True, key=True),
    Column("gaap_lvl_2", ("gaap lvl 2", "gaap level 2"), required=True, dtype="str"),
    Column("gaap_lvl_4", ("gaap lvl 4", "gaap level 4"), required=True, dtype="str"),
    Column("people_vs_thing", ("people vs thing", "people vs. thing"), required=True, dtype="str"),
    Column("active_vs_inactive", ("active vs inactive", "active vs. inactive"), required=True, dtype="str"),
    Column("line_item_text", ("line item text", "co document line item text"), required=True, dtype="str"),
    Column("partner_cost_center", ("partner cost center", "partner cost centre"), required=True, key=True),
    Column("partner_order", ("partner order",), required=True, key=True),
    Column("fiscal_period", ("fiscal period", "period"), dtype="str"),
    Column("amount", ("amount",), dtype="number"),
    Column("document_number", ("document number", "co document number", "document no"), key=True),
    Column("line_item", ("line item", "document line", "posting row"), key=True),
)


@register_adapter
class SapSalary(TabularAdapter):
    """A10 salary extract: one row per provider; base and supplements present."""

    SOURCE = "sap"
    DATASET = "salary"
    PREFIX = "salary_"
    COLUMNS = SALARY_COLUMNS
    ONE_ROW_PER = ("provider_id",)

    def before_read(self, path: Path) -> dict[str, Any]:
        from cpa.config import assumption

        return {"salary_extract_format": assumption("sources", "sap", "salary_extract_format")}


@register_adapter
class SapCoLineItems(TabularAdapter):
    """A11 CO line item detail (often above 15 MB; streamed)."""

    SOURCE = "sap"
    DATASET = "co_lineitems"
    PREFIX = "co_lineitems_"
    COLUMNS = CO_COLUMNS


# ------------------------------------------------------------------------------------------------ locate (A12)

_CENT = Decimal("0.01")
_NOISE = Decimal("0.000001")  # float representation noise only; never a tolerance


@dataclass
class LocateResult:
    """A12 misposting lookup: every CO line matching amount, cost center and period exactly."""

    amount: str
    cost_center: str
    period: str
    sap_label: str
    export: str
    matches: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def unique(self) -> bool:
        return len(self.matches) == 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["unique"] = self.unique
        return data


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace(",", "")
    if text.endswith("-"):
        text = "-" + text[:-1]
    try:
        return Decimal(text) if text else None
    except InvalidOperation:
        return None


def _same_amount(cell: Decimal, wanted: Decimal) -> bool:
    """Exact to the cent: equal after quantizing to cents, and within float noise of the requested value."""
    return cell.quantize(_CENT) == wanted.quantize(_CENT) and abs(cell - wanted) <= _NOISE


def _cc_key(value: Any) -> str | None:
    """Cost center compare key: stripped, case-folded; an all-digit value loses leading zeros (Excel strips
    them from numeric cost centers, SAP pads them)."""
    text = as_text(value)
    if text is None:
        return None
    text = text.casefold()
    return (text.lstrip("0") or "0") if text.isdigit() else text


def _period_matches(cell: Any, period: str, label: str) -> bool:
    text = as_text(cell)
    if text is None:
        return False
    if text in (period, label) or text == label.split(" : ")[0]:
        return True
    from cpa.periods import parse_sap_label

    try:
        return parse_sap_label(text) == period
    except ValueError:
        return False


def locate(amount: Decimal | str | float, cc: str, period: str, *, export: Path | None = None,
           root: Path | None = None) -> LocateResult:
    """Find the CO line item(s) for a misposting: exact amount, cost center and fiscal period (FYMM).

    export defaults to <workspace>/inbox/sap/co_lineitems_<period>.xlsx. The period matches a fiscal-period
    cell holding the FYMM, the SAP label (periods.sap_label) or its "NNN/YYYY" part; when the export has no
    period column, the file name's period token must equal `period`. Streams the export (any size); never
    writes anything."""
    from cpa.periods import AmbiguousFilename, fymm_from_filename, parse_fymm, sap_label

    try:
        parse_fymm(period)
    except ValueError as exc:
        raise SourceError(f"period {period!r} is not a FYMM such as 2703: {exc}") from exc
    wanted = _decimal(amount)
    if wanted is None:
        raise SourceError(f"amount {amount!r} is not a number")
    if export is None:
        from cpa.config import workspace

        export = Path(root or workspace()) / "inbox" / "sap" / f"co_lineitems_{period}.xlsx"
    export = Path(export)
    label = sap_label(period)
    result = LocateResult(amount=str(wanted), cost_center=cc, period=period, sap_label=label, export=str(export))
    adapter = SapCoLineItems()
    header, body = adapter.read(export)
    try:
        column_map, _ = adapter.match(header)
        for needed in ("cost_center", "amount"):
            if needed not in column_map:
                raise SchemaMismatch(f"{export.name}: no {needed} column; cannot locate a line item")
        idx = {name: header.index(col) for name, col in column_map.items()}
        if "fiscal_period" not in idx:
            try:
                file_period = fymm_from_filename(export.name)
            except AmbiguousFilename:
                file_period = None
                result.warnings.append("no fiscal period column and no period in the file name; period not checked")
            if file_period is not None and file_period != period:
                raise SchemaMismatch(f"{export.name} is period {file_period}, not {period}")
        for name in ("document_number", "line_item"):
            if name not in idx:
                result.warnings.append(f"export has no {name} column; matches cannot name the SAP {name}")
        want_cc = _cc_key(cc)
        for n, row in enumerate(body, start=2):
            cell = _decimal(row[idx["amount"]])
            if cell is None or not _same_amount(cell, wanted) or _cc_key(row[idx["cost_center"]]) != want_cc:
                continue
            if "fiscal_period" in idx and not _period_matches(row[idx["fiscal_period"]], period, label):
                continue
            result.matches.append({
                "row": n,
                "document_number": as_text(row[idx["document_number"]]) if "document_number" in idx else None,
                "line_item": as_text(row[idx["line_item"]]) if "line_item" in idx else None,
                "amount": str(cell),
                "cost_center": as_text(row[idx["cost_center"]]),
                "fiscal_period": as_text(row[idx["fiscal_period"]]) if "fiscal_period" in idx else None,
                "line_item_text": as_text(row[idx["line_item_text"]]) if "line_item_text" in idx else None,
            })
    finally:
        body.close()
    return result


# ------------------------------------------------------------------------------------------------ CLI


def _cmd_locate(args: argparse.Namespace) -> int:
    def action() -> int:
        res = locate(args.amount, args.cc, args.period, export=args.export)
        payload = res.to_dict()
        if args.out is not None:
            from cpa import fsutil

            text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            args.out.parent.mkdir(parents=True, exist_ok=True)
            fsutil.atomic_write(args.out, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            n = len(res.matches)
            verdict = "FOUND" if res.unique else ("NOT FOUND" if n == 0 else "AMBIGUOUS")
            print(f"{verdict}: {n} rows match amount {res.amount}, cost center {res.cost_center}, "
                  f"period {res.period} ({res.sap_label}) in {res.export}")
            for m in res.matches:
                print(f"  row {m['row']}: document {m['document_number']} line {m['line_item']} "
                      f"amount {m['amount']} cost center {m['cost_center']}")
        for w in res.warnings:
            print(f"cpa sources: warning: {w}", file=sys.stderr)
        return 0 if res.unique else 1

    return run_guarded(action)


def register_under(sub: argparse._SubParsersAction) -> None:
    """`sources sap validate` (salary, co_lineitems) and `sources sap locate` (A12). Import-cheap."""
    cmds = add_source_parser(sub, "sap", "SAP exports (A10-A12): validate salary and CO line item files, "
                                         "locate a misposting. Read and export only.")
    p = cmds.add_parser("locate", help="Find the CO line item for an amount, cost center and period (A12).",
                        description="Exit 0 when exactly one line matches, 1 when none or several do. "
                                    "Reads the landed CO line item export only; never writes to SAP.")
    p.add_argument("--amount", required=True, help="The exact amount, e.g. 1234.56.")
    p.add_argument("--cc", required=True, help="The cost center the amount was posted to.")
    p.add_argument("--period", required=True, help="Fiscal period as FYMM, e.g. 2703.")
    p.add_argument("--export", type=Path, default=None,
                   help="The CO line item export (default: inbox/sap/co_lineitems_<period>.xlsx).")
    p.add_argument("--out", type=Path, default=None, help="Also write the result as JSON to this file.")
    p.add_argument("--json", action="store_true", help="Print the result as JSON.")
    p.set_defaults(func=_cmd_locate)
