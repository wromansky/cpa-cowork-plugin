---
name: cpa-charge-forecast
description: Update the monthly CPA charge forecast from a Tableau Charges by Day export. Run when a new charges_by_day file lands in inbox/tableau, when the user says "forecast", "run the charge forecast", or "what's the month going to land at".
---

# cpa-charge-forecast

## When to run
- The dispatcher detects a new `inbox/tableau/charges_by_day_*.xlsx`.
- The user asks for the forecast.

## Inputs
| Input | Where | Required |
|---|---|---|
| Charges export | `inbox/tableau/charges_by_day_<FYMM>.xlsx` | yes |
| Forecast workbook | `templates/CPA_Charge_Forecast_Rebuild.xlsx` | yes |
| Input cell map | `reference/assumptions.yaml`: `charge_forecast.input_cells` | yes |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Run `python -m cpa charge_forecast run --export <export> --out outbox/forecast/<FYMM>/
   [--as-of <YYYY-MM-DD>]`, giving `<workbook>` = `CPA_Charge_Forecast_<FYMM>.xlsx` and `<summary>` =
   `forecast_summary.json` in that output folder.
   The command copies the template, pastes the export into the Paste MTD tab, sets the fiscal month
   and total workdays in the mapped input cells, wires the Prior-Year cell to a SUMIFS against
   Historical Data, appends the month's daily rows to Historical Data once the month has closed,
   recalculates, attaches the Verification tab itself, reads the base forecast and P10/P90 from the
   Forecast tab, and writes `<summary>`.
3. Read `<summary>`. If its verification result is not CLEAN, run `python -m cpa verify <workbook>
   --sources inbox/tableau/` and follow `cpa-verify`'s "If something is wrong" before continuing.
4. Run `python -m cpa charge_forecast track --summary <summary>` to upsert
   `logs/forecast_mape.csv` (fills the actual, APE, and P10-P90 hit once a closed month's summary
   lands).
5. Run `python -m cpa state record --skill cpa-charge-forecast --input <export> --output
   <workbook> --output <summary> --verification <CLEAN or "N ISSUES"> --duration <seconds>` to
   write the run record.
6. Report one line: "FY<yy> M<mm> forecast: base $X, range $P10-$P90, at <pct>% of workdays."

## Outputs
- `outbox/forecast/<FYMM>/CPA_Charge_Forecast_<FYMM>.xlsx`
- `outbox/forecast/<FYMM>/forecast_summary.json`

## Verify
- Verification tab CLEAN.
- Paste MTD row count equals the days elapsed in the export.
- Workday count matches `reference/holidays_jhm.csv` for the month.

## If something is wrong
- Any of the five input cells in `charge_forecast.input_cells` is null -> stop; ask the analyst to
  open the workbook and name the yellow input cells; propose them with `python -m cpa config
  propose charge_forecast.input_cells.<name> "<cell>" --note "confirmed by analyst"` for her to
  paste into `assumptions.yaml`.
- The export has fewer rows than days elapsed -> flag a possible partial export; still produce the
  forecast, labeled, and say so in the report line.
- `python -m cpa charge_forecast run` exits 2 (stopped) -> report the error text; do not run `track`
  or write a run record claiming success.

## Never
- Never hard-code the prior-year value; it comes from the SUMIFS against Historical Data.
- Never write into the Curve Reference tab.
- Never treat a partial export as a complete one without labeling it.
