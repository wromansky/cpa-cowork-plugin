"""Fiscal calendar: FYMM, SAP period labels, holidays, workdays, business days, and proration.

Build-list items: C6 period prorater (factor and label), fiscal calendar (guide section 5.1, section 9
periods.py). D02: FYMM is "yymm", month 01 = July, the fiscal year named by the calendar year it ends
in; this module is the only place that formats or parses it. D06: holidays_jhm.csv holds observed
dates (date,name,fiscal_year); a fiscal year with no rows raises instead of meaning zero holidays.
Hard rules enforced: 9 (period mismatches are prorated explicitly, with a label), 15 (no invented
holidays).
"""

from __future__ import annotations

import argparse
import calendar
import csv
import re
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

from cpa.config import MissingReference

FISCAL_START_MONTH = 7  # guide 5.1 / D04 fiscal.year_start_month; a calendar fact, not a Hopkins rate
HOLIDAYS_FILE = "holidays_jhm.csv"
_FYMM_RE = re.compile(r"^\d{4}$")
_FILENAME_TOKEN_RE = re.compile(r"(?:^|_)(\d{4})(?=[._]|$)")
_SAP_RE = re.compile(r"^(\d{3})/(\d{4})\s*:\s*([A-Za-z]+)\s+(\d{4})$")

__all__ = [
    "AmbiguousFilename", "PartialPeriod", "fymm", "parse_fymm", "calendar_month", "fymm_from_filename",
    "sap_label", "parse_sap_label", "load_holidays", "workdays", "is_business_day",
    "business_days_between", "prorate", "prorate_days", "months_between", "register",
]


class AmbiguousFilename(ValueError):
    """A filename does not carry exactly one valid _yymm period token."""


class PartialPeriod(ValueError):
    """A period does not start on the 1st and end on the last day of a month, so whole months do not apply."""


def fymm(d: date) -> str:
    """Fiscal period for a calendar date: July 2023 -> '2401'."""
    fy = d.year + 1 if d.month >= FISCAL_START_MONTH else d.year
    fm = (d.month - FISCAL_START_MONTH) % 12 + 1
    return f"{fy % 100:02d}{fm:02d}"


def parse_fymm(value: str) -> tuple[int, int]:
    """'2703' -> (2027, 3). Raises ValueError for anything that is not yymm with month 01-12."""
    if not isinstance(value, str) or not _FYMM_RE.match(value):
        raise ValueError(f"FYMM must be four digits yymm, got {value!r}")
    fy, fm = 2000 + int(value[:2]), int(value[2:])
    if not 1 <= fm <= 12:
        raise ValueError(f"fiscal month must be 01-12, got {value!r}")
    return fy, fm


def calendar_month(value: str) -> tuple[int, int]:
    """'2401' -> (2023, 7): the calendar year and month of a fiscal period."""
    fy, fm = parse_fymm(value)
    month = (fm - 1 + FISCAL_START_MONTH - 1) % 12 + 1
    year = fy - 1 if month >= FISCAL_START_MONTH else fy
    return year, month


def fymm_from_filename(name: str) -> str:
    """The single valid _yymm token in a filename such as charges_by_day_2703.xlsx."""
    stem = Path(name).name
    found = []
    for token in _FILENAME_TOKEN_RE.findall(stem):
        try:
            parse_fymm(token)
        except ValueError:
            continue
        found.append(token)
    if len(found) != 1:
        raise AmbiguousFilename(f"{stem}: expected exactly one _yymm period token, found {found or 'none'}")
    return found[0]


def sap_label(value: str) -> str:
    """'2401' -> '001/2024 : July 2023' (SAP period naming, guide 5.1)."""
    fy, fm = parse_fymm(value)
    year, month = calendar_month(value)
    return f"{fm:03d}/{fy} : {calendar.month_name[month]} {year}"


def parse_sap_label(label: str) -> str:
    """'001/2024 : July 2023' -> '2401'. The month name and year must agree with the period."""
    m = _SAP_RE.match(label.strip())
    if not m:
        raise ValueError(f"not an SAP period label: {label!r}")
    fm, fy = int(m.group(1)), int(m.group(2))
    value = f"{fy % 100:02d}{fm:02d}"
    if sap_label(value) != f"{fm:03d}/{fy} : {m.group(3).capitalize()} {m.group(4)}":
        raise ValueError(f"SAP label {label!r} is internally inconsistent (expected {sap_label(value)!r})")
    return value


def load_holidays(path: Path | str | None = None) -> list[date]:
    """Observed holiday dates from holidays_jhm.csv (her Hopkins list). Default file via config.reference_file."""
    if path is None:
        from cpa.config import reference_file

        path = reference_file(HOLIDAYS_FILE)
    out = []
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("date") or "").strip():
                out.append(date.fromisoformat(row["date"].strip()))
    return out


def _holiday_set(value: str, holidays: Path | str | Iterable[date] | None) -> set[date]:
    days = set(load_holidays(holidays) if holidays is None or isinstance(holidays, (str, Path)) else holidays)
    fy, _ = parse_fymm(value)
    if not any(fymm(d)[:2] == value[:2] for d in days):
        raise MissingReference(
            f"{HOLIDAYS_FILE} has no rows for FY{fy % 100:02d}. Add the Hopkins observed holidays for that year "
            "(date,name,fiscal_year); workdays are never counted without them"
        )
    return days


def is_business_day(d: date, holidays: Iterable[date]) -> bool:
    """Monday-Friday and not an observed holiday."""
    return d.weekday() < 5 and d not in set(holidays)


def workdays(value: str, holidays: Path | str | Iterable[date] | None = None) -> int:
    """Working days in a fiscal month: Mon-Fri minus observed holidays. Raises MissingReference without holiday rows."""
    days = _holiday_set(value, holidays)
    year, month = calendar_month(value)
    last = calendar.monthrange(year, month)[1]
    return sum(1 for day in range(1, last + 1) if is_business_day(date(year, month, day), days))


def business_days_between(start: date, end: date, holidays: Iterable[date]) -> int:
    """Business days in [start, end): start counts, end does not."""
    days = set(holidays)
    n, d = 0, start
    while d < end:
        n += is_business_day(d, days)
        d += timedelta(days=1)
    return n


def _check_count(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive whole number, got {value!r}")
    return value


def prorate(plan_value: float, plan_months: int, actual_months: int) -> tuple[float, str]:
    """Scale a plan figure to the actual period in whole months: (1200, 12, 10) -> (1000.0, 'prorated x0.8333 (10 of 12 months)')."""
    _check_count("plan_months", plan_months)
    _check_count("actual_months", actual_months)
    factor = actual_months / plan_months
    return plan_value * factor, f"prorated ×{factor:.4f} ({actual_months} of {plan_months} months)"


def prorate_days(plan_value: float, plan_days: int, actual_days: int) -> tuple[float, str]:
    """Day-based proration for periods that are not whole months; the label says days."""
    _check_count("plan_days", plan_days)
    _check_count("actual_days", actual_days)
    factor = actual_days / plan_days
    return plan_value * factor, f"prorated ×{factor:.4f} ({actual_days} of {plan_days} days)"


def months_between(start: date, end: date) -> int:
    """Inclusive whole calendar months from start (a 1st) to end (a month end); PartialPeriod otherwise."""
    if start.day != 1:
        raise PartialPeriod(f"{start} is not the first day of a month; use prorate_days")
    if end.day != calendar.monthrange(end.year, end.month)[1]:
        raise PartialPeriod(f"{end} is not the last day of a month; use prorate_days")
    if end < start:
        raise ValueError(f"period end {end} is before start {start}")
    return (end.year - start.year) * 12 + end.month - start.month + 1


# ---------------------------------------------------------------- CLI


def _cmd_fymm(a: argparse.Namespace) -> int:
    print(fymm(date.fromisoformat(a.date)))
    return 0


def _cmd_sap(a: argparse.Namespace) -> int:
    print(sap_label(a.fymm))
    return 0


def _cmd_from_sap(a: argparse.Namespace) -> int:
    print(parse_sap_label(a.label))
    return 0


def _cmd_workdays(a: argparse.Namespace) -> int:
    print(workdays(a.fymm, a.holidays))
    return 0


def _cmd_prorate(a: argparse.Namespace) -> int:
    value, label = prorate(a.value, a.plan_months, a.actual_months)
    print(f"{value:.2f}\t{label}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `periods` conversions so skills never compute fiscal periods by hand (R242)."""
    top = subparsers.add_parser("periods", help="Fiscal period conversions: FYMM, SAP labels, workdays, proration.")
    sub = top.add_subparsers(dest="command", required=True, title="commands")
    p = sub.add_parser("fymm", help="Calendar date (YYYY-MM-DD) to FYMM.")
    p.add_argument("date")
    p.set_defaults(func=_cmd_fymm)
    p = sub.add_parser("sap-label", help="FYMM to the SAP period label, e.g. 001/2024 : July 2023.")
    p.add_argument("fymm")
    p.set_defaults(func=_cmd_sap)
    p = sub.add_parser("from-sap", help="SAP period label to FYMM.")
    p.add_argument("label")
    p.set_defaults(func=_cmd_from_sap)
    p = sub.add_parser("workdays", help="Working days in a fiscal month from the holidays file.")
    p.add_argument("fymm")
    p.add_argument("--holidays", default=None, help="Holidays CSV (default: reference/holidays_jhm.csv).")
    p.set_defaults(func=_cmd_workdays)
    p = sub.add_parser("prorate", help="Prorate a plan value from plan months to actual months, with its label.")
    p.add_argument("value", type=float)
    p.add_argument("plan_months", type=int)
    p.add_argument("actual_months", type=int)
    p.set_defaults(func=_cmd_prorate)
