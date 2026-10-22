"""Consistent individual figures and unscaled, vector advisor combinations."""
from io import BytesIO
import sys
import json
import re
import shutil
import zipfile
from pathlib import Path
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.text import Text
from pypdf import PdfReader, PdfWriter, Transformation
import pypdfium2 as pdfium
import build_advisor_review_figures as b
import proto_figures
from figlib import registry as reg
from figlib.layout import MM, align_panel_label, crop_to_content, stack_panels
from figlib.legends import title_legends, center_legend_titles, configure_legend_titles

OUT = b.VIZ_DIR / 'advisor_package'
V2 = '--v2' in sys.argv
V3 = '--labeled-v2' in sys.argv  # numbering revision: lettered plot titles, no event numerals
PROTO = '--proto' in sys.argv  # with --labeled-v2: RQ2 A+B merged and RQ3 A as an exposure ratio
V3_DIR = 'prototypes' if PROTO else 'labeled_v3'  # colorblind-checked palette set; labeled_v2 keeps the earlier colors
V3_TITLES = {'RQ1b':'(A) Direct Costs by Top States',
             'RQ2a':'(A) Rerouting Cost Components', 'RQ2b':'(B) Rerouting and Isolation Costs',
             'RQ2c':'(C) Total Cost by Top States',
             'RQ3a':'(A) Total Disrupted Freight Cost by Event and Industry',
             'RQ3b':'(B) Disrupted Freight Cost by Industry in Top States'}
if PROTO:
    V3_TITLES.update(RQ2a='(A) Rerouting and Isolation Costs by Travel Mode', RQ2c='(B) Total Cost by Top States',
                     RQ3a='', RQ3b='(C) Disrupted Freight Cost by Industry in Top States')
RQ1C_TITLES = ['(B) Total Cost', '(C) Cost per Lane-mile of Roadways',
               '(D) Cost Relative to Annual Freight Value', '(E) Cost per Capita']
# Paper panels: letters, titles, heights and legend explainers come from visual_registry.csv (figlib.registry).
REG_HEIGHTS = {}
configure_legend_titles(reg.legend_pairs())
# RQ2 B prototypes: --rq2b=bottom|all letters each event panel (B)-(E); 'all' also gives the top row its own x-axis label
RQ2B = next((a.split('=')[1] for a in sys.argv if a.startswith('--rq2b=')), '')
if '--legend-right' in sys.argv:
    import figlib.legends as _legends
    _legends.EXPLAINER_ALIGN = 'right'
if V3:
    for _key, _row in reg.by_key('proto' if PROTO else 'standard').items():
        _titles = reg.titles(_row)
        if _row['paper_height_mm']:
            REG_HEIGHTS[_key] = float(_row['paper_height_mm'])
        if _key == 'RQ1c' and _titles:
            RQ1C_TITLES = _titles
        elif _titles:
            V3_TITLES[_key] = '|'.join(_titles)
    if RQ2B == 'all':  # taller sheet panel: the top row needs room for tick labels and its own x-axis label
        REG_HEIGHTS['RQ2c'] = 150
V2_CAP = {'RQ1b':4.5, 'RQ3b':9}
V2_STRETCH = .035
SUFFIX = '_v2' if V2 else ''
HEIGHTS = {'RQ1a':180, 'RQ1b':100, 'RQ1c':130,
           'RQ2a':70, 'RQ2b':75, 'RQ2c':110, 'RQ3a':85, 'RQ3b':170}
if V3:
    HEIGHTS.update(RQ2a=79, RQ2c=126, RQ1c=140)  # room for titled legends
    HEIGHTS['RQ1b']=112  # taller rows so the larger, unnumbered event names fit their boxes
    HEIGHTS.update(REG_HEIGHTS)  # registry paper_height_mm wins
PAGES = {'RQ1':[['RQ1a'], ['RQ1b','RQ1c']],
         'RQ2':[['RQ2a','RQ2b','RQ2c']], 'RQ3':[['RQ3a','RQ3b']]}

def build():
    b.apply_style()
    mpl.rcParams.update({'font.size':10, 'axes.labelsize':11, 'axes.titlesize':10,
                         'xtick.labelsize':10, 'ytick.labelsize':10, 'legend.fontsize':10})
    registry = b.load_registry().set_index('id')
    records=[]
    variants = (True,) if '--labeled-only' in sys.argv else (False, True)
    passes = [(True, True)] if PROTO else [(True, False), (True, True)] if V3 else [(v, False) for v in variants]
    for labeled, titled in passes:
        suffix = ('_wlabel' if titled else '_nolabel') if V3 else SUFFIX
        b.NUMBER_GROUPS = not V3
        b.COMPOSITION_MAGNITUDE = V3
        b.SHOW_DATA_LABELS=False
        folder=OUT / (V3_DIR if V3 else 'labeled' if labeled else 'unlabeled')
        parts=folder/'_parts' if V3 else folder
        parts.mkdir(parents=True, exist_ok=True)
        files={}
        combined_files={}
        combined_heights=dict(HEIGHTS, RQ3a=56, RQ3b=197)
        combined_heights.update(REG_HEIGHTS)
        for row_id, name in b.OUTPUT_NAMES.items():
            key=name.split('_')[0]
            if V3 and key in (('RQ1a',) if titled else ('RQ1b','RQ1c')):
                continue  # RQ1_1 is built once; RQ1_2 only exists lettered
            if PROTO and key in ('RQ1a','RQ1b','RQ1c','RQ2b'):
                continue  # the prototype sheets only change RQ2 (A+B merged) and RQ3 A
            if PROTO and key in proto_figures.BUILDERS:
                fig=proto_figures.BUILDERS[key](registry,combined_heights[key],V3_TITLES[key])
                title_legends(fig)
                align_panel_label(fig,4)
                path=parts/(name+suffix+'.pdf')
                fig.savefig(path)
                buffer=BytesIO()
                center_legend_titles(fig)
                fig.savefig(buffer,format='pdf')
                buffer.seek(0)
                combined_files[key]=buffer
                plt.close(fig)
                files[key]=path
                continue
            row=registry.loc[row_id].copy()
            row['id']=row_id
            data,status=b.load_or_synthetic(row)
            if V3 and key=='RQ2b':
                data=data.assign(cost=data.cost/1000)  # billions, like the other cost figures
            if key=='RQ2a':
                source=registry.loc['s4_freight_passenger_rerouting_isolation'].copy()
                source['id']='s4_freight_passenger_rerouting_isolation'
                data,status=b.load_or_synthetic(source)
                rerouting=data[data.component.eq('Rerouting')].copy()
                rng=b.stable_rng('rq2a_flow_components')
                rows=[]
                for _, record in rerouting.iterrows():
                    shares=rng.dirichlet([3,5,1])
                    for component, share in zip(('Operating','Time','Toll'),shares):
                        rows.append(dict(hazard=record.hazard,flow=record.flow,component=component,cost=record.cost*share))
                components=b.pd.DataFrame(rows)
                expected=rerouting.groupby(['hazard','flow']).cost.sum()
                actual=components.groupby(['hazard','flow']).cost.sum()
                b.np.testing.assert_allclose(actual.reindex(expected.index),expected)
                if V3:
                    components['cost']=components.cost/1000  # billions
                status += '; Operating/Time/Toll shares are synthetic, preserving rerouting totals'
                fig=b.plot_s4_freight_passenger(row,components,status,components=('Operating','Time','Toll'))
            else:
                fig=b.plot_generic(row,data,status)
            b.SHOW_DATA_LABELS = key=='RQ3a' and not V3  # magnitudes: segments too small for every label to fit, so none
            fig.set_size_inches(180/25.4,HEIGHTS[key]/25.4)
            for text in fig.findobj(Text):
                text.set_fontsize((11 if V3 else 8.5) if key=='RQ1b' and text.get_rotation()==90 else 10)
            for index, ax in enumerate(fig.axes):
                for text in ax.texts:
                    if text.get_color() != '#777777':
                        continue
                    value=float(text.get_text().replace(',', ''))
                    if key=='RQ3a' and not V3:
                        label=f'{value:g}%'
                    elif key=='RQ1c' and index>0:
                        label=(f'${value:,.0f}/lane-mi' if index==1 else
                               f'{value:g}%' if index==2 else f'${value:,.0f}/person')
                    else:
                        unit='Mn' if key in ('RQ2a','RQ2b') and not V3 else 'Bn'
                        label=f'${value:,.0f} {unit}' if unit=='Mn' else f'${value:,.2f} {unit}'
                    text.set_text(label)
                    text.set_color('black')
                    text.set_fontweight('bold')
                    text.set_fontsize(10)
            original_limits = {ax: ax.get_xlim() for ax in fig.axes}
            for ax in fig.axes:
                ax.xaxis.set_major_locator(mpl.ticker.MaxNLocator(6))
                ax.set_xlim(0, 4.0 if key == 'RQ1a' else original_limits[ax][1]*1.12)
                if key == 'RQ1a':
                    ax.set_xticks(np.arange(0, 4.01, 0.5))
                # Totals-only bars need only a small gap above the first row.
                lo,hi=ax.get_ylim()
                if lo>hi:
                    lower_gap = -.48 if key == 'RQ3b' else -.48
                    ax.set_ylim(len(ax.get_yticks())-.52 if key in ('RQ1a','RQ3b') else lo, lower_gap)
                for container in ax.containers:
                    if isinstance(container,mpl.container.BarContainer):
                        for bar in container:
                            center=bar.get_y()+bar.get_height()/2
                            bar.set_height(.64)
                            bar.set_y(center-.32)
            if key in ('RQ1a','RQ1b','RQ3b'):
                fig.subplots_adjust(left=.19 if key=='RQ1a' else .24,right=.97,top=.96 if key=='RQ1b' else .94,bottom=.20 if key=='RQ3b' else .13)
            elif key=='RQ1c':
                fig.subplots_adjust(left=.16,right=.98,top=.925 if V3 else .94,bottom=.215 if V3 else .16,wspace=.18,hspace=.5 if V3 else .44)
            elif key=='RQ2c':
                fig.subplots_adjust(left=.145,right=.98,top=.92,bottom=.235 if V3 else .17,wspace=.26,hspace=.95 if RQ2B == 'all' else .42)
            elif key in ('RQ2a','RQ2b'):
                fig.subplots_adjust(left=.145,right=.98,top=.87,bottom=.33,wspace=.18)
            else:
                fig.subplots_adjust(left=.145 if key=='RQ2a' else .16,right=.97,top=.89,bottom=.39 if key=='RQ3a' else .32)
            if key=='RQ1a':
                fig.axes[0].xaxis.set_major_locator(mpl.ticker.MultipleLocator(.5))
            if key=='RQ1b':
                fig.axes[0].xaxis.set_major_locator(mpl.ticker.MultipleLocator(.75))
            if key=='RQ1c':
                for ax, step in zip(fig.axes, (1,30000,.2,200)):
                    ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(step))
                fig.axes[1].xaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:f'{x/1000:g}'))
                fig.axes[1].set_xlabel('Thousands of dollars, 2023, per lane-mile' if V3 else 'Thousands of dollars (2023) per lane-mile')
                if V3:
                    fig.axes[2].set_xlabel('Freight cost / annual freight value (%)')
                    fig.axes[3].set_xlabel('Dollars, 2023, per capita')
            if key=='RQ3a' and V3:
                fig.axes[0].xaxis.set_major_locator(mpl.ticker.MaxNLocator(9,steps=[1,2,5,10]))
            elif key=='RQ3a':
                ax=fig.axes[0]
                ax.set_xlim(0,110)
                ax.set_xticks(range(0,101,10))
                ax.xaxis.set_major_formatter(mpl.ticker.PercentFormatter(100,decimals=0))
            if key=='RQ3b':
                fig.axes[0].xaxis.set_major_locator(mpl.ticker.MultipleLocator(1))
            if key in ('RQ2a','RQ2b'):
                for ax, title in zip(fig.axes, ('Passenger','Freight') if V3 else ('(i) Passenger','(ii) Freight')):
                    ax.set_title(title,loc='left',fontsize=11,fontweight='bold',color='black')
                    ax.set_title('')
            if key in ('RQ1c','RQ2c'):
                for index, ax in enumerate(fig.axes):
                    title=ax.get_title(loc='left')
                    lettered=V3 and titled and (key=='RQ1c' or (key=='RQ2c' and RQ2B))
                    if V3:
                        plain=re.sub(r'^\(\w+\) ','',title)
                        title=(RQ1C_TITLES[index] if key=='RQ1c' else f'({chr(ord("B")+index)}) {plain}') if lettered else plain
                    shift={}
                    if lettered:  # left column flush with the (A) margin; right column puts the letter, not the '(', on the y-axis
                        pos=ax.get_position()
                        shift['x']=(.025-pos.x0)/pos.width if index%2==0 else -4/(pos.width*fig.get_size_inches()[0]*72)
                    ax.set_title(title,loc='left',fontsize=12 if lettered else 11,fontweight='bold',color='black',pad=8 if V3 and titled else 6,**shift)
            if key!='RQ1a' and not (V3 and titled and (key=='RQ1c' or (key=='RQ2c' and RQ2B))):
                heading=V3_TITLES[key] if V3 and titled else '('+({'RQ1b':'A','RQ1c':'B'}.get(key,key[-1].upper()))+')'
                fig.text(.025,.985,heading,ha='left',va='baseline',fontsize=12,fontweight='bold',gid='panel-label')
            # Gap between a lettered title and the plot beneath it (single plots get the 4 pt base plus 4).
            title_gap=(10 if key in ('RQ2a','RQ2b','RQ2c') else 4) if V3 and titled else 0
            if V3 and key=='RQ2c':  # each column's bottom plot keeps its own x-axis label
                for ax in fig.axes[:2]:
                    ax.set_xlabel('')
                for ax in fig.axes[2:] + (fig.axes[:2] if RQ2B == 'all' else []):
                    ax.set_xlabel('Total cost (billions of dollars, 2023)')
                    ax.tick_params(labelbottom=True)
            if V3:  # x-axis labels one point larger than the 10 pt body text
                for ax in fig.axes:
                    ax.xaxis.label.set_fontsize(11)
                for text in fig.texts:
                    if text.get_gid()=='shared-x-label':
                        text.set_fontsize(11)
                        text.set_text(text.get_text().replace('millions','billions'))
            b.finish_labels_and_legends(fig,scale=1,value_fontsize=8,relayout=False)
            title_legends(fig)
            # Long five-category legends use two columns and remain inside the canvas.
            if key.startswith('RQ3'):
                legend=fig.legends[0]
                legend.set_ncols(2)
                # Recreate to lay out the new column count reliably.
                handles,labels=fig.axes[0].get_legend_handles_labels()
                legend.remove()
                legend=fig.legend(handles,labels,ncol=3 if V3 else 2,loc='upper center',frameon=False, borderaxespad=0)
                fig.canvas.draw()
                bottom=fig.axes[0].xaxis.label.get_window_extent(fig.canvas.get_renderer()).y0
                legend.set_bbox_to_anchor((.5,(bottom-10*fig.dpi/72)/fig.bbox.height),transform=fig.transFigure)
                title_legends(fig)
            if V3 and key=='RQ3a':  # start from the longest bar; the label-fit loop below adds only what the totals need
                fig.axes[0].set_xlim(0,max(p.get_x()+p.get_width() for p in fig.axes[0].patches))
            if V3 and key in V2_CAP:
                fig.axes[0].set_xlim(0,V2_CAP[key])  # cap at the last labeled tick; the bars stretch to fill the width
            # Fit total labels at final physical size, including shared-axis panels.
            for _ in range(8):
                fig.canvas.draw()
                renderer=fig.canvas.get_renderer()
                overflow=False
                for ax in fig.axes:
                    totals=[t for t in ax.texts if t.get_fontweight()=='bold' and t.get_rotation()==0]
                    if not totals:
                        continue
                    excess=max(t.get_window_extent(renderer).x1 for t in totals)-ax.bbox.x1+3
                    if excess>0:
                        ax.set_xlim(0,ax.get_xlim()[1]*(1+excess/ax.bbox.width+.03))
                        overflow=True
                if not overflow:
                    break
            if V3 and key=='RQ3a':  # snap the fitted limit up to the next tick so the axis ends on a label
                ax=fig.axes[0]
                ticks=ax.get_xticks()
                step=ticks[1]-ticks[0]
                upper=np.ceil(ax.get_xlim()[1]/step-1e-9)*step
                ax.set_xlim(0,upper)
                ax.set_xticks(np.arange(0,upper+step/2,step))
            align_panel_label(fig,title_gap)
            if V2 and key in V2_CAP:
                # Cap x-axis (4.5 for RQ1b, 9 for RQ3b), shift plot right by the reclaimed width, numerals outside the group boxes.
                ax=fig.axes[0]
                old=ax.get_xlim()[1]
                ax.set_xlim(0,V2_CAP[key])
                pos=ax.get_position()
                # Reclaimed width moves the plot right; V2_STRETCH of it is given back by widening leftward.
                new_width=pos.width*V2_CAP[key]/old+V2_STRETCH
                ax._v2_ratio=new_width/pos.width
                ax.set_position([pos.x1-new_width,pos.y0,new_width,pos.height])
                k=pos.width/new_width  # keep axes-fraction offsets at the same physical distance
                for patch in ax.patches:
                    if patch.get_x()<0:
                        patch.set_x(patch.get_x()*k)
                        patch.set_width(1-patch.get_x())
                box_x=min(patch.get_x() for patch in ax.patches)
                for t in list(ax.texts):
                    if t.get_rotation()==90 and t.get_text().startswith('('):
                        numeral,rest=t.get_text().split(') ',1)
                        t.set_text(rest)
                        t.set_fontsize(10)
                        t.set_x(t.get_position()[0]*k)
                        ax.text(box_x-.012,t.get_position()[1],numeral+')',transform=ax.get_yaxis_transform(),
                                ha='right',va='center',fontsize=10,fontweight='bold',color='#333333')
                align_panel_label(fig)
            if V3 and key=='RQ1a':  # solo export, cropped to content at the same pixel density
                fig.savefig(folder/'RQ1_1.pdf',bbox_inches='tight',pad_inches=.04)
                fig.savefig(folder/'RQ1_1.png',dpi=300,bbox_inches='tight',pad_inches=.04)
            path=parts/(name+suffix+'.pdf')
            figure_tmp = path.with_suffix('.tmp.pdf')
            center_legend_titles(fig)
            fig.savefig(figure_tmp)
            figure_tmp.replace(path)
            if key.startswith('RQ3'):
                fig.set_size_inches(180/25.4, combined_heights[key]/25.4)
                if key=='RQ3a':
                    for legend in list(fig.legends):
                        legend.remove()
                    fig.subplots_adjust(bottom=.20)
                else:
                    fig.subplots_adjust(top=.95,bottom=.19)
                    fig.canvas.draw()
                    bottom=fig.axes[0].xaxis.label.get_window_extent(fig.canvas.get_renderer()).y0
                    fig.legends[0].set_bbox_to_anchor((.5,(bottom-10*fig.dpi/72)/fig.bbox.height),transform=fig.transFigure)
                    if V2:  # subplots_adjust above reset the shifted axes
                        pos=fig.axes[0].get_position()
                        width=pos.width*fig.axes[0]._v2_ratio
                        fig.axes[0].set_position([pos.x1-width,pos.y0,width,pos.height])
                align_panel_label(fig,title_gap)
                buffer=BytesIO()
                center_legend_titles(fig)
                fig.savefig(buffer,format='pdf')
                buffer.seek(0)
                combined_files[key]=buffer
            plt.close(fig)
            files[key]=path
            records.append({'plot':key,'variant':folder.name,'data':status})
        pages=({'RQ2':[['RQ2a','RQ2c']],'RQ3':PAGES['RQ3']} if PROTO else
               {'RQ1':[['RQ1b','RQ1c']],'RQ2':PAGES['RQ2'],'RQ3':PAGES['RQ3']}) if V3 else PAGES
        for rq,groups in pages.items():
            if V3 and rq=='RQ1' and not titled:
                continue
            stem=(('RQ1_2' if rq=='RQ1' else rq+('_proto' if PROTO else suffix)) if V3 else rq+'_combined'+suffix)
            writer=PdfWriter()
            for group in groups:
                def panel_bytes(k):
                    return combined_files[k].getvalue() if k in combined_files else files[k].read_bytes()
                stack_panels(writer,group,combined_heights,panel_bytes,tight=V3)
            path=folder/(stem+'.pdf')
            combined_tmp = path.with_suffix('.tmp.pdf')
            writer.write(combined_tmp)
            combined_tmp.replace(path)
            if V3:
                crop_to_content(path)
            if rq=='RQ1' and not V3:
                solo=PdfWriter()
                solo.add_page(PdfReader(path).pages[0])
                solo_tmp = files['RQ1a'].with_suffix('.tmp.pdf')
                solo.write(solo_tmp)
                solo_tmp.replace(files['RQ1a'])
            doc=pdfium.PdfDocument(str(path))
            for i in range(len(doc)):
                preview=folder/((stem+'.png') if V3 else (rq+'_combined_'+str(i+1)+suffix+'.png'))
                temporary=preview.with_suffix('.tmp.png')
                doc[i].render(scale=300/72).to_pil().save(temporary)
                temporary.replace(preview)
    if V3:
        shutil.rmtree(OUT/V3_DIR/'_parts', ignore_errors=True)
        print(OUT/V3_DIR)
        return
    (OUT/'provenance.json').write_text(json.dumps(records,indent=2))
    (OUT/'README.txt').write_text('Advisor figure package\n\nBoth labeled and unlabeled versions include individual vector PDFs and RQ combinations. Only RQ3A includes percent component labels; both naming variants otherwise omit component labels and retain bold black totals with units, following advisor feedback.\nRQ1: Letter-sized solo figure on page 1; A above B on page 2. RQ2: A, B, C stacked. RQ3: compact A above taller B, with one shared industry legend below B.\nCombined sheets and the RQ1 solo figure: US Letter (8.5 x 11 inches), centered with at least 12 mm vertical margins. Individual figures retain their content-sized canvases.\nTimes New Roman 10 pt, component values 8 pt, parenthesized figure letters 12 pt. No PDF scaling.\nCosts, error bars and industry shares remain synthetic layout examples. RQ1c denominators include actual/approximate statewide inputs; hazard-intersected lane-miles remain unresolved. Do not interpret these figures as final empirical results.\n')
    if '--no-zip' not in sys.argv:
        with zipfile.ZipFile(OUT/'advisor_figures.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for path in OUT.rglob('*'):
                if path.is_file() and path.suffix in ('.pdf','.txt','.json'):
                    archive.write(path,path.relative_to(OUT))
    print(OUT)

if __name__=='__main__':
    build()
