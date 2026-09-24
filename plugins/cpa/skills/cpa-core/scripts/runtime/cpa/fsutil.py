"""Windows-safe file writes: same-directory temp file, os.replace, one retry on PermissionError.

The one shared writer for every cpa/ module (owned by U00). A module that writes an output calls
`atomic_write(path, write)` and never calls os.replace itself; a generated file name passes through
`safe_filename`; a path that may be long runs inside `guard_long_path`. Stdlib only and import-cheap
(D03): importing this module touches no file and imports nothing heavy.

Build-list items: D13 platform block (temp file in the same directory + os.replace, bounded retry on
PermissionError naming Excel and OneDrive, no forbidden characters in generated names, MAX_PATH).
Hard rules enforced: none of the 15 directly.
"""
from __future__ import annotations

import contextlib
import errno
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

__all__ = [
    "MAX_PATH",
    "FORBIDDEN_NAME_CHARS",
    "RESERVED_NAMES",
    "LongPathError",
    "UnsafeFilename",
    "atomic_write",
    "guard_long_path",
    "safe_filename",
]

MAX_PATH: int = 260
"""Win32 default path-length cap; used only to recognise a long-path failure, never to refuse a path up front."""

FORBIDDEN_NAME_CHARS: frozenset[str] = frozenset(':*?"<>|')
"""Characters Windows and OneDrive refuse in a file name."""

RESERVED_NAMES: frozenset[str] = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)
"""Windows reserved device names, refused case-insensitively with or without an extension (CON.txt too)."""


class LongPathError(OSError):
    """OSError on a Windows path of MAX_PATH or more characters; names the length and the LongPathsEnabled fix."""


class UnsafeFilename(ValueError):
    """A generated file name Windows or OneDrive would refuse; the message names the name and the reason."""


def _on_windows() -> bool:
    """True on Windows. A function, read at call time, so tests can simulate Windows without touching os.name."""
    return os.name == "nt"


def safe_filename(name: str) -> str:
    """Return `name` unchanged when it is a safe single file-name component; raise UnsafeFilename otherwise.

    Refused: empty, "." or "..", a path separator (/ or \\), any of : * ? " < > |, a control character
    (code point below 32), a trailing dot or space (Windows strips them silently), and a reserved device
    name (CON, PRN, AUX, NUL, COM1-COM9, LPT1-LPT9) compared case-insensitively on the part before the
    first dot. Never rewrites the name: the caller chooses a different one."""
    if not isinstance(name, str) or name in ("", ".", ".."):
        raise UnsafeFilename(f"file name {name!r} is empty or a directory reference")
    bad = sorted({c for c in name if c in FORBIDDEN_NAME_CHARS or c in "/\\" or ord(c) < 32})
    if bad:
        raise UnsafeFilename(
            f"file name {name!r} contains {' '.join(repr(c) for c in bad)}; Windows and OneDrive refuse "
            ': * ? " < > |, path separators and control characters in a file name'
        )
    if name[-1] in ". ":
        raise UnsafeFilename(f"file name {name!r} ends with a dot or space, which Windows strips")
    if name.split(".", 1)[0].rstrip(" ").upper() in RESERVED_NAMES:
        raise UnsafeFilename(f"file name {name!r} is a reserved Windows device name")
    return name


def _is_long_path_failure(path: Path, exc: OSError) -> bool:
    if not _on_windows() or len(str(path)) < MAX_PATH:
        return False
    return getattr(exc, "winerror", None) in (3, 206) or isinstance(exc, FileNotFoundError)


@contextlib.contextmanager
def guard_long_path(path: Path | str) -> Iterator[None]:
    """Re-raise a Windows long-path OSError inside the block as LongPathError; any other error passes unchanged.

    Converts only on Windows, only for a path of MAX_PATH or more characters, and only for the errors a
    disabled long-path setting produces (winerror 3 or 206, or FileNotFoundError)."""
    path = Path(path)
    try:
        yield
    except LongPathError:
        raise
    except OSError as exc:
        if not _is_long_path_failure(path, exc):
            raise
        raise LongPathError(
            exc.errno if exc.errno is not None else errno.ENAMETOOLONG,
            f"cannot use {path}: the path is {len(str(path))} characters, at or above the Windows MAX_PATH limit "
            f"of {MAX_PATH}. Move the file to a shorter path, or enable long paths (Group Policy: Computer "
            "Configuration > Administrative Templates > System > Filesystem > Enable Win32 long paths; registry "
            "value LongPathsEnabled=1), then open a new PowerShell window.",
            str(path),
        ) from exc


def _unlink_quietly(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def atomic_write(
    path: Path | str, write: Callable[[Path], None], *, retries: int = 1, wait_s: float = 0.5
) -> Path:
    """Write `path` through a temp file in the same directory, then os.replace it into place; return `path`.

    `write(tmp)` is called exactly once with the temp file's path (the file exists, empty, and no handle
    is open on it, because an open handle blocks os.replace on Windows) and must write the whole content.
    The temp name is short (`cpa_<random><suffix>`, same suffix as `path`) and contains no colon. Only
    os.replace is retried: on PermissionError (the target is open in Excel or held by the OneDrive sync
    client) wait `wait_s` seconds and retry, up to `retries` times, then raise PermissionError naming Excel
    and OneDrive. The temp file is removed on every failure path, so a failed write leaves the target
    exactly as it was. The whole operation runs inside guard_long_path(path)."""
    path = Path(path)
    with guard_long_path(path):
        fd, name = tempfile.mkstemp(dir=path.parent, prefix="cpa_", suffix=path.suffix or ".tmp")
        os.close(fd)
        tmp = Path(name)
        try:
            write(tmp)
        except BaseException:
            _unlink_quietly(tmp)
            raise
        attempt = 0
        while True:
            try:
                os.replace(tmp, path)
                return path
            except PermissionError as exc:
                if attempt >= retries:
                    _unlink_quietly(tmp)
                    raise PermissionError(
                        exc.errno if exc.errno is not None else errno.EACCES,
                        f"could not replace {path} after {attempt + 1} attempt(s): the file is open in Excel or "
                        "locked by the OneDrive sync client. Close it in Excel (or wait for OneDrive to finish "
                        "syncing) and run again",
                        str(path),
                    ) from exc
                attempt += 1
                time.sleep(wait_s)
            except BaseException:
                _unlink_quietly(tmp)
                raise
