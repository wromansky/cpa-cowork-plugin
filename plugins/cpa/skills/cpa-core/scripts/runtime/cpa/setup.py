"""cpa.setup - provision the Cowork sandbox interpreter for the bundled runtime.

`python -m cpa setup check` reports, as JSON, whether the interpreter running this module can
import every exact-pinned package declared by the payload's dependencies.json; `python -m cpa
setup install` installs missing or mismatched pins into a versioned, user-owned package target
inside the Cowork sandbox through pip (list-argument subprocess, never a shell, bounded timeout)
and re-verifies honestly afterwards. It never writes to system Python or the analyst's computer. This is the only place in the product that installs packages: no workflow skill
installs, upgrades or removes anything. In a repository checkout (no dependencies.json beside
cpa/) both commands are no-ops that name scripts/bootstrap.* as the developer path.

Build-list items: Cowork sandbox provisioning (docs/SETUP.md step 6 runtime check; the launcher's
`--check` reports, cpa.setup fixes). D09: exact pins only, taken from the integrity-verified
payload metadata - never a range, never an upgrade of an already-satisfied pin. Hard rules
enforced: none of the 15 directly. D13: list-argument subprocess, no shell, UTF-8, no /tmp.
D03: register() is import-cheap - no file I/O, no assumptions, no workspace resolution.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import platform
import re
import site
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

__all__ = [
    "PIP_TIMEOUT_SECONDS",
    "DEV_NOTE",
    "metadata_path",
    "load_metadata",
    "marker_applies",
    "installed_version",
    "evaluate",
    "register",
]

# Bounded pip run: a sandbox install of a few pinned wheels finishes well inside this; a hang is a
# reported failure, not a stalled session.
PIP_TIMEOUT_SECONDS = 600

# Developer-mode note: in a repository checkout the environment is managed by the bootstrap
# scripts, and cpa.setup deliberately changes nothing there.
DEV_NOTE = (
    "repository checkout detected: the developer environment is managed by scripts/bootstrap.* "
    "(bootstrap.ps1 on Windows, bootstrap.sh on Linux/mac); cpa setup changes nothing here"
)


def metadata_path() -> Path | None:
    """The payload's dependencies.json when running from the bundled runtime, else None.

    The launcher puts the runtime directory on sys.path, so cpa/ sits beside dependencies.json
    only in the bundle. A repository checkout has no dependencies.json beside cpa/ and is
    developer mode."""
    candidate = Path(__file__).resolve().parent.parent / "dependencies.json"
    return candidate if candidate.is_file() else None


def load_metadata(path: Path) -> dict:
    """Read and validate a dependencies.json file.

    Raises ValueError when the file is not a JSON object with a list of {name, version, marker}
    entries whose name and version are strings. Marker is None, "win32" or "not-win32" from the
    build script; any other string is passed through and treated as applicable (fail toward
    reporting, never toward claiming ready)."""
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get("requirements"), list):
        raise ValueError("dependencies.json must be a JSON object with a 'requirements' list")
    version = data.get("cpa_version")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version):
        raise ValueError("dependencies.json must contain a safe cpa_version")
    for entry in data["requirements"]:
        if not isinstance(entry, dict):
            raise ValueError(f"requirement entry is not an object: {entry!r}")
        if not isinstance(entry.get("name"), str) or not isinstance(entry.get("version"), str):
            raise ValueError(f"requirement entry needs string name and version: {entry!r}")
        marker = entry.get("marker")
        if marker is not None and not isinstance(marker, str):
            raise ValueError(f"requirement marker must be null or a string: {entry!r}")
    return data


def marker_applies(marker: str | None) -> bool:
    """Whether a requirement marker applies on this platform.

    None applies everywhere; "win32" on Windows only; "not-win32" everywhere else. Any other
    string is treated as applicable: a pin that cannot be placed is reported, not dropped."""
    if marker is None:
        return True
    is_win = platform.system() == "Windows"
    if marker == "win32":
        return is_win
    if marker == "not-win32":
        return not is_win
    return True


def installed_version(name: str) -> str | None:
    """The version of `name` installed for this interpreter, or None when not installed."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def evaluate(metadata: dict) -> list[dict]:
    """Status of every applicable requirement: satisfied, missing or mismatched.

    Requirements whose marker does not apply on this platform are dropped - they are not
    requirements here. Each row carries name, version (expected), marker, installed (None when
    absent) and status."""
    rows = []
    for entry in metadata["requirements"]:
        if not marker_applies(entry.get("marker")):
            continue
        installed = installed_version(entry["name"])
        if installed is None:
            status = "missing"
        elif installed != entry["version"]:
            status = "mismatched"
        else:
            status = "satisfied"
        rows.append({
            "name": entry["name"],
            "version": entry["version"],
            "marker": entry.get("marker"),
            "installed": installed,
            "status": status,
        })
    return rows


def _pip_available() -> bool:
    """Whether pip is importable in this interpreter (checked before any subprocess is started)."""
    return importlib.util.find_spec("pip") is not None


def install_target(version: str) -> Path:
    """Versioned, user-owned package directory for the Cowork session runtime."""
    return Path(site.getuserbase()) / "cpa-cowork" / version


def _add_install_target(version: str) -> Path:
    """Expose this payload's isolated packages to imports and metadata discovery."""
    target = install_target(version)
    value = str(target)
    if value not in sys.path:
        sys.path.insert(0, value)
        importlib.invalidate_caches()
    return target


def _pip_argv(pins: Sequence[str], version: str) -> list[str]:
    """Install exact pins into a private target directory, avoiding PEP 668 system writes."""
    return [
        sys.executable, "-m", "pip", "install", "--target", str(install_target(version)), "--upgrade", "--no-deps",
        "--disable-pip-version-check", "--no-input", *pins,
    ]


def _pip_install(pins: Sequence[str], version: str) -> subprocess.CompletedProcess:
    """Run pip once for every pin (list arguments, no shell, bounded timeout)."""
    return subprocess.run(
        _pip_argv(pins, version),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=PIP_TIMEOUT_SECONDS,
    )


def _json(payload: dict) -> None:
    """Print a report as UTF-8-safe JSON (ensure_ascii) on stdout."""
    print(json.dumps(payload, indent=2, ensure_ascii=True))


def _cmd_check(args: argparse.Namespace) -> int:
    """`setup check`: JSON report of the pinned packages this interpreter can import.

    Bundle mode: exit 0 when every applicable pin is satisfied, 1 otherwise (or when the
    metadata is unreadable). Developer mode (no payload metadata): exit 0 with the bootstrap
    note. The report is an environment statement, not a fix."""
    meta = args.metadata if args.metadata is not None else metadata_path()
    if meta is None:
        _json({"mode": "dev", "ready": True, "note": DEV_NOTE})
        return 0
    try:
        metadata = load_metadata(Path(meta))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        _json({"mode": "bundle", "ready": False,
               "error": f"dependency metadata unreadable: {type(exc).__name__}: {exc}"})
        return 1
    _add_install_target(str(metadata.get("cpa_version", "unknown")))
    rows = evaluate(metadata)
    missing = [row["name"] for row in rows if row["status"] == "missing"]
    mismatched = [f'{row["name"]}=={row["version"]}' for row in rows if row["status"] == "mismatched"]
    ready = not missing and not mismatched
    _json({
        "mode": "bundle",
        "ready": ready,
        "cpa_version": metadata.get("cpa_version"),
        "install_target": str(install_target(str(metadata.get("cpa_version", "unknown")))),
        "python": {"version": platform.python_version(), "minimum": metadata.get("python_minimum")},
        "requirements": rows,
        "missing": missing,
        "mismatched": mismatched,
    })
    return 0 if ready else 1


def _cmd_install(args: argparse.Namespace) -> int:
    """`setup install`: install the missing or mismatched pins into the Cowork-only package target.

    Exact pins only, from the payload metadata; nothing else is installed, upgraded or removed.
    Re-verifies after the pip run and reports honestly: exit 0 only when every applicable pin is
    satisfied afterwards. Developer mode is a no-op."""
    meta = args.metadata if args.metadata is not None else metadata_path()
    if meta is None:
        _json({"mode": "dev", "installed": [], "ready": True, "note": DEV_NOTE})
        return 0
    try:
        metadata = load_metadata(Path(meta))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        _json({"mode": "bundle", "installed": [], "ready": False,
               "error": f"dependency metadata unreadable: {type(exc).__name__}: {exc}"})
        return 1
    version = str(metadata.get("cpa_version", "unknown"))
    target = _add_install_target(version)
    rows = evaluate(metadata)
    targets = [f'{row["name"]}=={row["version"]}' for row in rows if row["status"] in ("missing", "mismatched")]
    if not targets:
        _json({"mode": "bundle", "installed": [], "ready": True,
               "note": "nothing to install; every applicable pin is satisfied"})
        return 0
    if not _pip_available():
        _json({"mode": "bundle", "installed": [], "ready": False,
               "error": "pip is not importable in this interpreter; no install attempted"})
        return 1
    try:
        proc = _pip_install(targets, version)
    except subprocess.TimeoutExpired:
        _json({"mode": "bundle", "installed": [], "ready": False,
               "error": f"pip install timed out after {PIP_TIMEOUT_SECONDS} seconds; no verification performed"})
        return 1
    except OSError as exc:
        _json({"mode": "bundle", "installed": [], "ready": False,
               "error": f"pip could not be started: {type(exc).__name__}: {exc}"})
        return 1
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
        _json({"mode": "bundle", "installed": [], "ready": False,
               "error": "pip install failed", "detail": tail, "install_target": str(target)})
        return 1
    rows = evaluate(metadata)
    missing = [row["name"] for row in rows if row["status"] == "missing"]
    mismatched = [f'{row["name"]}=={row["version"]}' for row in rows if row["status"] == "mismatched"]
    ready = not missing and not mismatched
    _json({"mode": "bundle", "installed": targets, "ready": ready,
           "missing": missing, "mismatched": mismatched, "install_target": str(target)})
    return 0 if ready else 1


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `setup check|install`. Import-cheap: no file I/O, no assumptions (cpa/cli.py rule 3)."""
    top = subparsers.add_parser(
        "setup",
        help="Provision the Cowork sandbox interpreter: check or install the exact pinned runtime packages.",
    )
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    p = sub.add_parser(
        "check",
        help="Report missing or mismatched pinned packages as JSON (exit 1 when not ready).",
    )
    p.add_argument(
        "--metadata", type=Path, default=None,
        help="Path to dependencies.json (default: the payload's, when running from the bundle).",
    )
    p.set_defaults(func=_cmd_check)
    p = sub.add_parser(
        "install",
        help="Install missing or mismatched pinned packages into the Cowork sandbox package target (exact pins only).",
    )
    p.add_argument(
        "--metadata", type=Path, default=None,
        help="Path to dependencies.json (default: the payload's, when running from the bundle).",
    )
    p.set_defaults(func=_cmd_install)
