---
description: Run the month-start export chain across every source system.
---

Use the cpa-monthly-pull skill. Run the full monthly pull chain, one pull per step, resuming from the last
good step if a prior run left one incomplete. Report which systems landed, which failed, and what is still
waiting on her. If the cpa-monthly-pull skill is not in the mounted plugin, say so and stop rather than
improvising the chain.
