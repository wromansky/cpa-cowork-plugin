# Install CPA in Cowork

**For the analyst.** You need Claude Desktop with Cowork available. You do **not** need to clone
this repository, open PowerShell, install Python, or run a command yourself.
Keep real exports in your approved CPA workspace; do not paste sensitive data into chat.

**Before you start:** ask Billy to confirm that use of this CPA plugin is approved for your work.
This public installation copy contains no live exports or approved rate values; keep confirmed
rates and all business data in your approved workspace, not in a public repository.

## 1. Add the plugin

1. Open **Claude Desktop → Cowork → Customize → Personal plugins**.
2. Select **+ → Add marketplace**. Paste
   `https://github.com/wromansky/cpa-cowork-plugin` and select **Sync**.
3. Install the plugin named **cpa** and turn it on under Personal plugins.
4. Start a **new Cowork conversation** with the plugin enabled. For this release, confirm the
   mounted bundle reports **0.2.6**; an older copy may still be present after an update.

If the marketplace or **cpa** does not appear, stop and ask Billy for help. You should not need
a terminal or a local software install.

### Bundled branding

The plugin includes your analyst-authored `jhm-brand` standard and supplied assets. After
confirming the updated plugin loads its bundled `branding` skill, disable the standalone copy to
avoid competing copies. Your brand rules supersede earlier CPA styling, including workbooks;
financial verification remains separate. Known source conflicts have documented resolutions;
remaining template/layout mismatches must be flagged, not silently treated as compliant.
Test actual files in Cowork after syncing: review fonts, header/tab colors, layout and artwork,
Source & Notes, and Verification. Automated tests are not visual acceptance.

## 2. Ask Cowork to set up CPA

Copy and send this message in Cowork:

> Use the cpa-setup skill to set up CPA in this Cowork session. Check the packaged runtime,
> provision only its approved pinned packages inside Cowork if needed, and show me the final
> readiness report, including the loaded launcher path, bundle version, and chosen interpreter.
> Use the currently loaded skill, not an older plugin copy. Do not install software on my computer.
> If a skill, Python, or the bundle
> is missing, stop and tell me what failed; do not ask me to use PowerShell.

Cowork should show a report for the **bundle**, **Python**, and **dependencies**; all three must
be ready. Automatic workbook recalculation is **unsupported**.
Do not run a workflow requiring recalculation until a supported path
is verified. A successful setup report does not mean workbook calculations have been verified.

## 3. Check the workspace before putting files in it

Send this message:

> Use cpa-core to find my CPA workspace and show me the exact folder you can actually access.
> Confirm it is my real OneDrive folder on this computer, not a temporary Cowork folder.
> If it does not exist yet, ask me before creating it in my existing OneDrive folder. If
> you cannot access that folder, stop and tell me; do not create a substitute workspace.

Your OneDrive folder may already be on your **C: drive**. The important check is that Cowork
can see the *same* folder you use, not just a folder with a similar name. You should not need
to set an environment variable yourself. If Cowork cannot access the real folder, send Billy
the result; do not move files into a temporary workspace.

## 4. Begin with a supervised run

Ask: **“Use cpa-workflow-feedback to walk through my COGNOS CRF process with me and record
reviewed, sanitized notes for me to send to Billy.”** She signs in herself. If Cowork has no approved browser
connection, start with a manual export and a sanitized example finished report instead. Browser
feedback is a short message she reviews and sends herself, not a recording or skill export.
Local saving is optional; notes alone need no workspace or browser. Nothing is sent automatically.

The old SAP-based JE draft is disabled. JE now needs confirmation of the COGNOS report, font,
and highlight rule; sending to Accounting stays manual.

Once setup and workspace access are confirmed, ask Cowork to initialize the CPA workspace and
show which information it still needs from you. Provide only values you have confirmed, including the JHM fringe rate needed by this public
installation; never let it guess a rate, department, report URL, person, or TaskKey. For the first real workflow,
watch the run, review the result in **outbox**, and open any workbook in Excel to check the
formulas, recalculated figures, and Verification tab. **Nothing should be sent or posted for you.**

Do **not** turn on scheduled tasks or unattended source pulls yet. Set those up only after the
first supervised runs and workbook check succeed with Billy. If anything fails, share Cowork's
report with Billy; the fix belongs in the CPA product, not in a command you run on your PC.
