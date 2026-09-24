"""Cycle and deadline dashboard (B22) and the B9 half of cycle registration.

Registry: logs/cycles.json. Output: logs/dashboard.md plus a morning message on stdout. This module
never sends anything and never reads mail or a calendar. Committee lead times come only from
reference/assumptions.yaml (cpa.config.assumption); an absent or null key raises MissingAssumption
before any write (R071, never guessed). B21 period rollover and B3 triage feed are a different part
of the workflow and are not implemented here. See `docs/OPEN_ITEMS.md` for the missing
triage-to-cycle-dashboard update.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

from cpa import fsutil

REGISTRY_RELPATH: tuple[str, ...] = ("logs", "cycles.json")
DASHBOARD_RELPATH: tuple[str, ...] = ("logs", "dashboard.md")
REGISTRY_VERSION = 1

COMMITTEES: dict[str, str] = {
    "som": "cycles.som_materials_lead_days",
    "bog": "cycles.bog_lead_days",
    "fc": "cycles.fc_lead_days",
    "gov": "cycles.gov_lead_days",
}  # D04: the only place a lead-day key is spelled

OUTBOX_DIRS: dict[str, str] = {"som": "app", "bog": "bog", "fc": "fc", "gov": "governance"}
SUBMISSION_RELPATHS: tuple[tuple[str, ...], ...] = (("inbox", "submissions"), ("archive", "submissions"))
DEFAULT_HORIZON_BUSINESS_DAYS = 10


class DashboardError(RuntimeError):
    """Named dashboard failure; the message says what to run or fill."""


class UnknownCycle(DashboardError):
    """No registered cycle matches the given committee and date; lists what is registered."""


@dataclass(frozen=True)
class Cycle:
    """One registry entry, key '<committee>:<YYYY-MM-DD>'."""

    key: str
    committee: str
    meeting_date: date
    materials_deadline: date
    lead_key: str
    lead_days: int
    departments_expected: tuple[str, ...] | None  # None = not recorded, never "none" ((),)
    registered_at: str

    def to_json(self) -> dict[str, Any]:
        """dates as ISO strings, departments_expected a list or null (never coerced to [])."""
        data = asdict(self)
        data["meeting_date"] = self.meeting_date.isoformat()
        data["materials_deadline"] = self.materials_deadline.isoformat()
        data["departments_expected"] = list(self.departments_expected) if self.departments_expected is not None else None
        return data


def _cycle_from_dict(data: dict) -> Cycle:
    dep = data.get("departments_expected")
    return Cycle(
        key=data["key"],
        committee=data["committee"],
        meeting_date=date.fromisoformat(data["meeting_date"]),
        materials_deadline=date.fromisoformat(data["materials_deadline"]),
        lead_key=data["lead_key"],
        lead_days=data["lead_days"],
        departments_expected=tuple(dep) if dep is not None else None,
        registered_at=data["registered_at"],
    )


def _root(root: Path | None) -> Path:
    if root is not None:
        return root
    from cpa.config import workspace

    return workspace()


def _registry_path(root: Path | None) -> Path:
    return _root(root).joinpath(*REGISTRY_RELPATH)


def load_registry(root: Path | None = None) -> dict:
    """Read logs/cycles.json; absent -> a fresh empty registry; corrupt -> DashboardError (never reset)."""
    p = _registry_path(root)
    if not p.is_file():
        return {"version": REGISTRY_VERSION, "current_fymm": None, "periods": {}, "cycles": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DashboardError(f"{p} is not valid JSON; fix or move it aside, it is never reset automatically") from exc


def save_registry(registry: dict, root: Path | None = None) -> Path:
    """Atomic write of logs/cycles.json (sort_keys, ensure_ascii=False)."""
    p = _registry_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(registry, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return fsutil.atomic_write(p, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))


def register_cycle(
    meeting_date: date,
    *,
    committee: str = "som",
    departments: Sequence[str] | None = None,
    root: Path | None = None,
) -> Cycle:
    """B9: register a meeting. deadline = meeting_date - lead calendar days (unit unconfirmed, always
    labelled). The lead is read ONLY through cpa.config.assumption(COMMITTEES[committee]); a missing or
    null key raises MissingAssumption before any write (R071). `departments` defaults to None, meaning
    "not recorded" (never stored as an empty tuple, which outstanding() would misread as "nobody
    expected"). When departments is given, it replaces the stored list; when it is None on a
    re-registration, the previously recorded list (if any) is left unchanged. SOM creates
    outbox/app/<YYYY-MM-DD>/."""
    if committee not in COMMITTEES:
        raise DashboardError(f"unknown committee {committee!r}; choose one of {sorted(COMMITTEES)}")
    from cpa import manifest
    from cpa.config import assumption

    lead_key = COMMITTEES[committee]
    lead_days = assumption(lead_key)  # MissingAssumption propagates before any write
    if not isinstance(lead_days, int) or isinstance(lead_days, bool):
        raise DashboardError(f"{lead_key} must be a whole number of calendar days, got {lead_days!r}")
    deadline = meeting_date - timedelta(days=lead_days)
    ws = _root(root)
    registry = load_registry(ws)
    key = f"{committee}:{meeting_date.isoformat()}"
    existing = registry["cycles"].get(key)
    if departments is not None:
        dep_tuple: tuple[str, ...] | None = tuple(departments)
    elif existing is not None:
        prev = existing.get("departments_expected")
        dep_tuple = tuple(prev) if prev is not None else None
    else:
        dep_tuple = None
    registered_at = existing["registered_at"] if existing is not None else manifest.utc_now_iso()
    cycle = Cycle(
        key=key,
        committee=committee,
        meeting_date=meeting_date,
        materials_deadline=deadline,
        lead_key=lead_key,
        lead_days=lead_days,
        departments_expected=dep_tuple,
        registered_at=registered_at,
    )
    registry["cycles"][key] = cycle.to_json()
    save_registry(registry, ws)
    if committee == "som":
        (ws / "outbox" / "app" / meeting_date.isoformat()).mkdir(parents=True, exist_ok=True)
    return cycle


def _find_cycle(registry: dict, committee: str, cycle_date: date) -> Cycle:
    key = f"{committee}:{cycle_date.isoformat()}"
    data = registry["cycles"].get(key)
    if data is None:
        registered = sorted(k for k in registry["cycles"] if k.startswith(f"{committee}:"))
        raise UnknownCycle(
            f"no registered {committee} cycle for {cycle_date.isoformat()}; registered: {registered or 'none'}"
        )
    return _cycle_from_dict(data)


def _submitted_departments(cycle: Cycle, *, root: Path | None = None) -> frozenset[str]:
    """Departments with a received submission folder: every immediate child directory under each of
    SUBMISSION_RELPATHS whose sidecar (manifest.read(folder); a folder with no sidecar is skipped,
    never counted submitted, never raised on) has a `received` date on or after the cycle's
    registered_at, or no `received` key at all (counted submitted either way). Read-only."""
    from cpa import manifest

    ws = _root(root)
    registered_date = date.fromisoformat(cycle.registered_at[:10])
    found: set[str] = set()
    for parts in SUBMISSION_RELPATHS:
        base = ws.joinpath(*parts)
        if not base.is_dir():
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            try:
                data = manifest.read(folder)
            except manifest.MissingManifest:
                continue
            department = data.get("department")
            if not department:
                continue
            received = data.get("received")
            if received:
                if date.fromisoformat(str(received)[:10]) < registered_date:
                    continue
            found.add(department)
    return frozenset(found)


def outstanding(cycle: date, *, committee: str = "som", root: Path | None = None) -> dict:
    """B24/R249 feed: submissions received vs outstanding by department for the registered cycle.
    UnknownCycle when no such cycle is registered; DashboardError when departments_expected is None,
    so an unrecorded list is never read as "nobody outstanding". Returns {cycle, expected, submitted,
    outstanding}, where `cycle` is the matched Cycle's to_json()."""
    ws = _root(root)
    registry = load_registry(ws)
    found = _find_cycle(registry, committee, cycle)
    if found.departments_expected is None:
        raise DashboardError(
            f"{committee} cycle {cycle.isoformat()} has no departments recorded; re-run "
            "register-cycle with --department, once per expected department"
        )
    expected = set(found.departments_expected)
    submitted = _submitted_departments(found, root=ws) & expected
    missing = sorted(expected - submitted)
    return {
        "cycle": found.to_json(),
        "expected": sorted(expected),
        "submitted": sorted(submitted),
        "outstanding": missing,
    }


def open_flags(root: Path | None = None) -> list[dict]:
    """Every outbox *.xlsx/*.xlsm (not "~$", not a manifest sidecar) whose Verification tab is missing,
    present but not the first sheet, or whose summary cell is not CLEAN."""
    from cpa import bigxlsx, manifest
    from cpa.verify import CLEAN, VERIFICATION_SHEET

    ws = _root(root)
    outbox = ws / "outbox"
    rows: list[dict] = []
    if not outbox.is_dir():
        return rows
    for path in sorted(outbox.rglob("*")):
        if not path.is_file() or path.name.startswith("~$") or manifest.is_sidecar(path):
            continue
        if path.suffix.lower() not in (".xlsx", ".xlsm"):
            continue
        try:
            names = bigxlsx.sheet_names(path)
            if VERIFICATION_SHEET not in names:
                summary = "NO VERIFICATION TAB"
            elif names[0] != VERIFICATION_SHEET:
                summary = "VERIFICATION TAB NOT FIRST"
            else:
                first_row = next(iter(bigxlsx.iter_rows(path, VERIFICATION_SHEET)))
                cell = first_row[1] if len(first_row) > 1 else None
                summary = None if cell == CLEAN else str(cell)
        except bigxlsx.BigXlsxError as exc:
            summary = f"UNREADABLE: {exc}"
        if summary is not None:
            rows.append({"path": manifest.to_rel(path), "summary": summary})
    return rows


def _landed_vs_missing(root: Path) -> list[dict]:
    """Inputs landed vs missing (via cpa.state) for the workflows that key off the current fiscal
    period; empty (with a note in build()) until a period has been recorded elsewhere."""
    registry = load_registry(root)
    fymm = registry.get("current_fymm")
    if not fymm:
        return []
    from cpa import state

    rows: list[dict] = []
    for rule in state.rules():
        if rule.key != "fymm":
            continue
        landed, missing = [], []
        for template in rule.needs:
            pattern = template.replace("{key}", fymm)
            hits = [p for p in root.glob(pattern) if p.is_file()]
            (landed if hits else missing).append(pattern)
        rows.append({"workflow": rule.workflow, "landed": landed, "missing": missing})
    return rows


def _ready_files(root: Path) -> list[str]:
    from cpa import manifest

    outbox = root / "outbox"
    if not outbox.is_dir():
        return []
    return sorted(
        manifest.to_rel(p) for p in outbox.rglob("*") if p.is_file() and not manifest.is_sidecar(p) and not p.name.startswith("~$")
    )


def build(
    *, root: Path | None = None, today: date | None = None, horizon_business_days: int = DEFAULT_HORIZON_BUSINESS_DAYS
) -> tuple[Path, str]:
    """B22: write logs/dashboard.md and return (path, morning message). Sections, in order: Due (every
    registered cycle with meeting_date >= today, sorted; deadline rendered with its calendar-day
    count), Missing (inputs landed vs missing per cpa.state's readiness rules for the current fiscal
    period, plus submitted-vs-outstanding by department for every registered SOM cycle whose
    departments_expected is recorded -- one recorded without departments is listed under Missing as
    "expected departments not recorded", never crashing the build), Ready (files under outbox/), Open
    verification flags (open_flags())."""
    from cpa.periods import business_days_between, load_holidays

    ws = _root(root)
    today = today or date.today()
    registry = load_registry(ws)
    cycles = [_cycle_from_dict(v) for v in registry["cycles"].values()]
    due = sorted((c for c in cycles if c.meeting_date >= today), key=lambda c: c.meeting_date)

    try:
        holidays = load_holidays()
        holiday_note = None
    except Exception as exc:  # MissingReference or similar; never treated as zero holidays
        holidays, holiday_note = [], str(exc)

    lines: list[str] = [f"# Dashboard ({today.isoformat()})", ""]

    lines.append("## Due")
    if not due:
        lines.append("- nothing registered")
    for c in due:
        if holiday_note:
            soon = " (due soon: unknown)"
        else:
            bdays = business_days_between(today, c.materials_deadline, holidays)
            soon = " (due soon)" if 0 <= bdays <= horizon_business_days else ""
        lines.append(
            f"- {c.committee} {c.meeting_date.isoformat()}: materials due {c.materials_deadline.isoformat()} "
            f"(meeting - {c.lead_days} calendar days){soon}"
        )
    if holiday_note:
        lines.append(f"- Needs you: {holiday_note}")
    lines.append("")

    lines.append("## Missing")
    for row in _landed_vs_missing(ws):
        if row["missing"]:
            lines.append(f"- {row['workflow']}: missing {', '.join(row['missing'])}")
    missing_lines_before = len(lines)
    for c in cycles:
        if c.committee != "som":
            continue
        if c.departments_expected is None:
            lines.append(f"- {c.key}: expected departments not recorded (register-cycle --department)")
            continue
        try:
            out = outstanding(c.meeting_date, committee=c.committee, root=ws)
        except DashboardError:
            continue
        if out["outstanding"]:
            lines.append(f"- {c.key}: outstanding {', '.join(out['outstanding'])}")
    if len(lines) == missing_lines_before and not any(r["missing"] for r in _landed_vs_missing(ws)):
        lines.append("- nothing missing")
    lines.append("")

    ready = _ready_files(ws)
    lines.append("## Ready")
    lines += [f"- {r}" for r in ready] or ["- nothing in outbox yet"]
    lines.append("")

    flags = open_flags(ws)
    lines.append("## Open verification flags")
    lines += [f"- {f['path']}: {f['summary']}" for f in flags] or ["- none"]
    lines.append("")

    text = "\n".join(lines) + "\n"
    path = ws.joinpath(*DASHBOARD_RELPATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fsutil.atomic_write(path, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))

    message = f"{len(due)} due, {len(ready)} ready in outbox, {len(flags)} verification flags open"
    from cpa import state

    state.record_run("cpa-dashboard", outputs=[path])
    return path, message


# ---------------------------------------------------------------- CLI


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not YYYY-MM-DD") from exc


def _root_arg(args: argparse.Namespace) -> Path | None:
    return Path(args.root) if getattr(args, "root", None) else None


def _cli_build(args: argparse.Namespace) -> int:
    import sys

    try:
        path, message = build(
            root=_root_arg(args), today=args.today, horizon_business_days=args.horizon
        )
    except DashboardError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        flags = open_flags(_root_arg(args))
        print(json.dumps({"dashboard": str(path), "message": message, "flags": len(flags)}, ensure_ascii=False))
    else:
        print(message)
        print(path)
    return 0


def _cli_register_cycle(args: argparse.Namespace) -> int:
    import sys

    from cpa.config import MissingAssumption

    try:
        cycle = register_cycle(
            args.date, committee=args.committee, departments=args.department, root=_root_arg(args)
        )
    except (MissingAssumption, DashboardError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(cycle.to_json(), ensure_ascii=False))
    else:
        print(f"{cycle.key}: materials due {cycle.materials_deadline.isoformat()}")
    return 0


def _cli_outstanding(args: argparse.Namespace) -> int:
    import sys

    try:
        result = outstanding(args.cycle, committee=args.committee, root=_root_arg(args))
    except DashboardError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"outstanding: {', '.join(result['outstanding']) or 'none'}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """U00 hook: top-level `dashboard` with build, register-cycle, outstanding."""
    top = subparsers.add_parser("dashboard", help="Cycle registry and the due/missing/ready dashboard.")
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    p = sub.add_parser("build", help="Write logs/dashboard.md and print the morning message.")
    p.add_argument("--today", type=_parse_date, default=None)
    p.add_argument("--horizon", type=int, default=DEFAULT_HORIZON_BUSINESS_DAYS, help="Business days for due soon.")
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cli_build)

    p = sub.add_parser("register-cycle", help="Register a committee meeting date (B9).")
    p.add_argument("--date", dest="date", type=_parse_date, required=True)
    p.add_argument("--committee", choices=sorted(COMMITTEES), default="som")
    p.add_argument("--department", action="append", default=None, help="Repeat for each expected department.")
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cli_register_cycle)

    p = sub.add_parser("outstanding", help="Departments expected but not yet submitted for a cycle.")
    p.add_argument("--cycle", dest="cycle", type=_parse_date, required=True)
    p.add_argument("--committee", choices=sorted(COMMITTEES), default="som")
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cli_outstanding)
