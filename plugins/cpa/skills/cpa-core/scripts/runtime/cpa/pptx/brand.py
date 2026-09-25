"""Analyst-authorized brand constants and generated-sheet formatting (C9).

The bundled branding skill supersedes historical visual assumptions, not financial assumptions
(hard rule 15). Production colors come from its published palette. Explicit path inspection of
legacy palettes remains available; importing this module performs no I/O. Never restyle analyst
or protected templates wholesale. Missing-activity flags remain visible (hard rule 8).
"""

from __future__ import annotations

import re
from pathlib import Path

from cpa import verify

__all__ = [
    "BRAND_KEYS", "ROLE", "HEX_RE", "BrandError", "InvalidColor",
    "color", "palette", "flag_text", "FONT", "COLORS", "CHART_COLORS",
    "APPROVED_FILLS", "style_generated_sheet", "style_generated_deck", "append_generated_row",
]

# R144/R187: JHM navy, gold, ice blue, dark green (CAG headers), yellow (flags) - the five brand.*
# keys (DECISIONS D04/D08), in the order the build list states them.
BRAND_KEYS: tuple[str, ...] = ("navy", "gold", "ice_blue", "dark_green", "flag_yellow")

# What each color is used for (FPA_Work_Inventory_CPA.md section M; R183/R216/R217). Reference only,
# for --help and docstrings; no code branches on it.
ROLE: dict[str, str] = {
    "navy": "slide header, footer divider, Division Surplus / Deficit row (R217)",
    "gold": "JHU Contribution Margin row (R216), gold divider line",
    "ice_blue": "cFTE mini-table",
    "dark_green": "CAG task headers",
    "flag_yellow": "flag box on a slide, flag cell in a workbook (R165)",
}

# Analyst brand source, with precedence recorded in branding/references/integration.md.
FONT = "Arial"  # approved portable fallback; no font installation or renderer assumptions
COLORS = {
    "navy": "#002D74", "gold": "#F3C300", "ice_blue": "#A3BBC3",
    "dark_green": "#638C1C", "flag_yellow": "#FFDD00",
}
CHART_COLORS = ("002D74", "F3C300", "007078", "638C1C", "00A0DF", "9D958C")
APPROVED_FILLS = frozenset({
    "002D74", "F3C300", "FFFFFF", "000000", "AB8900", "D15E14", "7F2629",
    "638C1C", "007078", "582C5F", "FFDD00", "F18A00", "E1251B", "D41367",
    "3DAE2B", "00ABC8", "00A0DF", "8A1A9B", "E19FC9", "B6B09C", "9D958C",
    "6E615D", "CFC393", "A3BBC3", "857550", "F2F2F2", "6B6B6B",
})


def style_generated_sheet(ws, *, header_rows=(1,), role="summary") -> None:
    """Style an explicitly generated sheet, never an existing analyst/template sheet.

    Preserve values, formulas, number formats, protection, dimensions, panes and semantic fills.
    Callers must not use this helper on an unprotected but analyst-owned template either.
    """
    from copy import copy
    from openpyxl.styles import PatternFill

    if ws.protection.sheet:
        raise BrandError(f"{ws.title}: protected template must not be restyled")
    tab_colors = {"summary": "002D74", "input": "F3C300", "reference": "9D958C",
                  "scenario": "007078"}
    if role not in tab_colors:
        raise BrandError(f"unknown worksheet role: {role}")
    ws.sheet_properties.tabColor = tab_colors[role]
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            font = copy(cell.font)
            font.name = FONT
            if cell.row in header_rows:
                font.bold, font.color, font.sz = True, "FFFFFF", 11
                cell.fill = PatternFill("solid", fgColor="002D74")
            elif cell.fill.fill_type is None and cell.row % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F2F2F2")
            cell.font = font


def append_generated_row(ws, values, *, row_number: int, header: bool = False) -> None:
    """Append a branded row to a new streaming worksheet without buffering the workbook."""
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill

    ws.sheet_properties.tabColor = "002D74"
    cells = []
    for value in values:
        cell = WriteOnlyCell(ws, value=value)
        cell.font = Font(name=FONT, size=11, bold=header, color="FFFFFF" if header else "000000")
        if header or row_number % 2 == 0:
            cell.fill = PatternFill("solid", fgColor="002D74" if header else "F2F2F2")
        cells.append(cell)
    ws.append(cells)


def style_generated_deck(prs) -> None:
    """Apply approved typography and widescreen geometry to newly generated decks only.

    Never use on a supplied deck/template: refresh must preserve its layout and report conflicts.
    This is a technical normalization, not a complete cover/logo/visual acceptance check.
    """
    from pptx.util import Inches

    width, height = Inches(13.333333), Inches(7.5)
    sx, sy = width / prs.slide_width, height / prs.slide_height
    for slide in prs.slides:
        for shape in slide.shapes:
            shape.left, shape.top = int(shape.left * sx), int(shape.top * sy)
            shape.width, shape.height = int(shape.width * sx), int(shape.height * sy)
            frames = []
            if shape.has_text_frame:
                frames.append(shape.text_frame)
            if shape.has_table:
                frames.extend(cell.text_frame for row in shape.table.rows for cell in row.cells)
            for frame in frames:
                for paragraph in frame.paragraphs:
                    paragraph.font.name = FONT
                    for run in paragraph.runs:
                        run.font.name = FONT
    prs.slide_width, prs.slide_height = width, height


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class BrandError(ValueError):
    """Base for brand palette failures."""


class InvalidColor(BrandError):
    """A brand.* value is not a 6-digit hex color. Names the key and the offending value."""


def _normalize(key: str, value: object) -> str:
    text = str(value).strip()
    if not text.startswith("#"):
        text = f"#{text}"
    text = text.upper()
    if not HEX_RE.match(text):
        raise InvalidColor(f"brand.{key} = {value!r} is not a 6-digit hex color like '#1F4E79'")
    return text


def color(key: str, *, path: Path | str | None = None) -> str:
    """Return an approved production color, or inspect an explicitly supplied legacy palette."""
    if key not in BRAND_KEYS:
        raise BrandError(f"{key!r} is not a brand color; expected one of {BRAND_KEYS}")
    from cpa import config

    # An explicit path remains a legacy palette inspection API, never the production default.
    if path is not None:
        return _normalize(key, config.assumption("brand", key, path=path))
    return COLORS[key]


def palette(*, path: Path | str | None = None) -> dict[str, str]:
    """Every brand.* color as {key: '#RRGGBB'}, in BRAND_KEYS order; raises on the first null one."""
    return {key: color(key, path=path) for key in BRAND_KEYS}


def flag_text(metric: str, why: str = "", source: str = "") -> str:
    """The CPA flag convention text (R165): states the metric, why it matters to the narrative, and
    the source that would supply it - the same wording cpa.activity_block writes into a workbook cell
    (DECISIONS D24), reused here so a slide's flag box and a workbook's flag cell read identically.
    Never invents `why`/`source` when the caller does not supply them (hard rule 15's spirit)."""
    text = f"{verify.M2_MISSING_MARKER}: {metric} not supplied"
    if why:
        text += f"; needed for {why}"
    if source:
        text += f"; source {source}"
    return text
