"""JE refund draft (B16, U21 "je" part): fill the JE template from a located SAP misposting; stop at ready-to-post.

FIXTURE — confirm against her file: reference/template_maps/je_refund.yaml's cells, and the debit/credit side of
each line, mirror no real JE template until her file arrives (NFH-P6-03-je-template). Hard rule 13 / R013 / R210:
this module never posts and exposes no `post`/`submit` leaf; the analyst's own click in SAP is the only control
on posting. `crf.py` (B15) is a different builder's file; nothing here imports it.

Source of the misposting is the JSON `python -m cpa sources sap locate --out` writes (U09,
`cpa.sources.sap.LocateResult.to_dict()`). R107/B16: the requested amount must equal the located amount exactly,
to the cent. B16: both cost centers must be present in the SAP cost structure reference -- by default the same
CO line item export the locate call itself read (A11 schema; public `cpa.sources.get("sap.co_lineitems")`
adapter, never ad hoc parsing or leaf-class imports, R143).
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from cpa import fsutil

__all__ = [
    "MAP_NAME", "OUTPUT_NAME", "READY_NOTE", "REFERENCE_FMT", "JE_ID_PATTERN", "RESERVED_NAMES",
    "JeError", "InvalidJeId", "AmountMismatch", "SourceMismatch", "LocateFailed", "InvalidCostCenter",
    "TemplateMapError", "AsOfUnknown", "WorkbookTooLarge",
    "JeResult",
    "to_cents", "check_amount", "check_cost_centers", "load_located", "load_map", "draft", "register",
]

MAP_NAME = "je_refund"
OUTPUT_NAME = "JE_{}.xlsx"
READY_NOTE = "READY TO POST - NOT POSTED. Review, then post it in SAP yourself (hard rule 13)."
# .format() target, never an f-string, so the literal is one Constant node (matches the rest of cpa/workflows).
REFERENCE_FMT = "SAP doc {} line {} ({})"
JE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
RESERVED_NAMES: frozenset[str] = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{n}" for n in range(1, 10)} | {f"LPT{n}" for n in range(1, 10)}
)
_CENT = Decimal("0.01")


class JeError(RuntimeError):
    """Base for every je_refund refusal; nothing is written to outbox/ when one is raised."""


class InvalidJeId(JeError):
    """je_id fails JE_ID_PATTERN, or je_id.upper() is a reserved Windows device name."""


class AmountMismatch(JeError):
    """The requested amount does not equal the located amount to the cent (R107 / B16)."""


class SourceMismatch(JeError):
    """The located record's cost center does not match --from-cc."""


class LocateFailed(JeError):
    """source.json does not carry exactly one located match."""


class InvalidCostCenter(JeError):
    """--from-cc or --to-cc is absent from the SAP cost structure reference (B16)."""


class TemplateMapError(JeError):
    """reference/template_maps/je_refund.yaml is missing a required key."""


class AsOfUnknown(JeError):
    """No --as-of was given and the cost-structure export carries no manifest sidecar (hard rule 7)."""


class WorkbookTooLarge(JeError):
    """The template is at or above the 15 MB streaming threshold (hard rule 11); this module edits in place
    with openpyxl and cannot stream a write."""


@dataclass(frozen=True)
class JeResult:
    """A ready-to-post JE draft. `posted` is always False -- this module has no way to set it True."""

    je_id: str
    workbook: Path
    requested: Decimal
    from_cc: str
    to_cc: str
    reference: str
    as_of: str
    posted: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "je_id": self.je_id, "workbook": str(self.workbook), "requested": str(self.requested),
            "from_cc": self.from_cc, "to_cc": self.to_cc, "reference": self.reference, "as_of": self.as_of,
            "posted": self.posted, "next_step": READY_NOTE,
        }


def to_cents(value: Any) -> Decimal:
    """Decimal(str(value)) quantized to cents, ROUND_HALF_EVEN. Never a float compare (D-U09-7 style)."""
    try:
        return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise AmountMismatch(f"{value!r} is not a decimal amount") from exc


def check_amount(requested: Any, located: Any) -> Decimal:
    """R107 / B16: the requested amount must equal the located amount exactly, to the cent."""
    req, loc = to_cents(requested), to_cents(located)
    if req != loc:
        raise AmountMismatch(f"requested amount {req} does not equal the located amount {loc}")
    return req


def _cc_key(value: Any) -> str:
    """Cost-center compare key: stripped, case-folded; an all-digit value loses leading zeros (mirrors
    cpa.sources.sap's own compare key, so a cost center matches the same way in locate and in this check)."""
    text = "" if value is None else str(value).strip()
    text = text.casefold()
    return (text.lstrip("0") or "0") if text.isdigit() else text


def check_cost_centers(from_cc: str, to_cc: str, cost_structure: Path) -> None:
    """B16: both from_cc and to_cc must be present in cost_structure's cost_center column.

    Reads cost_structure through the public cpa.sources registry (`sap.co_lineitems`), never ad hoc
    parsing or leaf-class imports (R143 / R012). Raises InvalidCostCenter naming every missing cost
    center and the file."""
    from cpa import sources

    frame = sources.get("sap.co_lineitems").load(Path(cost_structure))
    valid = {_cc_key(v) for v in frame["cost_center"].tolist()}
    missing = [cc for cc in (from_cc, to_cc) if _cc_key(cc) not in valid]
    if missing:
        raise InvalidCostCenter(
            f"cost center(s) {', '.join(missing)} not found in {Path(cost_structure)}"
        )


def _located_amount_ref(export: Path, row_number: int) -> str:
    """Build an A1 reference to the located SAP amount through the public source adapter (D21)."""
    from openpyxl.utils import get_column_letter

    from cpa import bigxlsx, sources

    adapter = sources.get("sap.co_lineitems")
    header, body = adapter.read(export)
    body.close()
    columns, _missing = adapter.match(header)
    if "amount" not in columns:
        raise LocateFailed(f"{export.name}: SAP source adapter found no amount column for the located row")
    amount_column = header.index(columns["amount"]) + 1
    sheet = bigxlsx.sheet_names(export)[0]
    quoted_sheet = "'" + sheet.replace("'", "''") + "'"
    return f"{quoted_sheet}!{get_column_letter(amount_column)}{row_number}"


def load_located(source: Path) -> dict[str, Any]:
    """Read a `sources sap locate --out` JSON; require exactly one match; return it merged with the
    top-level cost_center/export (attribute-style access only, never re-typed keys)."""
    source = Path(source)
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    matches = data.get("matches") or []
    if len(matches) != 1:
        raise LocateFailed(
            f"{source}: expected exactly one located match, found {len(matches)}"
        )
    m = dict(matches[0])
    if m.get("amount") is None:
        m["amount"] = data.get("amount")
    if m.get("cost_center") is None:
        m["cost_center"] = data.get("cost_center")
    m["export"] = data.get("export")
    return m


def load_map(name: str | None = None) -> dict[str, Any]:
    """The JE template's cell map (workspace copy first, cpa.config.template_map); TemplateMapError on a
    missing required key."""
    from cpa.config import template_map

    tmap = template_map(name or MAP_NAME)
    for key in ("sheet", "cells", "lines", "balance_cell"):
        if key not in tmap:
            raise TemplateMapError(f"reference/template_maps/{name or MAP_NAME}.yaml is missing {key!r}")
    for key in ("je_id", "fymm", "reason", "reference", "note"):
        if key not in tmap["cells"]:
            raise TemplateMapError(f"reference/template_maps/{name or MAP_NAME}.yaml cells is missing {key!r}")
    return tmap


def _check_je_id(je_id: str) -> None:
    if not JE_ID_PATTERN.match(je_id or ""):
        raise InvalidJeId(f"je_id {je_id!r} must match {JE_ID_PATTERN.pattern}")
    if je_id.upper() in RESERVED_NAMES:
        raise InvalidJeId(f"je_id {je_id!r} is a reserved Windows device name")


def _resolve_as_of(as_of: date | None, cost_structure: Path) -> str:
    if as_of is not None:
        return as_of.isoformat()
    from cpa import manifest

    if manifest.exists(cost_structure):
        recorded = manifest.read(cost_structure).get("as_of")
        if recorded:
            return str(recorded)
    raise AsOfUnknown(
        f"no --as-of was given and {cost_structure} has no manifest sidecar to read one from"
    )


def draft(
    source: Path,
    template: Path,
    *,
    je_id: str,
    from_cc: str,
    to_cc: str,
    requested_amount: Any,
    fymm: str,
    reason: str = "",
    cost_structure: Path | None = None,
    template_map: str | None = None,
    as_of: date | None = None,
    root: Path | None = None,
) -> JeResult:
    """B16: draft a ready-to-post JE refund. Never posts; writes only under outbox/je/<je_id>/."""
    from cpa import bigxlsx, manifest, verify

    _check_je_id(je_id)
    source, template = Path(source), Path(template)
    if bigxlsx.is_large(template):
        raise WorkbookTooLarge(f"{template} is at or above the 15 MB threshold; hand-edit it instead")
    located = load_located(source)
    if _cc_key(located.get("cost_center")) != _cc_key(from_cc):
        raise SourceMismatch(
            f"located cost center {located.get('cost_center')!r} does not match --from-cc {from_cc!r}"
        )
    requested = check_amount(requested_amount, located["amount"])
    cs = Path(cost_structure) if cost_structure is not None else Path(located["export"])
    check_cost_centers(from_cc, to_cc, cs)
    as_of_iso = _resolve_as_of(as_of, cs)
    tmap = load_map(template_map)

    import openpyxl

    ws_root = Path(root) if root is not None else None
    if ws_root is None:
        from cpa.config import workspace

        ws_root = workspace()
    out_dir = ws_root / "outbox" / "je" / je_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / OUTPUT_NAME.format(je_id)

    reference = REFERENCE_FMT.format(located.get("document_number"), located.get("line_item"), source.name)
    wb = openpyxl.load_workbook(str(template))
    sheet = wb[tmap["sheet"]]
    cells = tmap["cells"]
    sheet[cells["je_id"]] = je_id
    sheet[cells["fymm"]] = fymm
    sheet[cells["reason"]] = reason
    sheet[cells["reference"]] = reference
    sheet[cells["note"]] = READY_NOTE
    debit_cells, credit_cells = [], []
    for line in tmap["lines"]:
        cc = to_cc if line["side"] == "to" else from_cc
        sheet[line["cc_cell"]] = cc
        debit_cells.append(line["debit_cell"])
        credit_cells.append(line["credit_cell"])
        if line["side"] == "to":
            sheet[line["debit_cell"]], sheet[line["credit_cell"]] = float(requested), 0
        else:
            sheet[line["debit_cell"]], sheet[line["credit_cell"]] = 0, float(requested)
    sheet[tmap["balance_cell"]] = "=SUM({})-SUM({})".format(",".join(debit_cells), ",".join(credit_cells))
    fsutil.atomic_write(out, lambda tmp: wb.save(str(tmp)))

    check = openpyxl.load_workbook(str(out))[tmap["sheet"]]
    for line in tmap["lines"]:
        written = to_cents(check[line["debit_cell"]].value if line["side"] == "to" else check[line["credit_cell"]].value)
        if written != requested:
            out.unlink(missing_ok=True)
            raise AmountMismatch(
                f"{line['side']} line wrote {written}, not the requested {requested}; draft removed"
            )

    manifest.write(
        out, "SAP", "JE refund draft", f"je {je_id}", as_of_iso, row_count=1,
        inputs=[source, cs, template], status="actual", period=fymm, review="ready-to-post", posted=False,
        je_id=je_id, from_cc=from_cc, to_cc=to_cc,
    )
    source_export = Path(located["export"])
    amount_cell = next(line["debit_cell"] for line in tmap["lines"] if line["side"] == "to")
    output_cell = f"{tmap['sheet']}!{amount_cell}"
    manifest.add_figure(
        out, "je.refund_amount", float(requested), source_file=source_export,
        source_ref=_located_amount_ref(source_export, int(located["row"])),
        cell=output_cell, status="actual", period=fymm,
    )
    verify.build_verification_tab(out)

    return JeResult(je_id=je_id, workbook=out, requested=requested, from_cc=from_cc, to_cc=to_cc,
                    reference=reference, as_of=as_of_iso)


# ---------------------------------------------------------------- CLI


def _cmd_draft(args: argparse.Namespace) -> int:
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    try:
        result = draft(
            args.source, args.template, je_id=args.je_id, from_cc=args.from_cc, to_cc=args.to_cc,
            requested_amount=args.requested_amount, fymm=args.fymm, reason=args.reason or "",
            cost_structure=args.cost_structure, template_map=args.template_map, as_of=as_of, root=args.root,
        )
    except JeError as exc:
        print(f"stopped: {exc}")
        return 1
    if args.json:
        print(json.dumps(result.to_json(), ensure_ascii=False))
    else:
        print(f"wrote {result.workbook}")
        print(READY_NOTE)
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `je_refund draft` only. No `post`/`submit` leaf exists (hard rule 13)."""
    top = subparsers.add_parser("je_refund", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="je_refund_command", required=True)

    d = sub.add_parser(
        "draft",
        help="Fill a ready-to-post JE refund draft from a located SAP misposting. Never posts.",
        description="Amount must equal the located amount exactly, to the cent (R107). Both cost centers "
                    "must be present in the SAP cost structure reference (B16). Nothing is posted (hard rule 13).",
    )
    d.add_argument("--source", type=Path, required=True, help="sources sap locate --out JSON.")
    d.add_argument("--template", type=Path, required=True, help="The blank JE template to fill.")
    d.add_argument("--je-id", required=True, help="Short id; becomes outbox/je/<id>/.")
    d.add_argument("--from-cc", required=True, help="The misposted (current) cost center.")
    d.add_argument("--to-cc", required=True, help="The corrected cost center.")
    d.add_argument("--requested-amount", required=True, help="Must equal the located amount to the cent.")
    d.add_argument("--fymm", required=True, help="Fiscal period, yymm (cpa.periods.fymm format).")
    d.add_argument("--reason", default=None, help="Free-text reason written into the draft.")
    d.add_argument("--cost-structure", type=Path, default=None,
                   help="SAP cost structure export (default: the locate result's own CO export).")
    d.add_argument("--template-map", default=None, help="Template map name (default: je_refund).")
    d.add_argument("--as-of", default=None, help="ISO date; default: the cost structure's own manifest as_of.")
    d.add_argument("--root", type=Path, default=None, help="Workspace root (default: cpa.config.workspace()).")
    d.add_argument("--json", action="store_true", help="Print the result as one JSON object.")
    d.set_defaults(func=_cmd_draft)
