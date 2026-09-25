# Branding integration: resolved precedence and acceptance boundaries

Billy approved public distribution of the analyst-authored jhm-brand source and supplied assets,
confirmed that it supersedes CPA visual defaults, and authorized resolving its contradictions.
Original analyst-brand.md, colors.md and assets-source.md are preserved unchanged for provenance.
This document records the operative integration decisions; use these resolutions when the
original passages disagree. They are maintainer decisions pending her visual acceptance in Cowork,
not a claim of separate approval by JHM Communications.

## Resolved rules

1. **Typography:** Lato is the preferred document font. Arial is the sole approved fallback and
   the explicit slide-master/executive-summary default. Deterministic writers use Arial for
   portable output without assuming Lato is installed or downloading fonts. The isolated Calibri
   fallback in the workbook table loses to the explicit prohibition and final checklist.
2. **Identity and logo:** the CPA-specific entity rules and numbered CPA layouts outrank generic
   enterprise examples. Default identity is Clinical Practice Association / Johns Hopkins
   University School of Medicine. Recurring footers use Clinical Practice Association; formal
   Vice Dean wording is not the default. Use the supplied vertical SOM artwork unchanged, not
   a fabricated horizontal or enterprise mark.
3. **Cover and closing:** numbered layouts 1 and 5 govern: white backgrounds, navy left border,
   long gold rules, SOM logo bottom-left on WHITE beside (not over) the navy border, with required
   clear space. No campus photo. This overrides the generic bottom-right logo guidance and the
   assets README's campus recommendation. The campus JPEG is retained for explicitly requested,
   suitable non-cover/non-closing layouts; it is not a default decoration.
4. **Missing logos:** no white/reversed SOM or enterprise logos are supplied. Do not reconstruct
   or recolor them. Use the approved light-background CPA layout; if health-system/dark artwork
   is specifically required, stop for the official asset. Never deliver a placeholder as final.
5. **Colors and charts:** main skill section 1 governs usage and series order: navy #002D74,
   gold #F3C300, teal #007078, olive #638C1C, sky/steel blue #00A0DF, gray #9D958C. Favorable uses
   navy/gold; unfavorable uses warm gray #6E615D or dark olive #AB8900, with explicit labels.
   No red/green performance pair. The palette reference supplies available colors, not an
   alternative semantic encoding or chart sequence.
6. **Conflicting palette numbers:** HEX is the digital representation used by writers. Violet
   #8A1A9B resolves to RGB 138,26,155; khaki #857550 to 133,117,80. Their contradictory RGB entries
   are not used. Print PMS/CMYK conversion is not implemented or asserted as verified.
7. **Workbooks:** the tab is named Source & Notes, as in the workbook-specific rule. Verification
   remains separate. Headers use navy/white; neutral alternating rows use #F2F2F2. Summary/output
   tabs are navy, input/assumption tabs gold, reference/lookup gray, scenarios teal. No assumptions
   or financial cells are created merely to fill a role. Number formats stay appropriate to the
   data; branding never converts a ratio into dollars or discards required precision.
8. **Legacy color-role names:** runtime compatibility keys map ice_blue to approved steel blue
   gray #A3BBC3 and dark_green to approved olive #638C1C. Generated workbook headers are navy,
   not the legacy green. Missing-activity flags use approved bright yellow #FFDD00. These are
   visual integration mappings, not newly invented financial assumptions. Old workspace brand
   settings no longer override the supplied standard; analyst assumptions are never rewritten.
9. **Text sizes:** slide body text is 18–22 pt; titles, table labels, footnotes and page numbers
   use their distinct source scales. Do not apply a blanket 18pt floor to a legitimate footnote.
   Layout and readability need human inspection; a generic text-box lint cannot infer every role.

## Preservation and generation

The source's asset paths resolve under this skill. The original campus-bg.png is JPEG data;
assets/campus-bg.jpg contains exactly the same bytes, with the corrected extension.

Newly generated worksheet tables receive approved typography, navy headers, neutral banding and
role-colored tabs without changing values, formulas, number formats, panes or protection.
Existing semantic flag fills are preserved. Helpers must not be applied wholesale to analyst
or template sheets, even if sheet protection is off. Verification produces a separate Source &
Notes tab from recorded figure provenance only when that tab is absent; an existing analyst tab
is never overwritten. Empty provenance is labeled for review, not invented. Original financial
sheets remain untouched by verification. These changes do not implement recalculation.

Template-driven CRF, budget, APP and refresh paths retain existing layout and protected cells.
Only explicitly generated cells/tabs may acquire new styling. Report any remaining visual
mismatch as a template-review item; do not clear protection or silently reformat the template.
Source & Notes may be added alongside Verification; existing source-note cells remain protected
by template diffs. Streaming files must stay on the cpa.bigxlsx path; unsupported full-style
inspection is a visible limitation, never permission to load a large workbook wholesale.

Generated presentation helpers set Arial and 16:9 dimensions without changing figure text or
speaker notes. They do not rebuild a protected/source deck or invent cover content. Existing
specialized slide writers are not complete implementations of all five brand layouts. No
automatic cover/logo placement, chart recoloring, Word generator or comprehensive visual validator
is claimed by these helpers. Use the skill's layout rules in Cowork and report remaining renderer
mismatches rather than claiming that typography normalization alone ensures brand compliance.

## Acceptance in Cowork

Local tests use synthetic inputs and preservation assertions, not visual samples for approval.
After the release, the analyst tests the actual output in Cowork: fonts, header/tab colors,
identity, artwork/spacing, overflow, source notes and Verification. She reviews legacy templates
before any restyling and reports the exact file, workflow and mismatch. No automated sending.
Disable the standalone skill only after the bundled branding skill is confirmed loaded.
