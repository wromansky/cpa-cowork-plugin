"""Workday adapter stub (C8, E4): the SAP interface and schema, NotImplemented until the cutover.

Johns Hopkins moves from SAP to Workday around mid-2027 (hard rule 12, R197). Until Workday sandbox access
exists, every read raises NotImplementedError; schema() already equals SAP's so the contract tests in
tests/test_sources_contract.py run both adapters over the same fixtures (Workday skips). At cutover: implement
validate/load/locate here against those fixtures, set IMPLEMENTED = True, and point consumers' registry names at
the Workday datasets; the SAP fixtures stay the proof. No CLI leaf: nothing here can run yet.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from cpa.sources.base import TabularAdapter, Validation, register_adapter
from cpa.sources.sap import CO_COLUMNS, SALARY_COLUMNS, LocateResult

if TYPE_CHECKING:
    from pandas import DataFrame

__all__ = ["CUTOVER_MESSAGE", "WorkdaySalary", "WorkdayCoLineItems", "locate"]

CUTOVER_MESSAGE = (
    "the Workday adapter is not implemented: SAP is the source of record until the mid-2027 cutover "
    "(hard rule 12); implement it against tests/test_sources_contract.py using the SAP fixtures (E4)"
)


def _not_yet() -> NoReturn:
    raise NotImplementedError(CUTOVER_MESSAGE)


class _WorkdayStub(TabularAdapter):
    SOURCE = "workday"
    IMPLEMENTED = False

    def validate(self, path: Path) -> Validation:
        _not_yet()

    def load(self, path: Path) -> DataFrame:
        _not_yet()


@register_adapter
class WorkdaySalary(_WorkdayStub):
    """Replaces sap.salary at cutover (same columns, one row per provider)."""

    DATASET = "salary"
    PREFIX = "salary_"
    COLUMNS = SALARY_COLUMNS
    ONE_ROW_PER = ("provider_id",)
    FIXTURE_FROM = "sap.salary"


@register_adapter
class WorkdayCoLineItems(_WorkdayStub):
    """Replaces sap.co_lineitems at cutover (same columns)."""

    DATASET = "co_lineitems"
    PREFIX = "co_lineitems_"
    COLUMNS = CO_COLUMNS
    FIXTURE_FROM = "sap.co_lineitems"


def locate(amount: Decimal | str | float, cc: str, period: str, *, export: Path | None = None,
           root: Path | None = None) -> LocateResult:
    """Same signature as cpa.sources.sap.locate; not implemented until cutover."""
    _not_yet()
