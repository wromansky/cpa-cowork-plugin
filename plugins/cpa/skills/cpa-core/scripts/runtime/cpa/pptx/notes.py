"""Speaker notes generator (C10): notes density by audience, and figures flagged as changed since
the last version - `python -m cpa pptx notes --audience`.

Build-list items: C10 speaker notes generator (guide 5 cpa-format, guide 9 pptx/notes.py, build-list
C10 row). R147: notes density by audience - dean and board get the high-level story, committee and
internal get the detail; every figure that changed since the last version is called out. R068/R184
"never bury a flag in notes": a flagged (missing) metric is named here by its metric name only - its
why/source text is brand.flag_text's job, for the on-slide yellow box, never for the speaker notes.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "AUDIENCES", "DENSITY", "NotesError",
    "Figure", "Slide", "slide_notes", "write_notes", "register_under",
]

AUDIENCES: tuple[str, ...] = ("internal", "committee", "dean", "board")
# R147: "Dean: high-level story; committee: detail." Board is grouped with dean throughout the rules
# (R145/R185 always pair them); internal is grouped with committee - both want the numbers, not a story.
DENSITY: dict[str, str] = {"dean": "high_level", "board": "high_level",
                            "committee": "detailed", "internal": "detailed"}


class NotesError(ValueError):
    """Base for notes failures: a bad argument, a slide-count mismatch, or an unreadable file."""


@dataclass
class Figure:
    """One figure mentioned on a slide, for the notes to cite and to flag as changed."""

    label: str
    value: Any
    period: str = ""
    status: str = ""
    changed: bool = False
    prior_value: Any = None


@dataclass
class Slide:
    """What one slide's notes are built from. `flagged_metrics` names a metric missing on the slide -
    only the name, never why/source (R068: that detail stays on-slide, never in the notes)."""

    title: str
    points: list[str] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    flagged_metrics: list[str] = field(default_factory=list)


def slide_notes(slide: Slide, audience: str) -> str:
    """The notes text for one slide, at the density R147 names for `audience`."""
    if audience not in AUDIENCES:
        raise NotesError(f"audience must be one of {AUDIENCES}, got {audience!r}")
    density = DENSITY[audience]
    changed = [f for f in slide.figures if f.changed]
    lines: list[str] = []
    if density == "high_level":
        story = slide.title
        if slide.points:
            story += ": " + " ".join(slide.points[:2])
        lines.append(story)
        if changed:
            lines.append(f"Changed since last version: {', '.join(f.label for f in changed)}.")
    else:
        lines.append(slide.title)
        for point in slide.points:
            lines.append(f"- {point}")
        for f in slide.figures:
            tag = "[CHANGED] " if f.changed else ""
            bits = [str(f.value)]
            if f.period:
                bits.append(f.period)
            if f.status:
                bits.append(f.status)
            line = f"{tag}{f.label}: {', '.join(bits)}"
            if f.changed and f.prior_value is not None:
                line += f" (was {f.prior_value})"
            lines.append(line)
    if slide.flagged_metrics:
        lines.append(f"See the on-slide flag for: {', '.join(slide.flagged_metrics)}.")
    return "\n".join(lines)


def write_notes(deck: Path | str, slides: list[Slide], audience: str) -> list[str]:
    """Write slide_notes() onto every slide of `deck`, in order. `slides` must have one entry per
    slide already in the deck; raises NotesError otherwise (this module never adds or removes
    slides). Returns the text written, one entry per slide."""
    path = Path(deck)
    if path.suffix.lower() != ".pptx":
        raise NotesError(f"{path.name}: write_notes writes .pptx only")
    if not path.is_file():
        raise FileNotFoundError(f"deck not found: {path}")

    from pptx import Presentation

    from cpa import fsutil

    prs = Presentation(str(path))
    slide_objs = list(prs.slides)
    if len(slides) != len(slide_objs):
        raise NotesError(
            f"{path.name} has {len(slide_objs)} slide(s), got {len(slides)} Slide entr"
            f"{'y' if len(slides) == 1 else 'ies'}"
        )
    texts = [slide_notes(content, audience) for content in slides]
    for slide_obj, text in zip(slide_objs, texts):
        slide_obj.notes_slide.notes_text_frame.text = text
    fsutil.atomic_write(path, lambda tmp: prs.save(str(tmp)))
    return texts


# ---------------------------------------------------------------- CLI


def _figure_from_dict(d: dict) -> Figure:
    return Figure(label=str(d.get("label", "")), value=d.get("value"), period=str(d.get("period", "")),
                  status=str(d.get("status", "")), changed=bool(d.get("changed", False)),
                  prior_value=d.get("prior_value"))


def _slide_from_dict(d: dict) -> Slide:
    figures = [_figure_from_dict(f) for f in d.get("figures", [])]
    return Slide(title=str(d.get("title", "")), points=[str(p) for p in d.get("points", [])],
                 figures=figures, flagged_metrics=[str(m) for m in d.get("flagged_metrics", [])])


def _cmd_notes(args: argparse.Namespace) -> int:
    try:
        data = json.loads(args.content.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            raise NotesError(f"{args.content}: must be a JSON array, one object per slide")
        slides = [_slide_from_dict(d) for d in data]
        texts = write_notes(args.deck, slides, args.audience)
    except (NotesError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(texts, indent=2, ensure_ascii=False))
    else:
        for i, text in enumerate(texts, start=1):
            print(f"--- slide {i} ---")
            print(text)
    return 0


def register_under(sub: argparse._SubParsersAction) -> None:
    """Register `pptx notes`. Import-cheap: no file access here."""
    p = sub.add_parser(
        "notes",
        help="Generate and write speaker notes, density by audience.",
        description="Exit 0 on success, 2 on a bad argument, a slide-count mismatch, or an "
                    "unreadable file.",
    )
    p.add_argument("--deck", type=Path, required=True, help="The .pptx to write notes into.")
    p.add_argument("--audience", choices=AUDIENCES, required=True,
                   help="dean/board get the high-level story; committee/internal get the detail "
                        "(R147).")
    p.add_argument("--content", type=Path, required=True,
                   help="JSON array, one object per slide: title, points, figures "
                        "([{label,value,period,status,changed,prior_value}]), flagged_metrics "
                        "(metric names only, never why/source).")
    p.add_argument("--json", action="store_true", help="Emit the written notes text as JSON.")
    p.set_defaults(func=_cmd_notes)
