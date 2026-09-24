"""APP submission triage (B3): identify, check against the checklist, audit the P&L, classify.

Build List B3 (:101-107). Never edits the submission (R043); never sends mail (R044). `run` produces
`staging/app/<position>/{brief.md,triage.md}` and, when the submission must go back to the department,
a draft return email in `outbox/app/<cycle>/emails/` -- always "DRAFT - not sent", never sent by this
module or anything it imports.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

ITEM_STATUSES = ("PRESENT", "MISSING", "UNCLEAR")
CLASSES = ("COMPLETE", "FIXABLE", "RETURN")
IDENTIFY_FIELDS = ("department", "division", "position_title", "requester")
# R045's six defect classes plus RATE_UNVERIFIED (rule 15: a null assumptions key is a finding, never
# a default). resolution says who can fix it: "analyst" findings stay in triage.md only; "department"
# findings also go in the return email.
FINDING_CODES = ("HARDCODE_IN_FORMULA_CELL", "BROKEN_REFERENCE", "BENCHMARK_ENTERED_BY_DEPARTMENT",
                  "RATE_MISMATCH", "RATE_UNVERIFIED", "STRUCTURE", "SIGN_ERROR")
DEPARTMENT_RESOLUTION_CODES = ("BENCHMARK_ENTERED_BY_DEPARTMENT", "SIGN_ERROR")
RATE_KEYS = ("rates.fringe_jhm_base_pct", "rates.fringe_jhu_clinical_pct", "rates.deans_tax_pct",
             "rates.dom_clinical_tax_pct")  # D04; inventory :407-410

# FIXTURE — confirm against her file: every label/marker constant below is matched casefold-substring
# against her APP P&L v5 and a real submission; this is the swap step referenced in FIXTURE_SWAP.md.
RATE_LABELS: dict[str, tuple[str, ...]] = {
    "rates.fringe_jhm_base_pct": ("jhm", "fringe"),
    "rates.fringe_jhu_clinical_pct": ("jhu", "fringe"),
    "rates.deans_tax_pct": ("dean",),
    "rates.dom_clinical_tax_pct": ("dom", "tax"),
}
IDENTIFY_LABELS: dict[str, tuple[str, ...]] = {
    "department": ("department",), "division": ("division",),
    "position_title": ("position title", "position"), "requester": ("requester", "submitted by"),
}
BENCHMARK_MARKERS = ("benchmark", "sullivancotter", "percentile")   # inventory :297, :327
CALCULATED_ROW_MARKERS = ("jhu contribution margin", "division surplus")   # inventory :415-416
REVENUE_MARKERS = ("revenue", "collections", "charges")
YEAR_HEADER = re.compile(r"^(year|yr)\s*\d+$", re.I)   # "three years only", inventory :327
PNL_SUFFIXES = (".xlsx", ".xlsm")
HEADER_SEARCH_ROWS = 15
ROW_SEARCH_LIMIT = 60
COLUMN_SEARCH_LIMIT = 20

__all__ = [
    "ITEM_STATUSES", "CLASSES", "IDENTIFY_FIELDS", "FINDING_CODES", "TriageError", "ChecklistSpecError",
    "AuditError", "IdentificationIncomplete", "Located", "Identification", "ChecklistItem", "ChecklistSpec",
    "ItemResult", "Finding", "TriageResult", "load_spec", "resolve_spec_path", "find_pnl", "extract_text",
    "identify", "check_items", "audit_pnl", "classify", "email_gaps", "render_triage_md", "render_email_md",
    "position_id_for", "run", "register",
]


class TriageError(RuntimeError):
    """Base for triage failures that are not findings."""


class ChecklistSpecError(TriageError):
    """checklist.yaml is unreadable or invalid; names the file and the item id."""


class AuditError(TriageError):
    """The P&L cannot be audited (wrong suffix, too large, unreadable); names the file and why."""


class IdentificationIncomplete(TriageError):
    """A value `run` needs (the received date) is unknown and was not supplied; nothing is written."""


@dataclass(frozen=True)
class Located:
    """One value with where it came from: a source file name and a location within it."""

    value: str
    source: str
    location: str

    def to_json(self) -> dict:
        return {"value": self.value, "source": self.source, "location": self.location}


@dataclass(frozen=True)
class Identification:
    """The four IDENTIFY_FIELDS, each `Located` or None, plus any problems (missing/conflict/crosswalk)."""

    fields: dict[str, Located | None]
    department_canonical: str | None
    problems: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {
            "fields": {k: (v.to_json() if v else None) for k, v in self.fields.items()},
            "department_canonical": self.department_canonical,
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class ChecklistItem:
    id: str
    section: str
    text: str
    input: str
    satisfied_by: dict
    fix: str
    source: str


@dataclass(frozen=True)
class ChecklistSpec:
    path: Path
    title: str
    instructions: str
    placeholder: bool
    items: tuple[ChecklistItem, ...]
    sha256: str


@dataclass(frozen=True)
class ItemResult:
    item_id: str
    status: str
    evidence: tuple[Located, ...] = ()
    reason: str = ""

    def to_json(self) -> dict:
        return {"item_id": self.item_id, "status": self.status, "reason": self.reason,
                "evidence": [e.to_json() for e in self.evidence]}


@dataclass(frozen=True)
class Finding:
    """One audit_pnl defect. `cell` is None only for a workbook- or sheet-level STRUCTURE finding."""

    code: str
    sheet: str
    cell: str | None
    found: str
    expected: str
    fix: str
    resolution: str  # "analyst" or "department"

    def to_json(self) -> dict:
        return {"code": self.code, "sheet": self.sheet, "cell": self.cell, "found": self.found,
                "expected": self.expected, "fix": self.fix, "resolution": self.resolution}


@dataclass
class TriageResult:
    folder: Path
    position_id: str
    identification: Identification
    items: list[ItemResult]
    findings: list[Finding]
    classification: str
    questions: bool
    placeholder_spec: bool
    outputs: dict[str, Path] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "folder": str(self.folder), "position_id": self.position_id,
            "identification": self.identification.to_json(),
            "items": [i.to_json() for i in self.items], "findings": [f.to_json() for f in self.findings],
            "classification": self.classification, "questions": self.questions,
            "placeholder_spec": self.placeholder_spec,
            "outputs": {k: str(v) for k, v in self.outputs.items()},
        }


# ---------------------------------------------------------------- checklist spec


def resolve_spec_path(p: Path | None) -> Path:
    """None -> reference/checklist.yaml (workspace copy if present, else the shipped one)."""
    from cpa import config

    if p is not None:
        return Path(p)
    return config.reference_file("checklist.yaml")


def load_spec(path: Path) -> ChecklistSpec:
    """safe_load(utf-8-sig); validates ids, `input`, `satisfied_by.kind`, and R046 (no benchmark text field)."""
    import hashlib

    import yaml

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ChecklistSpecError(f"checklist spec not found: {path}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ChecklistSpecError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or not data.get("items"):
        raise ChecklistSpecError(f"{path} has no items")
    seen: set[str] = set()
    items = []
    for raw in data["items"]:
        item_id = str(raw.get("id", ""))
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", item_id):
            raise ChecklistSpecError(f"{path}: item id {item_id!r} must match [a-z][a-z0-9_]{{0,40}}")
        if item_id in seen:
            raise ChecklistSpecError(f"{path}: item id {item_id!r} is duplicated")
        seen.add(item_id)
        input_kind = raw.get("input")
        if input_kind not in ("text", "checkbox"):
            raise ChecklistSpecError(f"{path}: item {item_id!r} has input {input_kind!r}, expected text or checkbox")
        satisfied_by = raw.get("satisfied_by") or {}
        if satisfied_by.get("kind") not in ("identify", "pnl", "text", "audit"):
            raise ChecklistSpecError(f"{path}: item {item_id!r} has an unknown satisfied_by.kind")
        text_value = str(raw.get("text", ""))
        fix = str(raw.get("fix", ""))
        if not fix:
            raise ChecklistSpecError(f"{path}: item {item_id!r} has no fix sentence")
        if input_kind == "text" and any(
            m in item_id.casefold() or m in text_value.casefold() for m in BENCHMARK_MARKERS
        ):
            raise ChecklistSpecError(
                f"{path}: item {item_id!r} is a text field naming a benchmark; R046 never gives the "
                "department a benchmark entry cell -- make it a checkbox attestation instead"
            )
        items.append(ChecklistItem(item_id, str(raw.get("section", "")), text_value, input_kind,
                                    satisfied_by, fix, str(raw.get("source", ""))))
    return ChecklistSpec(path=path, title=str(data.get("title", "")), instructions=str(data.get("instructions", "")),
                         placeholder=bool(data.get("placeholder", False)), items=tuple(items),
                         sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


# ---------------------------------------------------------------- reading a submission


def find_pnl(folder: Path) -> list[Path]:
    """Workbooks directly in `folder` with a sheet whose casefold title contains a PNL_TAB_MARKERS entry.

    Sheet titles come from `bigxlsx.sheet_names` (U05) -- never `load_workbook` -- so this runs before
    any `is_large` gate and never loads a >15 MB workbook whole (hard rule 11)."""
    from cpa import bigxlsx
    from cpa.verify import PNL_TAB_MARKERS

    found = []
    for p in sorted(folder.iterdir()) if folder.is_dir() else []:
        if not p.is_file() or p.suffix.casefold() not in PNL_SUFFIXES:
            continue
        try:
            names = bigxlsx.sheet_names(p)
        except bigxlsx.BigXlsxError:
            continue
        if any(marker in name.casefold() for name in names for marker in PNL_TAB_MARKERS):
            found.append(p)
    return found


def extract_text(path: Path) -> list[tuple[str, str]] | None:
    """(location, text) pairs: page (.pdf), paragraph (.docx), line (.txt/.md), body line (.eml).

    None when the file is unreadable (encrypted, unsupported, corrupt) -- callers report UNCLEAR for
    a text-kind checklist item, never MISSING (a MISSING claim requires knowing the content is absent)."""
    suffix = path.suffix.casefold()
    try:
        if suffix == ".pdf":
            import pypdf

            reader = pypdf.PdfReader(str(path))
            return [(f"page {i + 1}", page.extract_text() or "") for i, page in enumerate(reader.pages)]
        if suffix == ".docx":
            import zipfile
            from xml.etree import ElementTree

            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            with zipfile.ZipFile(path) as z:
                root = ElementTree.fromstring(z.read("word/document.xml"))
            out = []
            for i, p in enumerate(root.iter(f"{{{ns['w']}}}p"), start=1):
                runs = "".join(t.text or "" for t in p.iter(f"{{{ns['w']}}}t"))
                out.append((f"paragraph {i}", runs))
            return out
        if suffix in (".txt", ".md"):
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return [(f"line {i + 1}", line) for i, line in enumerate(lines)]
        if suffix == ".eml":
            from email import policy
            from email.parser import BytesParser

            with path.open("rb") as fh:
                msg = BytesParser(policy=policy.default).parse(fh)
            body = msg.get_body(preferencelist=("plain",))
            text = body.get_content() if body is not None else ""
            return [(f"body line {i + 1}", line) for i, line in enumerate(text.splitlines())]
    except Exception:  # noqa: BLE001 - any parse failure means "unreadable", reported UNCLEAR by the caller
        return None
    return None


def _submission_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []


def _pnl_label_values(pnl: Path) -> dict[str, Located]:
    """First non-blank cell to the right of each IDENTIFY_LABELS match, scanned across the sheet's top rows."""
    import openpyxl

    from cpa.verify import PNL_TAB_MARKERS

    wb = openpyxl.load_workbook(str(pnl), read_only=True, data_only=True, keep_links=False)
    out: dict[str, Located] = {}
    try:
        tab = next((ws for ws in wb.worksheets if any(m in ws.title.casefold() for m in PNL_TAB_MARKERS)), None)
        if tab is None:
            return out
        for row in tab.iter_rows(min_row=1, max_row=HEADER_SEARCH_ROWS):
            for cell in row:
                text = str(cell.value or "").strip().casefold()
                if not text:
                    continue
                for field_name, labels in IDENTIFY_LABELS.items():
                    if field_name in out:
                        continue
                    if any(text.startswith(label) for label in labels):
                        right_cell = tab.cell(row=cell.row, column=cell.column + 1)
                        if right_cell.value not in (None, ""):
                            out[field_name] = Located(str(right_cell.value).strip(), pnl.name,
                                                      f"{tab.title}!{right_cell.coordinate}")
        return out
    finally:
        wb.close()


def _document_label_values(folder: Path) -> dict[str, list[Located]]:
    """Every "Label: value" hit per field, across every document -- callers dedupe/detect conflicts."""
    out: dict[str, list[Located]] = {name: [] for name in IDENTIFY_FIELDS}
    for path in _submission_files(folder):
        if path.suffix.casefold() in PNL_SUFFIXES:
            continue
        pairs = extract_text(path)
        if not pairs:
            continue
        for location, text in pairs:
            stripped = text.strip()
            if ":" not in stripped:
                continue
            label, _, value = stripped.partition(":")
            label, value = label.strip().casefold(), value.strip()
            if not value:
                continue
            for field_name, labels in IDENTIFY_LABELS.items():
                if label in labels:
                    out[field_name].append(Located(value, path.name, location))
    return out


def _load_crosswalk(ws_root: Path | None) -> dict[str, str] | None:
    """reference/dept_crosswalk.csv (U03's shape) when it exists; None means "no crosswalk to check against".

    U03 (cpa.crosswalk) is not built yet, so this reads the CSV directly rather than importing an
    unbuilt module; tighten to `cpa.crosswalk.load` once U03 lands."""
    import csv

    from cpa import config

    candidates = []
    if ws_root is not None:
        candidates.append(ws_root / "reference" / "dept_crosswalk.csv")
    try:
        candidates.append(config.reference_file("dept_crosswalk.csv"))
    except config.MissingReference:
        pass
    for path in candidates:
        if path.is_file():
            with path.open(encoding="utf-8-sig", newline="") as fh:
                return {row["raw_label"].strip().casefold(): row["canonical_department"]
                        for row in csv.DictReader(fh)}
    return None


def identify(folder: Path, *, overrides: Mapping[str, str] | None = None,
             ws_root: Path | None = None) -> Identification:
    """Sources in order per field: `overrides` (wins outright, no conflict check), P&L label cells,
    then "Label: value" lines in the submission's documents. Two different values from the non-override
    sources is a conflict; department is passed through `reference/dept_crosswalk.csv` when present
    (hard rule 10)."""
    overrides = overrides or {}
    pnl_candidates = find_pnl(folder)
    pnl_values = _pnl_label_values(pnl_candidates[0]) if len(pnl_candidates) == 1 else {}
    doc_values = _document_label_values(folder)

    fields: dict[str, Located | None] = {}
    problems: list[str] = []
    for name in IDENTIFY_FIELDS:
        if overrides.get(name):
            fields[name] = Located(str(overrides[name]), "override", f"--{name.replace('_', '-')}")
            continue
        candidates = ([pnl_values[name]] if name in pnl_values else []) + doc_values.get(name, [])
        distinct = {c.value.strip().casefold(): c for c in candidates}
        if not distinct:
            fields[name] = None
            problems.append(f"missing {name}")
        elif len(distinct) == 1:
            fields[name] = next(iter(distinct.values()))
        else:
            fields[name] = None
            a, b = list(distinct.values())[:2]
            problems.append(f"conflict {name}: {a.value!r} ({a.source} {a.location}) "
                            f"vs {b.value!r} ({b.source} {b.location})")

    department_canonical = None
    dept = fields.get("department")
    if dept is not None:
        crosswalk = _load_crosswalk(ws_root)
        if crosswalk is None:
            department_canonical = dept.value  # no crosswalk file yet (U03 unbuilt): pass through
        else:
            hit = crosswalk.get(dept.value.strip().casefold())
            if hit is None:
                problems.append(f'department "{dept.value}" not in the crosswalk')
            else:
                department_canonical = hit
    return Identification(fields=fields, department_canonical=department_canonical, problems=tuple(problems))


# ---------------------------------------------------------------- checklist items


def _has_conflict(problems: Sequence[str], field_name: str) -> str | None:
    prefix = f"conflict {field_name}:"
    return next((p for p in problems if p.startswith(prefix)), None)


def check_items(folder: Path, spec: ChecklistSpec, *, ident: Identification,
                findings: Sequence[Finding], pnl_candidates: Sequence[Path]) -> list[ItemResult]:
    """One ItemResult per spec item, in spec order (R110: every item gets a status)."""
    results: list[ItemResult] = []
    for item in spec.items:
        kind = item.satisfied_by.get("kind")
        if kind == "identify":
            fname = item.satisfied_by["field"]
            conflict = _has_conflict(ident.problems, fname)
            loc = ident.fields.get(fname)
            if conflict:
                results.append(ItemResult(item.id, "UNCLEAR", reason=conflict))
            elif loc is not None:
                results.append(ItemResult(item.id, "PRESENT", evidence=(loc,)))
            else:
                results.append(ItemResult(item.id, "MISSING", reason=f"{fname} not found in the submission"))
        elif kind == "pnl":
            if len(pnl_candidates) == 1:
                loc = Located(pnl_candidates[0].name, pnl_candidates[0].name, "P&L tab")
                results.append(ItemResult(item.id, "PRESENT", evidence=(loc,)))
            elif not pnl_candidates:
                results.append(ItemResult(item.id, "MISSING", reason="no workbook with a P&L tab in the folder"))
            else:
                names = ", ".join(p.name for p in pnl_candidates)
                results.append(ItemResult(item.id, "UNCLEAR", reason=f"more than one candidate: {names} (pass --pnl)"))
        elif kind == "text":
            pattern = str(item.satisfied_by.get("pattern", "")).casefold()
            hit, any_unreadable = None, False
            for path in _submission_files(folder):
                if path.suffix.casefold() in PNL_SUFFIXES:
                    continue
                pairs = extract_text(path)
                if pairs is None:
                    any_unreadable = True
                    continue
                for location, text in pairs:
                    if pattern in text.casefold():
                        hit = Located(pattern, path.name, location)
                        break
                if hit:
                    break
            if hit:
                results.append(ItemResult(item.id, "PRESENT", evidence=(hit,)))
            elif any_unreadable:
                results.append(ItemResult(item.id, "UNCLEAR", reason="a document could not be read"))
            else:
                results.append(ItemResult(item.id, "MISSING", reason=f'"{item.satisfied_by.get("pattern")}" not found'))
        elif kind == "audit":
            codes = set(item.satisfied_by.get("codes") or ())
            if not pnl_candidates:
                results.append(ItemResult(item.id, "UNCLEAR", reason="no P&L to audit"))
                continue
            hits = [f for f in findings if f.code in codes]
            if hits:
                evidence = tuple(Located(h.found, pnl_candidates[0].name, f"{h.sheet}!{h.cell}") for h in hits)
                results.append(ItemResult(item.id, "MISSING", evidence=evidence,
                                          reason="; ".join(f"{h.sheet}!{h.cell}: {h.found}" for h in hits)))
            else:
                results.append(ItemResult(item.id, "PRESENT"))
        else:  # pragma: no cover - load_spec already refuses any other kind
            results.append(ItemResult(item.id, "UNCLEAR", reason=f"unknown satisfied_by.kind {kind!r}"))
    return results


# ---------------------------------------------------------------- P&L audit


def _resolution(code: str) -> str:
    return "department" if code in DEPARTMENT_RESOLUTION_CODES else "analyst"


def _finding(code: str, sheet: str, cell: str | None, found: str, expected: str, fix: str) -> Finding:
    return Finding(code, sheet, cell, found, expected, fix, _resolution(code))


def _year_header(ws) -> tuple[int | None, list[int]]:
    """(header_row, year_columns) -- the row in the first HEADER_SEARCH_ROWS with the most YEAR_HEADER hits."""
    best_row, best_cols = None, []
    for row in ws.iter_rows(min_row=1, max_row=min(HEADER_SEARCH_ROWS, ws.max_row or 1),
                            max_col=min(COLUMN_SEARCH_LIMIT, ws.max_column or 1)):
        cols = [c.column for c in row if isinstance(c.value, str) and YEAR_HEADER.match(c.value.strip())]
        if len(cols) > len(best_cols):
            best_row, best_cols = row[0].row, cols
    return best_row, best_cols


def _audit_pnl_tab(ws, findings: list[Finding]) -> None:
    header_row, year_cols = _year_header(ws)
    if header_row is None or len(year_cols) != 3:
        found = "0" if header_row is None else str(len(year_cols))
        col_range = f"{ws.cell(1, min(year_cols)).coordinate}:{ws.cell(1, max(year_cols)).coordinate}" if year_cols else "?"
        findings.append(_finding("STRUCTURE", ws.title, None, f"{found} year column(s)", "3 year columns",
                                 "The P&L must have exactly three year columns (Year 1, Year 2, Year 3)."))
        return
    label_col = min(year_cols) - 1
    if label_col < 1:
        return
    max_row = min(ROW_SEARCH_LIMIT, ws.max_row or header_row)
    for row in ws.iter_rows(min_row=header_row + 1, max_row=max_row):
        label_cell = row[label_col - 1] if len(row) >= label_col else None
        label = str(label_cell.value).strip() if label_cell and label_cell.value not in (None, "") else ""
        if not label:
            continue
        low = label.casefold()
        cells = [c for c in row if c.column in year_cols]
        is_formula = [c.data_type == "f" for c in cells]
        values = [c.value for c in cells]

        for cell, formula in zip(cells, is_formula):
            if formula and isinstance(cell.value, str) and "#REF!" in cell.value:
                findings.append(_finding("BROKEN_REFERENCE", ws.title, cell.coordinate, cell.value,
                                         "a valid reference",
                                         "Rebuild this formula without the broken reference."))

        is_calculated = any(m in low for m in CALCULATED_ROW_MARKERS)
        if is_calculated:
            bad = [c for c, f in zip(cells, is_formula) if not f and c.value not in (None, "")]
        elif any(is_formula) and not all(is_formula):
            bad = [c for c, f in zip(cells, is_formula) if not f]
        else:
            bad = []
        for cell in bad:
            findings.append(_finding("HARDCODE_IN_FORMULA_CELL", ws.title, cell.coordinate, str(cell.value),
                                     "a formula, consistent with the row's other year cells",
                                     "Replace the hard-coded number with the row's formula."))

        if any(m in low for m in BENCHMARK_MARKERS):
            for cell in cells:
                if cell.value not in (None, ""):
                    findings.append(_finding("BENCHMARK_ENTERED_BY_DEPARTMENT", ws.title, cell.coordinate,
                                             str(cell.value), "blank (the analyst fills this in during the rebuild)",
                                             "Remove this benchmark figure; never enter your own benchmark."))

        numbers = [(c, v) for c, v, f in zip(cells, values, is_formula) if not f and isinstance(v, (int, float))]
        if any(m in low for m in REVENUE_MARKERS):
            for cell, v in numbers:
                if v < 0:
                    findings.append(_finding("SIGN_ERROR", ws.title, cell.coordinate, str(v), "a non-negative amount",
                                             "Check the intended sign of this figure with the department."))
        signs = {1 if v > 0 else -1 for _, v in numbers if v != 0}
        if len(signs) > 1:
            for cell, v in numbers:
                findings.append(_finding("SIGN_ERROR", ws.title, cell.coordinate, str(v),
                                         "a consistent sign across the row's year cells",
                                         "Check the intended sign of this figure with the department."))


def _audit_rates(wb, findings: list[Finding]) -> None:
    from cpa import config

    sheets = [ws for ws in wb.worksheets if ws.title.strip().casefold() == "assumptions"]
    if len(sheets) != 1:
        findings.append(_finding("STRUCTURE", "Assumptions", None, f"{len(sheets)} Assumptions sheet(s)",
                                 "exactly 1 Assumptions sheet",
                                 "The workbook must have exactly one sheet named Assumptions."))
        return
    ws = sheets[0]
    rows = {}
    for row in ws.iter_rows(min_row=1, max_row=min(ROW_SEARCH_LIMIT, ws.max_row or 1), max_col=2):
        if row[0].value:
            rows[str(row[0].value).strip().casefold()] = row[1] if len(row) > 1 else None
    for key in RATE_KEYS:
        labels = RATE_LABELS[key]
        cell = next((c for text, c in rows.items() if all(m in text for m in labels)), None)
        if cell is None:
            findings.append(_finding("STRUCTURE", ws.title, None, "row not found",
                                     f"a row labelled like {' '.join(labels)}",
                                     "Add the missing rate row to the Assumptions sheet."))
            continue
        try:
            expected = config.assumption(key)
        except config.MissingAssumption as exc:
            findings.append(_finding("RATE_UNVERIFIED", ws.title, cell.coordinate, "not yet confirmed",
                                     f"a confirmed value for {key}", str(exc)))
            continue
        value = cell.value
        if not isinstance(value, (int, float)):
            findings.append(_finding("STRUCTURE", ws.title, cell.coordinate, repr(value), "a numeric rate",
                                     "Enter the rate as a number."))
            continue
        stored = value * 100 if (cell.number_format and "%" in cell.number_format) else value
        if abs(stored - float(expected)) > 1e-6:
            findings.append(_finding("RATE_MISMATCH", ws.title, cell.coordinate, f"{stored:g}", f"{expected:g}",
                                     f"Set this rate to {expected:g}, matching assumptions.yaml ({key})."))


def audit_pnl(pnl: Path) -> list[Finding]:
    """R045: hard-coded formula cells, broken references, department-entered benchmark cells, rate
    mismatches (vs assumptions.yaml), three-year structure violations, sign errors."""
    from cpa import bigxlsx

    pnl = Path(pnl)
    if pnl.suffix.casefold() not in PNL_SUFFIXES:
        raise AuditError(f"{pnl.name}: audit_pnl reads .xlsx/.xlsm only")
    if bigxlsx.is_large(pnl):
        raise AuditError(f"{pnl.name} is over 15 MB; streamed audit is not implemented (hard rule 11)")
    import openpyxl

    from cpa.verify import PNL_TAB_MARKERS

    wb = openpyxl.load_workbook(str(pnl), data_only=False, keep_links=False)
    try:
        findings: list[Finding] = []
        pnl_tabs = [ws for ws in wb.worksheets if any(m in ws.title.casefold() for m in PNL_TAB_MARKERS)]
        if not pnl_tabs:
            findings.append(_finding("STRUCTURE", "", None, "0 P&L tabs", "1 P&L tab",
                                     "Name the P&L tab so its title contains \"P&L\"."))
        else:
            for ws in pnl_tabs:
                _audit_pnl_tab(ws, findings)
        _audit_rates(wb, findings)
        return findings
    finally:
        wb.close()


# ---------------------------------------------------------------- classify, render


def classify(items: Sequence[ItemResult], findings: Sequence[Finding]) -> tuple[str, bool]:
    """RETURN: any MISSING item or any department-resolution finding. FIXABLE: else any UNCLEAR item or
    any finding. COMPLETE: all PRESENT, no findings. questions: any UNCLEAR item or RATE_UNVERIFIED."""
    department_findings = [f for f in findings if f.resolution == "department"]
    if any(i.status == "MISSING" for i in items) or department_findings:
        result = "RETURN"
    elif any(i.status == "UNCLEAR" for i in items) or findings:
        result = "FIXABLE"
    else:
        result = "COMPLETE"
    questions = any(i.status == "UNCLEAR" for i in items) or any(f.code == "RATE_UNVERIFIED" for f in findings)
    return result, questions


def email_gaps(result: TriageResult) -> list[dict]:
    """What the return email names: MISSING/UNCLEAR items and department-resolution findings."""
    by_id = {i.item_id: i for i in result.items}
    spec_items = {i.item_id: i for i in result.items}  # placeholder for lookup symmetry
    gaps = []
    for item in result.items:
        if item.status in ("MISSING", "UNCLEAR"):
            gaps.append({"what": item.item_id, "where": item.item_id, "reason": item.reason})
    for f in result.findings:
        if f.resolution == "department":
            gaps.append({"what": f.code, "where": f"{f.sheet}!{f.cell}" if f.cell else f.sheet,
                        "reason": f.fix})
    return gaps


def _gap_lines(result: TriageResult, spec_by_id: dict[str, ChecklistItem]) -> list[dict]:
    """email_gaps augmented with the checklist item's own text/fix, for rendering.

    A checklist item of kind "audit" is skipped when a department-resolution finding with one of its
    codes is already listed below -- the finding already names the exact cell, so the item would only
    repeat it in vaguer words (R188: one clear step per gap, not two overlapping ones)."""
    department_codes = {f.code for f in result.findings if f.resolution == "department"}
    out = []
    for item in result.items:
        if item.status not in ("MISSING", "UNCLEAR"):
            continue
        spec_item = spec_by_id.get(item.item_id)
        if spec_item and spec_item.satisfied_by.get("kind") == "audit" and \
                set(spec_item.satisfied_by.get("codes") or ()) & department_codes:
            continue
        out.append({
            "what": spec_item.text if spec_item else item.item_id,
            "where": f"{spec_item.section}: {spec_item.text}" if spec_item else item.item_id,
            "how": spec_item.fix if spec_item else "Contact the analyst.",
        })
    for f in result.findings:
        if f.resolution != "department":
            continue
        out.append({"what": f"{f.code.replace('_', ' ').lower()}",
                    "where": f"{f.sheet}!{f.cell}" if f.cell else f.sheet, "how": f.fix})
    return out


def render_triage_md(result: TriageResult, spec: ChecklistSpec) -> str:
    lines = [f"# APP submission triage: {result.position_id}", "", f"Folder: `{result.folder.name}`",
            f"Classification: **{result.classification}**"
            + ("  (asks the analyst)" if result.questions else ""), ""]
    if result.placeholder_spec:
        lines += ["> PLACEHOLDER CHECKLIST: this checklist is not hers yet (see reference/checklist.yaml). "
                 "The classification above is provisional.", ""]
    lines.append("## Identification")
    for name in IDENTIFY_FIELDS:
        loc = result.identification.fields.get(name)
        lines.append(f"- {name}: " + (f"{loc.value} ({loc.source}, {loc.location})" if loc else "not found"))
    if result.identification.problems:
        lines.append("- problems: " + "; ".join(result.identification.problems))
    lines += ["", "## Checklist"]
    spec_by_id = {i.id: i for i in spec.items}
    for item in result.items:
        text = spec_by_id[item.item_id].text if item.item_id in spec_by_id else item.item_id
        lines.append(f"- [{item.status}] {text}" + (f" -- {item.reason}" if item.reason else ""))
    lines += ["", "## P&L findings"]
    if not result.findings:
        lines.append("- none")
    for f in result.findings:
        where = f"{f.sheet}!{f.cell}" if f.cell else (f.sheet or "workbook")
        lines.append(f"- {f.code} at {where} ({f.resolution}): found {f.found}, expected {f.expected}. {f.fix}")
    return "\n".join(lines) + "\n"


def render_email_md(result: TriageResult, spec: ChecklistSpec) -> str:
    """guide 497. Plain words, no finding codes, one numbered step per gap (R188/R212)."""
    spec_by_id = {i.id: i for i in spec.items}
    dept = result.identification.department_canonical or result.identification.fields.get("department")
    dept_name = dept.value if isinstance(dept, Located) else (dept or "the department")
    lines = ["DRAFT - not sent. Review, then send from Outlook yourself.", ""]
    if result.placeholder_spec:
        lines += ["This checklist is a placeholder until the analyst updates it; some items below may not "
                 "apply once the real checklist is in place.", ""]
    lines.append(f"Subject: APP submission for {result.position_id} -- a few things we need")
    lines += ["", f"Hi {dept_name} team,", "",
              "Thanks for the submission. Before we can bring this forward, we need a few things:", ""]
    for i, gap in enumerate(_gap_lines(result, spec_by_id), start=1):
        lines += [f"{i}. What is missing or wrong: {gap['what']}", f"   Where it goes: {gap['where']}",
                  f"   What a correct entry looks like: {gap['how']}", ""]
    lines += ["Once these are updated, please resend the submission.", "", "Thank you,", "CPA team"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- run


def position_id_for(folder: Path, override: str | None = None) -> str:
    from cpa import fsutil

    if override:
        name = override
    else:
        name = re.sub(r"_\d{4}-\d{2}-\d{2}$", "", folder.name)
    try:
        fsutil.safe_filename(name)
    except fsutil.UnsafeFilename as exc:
        raise TriageError(f"{name!r} is not a usable position id ({exc}); pass --position") from exc
    return name


def run(folder: Path, *, cycle: date, spec: Path | None = None, pnl: Path | None = None,
        position: str | None = None, overrides: Mapping[str, str] | None = None,
        received: date | None = None, root: Path | None = None) -> TriageResult:
    """Identify, audit, check the checklist, classify, and write brief.md/triage.md (and a return
    email when needed). `received` is required -- there is no landed sidecar to source it from yet, and
    today's date is never substituted (fabricated provenance, rule 15)."""
    from cpa import config, manifest

    if received is None:
        raise IdentificationIncomplete("received date unknown; pass --received YYYY-MM-DD")
    folder = Path(folder)
    if not folder.is_dir():
        raise TriageError(f"submission folder not found: {folder}")
    spec_obj = load_spec(resolve_spec_path(spec))
    ws_root = Path(root) if root is not None else config.workspace()

    ident = identify(folder, overrides=overrides, ws_root=ws_root)
    pnl_candidates = [Path(pnl)] if pnl is not None else find_pnl(folder)
    findings: list[Finding] = []
    if len(pnl_candidates) == 1:
        try:
            findings = audit_pnl(pnl_candidates[0])
        except AuditError as exc:
            findings = [_finding("STRUCTURE", "", None, str(exc), "an auditable P&L workbook",
                                 "Attach a readable .xlsx/.xlsm P&L under 15 MB.")]
    items = check_items(folder, spec_obj, ident=ident, findings=findings, pnl_candidates=pnl_candidates)
    classification, questions = classify(items, findings)
    if spec_obj.placeholder:
        if classification == "COMPLETE":
            classification = "FIXABLE"
        questions = True

    position_id = position_id_for(folder, position)
    result = TriageResult(folder=folder, position_id=position_id, identification=ident, items=items,
                          findings=findings, classification=classification, questions=questions,
                          placeholder_spec=spec_obj.placeholder)

    staging = ws_root / "staging" / "app" / position_id
    staging.mkdir(parents=True, exist_ok=True)
    brief_text = f"# {position_id}\n\nClass: {classification}\nQuestions for the analyst: {questions}\n"
    triage_text = render_triage_md(result, spec_obj)
    brief_path, triage_path = staging / "brief.md", staging / "triage.md"
    brief_path.write_text(brief_text, encoding="utf-8", newline="\n")
    triage_path.write_text(triage_text, encoding="utf-8", newline="\n")
    manifest.write(brief_path, "derived", "app triage brief", "", received.isoformat(), row_count=1,
                   inputs=[folder / p.name for p in pnl_candidates])
    manifest.write(triage_path, "derived", "app triage", "", received.isoformat(), row_count=len(items) + len(findings),
                   inputs=[folder / p.name for p in pnl_candidates])
    result.outputs = {"brief": brief_path, "triage": triage_path}

    if classification == "RETURN" or questions:
        from cpa import fsutil

        dept = ident.department_canonical or (ident.fields["department"].value if ident.fields.get("department") else "dept")
        dept_safe = re.sub(r"[^A-Za-z0-9_-]+", "_", dept).strip("_") or "dept"
        stem = position_id if position_id.casefold().startswith(dept_safe.casefold()) else f"{dept_safe}_{position_id}"
        email_dir = ws_root / "outbox" / "app" / cycle.isoformat() / "emails"
        email_dir.mkdir(parents=True, exist_ok=True)
        email_path = email_dir / fsutil.safe_filename(f"{stem}_return.md")
        email_path.write_text(render_email_md(result, spec_obj), encoding="utf-8", newline="\n")
        manifest.write(email_path, "derived", "app triage return email", "", received.isoformat(), row_count=1,
                       inputs=[triage_path])
        result.outputs["email"] = email_path

    return result


# ---------------------------------------------------------------- CLI

EXIT_OK, EXIT_ISSUES, EXIT_STOPPED = 0, 1, 2


def _override_args(args: argparse.Namespace) -> dict[str, str]:
    return {k: v for k, v in (("department", args.department), ("division", args.division),
                              ("position_title", args.position_title), ("requester", args.requester)) if v}


def _cmd_identify(args: argparse.Namespace) -> int:
    ident = identify(args.folder, overrides=_override_args(args))
    if args.json:
        import json

        print(json.dumps(ident.to_json(), indent=2, ensure_ascii=False))
    else:
        for name in IDENTIFY_FIELDS:
            loc = ident.fields.get(name)
            print(f"{name}: " + (f"{loc.value} ({loc.source}, {loc.location})" if loc else "NOT FOUND"))
        for p in ident.problems:
            print(f"problem: {p}")
    return EXIT_OK if not ident.problems else EXIT_ISSUES


def _cmd_checklist(args: argparse.Namespace) -> int:
    try:
        spec = load_spec(resolve_spec_path(args.spec))
    except ChecklistSpecError as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return EXIT_STOPPED
    ident = identify(args.folder)
    pnl_candidates = [Path(args.pnl)] if args.pnl else find_pnl(args.folder)
    findings: list[Finding] = []
    if len(pnl_candidates) == 1:
        try:
            findings = audit_pnl(pnl_candidates[0])
        except AuditError as exc:
            print(f"warning: {exc}", file=sys.stderr)
    items = check_items(args.folder, spec, ident=ident, findings=findings, pnl_candidates=pnl_candidates)
    if args.json:
        import json

        print(json.dumps([i.to_json() for i in items], indent=2, ensure_ascii=False))
    else:
        for item in items:
            print(f"[{item.status}] {item.item_id}" + (f" -- {item.reason}" if item.reason else ""))
    return EXIT_OK if all(i.status == "PRESENT" for i in items) else EXIT_ISSUES


def _cmd_audit_pnl(args: argparse.Namespace) -> int:
    try:
        findings = audit_pnl(args.pnl)
    except AuditError as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return EXIT_STOPPED
    if args.json:
        import json

        print(json.dumps([f.to_json() for f in findings], indent=2, ensure_ascii=False))
    else:
        for f in findings:
            where = f"{f.sheet}!{f.cell}" if f.cell else (f.sheet or "workbook")
            print(f"{f.code} at {where} ({f.resolution}): found {f.found}, expected {f.expected}")
    return EXIT_OK if not findings else EXIT_ISSUES


def _cmd_run(args: argparse.Namespace) -> int:
    from cpa import config

    try:
        received = date.fromisoformat(args.received) if args.received else None
        result = run(args.folder, cycle=date.fromisoformat(args.cycle), spec=args.spec, pnl=args.pnl,
                    position=args.position, overrides=_override_args(args), received=received, root=args.root)
    except (TriageError, config.ConfigError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return EXIT_STOPPED
    if args.json:
        import json

        print(json.dumps(result.to_json(), indent=2, ensure_ascii=False))
    print(f"{result.position_id}: {result.classification}" + (" (questions)" if result.questions else ""))
    for name, path in result.outputs.items():
        print(f"{name}: {path}")
    return EXIT_OK if result.classification != "RETURN" else EXIT_ISSUES


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `app_triage identify|checklist|audit_pnl|run`. Import-cheap (D03)."""
    top = subparsers.add_parser("app_triage", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    p = sub.add_parser("identify", help="Identify department, division, position title and requester.")
    p.add_argument("folder", type=Path)
    p.add_argument("--department"), p.add_argument("--division")
    p.add_argument("--position-title", dest="position_title"), p.add_argument("--requester")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_identify)

    p = sub.add_parser("checklist", help="Check a submission folder against the checklist spec.")
    p.add_argument("folder", type=Path)
    p.add_argument("--spec", type=Path, default=None)
    p.add_argument("--pnl", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_checklist)

    p = sub.add_parser("audit_pnl", help="Audit a P&L workbook for hard-codes, broken refs, benchmark "
                                        "cells, rate mismatches, structure and sign errors (R045).")
    p.add_argument("pnl", type=Path)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_audit_pnl)

    p = sub.add_parser("run", help="Identify, audit, classify and write triage.md and a return email if needed.",
                       description="Never edits the submission (R043); never sends the return email (R044). "
                                   "Exit 0 written and not RETURN, 1 written and RETURN, 2 stopped.")
    p.add_argument("folder", type=Path)
    p.add_argument("--cycle", required=True, help="SOM cycle date, YYYY-MM-DD (used in the output path).")
    p.add_argument("--spec", type=Path, default=None)
    p.add_argument("--pnl", type=Path, default=None)
    p.add_argument("--position", default=None)
    p.add_argument("--department"), p.add_argument("--division")
    p.add_argument("--position-title", dest="position_title"), p.add_argument("--requester")
    p.add_argument("--received", default=None, help="Date the submission was received, YYYY-MM-DD (required).")
    p.add_argument("--root", type=Path, default=None, help="Workspace root (default: the resolved workspace).")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_run)
