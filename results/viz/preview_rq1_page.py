"""Compose RQ1 at final size: A/B above C, without scaling PDF text."""
from io import BytesIO
import inspect
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.text import Text
from pypdf import PdfReader, PdfWriter, Transformation
import pypdfium2 as pdfium
import build_advisor_review_figures as b

b.apply_style()
b.SHOW_DATA_LABELS = False
mpl.rcParams.update({'font.size':10, 'axes.labelsize':10, 'axes.titlesize':10,
                    'xtick.labelsize':10, 'ytick.labelsize':10, 'legend.fontsize':10})
source = inspect.getsource(b.finish_labels_and_legends).replace('fig.set_size_inches(fig.get_size_inches() * 1.65)', 'pass')
exec(source, b.__dict__)
out = b.VIZ_DIR / 'paper_preview'
registry = b.load_registry().set_index('id')
mm = 72/25.4
writer = PdfWriter()
page = writer.add_blank_page(width=180*mm, height=275*mm)
for letter, row_id, x in [('A','s3_major_cost_panel_a_facility',0), ('B','s3_major_cost_panel_b_state',90)]:
    row = registry.loc[row_id].copy()
    row['id'] = row_id
    data, status = b.load_or_synthetic(row)
    fig = b.plot_generic(row, data, status)
    fig.set_size_inches(90/25.4, 135/25.4)
    ax = fig.axes[0]
    ax.set_xlabel('Direct infrastructure damage cost\n(billions of dollars, 2023)')
    ax.xaxis.set_major_locator(mpl.ticker.MaxNLocator(3))
    for text in fig.findobj(Text):
        text.set_fontsize(10)
    fig.subplots_adjust(left=.49, right=.96, bottom=.18, top=.94)
    fig.text(.025,.99,letter,ha='left',va='top',fontsize=12,fontweight='bold')
    b.finish_labels_and_legends(fig)
    # The legend belongs to its local panel, never to the whole sheet.
    buf=BytesIO()
    fig.savefig(buf,format='pdf')
    buf.seek(0)
    page.merge_transformed_page(PdfReader(buf).pages[0], Transformation().translate(x*mm,140*mm))
    plt.close(fig)
c=PdfReader(out/'RQ1c_paper_v3_unlabeled.pdf').pages[0]
assert abs(float(c.mediabox.width)-180*mm)<.1
page.merge_page(c)
path=out/'RQ1_compact_page.pdf'
writer.write(path)
doc=pdfium.PdfDocument(str(path))
doc[0].render(scale=1.7).to_pil().save(out/'RQ1_compact_page.png')
print(path)
