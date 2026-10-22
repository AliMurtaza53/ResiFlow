"""Isolated paper-size preview; reuse existing data and plotting functions."""
import inspect
from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.text import Text
import build_advisor_review_figures as b

out = b.VIZ_DIR / 'paper_preview'
out.mkdir(exist_ok=True)
b.apply_style()
mpl.rcParams.update({'font.size':10, 'axes.labelsize':10, 'axes.titlesize':10, 'xtick.labelsize':10, 'ytick.labelsize':10, 'legend.fontsize':10})
# Preview only: keep the existing label-placement algorithm, without enlargement.
source = inspect.getsource(b.finish_labels_and_legends)
source = source.replace('fig.set_size_inches(fig.get_size_inches() * 1.65)', 'pass')
source = source.replace('if fig.get_label() == "rq1c":', 'if False:')
source = source.replace('fontsize=12', 'fontsize=8')
exec(source, b.__dict__)
row = b.load_registry().set_index('id').loc['x_ranked_states_4metric'].copy()
row['id'] = 'x_ranked_states_4metric'
data, status = b.load_or_synthetic(row)
for layout in ('compact', 'stacked'):
  for labeled in (True, False):
    b.SHOW_DATA_LABELS = labeled
    fig = b.plot_ranked_state_metrics(row, data, status)
    height = 140 if layout == 'compact' else 245
    fig.set_size_inches(180/25.4, height/25.4)
    titles = ['(i) Total cost', '(ii) Cost per lane-mile of roadways', '(iii) Cost relative to annual freight value', '(iv) Cost per capita']
    for index, (ax, title) in enumerate(zip(fig.axes, titles)):
        ax.set_title(title, loc='left', fontsize=10, fontweight='bold', pad=7)
        ax.xaxis.set_major_locator(mpl.ticker.MaxNLocator(4))
        ax.set_xlim(0, ax.get_xlim()[1] * 1.18)
        ax.set_ylim(3.6, -1.05)
        for container in ax.containers:
            if isinstance(container, mpl.container.BarContainer):
                for bar in container:
                    center = bar.get_y() + bar.get_height()/2
                    bar.set_height(.64)
                    bar.set_y(center - .32)
        if layout == 'stacked':
            ax.set_position([.16, .77-index*.225, .80, .165])
            ax.tick_params(axis='y', labelleft=True)
    fig.axes[2].set_xlabel('Costs / annual outbound freight value (%)')
    for text in fig.findobj(Text):
        text.set_fontsize(10)
    if layout == 'compact':
        fig.subplots_adjust(left=.16, right=.98, top=.87, bottom=.16, wspace=.18, hspace=.64)
    fig.text(.025, .985, 'C', fontsize=12, fontweight='bold', ha='left', va='top')
    b.finish_labels_and_legends(fig)
    name = 'RQ1c_paper_v3_' + ('' if layout == 'compact' else 'stacked_') + ('labeled' if labeled else 'unlabeled')
    fig.savefig(out / (name+'.pdf'))
    fig.savefig(out / (name+'.png'), dpi=180)
    plt.close(fig)
print('Created compact and stacked previews, each with and without labels:', status)


