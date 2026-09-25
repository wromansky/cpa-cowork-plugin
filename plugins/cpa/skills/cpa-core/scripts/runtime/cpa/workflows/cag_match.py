"""CAG-to-QGenda matcher (B18): five tiers plus a reverse pass; TaskKeys from source only; coverage reported.

Build List B18 (CPA_Cowork_Build_List.md "B18 CAG-to-QGenda matcher refresh"), guide section 6 row
`cpa-cag-match`, hard rule 4 (TaskKeys are Hopkins system-assigned: never fabricated, blank when unmatched)
and hard rule 10 (department labels through reference/dept_crosswalk.csv; unmatched fails loudly).
Rules: R004/R128/R166/R167/R200/R234 (TaskKey), R127/R174 (tiers, gaps flagged), R169 (one task one CAG,
Hospitalists many to many), R172 (Link II over Link I), R220 (over-linking).

Inputs:
- QGenda task exports (A13) `inbox/qgenda/tasks_<dept>_<YYYY-MM-DD>.*`, read only through the U09 adapter
  `sources.get("qgenda.tasks")` (hard rule 12). The set of non-blank TaskKeys they carry is the ONLY place a
  TaskKey in any output can come from.
- Her workbook (FPA_Work_Inventory_CPA.md "Departmental_Overview_CAG_and_QGenda_SA.xlsx") with the sheets
  CAG Masterlist, Task to CAG Link and Task to CAG Link II.

Tiers (a link row against the source tasks of its department that share its TaskKey, else its task name):
strict (division and activity equal), loose activity, loose division, loose both (loose = equal after
folding case and punctuation, or one word set contains the other), department-only (division and activity
ignored). The reverse pass takes each source task no link claimed and looks for exactly one masterlist CAG
in its department, division and activity. Every row is kept and flagged; nothing is silently dropped.

FIXTURE - confirm against her file: sheet column headers, the Hospitalists division label, the role
labels, the Link I/Link II overlap identity and the tier fills are reconstructed from the inventory's
description of her CAG_Task_Combined v3-v8 script, not from the script itself.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Any

__all__ = [
    "SHEETS", "MASTERLIST_NAME", "TIERS", "TIER_FILLS", "BLOCKING", "REGISTER_NAME", "REGISTER_COLUMNS",
    "OUTPUT_STEM", "OUTPUT_SHEETS", "CagMatchError", "MasterlistError", "RegisterNotReadable",
    "Task", "CagRow", "Link", "MatchRow", "Issue", "MatchResult", "RunResult",
    "load_tasks", "load_masterlist", "resolve_links", "match", "default_tasks", "next_version",
    "update_register", "write_workbook", "run", "register",
]

# FIXTURE - confirm against her file (inventory: "Departmental_Overview_CAG_and_QGenda_SA.xlsx").
MASTERLIST_NAME = "Departmental_Overview_CAG_and_QGenda_SA.xlsx"
SHEETS = {"masterlist": "CAG Masterlist", "link_i": "Task to CAG Link", "link_ii": "Task to CAG Link II"}
# FIXTURE - confirm against her file: header spellings of the three sheets (canonical -> accepted headers).
COLUMNS: dict[str, tuple[str, ...]] = {
    "department": ("department", "dept"),
    "division": ("division", "div"),
    "activity": ("activity",),
    "role": ("role", "provider type", "provider role"),
    "cag": ("cag", "clinical activity group"),
    "task_name": ("task name", "task", "qgenda task", "qgenda task name"),
    "taskkey": ("taskkey", "task key", "task id"),
}
MASTERLIST_REQUIRED = ("department", "division", "activity", "role", "cag")
LINK_REQUIRED = ("department", "division", "activity", "role", "cag", "task_name")

TIERS: tuple[str, ...] = ("strict", "loose activity", "loose division", "loose both", "department-only",
                          "reverse", "unmatched")
# Tool setting (not a Hopkins fact): one fill per match quality, green = strongest. Never gold, ice blue or
# flag yellow (DECISIONS D08). FIXTURE - confirm against her file: her v8 color legend.
TIER_FILLS: dict[str, str] = {
    "strict": "F3C300",
    "loose activity": "A3BBC3",
    "loose division": "B6B09C",
    "loose both": "CFC393",
    "department-only": "9D958C",
    "reverse": "00A0DF",
    "unmatched": "F2F2F2",
    "issue": "FFDD00",
}
TIER_MEANING = {
    "strict": "department, division, activity and task all agree",
    "loose activity": "activity agrees only after folding case, punctuation or extra words",
    "loose division": "division agrees only after folding case, punctuation or extra words",
    "loose both": "division and activity both agree only after folding",
    "department-only": "only department and task agree; division and activity differ - review",
    "reverse": "task no link claimed; the one masterlist CAG for its division and activity - confirm",
    "unmatched": "link row with no QGenda task; TaskKey left blank",
    "issue": "row carries a blocking issue (over-linked or one task under two CAGs)",
}
MANY_TO_MANY_MARK = "hospitalist"  # FIXTURE - confirm the division label (inventory: "Hospitalists")
OVERLINK_ROLES = ("Faculty", "Clinical Associate")  # FIXTURE - confirm her role labels
BLOCKING = frozenset({"OVER_LINKED", "ONE_TO_ONE_VIOLATION"})

REGISTER_NAME = "taskkey_register.csv"
REGISTER_COLUMNS = ("taskkey", "task_name", "department", "source_file", "first_seen", "last_seen")
OUT = ("outbox", "cag")
OUTPUT_STEM = "CAG_Task_Combined"
OUTPUT_SHEETS = ("Summary", "Combined", "Unmatched Tasks", "Unlinked CAGs", "Issues", "Legend")
SOURCE_LABEL = "QGenda; CAG masterlist"
_TASK_FILE_RE = re.compile(r"^tasks_(.+)_(\d{4}-\d{2}-\d{2})\.(xlsx|xlsm|xlsb|csv)$", re.IGNORECASE)

COMBINED_HEADER = ("Department", "Division", "Activity", "Role", "CAG", "Task Name", "TaskKey", "Tier",
                   "Task Division", "Task Activity", "Link Sheet", "Link Row", "Source File", "Source Row",
                   "Flags", "Count")
UNMATCHED_HEADER = ("Department", "Division", "Activity", "Task Name", "TaskKey", "Source File", "Source Row",
                    "Reason", "Count")
UNLINKED_HEADER = ("Department", "Division", "Activity", "Role", "CAG", "Masterlist Row", "Count")


class CagMatchError(RuntimeError):
    """Base for every matcher failure the analyst can fix (exit 3)."""


class MasterlistError(CagMatchError):
    """A sheet or required column of her CAG workbook is missing; names file, sheet and column."""


class RegisterNotReadable(CagMatchError):
    """reference/taskkey_register.csv is not UTF-8 or has the wrong header."""


# -- primitives -----------------------------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    """Stripped text; None for None, pandas NA, NaN, blank and the literal 'nan'.

    'nan' is treated as blank because cpa/sources/base.py TabularAdapter._frame turns a blank string cell into
    the text 'nan' (known defect, reported by U09's own test); a real label or TaskKey is never 'nan'."""
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except (TypeError, ValueError):  # pandas NA refuses comparison
        return None
    if type(value).__name__ == "NAType":
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if not text or text == "nan":
        return None
    return text


def _key(value: Any) -> str | None:
    """The one TaskKey primitive: blank-like -> None (never matches anything), else the stripped text. A key is
    never generated, padded or reformatted beyond what the source cell holds."""
    return _text(value)


def _fold(value: Any) -> str:
    from cpa.sources.base import fold

    return fold(_text(value) or "")


def _exact(a: str | None, b: str | None) -> bool:
    return (a or "").strip() == (b or "").strip()


def _loose(a: str | None, b: str | None) -> bool:
    fa, fb = _fold(a), _fold(b)
    if not fa or not fb:
        return fa == fb
    if fa == fb:
        return True
    ta, tb = set(fa.split()), set(fb.split())
    return ta <= tb or tb <= ta


def _is_many_to_many(division: str | None) -> bool:
    return MANY_TO_MANY_MARK in _fold(division)


# -- data -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """One QGenda export row. `taskkey` is exactly what the source cell held (None when blank)."""

    taskkey: str | None
    task_name: str | None
    department: str
    division: str | None
    activity: str | None
    source_file: str
    source_row: int


@dataclass(frozen=True)
class CagRow:
    """One CAG Masterlist row."""

    department: str
    division: str | None
    activity: str | None
    role: str | None
    cag: str
    source_row: int


@dataclass(frozen=True)
class Link:
    """One Task to CAG Link / Link II row. `taskkey` is her cell; it is only ever compared, never emitted."""

    sheet: str
    department: str
    division: str | None
    activity: str | None
    role: str | None
    cag: str | None
    task_name: str | None
    taskkey: str | None
    source_row: int


@dataclass
class MatchRow:
    """One Combined row. `taskkey` is a matched source task's key or None."""

    department: str
    division: str | None
    activity: str | None
    role: str | None
    cag: str | None
    task_name: str | None
    taskkey: str | None
    tier: str
    sheet: str
    link_row: int | None
    tasks: tuple[int, ...] = ()  # indexes into the task list
    task_division: str | None = None
    task_activity: str | None = None
    source_file: str | None = None
    source_row: int | None = None
    flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Issue:
    code: str
    detail: str

    @property
    def blocking(self) -> bool:
        return self.code in BLOCKING


@dataclass
class MatchResult:
    rows: list[MatchRow]
    unmatched_tasks: list[tuple[Task, str]]
    unlinked_cags: list[CagRow]
    issues: list[Issue]
    tier_counts: dict[str, int]
    tasks_total: int
    tasks_covered: int
    cags_total: int
    cags_linked: int

    @property
    def task_coverage_pct(self) -> float | None:
        return round(100.0 * self.tasks_covered / self.tasks_total, 1) if self.tasks_total else None

    @property
    def cag_coverage_pct(self) -> float | None:
        return round(100.0 * self.cags_linked / self.cags_total, 1) if self.cags_total else None

    def blocking(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.blocking)

    def to_json(self) -> dict:
        return {
            "coverage": {"task_coverage_pct": self.task_coverage_pct, "cag_coverage_pct": self.cag_coverage_pct,
                         "tasks_total": self.tasks_total, "tasks_covered": self.tasks_covered,
                         "cags_total": self.cags_total, "cags_linked": self.cags_linked},
            "tier_counts": dict(self.tier_counts),
            "combined_rows": len(self.rows),
            "unmatched_tasks": len(self.unmatched_tasks),
            "unlinked_cags": len(self.unlinked_cags),
            "blocking": [f"{i.code}: {i.detail}" for i in self.blocking()],
            "issue_counts": {c: sum(1 for i in self.issues if i.code == c)
                             for c in dict.fromkeys(i.code for i in self.issues)},
        }


@dataclass
class RunResult:
    workbook: Path
    version: int
    date: str
    match: MatchResult
    register_added: int
    verification: dict
    inputs: list[Path]

    @property
    def exit_code(self) -> int:
        return 1 if self.match.blocking() else 0

    def to_json(self) -> dict:
        from cpa import manifest

        return {"workbook": manifest.to_rel(self.workbook), "version": self.version, "date": self.date,
                **self.match.to_json(), "register_added": self.register_added,
                "verification": self.verification, "inputs": [manifest.to_rel(p) for p in self.inputs]}


# -- loading --------------------------------------------------------------------------------------------------


def _canonical(labels: Sequence[str | None]):
    """Map every department label through the crosswalk; any unmatched label raises UnmatchedDepartment."""
    from cpa import crosswalk

    cw = crosswalk.load()
    offenders = [lab or "" for lab in labels if cw.lookup(lab) is None]
    if offenders:
        raise crosswalk.UnmatchedDepartment(offenders, cw.path)
    return cw


def load_tasks(paths: Sequence[Path]) -> list[Task]:
    """Every non-blank row of each QGenda export via the U09 adapter; departments canonicalised."""
    from cpa import sources

    adapter = sources.get("qgenda.tasks")
    raw: list[dict] = []
    for path in paths:
        frame = adapter.load(Path(path))
        for i, rec in enumerate(frame.to_dict("records")):
            vals = {k: _text(rec.get(k)) for k in ("task_key", "task_name", "department", "division", "activity")}
            if not any(vals.values()):
                continue
            raw.append({**vals, "source_file": Path(path).name, "source_row": i + 2})
    cw = _canonical([r["department"] for r in raw])
    return [Task(taskkey=_key(r["task_key"]), task_name=r["task_name"], department=cw.lookup(r["department"]),
                 division=r["division"], activity=r["activity"], source_file=r["source_file"],
                 source_row=r["source_row"]) for r in raw]


def _read_sheet(path: Path, sheet: str, required: Sequence[str]) -> list[tuple[int, dict]]:
    from cpa import bigxlsx

    rows = bigxlsx.iter_rows(path, sheet)
    try:
        header = next(rows, [])
        folded = [_fold(h) for h in header]
        where: dict[str, int] = {}
        for name, aliases in COLUMNS.items():
            for i, f in enumerate(folded):
                if f and f in aliases and i not in where.values():
                    where[name] = i
                    break
        missing = [c for c in required if c not in where]
        if missing:
            raise MasterlistError(f"{path.name}: sheet {sheet!r} has no column for {', '.join(missing)} "
                                  f"(accepted headers: {'; '.join('/'.join(COLUMNS[c]) for c in missing)})")
        out = []
        for n, row in enumerate(rows, start=2):
            rec = {c: _text(row[i]) if i < len(row) else None for c, i in where.items()}
            if any(rec.values()):
                out.append((n, rec))
        return out
    finally:
        rows.close()


def load_masterlist(path: Path) -> tuple[list[CagRow], list[Link], list[Link]]:
    """The three sheets of her CAG workbook; departments canonicalised through the crosswalk."""
    from cpa import bigxlsx

    path = Path(path)
    names = bigxlsx.sheet_names(path)
    absent = [s for s in SHEETS.values() if s not in names]
    if absent:
        raise MasterlistError(f"{path.name}: missing sheet(s) {', '.join(repr(s) for s in absent)}; "
                              f"found {', '.join(repr(n) for n in names)}")
    master = _read_sheet(path, SHEETS["masterlist"], MASTERLIST_REQUIRED)
    link_i = _read_sheet(path, SHEETS["link_i"], LINK_REQUIRED)
    link_ii = _read_sheet(path, SHEETS["link_ii"], LINK_REQUIRED)
    cw = _canonical([r["department"] for _, r in master + link_i + link_ii])
    cags = [CagRow(cw.lookup(r["department"]), r["division"], r["activity"], r["role"], r["cag"] or "", n)
            for n, r in master]

    def links(sheet: str, rows: list[tuple[int, dict]]) -> list[Link]:
        return [Link(sheet, cw.lookup(r["department"]), r["division"], r["activity"], r["role"], r["cag"],
                     r["task_name"], _key(r.get("taskkey")), n) for n, r in rows]

    return cags, links(SHEETS["link_i"], link_i), links(SHEETS["link_ii"], link_ii)


# -- matching (pure) ------------------------------------------------------------------------------------------


def _overlap_id(link: Link) -> tuple:
    return (link.department, _fold(link.division), _fold(link.activity), _fold(link.task_name))


def resolve_links(link_i: Sequence[Link], link_ii: Sequence[Link]) -> tuple[list[Link], list[Issue]]:
    """Link II is authoritative: a Link I row whose (department, division, activity, task) Link II also
    carries is dropped and reported as LINK_I_OVERRIDDEN, never silently. Link II rows come first."""
    authoritative = {}
    for link in link_ii:
        authoritative.setdefault(_overlap_id(link), link)
    kept, issues = list(link_ii), []
    for link in link_i:
        winner = authoritative.get(_overlap_id(link))
        if winner is None:
            kept.append(link)
            continue
        issues.append(Issue("LINK_I_OVERRIDDEN",
                            f"{link.sheet} row {link.source_row} (task {link.task_name!r}, CAG {link.cag!r}, "
                            f"role {link.role!r}) overridden by {winner.sheet} row {winner.source_row} "
                            f"(CAG {winner.cag!r}, role {winner.role!r})"))
    return kept, issues


_TIER_TESTS = (
    ("strict", lambda L, t: _exact(L.division, t.division) and _exact(L.activity, t.activity)),
    ("loose activity", lambda L, t: _exact(L.division, t.division) and _loose(L.activity, t.activity)),
    ("loose division", lambda L, t: _loose(L.division, t.division) and _exact(L.activity, t.activity)),
    ("loose both", lambda L, t: _loose(L.division, t.division) and _loose(L.activity, t.activity)),
    ("department-only", lambda L, t: True),
)


def _identity(row: MatchRow) -> str:
    return f"TaskKey {row.taskkey}" if row.taskkey else f"task {row.task_name!r}"


def match(tasks: Sequence[Task], cags: Sequence[CagRow], link_i: Sequence[Link],
          link_ii: Sequence[Link]) -> MatchResult:
    """Resolve links, run the five tiers and the reverse pass, then the one-to-one and over-linking checks."""
    links, issues = resolve_links(link_i, link_ii)
    allowed = frozenset(t.taskkey for t in tasks if t.taskkey)
    by_key: dict[tuple[str, str], list[int]] = {}
    by_name: dict[tuple[str, str], list[int]] = {}
    for i, t in enumerate(tasks):
        if t.taskkey:
            by_key.setdefault((t.department, t.taskkey), []).append(i)
        if t.task_name:
            by_name.setdefault((t.department, _fold(t.task_name)), []).append(i)
    master_cags = {(c.department, _fold(c.cag)) for c in cags}

    rows: list[MatchRow] = []
    covered: set[int] = set()
    for link in links:
        row = MatchRow(link.department, link.division, link.activity, link.role, link.cag, link.task_name,
                       None, "unmatched", link.sheet, link.source_row)
        where = f"{link.sheet} row {link.source_row}"
        if link.taskkey and link.taskkey in allowed:
            pool = by_key.get((link.department, link.taskkey), [])
        else:
            if link.taskkey:
                row.flags.append("TASKKEY_NOT_IN_SOURCE")
                issues.append(Issue("TASKKEY_NOT_IN_SOURCE", f"{where}: its TaskKey cell is in no QGenda export "
                                                             f"loaded; never copied, matched by task name instead"))
            pool = by_name.get((link.department, _fold(link.task_name)), []) if link.task_name else []
        winners: list[int] = []
        for tier, test in _TIER_TESTS:
            winners = [i for i in pool if test(link, tasks[i])]
            if winners:
                row.tier = tier
                break
        if not winners:
            row.flags.append("UNMATCHED_LINK")
            issues.append(Issue("UNMATCHED_LINK", f"{where} (task {link.task_name!r}, CAG {link.cag!r}): no QGenda "
                                                  f"task in {link.department}; TaskKey left blank"))
        else:
            keys = {tasks[i].taskkey for i in winners}
            first = tasks[winners[0]]
            row.task_name = first.task_name or link.task_name  # the QGenda spelling wins over the link's
            row.task_division, row.task_activity = first.division, first.activity
            row.source_file, row.source_row = first.source_file, first.source_row
            if len(keys) == 1:
                row.taskkey = keys.pop()
                row.tasks = tuple(winners)
                covered.update(winners)
                if row.taskkey is None:
                    row.flags.append("BLANK_TASKKEY_IN_SOURCE")
                    issues.append(Issue("BLANK_TASKKEY_IN_SOURCE", f"{where}: matched {first.source_file} row "
                                                                   f"{first.source_row}, whose TaskKey is blank"))
            else:
                row.flags.append("AMBIGUOUS_MATCH")
                issues.append(Issue("AMBIGUOUS_MATCH", f"{where} (task {link.task_name!r}): {len(winners)} QGenda "
                                                       f"rows with different TaskKeys at tier {row.tier}; left blank"))
        if link.cag and (link.department, _fold(link.cag)) not in master_cags:
            row.flags.append("CAG_NOT_IN_MASTERLIST")
            issues.append(Issue("CAG_NOT_IN_MASTERLIST", f"{where}: CAG {link.cag!r} is not in the "
                                                         f"{SHEETS['masterlist']} for {link.department}"))
        rows.append(row)

    # reverse pass: tasks no link claimed
    unmatched: list[tuple[Task, str]] = []
    for i, t in enumerate(tasks):
        if i in covered:
            continue
        cands = [c for c in cags if c.department == t.department and _loose(c.division, t.division)
                 and _loose(c.activity, t.activity)]
        distinct = {_fold(c.cag) for c in cands}
        if len(distinct) == 1:
            roles = {c.role for c in cands}
            rows.append(MatchRow(t.department, cands[0].division, cands[0].activity,
                                 roles.pop() if len(roles) == 1 else None, cands[0].cag, t.task_name, t.taskkey,
                                 "reverse", "reverse pass", None, (i,), t.division, t.activity, t.source_file,
                                 t.source_row, ["REVERSE_REVIEW"]))
            covered.add(i)
        else:
            reason = ("no link row and no masterlist CAG for its division and activity" if not distinct else
                      f"no link row; {len(distinct)} masterlist CAGs fit its division and activity")
            unmatched.append((t, reason))
    if unmatched:
        issues.append(Issue("UNMATCHED_TASK", f"{len(unmatched)} QGenda task row(s) with no CAG; "
                                              f"listed on Unmatched Tasks"))

    # one task, one CAG (R169) and over-linking (R220)
    groups: dict[tuple, list[int]] = {}
    for n, r in enumerate(rows):
        if r.tier == "unmatched" or not (r.taskkey or r.task_name):
            continue
        ident = r.taskkey or f"name:{_fold(r.task_name)}"
        div = r.task_division if r.tasks else r.division
        act = r.task_activity if r.tasks else r.activity
        groups.setdefault((r.department, _fold(div), _fold(act), ident), []).append(n)
    over_roles = {_fold(x) for x in OVERLINK_ROLES}
    for (dept, _, _, _), members in groups.items():
        sample = rows[members[0]]
        div = sample.task_division if sample.tasks else sample.division
        act = sample.task_activity if sample.tasks else sample.activity
        label = f"{_identity(sample)} in {dept} / {div} / {act}"
        cags_here = {_fold(rows[n].cag) for n in members if rows[n].cag}
        if len(cags_here) > 1:
            if _is_many_to_many(div) or any(_is_many_to_many(rows[n].division) for n in members):
                for n in members:
                    rows[n].flags.append("MANY_TO_MANY_OK")
            else:
                issues.append(Issue("ONE_TO_ONE_VIOLATION", f"{label} maps to {len(cags_here)} CAGs: "
                                    f"{', '.join(sorted({rows[n].cag or '' for n in members}))}"))
                for n in members:
                    rows[n].flags.append("ONE_TO_ONE_VIOLATION")
        if over_roles <= {_fold(rows[n].role) for n in members}:
            issues.append(Issue("OVER_LINKED", f"{label} is linked under both {' and '.join(OVERLINK_ROLES)}"))
            for n in members:
                if _fold(rows[n].role) in over_roles:
                    rows[n].flags.append("OVER_LINKED")

    linked = {(r.department, _fold(r.cag)) for r in rows if r.tasks and r.cag}
    unlinked = [c for c in cags if (c.department, _fold(c.cag)) not in linked]
    if unlinked:
        issues.append(Issue("UNLINKED_CAG", f"{len(unlinked)} masterlist CAG row(s) with no QGenda task; "
                                            f"listed on Unlinked CAGs"))
    counts = {t: sum(1 for r in rows if r.tier == t) for t in TIERS}
    return MatchResult(rows, unmatched, unlinked, issues, counts, len(tasks), len(covered), len(cags),
                       len(cags) - len(unlinked))


# -- files ----------------------------------------------------------------------------------------------------


def _root(root: Path | None) -> Path:
    if root is not None:
        return Path(root)
    from cpa import config

    return config.workspace()


def _task_files(root: Path) -> list[tuple[Path, str]]:
    folder = root / "inbox" / "qgenda"
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.iterdir()):
        m = _TASK_FILE_RE.match(p.name)
        if m and p.is_file():
            out.append((p, m.group(2)))
    return out


def default_tasks(root: Path, date: str | None) -> tuple[list[Path], str]:
    """Task exports for `date` (YYYY-MM-DD); with no date, those for the latest date present."""
    files = _task_files(root)
    if date is None:
        if not files:
            raise CagMatchError(f"no QGenda task export (tasks_<dept>_<YYYY-MM-DD>.xlsx) in "
                                f"{root / 'inbox' / 'qgenda'}; land one with cpa-pull-qgenda or pass --tasks")
        date = max(d for _, d in files)
    chosen = [p for p, d in files if d == date]
    if not chosen:
        raise CagMatchError(f"no QGenda task export dated {date} in {root / 'inbox' / 'qgenda'}; pass --tasks")
    return chosen, date


def next_version(root: Path) -> int:
    """1 + the highest N over outbox/cag/*/CAG_Task_Combined_v<N>.xlsx; 1 when there is none."""
    pat = re.compile(rf"^{OUTPUT_STEM}_v(\d+)\.xlsx$")
    base = root.joinpath(*OUT)
    found = [int(m.group(1)) for p in base.glob("*/*.xlsx") if (m := pat.match(p.name))] if base.is_dir() else []
    return max(found, default=0) + 1


def _prior(root: Path, version: int) -> Path | None:
    base = root.joinpath(*OUT)
    if version < 2 or not base.is_dir():
        return None
    name = f"{OUTPUT_STEM}_v{version - 1}.xlsx"
    hits = sorted(d / name for d in base.iterdir() if (d / name).is_file())
    return hits[0] if hits else None


def _load_register(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RegisterNotReadable(f"{path} is not UTF-8 ({exc}); re-save it in Excel as 'CSV UTF-8'") from exc
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != REGISTER_COLUMNS:
        raise RegisterNotReadable(f"{path} header must be {','.join(REGISTER_COLUMNS)}; found {reader.fieldnames}")
    return {row["taskkey"]: dict(row) for row in reader if _key(row.get("taskkey"))}


def update_register(path: Path, tasks: Sequence[Task], *, seen_on: str) -> int:
    """Add every non-blank TaskKey from the QGenda task rows (never from a link sheet); keep first_seen,
    advance last_seen. Returns the number of keys added."""
    from cpa import fsutil

    existing = _load_register(path)
    added = 0
    for t in tasks:
        if not t.taskkey:
            continue
        rec = existing.get(t.taskkey)
        if rec is None:
            existing[t.taskkey] = {"taskkey": t.taskkey, "task_name": t.task_name or "", "department": t.department,
                                   "source_file": t.source_file, "first_seen": seen_on, "last_seen": seen_on}
            added += 1
        elif (rec.get("last_seen") or "") < seen_on:
            rec["last_seen"] = seen_on
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(REGISTER_COLUMNS)
    for key in sorted(existing):
        writer.writerow([existing[key].get(c, "") for c in REGISTER_COLUMNS])
    text = buf.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    fsutil.atomic_write(path, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))
    return added


def _quote(sheet: str) -> str:
    return f"'{sheet}'" if " " in sheet else sheet


def write_workbook(result: MatchResult, path: Path, *, period: str, as_of: str) -> dict[str, tuple[str, str, int]]:
    """Write the six output sheets. Returns {figure id: (Summary cell, source ref, value)} for the figures that
    tie to a detail sheet's Count column."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    from cpa import fsutil
    from cpa.pptx import brand

    header_fill = PatternFill("solid", fgColor=brand.color("dark_green").lstrip("#"))
    header_font = Font(name="Arial", bold=True, color="FFFFFF")
    body_font = Font(name="Arial")
    fills = {k: PatternFill("solid", fgColor=v) for k, v in TIER_FILLS.items()}
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    sheets = {name: wb.create_sheet(name) for name in OUTPUT_SHEETS}

    def put(ws, values: Sequence[Any], fill=None, text_cols: Sequence[int] = ()) -> None:
        ws.append(list(values))
        r = ws.max_row
        for c in range(1, len(values) + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = body_font
            if fill is not None:
                cell.fill = fill
            if c in text_cols:
                cell.number_format = "@"

    def head(ws, header: Sequence[str]) -> None:
        ws.append(list(header))
        for c in range(1, len(header) + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill, cell.font = header_fill, header_font
            ws.column_dimensions[get_column_letter(c)].width = max(12, len(header[c - 1]) + 2)

    key_col = COMBINED_HEADER.index("TaskKey") + 1
    ws = sheets["Combined"]
    head(ws, COMBINED_HEADER)
    counted: set[int] = set()
    for r in result.rows:
        new = [i for i in r.tasks if i not in counted]
        counted.update(r.tasks)
        fill = fills["issue"] if any(f in BLOCKING for f in r.flags) else fills[r.tier]
        put(ws, [r.department, r.division, r.activity, r.role, r.cag, r.task_name, r.taskkey, r.tier,
                 r.task_division, r.task_activity, r.sheet, r.link_row, r.source_file, r.source_row,
                 "; ".join(dict.fromkeys(r.flags)) or None, 1 if new else 0], fill, (key_col,))

    ws = sheets["Unmatched Tasks"]
    head(ws, UNMATCHED_HEADER)
    for t, reason in result.unmatched_tasks:
        put(ws, [t.department, t.division, t.activity, t.task_name, t.taskkey, t.source_file, t.source_row,
                 reason, 1], fills["unmatched"], (UNMATCHED_HEADER.index("TaskKey") + 1,))

    ws = sheets["Unlinked CAGs"]
    head(ws, UNLINKED_HEADER)
    for c in result.unlinked_cags:
        put(ws, [c.department, c.division, c.activity, c.role, c.cag, c.source_row, 1], fills["unmatched"])

    ws = sheets["Issues"]
    head(ws, ("Code", "Blocking", "Detail"))
    for i in result.issues:
        put(ws, [i.code, "yes" if i.blocking else "no", i.detail], fills["issue"] if i.blocking else None)

    ws = sheets["Legend"]
    head(ws, ("Tier", "Fill", "Meaning"))
    for tier in (*TIERS, "issue"):
        put(ws, [tier, f"#{TIER_FILLS[tier]}", TIER_MEANING[tier]])
        ws.cell(row=ws.max_row, column=2).fill = fills[tier]

    detail_refs = {
        "tasks_covered": ("Combined", len(result.rows), len(COMBINED_HEADER)),
        "tasks_unmatched": ("Unmatched Tasks", len(result.unmatched_tasks), len(UNMATCHED_HEADER)),
        "cags_unlinked": ("Unlinked CAGs", len(result.unlinked_cags), len(UNLINKED_HEADER)),
    }
    m = result
    metrics = [
        ("Source task rows", None, m.tasks_total),
        ("Tasks linked to a CAG", "tasks_covered", m.tasks_covered),
        ("Tasks with no CAG", "tasks_unmatched", m.tasks_total - m.tasks_covered),
        ("Task coverage %", None, m.task_coverage_pct),
        ("Masterlist CAG rows", None, m.cags_total),
        ("CAG rows linked to a task", None, m.cags_linked),
        ("CAG rows with no task", "cags_unlinked", len(m.unlinked_cags)),
        ("CAG coverage %", None, m.cag_coverage_pct),
        *[(f"Rows at tier: {t}", None, m.tier_counts.get(t, 0)) for t in TIERS],
        ("Blocking issues", None, len(m.blocking())),
    ]
    ws = sheets["Summary"]
    head(ws, ("Metric", "Value", "Period", "Status", "Source", "As of"))
    figures: dict[str, tuple[str, str, int]] = {}
    for label, fid, value in metrics:
        put(ws, [label, value, period, "actual", SOURCE_LABEL, as_of])
        if fid and value:
            sheet, n, col = detail_refs[fid]
            letter = get_column_letter(col)
            figures[fid] = (f"Summary!B{ws.max_row}", f"{_quote(sheet)}!{letter}2:{letter}{n + 1}", value)
    ws.column_dimensions["A"].width = 30

    path.parent.mkdir(parents=True, exist_ok=True)
    from cpa.pptx import brand

    for sheet in wb.worksheets:
        brand.style_generated_sheet(sheet, role="reference" if sheet.title == "Legend" else "summary")
    fsutil.atomic_write(path, lambda tmp: wb.save(str(tmp)))
    wb.close()
    return figures


def run(*, root: Path | None = None, date: str | None = None, tasks: Sequence[Path] | None = None,
        masterlist: Path | None = None) -> RunResult:
    """Load, match, write outbox/cag/<date>/CAG_Task_Combined_v<N>.xlsx with its manifest and Verification tab,
    then add source TaskKeys to reference/taskkey_register.csv. Never overwrites an earlier version."""
    from cpa import config, fsutil, manifest, verify

    ws = _root(root)
    if date is not None:
        _date.fromisoformat(date)
    if tasks:
        task_paths = [Path(p) for p in tasks]
        date = date or _date.today().isoformat()
    else:
        task_paths, date = default_tasks(ws, date)
    master_path = Path(masterlist) if masterlist else config.reference_file(MASTERLIST_NAME)
    task_rows = load_tasks(task_paths)
    cags, link_i, link_ii = load_masterlist(master_path)
    result = match(task_rows, cags, link_i, link_ii)

    version = next_version(ws)
    out = ws.joinpath(*OUT, date) / fsutil.safe_filename(f"{OUTPUT_STEM}_v{version}.xlsx")
    if out.exists():
        raise CagMatchError(f"{out} already exists; never overwritten")
    figures = write_workbook(result, out, period=date, as_of=date)
    departments = sorted({t.department for t in task_rows})
    inputs = [master_path, *task_paths]
    manifest.write(out, SOURCE_LABEL, OUTPUT_STEM, f"departments={','.join(departments)}", date, inputs=inputs,
                   period=date, status="actual", version=version, coverage=result.to_json()["coverage"])
    for fid, (cell, ref, value) in figures.items():
        manifest.add_figure(out, fid, value, out, ref, cell=cell, status="actual", period=date)
    vr = verify.build_verification_tab(out, prior=_prior(ws, version))
    verification = {"summary": vr.summary, "issues": [i.line() for i in vr.issues]}
    added = update_register(ws / "reference" / REGISTER_NAME, task_rows, seen_on=date)
    return RunResult(out, version, date, result, added, verification, inputs)


# -- CLI ------------------------------------------------------------------------------------------------------


def _cmd_run(args: argparse.Namespace) -> int:
    from cpa import config, crosswalk, manifest
    from cpa.sources.base import SourceError

    try:
        res = run(root=Path(args.root) if args.root else None, date=args.date,
                  tasks=[Path(p) for p in args.tasks] if args.tasks else None,
                  masterlist=Path(args.masterlist) if args.masterlist else None)
    except (CagMatchError, config.ConfigError, crosswalk.CrosswalkError, SourceError, manifest.ManifestError,
            FileNotFoundError, ValueError) as exc:
        print(f"cag_match: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(res.to_json(), indent=2))
    for issue in res.match.blocking():
        print(f"BLOCKING {issue.code}: {issue.detail}", file=sys.stderr)
    return res.exit_code


def register(subparsers: argparse._SubParsersAction) -> None:
    """`cag_match run`. Import-cheap: no I/O and no third-party import here."""
    top = subparsers.add_parser("cag_match", help="CAG-to-QGenda task matcher (B18).")
    sub = top.add_subparsers(dest="command", required=True)
    p = sub.add_parser(
        "run",
        help="Match QGenda tasks to CAGs (five tiers plus reverse pass); TaskKeys only from source.",
        description="Writes outbox/cag/<date>/CAG_Task_Combined_v<N>.xlsx and prints JSON with coverage. "
                    "Exit 0 clean, 1 written with blocking issues (over-linked, one task under two CAGs), "
                    "3 input error.",
    )
    p.add_argument("--date", help="YYYY-MM-DD of the QGenda task exports (default: latest in inbox/qgenda).")
    p.add_argument("--tasks", nargs="+", help="QGenda task export files (default: inbox/qgenda for --date).")
    p.add_argument("--masterlist", help=f"Her CAG workbook (default: reference/{MASTERLIST_NAME}).")
    p.add_argument("--root", help="Workspace folder (default: the configured workspace).")
    p.set_defaults(func=_cmd_run)
