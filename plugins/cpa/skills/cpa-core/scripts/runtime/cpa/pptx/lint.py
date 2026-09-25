"""Slide and workbook format lint (C9): the fixed formatting rules a generated deck or internal
workbook must pass before it goes out - `python -m cpa pptx lint`.

Build-list items: C9 format lint (guide 5 cpa-format, guide 9 pptx/lint.py, build-list guide-13.17
"lint passes on generated slide"). Hard rules enforced: a missing narrative-relevant metric is
flagged visibly, never silently omitted ("never bury a flag in notes", R068/R184: a CPA flag belongs
in a yellow box on the slide, never only in the speaker notes).

lint_deck() and lint_workbook() are pure readers: they never write. Deck checks (R061/R145/R185: 18pt
minimum body text for a dean/board audience; R148: speaker notes present on every slide; R068/R184:
no flag-convention text hidden only in notes; R145/R185: the 7-8 slide cap for a dean/board main
deck). Workbook checks follow the analyst branding skill: Lato/Arial, approved palette,
Source & Notes, and no freeze panes unless asked. Transformed bounds and placeholder checks
are conservative diagnostics, not rendered visual acceptance. Agenda and closing-takeaway
semantics require a workflow-specific slide-kind contract and are not inferred here.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from cpa import verify
from cpa.pptx import brand

__all__ = [
    "AUDIENCES", "DECK_KINDS", "MIN_BODY_PT", "MAX_MAIN_SLIDES",
    "LintError", "UnsupportedFile",
    "LintIssue", "lint_deck", "lint_workbook", "register_under",
]

AUDIENCES: tuple[str, ...] = ("internal", "committee", "dean", "board")
DECK_KINDS: tuple[str, ...] = ("main", "companion")
MIN_BODY_PT: float = 18.0  # R061/R145/R185
MAX_MAIN_SLIDES: int = 8  # R145/R185: "maximum of 7 to 8 slides for the main deck"
_HIGH_BAR_AUDIENCES = ("dean", "board")


class LintError(ValueError):
    """Base for lint failures: a bad argument or an unreadable file - never a format finding, those
    are LintIssue rows."""


class UnsupportedFile(LintError):
    """The path is not the extension this lint function reads."""


@dataclass
class LintIssue:
    """One technical finding, optionally attributed to the original template or this edit."""

    code: str
    location: str
    detail: str
    origin: str = "CURRENT"

    def to_json(self) -> dict:
        """Serialize a finding without treating inherited defects as approved exceptions."""
        return {"code": self.code, "location": self.location, "detail": self.detail, "origin": self.origin}


def _run_point_sizes(shape):
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            if run.font.size is not None:
                yield run.font.size.pt


def lint_deck(path: Path | str, *, audience: str, deck_kind: str = "main",
              baseline: Path | str | None = None) -> list[LintIssue]:
    """Format-lint one .pptx against `audience`'s rules; returns every issue found (empty = passes).

    `deck_kind`: "main" (the 7-8 slide cap applies to a dean/board deck) or "companion" (the guide's
    longer analytical deck, never capped)."""
    if audience not in AUDIENCES:
        raise LintError(f"audience must be one of {AUDIENCES}, got {audience!r}")
    if deck_kind not in DECK_KINDS:
        raise LintError(f"deck_kind must be one of {DECK_KINDS}, got {deck_kind!r}")
    path = Path(path)
    if path.suffix.lower() != ".pptx":
        raise UnsupportedFile(f"{path.name}: lint_deck reads .pptx only")
    if not path.is_file():
        raise FileNotFoundError(f"deck not found: {path}")

    from pptx import Presentation

    from cpa import office
    from cpa.pptx.geometry import diagnostics

    office.inspect_package(path)
    prs = Presentation(str(path))
    slides = list(prs.slides)
    high_bar = audience in _HIGH_BAR_AUDIENCES
    issues: list[LintIssue] = [LintIssue(*finding) for finding in diagnostics(prs)]

    if high_bar and deck_kind == "main" and len(slides) > MAX_MAIN_SLIDES:
        issues.append(LintIssue(
            "TOO_MANY_SLIDES", "deck",
            f"{len(slides)} slides; a dean/board main deck caps at {MAX_MAIN_SLIDES} (R145/R185; "
            "put the detail in a companion deck)",
        ))

    for i, slide in enumerate(slides, start=1):
        loc = f"slide {i}"
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    for run in paragraph.runs:
                        if run.font.name and run.font.name not in ("Lato", "Arial"):
                            issues.append(LintIssue("UNAPPROVED_FONT", loc,
                                                     f"font {run.font.name!r}; use Lato or Arial"))
        if high_bar:
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                if shape.name in ("footer", "page_number", "source_line", "footnote"):
                    continue  # explicitly typed non-body elements have their own smaller scales
                for pt in _run_point_sizes(shape):
                    if pt < MIN_BODY_PT:
                        issues.append(LintIssue(
                            "BODY_TEXT_TOO_SMALL", loc,
                            f"{pt:g}pt run; {MIN_BODY_PT:g}pt minimum on a dean/board deck "
                            "(R061/R145/R185)",
                        ))
        notes_text = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        if not notes_text.strip():
            issues.append(LintIssue("NOTES_MISSING", loc,
                                     "no speaker notes text (R148: notes present on every slide)"))
        elif verify.M2_MISSING_MARKER.casefold() in notes_text.casefold():
            issues.append(LintIssue(
                "FLAG_IN_NOTES", loc,
                "a CPA flag belongs in a yellow box on the slide, never only in the speaker notes "
                "(R068/R184)",
            ))
    if baseline is not None:
        from collections import Counter

        prior = Counter((i.code, i.location, i.detail) for i in lint_deck(baseline, audience=audience, deck_kind=deck_kind))
        for issue in issues:
            key = (issue.code, issue.location, issue.detail)
            issue.origin = "INHERITED" if prior[key] else "NEW"
            if prior[key]:
                prior[key] -= 1
    return issues


def lint_workbook(path: Path | str, tab: str | None = None, *, allow_freeze: bool = False) -> list[LintIssue]:
    """Read-only brand diagnostics: approved fonts/fills, source notes and freeze permission.

    `tab=None` checks every sheet. Protected templates are reported, never restyled.
    """
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        raise UnsupportedFile(f"{path.name}: lint_workbook reads .xlsx only")
    if not path.is_file():
        raise FileNotFoundError(f"workbook not found: {path}")

    import openpyxl

    from cpa import bigxlsx

    if bigxlsx.is_large(path):
        return [LintIssue("STREAMING_REVIEW_REQUIRED", "workbook",
                          "Use cpa.bigxlsx for files above 15 MB; full format inspection is not available here")]
    wb = openpyxl.load_workbook(str(path), read_only=False)
    try:
        if tab is not None and tab not in wb.sheetnames:
            raise LintError(f"{path.name} has no tab {tab!r}")
        sheets = [wb[tab]] if tab is not None else wb.worksheets
        issues: list[LintIssue] = []
        if "Source & Notes" not in wb.sheetnames:
            issues.append(LintIssue("SOURCE_NOTES_MISSING", "workbook", "Source & Notes tab required; Verification is separate"))
        for ws in sheets:
            if ws.freeze_panes and not allow_freeze:
                issues.append(LintIssue(
                    "FREEZE_PANES", ws.title,
                    f"freeze_panes={ws.freeze_panes!r}; internal files carry no freeze panes unless "
                    "asked (R019/R146/R186; pass --allow-freeze if she asked)",
                ))
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is None:
                        continue
                    coord = f"{ws.title}!{cell.coordinate}"
                    name = cell.font.name if cell.font else None
                    if name not in ("Arial", "Lato"):
                        issues.append(LintIssue("UNAPPROVED_FONT", coord,
                                                 f"font {name!r}; branding requires Lato or Arial"))
                    if cell.fill is not None and cell.fill.fill_type == "solid":
                        fg = str(getattr(cell.fill.fgColor, "rgb", "") or "")[-6:].upper()
                        if fg not in brand.APPROVED_FILLS:
                            issues.append(LintIssue(
                                "UNAPPROVED_FILL", coord,
                                f"fill #{fg}; use the analyst's approved palette. Theme/indexed colors need explicit review.",
                            ))
        return issues
    finally:
        wb.close()


# ---------------------------------------------------------------- CLI


def _cmd_lint(args: argparse.Namespace) -> int:
    issues: list[LintIssue] = []
    try:
        if not args.deck and not args.workbook:
            raise LintError("pass --deck and/or --workbook")
        if args.deck:
            issues += lint_deck(args.deck, audience=args.audience, deck_kind=args.deck_kind)
        if args.workbook:
            issues += lint_workbook(args.workbook, args.tab, allow_freeze=args.allow_freeze)
    except (LintError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([i.to_json() for i in issues], indent=2, ensure_ascii=False))
    elif not issues:
        print("lint: no findings in checked scope; visual review NOT_REVIEWED; financial verification separate")
    else:
        for i in issues:
            print(f"{i.location}: {i.code} - {i.detail}")
    return 1 if issues else 0


def register_under(sub: argparse._SubParsersAction) -> None:
    """Register `pptx lint`. Import-cheap: no file access here."""
    p = sub.add_parser(
        "lint",
        help="Format-lint a deck and/or workbook against the audience's rules.",
        description="Exit 0 clean, 1 one or more issues found, 2 a bad argument or unreadable file.",
    )
    p.add_argument("--deck", type=Path, default=None, help="A .pptx to lint.")
    p.add_argument("--workbook", type=Path, default=None, help="A .xlsx to lint.")
    p.add_argument("--tab", default=None, help="Workbook sheet name to check (default: every sheet).")
    p.add_argument("--audience", choices=AUDIENCES, default="internal",
                   help="Deck audience: internal, committee, dean, or board (default: internal).")
    p.add_argument("--deck-kind", choices=DECK_KINDS, default="main",
                   help="main (the 7-8 slide cap applies) or companion (no cap). Default: main.")
    p.add_argument("--allow-freeze", action="store_true",
                   help="Allow freeze panes on the workbook (only when she asked).")
    p.add_argument("--json", action="store_true", help="Emit issues as JSON.")
    p.set_defaults(func=_cmd_lint)
