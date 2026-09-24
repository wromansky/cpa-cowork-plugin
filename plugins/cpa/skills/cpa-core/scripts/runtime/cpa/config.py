"""Workspace resolution, assumptions access, and reference-file lookup for every cpa module.

Build-list items: C14 assumptions maintainer (stale and unconfirmed flags), guide section 9 config.py.
Hard rules enforced: 15 (an unconfirmed value is never defaulted: absent or null raises
MissingAssumption naming the key). D03: importing this module touches no file; WORKSPACE resolves
only when accessed. D13: workspace order is CPA_WORKSPACE, then ~/OneDrive/CPA-Workspace, then a
home folder starting "OneDrive" that holds CPA-Workspace. D18: later units append their own sections
to reference/assumptions.yaml.
"""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT: Path = Path(__file__).parent.parent
ASSUMPTIONS_NAME = "assumptions.yaml"
WORKSPACE_DIRNAME = "CPA-Workspace"
STALE_AFTER_DAYS = 92  # C14: "flags stale values quarterly"

__all__ = [
    "ROOT", "ConfigError", "MissingAssumption", "WorkspaceNotFound", "MissingReference",
    "workspace", "assumptions_path", "load_assumptions", "assumption", "reference_file",
    "template_map", "propose", "review_report", "register",
]


class ConfigError(Exception):
    """Base for every configuration failure in cpa."""


class MissingAssumption(ConfigError, KeyError):
    """A required assumptions key is absent or null. Carries `.key` (dotted) and `.path`."""

    def __init__(self, key: str, path: Path, reason: str = "missing") -> None:
        self.key, self.path = key, path
        super().__init__(
            f"assumption '{key}' is {reason} in {path}. Fill it in {ASSUMPTIONS_NAME} "
            "(ask the analyst; never guess a value)"
        )

    def __str__(self) -> str:  # KeyError would otherwise repr-quote the message
        return self.args[0]


class WorkspaceNotFound(ConfigError):
    """No CPA workspace could be located."""


class MissingReference(ConfigError):
    """A reference file, template map, or reference data row the code needs does not exist."""


def __getattr__(name: str) -> Path:
    """Lazy module attribute WORKSPACE (guide section 9) so importing never touches the disk (D03)."""
    if name == "WORKSPACE":
        return workspace()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def workspace() -> Path:
    """Resolve the workspace root (D13). CPA_WORKSPACE wins and need not exist yet (rollover init creates it)."""
    env = os.environ.get("CPA_WORKSPACE")
    if env:
        return Path(env)
    home = Path.home()
    plain = home / "OneDrive" / WORKSPACE_DIRNAME
    if plain.is_dir():
        return plain
    try:
        children = sorted(p for p in home.iterdir() if p.is_dir() and p.name.startswith("OneDrive"))
    except OSError:
        children = []
    for child in children:
        if (child / WORKSPACE_DIRNAME).is_dir():
            return child / WORKSPACE_DIRNAME
    raise WorkspaceNotFound(
        f"no {WORKSPACE_DIRNAME} folder found under {home} or any OneDrive folder there. "
        "Set the CPA_WORKSPACE environment variable to the workspace folder, or run `python -m cpa rollover init`"
    )


def _workspace_or_none() -> Path | None:
    try:
        return workspace()
    except WorkspaceNotFound:
        return None


def assumptions_path() -> Path:
    """CPA_ASSUMPTIONS env, else the workspace copy if present, else the repository copy."""
    env = os.environ.get("CPA_ASSUMPTIONS")
    if env:
        return Path(env)
    ws = _workspace_or_none()
    if ws is not None and (ws / "reference" / ASSUMPTIONS_NAME).is_file():
        return ws / "reference" / ASSUMPTIONS_NAME
    return ROOT / "reference" / ASSUMPTIONS_NAME


def _read_yaml(path: Path) -> Any:
    import yaml

    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise MissingReference(f"{path} does not exist") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc


def load_assumptions(path: Path | str | None = None) -> dict:
    """Parse the assumptions file. An empty file is no keys; anything but a mapping is a ConfigError."""
    p = Path(path) if path is not None else assumptions_path()
    data = _read_yaml(p)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{p} must be a YAML mapping of sections to values")
    return data


def assumption(*keys: str, path: Path | str | None = None) -> Any:
    """Return the value at the key path, e.g. assumption("rates", "deans_tax_pct") or ("rates.deans_tax_pct").

    Absent or null raises MissingAssumption naming the dotted key and the file. There is deliberately no
    default parameter (hard rule 15)."""
    parts = [seg for k in keys for seg in str(k).split(".") if seg]
    if not parts:
        raise ValueError("assumption() needs at least one key")
    p = Path(path) if path is not None else assumptions_path()
    node: Any = load_assumptions(p)
    dotted = ".".join(parts)
    for seg in parts:
        if not isinstance(node, dict) or seg not in node:
            raise MissingAssumption(dotted, p, "missing")
        node = node[seg]
    if node is None:
        raise MissingAssumption(dotted, p, "null (unconfirmed)")
    return node


def reference_file(name: str) -> Path:
    """The workspace reference/<name> if present, else the repository copy, else MissingReference."""
    ws = _workspace_or_none()
    for base in ([ws / "reference"] if ws is not None else []) + [ROOT / "reference"]:
        candidate = base / name
        if candidate.is_file():
            return candidate
    raise MissingReference(f"reference file {name} not found in the workspace or the repository reference folder")


def template_map(name: str) -> dict:
    """Load reference/template_maps/<name>.yaml, workspace copy first (her edits win), else MissingReference."""
    ws = _workspace_or_none()
    bases = ([ws / "reference" / "template_maps"] if ws is not None else []) + [ROOT / "reference" / "template_maps"]
    for base in bases:
        candidate = base / f"{name}.yaml"
        if candidate.is_file():
            data = _read_yaml(candidate)
            if not isinstance(data, dict):
                raise ConfigError(f"{candidate} must be a YAML mapping")
            return data
    raise MissingReference(f"template map {name}.yaml not found in the workspace or the repository")


def propose(key: str, value: Any, note: str = "") -> Path:
    """Write a proposed value to <workspace>/reference/proposed/<key>.yaml for her to paste in (D03).

    Never edits assumptions.yaml."""
    import yaml

    from cpa import fsutil

    target_dir = workspace().joinpath("reference", "proposed")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / fsutil.safe_filename(f"{key}.yaml")
    body = {
        "key": key,
        "value": value,
        "note": note,
        "proposed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ"),
        "how_to_apply": f"Copy the value into {ASSUMPTIONS_NAME} at {key}, then delete this file.",
    }
    text = yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
    fsutil.atomic_write(target, lambda tmp: tmp.write_text(text, encoding="utf-8", newline="\n"))
    return target


def review_report(today: date | None = None, path: Path | str | None = None) -> dict:
    """C14: which review.quarterly_keys are still null, and whether the last review is over a quarter old."""
    p = Path(path) if path is not None else assumptions_path()
    data = load_assumptions(p)
    review = data.get("review") or {}
    unconfirmed = []
    for key in review.get("quarterly_keys") or []:
        try:
            assumption(key, path=p)
        except MissingAssumption:
            unconfirmed.append(key)
    last = review.get("last_reviewed")
    if isinstance(last, str):
        last = date.fromisoformat(last)
    today = today or date.today()
    stale = last is None or (today - last).days > STALE_AFTER_DAYS
    return {"path": str(p), "unconfirmed": unconfirmed, "stale": stale, "last_reviewed": str(last) if last else None}


# ---------------------------------------------------------------- CLI


def _cmd_where(args: argparse.Namespace) -> int:
    ws = _workspace_or_none()
    print(f"workspace: {ws if ws is not None else 'NOT FOUND (set CPA_WORKSPACE)'}")
    print(f"assumptions: {assumptions_path()}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    rep = review_report()
    print(f"assumptions: {rep['path']}")
    print(f"last reviewed: {rep['last_reviewed'] or 'never'}{' (STALE, review this quarter)' if rep['stale'] else ''}")
    if rep["unconfirmed"]:
        print("unconfirmed (null, code will stop when it needs them):")
        for key in rep["unconfirmed"]:
            print(f"  {key}")
    return 1 if rep["stale"] or rep["unconfirmed"] else 0


def _cmd_propose(args: argparse.Namespace) -> int:
    import yaml

    value = yaml.safe_load(args.value)
    print(propose(args.key, value, note=args.note))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `config where|check|propose`. Import-cheap: no file access here."""
    top = subparsers.add_parser("config", help="Workspace and assumptions: where they are, what is unconfirmed.")
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    p = sub.add_parser("where", help="Print the resolved workspace and assumptions file.")
    p.set_defaults(func=_cmd_where)
    p = sub.add_parser("check", help="List unconfirmed quarterly keys and whether the review is stale (exit 1 if so).")
    p.set_defaults(func=_cmd_check)
    p = sub.add_parser("propose", help="Write a proposed value to reference/proposed/ for the analyst to paste in.")
    p.add_argument("key", help="Dotted key, e.g. rates.deans_tax_pct")
    p.add_argument("value", help="Value as YAML, e.g. 6.0")
    p.add_argument("--note", default="", help="Where the value came from.")
    p.set_defaults(func=_cmd_propose)
