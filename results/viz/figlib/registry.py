"""Read the paper_* and legend_* columns of results/viz/visual_registry.csv (the single source for the paper set)."""
from pathlib import Path
import pandas as pd

REGISTRY = Path(__file__).resolve().parent.parent / 'visual_registry.csv'


def load(path=REGISTRY):
    return pd.read_csv(path, encoding='latin1', dtype=str, keep_default_na=False)


def paper_rows(build=None, path=REGISTRY):
    """Rows that belong to the paper, ordered by figure and panel order. build: 'standard' | 'proto' | None (all)."""
    r = load(path)
    r = r[r.paper_figure != '']
    if build:
        r = r[r.paper_build == build]
    return r.assign(_o=pd.to_numeric(r.paper_order)).sort_values(['paper_figure', '_o']).drop(columns='_o')


def letters(panel):
    """'A' -> ['A']; 'B-E' -> ['B','C','D','E']."""
    if '-' in panel:
        first, last = panel.split('-')
        return [chr(c) for c in range(ord(first), ord(last) + 1)]
    return [panel] if panel else []


def titles(row):
    """Lettered panel titles of a row: ['(B) Total Cost', ...]; empty if the row has no title."""
    parts = [t.strip() for t in row['paper_title'].split('|')] if row['paper_title'] else []
    return [f'({l}) {t}' for l, t in zip(letters(row['paper_panel']), parts)]


def by_key(build):
    """paper_key -> registry row (dict) for one build mode."""
    return {r['paper_key']: r for r in paper_rows(build).to_dict('records')}


def legend_pairs(path=REGISTRY):
    r = paper_rows(path=path)
    return list(zip(r.legend_match, r.legend_title))
