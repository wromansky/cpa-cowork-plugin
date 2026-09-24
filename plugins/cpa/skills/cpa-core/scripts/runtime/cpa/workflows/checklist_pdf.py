"""Submission checklist PDF (B8): interactive ReportLab AcroForm with live checkboxes and text fields.

Build List B8 (:141-147); R070, R117, R213. FIXTURE — pypdf-verified only until opened in Acrobat and
Edge (D15's her-machine check). ReportLab's `canvas.acroForm` sets `/NeedAppearances true` by default
(docs/research/methods/pdf-forms.md), so every field renders correctly without a baked-in appearance
stream; the form is never flattened.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

OUTPUT_STEM = "APP_Submission_Checklist_v"          # Build List :146
CHECKBOX_ON, CHECKBOX_OFF = "/Yes", "/Off"           # PDF checkbox convention (methods/pdf-forms.md)
PLACEHOLDER_WATERMARK = "DRAFT - placeholder checklist, do not issue"
PAGE_MARGIN = 54
WRAP_WIDTH = 92

__all__ = [
    "OUTPUT_STEM", "CHECKBOX_ON", "CHECKBOX_OFF", "PLACEHOLDER_WATERMARK", "ChecklistPdfError", "PdfBuild",
    "field_names", "next_version", "build", "register",
]


class ChecklistPdfError(RuntimeError):
    """The build was refused or failed; the message names the reason."""


@dataclass(frozen=True)
class PdfBuild:
    path: Path
    version: int
    fields: tuple[str, ...]
    spec_sha256: str
    placeholder: bool

    def to_json(self) -> dict:
        return {"path": str(self.path), "version": self.version, "fields": list(self.fields),
                "spec_sha256": self.spec_sha256, "placeholder": self.placeholder}


def field_names(spec) -> tuple[str, ...]:
    """'<id>_done' (checkbox) for every item, plus '<id>_text' for an `input: text` item, spec order."""
    names: list[str] = []
    for item in spec.items:
        names.append(f"{item.id}_done")
        if item.input == "text":
            names.append(f"{item.id}_text")
    return tuple(names)


def next_version(out_dir: Path) -> int:
    """1 + max N over files matching OUTPUT_STEM<N>.pdf, compared case-insensitively (Windows/OneDrive)."""
    import re

    pattern = re.compile(rf"^{re.escape(OUTPUT_STEM)}(\d+)\.pdf$", re.I)
    best = 0
    if Path(out_dir).is_dir():
        for p in Path(out_dir).iterdir():
            m = pattern.match(p.name)
            if m:
                best = max(best, int(m.group(1)))
    return best + 1


def _wrap(text: str, width: int = WRAP_WIDTH) -> list[str]:
    import textwrap

    lines: list[str] = []
    for para in (text or "").splitlines() or [""]:
        lines.extend(textwrap.wrap(para, width) or [""])
    return lines


def _draw(path: Path, spec, *, version: int, today: date) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    width, height = letter
    margin = PAGE_MARGIN
    c = canvas.Canvas(str(path), pagesize=letter)
    c.acroForm.extras["NeedAppearances"] = "true"  # belt-and-suspenders: ReportLab also bakes a real
    # appearance stream per field (checkboxAP/textfield), but some viewers still trust this flag first
    # (docs/research/methods/pdf-forms.md section 2-3).
    page = [1]

    def footer() -> None:
        c.setFont("Helvetica", 8)
        c.drawString(margin, 24, f"{spec.title} v{version} | {today.isoformat()} | "
                                 f"spec {spec.sha256[:8]} | page {page[0]}")
        if spec.placeholder:
            c.saveState()
            c.setFont("Helvetica-Bold", 36)
            c.setFillGray(0.82)
            c.translate(width / 2, height / 2)
            c.rotate(45)
            c.drawCentredString(0, 0, PLACEHOLDER_WATERMARK)
            c.restoreState()

    def new_page() -> None:
        footer()
        c.showPage()
        page[0] += 1

    y = height - margin
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, spec.title or "APP Submission Checklist")
    y -= 22
    c.setFont("Helvetica", 10)
    for line in _wrap(spec.instructions):
        c.drawString(margin, y, line)
        y -= 13
    y -= 10

    current_section = None
    for item in spec.items:
        if y < margin + 70:
            new_page()
            y = height - margin
            current_section = None
        if item.section != current_section:
            current_section = item.section
            c.setFont("Helvetica-Bold", 12)
            c.drawString(margin, y, current_section)
            y -= 16
            c.setFont("Helvetica", 10)
        c.acroForm.checkbox(name=f"{item.id}_done", tooltip=item.fix, x=margin, y=y - 2, size=12,
                            buttonStyle="check", borderStyle="solid", forceBorder=True, checked=False,
                            fieldFlags="")
        for i, line in enumerate(_wrap(item.text, WRAP_WIDTH - 10)):
            c.drawString(margin + 20, y - i * 12, line)
        y -= 12 * max(1, len(_wrap(item.text, WRAP_WIDTH - 10)))
        if item.input == "text":
            c.acroForm.textfield(name=f"{item.id}_text", tooltip=item.fix, x=margin + 20, y=y - 16,
                                 width=340, height=16, borderStyle="solid", forceBorder=True, fieldFlags="")
            y -= 28
        else:
            y -= 8
    new_page()
    c.save()


def build(spec_path: Path | None = None, *, out_dir: Path | None = None, allow_placeholder: bool = False,
          today: date | None = None) -> PdfBuild:
    """Render `spec_path` (default reference/checklist.yaml) to `<out_dir>/APP_Submission_Checklist_v<N>.pdf`.

    Refuses a placeholder spec unless `allow_placeholder` (never issue a placeholder checklist to a
    department). An existing version file is never overwritten."""
    from cpa import config, fsutil
    from cpa.workflows.app_triage import ChecklistSpecError, load_spec, resolve_spec_path

    try:
        spec = load_spec(resolve_spec_path(spec_path))
    except ChecklistSpecError as exc:
        raise ChecklistPdfError(str(exc)) from exc
    if spec.placeholder and not allow_placeholder:
        raise ChecklistPdfError(
            f"{spec.path} is a placeholder checklist (placeholder: true); pass --allow-placeholder to "
            "build a draft anyway, or replace the items with her real checklist first (NFH-P1-03)"
        )
    out_dir = Path(out_dir) if out_dir is not None else config.workspace() / "templates"
    out_dir.mkdir(parents=True, exist_ok=True)
    version = next_version(out_dir)
    target = out_dir / f"{OUTPUT_STEM}{version}.pdf"
    if target.exists():
        raise ChecklistPdfError(f"{target} already exists; an existing checklist version is never overwritten")
    today = today or date.today()

    def write(tmp: Path) -> None:
        _draw(tmp, spec, version=version, today=today)

    fsutil.atomic_write(target, write)
    return PdfBuild(path=target, version=version, fields=field_names(spec), spec_sha256=spec.sha256,
                    placeholder=spec.placeholder)


# ---------------------------------------------------------------- CLI

EXIT_OK, EXIT_STOPPED = 0, 2


def _cmd_build(args: argparse.Namespace) -> int:
    from cpa import config

    try:
        result = build(args.spec, out_dir=args.out, allow_placeholder=args.allow_placeholder)
    except (ChecklistPdfError, config.ConfigError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return EXIT_STOPPED
    if args.json:
        import json

        print(json.dumps(result.to_json(), indent=2, ensure_ascii=False))
    else:
        print(result.path)
        print(f"{len(result.fields)} field(s)")
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `checklist_pdf build`. Import-cheap (D03)."""
    top = subparsers.add_parser("checklist_pdf", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    p = sub.add_parser("build", help="Render the interactive checklist PDF from reference/checklist.yaml.",
                       description="ReportLab AcroForm: one checkbox per item, plus a text field for "
                                   "input: text items. Refuses a placeholder spec without "
                                   "--allow-placeholder. Exit 0 written, 2 stopped.")
    p.add_argument("--spec", type=Path, default=None, nargs="?",
                   help="checklist.yaml path (default: reference/checklist.yaml).")
    p.add_argument("--out", type=Path, default=None, dest="out", help="Output folder (default: templates/).")
    p.add_argument("--allow-placeholder", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_build)
