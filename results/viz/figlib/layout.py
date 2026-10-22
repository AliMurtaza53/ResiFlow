"""Sheet layout helpers: panel-letter alignment, content measuring, cropping, stacking panels onto a sheet."""
from io import BytesIO
import pypdfium2 as pdfium
from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject

MM = 72 / 25.4
GAP_FACTOR = 2  # between-panel white space is divided by this (halved)
PANEL_WIDTH_MM = 180
PAGE_WIDTH_MM = 215.9


def align_panel_label(fig, extra=0):
    """Parent letter baseline meets first-row title top, or clears axes by 4 pt."""
    labels=[t for t in fig.texts if t.get_gid()=='panel-label']
    if not labels:
        return
    def target():
        fig.canvas.draw()
        renderer=fig.canvas.get_renderer()
        titles=[ax._left_title for ax in fig.axes if ax.get_title(loc='left')]
        return (max(t.get_window_extent(renderer).y1 for t in titles) if titles else
                max(ax.bbox.y1 for ax in fig.axes)+4*fig.dpi/72)+extra*fig.dpi/72
    baseline=target()
    ceiling=fig.bbox.height-17*fig.dpi/72
    if baseline>ceiling:
        fig.subplots_adjust(top=fig.subplotpars.top-(baseline-ceiling)/fig.bbox.height)
        baseline=target()
    labels[0].set_verticalalignment('baseline')
    labels[0].set_y(baseline/fig.bbox.height)


def ink_margins(pdf_bytes):
    """White space (mm) above and below the drawn content of a one-page panel PDF."""
    scale = 100 / 72
    doc = pdfium.PdfDocument(pdf_bytes)
    image = doc[0].render(scale=scale).to_pil().convert('RGB')
    doc.close()
    ink = ImageChops.difference(image, Image.new('RGB', image.size, (255, 255, 255))).convert('L').point(lambda v: 255 if v > 10 else 0)
    _, top, _, bottom = ink.getbbox()
    mm_per_px = 25.4 / 100
    return top * mm_per_px, (image.size[1] - bottom) * mm_per_px


def crop_to_content(path, pad_pt=2.9):
    """Shrink a sheet's page box to its drawn content (plus a small pad): no white border, same scale."""
    scale=300/72
    doc=pdfium.PdfDocument(str(path))
    image=doc[0].render(scale=scale).to_pil().convert('RGB')
    doc.close()
    ink=ImageChops.difference(image,Image.new('RGB',image.size,(255,255,255))).convert('L').point(lambda v:255 if v>10 else 0)
    left,top,right,bottom=ink.getbbox()
    page=PdfReader(BytesIO(path.read_bytes())).pages[0]
    width,height=float(page.mediabox.width),float(page.mediabox.height)
    box=RectangleObject([max(left/scale-pad_pt,0),max(height-bottom/scale-pad_pt,0),
                         min(right/scale+pad_pt,width),min(height-top/scale+pad_pt,height)])
    page.mediabox=box
    page.cropbox=box
    writer=PdfWriter()
    writer.add_page(page)
    cropped=path.with_suffix('.crop.pdf')
    writer.write(cropped)
    cropped.replace(path)



def stack_panels(writer, group, heights, panel_bytes, tight=True, gap_factor=GAP_FACTOR):
    """Place one-page panel PDFs top to bottom on a new page; white space between panels is measured and divided."""
    margins = {k: ink_margins(panel_bytes(k)) for k in group} if tight else {k: (0, 0) for k in group}
    content = {k: heights[k] - sum(margins[k]) for k in group}
    gaps = [(margins[a][1] + margins[b][0]) / gap_factor for a, b in zip(group, group[1:])] if tight else [0] * (len(group) - 1)
    total = sum(content.values()) + sum(gaps)
    page_h = max(279.4, total + 8)
    page = writer.add_blank_page(width=612, height=page_h * MM)
    cursor = (page_h + total) / 2
    for n, key in enumerate(group):
        y = cursor - heights[key] + margins[key][0]
        source = PdfReader(BytesIO(panel_bytes(key))).pages[0]
        assert abs(float(source.mediabox.width) - PANEL_WIDTH_MM * MM) < .1
        page.merge_transformed_page(source, Transformation().translate((PAGE_WIDTH_MM - PANEL_WIDTH_MM) / 2 * MM, y * MM))
        cursor -= content[key] + (gaps[n] if n < len(gaps) else 0)
