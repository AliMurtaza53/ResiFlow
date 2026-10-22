"""Prototype panels for the advisor sheets: RQ2 A+B merged, RQ3 A as an exposure ratio.

Each builder returns a finished 180 mm wide figure; build_advisor_package.py (--labeled-v2 --proto) aligns the
panel heading and places the figure on the sheet like any other panel.
"""
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch
import build_advisor_review_figures as b
from figlib import synthetic_model

SHORT = {'Agriculture, fishing, forestry':'Agriculture', 'Mining':'Mining',
         'Petroleum & coal products':'Petroleum & coal', 'Manufactured goods':'Manufactured',
         'Mixed freight & other':'Mixed freight'}
REROUTING_PARTS = {'Operating':'#7fb6da', 'Time':'#3a7ca5', 'Toll':'#d3e6f3'}


def _source(registry, row_id):
    row = registry.loc[row_id].copy()
    row['id'] = row_id
    return row


def rq3a_exposure(registry, height_mm, heading):
    """Exposure ratio = share of disrupted freight cost / share of baseline truck flow, per event and industry."""
    data, _ = b.load_or_synthetic(_source(registry, 'x_freight_commodity_delta'))
    industries = list(b.INDUSTRY_COLORS)
    cost = data.pivot_table(index='hazard', columns='industry', values='cost', aggfunc='sum').reindex(b.HAZARDS)[industries]
    disrupted = cost.div(cost.sum(axis=1), axis=0)
    baseline = (pd.read_csv(b.VIZ_DIR / 'rq3_baseline_mix_by_event.csv')
                .pivot(index='hazard', columns='industry', values='share_trips').reindex(b.HAZARDS)[industries])
    ratio = disrupted / baseline
    xmax = np.ceil((ratio.values.max() + .55) * 2) / 2
    fig, axes = plt.subplots(2, 2, sharex=True, figsize=(180 / 25.4, height_mm / 25.4))
    fig.subplots_adjust(left=.20, right=.98, top=.88, bottom=.17, wspace=.12, hspace=.55)
    for index, (ax, hazard) in enumerate(zip(axes.ravel(), b.HAZARDS)):
        for y, industry in enumerate(industries):
            value = ratio.loc[hazard, industry]
            ax.barh(y, value - 1, left=1, height=.64, color=b.INDUSTRY_COLORS[industry])
            ax.annotate(f'{value:.2f}×', (max(value, 1), y), xytext=(6, 0), textcoords='offset points',
                        va='center', fontsize=10, fontweight='bold', color='black')
        ax.axvline(1, color='black', linewidth=.8, zorder=3)
        ax.set_ylim(len(industries) - .52, -.48)
        ax.set_yticks(range(len(industries)), [SHORT[i] for i in industries] if index % 2 == 0 else [''] * len(industries))
        ax.set_xlim(0, xmax)
        ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(.5))
        ax.grid(axis='y', visible=False)
        ax.set_title(hazard, loc='left', fontsize=11, fontweight='bold', color='black', pad=6)
    fig.text(.5, .1, 'Exposure ratio (share of disrupted cost ÷ share of baseline freight flow; 1 = proportional)',
             ha='center', va='center', fontsize=11, gid='shared-x-label')
    fig.text(.025, .985, heading, ha='left', va='baseline', fontsize=12, fontweight='bold', gid='panel-label')
    b.finish_labels_and_legends(fig, scale=1, value_fontsize=8, relayout=False)
    return fig


def rq2_merged(registry, height_mm, heading):
    """Passenger and Freight bars side by side per event on one shared axis; stack = rerouting parts + isolation."""
    components = synthetic_model.mode_components().set_index(['hazard', 'flow'])
    colors = {'Operating': REROUTING_PARTS['Operating'], 'Time': REROUTING_PARTS['Time'], 'Isolation': b.COST_COLORS['Isolation']}
    rows = [(h, f) for h in b.HAZARDS for f in ('Passenger', 'Freight')]
    fig, ax = plt.subplots(figsize=(180 / 25.4, height_mm / 25.4))
    fig.subplots_adjust(left=.24, right=.97, top=.9, bottom=.2)
    for y, (hazard, flow) in enumerate(rows):
        left = 0
        for part, color in colors.items():
            value = components.loc[(hazard, flow), part]
            ax.barh(y, value, left=left, height=.64, color=color)
            left += value
        ax.annotate(f'${left:,.2f} Bn', (left, y), xytext=(9, 0), textcoords='offset points',
                    va='center', fontsize=10, fontweight='bold', color='black')
    ax.set_ylim(len(rows) - .52, -.48)
    ax.set_yticks(range(len(rows)), [f for _, f in rows])
    ax.set_xlim(0, 2.25)
    ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(.25))
    ax.xaxis.set_major_formatter(mpl.ticker.FormatStrFormatter('%.2f'))
    ax.grid(axis='y', visible=False)
    b.grouped_hazard_labels(ax, pd.Series([h for h, _ in rows]), x=-0.18, numbered=False)
    for text in ax.texts:
        if text.get_rotation() == 90:
            text.set_fontsize(10)
    fig.text(.5, .1, 'Cumulative 90-day rerouting and isolation cost (billions of dollars, 2023)', ha='center', va='center',
             fontsize=11, gid='shared-x-label')
    fig.legend(handles=[Patch(color=c, label=k) for k, c in colors.items()], ncol=3, loc='lower center', frameon=False)
    fig.text(.025, .985, heading, ha='left', va='baseline', fontsize=12, fontweight='bold', gid='panel-label')
    b.finish_labels_and_legends(fig, scale=1, value_fontsize=8, relayout=False)
    return fig


BUILDERS = {'RQ2a': rq2_merged, 'RQ3a': rq3a_exposure}


def rq3a_dual(registry, height_mm, heading):
    """RQ3 A as 1 x 2: disrupted freight tonnage (left) and value (right) per event, stacked by industry.

    Tons are synthetic (national FAF5 ton mix with noise); value = tons x FAF5 2022 truck $/ton (real factors, 2017$).
    """
    industries = list(b.INDUSTRY_COLORS)
    tons, value = synthetic_model.freight_tons_value()
    tons, value = tons.reindex(b.HAZARDS)[industries], value.reindex(b.HAZARDS)[industries]
    fig, axes = plt.subplots(1, 2, sharey=True, figsize=(180 / 25.4, height_mm / 25.4))
    fig.subplots_adjust(left=.19, right=.98, top=.9, bottom=.27, wspace=.08)
    heads = heading.split('|') if heading else ['(A) Disrupted Freight Tonnage', '(B) Disrupted Freight Value']
    panels = [(tons, heads[0], 'Tonnage (million tons)', '{:,.1f} Mt'),
              (value, heads[1], 'Cargo value (billions of dollars, 2023)', '${:,.1f} Bn')]
    for ax, (frame, title, xlabel, fmt) in zip(axes, panels):
        left = np.zeros(len(frame))
        for industry in industries:
            ax.barh(range(len(frame)), frame[industry], left=left, height=.64, color=b.INDUSTRY_COLORS[industry])
            left += frame[industry].to_numpy()
        for y, t in enumerate(left):
            ax.annotate(fmt.format(t), (t, y), xytext=(6, 0), textcoords='offset points', va='center',
                        fontsize=10, fontweight='bold', color='black')
        ax.set_ylim(len(frame) - .52, -.48)
        ax.set_yticks(range(len(frame)), [b.HAZARD_LABELS[h] for h in frame.index])
        ax.set_xlim(0, left.max() * 1.32)
        ax.xaxis.set_major_locator(mpl.ticker.MaxNLocator(5))
        ax.grid(axis='y', visible=False)
        ax.set_xlabel(xlabel, fontsize=11)
        ax.set_title(title, loc='left', fontsize=12, fontweight='bold', color='black', pad=8)
    axes[1].tick_params(axis='y', length=0)
    b.finish_labels_and_legends(fig, scale=1, value_fontsize=8, relayout=False)
    # Title alignment as elsewhere: first title flush with the sheet's left margin (like panel letter C),
    # second shifted left by the width of '(' so its letter sits over the y-axis (like RQ1_2 C/E).
    fig.canvas.draw()
    pos = axes[0].get_position()
    axes[0].set_title(axes[0].get_title(loc='left'), loc='left', fontsize=12, fontweight='bold', color='black', pad=8, x=(.025 - pos.x0) / pos.width)
    pos = axes[1].get_position()
    axes[1].set_title(axes[1].get_title(loc='left'), loc='left', fontsize=12, fontweight='bold', color='black', pad=8, x=-4 / (pos.width * fig.get_size_inches()[0] * 72))
    return fig


BUILDERS['RQ3a'] = rq3a_dual
