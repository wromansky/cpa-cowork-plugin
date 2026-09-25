---
name: cpa-getting-started
description: Explain Cowork and the CPA plugin to a first-time user in plain language. Run when the user says "I have only used chat", "teach me Cowork", "how do I use this plugin", "what should I try first", or "why use this instead of chat", or when the dispatcher receives a request for orientation. Teach first; do not start setup or a workflow without consent.
---

# cpa-getting-started

## When to run
- The analyst is new to Cowork or wants a short explanation, first-task walkthrough or refresher.
- The dispatcher receives a learning/help request rather than a request to run a business workflow.
- A scheduled request arrives: return a brief invitation to an attended lesson; do not access
  files, run setup, demonstrate a browser or start financial work unattended.

## Inputs
- Her question and optionally the interface controls she sees. No sensitive files or screenshots needed.
- `references/first-session.md`: the practical lesson, prompt examples and review checklist.
- `references/claude-docs.md`: official documentation and boundaries between Claude and CPA.
- No workspace, connector, runtime readiness or browser access is required for teaching only.

## Steps
1. Read both references. Start with reassurance: "You can talk to Claude normally; you do not
   need commands or programming. CPA adds repeatable work instructions and tested tools, while
   you keep the decisions and review." State that this is teaching only: no file access or
   changes unless she chooses an action. Do not launch setup just because this skill loaded.
2. Give a short explanation of the practical difference: conversation is useful for exploring,
   drafting and explaining; delegated tasks can work through multiple steps with approved files
   and tools. Chat can also create files and current Claude interfaces may merge both experiences.
   The benefit is less repeated briefing and manual handoff, not a guaranteed smarter answer,
   error-free accounting or lower usage. Explain the plugin/skill distinction in one sentence.
3. Ask at most one simple question if needed: "Would you like a quick tour, or help starting
   your first supervised CRF check?" If she asks where to click, ask which controls she sees.
   If Chat/Cowork controls are present, use Cowork; if unified, continue in the conversation.
   Skills may appear through `/` or `+`; natural-language requests are sufficient. Do not invent
   a missing menu, require a UI reset, or ask for terminal commands or software installation.
4. Teach one small next step, not the entire manual. Use the first-session reference to explain
   how to give an outcome, named inputs, period/status, boundaries and expected result; how to
   review a proposed plan; and how to pause or redirect unexpected work. Offer one copyable
   prompt. Keep the initial response to about one screen unless she asks for the full lesson.
   Explain that source files may be processed by Anthropic; folder access is not local-only
   processing or organization approval. Use only work data approved for this account/environment.
5. Keep explanation separate from execution. If she explicitly requests setup, hand off to
   cpa-setup, which alone provisions the sandbox runtime. If she requests workspace confirmation,
   cpa-core must confirm the exact accessible approved location; never create a substitute.
   If she requests a first CRF trial, require setup/workspace readiness and approved manual exports,
   ask for a read-only input review first, and stop after a missing-input report for her review.
   A supplied prompt is not authorization to execute it. No browser, schedule or live source action
   is started by this orientation. Business work proceeds only through the relevant existing skill.
6. Explain review in plain language: outbox holds drafts for her review, not sent work; workbooks
   carry Source & Notes and Verification for different purposes. Run cpa-verify only through the
   chosen workflow, not as a pretend demo. NOT_RECALCULATED is a real blocker: automatic workbook
   recalculation is unsupported and cached values are not proof. Branding uses her supplied
   standard, but protected templates and unfinished slide-layout support require visual review.
   She approves access, handles login/MFA herself, checks outputs and sends them manually.
7. Finish with a short "You do / Claude does / Stop and ask" recap and exactly one suggested next
   action. Offer cpa-workflow-feedback for a reviewed, sanitized message to Billy when something
   fails. Do not promise that installing a plugin grants a connector or source-system access,
   that she can safely walk away from financial work, or that this session proves acceptance.
8. By default, leave the lesson in the conversation: no run record was written. Only if she
   explicitly requests a saved orientation record AND cpa-core has confirmed the approved
   workspace and runtime readiness, run `python -m cpa state record --skill cpa-getting-started
   --verification "orientation only; no workflow executed" --duration <seconds>` through the
   loaded cpa-core launcher. This writes only the generic logs/runs/ record, not her questions
   or private data. If unavailable, keep teaching without a record; never install dependencies,
   create a workspace or imply something was saved to satisfy the logging convention.

## Outputs
- A concise conversational lesson, one copyable next-step prompt and a realistic review checklist.
- No financial artifact, browser session, setup action or automatic workflow run from teaching.
- Optional generic logs/runs/ orientation record only on explicit request and confirmed readiness.

## Verify
- She can describe the next step in her own words or asks to proceed; do not administer a quiz.
- Instructions match the interface she actually sees, not an assumed product rollout.
- Clearly distinguish what Claude can generally do, what CPA implements, and what is untested.
- Identify any tool action separately from explanation; never report a described demo as executed.
- No automatic calculation, source access, local-only privacy or error-free-result promises.

## If something is wrong
- She has no Cowork button: explain the unified rollout; ask what she sees, not for sensitive screenshots.
- Skill/plugin is absent or disabled: refer to the analyst quickstart or Billy; do not guess an installation path.
- Account restrictions or organization policy prevent access: stop and ask the administrator/Billy;
  never bypass permissions or move data to a personal account.
- Setup/workspace access fails: route to the appropriate skill for the actual error, with her consent;
  education can continue without files. Never create a replacement workspace.
- A request mixes learning and unattended execution: teach first, then ask for an attended next step.

## Never
- Never ask her to run a terminal, install local Python/Git/browser add-ons, or edit plugin code.
- Never start setup, inspect files, open a browser, schedule work or generate financial output merely to teach.
- Never promise Cowork is always better than chat, always cheaper, local-only, or automatically correct.
- Never treat platform capabilities as proof that this plugin has implemented or validated them.
- Never grant blanket access, suggest skipping approvals, or bypass organization data-use rules.
- Never enter credentials, transmit raw feedback, send/post an artifact or automate source-system writes.
- Never guess a rate, department, period, TaskKey, report path or a successful verification result.
