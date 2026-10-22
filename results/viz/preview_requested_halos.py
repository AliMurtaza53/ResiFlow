"""Halo previews using the exact current advisor-package layouts."""
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import build_advisor_package as package

out=package.OUT.parent/'paper_preview'
original_save=plt.Figure.savefig
wanted={'RQ1a','RQ3b'}
class PreviewsComplete(Exception):
    pass

def preview_save(fig, destination, *args, **kwargs):
    if not isinstance(destination, Path):
        return
    key=destination.stem.split('_')[0]
    if destination.parent.name!='labeled' or key not in wanted:
        return
    for ax in fig.axes:
        for text in ax.texts:
            if text.get_bbox_patch() is not None:
                text.set_bbox(None)
                text.set_path_effects([pe.withStroke(linewidth=1.5,foreground='white'),pe.Normal()])
    original_save(fig,out/(key+'_halo_preview.pdf'))
    original_save(fig,out/(key+'_halo_preview.png'),dpi=150)
    wanted.remove(key)
    if not wanted:
        raise PreviewsComplete

# Skip composition: only export the two requested standalone samples.
package.PAGES={}
plt.Figure.savefig=preview_save
try:
    package.build()
except PreviewsComplete:
    print('Created RQ1A and RQ3B halo previews; advisor package unchanged.')
finally:
    plt.Figure.savefig=original_save
    plt.close('all')
