import math

import numpy as np

from smart_grid.cps_grid import (
    BASE_MVA,
    SLACK_BUS,
    apply_rating_overrides,
    build_B,
    build_LODF,
    build_PTDF,
    default_branches,
    default_buses,
    default_generators,
    direct_outage_flows,
    full_project_results,
    injections_from_dispatch,
    run_n1_screening,
    solve_dc_pf,
    solve_dcopf,
    solve_scopf,
)


def test_build_b_is_symmetric_and_rows_sum_to_zero():
    B = build_B(default_branches(), len(default_buses()))
    assert B.shape == (5, 5)
    assert np.allclose(B, B.T)
    assert np.allclose(B.sum(axis=1), 0.0)


def test_dc_pf_matches_ptdf_flows():
    buses = default_buses()
    branches = default_branches()
    gens = default_generators()
    dispatch = {1: 110.0, 2: 40.0, 3: 0.0}
    injections = injections_from_dispatch(buses, gens, dispatch)
    B = build_B(branches, len(buses))
    theta = solve_dc_pf(B, injections / BASE_MVA, SLACK_BUS)
    direct = np.array(
        [
            (theta[branch.from_bus - 1] - theta[branch.to_bus - 1]) / branch.x_pu
            * BASE_MVA
            for branch in branches
        ]
    )
    via_ptdf = build_PTDF(branches, len(buses), SLACK_BUS) @ (injections / BASE_MVA) * BASE_MVA
    assert np.allclose(direct, via_ptdf, atol=1e-6)


def test_ptdf_slack_column_is_zero():
    PTDF = build_PTDF(default_branches(), len(default_buses()), SLACK_BUS)
    assert np.allclose(PTDF[:, SLACK_BUS - 1], 0.0)


def test_lodf_shape_and_diagonal():
    LODF = build_LODF(default_branches(), len(default_buses()), SLACK_BUS)
    assert LODF.shape == (6, 6)
    assert np.allclose(np.diag(LODF), 1.0)


def test_dcopf_constraints_are_satisfied():
    buses = default_buses()
    branches = default_branches()
    result = solve_dcopf(buses, branches, default_generators(), SLACK_BUS)
    assert math.isfinite(result.total_cost_usd_per_h)
    assert abs(sum(result.injections_mw)) < 1e-7
    for flow, branch in zip(result.line_flows_mw, branches):
        assert abs(flow) <= branch.rating_mw + 1e-6


def test_lodf_worst_outage_matches_direct_resolve():
    buses = default_buses()
    branches = default_branches()
    gens = default_generators()
    dcopf = solve_dcopf(buses, branches, gens, SLACK_BUS)
    PTDF = build_PTDF(branches, len(buses), SLACK_BUS)
    LODF = build_LODF(branches, len(buses), SLACK_BUS)
    screening = run_n1_screening(
        branches,
        PTDF,
        LODF,
        np.asarray(dcopf.injections_mw) / BASE_MVA,
        [branch.rating_mw for branch in branches],
    )
    worst = max(screening, key=lambda row: row["max_loading_pct"])
    direct = direct_outage_flows(branches, dcopf.injections_mw, worst["outage_index"])
    for lodf_flow, direct_flow in zip(worst["post_flows_mw"], direct):
        if lodf_flow is not None:
            assert abs(lodf_flow - direct_flow) <= 1e-6


def test_scopf_survives_selected_contingency():
    results = full_project_results()
    branches = default_branches()
    row = results["phase4"]["scopf_post_contingency"]
    assert row["max_loading_pct"] <= 100.0 + 1e-6
    assert not row["overloaded"]
    scopf = solve_scopf(
        default_buses(),
        branches,
        default_generators(),
        SLACK_BUS,
        results["phase4"]["contingencies"],
    )
    for flow, branch in zip(scopf.line_flows_mw, branches):
        assert abs(flow) <= branch.rating_mw + 1e-6


def test_engineered_l2_congestion_keeps_rating():
    branches = apply_rating_overrides(default_branches(), {"L2": 30.0})
    result = solve_dcopf(default_buses(), branches, default_generators(), SLACK_BUS)
    assert abs(result.line_flows_mw[1]) <= 30.0 + 1e-6
