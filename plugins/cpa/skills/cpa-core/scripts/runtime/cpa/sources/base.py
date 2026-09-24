"""Source adapter contract (C8): SourceAdapter protocol, Validation, TabularAdapter and the adapter registry.

Guide section 9: every source adapter exposes validate(path) -> Validation, load(path) -> DataFrame (pandas,
DECISIONS D10) and schema() -> dict. Workflows never parse a source export themselves; they ask the registry
for an adapter by name (`cpa.sources.get("sap.co_lineitems")`) and call it (hard rule 12, R143).

HOW ANOTHER ADAPTER MODULE REGISTERS (parallel parts: tableau, powerbi, cognos, medvitals, qgenda)
---------------------------------------------------------------------------------------------------
1. Create `cpa/sources/<source>.py`. Import only stdlib and `cpa.sources.base` at module level (pandas, openpyxl
   and other cpa modules inside functions) so CLI discovery stays import-cheap (cpa/cli.py rule 3). Never import
   a network, browser or subprocess library (R014; tests/test_sources_contract.py scans every file here).
2. Subclass TabularAdapter once per dataset and decorate it with @register_adapter:

       @register_adapter
       class TableauChargesByDay(TabularAdapter):
           SOURCE = "tableau"                    # the inbox folder / CLI name
           DATASET = "charges_by_day"            # registry name becomes "tableau.charges_by_day"
           PREFIX = "charges_by_day_"            # file-name prefix used to infer the dataset (may be "")
           COLUMNS = (Column("department", ("department", "dept"), required=True, key=True),
                      Column("charges", ("charges",), dtype="number"), ...)
           ONE_ROW_PER = ()                      # canonical key columns that must be unique, if any

   Override hooks as needed: `before_read(path)` (read an assumptions key; it runs before any byte of the file
   is read), `header_check(result, header, column_map)` (before any data row), `row_check(header,
   column_map)` (return an object with feed(row) and issues(); rows are streamed, never held),
   `after_validate(path, result)`, `check_header_for_load(header, column_map)`, or override
   `validate`/`load` wholesale for exotic formats (keep the signatures). A class that does not subclass
   TabularAdapter must still satisfy SourceAdapter and the attributes listed on it, and schema() must return
   the same dict shape as TabularAdapter.schema().
3. Expose the CLI with one function; never define `register` in a leaf (cpa/cli.py rule 1):

       def register_under(sub):
           cmds = add_source_parser(sub, "tableau", "Tableau exports (A1-A3): validate landed files.")
           # optional extra commands: p = cmds.add_parser(...); p.set_defaults(func=...)

   `add_source_parser` adds `<source> validate <file> [--dataset D] [--json]` (exit 0 passed, 1 failed,
   3 quarantined). `cpa/sources/__init__.py` finds the module on disk and calls register_under; nobody edits
   __init__.py to add a leaf.
4. Fixtures (R085): add `tests/fixtures/gen_sources_<source>.py` following tests/fixtures/README.md, with
   `MAKERS = {"<source>.<dataset>": maker}`, maker(out_dir) -> Path writing real header spellings and five
   to ten fake rows, plus `generate(out_dir, *, seed=42) -> Path`. Never edit tests/fixtures/gen_sources.py.
5. Assumption keys: `reference/assumptions.yaml` already has ONE top-level `sources:` block (sap, epic). Never
   append a second top-level `sources:` (PyYAML keeps only the last block and silently drops the other); a
   test fails if there are two. Report the key you need so the block can be extended, or read it under the
   existing block once added.

Behaviour shared by every TabularAdapter: header cells are matched by fold() (case, spaces, punctuation), so
"Cost Center Number" and "cost_center_number" are one alias; unknown columns are kept verbatim; every row is
kept (never dropna, D10); key columns become stripped `string`; number columns `Float64` (a non-numeric cell is
a validation issue and a load SchemaMismatch, never silently coerced). Workbooks stream through
cpa.bigxlsx.iter_rows at every size (hard rule 11); CSV is read with utf-8-sig. validate() never modifies the
file; when the file has a sidecar manifest it is marked `validation: passed|failed|quarantined` (R040).
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pandas import DataFrame

__all__ = [
    "SourceError", "UnknownSource", "SchemaMismatch", "UnsupportedExport", "RegistryError",
    "Column", "Validation", "SourceAdapter", "TabularAdapter",
    "fold", "as_text", "register_adapter", "leaf_modules", "load_leaves", "leaf_errors", "names", "get",
    "adapter_class", "mark_manifest", "add_source_parser",
    "PASSED", "FAILED", "QUARANTINED", "EXIT_CODES", "CHUNK_ROWS",
]

PASSED, FAILED, QUARANTINED = "passed", "failed", "quarantined"
EXIT_CODES = {PASSED: 0, FAILED: 1, QUARANTINED: 3}
CHUNK_ROWS = 50_000  # rows per DataFrame chunk while building a frame from streamed rows (D10)
WORKBOOK_SUFFIXES = (".xlsx", ".xlsm", ".xlsb")
TEXT_SUFFIXES = (".csv",)
_MAX_LISTED = 20  # offending keys named in one issue line


class SourceError(Exception):
    """Base for source adapter failures a CLI reports as one line."""


class UnknownSource(SourceError, KeyError):
    """No registered adapter by that name; the message lists the registered names."""

    def __str__(self) -> str:  # KeyError would otherwise repr-quote the message
        return str(self.args[0]) if self.args else ""


class SchemaMismatch(SourceError):
    """load() on a file whose header lacks a required column, or whose typed column holds a non-value."""


class UnsupportedExport(SourceError):
    """The file suffix is not one the adapter reads."""


class RegistryError(SourceError):
    """Two different adapter classes registered under one name."""


def fold(text: object) -> str:
    """Header comparison key: casefold, every run of non-alphanumerics one space, stripped."""
    return re.sub(r"[^0-9a-z]+", " ", str(text if text is not None else "").casefold()).strip()


def as_text(value: object) -> str | None:
    """Cell value as a stripped string (None and blank -> None); an integral float prints without '.0'."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def _as_number(value: object) -> float | None:
    """Numeric cell value; None for blank; ValueError for text that is not a number."""
    if value is None or isinstance(value, bool):
        if isinstance(value, bool):
            raise ValueError(repr(value))
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if text.endswith("-"):  # SAP trailing-minus notation
        text = "-" + text[:-1]
    return float(text)


@dataclass(frozen=True)
class Column:
    """One canonical column: `name` (snake case, what load() returns), header `aliases`, required, dtype
    ("str" | "number" | "any"), key (stripped string, used for joins and uniqueness)."""

    name: str
    aliases: tuple[str, ...] = ()
    required: bool = False
    dtype: str = "any"
    key: bool = False


@dataclass
class Validation:
    """The result of validate(). `status` is passed | failed | quarantined; `ok` is status == passed."""

    adapter: str
    path: str
    status: str = PASSED
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    column_map: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    manifest: str = "not checked"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == PASSED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


@runtime_checkable
class SourceAdapter(Protocol):
    """Guide section 9. `name` is "<source>.<dataset>"; IMPLEMENTED False marks a stub (Workday);
    FIXTURE_FROM names another adapter whose fixture this one is proven against (R245)."""

    SOURCE: str
    DATASET: str
    IMPLEMENTED: bool
    FIXTURE_FROM: str | None

    def validate(self, path: Path) -> Validation: ...

    def load(self, path: Path) -> DataFrame: ...

    def schema(self) -> dict: ...


# ------------------------------------------------------------------------------------------------ reading


def _rows(path: Path, sheet: str | int | None) -> Iterator[list]:
    """Every row of the export as a list of cell values, streaming (bigxlsx for workbooks, csv for .csv)."""
    suffix = path.suffix.lower()
    if suffix in WORKBOOK_SUFFIXES:
        from cpa import bigxlsx

        gen = bigxlsx.iter_rows(path, sheet)
        try:
            yield from gen
        finally:
            gen.close()
        return
    if suffix in TEXT_SUFFIXES:
        import csv

        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                yield [cell if cell != "" else None for cell in row]
        return
    raise UnsupportedExport(f"{path.name}: unsupported file type {suffix or '(none)'}; expected one of "
                            f"{', '.join(WORKBOOK_SUFFIXES + TEXT_SUFFIXES)}")


def _header_names(raw: Sequence[Any]) -> list[str]:
    """Header strings, blanks named column_<n>, duplicates suffixed ' (2)', ' (3)'."""
    out: list[str] = []
    seen: dict[str, int] = {}
    for i, cell in enumerate(raw):
        name = as_text(cell) or f"column_{i + 1}"
        count = seen.get(name, 0) + 1
        seen[name] = count
        out.append(name if count == 1 else f"{name} ({count})")
    return out


def _blank(row: Sequence[Any]) -> bool:
    return all(as_text(v) is None for v in row)


class TabularAdapter:
    """Shared implementation of SourceAdapter for header-row exports (row 1 is the header)."""

    SOURCE: ClassVar[str] = ""
    DATASET: ClassVar[str] = ""
    PREFIX: ClassVar[str] = ""
    COLUMNS: ClassVar[tuple[Column, ...]] = ()
    ONE_ROW_PER: ClassVar[tuple[str, ...]] = ()
    MIN_ROWS: ClassVar[int] = 1
    SHEET: ClassVar[str | int | None] = None
    IMPLEMENTED: ClassVar[bool] = True
    FIXTURE_FROM: ClassVar[str | None] = None

    @property
    def name(self) -> str:
        return f"{self.SOURCE}.{self.DATASET}"

    # -- hooks ------------------------------------------------------------------------------------------
    def before_read(self, path: Path) -> dict[str, Any]:
        """Runs before any byte of the file is read (assumption gates). Returns entries for Validation.extra."""
        return {}

    def header_check(self, result: Validation, header: list[str], column_map: dict[str, str]) -> None:
        """validate() hook after the header is matched and before any data row is read. May append to
        result.issues or set result.status = QUARANTINED (data rows are then never read)."""

    def row_check(self, header: list[str], column_map: dict[str, str]) -> Any:
        """validate() hook: return None, or an object with feed(row) called per non-blank data row (streamed)
        and issues() -> list[str] called at the end."""
        return None

    def after_validate(self, path: Path, result: Validation) -> Path | None:
        """validate() hook before the manifest is marked; return the file's new path if it was moved."""
        return None

    def check_header_for_load(self, header: list[str], column_map: dict[str, str]) -> None:
        """load() hook between header match and the first data row (the Epic grain guard raises here)."""

    # -- contract ---------------------------------------------------------------------------------------
    def schema(self) -> dict:
        return {
            "source": self.SOURCE,
            "dataset": self.DATASET,
            "prefix": self.PREFIX,
            "columns": [
                {"name": c.name, "aliases": list(c.aliases), "required": c.required, "dtype": c.dtype, "key": c.key}
                for c in self.COLUMNS
            ],
            "one_row_per": list(self.ONE_ROW_PER),
            "min_rows": self.MIN_ROWS,
        }

    def match(self, header: Sequence[str]) -> tuple[dict[str, str], list[str]]:
        """(canonical name -> header cell, missing required canonical names). First matching cell wins."""
        folded = [fold(h) for h in header]
        column_map: dict[str, str] = {}
        for col in self.COLUMNS:
            wanted = {fold(a) for a in (col.name, *col.aliases)}
            for i, f in enumerate(folded):
                if f in wanted and header[i] not in column_map.values():
                    column_map[col.name] = header[i]
                    break
        missing = [c.name for c in self.COLUMNS if c.required and c.name not in column_map]
        return column_map, missing

    def read(self, path: Path) -> tuple[list[str], Iterator[list]]:
        """(header, iterator over the remaining rows padded to the header width). Close the iterator."""
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"{path} does not exist")
        rows = _rows(path, self.SHEET)
        try:
            raw = next(rows)
        except StopIteration:
            raw = []
        header = _header_names(raw)

        def body() -> Iterator[list]:
            try:
                for row in rows:
                    row = list(row)
                    if len(row) > len(header):
                        header.extend(f"column_{i + 1}" for i in range(len(header), len(row)))
                    yield row + [None] * (len(header) - len(row))
            finally:
                rows.close()

        return header, body()

    def validate(self, path: Path) -> Validation:
        path = Path(path)
        extra = self.before_read(path)
        header, body = self.read(path)
        result = Validation(adapter=self.name, path=str(path), extra=dict(extra))
        try:
            column_map, missing = self.match(header)
            result.column_map, result.missing = column_map, missing
            result.issues += [f"missing required column {m!r} (accepted headers: "
                              f"{', '.join(self._column(m).aliases or (m,))})" for m in missing]
            self.header_check(result, header, column_map)
            if result.status != QUARANTINED:
                tally = _Tally(self, header, column_map)
                extra_check = self.row_check(header, column_map)
                for row in body:
                    if _blank(row):
                        continue
                    result.rows += 1
                    tally.feed(row)
                    if extra_check is not None:
                        extra_check.feed(row)
                if result.rows < self.MIN_ROWS:
                    result.issues.append(f"{result.rows} data rows; expected at least {self.MIN_ROWS}")
                result.issues += tally.issues()
                if extra_check is not None:
                    result.issues += extra_check.issues()
        finally:
            body.close()
        result.columns = list(header)
        if result.issues and result.status == PASSED:
            result.status = FAILED
        moved = self.after_validate(path, result)
        result.manifest = mark_manifest(moved or path, result)
        return result

    def load(self, path: Path) -> DataFrame:
        path = Path(path)
        self.before_read(path)
        header, body = self.read(path)
        try:
            column_map, missing = self.match(header)
            if missing:
                raise SchemaMismatch(f"{path.name}: missing required column(s) {', '.join(missing)} for {self.name}")
            self.check_header_for_load(header, column_map)
            return self._frame(path, header, column_map, body)
        finally:
            body.close()

    # -- helpers ----------------------------------------------------------------------------------------
    def _column(self, name: str) -> Column:
        return next(c for c in self.COLUMNS if c.name == name)

    def _frame(self, path: Path, header: list[str], column_map: dict[str, str], body: Iterator[list]) -> DataFrame:
        import pandas as pd

        def records(rows: list[list]) -> DataFrame:
            width = len(header)  # a later, wider row may have extended the header
            return pd.DataFrame.from_records([r + [None] * (width - len(r)) for r in rows], columns=list(header))

        chunks, chunk = [], []
        for row in body:
            chunk.append(row)
            if len(chunk) >= CHUNK_ROWS:
                chunks.append(records(chunk))
                chunk = []
        chunks.append(records(chunk))
        chunks = [c.reindex(columns=list(header)) for c in chunks]
        frame = pd.concat(chunks, ignore_index=True) if len(chunks) > 1 else chunks[0]
        rename = {actual: canonical for canonical, actual in column_map.items()}
        typed = {}
        for canonical, actual in column_map.items():
            col = self._column(canonical)
            series = frame[actual]
            if col.key or col.dtype == "str":
                typed[actual] = pd.array([as_text(v) for v in series], dtype="string")
            elif col.dtype == "number":
                try:
                    typed[actual] = pd.array([_as_number(v) for v in series], dtype="Float64")
                except (TypeError, ValueError) as exc:
                    raise SchemaMismatch(f"{path.name}: column {canonical} ({actual!r}) holds a non-numeric cell: "
                                         f"{exc}") from exc
        other = [c for c in frame.columns if c not in typed]
        if other:
            frame[other] = frame[other].convert_dtypes(dtype_backend="numpy_nullable")
        for actual, values in typed.items():
            frame[actual] = values
        return frame.rename(columns=rename)


class _Tally:
    """Streaming per-row checks shared by every TabularAdapter: numeric cells and one-row-per keys."""

    def __init__(self, adapter: TabularAdapter, header: list[str], column_map: dict[str, str]) -> None:
        self.numbers = [(c.name, header.index(column_map[c.name])) for c in adapter.COLUMNS
                        if c.dtype == "number" and c.name in column_map]
        self.bad: dict[str, list[int]] = {}
        self.keys = list(adapter.ONE_ROW_PER)
        self.key_idx = ([header.index(column_map[k]) for k in self.keys]
                        if self.keys and all(k in column_map for k in self.keys) else [])
        self.seen: dict[tuple, int] = {}
        self.blank_keys = 0
        self.n = 0

    def feed(self, row: list) -> None:
        self.n += 1
        for name, idx in self.numbers:
            try:
                _as_number(row[idx])
            except (TypeError, ValueError):
                self.bad.setdefault(name, []).append(self.n)
        if self.key_idx:
            key = tuple(as_text(row[i]) for i in self.key_idx)
            if any(k is None for k in key):
                self.blank_keys += 1
            else:
                self.seen[key] = self.seen.get(key, 0) + 1

    def issues(self) -> list[str]:
        out = [f"{name}: {len(rows)} non-numeric cell(s), first at data row {rows[0]}"
               for name, rows in self.bad.items()]
        label = "+".join(self.keys)
        dups = [k for k, n in self.seen.items() if n > 1]
        if dups:
            shown = ", ".join("/".join(k) for k in dups[:_MAX_LISTED])
            more = f" (+{len(dups) - _MAX_LISTED} more)" if len(dups) > _MAX_LISTED else ""
            out.append(f"one row per {label} expected; duplicated {label}: {shown}{more}")
        if self.blank_keys:
            out.append(f"{self.blank_keys} row(s) with a blank {label}")
        return out


# ------------------------------------------------------------------------------------------------ manifest


def mark_manifest(path: Path, result: Validation) -> str:
    """R040: record the validation outcome in the file's sidecar manifest, if one exists. Never touches the
    file and never creates a sidecar. Returns "marked <status>" or "no manifest"."""
    from cpa import manifest

    if not manifest.exists(path):
        return "no manifest"
    manifest.update(path, validation=result.status, validation_issues=list(result.issues[:50]),
                    validated_as=result.adapter, validated_at=manifest.utc_now_iso())
    return f"marked {result.status}"


# ------------------------------------------------------------------------------------------------ registry

_REGISTRY: dict[str, type] = {}
_LEAF_ERRORS: dict[str, str] = {}
_LOADED = False
_NOT_LEAVES = {"__init__", "base"}


def register_adapter(cls: type) -> type:
    """Class decorator: register cls under "<SOURCE>.<DATASET>". Re-registering the same class is a no-op
    (module reload); a different class under a taken name raises RegistryError."""
    if not cls.SOURCE or not cls.DATASET:
        raise RegistryError(f"{cls.__name__} needs SOURCE and DATASET")
    key = f"{cls.SOURCE}.{cls.DATASET}"
    prior = _REGISTRY.get(key)
    if prior is not None and (prior.__module__, prior.__qualname__) != (cls.__module__, cls.__qualname__):
        raise RegistryError(f"{key} is registered by {prior.__module__}.{prior.__qualname__} and again by "
                            f"{cls.__module__}.{cls.__qualname__}")
    _REGISTRY[key] = cls
    return cls


def leaf_modules() -> list[str]:
    """Basenames of the adapter modules on disk (cpa/sources/*.py except __init__ and base), sorted."""
    here = Path(__file__).resolve().parent
    return sorted(p.stem for p in here.glob("*.py") if p.stem not in _NOT_LEAVES)


def load_leaves() -> dict[str, str]:
    """Import every leaf module once so its @register_adapter classes are in the registry. Returns
    {leaf: import error} for leaves that failed (also kept for `sources list`)."""
    global _LOADED
    if not _LOADED:
        for leaf in leaf_modules():
            try:
                importlib.import_module(f"cpa.sources.{leaf}")
            except Exception as exc:  # recorded and reported by `sources list`, never swallowed silently
                _LEAF_ERRORS[leaf] = f"{type(exc).__name__}: {exc}"
        _LOADED = True
    return dict(_LEAF_ERRORS)


def leaf_errors() -> dict[str, str]:
    return dict(_LEAF_ERRORS)


def names(*, implemented: bool | None = None) -> list[str]:
    """Registered adapter names; implemented=True drops stubs, False keeps only stubs."""
    load_leaves()
    return sorted(k for k, cls in _REGISTRY.items() if implemented is None or bool(cls.IMPLEMENTED) == implemented)


def adapter_class(name: str) -> type:
    """The class registered as name ("<source>.<dataset>", or "<source>" when it has exactly one dataset)."""
    load_leaves()
    if name in _REGISTRY:
        return _REGISTRY[name]
    candidates = sorted(k for k in _REGISTRY if k.split(".", 1)[0] == name)
    if len(candidates) == 1:
        return _REGISTRY[candidates[0]]
    if candidates:
        raise UnknownSource(f"{name!r} has several datasets; name one of: {', '.join(candidates)}")
    broken = f" (leaf import errors: {', '.join(sorted(_LEAF_ERRORS))})" if _LEAF_ERRORS else ""
    raise UnknownSource(f"no source adapter {name!r}; registered: {', '.join(sorted(_REGISTRY)) or 'none'}{broken}")


def get(name: str) -> TabularAdapter:
    """A fresh adapter instance for name (see adapter_class)."""
    return adapter_class(name)()


def infer_dataset(source: str, path: Path) -> str:
    """The dataset of `source` whose PREFIX starts path's file name; the only dataset when there is one."""
    load_leaves()
    options = {k: cls for k, cls in _REGISTRY.items() if cls.SOURCE == source and cls.IMPLEMENTED}
    if len(options) == 1:
        return next(iter(options))
    stem = Path(path).name.casefold()
    hits = [k for k, cls in options.items() if cls.PREFIX and stem.startswith(cls.PREFIX.casefold())]
    if len(hits) == 1:
        return hits[0]
    choices = ", ".join(sorted(cls.DATASET for cls in options.values()))
    raise UnknownSource(f"{Path(path).name}: cannot tell which {source} export this is from its name; "
                        f"pass --dataset ({choices})")


# ------------------------------------------------------------------------------------------------ CLI


def _print_validation(result: Validation, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str))
        return
    print(f"{result.status.upper()} {result.adapter} {result.path}: {result.rows} data row(s); {result.manifest}")
    for issue in result.issues:
        print(f"  - {issue}")


def run_guarded(action: Callable[[], int]) -> int:
    """Run a CLI action; expected failures become one stderr line and exit 1 (never a traceback)."""
    from cpa.bigxlsx import BigXlsxError
    from cpa.config import ConfigError

    try:
        return action()
    except (SourceError, ConfigError, BigXlsxError, OSError, NotImplementedError) as exc:
        print(f"cpa sources: {exc}", file=sys.stderr)
        return 1


def add_source_parser(sub: argparse._SubParsersAction, source: str, help_text: str, *,
                      validate_args: Callable[[argparse.ArgumentParser], None] | None = None,
                      validate_kwargs: Callable[[argparse.Namespace], dict] | None = None,
                      ) -> argparse._SubParsersAction:
    """Add `<source>` with a `validate <file> [--dataset D] [--json]` command; return its command subparsers.

    validate_args adds source-specific flags; validate_kwargs maps parsed args to adapter.validate kwargs.
    Exit 0 passed, 1 failed (or an error, one stderr line), 3 quarantined."""
    top = sub.add_parser(source, help=help_text, description=help_text)
    cmds = top.add_subparsers(dest="command", required=True, title="commands")
    p = cmds.add_parser("validate", help=f"Check a landed {source} export against its expected layout.",
                        description="Exit 0 passed, 1 failed or unreadable, 3 quarantined. The file is never "
                                    "modified; a sidecar manifest, when present, is marked with the outcome.")
    p.add_argument("path", type=Path, help="The export file.")
    p.add_argument("--dataset", default=None, help="Which export this is, when the file name does not say.")
    p.add_argument("--json", action="store_true", help="Print the result as JSON.")
    if validate_args is not None:
        validate_args(p)

    def _func(args: argparse.Namespace) -> int:
        def action() -> int:
            name = f"{source}.{args.dataset}" if args.dataset else infer_dataset(source, args.path)
            kwargs = validate_kwargs(args) if validate_kwargs is not None else {}
            result = get(name).validate(args.path, **kwargs)
            _print_validation(result, args.json)
            dest = result.extra.get("quarantined_to")
            if result.status == QUARANTINED:
                print(f"cpa sources: {result.path} is patient-level data: "
                      + (f"moved to quarantine at {dest}" if dest else "left in place (not moved to quarantine)")
                      + "; route it outside the automated pipeline", file=sys.stderr)
            return EXIT_CODES[result.status]

        return run_guarded(action)

    p.set_defaults(func=_func)
    return cmds
