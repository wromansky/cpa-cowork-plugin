"""Deck and workbook change report (C11): slide-by-slide and cell-by-cell, numeric changes separated
from format drift - `python -m cpa pptx diff --a --b`.

Build-list items: C11 deck and workbook diff (guide 5 cpa-format, guide 9 pptx/diff.py, build-list
guide-13.21 "change log lists the seeded change"). R149: separates numeric changes from format
drift. A `Change.kind` is "numeric" when both the before and after values parse as a number, "text"
when a non-numeric value changed, or "format" when formatting changed. Content changes do not
hide independent format changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "Change", "DiffError", "UnsupportedFile", "MismatchedFiles",
    "diff_decks", "diff_workbooks", "diff_files", "register_under",
]


class DiffError(ValueError):
    """Base for diff failures: a bad argument or an unreadable/mismatched file pair."""


class UnsupportedFile(DiffError):
    """The path is not a .pptx or .xlsx this module reads."""


class MismatchedFiles(DiffError):
    """`a` and `b` are not the same kind of file (one .pptx, the other .xlsx or something else)."""


@dataclass
class Change:
    """One content or formatting change, not a full acceptance verdict."""

    kind: str  # "numeric" | "text" | "format"
    location: str  # "slide 3 shape 0" or "Sheet1!B4"
    field: str  # "text" | "value" | "font" | "fill" | "slide_count" | ...
    before: Any
    after: Any

    def to_json(self) -> dict:
        """Serialize a change for the existing diff CLI."""
        return {"kind": self.kind, "location": self.location, "field": self.field,
                 "before": self.before, "after": self.after}


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.strip().replace(",", ""))
            return True
        except ValueError:
            return False
    return False


def _value_kind(before: Any, after: Any) -> str:
    return "numeric" if _is_number(before) and _is_number(after) else "text"


def _check_pair(a: Path, b: Path, suffix: str, reader_name: str) -> None:
    for p in (a, b):
        if p.suffix.lower() != suffix:
            raise UnsupportedFile(f"{p.name}: {reader_name} reads {suffix} only")
        if not p.is_file():
            raise FileNotFoundError(f"file not found: {p}")


# ---------------------------------------------------------------- decks


def _first_run_size(shape) -> float | None:
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            if run.font.size is not None:
                return run.font.size.pt
    return None


def _text_shapes(shapes):
    result = {}
    for shape in shapes:
        children = _text_shapes(shape.shapes) if hasattr(shape, "shapes") else {}
        if shape.has_text_frame:
            children[shape.shape_id] = shape
        if result.keys() & children.keys():
            raise DiffError("Duplicate shape identity; cannot safely pair template shapes")
        result.update(children)
    return result


def _run_properties(shape):
    return [[str(run._r.rPr.xml) if run._r.rPr is not None else None for run in paragraph.runs]
            for paragraph in shape.text_frame.paragraphs]


def diff_decks(a: Path | str, b: Path | str) -> list[Change]:
    """Compare native slide/shape identities; report content and formatting independently.

    Human locations retain the original text-shape index; matching does not use that index.
    This is a change report, not a complete preservation or rendered appearance guarantee.
    """
    a, b = Path(a), Path(b)
    _check_pair(a, b, ".pptx", "diff_decks")

    from pptx import Presentation

    from cpa import office

    office.inspect_package(a)
    office.inspect_package(b)
    slides_a = list(Presentation(str(a)).slides)
    slides_b = list(Presentation(str(b)).slides)
    changes: list[Change] = []
    if len(slides_a) != len(slides_b):
        changes.append(Change("format", "deck", "slide_count", len(slides_a), len(slides_b)))

    ids_a, ids_b = [s.slide_id for s in slides_a], [s.slide_id for s in slides_b]
    if set(ids_a) == set(ids_b) and ids_a != ids_b:
        changes.append(Change("format", "deck", "slide_order", ids_a, ids_b))
    other_slides = {s.slide_id: s for s in slides_b}
    for i, slide_a in enumerate(slides_a, start=1):
        loc = f"slide {i}"
        slide_b = other_slides.get(slide_a.slide_id)
        if slide_b is None:
            changes.append(Change("format", loc, "slide_presence", True, False))
            continue
        shapes_a, shapes_b = _text_shapes(slide_a.shapes), _text_shapes(slide_b.shapes)
        for j, identity in enumerate(dict.fromkeys([*shapes_a, *shapes_b])):
            shape_a, shape_b = shapes_a.get(identity), shapes_b.get(identity)
            shape_loc = f"{loc} shape {j}"
            if shape_a is None or shape_b is None:
                changes.append(Change("format", shape_loc, "shape_presence", shape_a is not None, shape_b is not None))
                continue
            text_a, text_b = shape_a.text_frame.text, shape_b.text_frame.text
            if text_a != text_b:
                changes.append(Change(_value_kind(text_a, text_b), shape_loc, "text", text_a, text_b))
            size_a, size_b = _first_run_size(shape_a), _first_run_size(shape_b)
            if size_a != size_b:
                changes.append(Change("format", shape_loc, "font_size", size_a, size_b))
            props_a, props_b = _run_properties(shape_a), _run_properties(shape_b)
            if props_a != props_b:
                changes.append(Change("format", shape_loc, "run_properties", props_a, props_b))
    for slide_b in slides_b:
        if slide_b.slide_id not in ids_a:
            changes.append(Change("format", f"slide {ids_b.index(slide_b.slide_id) + 1}", "slide_presence", False, True))
    return changes


# ---------------------------------------------------------------- workbooks


def _fill_rgb(fill) -> str | None:
    if fill is None or fill.fill_type != "solid":
        return None
    return str(getattr(fill.fgColor, "rgb", "") or "") or None


def diff_workbooks(a: Path | str, b: Path | str) -> list[Change]:
    """Cell-by-cell change report between two .xlsx workbooks, tab by tab (tabs present in only one
    side are reported once as format drift, not cell by cell): value (and whether it is numeric)
    plus font and fill, per cell."""
    a, b = Path(a), Path(b)
    _check_pair(a, b, ".xlsx", "diff_workbooks")

    import openpyxl

    from cpa import bigxlsx

    if bigxlsx.is_large(a) or bigxlsx.is_large(b):
        raise DiffError("Large workbook: full cell-format diff is unavailable; use streaming review")
    wb_a = openpyxl.load_workbook(str(a), rich_text=True)
    wb_b = openpyxl.load_workbook(str(b), rich_text=True)
    try:
        changes: list[Change] = []
        common_tabs = [t for t in wb_a.sheetnames if t in wb_b.sheetnames]
        for tab in common_tabs:
            sheet_a, sheet_b = wb_a[tab], wb_b[tab]
            max_row = max(sheet_a.max_row, sheet_b.max_row)
            max_col = max(sheet_a.max_column, sheet_b.max_column)
            for r in range(1, max_row + 1):
                for c in range(1, max_col + 1):
                    cell_a = sheet_a.cell(row=r, column=c)
                    cell_b = sheet_b.cell(row=r, column=c)
                    loc = f"{tab}!{cell_a.coordinate}"
                    if cell_a.value != cell_b.value:
                        changes.append(Change(_value_kind(cell_a.value, cell_b.value), loc, "value",
                                               cell_a.value, cell_b.value))
                    font_a = (cell_a.font.name, cell_a.font.bold, cell_a.font.size)
                    font_b = (cell_b.font.name, cell_b.font.bold, cell_b.font.size)
                    if font_a != font_b:
                        changes.append(Change("format", loc, "font", font_a, font_b))
                    fill_a, fill_b = _fill_rgb(cell_a.fill), _fill_rgb(cell_b.fill)
                    if fill_a != fill_b:
                        changes.append(Change("format", loc, "fill", fill_a, fill_b))
        for tab in set(wb_a.sheetnames) ^ set(wb_b.sheetnames):
            changes.append(Change("format", tab, "tab_presence", tab in wb_a.sheetnames,
                                   tab in wb_b.sheetnames))
        return changes
    finally:
        wb_a.close()
        wb_b.close()


def diff_files(a: Path | str, b: Path | str) -> list[Change]:
    """Dispatch to diff_decks or diff_workbooks by extension; raises MismatchedFiles when `a` and `b`
    are not the same kind."""
    a, b = Path(a), Path(b)
    suffix_a, suffix_b = a.suffix.lower(), b.suffix.lower()
    if suffix_a != suffix_b:
        raise MismatchedFiles(
            f"{a.name} is {suffix_a or '(no suffix)'}, {b.name} is {suffix_b or '(no suffix)'}; "
            "diff compares two files of the same kind"
        )
    if suffix_a == ".pptx":
        return diff_decks(a, b)
    if suffix_a == ".xlsx":
        return diff_workbooks(a, b)
    raise UnsupportedFile(f"{a.name}: diff reads .pptx or .xlsx only")


# ---------------------------------------------------------------- CLI


def _cmd_diff(args: argparse.Namespace) -> int:
    try:
        changes = diff_files(args.a, args.b)
    except (DiffError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([c.to_json() for c in changes], indent=2, ensure_ascii=False))
    elif not changes:
        print("diff: no changes")
    else:
        for c in changes:
            print(f"{c.location}: {c.kind} {c.field} changed: {c.before!r} -> {c.after!r}")
    return 1 if changes else 0


def register_under(sub: argparse._SubParsersAction) -> None:
    """Register `pptx diff`. Import-cheap: no file access here."""
    p = sub.add_parser(
        "diff",
        help="Slide-by-slide or cell-by-cell change report between two versions.",
        description="Exit 0 no changes, 1 one or more changes found, 2 a bad argument or an "
                    "unreadable/mismatched file pair. --a and --b must be the same kind of file, "
                    "both .pptx or both .xlsx.",
    )
    p.add_argument("--a", type=Path, required=True, help="The earlier version.")
    p.add_argument("--b", type=Path, required=True, help="The later version.")
    p.add_argument("--json", action="store_true", help="Emit changes as JSON.")
    p.set_defaults(func=_cmd_diff)
