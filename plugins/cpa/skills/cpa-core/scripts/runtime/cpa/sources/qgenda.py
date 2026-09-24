"""QGenda adapter (C8; A13): task definitions, TaskKeys, weekday/weekend credits, hospital tags.

Guide section 9/6.641: one adapter, `qgenda.tasks`, following cpa/sources/base.py's TabularAdapter
contract exactly. `python -m cpa sources qgenda validate <file>` is the only entry point; workflows
never parse a QGenda export themselves (hard rule 12).

The header aliases are FIXTURE - confirm against her file: spellings follow
FPA_Work_Inventory_CPA.md's QGenda row and Build List A13; the swap step is
`python -m cpa sources qgenda validate <her export>` and adding her spellings to the aliases below.

R065 (TaskKey column present and non-empty) is two separate checks: `task_key` is `required=True` so a
missing column fails validate()/load() the same way every other TabularAdapter required column does;
"non-empty" is not something the base contract checks per-cell, so `row_check` below adds a streamed
tally that flags any row whose TaskKey cell is blank.

R224 (TaskKeys are system-assigned and must never be fabricated) is a property of what this module does
NOT do: every TaskKey the adapter reports is exactly the cell `as_text()` returned from the source file
(base.py's shared reader) - never filled, defaulted, generated or inferred. A blank source cell stays
blank (None / pd.NA) all the way through validate() and load(); nothing here ever manufactures a value.

No `ONE_ROW_PER`: FPA_Work_Inventory_CPA.md ("CAG to QGenda task mapping") and R169 both say the same
physical task legitimately repeats under multiple divisions that share a unit, so per-TaskKey row
uniqueness is not an adapter-level rule here (unlike SAP's provider_id in sap.py).
"""
from __future__ import annotations

import argparse

from cpa.sources.base import (
    Column,
    TabularAdapter,
    add_source_parser,
    as_text,
    register_adapter,
)

__all__ = ["TASK_COLUMNS", "QgendaTasks", "register_under"]

# FIXTURE - confirm against her file (A13 QGenda task export layout).
TASK_COLUMNS: tuple[Column, ...] = (
    Column("task_key", ("TaskKey", "task key", "task id"), required=True, key=True),
    Column("department", ("dept",), required=True, key=True),
    Column("task_name", ("task", "task description"), dtype="str"),
    Column("division", (), dtype="str"),
    Column("activity", (), dtype="str"),
    Column("weekday_credit", ("weekday cr",), dtype="number"),
    Column("weekend_credit", ("weekend cr",), dtype="number"),
    Column("hospital_tag", ("hospital",), dtype="str"),
)


class _BlankTaskKeyTally:
    """Streamed check for A13's "non-empty" half: counts data rows whose TaskKey cell is blank. Never
    fills or fabricates one (R224) - it only counts what as_text() already read as absent."""

    def __init__(self, idx: int) -> None:
        self.idx = idx
        self.blank = 0

    def feed(self, row: list) -> None:
        if as_text(row[self.idx]) is None:
            self.blank += 1

    def issues(self) -> list[str]:
        if not self.blank:
            return []
        return [f"task_key: {self.blank} row(s) with a blank TaskKey "
                f"(A13 requires the TaskKey column present and non-empty)"]


@register_adapter
class QgendaTasks(TabularAdapter):
    """A13 QGenda task export: task definitions with TaskKey, department, division, activity, weekday
    and weekend credits, hospital tag. One dataset, so `get("qgenda")` also resolves it."""

    SOURCE = "qgenda"
    DATASET = "tasks"
    PREFIX = "tasks_"
    COLUMNS = TASK_COLUMNS

    def row_check(self, header: list[str], column_map: dict[str, str]) -> _BlankTaskKeyTally | None:
        if "task_key" not in column_map:
            return None  # the required-column check already reports the missing column
        return _BlankTaskKeyTally(header.index(column_map["task_key"]))


def register_under(sub: argparse._SubParsersAction) -> None:
    """`sources qgenda validate` (A13). Import-cheap: only stdlib and cpa.sources.base at module level."""
    add_source_parser(sub, "qgenda", "QGenda task exports (A13): validate landed task definition files.")
