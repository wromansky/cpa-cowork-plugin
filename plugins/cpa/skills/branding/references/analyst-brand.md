---
name: jhm-brand
description: >
  Apply Johns Hopkins Medicine (JHM) and CPA brand standards to any deliverable — PPTX decks,
  XLSX workbooks, Word documents, and executive summaries. Use whenever producing output for a
  JHM or CPA audience: executive presentations, financial models, operational reports,
  physician leadership communications, or standalone executive summaries. Trigger on any
  mention of Hopkins, JHM, CPA, Clinical Practice Association, slide deck, presentation,
  workbook, Word doc, executive summary, or executive report — even without explicit brand
  requests. All deliverables must identify as originating from the Clinical Practice
  Association, Office of the Vice Dean for Clinical Affairs, Johns Hopkins University School
  of Medicine. Encodes colors, typography, logo rules, layout conventions, CPA identity
  placement, and physician executive audience standards.
---

# Johns Hopkins Medicine Brand Standards Skill

This skill ensures all outputs — PPTX, XLSX, DOCX, and executive summaries — comply
with official JHM brand standards, carry consistent CPA identity, and are calibrated
for a physician executive audience.

**Always read this file fully before producing any branded deliverable.**
For the complete color palette with HEX/RGB/PMS values, read:
→ `references/colors.md`

---

## 0. CPA Identity Standards

Every deliverable produced under this skill originates from the **Clinical Practice
Association (CPA)**. CPA identity must appear consistently across all output types.

### The Entity Line
The primary CPA identifier is simply:
> **Clinical Practice Association**
> Johns Hopkins University School of Medicine

Use the two-line form on cover slides, DOCX title pages, and executive summary headers.
Use **Clinical Practice Association** alone in footers, sub-headers, and recurring elements.

The full form — *Clinical Practice Association | Office of the Vice Dean for Clinical
Affairs* — is reserved for formal external communications or when the Vice Dean's office
is the explicit point of contact. Do not use it by default.

### CPA Identity by Output Type

| Output | CPA Treatment |
|---|---|
| PPTX cover slide | "Clinical Practice Association" below title; SOM logo bottom-left adjacent to navy border |
| PPTX content slides | Footer: "Clinical Practice Association" left-aligned, page number right |
| PPTX last slide | "Clinical Practice Association \| Johns Hopkins University School of Medicine" + SOM logo |
| DOCX title page | Two-line form below document title |
| DOCX footer | "Clinical Practice Association \| Johns Hopkins University School of Medicine" |
| XLSX cover/summary tab | "Clinical Practice Association" in cell beneath title |
| Executive summary header | Two-line form + date + "Prepared by: [Author], CPA" |

### Signing Authority
When a deliverable is signed or attributed, the standard form is:
> [Name], [Title]
> Clinical Practice Association
> Johns Hopkins University School of Medicine

---

## 1. Color System

### Primary Brand Colors (use for all core design elements)

| Role | Color | HEX | RGB | PMS |
|---|---|---|---|---|
| Primary Navy (dominant) | Hopkins Blue | `#002d74` | 0, 45, 116 | 288 C |
| Primary Gold (accent) | Hopkins Gold | `#f3c300` | 243, 195, 0 | 7406 C |
| Background | White | `#ffffff` | 255, 255, 255 | — |
| Body text / rules | Black | `#000000` | 0, 0, 0 | — |

> ⚠️ No color substitutions are permitted for the primary navy and gold in logo reproduction.
> No other blues or golds may stand in for the official PMS values.

### Color Usage Hierarchy (PPTX / XLSX / DOCX)
1. **Navy `#002d74`** — slide headers, section dividers, table headers, chart primary series, document headings
2. **Gold `#f3c300`** — accent bars, callout highlights, key metric boxes, secondary chart series
3. **White** — slide/page background, reversed text on navy fields
4. **Black** — body text, footnotes, data labels
5. **Supportive palette** — tertiary chart series, categorical data only; see `references/colors.md`

### Colorblind Safety Rule (MANDATORY)
- **Never use red and green together** to encode meaning (e.g., good/bad, up/down)
- Approved substitutions for performance coding:
  - Positive / on target → Navy `#002d74` or Gold `#f3c300`
  - Negative / below target → Neutral gray `#6e615d` (PMS WG10 C) or dark olive `#ab8900`
  - Use pattern fills or data labels as a secondary indicator when color alone is insufficient

### Chart / Data Visualization Color Sequence
For multi-series charts, pull from the supportive palette in this preferred order to ensure
contrast and brand alignment:
1. Navy `#002d74`
2. Gold `#f3c300`
3. Teal `#007078` (PMS 322 C — sophisticated)
4. Olive `#638c1c` (PMS 370 C — sophisticated)
5. Steel blue `#00a0df` (PMS 299 C — bright)
6. Warm gray `#9d958c` (PMS 402 C — neutral)

For full supportive palette options, see `references/colors.md`.

---

## 2. Typography

### Font Stack

| Context | Primary Font | Fallback |
|---|---|---|
| All documents | **Lato** | Arial |
| PPTX (Slide Master) | Lato | Arial |
| XLSX | Lato | Calibri → Arial |
| DOCX | Lato | Arial |

> Arial is the **only approved substitute** when Lato is unavailable (standard in
> PowerPoint and Word environments). Do not use Calibri, Cambria, or any other font
> as a brand-compliant default.

### Type Scale — PPTX

| Element | Font | Size | Weight | Color |
|---|---|---|---|---|
| Slide title | Lato / Arial | 28–32 pt | Bold | Navy `#002d74` or White (on navy bg) |
| Section divider title | Lato / Arial | 36–40 pt | Bold | White (on navy bg) |
| Body / bullet text | Lato / Arial | 18–22 pt | Regular | Black `#000000` |
| Chart title | Lato / Arial | 14–16 pt | Bold | Navy `#002d74` |
| Data labels | Lato / Arial | 10–12 pt | Regular | Black or White |
| Footnote / source line | Lato / Arial | 9–10 pt | Regular | Gray `#6b6b6b` |

### Type Scale — DOCX

| Element | Font | Size | Weight |
|---|---|---|---|
| Document title | Lato / Arial | 20–24 pt | Bold |
| H1 heading | Lato / Arial | 16–18 pt | Bold |
| H2 heading | Lato / Arial | 13–14 pt | Bold |
| Body text | Lato / Arial | 11 pt | Regular |
| Table header | Lato / Arial | 11 pt | Bold |
| Footnote | Lato / Arial | 9 pt | Regular |

---

## 3. Logo Rules

### Entity Context — Which Logo to Use
The **Clinical Practice Association (CPA)** sits within **Johns Hopkins University /
School of Medicine** — not the Johns Hopkins Medicine health system. This distinction
governs logo selection:

| Context | Logo to Use | File |
|---|---|---|
| **CPA deliverables (default)** | Johns Hopkins School of Medicine | `assets/som-logo.png` ✅ |
| Health-system-facing work (JHH, JHBMC, enterprise) | Johns Hopkins Medicine (horizontal, color) | `assets/jhm-logo.png` |
| Navy/dark background, health-system context | Johns Hopkins Medicine (white/reversed) | `assets/jhm-logo-white.png` |
| **Cover & closing slide background image** | Hopkins campus photograph | `assets/campus-bg.png` ✅ |

### Logo Asset — SOM (Primary for CPA)
The SOM mark is a vertical configuration:
- **Symbol** — navy shield with dome/triangle mark
- **Logotype** — "JOHNS HOPKINS" / "SCHOOL of MEDICINE" stacked wordmark, navy

**For programmatically generated files (PPTX/DOCX):**
- Primary logo file: `assets/som-logo.png` — navy monochrome, vertical, for white/light backgrounds
- This file is **already embedded** in the skill assets folder
- If placed on a navy background, use a white-reversed version (not yet available —
  insert placeholder: "SOM LOGO WHITE — INSERT OFFICIAL PNG")
- Never reconstruct the logo with fonts or shapes as a substitute

### Hard Rules (non-negotiable per JHM brand policy)
- **Never alter, add, or redraw** the logo in any way — treat it as artwork only
- **Never use other colors** in the logo — navy and gold only, exactly as provided
- **Never combine** with another organization's name, logo, or mark
- **No custom department or division logos** — CPA does not have its own mark;
  use the JHM logo to unify under the enterprise brand
- **Never create a purpose-specific custom logo** — this dilutes brand equity
- **Always use the primary logo files** provided by JHM Communications

### Preferred Configuration
- **Horizontal layout** (symbol left + logotype right) — preferred in all cases
- **Vertical layout** (symbol above + logotype below) — second choice only when
  horizontal does not fit the space

### Color Versions & Background Rules
| Background | Logo Version to Use |
|---|---|
| White or light (`#ffffff`) | Full color (navy + gold) — **preferred; use whenever possible** |
| Navy (`#002d74`) | White/reversed version |
| Dark gray or dark photo | White/reversed version |
| Never place on: | Busy patterns, gradients, or any color that reduces contrast |

### Placement on Slides
- **Cover/title slide**: bottom-right corner, or top-left — with clear space on all sides
  equal to the height of the triangle symbol
- **Content slides**: logo not required on every slide; include on first and last slide minimum
- **Section dividers**: omit the logo — the navy field carries the brand identity
- **Footer bar option**: a thin navy footer bar (0.2–0.3" height) with the white logo
  is an acceptable persistent treatment on content slides if desired

### Clear Space Rule
Maintain clear space around the logo on all four sides equal to the height of the
triangle/dome symbol. No text, rules, or graphic elements may enter this zone.

---

## 4. Slide Layout Conventions (PPTX)

### Slide Master Principles
- Background: white (`#ffffff`) for content slides; navy (`#002d74`) for section dividers
- All slide masters must set the default font to **Arial** (Lato fallback when embedded)
- Slide dimensions: **16:9 widescreen** (13.33" × 7.5") — standard for JHM executive decks

### Layout 1 — Title / Cover Slide
- **Background**: White (`#ffffff`) — clean, light, professional. No campus image or background photography.
- **Left border**: Solid navy (`#002d74`) vertical bar, 0.3–0.4" wide, full slide height — anchors brand identity along the left edge
- **Title**: Large, bold, navy `#002d74`, Lato/Arial, 36–44 pt — left-aligned in the content zone (to the right of the navy border)
- **Subtitle / date / presenter**: Lato/Arial, 20–24 pt, Hopkins Gold `#f3c300` — left-aligned beneath the title
- **Gold framing lines**: Two horizontal gold rules (`#f3c300`, 2–3 pt weight) running full slide width (13.33") — one above the title block, one below the subtitle/date line. These are structural framing elements, not short accent bars. Minimum length: 80% of slide width.
- **SOM logo**: Bottom-left corner, inside or immediately adjacent to the navy vertical border, with required clear space
- **CPA entity line**: "Clinical Practice Association | Johns Hopkins University School of Medicine" — below or beside logo, 11–13 pt, navy on white background

### Layout 2 — Section Divider
- Full navy background
- Section title: bold white, Lato/Arial, 36–40 pt, centered or left-aligned
- **Gold horizontal rule**: full slide width (13.33"), 2–3 pt — placed below the title as a structural separator, not a short decorative accent
- No content — clean and minimal

### Layout 3 — Content + Chart
- White background
- Navy title bar at top (0.5–0.75" height), white title text
- Chart occupies 60–70% of slide body
- Source / footnote line at bottom: right-aligned, 9 pt gray
- **Every chart must have a labeled data source** (bottom of slide or chart footnote)

### Layout 4 — Two-Column
- White background, navy title bar
- Left column: narrative / bullets (max 4 bullets per column, 3 preferred)
- Right column: chart, table, or supporting data
- Dividing rule: 1 pt, gold `#f3c300` or light gray — never navy on white (too heavy)

### Layout 5 — Closing / Final Slide
The closing slide mirrors the cover slide in visual treatment to bookend the deck with brand consistency.
- **Background**: White (`#ffffff`) — matches cover slide. No campus image or background photography.
- **Left border**: Solid navy (`#002d74`) vertical bar, 0.3–0.4" wide, full slide height — identical placement to cover slide
- **Content**: Closing message (e.g., "Thank You," "Questions?", or a key call to action) — bold navy `#002d74`, Lato/Arial, 36–44 pt, left-aligned in the content zone
- **Gold framing lines**: Two horizontal gold rules (`#f3c300`, 2–3 pt) running full slide width — one above the closing message, one below it. Same framing structure as the cover; minimum 80% of slide width.
- **SOM logo**: Bottom-left corner, consistent with cover slide placement
- **CPA entity line**: "Clinical Practice Association | Johns Hopkins University School of Medicine" — 11–13 pt, navy, beneath or adjacent to logo
- Contact / attribution line (optional): presenter name, title, email — 12–14 pt, navy or gold
- **No page number** on the closing slide

> The cover and closing slides form a visual pair. Both use a white background with a left navy vertical border and full-width gold framing lines. Logo position and gold line framing must be identical between them.

### Universal Slide Rules
- **Maximum 4 bullets per slide; 3 preferred** for physician executive audiences
- Bullets should be conclusion-first (lead with the insight, not the setup)
- **No clip art, no stock illustration, no decorative icons** unless from JHM-approved photography library
- No WordArt, no drop shadows on text
- Consistent left margin: 0.5" from slide edge for all body text
- Page numbers: bottom-right, 10 pt, gray — include on all content slides

---

## 5. XLSX Workbook Standards

- **Tab color coding**: Navy `#002d74` for primary/summary tabs; Gold `#f3c300` for input/assumption tabs; Gray for reference/lookup tabs
- **Header rows**: Navy fill `#002d74`, white bold text, Lato/Arial 10–11 pt
- **Alternating row shading**: light gray `#f2f2f2` — never use color fills to encode meaning without a legend
- **Currency / number format**: `$#,##0` for whole dollars; `$#,##0.0` for one decimal; `0.0%` for percentages
- **Chart defaults in XLSX**: follow the same color sequence defined in Section 1
- **Source tab**: every workbook should contain a "Source & Notes" tab documenting data origins
- **No red/green conditional formatting** without an accompanying legend and colorblind-safe alternative

---

## 6. DOCX Document Standards

- **Letterhead**: use official JHM personalized letterhead template when producing external-facing documents
- **Heading colors**: H1 in navy `#002d74`; H2 in dark gray or navy; body in black
- **Table headers**: navy fill, white bold text — matches PPTX and XLSX convention for visual consistency
- **Footer**: include document title, date, and "Johns Hopkins Medicine | Clinical Practice Association" or relevant entity
- **Page margins**: 1" all sides (standard); 0.75" permitted for dense financial/operational reports
- **Source citations**: footnote format, 9 pt Lato/Arial, gray — required for any externally sourced data

---

## 7. Physician Executive Audience Standards

These govern tone, structure, and content decisions across all output types.

### Tone
- **Authoritative and precise** — physician executives respond to evidence, not hedging
- **Conclusion-first** — lead every section, slide, and bullet with the finding or recommendation
- No filler language ("it is important to note that…", "as we can see…")
- Avoid jargon that is administrative rather than clinical or financial

### Content Rules
- **Always cite data sources** — every chart, table, and statistic requires attribution
- **No red/green for performance coding** (colorblind rule applies to content design too)
- Benchmarks and comparators should be explicitly labeled (e.g., "JHM peer median," "MGMA 50th %ile")
- Financial figures: always specify whether net or gross, professional or technical, YTD or annualized
- wRVU figures: always specify the RVU conversion factor and time period

### Structure for Executive Decks
1. **Situation** — what is the current state (data-backed)
2. **Complication** — what is the gap, risk, or opportunity
3. **Resolution** — recommended action or decision requested
4. **Appendix** — supporting detail, methodology, raw data

Keep the main deck to the decision-relevant content only. Park methodology and granular
data in the appendix.

---

## 8. Executive Summary Standards

Executive summaries are standalone branded documents — typically 1–2 pages — that
accompany or precede a full PPTX deck or XLSX model. They follow all JHM brand and
CPA identity rules and are written for physician executive decision-makers.

### Header Block (required on every executive summary)

The header should be visually set apart — navy top border rule (2–3 pt), title in
navy bold Arial/Lato 14 pt, entity line in 10 pt gray below:

- Line 1: Document Title (navy bold)
- Line 2: Clinical Practice Association
- Line 3: Johns Hopkins University School of Medicine
- Line 4: Date (Month DD, YYYY)
- Line 5: Prepared by: [Name], [Title], CPA

### Structure
Executive summaries follow the same SCR logic as executive decks:

1. **Purpose / Background** (2–3 sentences) — why this document exists and who requested it
2. **Key Findings** — 3–5 bullets, conclusion-first, data-anchored; include source inline
3. **Implications / Recommendations** — what leadership should decide or act on
4. **Next Steps** (optional) — owner, action, timeline in a simple table

### Formatting Rules
- Length: 1 page strongly preferred; 2 pages maximum
- Font: Arial 11 pt body; Arial Bold 13–14 pt section headers
- Section header color: navy `#002d74`
- Top border rule: navy, 2–3 pt — runs full page width
- Bottom footer: "Clinical Practice Association | Johns Hopkins University School of Medicine"
  in 9 pt gray, page number right-aligned
- No decorative imagery, no clip art
- Tables: navy header row, white bold text, alternating gray rows `#f2f2f2`
- Every statistic must have an inline source or footnote

### When an Executive Summary Accompanies a Deck
- The exec summary is the leave-behind / read-ahead; the deck is the presentation vehicle
- Both must be consistent: same title, same date, same key findings
- The exec summary must stand alone without the deck

---

## 9. Compliance Checklist

Before delivering any output, verify:

**Brand & Visual**
- [ ] Colors limited to JHM primary + approved supportive palette
- [ ] No red/green performance coding
- [ ] Font is Lato or Arial only
- [ ] Logo (if present) is unmodified official SOM or JHM artwork
- [ ] No clip art or unapproved imagery

**CPA Identity**
- [ ] CPA entity line present in correct location for output type
- [ ] Signing authority block uses correct CPA format (if attributed)
- [ ] Footer includes "Clinical Practice Association" on every page/slide

**Content & Data**
- [ ] Every chart and statistic has a labeled data source
- [ ] Bullets 4 or fewer per slide/section; conclusion-first throughout
- [ ] Financial figures specify net/gross, professional/technical, YTD/annualized
- [ ] wRVU figures specify conversion factor and time period

**By Output Type**
- [ ] PPTX: navy/gold slide master applied; page numbers on content slides
- [ ] XLSX: navy/gold tab color coding applied; Source and Notes tab present
- [ ] DOCX: navy heading colors, CPA footer, correct margins
- [ ] Executive summary: header block complete; SCR structure; 1-2 page limit

---

## Reference Files

- **`references/colors.md`** — Complete JHM supportive color palette with all HEX, RGB, and PMS values,
  organized by family (Sophisticated, Bright, Neutral). Read this when selecting accent or
  chart colors beyond the primary navy and gold.
