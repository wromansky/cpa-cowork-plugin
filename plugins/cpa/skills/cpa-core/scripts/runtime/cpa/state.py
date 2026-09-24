"""Dispatcher state: what landed, what is ready to run, what ran, and run records.

Build-list items: the watched-folder engine (guide section 7), E2 archive move (never delete), run
records (guide 5.1 "Run records"). Rules enforced: R055 (never rerun a done period unless an input hash
changed), R056 (browser pulls are never dispatched), R057 (a changed input makes a done run stale),
R101 (nothing leaves outbox automatically: archive moves inbox files only). D13: a file that cannot be
read (OneDrive placeholder) is "unavailable", never new or missing. D19: rules that depend on another
unit's output format are declared by that unit as READINESS_RULES and collected lazily.

logs/state.json layout (guide 7.1): {"files": {rel: {sha256, first_seen, manifest}}, "runs":
{"<workflow>:<key>": {status, outputs, input_hashes, ended}}, "intake": {...}, "pulled": {fymm: [system]}}.
"""

from __future__ import annotations

import argparse
import json
import pkgutil
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from cpa import manifest

BROWSER_PREFIXES = ("cpa-pull-", "cpa-monthly-pull")
KEY_KINDS = ("fymm", "folder", "date")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

__all__ = [
    "Rule", "ScanResult", "ReadyWorkflow", "BASE_RULES", "rules", "register_rule", "unregister_rule",
    "load_state", "save_state", "scan", "ready", "mark", "mark_pulled", "archive", "record_run", "register",
]


@dataclass(frozen=True)
class Rule:
    """A workflow is ready for a key when every `needs` template matches at least one file.

    Templates are workspace-relative globs with `{key}`; `key` says how the key is read: `fymm` from the
    filename token, `folder` as the path segment in the {key} position, `date` as a YYYY-MM-DD token.
    `extra` (optional, U12 additive): `extra(workspace, key)` returns further input files the run needs (their
    hashes count toward staleness) or None when the key is not ready for a reason a glob cannot express (a
    triage classification, a file named by a value inside another input). It must not raise."""

    workflow: str
    needs: tuple[str, ...]
    key: str
    extra: Callable[[Path, str], list[Path] | None] | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.key not in KEY_KINDS:
            raise ValueError(f"{self.workflow}: key must be one of {KEY_KINDS}")
        if not self.needs or any("{key}" not in n for n in self.needs[:1]):
            raise ValueError(f"{self.workflow}: the first needs template must contain {{key}}")


# Guide 7.2 rules that depend only on landed files. Extensions are left open (".*") because exports
# may be .xlsx or .csv; manifest sidecars are always excluded.
BASE_RULES: tuple[Rule, ...] = (
    Rule("cpa-charge-forecast", ("inbox/tableau/charges_by_day_{key}.*",), "fymm"),
    Rule("cpa-app-triage", ("inbox/submissions/{key}/*",), "folder"),
    Rule("cpa-budget-workbook", ("inbox/sap/co_lineitems_{key}.*",), "fymm"),
    Rule("cpa-master-data", ("inbox/powerbi/dept_productivity_{key}.*",), "fymm"),
    Rule("cpa-bog-refresh", ("inbox/tableau/charges_by_day_{key}.*", "inbox/powerbi/dept_productivity_{key}.*",
                             "inbox/cognos/dept_financials_{key}.*"), "fymm"),
    Rule("cpa-fc-refresh", ("inbox/tableau/charges_by_day_{key}.*", "inbox/powerbi/dept_productivity_{key}.*",
                            "inbox/cognos/dept_financials_{key}.*", "outbox/budget/{key}/Budget_Workbook_{key}.*"), "fymm"),
    Rule("cpa-crf", ("inbox/cognos/crf_{key}.*",), "fymm"),
    Rule("cpa-cag-match", ("inbox/qgenda/tasks_*_{key}.*",), "date"),
)

_EXTRA_RULES: dict[str, Rule] = {}


def register_rule(rule: Rule) -> None:
    """Add a readiness rule owned by a workflow unit (D19). Browser pulls are refused (R056)."""
    if rule.workflow.startswith(BROWSER_PREFIXES):
        raise ValueError(f"{rule.workflow}: browser pull workflows are interactive and never dispatched")
    _EXTRA_RULES[rule.workflow] = rule


def unregister_rule(workflow: str) -> None:
    _EXTRA_RULES.pop(workflow, None)


def _collect_module_rules() -> None:
    """Import cpa.workflows.* (import-cheap by contract) and register their READINESS_RULES."""
    try:
        import cpa.workflows as pkg
    except ImportError:
        return
    for info in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        import importlib

        mod = importlib.import_module(info.name)
        for rule in getattr(mod, "READINESS_RULES", ()):
            register_rule(rule)


def rules() -> list[Rule]:
    _collect_module_rules()
    return list(BASE_RULES) + list(_EXTRA_RULES.values())


# ---------------------------------------------------------------- state file


def _ws() -> Path:
    from cpa.config import workspace

    return workspace()


def _state_path() -> Path:
    return _ws() / "logs" / "state.json"


def load_state() -> dict:
    p = _state_path()
    data = json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
    for k in ("files", "runs", "intake", "pulled"):
        data.setdefault(k, {})
    return data


def save_state(data: dict) -> Path:
    from cpa import fsutil

    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return fsutil.atomic_write(p, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))


# ---------------------------------------------------------------- scan


@dataclass
class ScanResult:
    new: list[Path] = field(default_factory=list)
    changed: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    unavailable: list[Path] = field(default_factory=list)
    missing_manifest: list[Path] = field(default_factory=list)


def _inbox_files(ws: Path) -> list[Path]:
    inbox = ws / "inbox"
    if not inbox.is_dir():
        return []
    return sorted(p for p in inbox.rglob("*") if p.is_file() and not manifest.is_sidecar(p))


def scan() -> ScanResult:
    """Hash every inbox file and compare with logs/state.json; records what it saw."""
    ws = _ws()
    data = load_state()
    res = ScanResult()
    for p in _inbox_files(ws):
        rel = manifest.to_rel(p)
        try:
            digest = manifest.sha256_of(p)
        except OSError:
            res.unavailable.append(p)
            continue
        prev = data["files"].get(rel)
        if prev is None:
            res.new.append(p)
        elif prev.get("sha256") != digest:
            res.changed.append(p)
        else:
            res.unchanged.append(p)
        has_manifest = manifest.exists(p)
        if not has_manifest:
            res.missing_manifest.append(p)
        data["files"][rel] = {
            "sha256": digest,
            "first_seen": prev.get("first_seen") if prev else manifest.utc_now_iso(),
            "manifest": has_manifest,
        }
    save_state(data)
    return res


# ---------------------------------------------------------------- readiness


@dataclass
class ReadyWorkflow:
    workflow: str
    key: str
    inputs: list[Path]
    reason: str  # new | stale | retry


def _matches(ws: Path, pattern: str) -> list[Path]:
    return sorted(p for p in ws.glob(pattern) if p.is_file() and not manifest.is_sidecar(p))


def _keys_for(ws: Path, rule: Rule) -> set[str]:
    from cpa import periods

    first = rule.needs[0]
    found: set[str] = set()
    if rule.key == "folder":
        prefix = first.split("{key}")[0].rstrip("/")
        base = ws.joinpath(*prefix.split("/")) if prefix else ws
        if base.is_dir():
            found = {d.name for d in base.iterdir() if d.is_dir()}
        return found
    for p in _matches(ws, first.replace("{key}", "*")):
        if rule.key == "fymm":
            try:
                found.add(periods.fymm_from_filename(p.name))
            except periods.AmbiguousFilename:
                continue
        else:
            m = _DATE_RE.search(p.name)
            if m:
                found.add(m.group(1))
    return found


def _inputs_for(ws: Path, rule: Rule, key: str) -> list[Path] | None:
    files: list[Path] = []
    for tmpl in rule.needs:
        hits = _matches(ws, tmpl.replace("{key}", key))
        if not hits:
            return None
        files.extend(hits)
    if rule.extra is not None:
        more = rule.extra(ws, key)
        if more is None:
            return None
        files.extend(more)
    return files


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {manifest.to_rel(p): manifest.sha256_of(p) for p in paths}


def ready() -> list[ReadyWorkflow]:
    """Workflows whose inputs are all present and that have not run for those exact inputs (R055, R057)."""
    ws = _ws()
    runs = load_state()["runs"]
    out: list[ReadyWorkflow] = []
    for rule in rules():
        for key in sorted(_keys_for(ws, rule)):
            inputs = _inputs_for(ws, rule, key)
            if inputs is None:
                continue
            run = runs.get(f"{rule.workflow}:{key}")
            if run is None:
                reason = "new"
            elif run.get("status") != "done":
                reason = "retry"
            else:
                try:
                    current = _hashes(inputs)
                except OSError:
                    continue
                if current == run.get("input_hashes"):
                    continue
                reason = "stale"
            out.append(ReadyWorkflow(rule.workflow, key, inputs, reason))
    return out


def mark(workflow: str, key: str, status: str, outputs: list[Path | str], inputs: list[Path] | None = None) -> None:
    """Record a run's status, outputs, and the hashes of the inputs it used."""
    if inputs is None:
        rule = next((r for r in rules() if r.workflow == workflow), None)
        inputs = (_inputs_for(_ws(), rule, key) or []) if rule else []
    data = load_state()
    data["runs"][f"{workflow}:{key}"] = {
        "status": status,
        "outputs": [manifest.to_rel(o) for o in outputs],
        "input_hashes": _hashes(inputs),
        "ended": manifest.utc_now_iso(),
    }
    save_state(data)


def mark_pulled(fymm: str, system: str) -> None:
    data = load_state()
    systems = data["pulled"].setdefault(fymm, [])
    if system not in systems:
        systems.append(system)
    save_state(data)


# ---------------------------------------------------------------- archive and run records


def _unique(target: Path) -> Path:
    if not target.exists():
        return target
    n = 2
    while True:
        candidate = target.with_name(f"{target.stem}_{n}{target.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def archive(paths: list[Path | str], today: date | None = None) -> list[Path]:
    """Move processed inbox files (and their manifests) to archive/<system>/<date>/. Never deletes (E2)."""
    ws = _ws().resolve()
    stamp = (today or date.today()).isoformat()
    moved = []
    for raw in paths:
        p = Path(raw).resolve()
        try:
            rel = p.relative_to(ws / "inbox")
        except ValueError as exc:
            raise ValueError(f"{p} is not under inbox/: only processed inbox files are archived; nothing else moves") from exc
        system = rel.parts[0]
        dest_dir = ws / "archive" / system / stamp
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = _unique(dest_dir / p.name)
        side = manifest.sidecar(p)
        shutil.move(str(p), str(dest))
        if side.is_file():
            shutil.move(str(side), str(manifest.sidecar(dest)))
        moved.append(dest)
    return moved


def record_run(
    skill: str,
    inputs: list[Path | str] = (),
    outputs: list[Path | str] = (),
    verification: str = "",
    warnings: list[str] = (),
    duration_s: float = 0.0,
    needs_analyst: bool = False,
) -> Path:
    """Write logs/runs/<UTC timestamp>_<skill>.json (guide 5.1 run records)."""
    from cpa import fsutil

    runs_dir = _ws() / "logs" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = _unique(runs_dir / fsutil.safe_filename(f"{stamp}_{skill}.json"))
    rec = {
        "skill": skill,
        "inputs": [manifest.to_rel(i) for i in inputs],
        "outputs": [manifest.to_rel(o) for o in outputs],
        "verification": verification,
        "warnings": list(warnings),
        "duration_s": duration_s,
        "needs_analyst": needs_analyst,
        "ended": manifest.utc_now_iso(),
    }
    text = json.dumps(rec, indent=2, ensure_ascii=False) + "\n"
    return fsutil.atomic_write(target, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))


# ---------------------------------------------------------------- CLI


def _cmd_scan(a: argparse.Namespace) -> int:
    res = scan()
    for label in ("new", "changed", "unchanged", "unavailable", "missing_manifest"):
        for p in getattr(res, label):
            print(f"{label}\t{manifest.to_rel(p)}")
    return 0


def _cmd_ready(a: argparse.Namespace) -> int:
    rows = [{"workflow": r.workflow, "key": r.key, "reason": r.reason, "inputs": [manifest.to_rel(i) for i in r.inputs]}
            for r in ready()]
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['workflow']}\t{r['key']}\t{r['reason']}")
    return 0


def _cmd_mark(a: argparse.Namespace) -> int:
    mark(a.workflow, a.key, a.status, a.output or [])
    return 0


def _cmd_mark_pulled(a: argparse.Namespace) -> int:
    mark_pulled(a.fymm, a.system)
    return 0


def _cmd_archive(a: argparse.Namespace) -> int:
    for p in archive(a.files):
        print(manifest.to_rel(p))
    return 0


def _cmd_record(a: argparse.Namespace) -> int:
    print(record_run(a.skill, a.input or [], a.output or [], a.verification, a.warning or [], a.duration, a.needs_analyst))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `state scan|ready|mark|mark-pulled|archive|record`. Import-cheap."""
    top = subparsers.add_parser("state", help="Dispatcher state: what landed, what is ready, what ran.")
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    p = sub.add_parser("scan", help="Hash inbox files and report new, changed, unavailable, and missing manifests.")
    p.set_defaults(func=_cmd_scan)
    p = sub.add_parser("ready", help="List workflows whose inputs are present and not yet run for those inputs.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_ready)
    p = sub.add_parser("mark", help="Record a run's status and outputs.")
    p.add_argument("workflow")
    p.add_argument("key")
    p.add_argument("status", choices=("done", "failed", "running", "blocked"))
    p.add_argument("--output", action="append")
    p.set_defaults(func=_cmd_mark)
    p = sub.add_parser("mark-pulled", help="Record that a system's export landed for a fiscal month.")
    p.add_argument("fymm")
    p.add_argument("system")
    p.set_defaults(func=_cmd_mark_pulled)
    p = sub.add_parser("archive", help="Move processed inbox files to archive/<system>/<date>/ (never deletes).")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=_cmd_archive)
    p = sub.add_parser("record", help="Write the run record for a skill run to logs/runs/.")
    p.add_argument("--skill", required=True)
    p.add_argument("--input", action="append")
    p.add_argument("--output", action="append")
    p.add_argument("--verification", default="")
    p.add_argument("--warning", action="append")
    p.add_argument("--duration", type=float, default=0.0)
    p.add_argument("--needs-analyst", action="store_true", dest="needs_analyst")
    p.set_defaults(func=_cmd_record)
