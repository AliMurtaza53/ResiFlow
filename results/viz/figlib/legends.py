"""Legends with a bold explainer entry in the same row (two-row legends: explainer centered in its own column).

The explainer text and the label it is matched on come from visual_registry.csv (legend_match / legend_title);
LEGEND_TITLES holds defaults and is replaced by configure_legend_titles().
"""
LEGEND_TITLES = [('Minor', 'Direct damage severity'), ('Operating', 'Indirect damage cost type'),
                 ('Direct', 'Cost type'), ('Rerouting', 'Non-damage cost type'),
                 ('Agriculture', 'Freight commodity group')]

def title_legends(fig):
    """Rebuild each legend with a bold explainer entry first, in the same row (RQ3: first column)."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    legends = [(l, False) for l in fig.legends] + [(ax.get_legend(), True) for ax in fig.axes if ax.get_legend()]
    for legend, from_axes in legends:
        texts = [t.get_text() for t in legend.get_texts()]
        title = next((t for first, t in LEGEND_TITLES if any(x.startswith(first) for x in texts)), None)
        if title is None or texts[0].endswith(':'):
            continue
        anchor = legend.get_bbox_to_anchor().transformed(fig.transFigure.inverted())
        handles = [Patch(facecolor=h.get_facecolor(), edgecolor='none', label=t)
                   for h, t in zip(legend.legend_handles, texts)]
        legend.remove()
        blank = lambda: Line2D([], [], linestyle='none', label=' ')
        if len(handles) > 4:  # five-entry legend: explainer column, then two rows of entries
            words = (title + ':').split()  # wrap the explainer over the two legend rows, as evenly as possible
            cut = min(range(1, len(words)), key=lambda i: max(len(' '.join(words[:i])), len(' '.join(words[i:]))))
            lines = [' '.join(words[:cut]) + ' ', ' '.join(words[cut:])]
            ghost = lambda text: Line2D([], [], linestyle='none', label=text)  # reserves the column; real title drawn centered
            entries = [ghost(lines[0]), ghost(lines[1])] + handles + [blank()] * ((-len(handles)) % 2)
            ncol = 1 + (len(handles) + 1) // 2
        else:
            entries, ncol = [Line2D([], [], linestyle='none', label=title + ':')] + handles, len(handles) + 1
        new = fig.legend(handles=entries, ncol=ncol, loc='upper center', frameon=False, borderaxespad=0,
                         handlelength=1.2, handletextpad=.4, columnspacing=.4, bbox_to_anchor=(anchor.x0, anchor.y0), bbox_transform=fig.transFigure)
        new.get_texts()[0].set_fontweight('bold')
        if len(handles) > 4:
            for t in new.get_texts()[:2]:
                t.set_alpha(0)
                t.set_gid('legend-title-ghost')


EXPLAINER_ALIGN = 'right'  # 'right' (final), 'left' or 'center'


def center_legend_titles(fig):
    """Draw the explainer of two-row legends vertically centered on the legend rows."""
    ghosts = [t for lg in fig.legends for t in lg.get_texts() if t.get_gid() == 'legend-title-ghost']
    if len(ghosts) < 2:
        return
    for t in [t for t in fig.texts if t.get_gid() == 'legend-title-real']:
        t.remove()
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    top, bottom = (g.get_window_extent(renderer) for g in ghosts[:2])
    left, right = min(top.x0, bottom.x0), max(top.x1, bottom.x1)
    x = fig.transFigure.inverted().transform(({'left': left, 'center': (left + right) / 2, 'right': right}[EXPLAINER_ALIGN], 0))[0]
    y = fig.transFigure.inverted().transform((0, (top.y0 + top.y1 + bottom.y0 + bottom.y1) / 4))[1]
    fig.text(x, y, ghosts[0].get_text() + '\n' + ghosts[1].get_text(), ha=EXPLAINER_ALIGN, va='center', multialignment=EXPLAINER_ALIGN,
             fontsize=10, fontweight='bold', linespacing=1.15, gid='legend-title-real')


def configure_legend_titles(pairs):
    """pairs: iterable of (first legend label, explainer). Registry-defined pairs take precedence over defaults."""
    global LEGEND_TITLES
    pairs = [p for p in pairs if p[0] and p[1]]
    LEGEND_TITLES = pairs + [d for d in LEGEND_TITLES if d[0] not in {p[0] for p in pairs}]
