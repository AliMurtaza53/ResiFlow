"""Reusable figure library for the ResiFlow paper figures.

Layers (each can be changed without touching the others):
  visual_registry.csv   what each paper figure/panel is: letter, title, template, height, legend explainer
  figlib.registry       reads the paper_* / legend_* columns
  figlib.templates      plot-type builders (one per chart template, named in registry paper_template)
  figlib.legends        legend explainer entry, shared by every template
  figlib.layout         panel-letter alignment, measuring, cropping, stacking panels into a sheet
  build_advisor_package / build_paper_final.py   orchestration: build panels, compose sheets, write the final set
Style rules live in the multipanel-figures skill (~/.claude/skills/multipanel-figures/SKILL.md).
"""
