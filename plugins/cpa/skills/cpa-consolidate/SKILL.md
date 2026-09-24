---
name: cpa-consolidate
description: Inventory scattered CPA files, propose one master tree under the Workflow_Scope_FYMM_vN naming convention, and move files only after the analyst approves the plan, leaving a pointer at every old location. Run weekly as the stray-file sweep, or when the user says "consolidate my files", "find duplicates", "which copy is current", or "where is the current version".
---

# cpa-consolidate

## When to run
- The weekly stray-file sweep, once the analyst has approved a plan (step 5).
- The user says "consolidate my files", "consolidate", "find duplicates", "which copy is current", or
  "where is the current version".
- A reorganisation moved a folder, or a new stray copy appears in a folder the master tree covers.

## Inputs
| Input | Where | Required |
|---|---|---|
| Source folders to inventory | given as workspace-relative paths (`inbox/`, `staging/`, `templates/`, a network-drive folder) | yes |
| Inventory JSON | `outbox/consolidate/<stamp>/inventory.json`, printed by step 2 | yes for the plan step |
| Move plan | `outbox/consolidate/<stamp>/move_plan.json`, written by step 3 | yes for the apply step |
| The analyst's approval | the plan file's top-level `"approved"` key, set to `true` by her own edit | yes for the apply step |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core. Every path below is workspace-relative under that root.
2. Inventory: run `python -m cpa consolidate inventory <source> [<source> ...]`. It hashes every file
   under each source, skipping Excel lock files, sidecar manifests and OS metadata, writes
   `outbox/consolidate/<stamp>/inventory.json`, and prints the inventory path. It moves nothing.
3. Propose: run `python -m cpa consolidate plan <inventory.json>`. Add `--default-dest <folder>` to name
   the master destination (default `templates`). It groups the inventory into chains by name with a
   trailing version or copy token stripped, marks the highest version in each chain `move_master` (a tie
   goes to the newest modification time) and the rest `archive_copy`, and writes
   `outbox/consolidate/<stamp>/move_plan.json` with `"approved": false`. It moves nothing.
4. Present the plan to the analyst: every `move_master` row with its destination, every `archive_copy`
   row with the master it duplicates, and the `note` on any master whose name does not match
   `Workflow_Scope_FYMM_vN` (FYMM is the fiscal month; run `python -m cpa periods fymm <date>` if she
   wants a label produced rather than read by eye).
5. Stop and wait for her decision. She reviews the plan file and flips its top-level `"approved"` key to
   `true` herself. There is no per-row approval column and no other approval flag.
6. Apply: run `python -m cpa consolidate apply --plan <move_plan.json>`. Each `move_master` row moves to
   its destination and gets a sidecar manifest; each `archive_copy` row moves into
   `archive/consolidate/<date>/`; a pointer file `<name>.pointer.txt` is written at every old location. A
   row whose file is already gone is skipped and printed, not treated as an error. If the plan is not
   approved the command exits 1 with `stopped:` and moves nothing.
7. Report: files inventoried, chains found, each move and archive move, every skipped row, and every
   pointer written. If the sources were a scratch tree rather than her real folders, say so.
8. Write the run record: `python -m cpa state record --skill cpa-consolidate --input <each source>
   --output <plan path> --verification "<moved> moved, <archived> archived, <skipped> skipped"
   --duration <seconds>`.

## Outputs
- `outbox/consolidate/<stamp>/inventory.json` — every file under each source with its hash, size, chain
  key and version.
- `outbox/consolidate/<stamp>/move_plan.json` — the proposed rows, each with an action of `move_master`
  or `archive_copy`, a destination and a note; `"approved"` starts as `false`.
- The moved master files at their destinations, each with a sidecar manifest.
- `archive/consolidate/<date>/` — the duplicate and older copies, moved, never deleted.
- `<old folder>/<name>.pointer.txt` — one pointer per moved file, naming the new location.
- This skill produces no workbook.

## Verify
- The inventory lists every file under each source except lock files, sidecars and OS metadata, and the
  inventory and plan steps moved nothing.
- The plan's `"approved"` key was `false` when written and is `true` only because the analyst edited it.
- Every plan row carries an action of `move_master` or `archive_copy`, and every `archive_copy` row names
  the master it duplicates.
- `apply` printed a destination and a pointer path for every row it did not skip, and the pointer count
  equals the number of rows it moved.
- Nothing was deleted at any step; each old location still holds its pointer file.
- A master whose name does not match `Workflow_Scope_FYMM_vN` carries that in its plan `note`, and the
  report repeats it.

## If something is wrong
- `apply` prints `stopped:` and exits 1 → the plan is not approved; show it to her again and wait. Never
  flip the key yourself.
- A source folder does not exist or is empty → report the folder; do not substitute a guessed path.
- A row is skipped as "source not found" → the plan was partly applied earlier; report every skipped row
  and re-run the inventory before proposing anything new.
- A destination name already exists → `apply` writes the incoming file under a `_2` (then `_3`) suffixed
  name instead of overwriting; report the collision so she can merge the two copies by hand.
- A move fails because Excel or the file-sync client holds the file → report the path and the error;
  re-run after she closes it. Never retry by deleting the old copy.
- Two files look like the same artifact but carry unrelated names → report both paths and their
  versions; the plan only groups name-derived version chains, so the decision is hers.

## Never
- Never move a file before the plan's `"approved"` key is `true`; this skill never edits that key.
- Never delete a file, and never propose a deletion: duplicates and older versions move to `archive/`,
  they are never removed.
- Never move a file without leaving a pointer file at its old location, one pointer per moved row.
- Never invent a destination, a master, or a naming-convention match; an off-convention name is reported
  in the plan's `note` for her to decide.
- Never treat retention rules as set; `retention.rules` ships unconfirmed and this skill deletes nothing
  whatever it says.
- Never present a run against a scratch or fixture tree as a consolidation of her real files; the
  sources hashed are stated in the report.
- Never re-apply a plan without re-running the inventory first; stale rows are skipped, not resurrected.
- Never report a move, a pointer or an archive that did not happen.
