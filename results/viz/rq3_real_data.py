"""RQ3 A from real model output: aggregate freight disruption cost per event, split by industry.

Inputs per scenario (pulled from Hopper into hopper_pull_<date>/): cost_matrix_by_scenario.csv (Script 4) and
freight_industry_mix.json (compute_freight_industry_mix.py). Cost = freight rerouting + isolation at a chosen
event day; industries get their share of the disrupted OD flow (Car21 by sctgG5). Direct infrastructure damage
is excluded: it cannot be attributed to a commodity. The split is an allocation by flow share, not a
commodity-specific cost (VOT is one value for all trucks).
"""
import json
import sys
from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
import build_advisor_review_figures as b

PULL = b.VIZ_DIR / 'hopper_pull_2026-10-22'
SCTG = {'sctg0109':'Agriculture, fishing, forestry', 'sctg1014':'Mining', 'sctg1519':'Petroleum & coal products',
        'sctg2033':'Manufactured goods', 'sctg3499':'Mixed freight & other'}
EVENTS = {301:'Virginia flood\n(scenario 301)', 401:'Mineral earthquake\n(401)',
          501:'Mineral landslide\n(501)', 601:'Winter Storm Jonas\n(601)'}


def load_real_rq3a(pull=PULL, event_day=0):
    rows = []
    for scenario, label in EVENTS.items():
        matrix = pull / f'{scenario}_cost_matrix_by_scenario.csv'
        mix = json.loads((pull / f'{scenario}_freight_industry_mix.json').read_text())
        if matrix.stat().st_size == 0 or not mix['shares']:
            cost = 0.0  # nothing disrupted in this run
            shares = {code: 0.0 for code in SCTG}
        else:
            day = pd.read_csv(matrix).set_index('event_day').loc[event_day]
            cost = float(day['rerouting_cost'] + day['isolation_cost'])
            shares = mix['shares']
        for code, industry in SCTG.items():
            rows.append(dict(scenario=scenario, event=label, industry=industry, cost_usd=cost * shares.get(code, 0.0)))
    return pd.DataFrame(rows)


def plot_preview(data, out_stem):
    mpl.rcParams.update({'font.size':10, 'axes.labelsize':11, 'xtick.labelsize':10, 'ytick.labelsize':10, 'legend.fontsize':10})
    pivot = data.pivot_table(index='event', columns='industry', values='cost_usd', aggfunc='sum') / 1e6
    pivot = pivot.reindex([EVENTS[s] for s in EVENTS])[list(b.INDUSTRY_COLORS)]
    fig, ax = plt.subplots(figsize=(180 / 25.4, 78 / 25.4))
    fig.subplots_adjust(left=.20, right=.97, top=.86, bottom=.36)
    left = pd.Series(0.0, index=pivot.index)
    for industry, color in b.INDUSTRY_COLORS.items():
        ax.barh(range(len(pivot)), pivot[industry], left=left, height=.64, color=color, label=industry)
        left += pivot[industry]
    for y, total in enumerate(left):
        text = ('no disruption' if not total else f'${total:,.1f} M' if total >= .1 else f'${total * 1000:,.1f} K')
        ax.annotate(text, (total, y), xytext=(9, 0), textcoords='offset points', va='center',
                    fontsize=10, fontweight='bold', color='black')
    ax.set_yticks(range(len(pivot)), pivot.index)
    ax.set_ylim(len(pivot) - .52, -.48)
    ax.set_xlim(0, 140)
    ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(20))
    ax.grid(axis='y', visible=False)
    ax.set_xlabel('Freight rerouting and isolation cost, day 0 (millions of dollars)', fontsize=11)
    fig.text(.025, .975, '(A) Total Disrupted Freight Cost by Event and Industry (real Hopper results, preview)',
             ha='left', va='baseline', fontsize=12, fontweight='bold')
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, ncol=2, loc='lower center', frameon=False, borderaxespad=.3)
    for suffix, kw in (('.pdf', dict(bbox_inches='tight', pad_inches=.04)), ('.png', dict(dpi=300, bbox_inches='tight', pad_inches=.04))):
        fig.savefig(str(out_stem) + suffix, **kw)
    plt.close(fig)


if __name__ == '__main__':
    b.apply_style()
    data = load_real_rq3a()
    print(data.groupby('event').cost_usd.sum().round(0))
    out = b.VIZ_DIR / 'advisor_package' / 'prototypes'
    out.mkdir(parents=True, exist_ok=True)
    plot_preview(data, out / 'RQ3A_real_preview')
    print(out / 'RQ3A_real_preview.png')
