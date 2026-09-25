"""Record analyst-reviewed workflow observations locally for maintainer review.

Browser-workflow discovery and correction: stores ordered steps and blockers, not telemetry,
credentials, screenshots, exports, or executable automation. Hard rules 13-14: no posting or
source-system writes. Notes never modify report navigation or leave outbox automatically.
This is not a secret detector: the analyst must review every field before storage and again
before sharing. Missing workspace stops instead of creating a substitute.
"""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime, timezone
from uuid import uuid4


def record(*, workflow: str, mode: str, steps: list[str], blockers: list[str], reviewed: bool):
    """Save reviewed descriptive notes and a run record, with no upload or navigation edits."""
    from cpa import config, fsutil, state

    if not reviewed:
        raise ValueError("Analyst review and consent are required before recording notes")
    if workflow not in ("crf", "je-refund", "other") or mode not in ("manual", "observed", "browser-assisted"):
        raise ValueError("Unknown workflow or observation mode")
    if not steps or any(not s.strip() for s in steps):
        raise ValueError("At least one nonempty, analyst-confirmed step is required")
    text = "\n".join([*steps, *blockers])
    if len(text) > 20000:
        raise ValueError("Keep notes below 20000 characters; do not attach exports")
    if re.search(r"https?://\S+|\b(password|token|cookie|authorization)\s*[:=]", text, re.I):
        raise ValueError("Remove URLs and credential values; keep bookmarks in the private reference configuration")
    root = config.workspace()
    if not root.is_dir():
        raise ValueError("Workspace is not accessible; no substitute will be created")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / "outbox" / "feedback" / fsutil.safe_filename(f"{stamp}_{workflow}_{uuid4().hex}.json")
    payload = {"workflow": workflow, "mode": mode, "steps": steps, "blockers": blockers,
               "reviewed": True, "recorded_at": datetime.now(timezone.utc).isoformat(),
               "status": "analyst-reviewed observation; not an approved automation plan"}
    def write(tmp):
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
    with fsutil.guard_long_path(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fsutil.atomic_write(path, write)
    log = state.record_run("cpa-workflow-feedback", outputs=[path],
                           verification="Reviewed notes recorded locally; no automation plan changed",
                           needs_analyst=True, warnings=["Review and redact before manually sharing with maintainer"])
    return {"output": str(path), "run_record": str(log)}


def _cmd_record(args):
    from cpa.config import WorkspaceNotFound
    try:
        result = record(workflow=args.workflow, mode=args.mode, steps=args.step,
                        blockers=args.blocker, reviewed=args.reviewed)
    except (ValueError, OSError, WorkspaceNotFound) as exc:
        print(json.dumps({"error": str(exc), "complete": False}))
        return 1
    print(json.dumps(result))
    return 0


def register(subparsers) -> None:
    """Register import-cheap commands; observation text is never executed."""
    top = subparsers.add_parser("feedback", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True)
    leaf = sub.add_parser("record", help="Save reviewed, sanitized workflow notes locally and write a run record.")
    leaf.add_argument("--workflow", required=True, choices=("crf", "je-refund", "other"))
    leaf.add_argument("--mode", required=True, choices=("manual", "observed", "browser-assisted"))
    leaf.add_argument("--step", action="append", required=True)
    leaf.add_argument("--blocker", action="append", default=[])
    leaf.add_argument("--reviewed", action="store_true", help="Analyst reviewed all fields and approved local storage.")
    leaf.set_defaults(func=_cmd_record)
