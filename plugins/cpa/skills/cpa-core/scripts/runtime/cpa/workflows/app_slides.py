"""APP committee slide (B5), returning-position Q&A slide (B6), deck assembly (B7).

FIXTURE -- confirm against her file: no real APP committee slide or SOM Review deck exists in this
repository (same status as U06's own tests, docs/FIXTURE_SWAP.md). Every slide is built fresh with
python-pptx rather than populated into a template; BRANDING_TEXT/FOOTER_FMT/INCUMBENT_LABEL are FIXTURE
wording pending her real deck.

Build-list items: B5 APP committee slide, B6 returning-position Q&A slide, B7 deck assembly (guide 9
app_slides.py, guide 13.16-13.18). Hard rules enforced: 7 (every figure equals the workbook cell it
came from -- read from the PnL's own manifest `figures`, never recomputed), a missing narrative-relevant
metric is a yellow flag box on the slide, never only in notes (R068/R184), never blank/estimated (rule
5/7), nothing is sent to a source system.

Data sources (no unit invents another unit's file format, D19; this unit's own new contracts marked so):
- position details, cycle, cFTE: `cpa.workflows.app_pnl.load_inputs` (built, staging `pnl_inputs.json`).
- named rows (JHU Contribution Margin, Division Surplus), 3 years: the PnL workbook's own manifest
  `figures` (fids `f"{name}_y{n}"`, app_pnl's own naming) -- the exact cell the workbook holds.
- benchmark statements and every flag (collection rate, fringe, M2/cFTE, locked cells): staging
  `pnl_flags.json` (app_pnl's `BuildResult.to_json()`), printed verbatim, never re-derived.
- new here: `staging/app/<pos>/slide_inputs.json` `{"business_need": str}` (the cpa-app-slide skill).
- new here: `staging/app/<pos>/qa_inputs.json` `{"questions": [{question_id, question, status, summary,
  contradicts_pnl, contradiction_note}]}` -- status is supplied by her via the skill, never inferred
  (hard rule 15).

Architecture: python-pptx cannot cheaply copy a slide between `Presentation` objects, so `deck()` never
copies `slide.pptx`/`qa_slide.pptx` files -- it calls the same `_render_*` functions position()/qa() use,
into one shared `Presentation`, then walks every slide once to set its `page_number`-named shape.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from cpa import state

__all__ = [
    "WORKFLOW_SLIDE", "WORKFLOW_DECK", "SLIDE_NAME", "QA_NAME", "DECK_NAME_FMT", "SLIDE_INPUTS_NAME",
    "QA_INPUTS_NAME", "EXCLUSIONS_NAME_FMT", "QA_STATUSES", "AUDIENCE", "ROW_COLORS", "ROW_LABELS",
    "BENCH_METRICS", "BRANDING_TEXT", "FOOTER_FMT", "INCUMBENT_LABEL", "EXIT_OK", "EXIT_ISSUES", "EXIT_STOPPED",
    "AppSlidesError", "SlideInputError", "QaInputError", "PnlNotVerified", "CycleError", "LintFailed",
    "BenchmarkRow", "NamedRow", "CfteInfo", "SlideContent", "QaRow", "QaContent", "Exclusion", "DeckResult",
    "position", "position_detailed", "qa", "qa_detailed", "deck", "deck_detailed", "READINESS_RULES", "register",
]

WORKFLOW_SLIDE = "cpa-app-slide"  # both position() and qa() (interfaces.json: both dispatch under this skill)
WORKFLOW_DECK = "cpa-app-deck"
SLIDE_NAME = "slide.pptx"           # Build List :123
QA_NAME = "qa_slide.pptx"           # Build List :131
DECK_NAME_FMT = "SOM_Review_{cycle}.pptx"          # Build List :138; cycle = YYYY-MM-DD
EXCLUSIONS_NAME_FMT = "SOM_Review_{cycle}_exclusions.md"
SLIDE_INPUTS_NAME = "slide_inputs.json"
QA_INPUTS_NAME = "qa_inputs.json"
QA_STATUSES = ("ANSWERED", "PARTIAL", "NOT ANSWERED", "PENDING")  # R211, exact order guide/build-list state
AUDIENCE = "committee"  # lint.py / notes.py audience for every slide this unit builds
ROW_LABELS = {"jhu_contribution_margin": "JHU Contribution Margin", "division_surplus": "Division Surplus / Deficit"}
ROW_COLORS = {"jhu_contribution_margin": "gold", "division_surplus": "navy"}  # R216/R217
BENCH_METRICS = ("TCC", "Work RVUs")
# FIXTURE -- confirm against her file: branding/footer/placeholder wording; no her real deck exists yet.
BRANDING_TEXT = "Johns Hopkins University School of Medicine"
FOOTER_FMT = "Clinical Practice Association | SOM Review Committee | {cycle}"
INCUMBENT_LABEL = "Incumbent actuals (fill in by hand before the meeting)"
EXIT_OK, EXIT_ISSUES, EXIT_STOPPED = 0, 1, 2


class AppSlidesError(RuntimeError):
    """Base for every app_slides failure; raised before any output file for that command is written."""


class SlideInputError(AppSlidesError):
    """slide_inputs.json (or pnl_flags.json) is absent, unreadable, or does not match the position."""


class QaInputError(AppSlidesError):
    """qa_inputs.json is absent or invalid, or a question_id repeats (R115: exactly once)."""


class PnlNotVerified(AppSlidesError):
    """No PnL.xlsx, its locked cells changed after recalculation, or it has not been through cpa-verify (R069)."""


class CycleError(AppSlidesError):
    """The position's SOM cycle cannot be determined, or more than one cycle's outbox claims it."""


class LintFailed(AppSlidesError):
    """A generated slide or deck failed its own format lint -- a construction bug, never shipped unchecked."""


@dataclass(frozen=True)
class BenchmarkRow:
    """One TCC/Work RVUs row. `statement` (full percentile sentence, citing specialty + survey column,
    R114) when stated; else `flag_text` (the pnl_flags.json MISSING text, printed once in the flag stack,
    never duplicated as a stated benchmark)."""

    metric: str
    statement: str | None
    flag_text: str | None


@dataclass(frozen=True)
class NamedRow:
    """JHU Contribution Margin or Division Surplus/Deficit: three years from the PnL's own manifest
    figures (R214); `flag_text` set only when every year is None (not recalculated)."""

    key: str
    label: str
    color: str
    values: dict[int, float | None]
    flag_text: str | None


@dataclass(frozen=True)
class CfteInfo:
    value: Any
    period: str
    status: str
    source: str
    as_of: str
    flag_text: str | None


@dataclass(frozen=True)
class SlideContent:
    position_id: str
    cycle: str
    as_of: str
    department: str
    division: str
    role: str
    plan_period: str
    business_need: str
    benchmarks: tuple[BenchmarkRow, ...]
    named_rows: tuple[NamedRow, ...]
    cfte: CfteInfo
    flags: tuple[str, ...]           # every flag's full text, one yellow box each (R068/R184)
    flagged_labels: tuple[str, ...]  # names only, for speaker notes (R068: never why/source in notes)
    workbook: Path


@dataclass(frozen=True)
class QaRow:
    question_id: str
    question: str
    status: str
    summary: str
    contradicts_pnl: bool
    contradiction_note: str


@dataclass(frozen=True)
class QaContent:
    position_id: str
    cycle: str
    rows: tuple[QaRow, ...]


@dataclass(frozen=True)
class Exclusion:
    """R116: a position with no complete, verified, slide-built P&L, and why."""

    position_id: str
    code: str  # NO_INPUTS | NO_VERIFIED_PNL | NO_SLIDE
    reason: str


@dataclass
class DeckResult:
    path: Path
    new: tuple[str, ...] = ()
    returning: tuple[str, ...] = ()
    excluded: tuple[Exclusion, ...] = ()
    exclusions_path: Path | None = None

    def to_json(self) -> dict:
        from cpa import manifest

        return {"path": manifest.to_rel(self.path), "new": list(self.new), "returning": list(self.returning),
                "excluded": [{"position_id": e.position_id, "code": e.code, "reason": e.reason}
                            for e in self.excluded],
                "exclusions_path": manifest.to_rel(self.exclusions_path) if self.exclusions_path else None}


# ---------------------------------------------------------------- small helpers


def _stage(ws: Path, position_id: str) -> Path:
    return ws / "staging" / "app" / position_id


def manifest_rel(path: Path) -> str:
    from cpa import manifest

    return manifest.to_rel(path)


def _read_json(path: Path, what: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise SlideInputError(f"{manifest_rel(path)} not found: the cpa-app-slide skill writes it before "
                              f"`app_slides {what}`") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SlideInputError(f"{path.name} is not valid JSON ({exc})") from exc


def _flag_label(flag: dict) -> str:
    """The metric/thing a flag names, for speaker notes (names only, never why/source, R068)."""
    from cpa import verify

    text = str(flag.get("text", ""))
    m = re.match(rf"^{re.escape(verify.M2_MISSING_MARKER)}:\s*(.+?)\s+not supplied\b", text)
    if m:
        return m.group(1)
    return str(flag.get("kind", "flag")).replace("_", " ")


# ---------------------------------------------------------------- cycle and PnL location


def _resolve_cycle(position_id: str, ws: Path):
    """(PositionInputs, cycle) for a position: `pnl_inputs.json`'s own cycle, else the single cycle
    folder its PnL was built under. Never guesses when more than one cycle claims it."""
    from cpa.workflows import app_pnl

    inputs = app_pnl.load_inputs(position_id, ws)
    if inputs.cycle:
        return inputs, inputs.cycle
    app_dir = ws / "outbox" / "app"
    hits = (sorted({p.parent.name for p in app_dir.glob("*/" + position_id) if p.is_dir()})
           if app_dir.is_dir() else [])
    if not hits:
        raise CycleError(f"no cycle recorded for {position_id!r}: set cycle in {app_pnl.INPUTS_NAME}, or build "
                         "the P&L first (its outbox folder names the cycle)")
    if len(hits) > 1:
        raise CycleError(f"{position_id!r} has PnL output under more than one cycle ({', '.join(hits)}); set "
                         f"cycle in {app_pnl.INPUTS_NAME} to disambiguate")
    return inputs, hits[0]


def _pnl_paths(ws: Path, cycle: str, position_id: str) -> tuple[Path, Path, Path]:
    from cpa.workflows import app_pnl

    out_dir = ws / "outbox" / "app" / cycle / position_id
    return out_dir, out_dir / app_pnl.OUTPUT_NAME, out_dir / app_pnl.FAILED_NAME


def _require_verified_pnl(position_id: str, pnl_path: Path, failed_path: Path) -> None:
    """R069: never include a position without a verified P&L."""
    from cpa import manifest

    if failed_path.is_file():
        raise PnlNotVerified(f"{position_id}: {manifest.to_rel(failed_path)} exists (locked cells changed after "
                             "recalculation); do not send -- fix and rerun `cpa app_pnl build`")
    if not pnl_path.is_file():
        raise PnlNotVerified(f"{position_id}: no P&L at {manifest.to_rel(pnl_path)}; run "
                             f"`python -m cpa app_pnl build --position {position_id}` first")
    if not manifest.exists(pnl_path) or "verification" not in manifest.read(pnl_path):
        raise PnlNotVerified(f"{position_id}: {manifest.to_rel(pnl_path)} has not been through cpa-verify "
                             "(no verification record in its manifest)")


# ---------------------------------------------------------------- committee slide content


def _load_slide_inputs(stage: Path) -> dict:
    data = _read_json(stage / SLIDE_INPUTS_NAME, "position")
    if not isinstance(data, dict) or not str(data.get("business_need") or "").strip():
        raise SlideInputError(f"{manifest_rel(stage / SLIDE_INPUTS_NAME)} must be a JSON object with a "
                              "non-empty business_need string (never fabricated, hard rule 15)")
    return data


def _named_rows(pnl_path: Path, recalc_reason: str) -> tuple[NamedRow, ...]:
    from cpa import manifest
    from cpa.pptx import brand
    from cpa.workflows import app_pnl

    figures = (manifest.read(pnl_path).get("figures") or {}) if manifest.exists(pnl_path) else {}
    rows = []
    for key in app_pnl.NAMED_ROWS:
        values: dict[int, float | None] = {}
        for n in range(1, app_pnl.YEARS + 1):
            rec = figures.get(f"{key}_y{n}") or {}
            values[n] = rec.get("value")
        flag = None
        if all(v is None for v in values.values()):
            flag = brand.flag_text(ROW_LABELS[key], f"the committee slide's {ROW_LABELS[key]} row",
                                   f"the APP P&L (not recalculated: {recalc_reason or 'unknown reason'})")
        rows.append(NamedRow(key, ROW_LABELS[key], ROW_COLORS[key], values, flag))
    return tuple(rows)


def _benchmark_rows(payload: dict) -> tuple[BenchmarkRow, ...]:
    statements = payload.get("statements") or {}
    flags = payload.get("flags") or []
    rows = []
    for metric in BENCH_METRICS:
        statement = statements.get(metric)
        flag_text = None
        if statement is None:
            flag_text = next((f.get("text") for f in flags
                              if f.get("kind") == "benchmark" and metric in str(f.get("text", ""))), None)
        rows.append(BenchmarkRow(metric, statement, flag_text))
    return tuple(rows)


def _cfte(inputs, payload: dict) -> CfteInfo:
    cfte = inputs.cfte
    if cfte:
        return CfteInfo(cfte.get("value"), str(cfte.get("period", "")), str(cfte.get("status", "")),
                        str(cfte.get("source", "")), str(cfte.get("as_of", "")), None)
    flags = payload.get("flags") or []
    hit = next((f.get("text") for f in flags if f.get("kind") == "m2" and "cFTE" in str(f.get("text", ""))), None)
    return CfteInfo(None, "", "", "", "", hit)


def _flags_and_labels(payload: dict, named_rows: tuple[NamedRow, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    texts: list[str] = []
    labels: list[str] = []
    for f in (payload.get("flags") or []):
        texts.append(str(f.get("text", "")))
        labels.append(_flag_label(f))
    for row in named_rows:
        if row.flag_text:
            texts.append(row.flag_text)
            labels.append(row.label)
    return tuple(texts), tuple(labels)


def _slide_content(position_id: str, ws: Path) -> SlideContent:
    from cpa.workflows import app_pnl

    stage = _stage(ws, position_id)
    slide_inputs = _load_slide_inputs(stage)
    inputs, cycle = _resolve_cycle(position_id, ws)
    out_dir, pnl_path, failed_path = _pnl_paths(ws, cycle, position_id)
    _require_verified_pnl(position_id, pnl_path, failed_path)
    payload = _read_json(stage / app_pnl.FLAGS_NAME, "position")
    if not isinstance(payload, dict) or payload.get("position_id") != position_id:
        raise SlideInputError(f"{manifest_rel(stage / app_pnl.FLAGS_NAME)} is for position "
                              f"{payload.get('position_id') if isinstance(payload, dict) else '?'!r}, not "
                              f"{position_id!r}")
    named_rows = _named_rows(pnl_path, str(payload.get("recalc_reason") or ""))
    benchmarks = _benchmark_rows(payload)
    cfte = _cfte(inputs, payload)
    flags, labels = _flags_and_labels(payload, named_rows)
    return SlideContent(
        position_id=position_id, cycle=cycle, as_of=inputs.as_of, department=inputs.department,
        division=inputs.division, role=inputs.role, plan_period=inputs.plan_period,
        business_need=str(slide_inputs["business_need"]), benchmarks=benchmarks, named_rows=named_rows,
        cfte=cfte, flags=flags, flagged_labels=labels, workbook=pnl_path,
    )


def _slide_title(content: SlideContent) -> str:
    return f"APP Committee Review: {content.department} / {content.division} - {content.role}"


def _money(v: float) -> str:
    return f"-${-v:,.0f}" if v < 0 else f"${v:,.0f}"


# ---------------------------------------------------------------- shape helpers (python-pptx)


def _add_rect(slide, left, top, width, height, hexcolor: str, name: str):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(hexcolor.lstrip("#").upper())
    shape.line.fill.background()
    shape.name = name
    return shape


def _add_text(slide, left, top, width, height, text: str, name: str, *, size_pt=14, bold=False,
              color_hex: str | None = None):
    from pptx.dml.color import RGBColor
    from pptx.util import Pt

    box = slide.shapes.add_textbox(left, top, width, height)
    box.name = name
    tf = box.text_frame
    tf.word_wrap = True
    lines = str(text).split("\n") if text else [""]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text = line
        run.font.name = "Arial"
        run.font.size = Pt(size_pt)
        run.font.bold = bold
        if color_hex:
            run.font.color.rgb = RGBColor.from_string(color_hex.lstrip("#").upper())
    return box


# ---------------------------------------------------------------- rendering


def _render_committee_slide(prs, content: SlideContent):
    """R183 fixed layout: left narrative/details, right benchmarks + named rows, ice-blue cFTE table
    bottom left, empty incumbent-actuals space, yellow flag boxes, navy header, gold divider, footer,
    page number. Never opens the workbook: every figure is the value the PnL's own manifest already
    recorded for that cell (R114)."""
    from pptx.util import Inches

    from cpa.pptx import brand

    navy, gold = brand.color("navy"), brand.color("gold")
    ice_blue, yellow = brand.color("ice_blue"), brand.color("flag_yellow")

    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)

    _add_rect(slide, Inches(0), Inches(0), Inches(10), Inches(0.7), navy, "header")
    _add_text(slide, Inches(0.25), Inches(0.1), Inches(9.5), Inches(0.5), _slide_title(content), "header_title",
              size_pt=18, bold=True, color_hex="#FFFFFF")
    _add_rect(slide, Inches(0), Inches(0.7), Inches(10), Inches(0.04), gold, "gold_divider")

    left_text = (f"Business need:\n{content.business_need}\n\nDepartment: {content.department}\n"
                f"Division: {content.division}\nRole: {content.role}\nPlan period: {content.plan_period}")
    _add_text(slide, Inches(0.25), Inches(0.9), Inches(4.4), Inches(3.4), left_text, "narrative_box", size_pt=11)

    _add_rect(slide, Inches(0.25), Inches(4.5), Inches(2.1), Inches(1.3), ice_blue, "cfte_box")
    if content.cfte.flag_text is None:
        cfte_text = f"cFTE: {content.cfte.value}\n{content.cfte.period} {content.cfte.status}\n{content.cfte.source}"
    else:
        cfte_text = "cFTE: see flag below"
    _add_text(slide, Inches(0.3), Inches(4.55), Inches(2.0), Inches(1.2), cfte_text, "cfte_text", size_pt=9)

    # R113: this space is always left empty -- never filled by code, regardless of any input.
    _add_rect(slide, Inches(2.5), Inches(4.5), Inches(2.15), Inches(1.3), "#FFFFFF", "incumbent_actuals_box")
    _add_text(slide, Inches(2.55), Inches(4.55), Inches(2.05), Inches(1.2), INCUMBENT_LABEL,
              "incumbent_actuals", size_pt=9)

    y = Inches(0.9)
    _add_text(slide, Inches(4.85), y, Inches(4.9), Inches(0.35), "SullivanCotter benchmarks (2025 AMC)",
              "benchmarks_title", size_pt=13, bold=True)
    y = Inches(1.3)
    for i, row in enumerate(content.benchmarks):
        text = row.statement if row.statement is not None else f"{row.metric}: not available - see flag below"
        _add_text(slide, Inches(4.85), y, Inches(4.9), Inches(0.7), text, f"benchmark_row_{i}", size_pt=10)
        y = y + Inches(0.75)

    for row in content.named_rows:
        color = brand.color(row.color)
        _add_rect(slide, Inches(4.85), y, Inches(4.9), Inches(0.5), color, f"named_row_{row.key}")
        if row.flag_text is None:
            values_text = ", ".join(f"Year {n} {_money(v)}" for n, v in sorted(row.values.items()))
        else:
            values_text = "see flag below"
        _add_text(slide, Inches(4.9), y, Inches(4.8), Inches(0.5), f"{row.label}: {values_text}",
                  f"named_row_text_{row.key}", size_pt=10, bold=True, color_hex="#FFFFFF")
        y = y + Inches(0.55)

    fy = max(y, Inches(5.9))
    for i, text in enumerate(content.flags):
        _add_rect(slide, Inches(0.25), fy, Inches(9.5), Inches(0.35), yellow, f"flag_{i}")
        _add_text(slide, Inches(0.3), fy, Inches(9.4), Inches(0.35), text, f"flag_text_{i}", size_pt=8)
        fy = fy + Inches(0.4)

    _add_text(slide, Inches(0.25), Inches(7.15), Inches(7.2), Inches(0.3),
              FOOTER_FMT.format(cycle=content.cycle) + " | " + BRANDING_TEXT, "footer", size_pt=7)
    _add_text(slide, Inches(9.0), Inches(7.15), Inches(0.8), Inches(0.3), "1", "page_number", size_pt=7)
    return slide


def _render_qa_slide(prs, content: QaContent):
    """R211/R115: every prior question exactly once, tagged with one of QA_STATUSES; a contradicting
    answer gets its own yellow flag box (R184), never only a note in speaker notes."""
    from pptx.util import Inches

    from cpa.pptx import brand

    navy, gold, yellow = brand.color("navy"), brand.color("gold"), brand.color("flag_yellow")

    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)

    _add_rect(slide, Inches(0), Inches(0), Inches(10), Inches(0.7), navy, "header")
    _add_text(slide, Inches(0.25), Inches(0.1), Inches(9.5), Inches(0.5),
              f"Returning Position Q&A: {content.position_id}", "header_title", size_pt=18, bold=True,
              color_hex="#FFFFFF")
    _add_rect(slide, Inches(0), Inches(0.7), Inches(10), Inches(0.04), gold, "gold_divider")

    y = Inches(0.9)
    for row in content.rows:
        text = f"[{row.status}] {row.question}\nA: {row.summary}"
        _add_text(slide, Inches(0.25), y, Inches(9.5), Inches(0.65), text, f"qa_row_{row.question_id}", size_pt=10)
        y = y + Inches(0.7)
        if row.contradicts_pnl:
            note = row.contradiction_note or f"{row.question_id}: this answer appears to contradict the P&L"
            _add_rect(slide, Inches(0.25), y, Inches(9.5), Inches(0.35), yellow, f"qa_flag_{row.question_id}")
            _add_text(slide, Inches(0.3), y, Inches(9.4), Inches(0.35), note, f"qa_flag_text_{row.question_id}",
                      size_pt=8)
            y = y + Inches(0.4)

    _add_text(slide, Inches(0.25), Inches(7.15), Inches(7.2), Inches(0.3),
              FOOTER_FMT.format(cycle=content.cycle) + " | " + BRANDING_TEXT, "footer", size_pt=7)
    _add_text(slide, Inches(9.0), Inches(7.15), Inches(0.8), Inches(0.3), "1", "page_number", size_pt=7)
    return slide


def _render_agenda_slide(prs, new_ids: Sequence[str], returning_ids: Sequence[str], cycle: str):
    """R184: every deck opens with an agenda listing new requests plus a placeholder section for
    returning positions."""
    from pptx.util import Inches

    from cpa.pptx import brand

    navy, gold = brand.color("navy"), brand.color("gold")

    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)

    _add_rect(slide, Inches(0), Inches(0), Inches(10), Inches(0.7), navy, "header")
    _add_text(slide, Inches(0.25), Inches(0.1), Inches(9.5), Inches(0.5), f"SOM Review Committee - Agenda ({cycle})",
              "header_title", size_pt=20, bold=True, color_hex="#FFFFFF")
    _add_rect(slide, Inches(0), Inches(0.7), Inches(10), Inches(0.04), gold, "gold_divider")

    new_text = "New requests:\n" + ("\n".join(f"- {p}" for p in new_ids) if new_ids else "- none this cycle")
    _add_text(slide, Inches(0.25), Inches(0.9), Inches(9.4), Inches(2.9), new_text, "agenda_new", size_pt=13)

    ret_text = ("Returning positions:\n"
               + ("\n".join(f"- {p}" for p in returning_ids) if returning_ids else "- none this cycle"))
    _add_text(slide, Inches(0.25), Inches(3.9), Inches(9.4), Inches(2.9), ret_text, "agenda_returning", size_pt=13)

    _add_text(slide, Inches(0.25), Inches(7.15), Inches(7.2), Inches(0.3),
              FOOTER_FMT.format(cycle=cycle) + " | " + BRANDING_TEXT, "footer", size_pt=7)
    _add_text(slide, Inches(9.0), Inches(7.15), Inches(0.8), Inches(0.3), "1", "page_number", size_pt=7)
    return slide


# ---------------------------------------------------------------- position(), qa()


def position_detailed(position_id: str, *, ws: Path | None = None) -> Path:
    """Build outbox/app/<cycle>/<position>/slide.pptx (B5) and return its path."""
    from pptx import Presentation

    from cpa import config, fsutil, manifest
    from cpa.pptx import lint, notes
    from cpa.workflows import app_pnl

    ws = ws or config.workspace()
    content = _slide_content(position_id, ws)
    prs = Presentation()
    _render_committee_slide(prs, content)
    out_dir = ws / "outbox" / "app" / content.cycle / position_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / SLIDE_NAME
    from cpa.pptx import brand

    brand.style_generated_deck(prs)
    fsutil.atomic_write(path, lambda tmp: prs.save(str(tmp)))
    notes.write_notes(path, [notes.Slide(title=_slide_title(content), points=[content.business_need],
                                         flagged_metrics=list(content.flagged_labels))], AUDIENCE)
    issues = lint.lint_deck(path, audience=AUDIENCE)
    if issues:
        raise LintFailed(f"{position_id}: generated {SLIDE_NAME} failed its own format lint: "
                         + "; ".join(f"{i.code} {i.location}" for i in issues))
    stage = _stage(ws, position_id)
    manifest.write(path, "derived", "APP committee slide", f"position {position_id}", content.as_of,
                  row_count=1, inputs=[content.workbook, stage / SLIDE_INPUTS_NAME, stage / app_pnl.FLAGS_NAME])
    return path


def position(position_id: str) -> Path:
    """guide 9: build the position's committee slide and return its path."""
    return position_detailed(position_id)


def _load_qa_inputs(stage: Path) -> tuple[QaRow, ...]:
    data = _read_json(stage / QA_INPUTS_NAME, "qa")
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list) or not data["questions"]:
        raise QaInputError(f"{manifest_rel(stage / QA_INPUTS_NAME)} must be a JSON object with a non-empty "
                           "'questions' array")
    seen: set[str] = set()
    rows: list[QaRow] = []
    for i, item in enumerate(data["questions"]):
        if not isinstance(item, dict):
            raise QaInputError(f"{QA_INPUTS_NAME} item {i} must be an object")
        qid = str(item.get("question_id") or "")
        if not qid:
            raise QaInputError(f"{QA_INPUTS_NAME} item {i} has no question_id")
        if qid in seen:
            raise QaInputError(f"{QA_INPUTS_NAME}: question_id {qid!r} appears more than once "
                               "(R115: every prior question appears exactly once)")
        seen.add(qid)
        status = str(item.get("status") or "")
        if status not in QA_STATUSES:
            raise QaInputError(f"{QA_INPUTS_NAME}: question_id {qid!r} status {status!r} must be one of "
                               f"{QA_STATUSES} (R211; never inferred, hard rule 15)")
        question = str(item.get("question") or "").strip()
        if not question:
            raise QaInputError(f"{QA_INPUTS_NAME}: question_id {qid!r} has no question text")
        rows.append(QaRow(qid, question, status, str(item.get("summary") or ""),
                          bool(item.get("contradicts_pnl", False)), str(item.get("contradiction_note") or "")))
    return tuple(rows)


def _qa_content(position_id: str, ws: Path) -> QaContent:
    stage = _stage(ws, position_id)
    _, cycle = _resolve_cycle(position_id, ws)
    rows = _load_qa_inputs(stage)
    return QaContent(position_id=position_id, cycle=cycle, rows=rows)


def qa_detailed(position_id: str, *, ws: Path | None = None) -> Path:
    """Build outbox/app/<cycle>/<position>/qa_slide.pptx (B6) and return its path."""
    from pptx import Presentation

    from cpa import config, fsutil, manifest
    from cpa.pptx import lint, notes

    ws = ws or config.workspace()
    content = _qa_content(position_id, ws)
    prs = Presentation()
    _render_qa_slide(prs, content)
    out_dir = ws / "outbox" / "app" / content.cycle / position_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / QA_NAME
    from cpa.pptx import brand

    brand.style_generated_deck(prs)
    fsutil.atomic_write(path, lambda tmp: prs.save(str(tmp)))
    notes.write_notes(path, [notes.Slide(title=f"Returning Position Q&A: {position_id}",
                                         points=[r.question for r in content.rows])], AUDIENCE)
    issues = lint.lint_deck(path, audience=AUDIENCE)
    if issues:
        raise LintFailed(f"{position_id}: generated {QA_NAME} failed its own format lint: "
                         + "; ".join(f"{i.code} {i.location}" for i in issues))
    stage = _stage(ws, position_id)
    manifest.write(path, "derived", "APP returning-position Q&A slide", f"position {position_id}", _today(),
                  row_count=len(content.rows), inputs=[stage / QA_INPUTS_NAME])
    return path


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def qa(position_id: str) -> Path:
    """guide 9: build the position's returning-position Q&A slide and return its path."""
    return qa_detailed(position_id)


# ---------------------------------------------------------------- deck()


def _candidates(ws: Path, cycle: str) -> list[str]:
    from cpa.workflows import app_pnl

    found: set[str] = set()
    out_root = ws / "outbox" / "app" / cycle
    if out_root.is_dir():
        found |= {p.name for p in out_root.iterdir() if p.is_dir()}
    stage_root = ws / "staging" / "app"
    if stage_root.is_dir():
        for p in stage_root.iterdir():
            if not p.is_dir():
                continue
            try:
                inputs = app_pnl.load_inputs(p.name, ws)
            except Exception:
                continue
            if inputs.cycle == cycle:
                found.add(p.name)
    return sorted(found)


def _classify(ws: Path, cycle: str, position_id: str) -> Exclusion | tuple[Path, bool]:
    """None-equivalent: either an Exclusion, or (slide_path, is_returning)."""
    from cpa.workflows import app_pnl

    stage = _stage(ws, position_id)
    _out_dir, pnl_path, failed_path = _pnl_paths(ws, cycle, position_id)
    if not (stage / app_pnl.INPUTS_NAME).is_file():
        return Exclusion(position_id, "NO_INPUTS", f"no {app_pnl.INPUTS_NAME}; the cpa-app-pnl skill writes it "
                         "before this cycle's build")
    try:
        _require_verified_pnl(position_id, pnl_path, failed_path)
    except PnlNotVerified as exc:
        return Exclusion(position_id, "NO_VERIFIED_PNL", str(exc))
    slide_path = _out_dir / SLIDE_NAME
    if not slide_path.is_file():
        return Exclusion(position_id, "NO_SLIDE", "no committee slide; run `python -m cpa app_slides position "
                         f"--position {position_id}`")
    returning = (_out_dir / QA_NAME).is_file()
    return slide_path, returning


def _render_exclusions_md(cycle: str, excluded: Sequence[Exclusion]) -> str:
    lines = [f"# Excluded positions: {cycle}", ""]
    if not excluded:
        lines.append("- none")
    else:
        lines += [f"- {e.position_id} ({e.code}): {e.reason}" for e in excluded]
    return "\n".join(lines) + "\n"


def deck_detailed(cycle: str, *, ws: Path | None = None) -> DeckResult:
    """Build outbox/app/SOM_Review_<cycle>.pptx (B7): agenda, then every included position's committee
    slide (and its qa_slide when returning), page-numbered; every excluded position is listed with the
    reason (R116) in the returned result, the CLI, and a sidecar _exclusions.md."""
    from pptx import Presentation

    from cpa import config, fsutil, manifest
    from cpa.pptx import lint, notes

    ws = ws or config.workspace()
    excluded: list[Exclusion] = []
    included: list[tuple[str, Path, bool]] = []
    for pos in _candidates(ws, cycle):
        result = _classify(ws, cycle, pos)
        if isinstance(result, Exclusion):
            excluded.append(result)
        else:
            slide_path, returning = result
            included.append((pos, slide_path, returning))

    new_ids = tuple(pos for pos, _, returning in included if not returning)
    returning_ids = tuple(pos for pos, _, returning in included if returning)

    prs = Presentation()
    slide_notes: list = [notes.Slide(title="Agenda", points=["New requests", "Returning positions"])]
    _render_agenda_slide(prs, new_ids, returning_ids, cycle)

    for pos, _slide_path, returning in included:
        content = _slide_content(pos, ws)
        _render_committee_slide(prs, content)
        slide_notes.append(notes.Slide(title=_slide_title(content), points=[content.business_need],
                                       flagged_metrics=list(content.flagged_labels)))
        if returning:
            qcontent = _qa_content(pos, ws)
            _render_qa_slide(prs, qcontent)
            slide_notes.append(notes.Slide(title=f"Returning Position Q&A: {pos}",
                                           points=[r.question for r in qcontent.rows]))

    for i, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if shape.name == "page_number":
                shape.text_frame.text = str(i)

    out_path = ws / "outbox" / "app" / DECK_NAME_FMT.format(cycle=fsutil.safe_filename(cycle))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from cpa.pptx import brand

    brand.style_generated_deck(prs)
    fsutil.atomic_write(out_path, lambda tmp: prs.save(str(tmp)))
    notes.write_notes(out_path, slide_notes, AUDIENCE)

    issues = lint.lint_deck(out_path, audience=AUDIENCE, deck_kind="main")
    if issues:
        raise LintFailed(f"deck for {cycle}: generated deck failed its own format lint: "
                         + "; ".join(f"{i.code} {i.location}" for i in issues))

    exclusions_path = out_path.with_name(EXCLUSIONS_NAME_FMT.format(cycle=fsutil.safe_filename(cycle)))
    fsutil.atomic_write(exclusions_path,
                        lambda tmp: tmp.write_text(_render_exclusions_md(cycle, excluded), encoding="utf-8",
                                                   newline="\n"))

    manifest.write(out_path, "derived", "SOM Review Committee deck", f"cycle {cycle}", cycle,
                  row_count=len(list(prs.slides)), inputs=[p for _, p, _ in included])
    return DeckResult(path=out_path, new=new_ids, returning=returning_ids, excluded=tuple(excluded),
                      exclusions_path=exclusions_path)


def deck(cycle: str) -> Path:
    """guide 9: assemble the SOM Review Committee deck for a cycle and return its path."""
    return deck_detailed(cycle).path


# ---------------------------------------------------------------- readiness (guide 7.2, D19)


def _slide_ready_extra(ws: Path, key: str) -> list[Path] | None:
    """cpa-app-slide is ready when slide_inputs.json exists and the position's PnL is verified
    (mirrors app_pnl's own `_ready_extra` pattern)."""
    try:
        _inputs, cycle = _resolve_cycle(key, ws)
        _out_dir, pnl_path, failed_path = _pnl_paths(ws, cycle, key)
        _require_verified_pnl(key, pnl_path, failed_path)
        return [pnl_path]
    except Exception:  # a readiness probe never raises: anything unreadable is simply not ready
        return None


READINESS_RULES = (
    state.Rule(WORKFLOW_SLIDE, ("staging/app/{key}/" + SLIDE_INPUTS_NAME,), "folder", extra=_slide_ready_extra),
    state.Rule(WORKFLOW_DECK, ("outbox/app/{key}/*/" + SLIDE_NAME,), "folder"),
)


# ---------------------------------------------------------------- CLI


def _stoppers() -> tuple:
    from cpa import config, manifest
    from cpa.pptx import lint, notes
    from cpa.workflows import app_pnl

    return (AppSlidesError, app_pnl.AppPnlError, config.ConfigError, manifest.ManifestError, lint.LintError,
           notes.NotesError, FileNotFoundError, PermissionError)


def _stop(exc: BaseException) -> int:
    print(f"stopped: {exc}", file=sys.stderr)
    return EXIT_STOPPED


def _cmd_position(args) -> int:
    try:
        path = position(args.position)
    except _stoppers() as exc:
        return _stop(exc)
    print(path)
    return EXIT_OK


def _cmd_qa(args) -> int:
    try:
        path = qa(args.position)
    except _stoppers() as exc:
        return _stop(exc)
    print(path)
    return EXIT_OK


def _cmd_deck(args) -> int:
    try:
        result = deck_detailed(args.cycle)
    except _stoppers() as exc:
        return _stop(exc)
    if args.json:
        print(json.dumps(result.to_json(), indent=2, ensure_ascii=False))
    else:
        print(result.path)
        print(f"new: {', '.join(result.new) or 'none'}")
        print(f"returning: {', '.join(result.returning) or 'none'}")
        for e in result.excluded:
            print(f"excluded {e.position_id} ({e.code}): {e.reason}")
    return EXIT_OK if not result.excluded else EXIT_ISSUES


def register(subparsers) -> None:
    """Register `app_slides position|qa|deck`. Import-cheap (D03)."""
    top = subparsers.add_parser("app_slides", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    p = sub.add_parser("position", help="Build the committee slide for one position (B5).",
                       description="Reads staging/app/<pos>/slide_inputs.json, pnl_inputs.json and pnl_flags.json, "
                                   "plus the position's verified PnL.xlsx manifest. Exit 0 written, 2 stopped.")
    p.add_argument("--position", required=True, help="Position id (the staging/app/<position> folder name).")
    p.set_defaults(func=_cmd_position)

    p = sub.add_parser("qa", help="Build the returning-position Q&A slide for one position (B6).",
                       description="Reads staging/app/<pos>/qa_inputs.json. Exit 0 written, 2 stopped.")
    p.add_argument("--position", required=True, help="Position id (the staging/app/<position> folder name).")
    p.set_defaults(func=_cmd_qa)

    p = sub.add_parser("deck", help="Assemble the SOM Review Committee deck for a cycle (B7).",
                       description="Copies in every position with a verified P&L and a built slide.pptx; lists "
                                   "every excluded position with its reason. Exit 0 no exclusions, 1 some "
                                   "excluded, 2 stopped.")
    p.add_argument("--cycle", required=True, help="SOM cycle date, YYYY-MM-DD.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_deck)
