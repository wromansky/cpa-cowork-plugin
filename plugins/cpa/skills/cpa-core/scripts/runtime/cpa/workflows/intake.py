"""Email intake (U17 "intake" part): B23 poll, B24 reminder drafts, D1 request brief, D7 answer recall.

Parses `.eml` with stdlib `email.message_from_bytes(..., policy=email.policy.default)` per
DECISIONS D11 -- no third-party mail parser. `.msg` (Outlook binary) is out of scope for this run
(D11); `UnsupportedFormat` names the extension and says to re-save as `.eml` or use the connector.

Classification (`classify`) uses only the sender address (against `reference/stakeholders.csv`,
role/department/email_pattern/category -- a Hopkins fact that ships as a header-only, empty file,
D18) and whether the message carries an attachment. **The email body is never read for
classification** (AGENTS.md, hard rule, R052): a message that looks like a filing instruction in
its body changes nothing about where anything lands. A message with an attachment from a sender not
in stakeholders.csv classifies OTHER rather than guessed (R054); a message with no attachment is
treated as an ad hoc request regardless of sender, since D1's whole job is "a request email becomes
a runnable brief with no typing by her" and requesters are not necessarily known department
administrators.

B23's "connector" is modelled as a folder of `.eml` files (`poll(mailbox_dir, ...)`): this is the
same shape as both the real Microsoft 365 connector's eventual export and the Cowork/browser-Outlook
fallback (guide 5.7), so the module does not change when the connector question (H-05-m365,
[UNCONFIRMED]) is answered -- only what fills the folder does. An absent mailbox_dir is "the
connector is unavailable": `ConnectorUnavailable` is raised, nothing is processed, nothing guessed
(R053). The watermark lives at `logs/state.json` -> `intake.last_seen` (cpa.state.load_state /
save_state, D19's own state.json layout already reserves the `intake` key).

D1's "tracker entry" output is filed through `cpa.workflows.tracker.add_request` (D6, the other part
of this unit, already built) -- intake.py never writes `logs/requests.csv` itself; that file's shape
is tracker.py's contract. Never sends the acknowledgment (R051): `ack.md` is written to disk only,
headed "DRAFT -- not sent"; no module imported here can reach mail, Teams, or a browser.
"""
from __future__ import annotations

import argparse
import csv
import email
import email.policy
import fnmatch
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any

MESSAGE_CLASSES: tuple[str, ...] = (
    "APP_SUBMISSION", "COMMITTEE_ANSWER", "LOOKBACK_DOC", "ADHOC_REQUEST", "OTHER",
)
STAKEHOLDERS_FILE = "stakeholders.csv"
STAKEHOLDERS_COLUMNS: tuple[str, ...] = ("role", "department", "email_pattern", "category")
REQUEST_FIELDS: tuple[str, ...] = (
    "requester", "department", "division", "period", "scope", "due_date", "requested_output",
)
NOT_STATED = "not stated"
SUPPORTED_SUFFIX = ".eml"
FOLDER_DESTS: dict[str, tuple[str, ...]] = {
    "LOOKBACK_DOC": ("inbox", "lookback_docs"),
    "COMMITTEE_ANSWER": ("staging", "app"),
}

__all__ = [
    "MESSAGE_CLASSES", "IntakeError", "ConnectorUnavailable", "UnsupportedFormat", "Stakeholder",
    "load_stakeholders", "parse_message", "classify", "brief", "recall", "poll", "draft_reminders", "register",
]


class IntakeError(RuntimeError):
    """Base for every intake failure."""


class ConnectorUnavailable(IntakeError):
    """B23/R053: the mailbox_dir folder standing in for the connector does not exist.

    Nothing is processed and the watermark does not move; the message names the path so the
    analyst knows exactly what to check or fix."""

    def __init__(self, mailbox_dir: Path) -> None:
        super().__init__(
            f"intake connector unavailable: {mailbox_dir} does not exist. Tell the analyst and stop; "
            "the fallback is a Cowork task on her open Outlook tab (guide 5.7). Never guess."
        )


class UnsupportedFormat(IntakeError):
    """A message file is not `.eml` (D11: `.msg` is out of scope this run)."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"{path.name}: unsupported message format {path.suffix or '(none)'!r}. "
            "Save As -> .eml in Outlook, or use the Microsoft 365 connector export; "
            ".msg parsing is not built (D11)."
        )


@dataclass(frozen=True)
class Stakeholder:
    role: str
    department: str
    email_pattern: str
    category: str


def _root(root: Path | None) -> Path:
    if root is not None:
        return root
    from cpa.config import workspace

    return workspace()


def load_stakeholders(root: Path | None = None) -> list[Stakeholder]:
    """Read reference/stakeholders.csv (workspace copy wins, cpa.config.reference_file).

    A Hopkins fact: it ships header-only (D18) so an unfilled file yields an empty list, never a
    fabricated row. Raises IntakeError if the header does not match STAKEHOLDERS_COLUMNS exactly."""
    from cpa.config import reference_file

    path = reference_file(STAKEHOLDERS_FILE)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != STAKEHOLDERS_COLUMNS:
            raise IntakeError(
                f"{path} has columns {reader.fieldnames}; expected {', '.join(STAKEHOLDERS_COLUMNS)}"
            )
        return [
            Stakeholder(
                role=(row.get("role") or "").strip(),
                department=(row.get("department") or "").strip(),
                email_pattern=(row.get("email_pattern") or "").strip(),
                category=(row.get("category") or "").strip(),
            )
            for row in reader
            if (row.get("email_pattern") or "").strip()
        ]


def parse_message(path: Path) -> EmailMessage:
    """Parse one `.eml` file with policy.default (D11). Raises UnsupportedFormat for any other suffix."""
    p = Path(path)
    if p.suffix.lower() != SUPPORTED_SUFFIX:
        raise UnsupportedFormat(p)
    with p.open("rb") as fh:
        return email.message_from_binary_file(fh, policy=email.policy.default)  # type: ignore[return-value]


def _sender_address(msg: EmailMessage) -> str:
    return parseaddr(str(msg.get("From", "")))[1].strip().lower()


def _message_date(msg: EmailMessage) -> datetime:
    dt = msg.get("Date")
    parsed = dt.datetime if dt is not None else None
    if parsed is None:
        raise IntakeError("message has no parseable Date header")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iter_attachments(msg: EmailMessage) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for part in msg.iter_attachments():
        filename = part.get_filename() or "attachment"
        payload = part.get_content()
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        out.append((filename, payload))
    return out


def _match_stakeholder(sender: str, stakeholders: list[Stakeholder]) -> Stakeholder | None:
    if not sender:
        return None
    for s in stakeholders:
        if fnmatch.fnmatch(sender, s.email_pattern.lower()):
            return s
    return None


def classify(msg: EmailMessage, stakeholders: list[Stakeholder]) -> tuple[str, Stakeholder | None]:
    """B23/D1 classification. Sender and attachment presence only -- never the body (R052).

    1. Sender matches a stakeholders.csv row with a known category -> that category.
    2. No attachment -> ADHOC_REQUEST.
    3. Attachment present, sender unmatched -> OTHER (R054, unsure)."""
    sender = _sender_address(msg)
    matched = _match_stakeholder(sender, stakeholders)
    has_attachment = bool(_iter_attachments(msg))
    if matched is not None and matched.category in MESSAGE_CLASSES:
        return matched.category, matched
    if not has_attachment:
        return "ADHOC_REQUEST", matched
    return "OTHER", matched


_LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z ]*)\s*:\s*(.+?)\s*$")


def _body_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    return content if isinstance(content, str) else str(content)


def _extract_fields(body: str) -> dict[str, str]:
    """Read only recognised `Label: value` lines (used for the brief's structured fields).

    Free text elsewhere in the body -- including anything that reads like an instruction -- is never
    acted on (R052); this function extracts values for the brief, it does not file anything."""
    labels = {
        "requester": ("requester", "submitted by", "from"),
        "department": ("department",),
        "division": ("division",),
        "period": ("period",),
        "scope": ("scope",),
        "due_date": ("due date", "due"),
        "requested_output": ("requested output", "output"),
    }
    found: dict[str, str] = {}
    for line in body.splitlines():
        m = _LABEL_RE.match(line)
        if not m:
            continue
        key_text, value = m.group(1).strip().casefold(), m.group(2).strip()
        for field, aliases in labels.items():
            if field in found:
                continue
            if key_text in aliases:
                found[field] = value
    return found


def _safe_slug(text: str, fallback: str = "message") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return slug[:60] or fallback


# ---------------------------------------------------------------- D1 brief


def brief(message_path: Path, *, root: Path | None = None) -> dict[str, Any]:
    """D1: parse one `.eml`, create requests/<id>/{brief.md,ack.md}, run D7 recall, file the tracker
    entry through cpa.workflows.tracker.add_request (the other part of this unit, already built).

    Classification here is NOVEL only: routing to D2-D5 needs those modules' own contracts, which
    this part does not own or import. Never sends ack.md (R051); no send call exists in this module."""
    from cpa import fsutil, manifest

    ws = _root(root)
    msg = parse_message(Path(message_path))
    stakeholders = load_stakeholders(ws)
    msg_class, matched = classify(msg, stakeholders)
    body = _body_text(msg)
    fields = _extract_fields(body)
    requester = fields.get("requester") or parseaddr(str(msg.get("From", "")))[0] or _sender_address(msg) or NOT_STATED
    department = fields.get("department") or (matched.department if matched else "") or "UNKNOWN"
    division = fields.get("division") or NOT_STATED
    period = fields.get("period") or NOT_STATED
    scope = fields.get("scope") or NOT_STATED
    due_date = fields.get("due_date") or NOT_STATED
    requested_output = fields.get("requested_output") or NOT_STATED

    try:
        received_dt = _message_date(msg)
    except IntakeError:
        received_dt = datetime.now(timezone.utc)
    received = received_dt.date()

    subject = str(msg.get("Subject", "") or "no subject")
    stamp = received_dt.strftime("%Y%m%dT%H%M%SZ")
    request_id = f"{stamp}_{_safe_slug(subject)}"
    folder = ws / "requests" / request_id
    folder.mkdir(parents=True, exist_ok=True)

    prior = recall(department, requested_output, period, root=ws)

    lines = [
        f"# Request {request_id}", "",
        f"Requester: {requester}", f"Department: {department}", f"Division: {division}",
        f"Period: {period}", f"Scope: {scope}", f"Due date: {due_date}",
        f"Requested output: {requested_output}", f"Classification: NOVEL", f"Subject: {subject}",
        f"Received: {received.isoformat()}", "",
        "## D7 answer recall",
    ]
    if prior:
        for p in prior:
            lines.append(f"- {p['path']} (age {p['age_days']} days)")
    else:
        lines.append("- no prior artifact found for this department and period")
    lines.append("")
    brief_text = "\n".join(lines) + "\n"
    brief_path = folder / "brief.md"

    def _write_brief(tmp: Path) -> None:
        tmp.write_text(brief_text, encoding="utf-8", newline="\n")

    fsutil.atomic_write(brief_path, _write_brief)
    manifest.write(
        brief_path, "email", "intake brief", "", received.isoformat(), row_count=1,
        inputs=[Path(message_path)], department=department, period=period, classification="NOVEL",
    )

    ack_lines = [
        "DRAFT -- not sent", "", f"To: {requester}", "",
        f"Thank you for your request ({scope}). We will deliver {requested_output} "
        f"by {due_date}.",
    ]
    ack_text = "\n".join(ack_lines) + "\n"
    ack_path = folder / "ack.md"

    def _write_ack(tmp: Path) -> None:
        tmp.write_text(ack_text, encoding="utf-8", newline="\n")

    fsutil.atomic_write(ack_path, _write_ack)
    manifest.write(ack_path, "derived", "intake acknowledgment draft", "", received.isoformat(),
                    row_count=1, inputs=[brief_path])

    from cpa.workflows import tracker

    tracker.add_request(
        request_id=request_id, requester=requester, received=received.isoformat(),
        due=due_date if due_date != NOT_STATED else "", classification="NOVEL", status="open",
        artifact_path="", sent_date="", root=ws,
    )

    return {
        "id": request_id, "brief": brief_path, "ack": ack_path, "classification": "NOVEL",
        "requester": requester, "department": department, "period": period, "recall": prior,
        "message_class": msg_class,
    }


# ---------------------------------------------------------------- D7 recall


def _age_days(path: Path, today: date | None = None) -> int:
    today = today or date.today()
    mtime = date.fromtimestamp(path.stat().st_mtime)
    return max((today - mtime).days, 0)


def recall(department: str, metric: str, period: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    """D7: prior artifacts for the same department and period, in requests/ and outbox/, with age.

    Matches on manifest `department`/`period` fields when a sidecar exists, else a case-insensitive
    substring match against the file's path. Never raises; no match is an empty list (R244's "before
    any rebuild" is met by calling this before any D2-D5 build starts, not by this function itself)."""
    from cpa import manifest

    ws = _root(root)
    dept_key = (department or "").strip().casefold()
    period_key = (period or "").strip().casefold()
    hits: list[dict[str, Any]] = []
    for base_name in ("requests", "outbox"):
        base = ws / base_name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or manifest.is_sidecar(path) or path.name.startswith("~$"):
                continue
            matched = False
            try:
                data = manifest.read(path)
            except manifest.MissingManifest:
                data = {}
            if data:
                if dept_key and dept_key == str(data.get("department", "")).strip().casefold():
                    if not period_key or period_key == str(data.get("period", "")).strip().casefold():
                        matched = True
            if not matched and dept_key:
                rel = manifest.to_rel(path).casefold()
                if dept_key in rel and (not period_key or period_key in rel):
                    matched = True
            if matched:
                hits.append({"path": manifest.to_rel(path), "age_days": _age_days(path)})
    return hits


# ---------------------------------------------------------------- B23 poll


def _folder_manifest_write(folder: Path, **data: Any) -> Path:
    """Write a folder-level sidecar (<folder>.manifest.json beside it), the shape dashboard.py's
    D28 `_submitted_departments` already reads via `manifest.read(folder)`. `manifest.write` cannot
    be reused here: it requires an existing plain file, and `folder` is a directory."""
    from cpa import fsutil, manifest

    target = manifest.sidecar(folder)
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fsutil.atomic_write(target, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))
    return target


def _file_attachments(dest: Path, msg: EmailMessage, *, sender: str, received: date, subject: str) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, content in _iter_attachments(msg):
        from cpa import fsutil

        safe = fsutil.safe_filename(filename) if filename else "attachment"
        target = dest / safe
        fsutil.atomic_write(target, lambda tmp, c=content: tmp.write_bytes(c))
        written.append(target)
    return written


def poll(mailbox_dir: Path, *, root: Path | None = None) -> dict[str, Any]:
    """B23: fetch messages since the watermark from `mailbox_dir` (a folder of `.eml` files standing
    in for the connector / Outlook fallback drop). ConnectorUnavailable if the folder is absent
    (R053); nothing is processed and the watermark is not moved. Advances `intake.last_seen` to the
    newest processed message's Date, saved only after every message in this batch is handled."""
    from cpa import state

    mailbox_dir = Path(mailbox_dir)
    if not mailbox_dir.is_dir():
        raise ConnectorUnavailable(mailbox_dir)

    ws = _root(root)
    stakeholders = load_stakeholders(ws)
    data = state.load_state()
    last_seen_raw = data.get("intake", {}).get("last_seen")
    last_seen = datetime.fromisoformat(last_seen_raw) if last_seen_raw else None

    messages: list[tuple[datetime, Path, EmailMessage]] = []
    for path in sorted(mailbox_dir.glob(f"*{SUPPORTED_SUFFIX}")):
        msg = parse_message(path)
        try:
            when = _message_date(msg)
        except IntakeError:
            continue
        if last_seen is not None and when <= last_seen:
            continue
        messages.append((when, path, msg))
    messages.sort(key=lambda t: t[0])

    counts = {c: 0 for c in MESSAGE_CLASSES}
    other: list[dict[str, str]] = []
    briefs: list[dict[str, Any]] = []
    filed: list[dict[str, str]] = []
    newest = last_seen

    for when, path, msg in messages:
        msg_class, matched = classify(msg, stakeholders)
        counts[msg_class] += 1
        sender = _sender_address(msg)
        subject = str(msg.get("Subject", "") or "no subject")
        received = when.date()

        if msg_class == "ADHOC_REQUEST":
            briefs.append(brief(path, root=ws))
        elif msg_class == "APP_SUBMISSION":
            dept = (matched.department if matched else "unknown_dept")
            dest = ws / "inbox" / "submissions" / f"{_safe_slug(dept)}_{_safe_slug(subject)}_{received.isoformat()}"
            written = _file_attachments(dest, msg, sender=sender, received=received, subject=subject)
            _folder_manifest_write(dest, sender=sender, received=received.isoformat(), subject=subject, department=dept)
            filed.append({"path": str(dest), "class": msg_class, "files": [str(w) for w in written]})
        elif msg_class in FOLDER_DESTS:
            key = (matched.department if matched else None) or _safe_slug(sender, "sender")
            dest = ws.joinpath(*FOLDER_DESTS[msg_class]) / _safe_slug(key)
            if msg_class == "COMMITTEE_ANSWER":
                dest = dest / "answers"
            written = _file_attachments(dest, msg, sender=sender, received=received, subject=subject)
            filed.append({"path": str(dest), "class": msg_class, "files": [str(w) for w in written]})
        else:  # OTHER
            other.append({"path": str(path), "sender": sender, "subject": subject})

        if newest is None or when > newest:
            newest = when

    if newest is not None:
        data.setdefault("intake", {})["last_seen"] = newest.isoformat()
        state.save_state(data)

    return {
        "counts": counts, "other": other, "briefs": [b["id"] for b in briefs], "filed": filed,
        "processed": len(messages),
    }


# ---------------------------------------------------------------- B24 reminder drafts


def _submitted_departments(registered_at: str, root: Path, crosswalk) -> dict[str, str]:
    """Return departments with in-cycle submission sidecars under inbox/ or archive/.

    Matches dashboard D28: sidecars are required; old dated submissions are ignored, while a
    manifest without `received` counts as submitted. This only reads files and never sends mail.
    """
    from cpa import crosswalk as crosswalk_module, manifest

    registered_date = date.fromisoformat(registered_at[:10])
    found: dict[str, str] = {}
    unmatched: list[str] = []
    for base_name in ("inbox", "archive"):
        base = root / base_name / "submissions"
        if not base.is_dir():
            continue
        for folder in sorted(p for p in base.rglob("*") if p.is_dir()):
            try:
                data = manifest.read(folder)
            except manifest.MissingManifest:
                continue
            department = str(data.get("department") or "").strip()
            if not department:
                continue
            canonical = crosswalk.lookup(department)
            if canonical is None:
                unmatched.append(department)
                continue
            received = str(data.get("received") or "").strip()
            if received and date.fromisoformat(received[:10]) < registered_date:
                continue
            canonical = str(canonical).strip()
            found.setdefault(canonical.casefold(), canonical)
    if unmatched:
        raise crosswalk_module.UnmatchedDepartment(unmatched, crosswalk.path)
    return found


def draft_reminders(
    cycle_date: str | date, outstanding: dict[str, Any], *, root: Path | None = None
) -> tuple[list[Path], list[str]]:
    """Create draft reminder files for outstanding departments not submitted in this cycle.

    `outstanding` follows `dashboard.outstanding()` (`cycle` metadata plus an `outstanding` list).
    Drafts are written only under outbox/app/<cycle>/emails; this function never sends them.
    Returns (draft paths, submitted department labels skipped).
    """
    from cpa import crosswalk as crosswalk_module, fsutil, manifest

    ws = _root(root)
    cycle_day = date.fromisoformat(cycle_date) if isinstance(cycle_date, str) else cycle_date
    if not isinstance(outstanding, dict):
        raise IntakeError("outstanding cycle data must be an object")
    cycle = outstanding.get("cycle")
    if not isinstance(cycle, dict):
        raise IntakeError("outstanding cycle data is missing cycle metadata and materials_deadline")
    deadline = str(cycle.get("materials_deadline") or "").strip()
    registered_at = str(cycle.get("registered_at") or "").strip()
    if not deadline:
        raise IntakeError("outstanding cycle data is missing materials_deadline")
    if not registered_at:
        raise IntakeError("outstanding cycle data is missing registered_at")
    try:
        date.fromisoformat(deadline)
        date.fromisoformat(registered_at[:10])
    except ValueError as exc:
        raise IntakeError("materials_deadline and registered_at must be ISO dates") from exc
    departments = outstanding.get("outstanding")
    if not isinstance(departments, list) or any(not isinstance(value, str) or not value.strip() for value in departments):
        raise IntakeError("outstanding must be a list of non-empty department labels")

    departments_crosswalk = crosswalk_module.load(ws / "reference" / "dept_crosswalk.csv")
    submitted = _submitted_departments(registered_at, ws, departments_crosswalk)
    canonical_departments: list[str] = []
    unmatched: list[str] = []
    for department in departments:
        canonical = departments_crosswalk.lookup(department.strip())
        if canonical is None:
            unmatched.append(department.strip())
        else:
            canonical_departments.append(str(canonical).strip())
    if unmatched:
        raise crosswalk_module.UnmatchedDepartment(unmatched, departments_crosswalk.path)

    # Finish validation of all input labels before writing any drafts.
    canonical_departments = list(dict.fromkeys(canonical_departments))
    skipped: list[str] = []
    drafts: list[Path] = []
    email_dir = ws / "outbox" / "app" / cycle_day.isoformat() / "emails"
    for label in canonical_departments:
        if label.casefold() in submitted:
            skipped.append(submitted[label.casefold()])
            continue
        safe = fsutil.safe_filename(label)
        email_dir.mkdir(parents=True, exist_ok=True)
        path = email_dir / f"{safe}_reminder.md"
        text = (
            "DRAFT -- not sent\n\n"
            f"To: {label}\n"
            "Subject: APP submission reminder\n\n"
            f"Our records show the APP submission is outstanding for the {cycle_day.isoformat()} cycle. "
            f"Please send the materials by {deadline}.\n"
        )
        fsutil.atomic_write(path, lambda tmp, content=text: tmp.write_text(content, encoding="utf-8", newline="\n"))
        manifest.write(
            path, "derived", "APP submission reminder draft", "", cycle_day.isoformat(),
            row_count=1, materials_deadline=deadline, department=label, sent=False,
        )
        drafts.append(path)
    return drafts, skipped


# ---------------------------------------------------------------- CLI


def _root_arg(args: argparse.Namespace) -> Path | None:
    return Path(args.root) if getattr(args, "root", None) else None


def _cli_brief(args: argparse.Namespace) -> int:
    import sys

    try:
        result = brief(Path(args.message), root=_root_arg(args))
    except IntakeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        payload = {k: (str(v) if isinstance(v, Path) else v) for k, v in result.items()}
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"{result['id']}: {result['brief']}")
    return 0


def _cli_recall(args: argparse.Namespace) -> int:
    hits = recall(args.department, args.metric, args.period, root=_root_arg(args))
    if args.json:
        print(json.dumps(hits, ensure_ascii=False))
    else:
        for h in hits:
            print(f"{h['path']}\t{h['age_days']} days")
        if not hits:
            print("no prior artifact found")
    return 0


def _cli_reminders(args: argparse.Namespace) -> int:
    import sys

    try:
        data = json.loads(args.outstanding.read_text(encoding="utf-8-sig"))
        drafts, skipped = draft_reminders(args.cycle, data, root=_root_arg(args))
    except (IntakeError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"drafted {len(drafts)} reminder(s); skipped submitted departments: {', '.join(skipped) or 'none'}")
    return 0


def _cli_poll(args: argparse.Namespace) -> int:
    import sys

    try:
        result = poll(Path(args.mailbox), root=_root_arg(args))
    except IntakeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"processed {result['processed']}; counts {result['counts']}")
        if result["other"]:
            print(f"OTHER ({len(result['other'])}): " + ", ".join(o["subject"] for o in result["other"]))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    top = subparsers.add_parser("intake", help="Email intake: poll, brief (D1), recall (D7).")
    sub = top.add_subparsers(dest="intake_command", required=True)

    p = sub.add_parser("brief", help="Turn one saved .eml into requests/<id>/brief.md + ack.md.")
    p.add_argument("--message", type=Path, required=True)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cli_brief)

    p = sub.add_parser("recall", help="D7: prior artifacts for a department/metric/period.")
    p.add_argument("--department", required=True)
    p.add_argument("--metric", default="")
    p.add_argument("--period", default="")
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cli_recall)

    p = sub.add_parser("reminders", help="B24: draft reminders for outstanding APP submissions; never send.")
    p.add_argument("--cycle", required=True, help="Cycle date, YYYY-MM-DD.")
    p.add_argument("--outstanding", type=Path, required=True, help="JSON from dashboard outstanding.")
    p.add_argument("--root", type=Path, default=None)
    p.set_defaults(func=_cli_reminders)

    p = sub.add_parser("poll", help="B23: fetch new messages from a mailbox folder since the watermark.")
    p.add_argument("--mailbox", type=Path, required=True)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cli_poll)
