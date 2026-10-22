# Paper figure pipeline (modular, registry-driven)

Everything for the paper set traces to one file: `visual_registry.csv`. Rows with `paper_figure` set are in the paper.

| Layer | Where | Change it to... |
|---|---|---|
| Definition | `visual_registry.csv` columns `paper_figure, paper_order, paper_key, paper_build, paper_panel, paper_title, paper_template, paper_height_mm, legend_match, legend_title` (+ `axis_dollar_year`, `dollar_year_by_component`, `status`, `caption`, `caveats`) | add/remove/retitle/reletter a panel, change a height or a legend explainer |
| Elements (shared) | `figlib/legends.py` (explainer legends), `figlib/layout.py` (panel letters, measuring, crop, stacking, halved gaps), `figlib/registry.py` | change a rule everywhere |
| Templates (plot types) | `figlib/templates.py` lists them; code in `build_advisor_review_figures.py` (event/state plots) and `proto_figures.py` (merged RQ2, RQ3 tonnage/value) | change one chart type |
| Data | placeholders in `build_advisor_review_figures.synthetic_data`; real: `rq3_real_data.py`, `hopper_pull_*/`, `compute_rq3_baseline_mix.py` | swap synthetic for model output |
| Orchestration | `build_advisor_package.py` (panels + sheets), `build_paper_final.py` (reads registry, builds, copies to `advisor_package/final`, writes `MANIFEST.csv`) | rarely |
| Style guide | `~/.claude/skills/multipanel-figures/SKILL.md` | house rules (fonts, labels, palette, legends) |

## Common tasks
- **Rebuild the set:** `python build_paper_final.py` (add `--no-build` to only re-copy). Output: `advisor_package/final/{RQ1_1,RQ1_2,RQ2,RQ3}.{pdf,png}` + `MANIFEST.csv`.
- **Retitle / reletter a panel or change a legend explainer:** edit the registry row (`paper_title` uses ` | ` between panels; `paper_panel` like `A`, `B-E`).
- **Add a new plot to an existing figure:** add the template function, register it in `figlib/templates.py`, add a registry row with the same `paper_figure`, next `paper_order`, a `paper_key`, `paper_build`.
- **Add a background figure/map:** new template (e.g. `map_footprint`), new registry row with `paper_figure` (e.g. `BG1`), `paper_build` = a build mode that makes it. Figures of one `paper_figure` must come from one build.
- **Swap synthetic for real results:** replace the data loader behind the template; update `status` in the registry; `MANIFEST.csv` shows the status shipped with each figure.

## Known limitations of this structure
- `paper_key` names (RQ1a, RQ2a ...) are historical; the build script still has per-key branches (axis caps, tick steps, label formats) that should migrate into template functions over time.
- The two builds (`standard`, `proto`) are separate runs; `build_paper_final.py` runs the ones the registry needs.
- Dollar-year harmonization is documented in the registry, not yet enforced in code.
