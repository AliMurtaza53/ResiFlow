"""Run with: python results/viz/check_advisor_layout.py"""
import matplotlib.pyplot as plt
import numpy as np
import build_advisor_review_figures as viz

viz.apply_style()
viz.SHOW_DATA_LABELS = False  # Advisor review now shows totals only.
rows = viz.filtered_rows(viz.load_registry()).set_index('id')
for row_id in rows.index:
    row = rows.loc[row_id].copy()
    row['id'] = row_id
    data, _ = viz.load_or_synthetic(row)
    fig = viz.plot_generic(row, data, 'synthetic')
    fig.canvas.draw()
    for ax in fig.axes:
        for bar in ax.patches:
            if bar.get_transform() == ax.transData:
                assert bar.get_x() + bar.get_width() <= ax.get_xlim()[1] + 1e-8, row_id
    if row_id == 's3_major_cost_panel_a_facility':
        ax = fig.axes[0]
        labels = ax.get_yticklabels()
        totals = np.array([p.get_width() for p in ax.patches[:60]]).reshape(3, 20).sum(axis=0)
        for start in range(0, 20, 5):
            group = labels[start:start + 5]
            assert {t.get_text() for t in group} == {'Bridges', 'Interstate', 'Arterial', 'Collector', 'Local road'}
            assert next(t for t in group if t.get_text() == 'Bridges').get_fontstyle() == 'italic'
            assert np.all(np.diff(totals[start:start + 5]) <= 0)
        assert ax.yaxis_inverted()
    if row_id == 'x_ranked_states_4metric':
        assert [ax.get_xlabel() for ax in fig.axes] == ['Billions of dollars, 2023', '2023 dollars per lane-mile', 'Costs / annual outbound freight value (%)', 'Dollars (2023) per capita']
        totals, denominators = viz.affected_cost_metrics(data)
        assert denominators[1].gt(0).all() and denominators[2].gt(0).all()
        assert denominators[3].gt(0).all()
        expected_totals = data[data.geo_scope.eq('affected')].groupby('hazard')[list(viz.COST_COLORS)].sum().reindex(viz.HAZARDS)
        np.testing.assert_allclose(totals, expected_totals)
    if row_id == 'x_top5_states_industry':
        ax = fig.axes[0]
        totals = np.array([p.get_width() for c in ax.containers for p in c]).reshape(5, 20).sum(axis=0)
        for start in range(0, 20, 5):
            assert np.all(np.diff(totals[start:start + 5]) <= 0)
    before = sum(len(ax.texts) for ax in fig.axes)
    expected = sum(sum(len(c) for c in ax.containers) for ax in fig.axes
                   if len(ax.containers) > 1 and all(isinstance(c, viz.mpl.container.BarContainer) for c in ax.containers))
    expected = 0 if not viz.SHOW_DATA_LABELS else expected
    viz.finish_labels_and_legends(fig)
    assert sum(len(ax.texts) for ax in fig.axes) - before == expected
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    labels = [ax.xaxis.label for ax in fig.axes if ax.get_xlabel()]
    labels += [t for t in fig.texts if t.get_gid() == 'shared-x-label']
    legends = list(fig.legends) + [ax.get_legend() for ax in fig.axes if ax.get_legend()]
    for legend in legends:
        gap = min(t.get_window_extent(renderer).y0 for t in labels) - legend.get_window_extent(renderer).y1
        assert abs(gap * 72 / fig.dpi - 10) < .1
    plt.close(fig)
print('Eight layouts checked; aggregation, denominator availability, sorting, label counts and legend gap passed.')
