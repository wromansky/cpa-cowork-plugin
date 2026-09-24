"""MedVitals adapter (A7, A8): CPT Billing Profile and business plan file exports. Read only.

`MedVitalsCptProfile` (A7, `cpt_profile_<division>_<date>`): CPT, description, volume, wRVU, charge.
`MedVitalsBp` (A8, `bp_<recordid>`): one file per provider MedVitals record ID -- the id lives in
the file name, not a column, so `load()` adds a `record_id` column (from the filename) to every
row: the join key the lookback needs (H.6, R170), supplied here since the lookback unit is unbuilt.
`check_cohort` is R062 ("read only; one file per record ID"): compares a cohort's record IDs against
`inbox/medvitals/bp_*` and reports missing, unexpected and duplicated ids. Record IDs compare
casefolded, never by exact file name: `bp_R0001.xlsx` and `bp_r0001.xlsx` are the same id on a
case-insensitive filesystem (her Windows/OneDrive machine silently overwrites one with the other) and
must still be caught as a collision on this box's case-sensitive filesystem.

The header aliases are FIXTURE - confirm against her file: no MedVitals export has landed yet; the
swap step is `python -m cpa sources medvitals validate <her export>` and correcting the aliases below.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cpa.sources.base import (
    Column,
    SourceError,
    TabularAdapter,
    add_source_parser,
    register_adapter,
    run_guarded,
)

if TYPE_CHECKING:
    from pandas import DataFrame

__all__ = ["CPT_PROFILE_COLUMNS", "BP_COLUMNS", "MedVitalsCptProfile", "MedVitalsBp", "CohortCheck",
           "record_id_from_filename", "list_bp_files", "read_cohort_ids", "check_cohort", "register_under"]

# FIXTURE - confirm against her file (A7: CPT Billing Profile, ProFee module).
CPT_PROFILE_COLUMNS: tuple[Column, ...] = (
    Column("cpt", ("cpt", "cpt code"), required=True, key=True),
    Column("description", ("description",), dtype="str"),
    Column("volume", ("volume",), required=True, dtype="number"),
    Column("wrvu", ("wrvu", "wrvus", "work rvu", "work rvus"), dtype="number"),
    Column("charge", ("charge", "charges"), dtype="number"),
)

# FIXTURE - confirm against her file (A8: business plan record, one file per MedVitals record ID).
BP_COLUMNS: tuple[Column, ...] = (
    Column("line", ("line",), required=True, key=True),
    Column("year_1", ("year 1",), required=True, dtype="number"),
)

_BP_STEM_RE = re.compile(r"^bp_(?P<record_id>.+)$", re.IGNORECASE)


@register_adapter
class MedVitalsCptProfile(TabularAdapter):
    """A7 CPT Billing Profile export, filtered by division, year to date."""

    SOURCE = "medvitals"
    DATASET = "cpt_profile"
    PREFIX = "cpt_profile_"
    COLUMNS = CPT_PROFILE_COLUMNS
    ONE_ROW_PER = ("cpt",)


@register_adapter
class MedVitalsBp(TabularAdapter):
    """A8 business plan file, one per provider MedVitals record ID."""

    SOURCE = "medvitals"
    DATASET = "bp"
    PREFIX = "bp_"
    COLUMNS = BP_COLUMNS

    def load(self, path: Path) -> DataFrame:
        """The business plan frame with a `record_id` column (from the file name) on every row."""
        frame = super().load(path)
        frame["record_id"] = record_id_from_filename(path)
        return frame


def record_id_from_filename(path: Path) -> str:
    """The MedVitals record ID from `bp_<recordid>.<ext>` (A8); raises SourceError when the name
    does not follow that convention."""
    path = Path(path)
    m = _BP_STEM_RE.match(path.stem)
    if not m:
        raise SourceError(f"{path.name}: file name is not bp_<recordid>; cannot determine the MedVitals "
                          "record ID (A8)")
    return m.group("record_id")


def list_bp_files(inbox: Path) -> list[Path]:
    """Every `bp_*` file directly under `<inbox>/medvitals`, sorted; `[]` when the folder is absent."""
    folder = Path(inbox) / "medvitals"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and _BP_STEM_RE.match(p.stem))


def read_cohort_ids(path: Path) -> list[str]:
    """One record ID per line; blank lines and `#`-led comments skipped."""
    path = Path(path)
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ids.append(line)
    return ids


@dataclass
class CohortCheck:
    """R062 outcome: `ok` is true only when nothing is missing or duplicated (unexpected files alone
    do not fail it -- A8's acceptance line names only missing and duplicated)."""

    cohort_size: int
    inbox: str
    wanted: list[str] = field(default_factory=list)
    present: dict[str, str] = field(default_factory=dict)  # requested id (as given) -> file name found
    missing: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)  # file names present but not on the cohort list
    duplicated: dict[str, list[str]] = field(default_factory=dict)  # casefolded id -> file names

    @property
    def ok(self) -> bool:
        return not self.missing and not self.duplicated

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def check_cohort(record_ids: Sequence[str], *, inbox: Path | str | None = None, root: Path | str | None = None,
                 listing: Callable[[], list[Path]] | None = None) -> CohortCheck:
    """R062: compare `record_ids` (a cohort list) against the `bp_*` files under `<inbox>/medvitals`
    (or `<root>/inbox` when `inbox` is not given, or `config.workspace()/inbox` when neither is).
    `listing` overrides file discovery (tests only). Never writes anything."""
    if inbox is not None:
        inbox_dir = Path(inbox)
    else:
        from cpa.config import workspace

        inbox_dir = Path(root or workspace()) / "inbox"
    files = listing() if listing is not None else list_bp_files(inbox_dir)

    by_norm: dict[str, list[str]] = {}
    for f in files:
        rid = record_id_from_filename(f)
        by_norm.setdefault(rid.casefold(), []).append(f.name)

    wanted = [str(r).strip() for r in record_ids if str(r).strip()]
    wanted_norm = {w.casefold() for w in wanted}
    present: dict[str, str] = {}
    missing: list[str] = []
    for w in wanted:
        names = by_norm.get(w.casefold())
        if not names:
            missing.append(w)
        else:
            present[w] = names[0]
    unexpected = sorted(names[0] for norm, names in by_norm.items() if norm not in wanted_norm)
    duplicated = {norm: sorted(names) for norm, names in by_norm.items() if len(names) > 1}

    return CohortCheck(cohort_size=len(wanted), inbox=str(inbox_dir), wanted=wanted, present=present,
                       missing=missing, unexpected=unexpected, duplicated=duplicated)


# ------------------------------------------------------------------------------------------------ CLI


def _cmd_check_cohort(args: argparse.Namespace) -> int:
    import json

    def action() -> int:
        ids = read_cohort_ids(args.cohort)
        result = check_cohort(ids, inbox=args.inbox, root=args.root)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(f"{'OK' if result.ok else 'FAILED'}: {len(result.wanted)} id(s) on the cohort list, "
                  f"{len(result.present)} present, {len(result.missing)} missing, "
                  f"{len(result.duplicated)} duplicated, {len(result.unexpected)} unexpected")
            for rid in result.missing:
                print(f"  missing: {rid}")
            for norm, names in result.duplicated.items():
                print(f"  duplicated ({norm}): {', '.join(names)}")
            for name in result.unexpected:
                print(f"  unexpected: {name}")
        return 0 if result.ok else 1

    return run_guarded(action)


def register_under(sub: argparse._SubParsersAction) -> None:
    """`sources medvitals validate` (cpt_profile, bp) and `sources medvitals check-cohort` (R062, A8).
    Import-cheap."""
    cmds = add_source_parser(sub, "medvitals", "MedVitals exports (A7, A8): CPT Billing Profile, "
                                               "business plan files. Read only; one file per record ID.")
    p = cmds.add_parser("check-cohort", help="Check a cohort's business plan files (R062, A8).",
                        description="Exit 0 when every id on the cohort list has exactly one file and "
                                    "no file present is off-list-duplicated; 1 otherwise.")
    p.add_argument("--cohort", type=Path, required=True,
                   help="A text file with one MedVitals record ID per line.")
    p.add_argument("--inbox", type=Path, default=None,
                   help="The inbox folder to scan (default: <root>/inbox).")
    p.add_argument("--root", type=Path, default=None, help="Workspace root (default: config.workspace()).")
    p.add_argument("--json", action="store_true", help="Print the result as JSON.")
    p.set_defaults(func=_cmd_check_cohort)
