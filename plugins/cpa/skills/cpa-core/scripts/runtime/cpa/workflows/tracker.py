"""Request tracker (D6, U17 "tracker" part): logs/requests.csv and the weekly aging digest.

`intake.py` (D1/B23, a different part of the same unit) and U16's `dashboard.py` (B22, D28 --
not a confirmed Python contract yet) coordinate with this module only through the eight CSV
columns, fixed exactly as handed down: id, requester, received, due, classification, status,
artifact_path, sent_date. No column is added here.

Build List D6 text is "none closes without an artifact path or a **declined note**" -- two
alternatives for one closing act. Since the column set is pinned (no separate `declined_note`
field), both alternatives share the `artifact_path` cell: for status "closed" it holds the
artifact's path, for status "declined" it holds the decline reason text. The rule enforced is
uniform (R080/R156): any status in CLOSED_STATUSES requires that cell non-blank, checked before
any write, never silently defaulted.

`add_request` is the cross-part contract D1/intake.py calls to file a new request, or to upsert
(re-call with the same id) as a request progresses. `digest()` writes logs/tracker_digest.md,
which is how this feeds B22 (D6 "feeds B22") -- no direct Python import either direction.
"""
from __future__ import annotations

import argparse
import csv
import io
from datetime import date
from pathlib import Path
from typing import Any

from cpa import fsutil

COLUMNS: tuple[str, ...] = (
    "id", "requester", "received", "due", "classification", "status", "artifact_path", "sent_date",
)
REQUESTS_RELPATH: tuple[str, ...] = ("logs", "requests.csv")
DIGEST_RELPATH: tuple[str, ...] = ("logs", "tracker_digest.md")
CLOSED_STATUSES: frozenset[str] = frozenset({"closed", "declined"})
AGING_BUCKETS: tuple[str, ...] = ("0-3", "4-7", "8-14", "15+")

__all__ = [
    "COLUMNS", "CLOSED_STATUSES", "AGING_BUCKETS",
    "TrackerError", "RequestNotFound", "RequestClosedWithoutProof",
    "log_path", "read_requests", "add_request", "update_status",
    "weekly_aging_digest", "digest", "register",
]


class TrackerError(RuntimeError):
    """Base for every tracker failure."""


class RequestNotFound(TrackerError):
    """No row with the given id in logs/requests.csv."""

    def __init__(self, request_id: str) -> None:
        super().__init__(f"no request {request_id!r} in {'/'.join(REQUESTS_RELPATH)}")


class RequestClosedWithoutProof(TrackerError):
    """A closing status (CLOSED_STATUSES) was written with an empty artifact_path cell (R080/R156)."""

    def __init__(self, request_id: str, status: str) -> None:
        note = "a declined note" if status == "declined" else "an artifact path"
        super().__init__(
            f"request {request_id!r} cannot be set to status {status!r} without {note} "
            "in the artifact_path column"
        )


def _root(root: Path | None) -> Path:
    if root is not None:
        return root
    from cpa.config import workspace

    return workspace()


def log_path(root: Path | None = None) -> Path:
    return _root(root).joinpath(*REQUESTS_RELPATH)


def read_requests(root: Path | None = None) -> list[dict[str, str]]:
    """Every row of logs/requests.csv as a dict; [] when the file does not exist yet.

    Raises TrackerError if an existing file's header does not match COLUMNS exactly -- it is
    never silently rewritten (matches cpa.workflows.charge_forecast's MAPE-log convention)."""
    path = log_path(root)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise TrackerError(
                f"{path} has columns {reader.fieldnames}; expected {', '.join(COLUMNS)}. "
                "It was not rewritten; fix or move it and run again"
            )
        return [dict(r) for r in reader]


def _write_requests(rows: list[dict[str, str]], root: Path | None) -> Path:
    path = log_path(root)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(COLUMNS), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    text = buf.getvalue()

    def write(tmp: Path) -> None:
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    path.parent.mkdir(parents=True, exist_ok=True)
    return fsutil.atomic_write(path, write)


def _enforce_closed(row: dict[str, str]) -> None:
    status = (row.get("status") or "").strip().lower()
    if status in CLOSED_STATUSES and not (row.get("artifact_path") or "").strip():
        raise RequestClosedWithoutProof(row["id"], status)


def add_request(
    *,
    request_id: str,
    requester: str,
    received: str,
    due: str,
    classification: str,
    status: str = "open",
    artifact_path: str = "",
    sent_date: str = "",
    root: Path | None = None,
) -> dict[str, str]:
    """File a new request, or upsert (replace) the row for `request_id` if it already exists.

    This is the function D1/intake.py calls to file every request; it is the U17 cross-part
    contract. Enforces the closing rule before any write: nothing is written on failure."""
    row = {
        "id": request_id, "requester": requester, "received": received, "due": due,
        "classification": classification, "status": status, "artifact_path": artifact_path,
        "sent_date": sent_date,
    }
    _enforce_closed(row)
    rows = read_requests(root)
    for i, existing in enumerate(rows):
        if existing["id"] == request_id:
            rows[i] = row
            break
    else:
        rows.append(row)
    _write_requests(rows, root)
    return row


def update_status(
    request_id: str,
    *,
    status: str,
    artifact_path: str | None = None,
    sent_date: str | None = None,
    root: Path | None = None,
) -> dict[str, str]:
    """Change `status` (and optionally `artifact_path`/`sent_date`) on an existing row.

    Raises RequestNotFound if the id is absent; enforces the closing rule (R080/R156) before any
    write, so a rejected call leaves the CSV exactly as it was."""
    rows = read_requests(root)
    for i, row in enumerate(rows):
        if row["id"] != request_id:
            continue
        updated = dict(row)
        updated["status"] = status
        if artifact_path is not None:
            updated["artifact_path"] = artifact_path
        if sent_date is not None:
            updated["sent_date"] = sent_date
        _enforce_closed(updated)
        rows[i] = updated
        _write_requests(rows, root)
        return updated
    raise RequestNotFound(request_id)


def _age_bucket(days: int) -> str:
    if days <= 3:
        return "0-3"
    if days <= 7:
        return "4-7"
    if days <= 14:
        return "8-14"
    return "15+"


def weekly_aging_digest(*, today: date | None = None, root: Path | None = None) -> dict[str, Any]:
    """Open requests (status not in CLOSED_STATUSES) bucketed by calendar days since `received`.

    Returns {"as_of": iso date, "buckets": {bucket: [row, ...]}, "overdue": [row, ...],
    "total_open": n}. A request is "overdue" when its `due` date is before `today`, independent
    of its bucket. Does not write a file (see digest())."""
    as_of = today or date.today()
    buckets: dict[str, list[dict[str, str]]] = {b: [] for b in AGING_BUCKETS}
    overdue: list[dict[str, str]] = []
    total = 0
    for row in read_requests(root):
        status = (row.get("status") or "").strip().lower()
        if status in CLOSED_STATUSES:
            continue
        total += 1
        received = date.fromisoformat(row["received"])
        days = (as_of - received).days
        buckets[_age_bucket(max(days, 0))].append(row)
        due_str = (row.get("due") or "").strip()
        if due_str and date.fromisoformat(due_str) < as_of:
            overdue.append(row)
    return {"as_of": as_of.isoformat(), "buckets": buckets, "overdue": overdue, "total_open": total}


def _render_digest(result: dict[str, Any]) -> str:
    lines = [f"# Request tracker aging digest -- {result['as_of']}", "", f"Open requests: {result['total_open']}", ""]
    for bucket in AGING_BUCKETS:
        rows = result["buckets"][bucket]
        lines.append(f"## {bucket} days ({len(rows)})")
        if rows:
            for r in rows:
                lines.append(f"- {r['id']}: {r['requester']} -- {r['classification']} (due {r['due']})")
        else:
            lines.append("- none")
        lines.append("")
    lines.append(f"## Overdue ({len(result['overdue'])})")
    if result["overdue"]:
        for r in result["overdue"]:
            lines.append(f"- {r['id']}: {r['requester']} -- due {r['due']}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def digest(*, today: date | None = None, root: Path | None = None) -> Path:
    """Compute weekly_aging_digest and write it to logs/tracker_digest.md (atomic). Feeds B22."""
    result = weekly_aging_digest(today=today, root=root)
    text = _render_digest(result)
    path = _root(root).joinpath(*DIGEST_RELPATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(tmp: Path) -> None:
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    return fsutil.atomic_write(path, write)


# ---------------------------------------------------------------- CLI


def _cmd_digest(args: argparse.Namespace) -> int:
    import json

    today = date.fromisoformat(args.today) if args.today else None
    root = args.root if getattr(args, "root", None) else None
    result = weekly_aging_digest(today=today, root=root)
    path = digest(today=today, root=root)
    if args.json:
        payload = dict(result)
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"wrote {path}")
        print(f"open requests: {result['total_open']}; overdue: {len(result['overdue'])}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    top = subparsers.add_parser("tracker", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="tracker_command", required=True)

    d = sub.add_parser("digest", help="Write the weekly aging digest (logs/tracker_digest.md).")
    d.add_argument("--today", type=str, default=None, help="Override today's date, YYYY-MM-DD.")
    d.add_argument("--root", type=Path, default=None, help="Override the workspace root.")
    d.add_argument("--json", action="store_true", help="Print the digest result as JSON.")
    d.set_defaults(func=_cmd_digest)
