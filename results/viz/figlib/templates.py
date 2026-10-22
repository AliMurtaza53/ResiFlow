"""Chart templates: name (registry column paper_template) -> where the plot code lives and what it needs.

Adding a plot = add a function that returns a finished 180 mm-wide matplotlib Figure, register it here, then add a
visual_registry.csv row with paper_figure / paper_key / paper_template. Panel letters and titles come from the registry.
"""

TEMPLATES = {
    'stacked_by_event_and_class': dict(
        where='build_advisor_review_figures.plot_generic (id s3_major_cost_panel_a_facility)',
        data='direct cost by hazard x road class x severity (3 severity levels)', legend='severity ramp'),
    'grouped_event_bars_with_error': dict(
        where='build_advisor_review_figures.plot_generic (id s3_major_cost_panel_b_state)',
        data='direct cost by state within event, with min-max band', legend='none'),
    'small_multiples_2x2_by_event': dict(
        where='build_advisor_review_figures.plot_ranked_state_metrics',
        data='total/per-lane-mile/relative/per-capita cost by event, Direct|Rerouting|Isolation stacks', legend='cost type'),
    'event_mode_stacked_bars': dict(
        where='proto_figures.rq2_merged', data='rerouting (Operating/Time/Toll) + isolation, Passenger vs Freight per event',
        legend='indirect damage cost type'),
    'small_multiples_2x2_by_state': dict(
        where='build_advisor_review_figures.plot_state_flow_cost', data='top states per event, Direct|Rerouting|Isolation',
        legend='cost type'),
    'event_industry_dual_panel': dict(
        where='proto_figures.rq3a_dual', data='disrupted tonnage and value by event x industry', legend='shared with grouped_state_stacked_bars'),
    'grouped_state_stacked_bars': dict(
        where='build_advisor_review_figures.plot_generic (id x_top5_states_industry)', data='disrupted freight cost by state x industry',
        legend='freight commodity group'),
}
# Planned for background figures (not built yet): 'map_footprint' (hazard footprint map), 'network_overview'.
