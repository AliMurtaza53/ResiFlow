"""Preview white text halos on existing external component labels."""
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.text import Text
import build_advisor_review_figures as b
b.apply_style()
b.SHOW_DATA_LABELS=True
row=b.load_registry().set_index('id').loc['x_top5_states_industry'].copy()
row['id']='x_top5_states_industry'
data,status=b.load_or_synthetic(row)
data=data[data['hazard'].eq('New Madrid Earthquake')].copy()
fig=b.plot_generic(row,data,status)
fig.set_size_inches(180/25.4,85/25.4)
for t in fig.findobj(Text):
    t.set_fontsize(10)
fig.subplots_adjust(left=.24,right=.97,top=.95,bottom=.17)
b.finish_labels_and_legends(fig,scale=1,value_fontsize=8,relayout=False)
# Crop to the crowded second hazard group for a readable before/after sample.
ax=fig.axes[0]
ax.set_ylim(4.5,-.8)
for legend in list(fig.legends):
    legend.remove()
fig.set_size_inches(180/25.4,85/25.4)
fig.subplots_adjust(top=.93,bottom=.20)
out=b.VIZ_DIR/'paper_preview'
fig.savefig(out/'label_boxes_sample.pdf')
count=0
for t in ax.texts:
    if t.get_bbox_patch() is not None:
        t.set_bbox(None)
        t.set_path_effects([pe.withStroke(linewidth=1.5,foreground='white'),pe.Normal()])
        count+=1
fig.savefig(out/'label_halo_sample.pdf')
fig.savefig(out/'label_halo_sample.png',dpi=180)
plt.close(fig)
print('Previewed halo treatment on',count,'labels; production figures unchanged.')
