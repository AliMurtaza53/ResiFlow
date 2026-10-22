# FIGURE_GUIDE.md — Publication Figure Reference

A single reference for producing publication-quality figures for peer-reviewed
journals, written to be handed to an LLM coding assistant (e.g. Claude Code) or
used by a human author. It has four layers:

1. **Principles** — how humans read charts (what to optimize for).
2. **Chart-craft** — per-chart-type rules, calibrated to this project's figures.
3. **Hard specs** — exact numbers for the target journal (Transportation
   Research Part D / Elsevier), with other majors for reference.
4. **Executable defaults** — a matplotlib style block and a pre-flight checklist.

Primary sources, in order of authority for this file:
- Schwabish, J. (2021). *Better Data Visualizations*. Columbia University Press.
  (principles + chart-by-chart craft; quoted where marked)
- Wilke, C. (2019). *Fundamentals of Data Visualization*. O'Reilly. Free at
  https://clauswilke.com/dataviz (figure-design principles, color, composition)
- Rougier, Droettboom & Bourne (2014). "Ten Simple Rules for Better Figures."
  *PLOS Comp Biol* 10(9):e1003833. CC0. Code: github.com/rougier/ten-rules
- Journal author guidelines (Elsevier TR-D, Nature, Science, Wiley) — see §3.

When any two sources conflict, the target journal's hard specs (§3) win for
anything measurable (size, font, dpi), and the principles (§1) win for anything
about clarity.

---

## 0. NON-NEGOTIABLES (read first)

These are the rules that most often cause rejection or reviewer friction. If a
figure violates one of these, fix it before anything else.

- **Every axis has a label with units in parentheses.** e.g. `Direct cost (USD
  billions)`, `Flood depth (m)`. No bare axes, ever.
- **Every color/size/style encoding has a legend** with a stated meaning and,
  for continuous scales, a stated range.
- **Vector output** (PDF/EPS) for anything with lines, bars, or text. Never ship
  a rasterized chart as the final figure.
- **Colorblind-safe palette.** No red/green as the only distinction. Use the
  Okabe–Ito / Wong palette or a named colorblind-safe colormap (viridis,
  cividis, magma). Test in greyscale.
- **Redundant coding.** Never let color be the *only* channel separating series.
  Add line style, marker shape, or hatching so the figure survives B&W printing.
  (Rougier Rule; Wilke Ch. on redundant coding.)
- **One consistent visual identity across the whole paper.** One palette, one
  font, one axis-label style, one panel-label convention. Define once, import
  everywhere.
- **Figure answers a research question.** If a figure maps to no RQ, cut it or
  move it to supplementary. (Group convention.)
- **Caption states the finding, not the mechanics.** "Flood rerouting raises
  average travel cost 18% in coastal counties," not "Travel cost vs. county."

---

## 1. PRINCIPLES — how charts are read

### 1.1 The perceptual ranking (the single most useful idea)

Different visual encodings let readers judge values with different accuracy.
Schwabish reproduces the Cleveland–McGill / Cairo ranking (Better Data
Visualizations, Ch. 1). From most to least accurate:

> **Enable accurate estimation:** Position along a common scale → Position along
> non-aligned scales → Length → Direction/slope → Angle → Area → Volume → Shading
> and saturation → Color hue. *(Better Data Visualizations, "Perceptual ranking
> diagram," Ch. 1)*

Practical consequences for this project:
- **Prefer position and length** (bars, dot plots, aligned small multiples) for
  the numbers that carry your argument (costs, rankings).
- **Area and color are for magnitude *impressions*, not precise reading** — fine
  for a choropleth's "where," weak for "how much." This is exactly why a state
  cost choropleth is a poor *primary* cost display but a good *orienting* map.
- **Color hue is the weakest for quantity** but the *strongest for categories* —
  use hue to label unordered classes (hazards, industries), sequential ramps for
  ordered/continuous quantities (damage ratio, severity). Never a sequential
  ramp for unordered categories.

### 1.2 Schwabish's five guidelines (verbatim frame)

From *Better Data Visualizations*, Ch. 2. These are the working checklist:

1. **Show the data.** "Your reader can only grasp your point... if they see the
   data." Show the data that matter most, not the least or the most.
2. **Reduce the clutter.** "The use of unnecessary visual elements distracts
   your reader from the central data." Remove heavy tick marks, gridlines,
   redundant markers, borders, and fill in almost every case.
3. **Integrate the graphics and text.** Active titles, direct labels, and
   annotations placed *on* the chart instead of in a distant legend.
4. **Avoid the spaghetti chart.** When many series overlap, split into small
   multiples or highlight the few series of interest.
5. **Start with gray.** "Whenever you make a graph, start with all-gray data
   elements. By doing so, you force yourself to be purposeful and strategic in
   your use of color." Color is then *earned* by the series that matter.

### 1.3 Gestalt / preattentive basics (why layout works)

- Readers group by **proximity, similarity, enclosure, and continuity** before
  they read anything (Gestalt, Ch. 1). Use whitespace and grouping to do work
  that borders and boxes otherwise do — small multiples read as a group because
  they share position and scale, not because a box surrounds them.
- **Preattentive attributes** (color, size, orientation) are seen in <250 ms.
  One highlighted bar in a field of gray is found instantly; ten colored bars
  are not. Spend preattentive "pop" sparingly.

### 1.4 Data–ink and small multiples (Tufte, via Rougier/Wilke)

- Maximize the share of ink that encodes data; delete chartjunk (3D, shadows,
  gradient fills, decorative backgrounds).
- **Small multiples** (a grid of small panels sharing axes and scale) are the
  preferred way to compare across a category (hazard, scenario, region). Shared
  scales are what make them comparable — an independent scale per panel silently
  breaks the comparison (see §2.7).

---

## 2. CHART-CRAFT — per-type rules

General layout defaults (apply unless a journal spec overrides):

- **Bar width vs. gap:** bar width should exceed the gap between bars. A common,
  legible default is a gap of ~40–50% of bar width (i.e. bars occupy ~55–70% of
  the category slot). Bars should not be hairline-thin nor touch.
- **Grouped (clustered) bars:** no gap between bars *within* a group; a clear gap
  *between* groups. Keep ≤4–5 bars per group before switching to small multiples.
- **Whitespace:** margins should breathe; do not run bars or text to the panel
  edge. Consistent inter-panel spacing in multi-panel figures.
- **Direct labels over legends** where space allows (Guideline 3). A legend is a
  lookup cost the reader pays on every glance.

### 2.1 Bar charts (Better Data Visualizations, Ch. 4)

- **Start the value axis at zero.** "Starting the axis of bar charts at zero is a
  rule of thumb upon which many data visualization experts and authors agree."
  A non-zero baseline overemphasizes differences and "is a matter of moving from
  accurate to inaccurate."
- **Never break the bar.** "Another cardinal sin... using a squiggly line or
  shape to show that you've cropped one or more of the bars... it distorts the
  relative values between the bars."
- **Outliers / wide dynamic range** (directly relevant when one hazard dwarfs
  another, e.g. landslide vs. Harvey): use the **"zoom out / zoom in"** approach
  — one panel showing all data at true magnitude, a second panel omitting the
  outlier to reveal detail among small values — rather than breaking the bar or
  log-scaling silently. Add value labels and an active title to communicate the
  small differences. *(Better Data Visualizations, Ch. 4, "Extreme values or
  outliers.")*
- **Order by value**, not alphabetically, unless the category has a natural order
  (time, geography). Highlight the bar(s) of interest with color; leave the rest
  gray.
- **Horizontal bars** when category labels are long (state names, facility
  types) — avoids rotated tick labels.

### 2.2 Paired vs. stacked vs. diverging bars (Ch. 4)

- **Paired/clustered bar:** best when the reader compares components *across*
  categories (this group prefers clustered as the default).
- **Stacked bar:** legitimate only for **part-to-whole** where the total also
  matters (e.g. total cost = direct + rerouting + isolation; or severity split
  within one facility's damage). The internal segments beyond the first are hard
  to compare because they lack a common baseline — so stack the component you
  care least about comparing precisely, and put the most-compared component on
  the zero baseline.
- **Diverging bar:** the right tool for deviation-from-baseline / +over / −under
  (e.g. commodity-mix delta). Center on zero, use a two-hue diverging scheme,
  and label the axis direction ("under-represented ← 0 → over-represented") so
  the sign is unambiguous. Avoid red as "negative" if negative isn't "bad."

### 2.3 Choropleth / spatial maps

- **Sequential** color scale for magnitude; **diverging** for change/anomaly.
- **Same projection and same bin edges across every panel** in a small-multiple
  set (this is what makes them comparable).
- Include scale bar, north arrow, legend, and a basemap source credit
  (Elsevier TR-D requires this for GIS figures — see §3).
- Remember the perceptual limit (§1.1): a choropleth communicates *location and
  footprint* well and *magnitude* only roughly. Keep it as an orienting figure;
  put precise magnitudes in bars/dot plots.

### 2.4 Network / disruption maps

- Color edges by a **continuous** severity/damage-ratio scale, not by category,
  when the metric is continuous.
- Keep node size mapped to one consistent quantity (e.g. population or flow
  served) across all panels.
- This is the one map type that shows what a flow model actually produces
  (link-level disruption) and does not duplicate state-aggregated bar figures.

### 2.5 Fragility / damage curves

- x = hazard intensity (native units, labeled), y = damage ratio or failure
  probability (0–1).
- **One line style per asset class held constant across the whole paper** —
  line style, not just color, so it survives greyscale.
- **Always show an uncertainty band** (shaded CI). A deterministic single line
  from a stochastic process invites the reviewer question you don't want.

### 2.6 Resilience / recovery curves

- x = time since event, y = % functionality (or cost decaying to zero).
- Shade the disruption window; annotate recovery milestones (50%, 90%, full)
  with vertical markers.
- Small multiples by hazard/scenario; note whether panels share a y-scale
  (comparable magnitude) or not (comparable shape only) — and say which in the
  caption.

### 2.7 Uncertainty (Rougier; Nature/Science enforced)

- **Never plot a single point estimate from a stochastic model.** Use shaded
  bands, error bars, or box/violin plots.
- **Define the error representation in the caption** (SD, SEM, 95% CI) — this is
  explicitly enforced by Nature/Science.
- For n < 5, show individual points, not a bar or box (Nature rule, §3.1).

### 2.8 Shared-scale rule for small multiples (project-specific, important)

The recurring comparison in a multi-hazard paper is *across hazards*. Therefore
the shared axis should sit on the dimension the reader is meant to compare:
- If comparing magnitude across hazards → share the value axis across all panels.
- If comparing *shape* (e.g. freight vs. passenger split, or recovery decay) →
  you may give each panel/column its own scale, but state it in the caption and
  keep the scale consistent *within* the compared dimension (e.g. one freight
  scale across all hazard rows, one passenger scale across all hazard rows).
- Independent per-panel scales with no note is the most common silent error —
  it makes a tiny hazard look as large as a dominant one.

---

## 3. HARD SPECS — exact numbers

> Target journal for this project: **Transportation Research Part D
> (Elsevier).** Use the Elsevier/TR-D column below as the binding spec. The
> other columns are for reference / co-authored submissions elsewhere.

### 3.1 Elsevier — Transportation Research Part D (BINDING)

| Spec | Value |
|---|---|
| Single-column width | **90 mm** |
| 1.5-column width | **140 mm** |
| Double-column width | **190 mm** |
| Fonts | Arial, Courier, Times New Roman, Symbol, or native LaTeX (Computer Modern) |
| Minimum font size in figures | **7 pt** (at final published size) |
| Vector / line art | **≥ 1000 dpi**; EPS, PDF, or MS Office native |
| Halftone / raster | **≥ 300 dpi**; TIFF or JPEG |
| Combination (line + raster) | **≥ 500 dpi** |
| GIS / maps (Part D specific) | Must include scale bar, north arrow, clear legend; credit basemap source (OpenStreetMap, ESRI, etc.) |
| Axis units | Declared in axis label / column header in parentheses, never in data cells |
| Tables | Editable text (Word table or LaTeX `table`); no images |
| Nomenclature | A "Table of Notations" recommended when >15 distinct math variables |
| Workflow | "Your Paper Your Way" — inline figures allowed at first submission; strict formatting on revision/acceptance |

Official: elsevier.com/researcher/author/policies-and-guidelines/artwork-and-media-instructions
Part D guide: sciencedirect.com/journal/transportation-research-part-d-transport-and-environment/publish/guide-for-authors

### 3.2 Reference — other major publishers

| Spec | Nature | Science | Wiley |
|---|---|---|---|
| Single-column | 89 mm | 90 mm | 80 mm |
| 1.5-column | 120–136 mm | — | 114 mm |
| Double-column | 183 mm | 180 mm | 177 mm |
| Max depth/height | 247 mm | 216 mm | 230 mm |
| Font | Arial/Helvetica (mandatory) | Arial/Helvetica | Arial, Helvetica, Times, Symbol |
| Font size in figure | 5–7 pt (7 pt max) | 5–7 pt | 8–10 pt |
| Panel labels | lowercase **a b c**, 8 pt bold | uppercase **A B C**, 8 pt bold | lowercase in parens **(a) (b)**, top-left |
| Line weights | 0.25–1 pt (no hairlines) | 0.25–1 pt | ≥ 0.5 pt |
| Vector art | 1200 dpi, EPS/PDF/AI, fonts embedded | vector preferred | 600–1200 dpi, EPS/PDF |
| Halftone | 300 dpi TIFF | 300 dpi | 300 dpi TIFF |
| Combination | 600 dpi | — | — |
| Color mode | RGB | RGB | — |

Tables (Nature/Science convention, widely applicable): **no vertical lines**;
only three horizontal rules (top, below header, bottom); no cell shading unless
essential. Table caption **above** the table (Wiley); footnotes below with
superscript lowercase letters; reserve `*, **, ***` for statistical significance.

### 3.3 Panel-label convention for THIS paper

Pick one and apply everywhere. For TR-D/Elsevier, **lowercase letters in
parentheses, top-left of each panel: (a) (b) (c)** matches the Wiley/Elsevier
house style and is the safest default. Keep panel letters 8 pt bold.

---

## 4. EXECUTABLE DEFAULTS (Python / matplotlib)

### 4.1 A starting `rcParams` block (TR-D-tuned)

```python
import matplotlib as mpl

# Fixed, colorblind-safe categorical palette (Okabe–Ito subset).
# Define the project's category->color maps ONCE and import everywhere.
HAZARD_COLORS = {
    "Harvey":                  "#0072B2",  # blue
    "Earthquake (New Madrid)": "#D55E00",  # vermillion
    "Landslide":               "#8C510A",  # brown
    "Winter storm (Jonas)":    "#009E73",  # green
}
INDUSTRY_COLORS = {           # unordered categories -> qualitative hues
    "Manufacturing":    "#4477AA",
    "Ag / forestry":    "#228833",
    "Mining":           "#CCBB44",
    "Petroleum / coal": "#AA3377",
}

mpl.rcParams.update({
    # font: Arial per Elsevier; DejaVu Sans is a safe metric-compatible fallback
    "font.family":       "sans-serif",
    "font.sans-serif":   ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size":         8,     # >= 7 pt at final size (TR-D minimum)
    "axes.titlesize":    9,
    "axes.labelsize":    8,
    "xtick.labelsize":   7,
    "ytick.labelsize":   7,
    "legend.fontsize":   7,
    # clutter reduction (Guideline 2): no top/right spines, light grid
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.color":        "#e6e6e6",
    "grid.linewidth":    0.5,
    "axes.linewidth":    0.6,   # 0.25–1 pt range
    "lines.linewidth":   1.5,
    "legend.frameon":    False,
    # vector output, fonts embedded (Type 42 = TrueType, editable/embeddable)
    "pdf.fonttype":      42,
    "ps.fonttype":       42,
    "savefig.dpi":       1000,  # for any rasterized fallback; prefer PDF
    "savefig.bbox":      "tight",
    "figure.dpi":        150,
})

# Figure widths in inches (TR-D): single 90 mm, 1.5-col 140 mm, double 190 mm
MM = 1 / 25.4
W1, W15, W2 = 90 * MM, 140 * MM, 190 * MM
```

### 4.2 Export

```python
# Always export vector PDF as the deliverable; PNG only for quick preview.
fig.savefig("figure_1.pdf")          # vector, fonts embedded via rcParams
fig.savefig("figure_1.png", dpi=300) # preview / slides only
```

### 4.3 Greyscale + colorblind self-test

```python
# Quick greyscale check: convert the saved PNG to L and eyeball series separation.
from PIL import Image
Image.open("figure_1.png").convert("L").save("figure_1_gray.png")
# Also run through an external simulator (Color Oracle / Coblis) before submission.
```

---

## 5. PRE-FLIGHT CHECKLIST (run before sending to advisor / submitting)

**Substance**
- [ ] Figure maps to a specific research question; caption states the *finding*.
- [ ] Referenced in the text (no orphan figures).
- [ ] Every stochastic quantity shows uncertainty (band / error bar / box).

**Encoding**
- [ ] Value-carrying comparisons use position/length, not area/hue.
- [ ] Unordered categories → qualitative hues; ordered/continuous → sequential ramp.
- [ ] Color is not the only channel (line style / marker / hatch redundancy).
- [ ] Bars start at zero; no broken bars; outliers handled by zoom-out/zoom-in.
- [ ] Small multiples share scale on the compared dimension; any per-panel scale
      is stated in the caption.

**Labels & legend**
- [ ] Every axis labeled with units in parentheses.
- [ ] Legend meaning + range stated; direct labels used where they fit.
- [ ] Maps: scale bar, north arrow, legend, basemap credit.
- [ ] Panel labels consistent: (a) (b) (c), 8 pt bold, top-left.

**Format (TR-D)**
- [ ] Final width = 90 / 140 / 190 mm; nothing rescaled after the fact.
- [ ] Font Arial (or metric-safe), ≥ 7 pt at final size; ≤ 3 font sizes total.
- [ ] Line weights 0.25–1 pt; no hairlines.
- [ ] Vector PDF/EPS, fonts embedded; ≥1000 dpi if any raster; maps ≥300 dpi.
- [ ] Passes greyscale test and a colorblind simulator.

**Consistency across the paper**
- [ ] One palette, one font, one axis style, one panel-label convention reused in
      every figure. Category→color maps defined once in a shared module.

---

## 6. HOW TO USE THIS FILE WITH AN LLM ASSISTANT

- Keep this file at the repo root (`FIGURE_GUIDE.md`) and reference it in the
  task prompt: *"Follow FIGURE_GUIDE.md. Binding specs are §3.1 (TR-D). Use the
  palette and rcParams in §4."*
- When a figure decision is ambiguous, tell the assistant which section governs:
  perceptual/encoding questions → §1–2; measurable format → §3.
- Ask the assistant to end each figure task by running the §5 checklist and
  reporting any item it could not satisfy, rather than silently skipping it.
- The §4 palette blocks are the source of truth for category colors — the
  assistant should import them, never re-pick colors per figure.
```
