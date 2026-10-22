"""Build the paper figure set from visual_registry.csv (rows with paper_figure set).

    python build_paper_final.py            # build panels + sheets, copy into advisor_package/final, write MANIFEST.csv
    python build_paper_final.py --no-build # only re-copy + manifest from existing outputs

What goes in the set, in what order, with which letters/titles/heights/legend explainers is defined in the registry
columns paper_figure, paper_order, paper_key, paper_build, paper_panel, paper_title, paper_template, paper_height_mm,
legend_match, legend_title. Plot code lives in the templates listed in figlib/templates.py.
"""
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import pandas as pd
from figlib import registry as reg
from figlib.templates import TEMPLATES

HERE = Path(__file__).resolve().parent
PKG = HERE / 'advisor_package'
FINAL = PKG / 'final'
BUILD_FLAGS = {'standard': ['--labeled-v2', '--no-zip'], 'proto': ['--labeled-v2', '--proto', '--no-zip']}
SOURCE = {'standard': lambda fig: PKG / 'labeled_v3' / fig, 'proto': lambda fig: PKG / 'prototypes' / (fig + '_proto')}


def build(modes):
    for mode in modes:
        subprocess.run([sys.executable, str(HERE / 'build_advisor_package.py'), *BUILD_FLAGS[mode]], check=True, cwd=HERE)


def main():
    rows = reg.paper_rows()
    unknown = sorted(set(rows.paper_template) - set(TEMPLATES))
    assert not unknown, f'templates missing from figlib/templates.py: {unknown}'
    modes = sorted(set(rows.paper_build))
    if '--no-build' not in sys.argv:
        build(modes)
    FINAL.mkdir(parents=True, exist_ok=True)
    manifest = []
    for fig, group in rows.groupby('paper_figure', sort=True):
        mode = group.paper_build.iloc[0]
        assert group.paper_build.nunique() == 1, f'{fig}: panels of one figure must come from one build'
        for ext in ('.pdf', '.png'):
            shutil.copy(SOURCE[mode](fig).with_suffix(ext), FINAL / (fig + ext))
        for _, r in group.iterrows():
            manifest.append(dict(figure=fig, panels=r.paper_panel, registry_id=r.id, template=r.paper_template,
                                 build=mode, titles=' | '.join(reg.titles(r)), status=r.status,
                                 axis_dollar_year=r.axis_dollar_year, built=datetime.now().strftime('%Y-%m-%d %H:%M')))
    pd.DataFrame(manifest).to_csv(FINAL / 'MANIFEST.csv', index=False)
    print(f'{len(rows)} panel rows -> {FINAL}')


if __name__ == '__main__':
    main()
