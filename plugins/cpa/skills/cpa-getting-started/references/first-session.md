# A first session with CPA

Use this as a teaching reference, not a script to read aloud in full. Start with one short
explanation and one next step; expand only when she asks. No programming vocabulary is needed.

## The short explanation

"You can keep talking to Claude the way you already do. The difference is that, with the right
permission, you can give it a defined piece of work and let it work through the steps using
approved files and tools. The CPA plugin gives it our repeatable workflow instructions, your
branding, and tested checks. You still decide what is allowed, review the results and send them."

For example, instead of repeatedly explaining a CRF process and copying results between a
conversation and a workbook, you can ask CPA to inspect approved exports, identify missing
inputs, and use its existing workflow once the inputs and access have been validated. That
can reduce repeated briefing and manual transfer. It does not guarantee time savings on every
task, correct numbers or production-ready output from the first run.

## What changes, and what does not

| What you need | A sensible approach |
|---|---|
| Explain a variance, draft a sentence, explore an idea | A normal conversation is often enough. |
| Work through approved files with repeatable CPA rules | A scoped task using the relevant CPA skill is more useful. |
| Remember the workflow and formatting each time | The plugin supplies reusable instructions; do not assume every previous conversation is remembered. |
| Reconcile or generate exact data | CPA uses its registered Python tools where implemented, not conversational arithmetic. |
| Decide whether the result is right and appropriate to send | You review; neither the plugin nor a successful setup replaces that decision. |

Important: chat can also create files, and plugins can be available in chat. Newer Claude accounts
have a unified conversation experience without separate Chat/Cowork controls. The meaningful
benefit is the approved tool-assisted workflow, not the name of the tab or a promise that one
mode is inherently smarter. This CPA deployment still needs its actual runtime, files and
permissions checked; a platform feature existing does not prove that CPA can use it here.

Multi-step tasks can use more usage than quick questions. Keep one defined outcome per task;
start a new conversation for unrelated work. Do not start large parallel runs or remove review
steps to save tokens. No savings target has been measured against her actual workflow yet.

## Four words worth knowing

- **Plugin:** the installed CPA package of instructions and tested tools.
- **Skill:** one job-specific set of instructions, such as setup, CRF or branding. Ask for it
  by name in normal language; you need not memorize slash commands.
- **Workspace:** the actual approved folder holding your working files. A temporary execution
  folder with the same name is not your OneDrive workspace.
- **Connector:** separately permitted access to an app/service. Installing CPA does not
  automatically connect COGNOS, SAP, Epic, OneDrive or any other system.

## How to begin

1. Open the approved Claude Desktop account with CPA enabled. If you see Chat/Cowork choices,
   choose Cowork. If the unified experience has no selector, describe your task in that
   conversation. Keep Desktop open for work needing local files or browser access. Do not
   assume a cloud task can reach local files while Desktop is offline.
2. If helpful, type `/` or use `+` to see installed skills. Alternatively ask "Use
   cpa-getting-started to teach me the basics." If a control or skill is missing, describe
   what you see; do not install additional tools or change accounts to work around policy.
3. For financial trials, prefer manual approval where that permission option is available.
   Review the task's scope, not unfamiliar technical commands. A prompt asking for unrelated
   access, deletion, broad permissions or sending is a reason to pause, not click through.
4. Ask for a plan before work. A good brief states the outcome, input files, fiscal period,
   actual/budget status, what must not change, and what should be returned for your review.
5. Keep the first trial attended and small. Use approved manual exports before browser pulls.
   Do not enable schedules or unattended source access as a beginner exercise.

## A safe sequence of copyable prompts

Offer ONE prompt appropriate to her current readiness. Do not run these simply because they
appear here. Do not teach all steps at once unless she requests the whole sequence.

**Learn first — requires no files**

> Use cpa-getting-started. I have only used chat before. Explain how CPA can help with my work
> in plain language, and give me one safe next step. Do not open files or run anything yet.

**Setup — only when she chooses it**

> Use cpa-setup to check the CPA plugin currently loaded in this session. Show the version
> and readiness result. Provision only the approved packages inside Cowork if needed; do not
> install software on my computer. Stop and explain any failure.

**Confirm the real folder — after setup**

> Help me confirm the exact approved CPA folder you can actually access. Show me the location
> so I can confirm it is the same OneDrive workspace I use. Do not create a substitute folder,
> move files or ask me to run terminal commands.

**First CRF input review — after setup, access and data-use approval**

> Use cpa-crf to help me prepare a supervised CRF trial using the manual exports I identify.
> First show me your plan. After I approve it, inspect only those files read-only and tell me
> what is missing or mismatched, including periods and sources. Do not build the report, edit
> the originals, open a source system, schedule anything or send anything. Stop for my review.

## While Claude is working

Read its plan and progress. If the scope changes, say "Stop here. Explain what you were about
to do and which files would change." Use the task's visible stop/cancel control if available.
If it reports a source job is already running, stopping the conversation is not proof that the
external job was cancelled; do not submit another copy. Ask for the last confirmed state.

You handle passwords, SSO and MFA yourself; do not paste credentials into the conversation.
If a permitted browser session needs sign-in, pause assistance during authentication and
resume only after you say you are ready. No approved browser connection? Continue with manual
exports, not an add-on installation or an invented connection.

## How to review a result

- Ask "What changed, where is the output, what did you verify, and what remains blocked?"
- **outbox** is where workflow drafts wait for your review; it does not mean they were sent.
- **Source & Notes** documents recorded data origins. **Verification** reports CPA checks.
  Neither tab's presence proves that all figures are right or every source is confirmed.
- Check the period, actual/budget/forecast status, as-of date and source system. Missing data
  should be visible, not filled with a plausible estimate.
- Look for **NOT_RECALCULATED**. Automatic workbook recalculation is unsupported. Cached
  formula results are not proof of verified values, and a dependent workflow must stop.
  Your manual Excel review does not automatically turn the plugin's result into CLEAN.
- Check that protected templates, formulas and original source files stayed intact.
- The plugin uses your branding skill. Inspect fonts, header/tab colors, layout and artwork.
  Python slide helpers do not yet implement every cover/logo/layout; report mismatches.
- You decide whether an artifact is appropriate and send it yourself. Nothing should be
  emailed, posted to Accounting or written back to a source system for you.

## Privacy and practical limits

Use only data your organization permits in the approved Claude account and environment.
Do not assume selecting a local folder means local-only processing: official docs explain
that content accessed by cloud tasks is processed on Anthropic's servers. Do not upload patient
records, compensation details or other sensitive material merely for a tutorial. A folder grant
is not organization approval. Do not grant an entire drive to overcome a missing-file problem.

CPA does not automatically configure connectors, authenticate to source systems, implement
Excel desktop UI automation, or validate every template. The SAP JE draft is disabled; the
corrected COGNOS JE formatting still needs confirmation and implementation. Scheduled work
requires its own validation after supervised trials. A green setup report only proves the
reported runtime prerequisites, not that CRF works against your files.

## When something fails

Ask for cpa-workflow-feedback. It prepares a short message you review and send privately to
Billy: what you requested, what you expected, what happened, the exact sanitized error, and the
plugin version if known. Remove people, amounts, sensitive paths/URLs and raw report contents.
No recording or local file saving is required. Do not try to repair the plugin yourself.

Finish with: **You** approve access, supply confirmed inputs, review and send. **Claude** plans,
uses approved tools and reports results/blockers. **Stop and ask** when access, source data,
verification or the task scope is unclear.
