"""Power BI adapter (A4): departmental wRVU, collections and PB-visits export. Read only; nothing here writes
to Power BI (R014/R064's read-and-export-only shape applies here too).

INV-271 / Y-05 / H-01 (docs/research/REQUIREMENTS.md): the report's name is `[UNCONFIRMED]`, read from her
bookmark. Following the SAP salary precedent (D31, `sap.py`'s `before_read` gate on
`sources.sap.salary_extract_format`): until she confirms `sources.powerbi.dept_productivity_report_name`, no
byte of a departmental productivity export is read, and validate()/load() raise `MissingAssumption` naming
the key rather than guessing a report.

Header aliases are FIXTURE - confirm against her file: spellings follow the Build List A4 description
(department, wRVUs, collections, PB visits, all departments at fiscal YTD); the swap step is
`python -m cpa sources powerbi validate <her export>` and correcting the aliases below.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from cpa.sources.base import Column, TabularAdapter, add_source_parser, register_adapter

__all__ = ["DEPT_PRODUCTIVITY_COLUMNS", "PowerBiDeptProductivity", "register_under"]

# FIXTURE - confirm against her file (A4: all departments, fiscal YTD).
DEPT_PRODUCTIVITY_COLUMNS: tuple[Column, ...] = (
    Column("department", ("department", "dept"), required=True, dtype="str", key=True),
    Column("wrvus", ("wrvus", "wrvu", "work rvus"), required=True, dtype="number"),
    Column("collections", ("collections", "gross collections"), required=True, dtype="number"),
    Column("pb_visits", ("pb visits", "pb encounters"), required=True, dtype="number"),
)


@register_adapter
class PowerBiDeptProductivity(TabularAdapter):
    """A4 departmental productivity export: one row per department (crosswalk match is a later C4 concern,
    not this adapter's -- it only validates the file's own shape)."""

    SOURCE = "powerbi"
    DATASET = "dept_productivity"
    PREFIX = "dept_productivity_"
    COLUMNS = DEPT_PRODUCTIVITY_COLUMNS
    ONE_ROW_PER = ("department",)

    def before_read(self, path: Path) -> dict[str, Any]:
        from cpa.config import assumption

        return {"dept_productivity_report_name": assumption("sources", "powerbi", "dept_productivity_report_name")}


def register_under(sub: argparse._SubParsersAction) -> None:
    """`sources powerbi validate` (dept_productivity). Import-cheap."""
    add_source_parser(sub, "powerbi", "Power BI exports (A4): validate departmental productivity exports. "
                                      "Read only.")
