"""Health check and monthly effort report (E5 Build List :380-383, E6 :385-388).

`run` invokes pytest programmatically (DECISIONS.md:96 -- from this module's own Python code, list
argv, never `shell=True`; no skill shells out to bare `pytest`). `dryrun` checks last month's run
status for every `cpa.state` readiness rule without invoking another unit's workflow module (most are
unbuilt; D19 already isolates readiness rules per owner). `effort` reads `logs/runs/*.json`
(`cpa.state.record_run`'s output) for one calendar month. `notify` is R023/R233's single end-of-run
message, silent when nothing needs her.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO_TESTS = Path(__file__).resolve().parents[2] / "tests"
DRAFT_BANNER = "DRAFT - for her review, never sent automatically"

EXIT_OK = 0
EXIT_ISSUES = 1


class HealthcheckError(Exception):
    """Base for healthcheck failures."""


@dataclass
class TestRunResult:
    exit_code: int
    duration_s: float
    output_tail: str


def run(tests_path: Path | None = None, *, extra_args: list[str] = ()) -> TestRunResult:
    """Run the pytest suite (or `tests_path`) in a child interpreter, programmatically (list argv, no
    shell). Returns the exit code and the tail of combined output; never raises on test failure."""
    target = Path(tests_path) if tests_path is not None else REPO_TESTS
    started = datetime.now()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(target), *extra_args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    duration = (datetime.now() - started).total_seconds()
    output = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(output.splitlines()[-40:])
    return TestRunResult(exit_code=proc.returncode, duration_s=duration, output_tail=tail)


def dryrun() -> list[dict]:
    """For each `cpa.state.rules()` entry: last calendar month's status. A fymm-keyed rule looks up
    `<workflow>:<fymm>` in state.json's runs; a non-fymm rule (folder/date keyed) reports "n/a" since
    last month has no single fymm key for it. Reports drift, never invokes a workflow module."""
    from cpa import periods, state

    today = date.today()
    prior_month = today.month - 1 or 12
    prior_year = today.year - 1 if today.month == 1 else today.year
    prior_first = date(prior_year, prior_month, 1)
    fymm = periods.fymm(prior_first)
    runs = state.load_state()["runs"]
    out: list[dict] = []
    for rule in state.rules():
        if rule.key != "fymm":
            out.append({"workflow": rule.workflow, "period": None, "status": f"n/a (key={rule.key})", "drift": False})
            continue
        run_rec = runs.get(f"{rule.workflow}:{fymm}")
        status = run_rec.get("status") if run_rec else "no run recorded"
        out.append({"workflow": rule.workflow, "period": fymm, "status": status, "drift": status != "done"})
    return out


def _month_bounds(month: str) -> tuple[str, str]:
    """Inclusive local-date [start, end) as ISO date strings for a "YYYY-MM" month string."""
    year, mon = (int(x) for x in month.split("-"))
    start = date(year, mon, 1)
    end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return start.isoformat(), end.isoformat()


@dataclass
class EffortReport:
    month: str
    hours_by_skill: dict[str, float]
    flags_raised: int
    records_counted: int
    path: Path


def _load_runs(ws: Path) -> list[dict]:
    runs_dir = ws / "logs" / "runs"
    if not runs_dir.is_dir():
        return []
    records = []
    for p in sorted(runs_dir.glob("*.json")):
        try:
            records.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def effort(month: str, *, root: Path | None = None) -> EffortReport:
    """From logs/runs/*.json: hours by skill (duration_s summed / 3600), warnings-count as flags
    raised, over one calendar month (grain noted in the report -- her fiscal calendar can differ).
    Writes outbox/healthcheck/<month>/Effort_Report_<month>.md (draft) plus a JSON sidecar."""
    from cpa import config, manifest

    ws = Path(root) if root is not None else config.workspace()
    start, end = _month_bounds(month)
    records = [r for r in _load_runs(ws) if start <= str(r.get("ended", ""))[:10] < end]
    hours: dict[str, float] = {}
    flags_raised = 0
    for r in records:
        skill = r.get("skill", "unknown")
        hours[skill] = hours.get(skill, 0.0) + float(r.get("duration_s", 0.0)) / 3600.0
        flags_raised += len(r.get("warnings") or [])
    out_dir = ws / "outbox" / "healthcheck" / month
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"Effort_Report_{month}.md"
    lines = [
        DRAFT_BANNER, "",
        f"period: {month} (calendar month) | status: actual | source: logs/runs/ | as-of: {manifest.utc_now_iso()}",
        "", "## Automated hours by workflow",
    ]
    for skill, h in sorted(hours.items()):
        lines.append(f"- {skill}: {h:.2f} h")
    if not hours:
        lines.append("- no runs recorded for this month")
    lines += ["", f"## Verification flags raised: {flags_raised}", "",
              "hygiene.effort_success_measures is unconfirmed; no baseline to compare against yet."]
    from cpa import fsutil

    fsutil.atomic_write(report_path, lambda tmp: tmp.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n"))
    manifest.write(report_path, "healthcheck", "E6 effort report", "", date.today().isoformat(),
                    row_count=len(records), review="draft")
    return EffortReport(month=month, hours_by_skill=hours, flags_raised=flags_raised,
                        records_counted=len(records), path=report_path)


def notify(ran: list[str], outbox: list[Any], flagged: list[str], blocked: list[str]) -> str | None:
    """R023/R233: one end-of-run message naming what ran, what is in outbox, what is flagged, what is
    blocked. Returns None (silent) when outbox, flagged and blocked are all empty."""
    if not outbox and not flagged and not blocked:
        return None
    return (f"ran: {', '.join(ran) or 'nothing'} | outbox: {len(outbox)} item(s) | "
            f"flagged: {', '.join(flagged) or 'none'} | blocked: {', '.join(blocked) or 'none'}")


# ---------------------------------------------------------------- CLI


def _cmd_run(a: argparse.Namespace) -> int:
    result = run(a.path)
    if a.json:
        print(json.dumps({"exit_code": result.exit_code, "duration_s": result.duration_s}, indent=2))
    else:
        print(result.output_tail)
        print(f"exit_code={result.exit_code} duration_s={result.duration_s:.1f}")
    return EXIT_OK if result.exit_code == 0 else EXIT_ISSUES


def _cmd_dryrun(a: argparse.Namespace) -> int:
    rows = dryrun()
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['workflow']}\t{row['period']}\t{row['status']}\t{'DRIFT' if row['drift'] else 'ok'}")
    return EXIT_OK if not any(r["drift"] for r in rows) else EXIT_ISSUES


def _cmd_effort(a: argparse.Namespace) -> int:
    result = effort(a.month)
    if a.json:
        print(json.dumps({"month": result.month, "hours_by_skill": result.hours_by_skill,
                          "flags_raised": result.flags_raised, "path": str(result.path)}, indent=2))
    else:
        print(result.path)
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `healthcheck run|dryrun|effort`. Import-cheap (D03)."""
    top = subparsers.add_parser("healthcheck", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    p = sub.add_parser("run", help="Run the pytest suite programmatically (D12; no skill shells out to bare pytest).")
    p.add_argument("--path", type=Path, default=None, help="Tests directory (default: the repository's tests/).")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("dryrun", help="Report last month's run status for every watched workflow.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_dryrun)

    p = sub.add_parser("effort", help="Monthly effort report from logs/runs/ (E6).")
    p.add_argument("--month", required=True, help="YYYY-MM, calendar month.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_effort)
