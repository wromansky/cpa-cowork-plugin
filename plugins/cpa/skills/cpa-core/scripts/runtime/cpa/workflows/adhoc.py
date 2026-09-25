"""Ad hoc module library (D2 dept/division P&L, D3 comp/benchmark, D4 cost allocation with live
weight cells, D5 data-pull summary, D8 slide builder) -- `python -m cpa adhoc <leaf>`.

FIXTURE -- confirm against her file: each builder reads its own small JSON contract
(`pnl_inputs.json`, `comp_inputs.json`, `allocation_inputs.json`, `pull_inputs.json`) placed beside
`brief.md` by whatever calls this module (a future skill, or a test). Every one of those JSON
contracts carries its own `period`, `status`, `source`, `as_of` (hard rule 7). Callers may replace
these JSON readers with adapters while preserving the `build_*` public signatures (brief,
inputs_path).

Build-list items: D2:307-314, D3:315-322, D4:323-330, D5:331-336, D8:350-354. Hard rules enforced:
1 (TCC = base + supplements, never fringe -- delegated to cpa.benchmarks.tcc), 2/3 (SullivanCotter
2025 AMC only, specific interpolated percentiles -- delegated to cpa.benchmarks), 6
(gross vs net collections always labelled, R006/R181), 7 (every figure carries period, status,
source, as-of), "unmatched department labels fail loudly" (crosswalk.normalize, R010/R138),
R079/R155/R159 (every net collection figure states its definition; a weight cell change
recalculates every department because every department's formula divides by one shared
`SUM()` over the weight range).

Computed figures use D35 controls supplied explicitly by the input owner, never generated from the
builder's results. Optional input schema: `provenance_controls` is a direct map from semantic
figure ID to the D35 record itself. For example, the value at key `pnl.Dermatology.margin` is
`{"op":"difference","args":["calc:/provenance_controls/revenue_total","calc:/provenance_controls/cost_total"]}`;
`revenue_total`, `cost_total`, and `tax` are likewise records under `provenance_controls`, with
args resolving only to D35 `json:`/`calc:` refs. Figure IDs containing `/` or `~` are encoded as
one RFC6901 pointer token by replacing them with `~1` or `~0`; the mapping keys remain the literal
semantic IDs. Missing controls get a deterministic absent calc pointer and therefore remain
unverified. For formulae involving tax or transfer rates
sourced from assumptions rather than JSON, D35 has no JSON operand for that constant: an input
control cannot honestly establish that formula until the source/control design is extended. Do not
invent or copy such constants into the JSON. This is the smoke owner's contract; formula controls
must include every adjustment in the live workbook formula.

Request intake, tracking and recall (D1/D6/D7) are provided by the intake and tracker modules,
not this module.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "BRIEF_FIELDS", "OUTPUT_NAMES", "COLLECTION_BASES",
    "AdhocError", "BriefError", "InputSpecError", "ArtifactExists",
    "Brief", "parse_brief",
    "build_pnl", "build_comp", "build_allocation", "build_summary", "build_slides",
    "register",
]

BRIEF_FIELDS: tuple[str, ...] = (
    "requester", "department", "division", "period", "scope", "due_date", "requested_output",
)
OUTPUT_NAMES: dict[str, str] = {
    "pnl": "PnL.xlsx", "comp": "Comp.xlsx", "allocation": "Allocation.xlsx",
    "summary": "summary.xlsx", "slides": "slides.pptx",
}
COLLECTION_BASES: tuple[str, ...] = ("gross", "net")  # R006/R181: gross vs net always labelled


class AdhocError(RuntimeError):
    """Base for every adhoc failure. Nothing new is left under requests/<id>/ when raised before save."""


class BriefError(AdhocError):
    """brief.md is absent, unparsable, or missing a required field. Names the field."""


class InputSpecError(AdhocError):
    """The kind's *_inputs.json is missing, malformed, or missing a required key. Names the key."""


class ArtifactExists(AdhocError):
    """The output path already exists and overwrite=False; her edits are never clobbered."""


# ---------------------------------------------------------------- brief


@dataclass(frozen=True)
class Brief:
    """One ad hoc request read from requests/<id>/brief.md."""

    id: str
    dir: Path
    requester: str
    department: str
    division: str
    period: str
    scope: str
    due_date: str
    requested_output: str


def parse_brief(path: Path | str) -> Brief:
    """Read `key: value` lines (one per line, case-insensitive key, utf-8-sig) from brief.md.

    Every BRIEF_FIELDS name must appear with a non-empty value or BriefError names it. `id` is the
    parent directory name (requests/<id>/brief.md)."""
    p = Path(path)
    if not p.is_file():
        raise BriefError(f"brief not found: {p}")
    fields: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace(" ", "_")
        fields[key] = value.strip()
    missing = [f for f in BRIEF_FIELDS if not fields.get(f)]
    if missing:
        raise BriefError(f"{p}: missing required field(s) {missing}")
    return Brief(id=p.parent.name, dir=p.parent, **{f: fields[f] for f in BRIEF_FIELDS})


# ---------------------------------------------------------------- shared helpers


def _load_json(path: Path | str, kind: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise InputSpecError(f"{kind}_inputs.json not found: {p}")
    import json

    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise InputSpecError(f"{p} is not valid JSON: {exc}") from exc


def _require(data: dict, key: str, where: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise InputSpecError(f"{where}: missing required key {key!r}")
    return data[key]


def _output_path(brief: Brief, root: Path | None, kind: str, *, overwrite: bool) -> Path:
    from cpa import config

    ws = Path(root) if root is not None else config.workspace()
    out = ws / "requests" / brief.id / OUTPUT_NAMES[kind]
    if out.is_file() and not overwrite:
        raise ArtifactExists(f"{out} already exists; pass overwrite=True / --overwrite to replace it")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _canonical_department(label: str) -> str:
    """crosswalk.normalize on a single label; UnmatchedDepartment propagates (fails loudly)."""
    import pandas as pd

    from cpa import crosswalk

    return crosswalk.normalize(pd.Series([label]))[0]


def _save_workbook(wb, path: Path) -> Path:
    from cpa import fsutil
    from cpa.pptx import brand

    if path.suffix.lower() == ".xlsx":
        for sheet in wb.worksheets:
            brand.style_generated_sheet(sheet)
    else:
        brand.style_generated_deck(wb)
    fsutil.atomic_write(path, lambda tmp: wb.save(str(tmp)))
    return path


def _write_manifest(path: Path, *, source: str, report: str, filters: str, as_of: str, status: str,
                     period: str) -> None:
    from cpa import manifest

    manifest.write(path, source=source, report=report, filters=filters, as_of=as_of, status=status, period=period)


def _record_figure(path: Path, figure_id: str, value: Any, *, source_file: Path, source_ref: str,
                    status: str, period: str, cell: str | None = None) -> None:
    """Record a numeric figure tied to its original JSON source or explicit calc control."""
    from cpa import manifest

    manifest.add_figure(path, figure_id, value, source_file, source_ref, cell=cell, status=status, period=period)


def _pointer_part(value: str) -> str:
    """Escape one JSON Pointer token according to RFC 6901."""
    return value.replace("~", "~0").replace("/", "~1")


def _control_ref(figure_id: str) -> str:
    """Select the direct D35 record keyed by semantic ID, or an absent pointer if missing."""
    return "calc:/provenance_controls/" + _pointer_part(figure_id)


def _input_ref(*parts: str) -> str:
    """Build an escaped direct JSON scalar reference."""
    return "json:/" + "/".join(_pointer_part(part) for part in parts)


# ---------------------------------------------------------------- D2 P&L


def build_pnl(brief: Brief, inputs_path: Path | str, *, root: Path | None = None,
              overwrite: bool = False) -> Path:
    """D2: one department's P&L from pnl_inputs.json. Revenue/compensation/expense subtotals and Tax
    are `=SUM(...)`/`=<subtotal>*<pct>` formulas; Margin is a formula over the four subtotal cells
    (never a value), so it always reflects the line items above it. Department is normalized through
    `crosswalk.normalize` first (fails loudly on an unmatched label). The M2 block (wRVUs, cFTE,
    Collections gross/net, Charges) is written via `cpa.activity_block.build`; the Verification tab
    via `cpa.verify.build_verification_tab`."""
    import openpyxl

    from cpa import activity_block, verify

    data = _load_json(inputs_path, "pnl")
    period = _require(data, "period", "pnl_inputs.json")
    status = _require(data, "status", "pnl_inputs.json")
    source = _require(data, "source", "pnl_inputs.json")
    as_of = _require(data, "as_of", "pnl_inputs.json")
    departments = _require(data, "departments", "pnl_inputs.json")

    canonical = _canonical_department(brief.department)
    dept_data = None
    raw_department = None
    for raw_label, d in departments.items():
        if raw_label == brief.department or _canonical_department(raw_label) == canonical:
            dept_data = d
            raw_department = raw_label
            break
    if dept_data is None:
        raise InputSpecError(f"pnl_inputs.json has no department matching brief department {brief.department!r}")

    out = _output_path(brief, root, "pnl", overwrite=overwrite)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "P&L"
    ws.cell(row=1, column=1, value=canonical)
    ws.cell(row=1, column=2, value=period)

    row = 3
    source_figures: list[tuple[str, float, str, str]] = []
    subtotal_cells: dict[str, str] = {}
    for section in ("revenue", "compensation", "expense"):
        items = dept_data.get(section, {})
        ws.cell(row=row, column=1, value=section.capitalize())
        row += 1
        start_row = row
        for label, amount in items.items():
            ws.cell(row=row, column=1, value=f"  {label}")
            ws.cell(row=row, column=2, value=float(amount))
            source_figures.append((f"pnl.{canonical}.{section}.{label}", float(amount),
                                   _input_ref("departments", raw_department, section, label), f"P&L!B{row}"))
            row += 1
        subtotal_row = row
        ws.cell(row=subtotal_row, column=1, value=f"{section.capitalize()} subtotal")
        if row > start_row:
            ws.cell(row=subtotal_row, column=2, value=f"=SUM(B{start_row}:B{row - 1})")
        else:
            ws.cell(row=subtotal_row, column=2, value=0)
        subtotal_cells[section] = f"B{subtotal_row}"
        row += 2

    tax_pct = dept_data.get("tax_pct")
    if tax_pct is None:
        from cpa import config

        tax_pct = config.assumption("rates", "deans_tax_pct")
    tax_row = row
    ws.cell(row=tax_row, column=1, value="Tax")
    ws.cell(row=tax_row, column=2, value=f"={subtotal_cells['revenue']}*{float(tax_pct)}")
    row += 2

    margin_row = row
    ws.cell(row=margin_row, column=1, value="Margin")
    ws.cell(row=margin_row, column=2,
            value=f"={subtotal_cells['revenue']}-{subtotal_cells['compensation']}-{subtotal_cells['expense']}-B{tax_row}")
    margin_cell = f"B{margin_row}"

    _save_workbook(wb, out)

    _write_manifest(out, source=source, report="adhoc/pnl", filters=f"department={canonical}", as_of=as_of,
                     status=status, period=period)
    for figure_id, value, ref, cell in source_figures:
        _record_figure(out, figure_id, value, source_file=Path(inputs_path), source_ref=ref,
                       status=status, period=period, cell=cell)
    margin_id = f"pnl.{canonical}.margin"
    _record_figure(out, margin_id, None, source_file=Path(inputs_path),
                    source_ref=_control_ref(margin_id), cell=f"P&L!{margin_cell}",
                    status=status, period=period)

    activity = data.get("activity", {}).get(brief.department) or data.get("activity", {}).get(canonical) or {}
    metrics: dict[str, Any] = dict(activity)
    if metrics:
        narrative_relevant = {activity_block.canonical_metric(k) for k in metrics}
        activity_block.build(out, "P&L", metrics, narrative_relevant=narrative_relevant)

    verify.build_verification_tab(out)
    return out


# ---------------------------------------------------------------- D3 comp/benchmark


def build_comp(brief: Brief, inputs_path: Path | str, *, root: Path | None = None,
               overwrite: bool = False) -> Path:
    """D3: TCC (base + supplements, never fringe) and a percentile statement per provider.
    `cpa.benchmarks.statement_for_specialty` guarantees the statement is a specific number unless the
    value is above every reported point (never a range); specialty and survey column are written on
    every row (R154)."""
    import openpyxl

    from cpa import benchmarks

    data = _load_json(inputs_path, "comp")
    specialty = _require(data, "specialty", "comp_inputs.json")
    metric = _require(data, "metric", "comp_inputs.json")
    survey_column = _require(data, "survey_column", "comp_inputs.json")
    points = _require(data, "points", "comp_inputs.json")
    providers = _require(data, "providers", "comp_inputs.json")

    out = _output_path(brief, root, "comp", overwrite=overwrite)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Comp"
    headers = ["Name", "TCC", "Percentile statement", "Specialty", "Survey column"]
    for i, h in enumerate(headers, start=1):
        ws.cell(row=1, column=i, value=h)

    for r, provider in enumerate(providers, start=2):
        name = _require(provider, "name", "comp_inputs.json provider")
        base = float(_require(provider, "base", f"comp_inputs.json provider {name!r}"))
        supplements = provider.get("supplements", {})
        tcc_value = benchmarks.tcc(base, supplements)
        result = benchmarks.statement_for_specialty(tcc_value, points, specialty, metric)
        ws.cell(row=r, column=1, value=name)
        ws.cell(row=r, column=2, value=tcc_value)
        ws.cell(row=r, column=3, value=result.statement)
        ws.cell(row=r, column=4, value=result.specialty)
        ws.cell(row=r, column=5, value=survey_column)

    _save_workbook(wb, out)
    as_of = _require(data, "as_of", "comp_inputs.json")
    _write_manifest(out, source="SullivanCotter 2025 AMC (fixture)", report="adhoc/comp",
                     filters=f"specialty={specialty}", as_of=as_of, status="actual", period=brief.period)
    for r, provider in enumerate(providers, start=2):
        name = str(provider["name"])
        figure_id = f"comp.{name}.tcc"
        _record_figure(out, figure_id, float(ws.cell(r, 2).value), source_file=Path(inputs_path),
                       source_ref=_control_ref(figure_id), status="actual", period=brief.period,
                       cell=f"Comp!B{r}")
    return out


# ---------------------------------------------------------------- D4 allocation


def build_allocation(brief: Brief, inputs_path: Path | str, *, root: Path | None = None,
                      overwrite: bool = False) -> Path:
    """D4: one or more weighted variants across net (or gross) collections, each stating its own
    definition, with live weight input cells so a change to any one weight recalculates every
    department. Every department's Allocation formula is `weight_cell / SUM(<every weight cell in
    the variant>) * pool_cell`, so the shared SUM() denominator ties every department's result to
    every weight cell (R155). A `net` basis variant with no definition raises InputSpecError (R079)."""
    import openpyxl

    data = _load_json(inputs_path, "allocation")
    period = _require(data, "period", "allocation_inputs.json")
    status = _require(data, "status", "allocation_inputs.json")
    source = _require(data, "source", "allocation_inputs.json")
    as_of = _require(data, "as_of", "allocation_inputs.json")
    departments_raw = _require(data, "departments", "allocation_inputs.json")
    variants = _require(data, "variants", "allocation_inputs.json")
    departments = [_canonical_department(d) for d in departments_raw]

    out = _output_path(brief, root, "allocation", overwrite=overwrite)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Allocation"

    row = 1
    figures: list[tuple[str, Any, str, str]] = []
    for variant_index, variant in enumerate(variants):
        name = _require(variant, "name", "allocation_inputs.json variant")
        basis = variant.get("basis", "net")
        if basis not in COLLECTION_BASES:
            raise InputSpecError(f"variant {name!r}: basis must be one of {COLLECTION_BASES}, got {basis!r}")
        definition = variant.get("definition") or ""
        if basis == "net" and not definition:
            raise InputSpecError(f"variant {name!r}: basis 'net' requires a non-empty 'definition' (R079)")
        pool = float(_require(variant, "pool", f"allocation_inputs.json variant {name!r}"))
        weights = _require(variant, "weights", f"allocation_inputs.json variant {name!r}")
        tech_transfer_pct = variant.get("tech_transfer_pct")
        drug_revenue_excluded = variant.get("drug_revenue_excluded", {})

        header_label = f"{basis.capitalize()} collections ({definition})" if definition else f"{basis.capitalize()} collections"
        ws.cell(row=row, column=1, value=f"Variant: {name}")
        row += 1
        ws.cell(row=row, column=1, value=header_label)
        row += 1
        ws.cell(row=row, column=1, value="Pool")
        pool_cell_row = row
        ws.cell(row=row, column=2, value=pool)
        pool_cell = f"B{pool_cell_row}"
        figures.append((f"allocation.{name}.pool", pool, _input_ref("variants", str(variant_index), "pool"),
                        f"Allocation!{pool_cell}"))
        row += 1

        weight_header_row = row
        ws.cell(row=row, column=1, value="Department")
        ws.cell(row=row, column=2, value="Weight")
        ws.cell(row=row, column=3, value="Allocation")
        row += 1
        weight_start_row = row
        weight_rows: dict[str, int] = {}
        for dept in departments:
            if dept in weights:
                raw_weight_key = dept
                raw_weight = weights[dept]
            else:
                raw_weight_key = None
                raw_weight = None
                for raw_label, w in weights.items():
                    if _canonical_department(raw_label) == dept:
                        raw_weight_key = raw_label
                        raw_weight = w
                        break
            if raw_weight is None:
                raise InputSpecError(f"variant {name!r}: no weight given for department {dept!r}")
            ws.cell(row=row, column=1, value=dept)
            ws.cell(row=row, column=2, value=float(raw_weight))
            figures.append((f"allocation.{name}.{dept}.weight", float(raw_weight),
                            _input_ref("variants", str(variant_index), "weights", raw_weight_key),
                            f"Allocation!B{row}"))
            weight_rows[dept] = row
            row += 1
        weight_end_row = row - 1
        weight_sum = f"SUM(B{weight_start_row}:B{weight_end_row})"

        for dept in departments:
            wrow = weight_rows[dept]
            allocation_formula = f"=B{wrow}/{weight_sum}*{pool_cell}"
            if tech_transfer_pct is not None:
                allocation_formula += f"*(1-{float(tech_transfer_pct)})"
            excluded = drug_revenue_excluded.get(dept) if isinstance(drug_revenue_excluded, dict) else None
            if excluded is not None:
                allocation_formula += f"-{float(excluded)}"
            ws.cell(row=wrow, column=3, value=allocation_formula)
            figure_id = f"allocation.{name}.{dept}.allocation"
            figures.append((figure_id, None, _control_ref(figure_id), f"Allocation!C{wrow}"))
        row += 2

    _save_workbook(wb, out)
    _write_manifest(out, source=source, report="adhoc/allocation", filters=f"departments={departments}",
                     as_of=as_of, status=status, period=period)
    for figure_id, value, ref, cell in figures:
        _record_figure(out, figure_id, value, source_file=Path(inputs_path), source_ref=ref,
                       status=status, period=period, cell=cell)
    return out


# ---------------------------------------------------------------- D5 pull summary


def build_summary(brief: Brief, inputs_path: Path | str, *, root: Path | None = None,
                   overwrite: bool = False) -> Path:
    """D5: a flat `Data` tab plus a one-page `Summary` (Question/Answer, a group-by measure table,
    and a Sources block listing every input's system/report/filters/as_of)."""
    import openpyxl

    from cpa import crosswalk

    data = _load_json(inputs_path, "pull")
    question = _require(data, "question", "pull_inputs.json")
    answer = data.get("answer")
    sources = data.get("sources", [])
    rows = _require(data, "rows", "pull_inputs.json")
    group_by = data.get("group_by")
    measures = data.get("measures", [])

    if rows and "department" in rows[0]:
        for r in rows:
            r["department"] = _canonical_department(r["department"])

    out = _output_path(brief, root, "summary", overwrite=overwrite)

    wb = openpyxl.Workbook()
    data_ws = wb.active
    data_ws.title = "Data"
    columns = list(rows[0].keys()) if rows else []
    for i, col in enumerate(columns, start=1):
        data_ws.cell(row=1, column=i, value=col)
    summary_figures: list[tuple[str, Any, str, str]] = []
    for r, row_dict in enumerate(rows, start=2):
        for i, col in enumerate(columns, start=1):
            value = row_dict.get(col)
            data_ws.cell(row=r, column=i, value=value)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                summary_figures.append((f"summary.row{r - 1}.{col}", value,
                                        _input_ref("rows", str(r - 2), col), f"Data!{data_ws.cell(r, i).coordinate}"))
    n_rows = len(rows)

    summary_ws = wb.create_sheet("Summary")
    summary_ws.cell(row=1, column=1, value="Question")
    summary_ws.cell(row=1, column=2, value=question)
    summary_ws.cell(row=2, column=1, value="Answer")
    summary_ws.cell(row=2, column=2, value=answer if answer else "MISSING: answer not yet written")

    r = 4
    if group_by and measures and columns:
        gb_col = columns.index(group_by) + 1
        summary_ws.cell(row=r, column=1, value=group_by)
        for j, measure in enumerate(measures, start=2):
            summary_ws.cell(row=r, column=j, value=measure)
        r += 1
        seen: list[str] = []
        for row_dict in rows:
            key = row_dict.get(group_by)
            if key in seen:
                continue
            seen.append(key)
        gb_letter = data_ws.cell(row=1, column=gb_col).coordinate[0]
        for key in seen:
            summary_ws.cell(row=r, column=1, value=key)
            for j, measure in enumerate(measures, start=2):
                m_col = columns.index(measure) + 1
                m_letter = data_ws.cell(row=1, column=m_col).coordinate[0]
                formula = f"=SUMIF(Data!{gb_letter}2:{gb_letter}{1 + n_rows},A{r},Data!{m_letter}2:{m_letter}{1 + n_rows})"
                summary_ws.cell(row=r, column=j, value=formula)
                figure_id = f"summary.group.{key}.{measure}"
                summary_figures.append((figure_id, None, _control_ref(figure_id),
                                        f"Summary!{summary_ws.cell(r, j).coordinate}"))
            r += 1
        r += 1

    summary_ws.cell(row=r, column=1, value="Sources")
    r += 1
    for src in sources:
        summary_ws.cell(row=r, column=1, value=src.get("system", "SOURCE UNKNOWN"))
        summary_ws.cell(row=r, column=2, value=src.get("report", ""))
        summary_ws.cell(row=r, column=3, value=src.get("filters", ""))
        summary_ws.cell(row=r, column=4, value=src.get("as_of", ""))
        r += 1

    _save_workbook(wb, out)
    as_of = sources[0]["as_of"] if sources else brief.period
    src_name = sources[0]["system"] if sources else "SOURCE UNKNOWN"
    _write_manifest(out, source=src_name, report="adhoc/summary", filters=f"group_by={group_by}", as_of=as_of,
                     status="actual", period=brief.period)
    for figure_id, value, ref, cell in summary_figures:
        _record_figure(out, figure_id, value, source_file=Path(inputs_path), source_ref=ref,
                       status="actual", period=brief.period, cell=cell)
    return out


# ---------------------------------------------------------------- D8 slide builder


def build_slides(brief: Brief, source_path: Path | str, *, audience: str = "internal",
                  root: Path | None = None, overwrite: bool = False) -> Path:
    """D8: turn a D2-D5 output into slides. Reads the source artifact's own sidecar manifest for
    figures (never re-derives them); every slide gets speaker notes (`cpa.pptx.notes.write_notes`,
    required by lint's NOTES_MISSING check); `cpa.pptx.lint.lint_deck` runs before returning and a
    non-empty result raises AdhocError, so a deck that would fail format lint is never left on disk
    (acceptance: "format lint passes")."""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    from cpa import manifest
    from cpa.pptx import brand, lint
    from cpa.pptx import notes as notes_mod

    src = Path(source_path)
    if not src.is_file():
        raise AdhocError(f"source artifact not found: {src}")
    try:
        record = manifest.read(src)
    except manifest.MissingManifest as exc:
        raise AdhocError(str(exc)) from exc

    out = _output_path(brief, root, "slides", overwrite=overwrite)

    navy = brand.color("navy")
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    layout = prs.slide_layouts[6]

    slide = prs.slides.add_slide(layout)
    box = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(12), Inches(1))
    tf = box.text_frame
    tf.text = f"{brief.requested_output} -- {brief.department}"
    tf.paragraphs[0].runs[0].font.size = Pt(28)
    tf.paragraphs[0].runs[0].font.bold = True

    figures = record.get("figures", {})
    slide2 = prs.slides.add_slide(layout)
    header = slide2.shapes.add_shape(1, Inches(0), Inches(0), Inches(13.333), Inches(0.7))
    header.fill.solid()
    from pptx.dml.color import RGBColor

    header.fill.fore_color.rgb = RGBColor.from_string(navy.lstrip("#"))
    header.line.fill.background()
    box2 = slide2.shapes.add_textbox(Inches(0.5), Inches(1), Inches(12), Inches(5.5))
    tf2 = box2.text_frame
    tf2.word_wrap = True
    lines = [f"Period: {brief.period}", f"Scope: {brief.scope}"]
    for fid, rec in figures.items():
        lines.append(f"{fid}: {rec.get('value')}")
    if not lines:
        lines = ["No figures recorded on the source artifact."]
    for i, line in enumerate(lines):
        p = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
        p.text = line
        p.font.size = Pt(20)

    _save_workbook(prs, out)

    slide_contents = [
        notes_mod.Slide(title=f"{brief.requested_output} for {brief.department}",
                        points=[f"Requested by {brief.requester}", brief.scope]),
        notes_mod.Slide(title="Figures", points=[f"{fid}: {rec.get('value')}" for fid, rec in figures.items()]),
    ]
    notes_mod.write_notes(out, slide_contents, audience)

    issues = lint.lint_deck(out, audience=audience)
    if issues:
        raise AdhocError(f"{out}: format lint failed: {[i.to_json() for i in issues]}")
    return out


# ---------------------------------------------------------------- CLI


def _cmd_pnl(a: argparse.Namespace) -> int:
    brief = parse_brief(a.brief)
    out = build_pnl(brief, a.inputs, root=a.root, overwrite=a.overwrite)
    print(out)
    return 0


def _cmd_comp(a: argparse.Namespace) -> int:
    brief = parse_brief(a.brief)
    out = build_comp(brief, a.inputs, root=a.root, overwrite=a.overwrite)
    print(out)
    return 0


def _cmd_allocation(a: argparse.Namespace) -> int:
    brief = parse_brief(a.brief)
    out = build_allocation(brief, a.inputs, root=a.root, overwrite=a.overwrite)
    print(out)
    return 0


def _cmd_summary(a: argparse.Namespace) -> int:
    brief = parse_brief(a.brief)
    out = build_summary(brief, a.inputs, root=a.root, overwrite=a.overwrite)
    print(out)
    return 0


def _cmd_slides(a: argparse.Namespace) -> int:
    brief = parse_brief(a.brief)
    out = build_slides(brief, a.source, audience=a.audience, root=a.root, overwrite=a.overwrite)
    print(out)
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `adhoc pnl|comp|allocation|summary|slides`. Import-cheap (D03)."""
    top = subparsers.add_parser("adhoc", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    def add_leaf(name: str, help_text: str, func) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--brief", required=True, type=Path, help="Path to requests/<id>/brief.md")
        p.add_argument("--root", type=Path, default=None, help="Workspace root (default: config.workspace())")
        p.add_argument("--overwrite", action="store_true", help="Replace the output if it already exists")
        p.set_defaults(func=func)
        return p

    p = add_leaf("pnl", "D2: build a department P&L workbook from a classified brief.", _cmd_pnl)
    p.add_argument("--inputs", required=True, type=Path, help="Path to pnl_inputs.json")

    p = add_leaf("comp", "D3: build a compensation and benchmark comparison workbook.", _cmd_comp)
    p.add_argument("--inputs", required=True, type=Path, help="Path to comp_inputs.json")

    p = add_leaf("allocation", "D4: build a cost allocation and funds flow workbook with live weight cells.",
                 _cmd_allocation)
    p.add_argument("--inputs", required=True, type=Path, help="Path to allocation_inputs.json")

    p = add_leaf("summary", "D5: build a data pull flat table plus one-page summary.", _cmd_summary)
    p.add_argument("--inputs", required=True, type=Path, help="Path to pull_inputs.json")

    p = add_leaf("slides", "D8: turn a D2-D5 output into a lint-clean slide deck.", _cmd_slides)
    p.add_argument("--source", required=True, type=Path, help="Path to the D2-D5 artifact to build slides from")
    p.add_argument("--audience", default="internal", choices=("internal", "committee", "dean", "board"))
