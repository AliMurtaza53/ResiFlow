# ResiFlow pipeline (technical overview)

Copy of the script-by-script explainer for offline review. Canonical copy: [`docs/PIPELINE_OVERVIEW.md`](../docs/PIPELINE_OVERVIEW.md).

ResiFlow is a **four-script transport resilience workflow**: baseline network assignment → hazard exposure & operational disruption → direct asset damage → disrupted rerouting under recovery scenarios. It reads a data bundle from `config.json` (`paths.soge_clusters`) and writes under `<parent>/results/<variant>/`.

See `docs/PIPELINE_OVERVIEW.md` for the full mermaid diagram, per-script tables, and command sequence.
