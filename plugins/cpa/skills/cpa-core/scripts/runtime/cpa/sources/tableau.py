"""Tableau adapter (A1-A3): Charges by Day, JHM PB KPIs Dashboard (gross collection rate), Ambulatory
Operations Dashboard. Read and export only; nothing here writes to Tableau or opens a session (hard rule 12
style, R014/R064's read-and-export-only shape applies here too even though it names SAP/Epic specifically).

Every dataset is a plain `TabularAdapter` (D31): header match by folded alias, streaming read, never a
network/browser import (`test_epic_and_sap_sessions_read_and_export_only` scans every file here). Beyond the
column checks every `TabularAdapter` already gives for free, A1 and A2's acceptance lines ("row count matches
the number of calendar days elapsed", "12-month ... rate by bill area") bound plausible row counts above
`MIN_ROWS`: `_MaxRows` is a `row_check` object (the same `feed(row)`/`issues()` protocol as base.py's
`_Tally`) that appends one issue when the file holds more rows than a single export of that kind plausibly
can, without quarantining or blocking `load()`. A3's acceptance line is only "file non-empty, manifest
written", so `TableauAmbulatoryOps` sets no ceiling.

Header aliases and the row-count ceilings are FIXTURE - confirm against her file: spellings and exact bounds
follow the Build List (A1-A3) and the guide's plain-language description of each dashboard; the swap step is
`python -m cpa sources tableau validate <her export>` and correcting the aliases/ceiling below.
"""
from __future__ import annotations

import argparse

from cpa.sources.base import Column, TabularAdapter, add_source_parser, register_adapter

__all__ = [
    "CHARGES_BY_DAY_COLUMNS", "PB_KPIS_COLUMNS", "AMBULATORY_OPS_COLUMNS",
    "TableauChargesByDay", "TableauPbKpis", "TableauAmbulatoryOps", "register_under",
]

# FIXTURE - confirm against her file (A1: one row per calendar day; department is exported but not the key).
CHARGES_BY_DAY_COLUMNS: tuple[Column, ...] = (
    Column("charge_date", ("date", "charge date", "day"), required=True, dtype="str", key=True),
    Column("department", ("department", "dept"), dtype="str"),
    Column("charges", ("charges", "total charges", "gross charges"), required=True, dtype="number"),
)

# FIXTURE - confirm against her file (A2: JHM PB KPIs Dashboard, 12-month gross collection rate by bill area).
PB_KPIS_COLUMNS: tuple[Column, ...] = (
    Column("bill_area", ("bill area", "billing area"), required=True, dtype="str", key=True),
    Column("period", ("month", "period", "report month"), required=True, dtype="str", key=True),
    Column("gross_collection_rate", ("gross collection rate", "collection rate"), required=True, dtype="number"),
)

# FIXTURE - confirm against her file (A3: Ambulatory Operations Dashboard; non-empty is the only bound).
AMBULATORY_OPS_COLUMNS: tuple[Column, ...] = (
    Column("department", ("department", "dept"), required=True, dtype="str", key=True),
    Column("period", ("period", "month", "fiscal period"), dtype="str"),
    Column("visits", ("visits", "ambulatory visits", "total visits"), dtype="number"),
    Column("utilization_rate", ("utilization rate", "utilization", "room utilization"), dtype="number"),
)


class _MaxRows:
    """row_check hook: flag more data rows than a single export of this kind plausibly holds (never fewer;
    MIN_ROWS already covers that). Never quarantines; one issue among the usual issues-imply-failed rule."""

    def __init__(self, ceiling: int, why: str) -> None:
        self.ceiling = ceiling
        self.why = why
        self.n = 0

    def feed(self, row: list) -> None:
        self.n += 1

    def issues(self) -> list[str]:
        if self.n > self.ceiling:
            return [f"{self.n} data rows; expected at most {self.ceiling} ({self.why}; FIXTURE bound, "
                    "confirm against her file)"]
        return []


@register_adapter
class TableauChargesByDay(TabularAdapter):
    """A1 Charges by Day export (fiscal month; Imaging excluded by the pull's own filter, not a column here)."""

    SOURCE = "tableau"
    DATASET = "charges_by_day"
    PREFIX = "charges_by_day_"
    COLUMNS = CHARGES_BY_DAY_COLUMNS

    def row_check(self, header: list[str], column_map: dict[str, str]) -> _MaxRows:
        return _MaxRows(31, "a fiscal month has at most 31 calendar days")


@register_adapter
class TableauPbKpis(TabularAdapter):
    """A2 gross collection rate by bill area, one row per bill_area+period."""

    SOURCE = "tableau"
    DATASET = "pb_kpis"
    PREFIX = "pb_kpis_"
    COLUMNS = PB_KPIS_COLUMNS
    ONE_ROW_PER = ("bill_area", "period")

    def row_check(self, header: list[str], column_map: dict[str, str]) -> _MaxRows:
        return _MaxRows(12, "the dashboard is a 12-month rolling collection rate per bill area")


@register_adapter
class TableauAmbulatoryOps(TabularAdapter):
    """A3 Ambulatory Operations Dashboard export: file non-empty is the only acceptance line."""

    SOURCE = "tableau"
    DATASET = "ambulatory_ops"
    PREFIX = "ambulatory_"
    COLUMNS = AMBULATORY_OPS_COLUMNS


def register_under(sub: argparse._SubParsersAction) -> None:
    """`sources tableau validate` (charges_by_day, pb_kpis, ambulatory_ops). Import-cheap."""
    add_source_parser(sub, "tableau", "Tableau exports (A1-A3): validate Charges by Day, PB KPIs and "
                                      "Ambulatory Operations exports. Read and export only.")
