"""Course-required DC smart-grid toolbox.

The module intentionally avoids high-level power-system packages. It uses only
NumPy for network algebra and SciPy/HiGHS for the LPs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Iterable

import numpy as np
from scipy.optimize import linprog

SEED = 31052026
BASE_MVA = 100.0
SLACK_BUS = 4


@dataclass(frozen=True)
class Bus:
    idx: int
    kind: str
    load_mw: float


@dataclass(frozen=True)
class Branch:
    idx: int
    name: str
    from_bus: int
    to_bus: int
    x_pu: float
    rating_mw: float


@dataclass(frozen=True)
class Generator:
    idx: int
    bus: int
    p_min_mw: float
    p_max_mw: float
    cost_usd_per_mwh: float


@dataclass(frozen=True)
class DcopfResult:
    dispatch_mw: dict[int, float]
    injections_mw: list[float]
    angles_rad: list[float]
    line_flows_mw: list[float]
    total_cost_usd_per_h: float
    lmps_usd_per_mwh: list[float]
    binding_lines: list[str]
    line_shadow_prices_usd_per_mwh: dict[str, float]
    raw_success: bool
    raw_message: str


def default_buses() -> list[Bus]:
    return [
        Bus(1, "PV", 0.0),
        Bus(2, "PQ", 90.0),
        Bus(3, "PV", 0.0),
        Bus(4, "Slack", 0.0),
        Bus(5, "PQ", 60.0),
    ]


def default_branches() -> list[Branch]:
    return [
        Branch(1, "L1", 1, 2, 0.094, 100.0),
        Branch(2, "L2", 1, 4, 0.135, 100.0),
        Branch(3, "L3", 2, 3, 0.181, 70.0),
        Branch(4, "L4", 3, 4, 0.122, 90.0),
        Branch(5, "L5", 4, 5, 0.107, 80.0),
        Branch(6, "L6", 2, 5, 0.165, 60.0),
    ]


def default_generators() -> list[Generator]:
    return [
        Generator(1, 1, 20.0, 180.0, 12.40),
        Generator(2, 3, 0.0, 100.0, 22.60),
        Generator(3, 4, 0.0, 200.0, 31.10),
    ]


def scenario_dict() -> dict[str, object]:
    return {
        "seed": SEED,
        "base_mva": BASE_MVA,
        "slack_bus": SLACK_BUS,
        "buses": [asdict(bus) for bus in default_buses()],
        "branches": [asdict(branch) for branch in default_branches()],
        "generators": [asdict(gen) for gen in default_generators()],
    }


def apply_rating_overrides(
    branches: list[Branch], overrides: dict[str, float] | None = None
) -> list[Branch]:
    if not overrides:
        return list(branches)
    by_key = {str(key).upper(): float(value) for key, value in overrides.items()}
    updated: list[Branch] = []
    for branch in branches:
        keys = {branch.name.upper(), str(branch.idx)}
        rating = next((by_key[key] for key in keys if key in by_key), branch.rating_mw)
        updated.append(replace(branch, rating_mw=rating))
    return updated


def build_B(branches: list[Branch], n_buses: int) -> np.ndarray:
    """Build the DC bus susceptance matrix B' in per unit."""
    B = np.zeros((n_buses, n_buses), dtype=float)
    for branch in branches:
        i = branch.from_bus - 1
        j = branch.to_bus - 1
        b = 1.0 / branch.x_pu
        B[i, i] += b
        B[j, j] += b
        B[i, j] -= b
        B[j, i] -= b
    return B


def solve_dc_pf(
    B: np.ndarray, P_inj_pu: Iterable[float], slack_bus_1idx: int
) -> np.ndarray:
    """Solve bus voltage angles for a DC power flow."""
    P = np.asarray(list(P_inj_pu), dtype=float)
    n = B.shape[0]
    slack = slack_bus_1idx - 1
    keep = [idx for idx in range(n) if idx != slack]
    theta = np.zeros(n, dtype=float)
    theta[keep] = np.linalg.solve(B[np.ix_(keep, keep)], P[keep])
    return theta


def branch_flows_mw(branches: list[Branch], theta: Iterable[float]) -> np.ndarray:
    theta_arr = np.asarray(list(theta), dtype=float)
    flows_pu = [
        (theta_arr[branch.from_bus - 1] - theta_arr[branch.to_bus - 1]) / branch.x_pu
        for branch in branches
    ]
    return np.asarray(flows_pu, dtype=float) * BASE_MVA


def build_PTDF(
    branches: list[Branch], n_buses: int, slack_bus_1idx: int
) -> np.ndarray:
    """Return MW/MW PTDF with the slack-bus column fixed at zero."""
    B = build_B(branches, n_buses)
    PTDF = np.zeros((len(branches), n_buses), dtype=float)
    for bus in range(1, n_buses + 1):
        if bus == slack_bus_1idx:
            continue
        injection = np.zeros(n_buses, dtype=float)
        injection[bus - 1] = 1.0
        injection[slack_bus_1idx - 1] = -1.0
        theta = solve_dc_pf(B, injection, slack_bus_1idx)
        PTDF[:, bus - 1] = branch_flows_mw(branches, theta) / BASE_MVA
    return PTDF


def build_LODF(
    branches: list[Branch], n_buses: int, slack_bus_1idx: int
) -> np.ndarray:
    """Return the line outage distribution factor matrix."""
    PTDF = build_PTDF(branches, n_buses, slack_bus_1idx)
    n_lines = len(branches)
    LODF = np.zeros((n_lines, n_lines), dtype=float)
    for k, outage in enumerate(branches):
        bus_to_bus = PTDF[:, outage.from_bus - 1] - PTDF[:, outage.to_bus - 1]
        denom = 1.0 - bus_to_bus[k]
        for m in range(n_lines):
            LODF[m, k] = 1.0 if m == k else bus_to_bus[m] / denom
    return LODF


def injections_from_dispatch(
    buses: list[Bus], gens: list[Generator], dispatch_mw: dict[int, float]
) -> np.ndarray:
    injections = np.asarray([-bus.load_mw for bus in buses], dtype=float)
    for gen in gens:
        injections[gen.bus - 1] += dispatch_mw[gen.idx]
    return injections


def _line_flow_coefficients(
    branches: list[Branch], buses: list[Bus], gens: list[Generator]
) -> tuple[np.ndarray, np.ndarray]:
    PTDF = build_PTDF(branches, len(buses), SLACK_BUS)
    load = np.asarray([bus.load_mw for bus in buses], dtype=float)
    gen_bus_map = np.zeros((len(buses), len(gens)), dtype=float)
    for col, gen in enumerate(gens):
        gen_bus_map[gen.bus - 1, col] = 1.0
    return PTDF @ gen_bus_map, PTDF @ (-load)


def _solve_dispatch_lp(
    buses: list[Bus],
    branches: list[Branch],
    gens: list[Generator],
    extra_ub: list[list[float]] | None = None,
    extra_b: list[float] | None = None,
) -> tuple[np.ndarray, object]:
    c = np.asarray([gen.cost_usd_per_mwh for gen in gens], dtype=float)
    bounds = [(gen.p_min_mw, gen.p_max_mw) for gen in gens]
    total_load = sum(bus.load_mw for bus in buses)
    A_eq = np.ones((1, len(gens)), dtype=float)
    b_eq = np.asarray([total_load], dtype=float)

    flow_coef, flow_const = _line_flow_coefficients(branches, buses, gens)
    A_ub: list[list[float]] = []
    b_ub: list[float] = []
    for row, const, branch in zip(flow_coef, flow_const, branches):
        A_ub.append(row.tolist())
        b_ub.append(branch.rating_mw - const)
        A_ub.append((-row).tolist())
        b_ub.append(branch.rating_mw + const)
    if extra_ub:
        A_ub.extend(extra_ub)
        b_ub.extend(extra_b or [])

    result = linprog(
        c,
        A_ub=np.asarray(A_ub, dtype=float),
        b_ub=np.asarray(b_ub, dtype=float),
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )
    if not result.success:
        raise RuntimeError(f"LP failed: {result.message}")
    return np.asarray(result.x, dtype=float), result


def _lmps_by_finite_difference(
    buses: list[Bus],
    branches: list[Branch],
    gens: list[Generator],
    base_cost: float,
    contingencies: list[int] | None = None,
) -> list[float]:
    lmps: list[float] = []
    eps = 0.01
    for bus_index in range(len(buses)):
        perturbed = list(buses)
        perturbed[bus_index] = replace(
            buses[bus_index], load_mw=buses[bus_index].load_mw + eps
        )
        try:
            if contingencies:
                result = solve_scopf(
                    perturbed, branches, gens, SLACK_BUS, contingencies, compute_lmps=False
                )
            else:
                result = solve_dcopf(
                    perturbed, branches, gens, SLACK_BUS, compute_lmps=False
                )
            lmps.append((result.total_cost_usd_per_h - base_cost) / eps)
        except RuntimeError:
            lmps.append(float("nan"))
    return lmps


def _line_shadow_prices(branches: list[Branch], raw: object) -> dict[str, float]:
    prices: dict[str, float] = {}
    marginals = getattr(getattr(raw, "ineqlin", None), "marginals", None)
    if marginals is None:
        return {branch.name: 0.0 for branch in branches}
    for idx, branch in enumerate(branches):
        upper = float(marginals[2 * idx])
        lower = float(marginals[2 * idx + 1])
        prices[branch.name] = max(0.0, -upper, -lower)
    return prices


def solve_dcopf(
    buses: list[Bus],
    branches: list[Branch],
    gens: list[Generator],
    slack_bus_1idx: int,
    compute_lmps: bool = True,
) -> DcopfResult:
    dispatch_vector, raw = _solve_dispatch_lp(buses, branches, gens)
    dispatch = {gen.idx: float(dispatch_vector[i]) for i, gen in enumerate(gens)}
    injections = injections_from_dispatch(buses, gens, dispatch)
    B = build_B(branches, len(buses))
    theta = solve_dc_pf(B, injections / BASE_MVA, slack_bus_1idx)
    flows = branch_flows_mw(branches, theta)
    cost = float(sum(dispatch[gen.idx] * gen.cost_usd_per_mwh for gen in gens))
    lmps = _lmps_by_finite_difference(buses, branches, gens, cost) if compute_lmps else []
    binding = [
        branch.name
        for branch, flow in zip(branches, flows)
        if abs(abs(flow) - branch.rating_mw) <= 1e-5
    ]
    return DcopfResult(
        dispatch_mw=dispatch,
        injections_mw=injections.tolist(),
        angles_rad=theta.tolist(),
        line_flows_mw=flows.tolist(),
        total_cost_usd_per_h=cost,
        lmps_usd_per_mwh=lmps,
        binding_lines=binding,
        line_shadow_prices_usd_per_mwh=_line_shadow_prices(branches, raw),
        raw_success=bool(raw.success),
        raw_message=str(raw.message),
    )


def run_n1_screening(
    branches: list[Branch],
    PTDF: np.ndarray,
    LODF: np.ndarray,
    P_inj_pu: Iterable[float],
    ratings_MW: Iterable[float],
) -> list[dict[str, object]]:
    base_flows = PTDF @ np.asarray(list(P_inj_pu), dtype=float) * BASE_MVA
    ratings = np.asarray(list(ratings_MW), dtype=float)
    records: list[dict[str, object]] = []
    for k, outage in enumerate(branches):
        post = base_flows + LODF[:, k] * base_flows[k]
        post[k] = np.nan
        loading = np.abs(post) / ratings * 100.0
        loading[k] = np.nan
        worst_idx = int(np.nanargmax(loading))
        records.append(
            {
                "outage": outage.name,
                "outage_index": outage.idx,
                "post_flows_mw": [
                    None if np.isnan(value) else float(value) for value in post
                ],
                "max_loading_pct": float(loading[worst_idx]),
                "worst_line": branches[worst_idx].name,
                "overloaded": bool(np.nanmax(loading) > 100.0 + 1e-9),
            }
        )
    return records


def solve_scopf(
    buses: list[Bus],
    branches: list[Branch],
    gens: list[Generator],
    slack_bus_1idx: int,
    contingencies: list[int],
    compute_lmps: bool = True,
) -> DcopfResult:
    PTDF = build_PTDF(branches, len(buses), slack_bus_1idx)
    LODF = build_LODF(branches, len(buses), slack_bus_1idx)
    load = np.asarray([bus.load_mw for bus in buses], dtype=float)
    gen_bus_map = np.zeros((len(buses), len(gens)), dtype=float)
    for col, gen in enumerate(gens):
        gen_bus_map[gen.bus - 1, col] = 1.0

    extra_ub: list[list[float]] = []
    extra_b: list[float] = []
    for contingency in contingencies:
        k = contingency - 1
        for m, branch in enumerate(branches):
            if m == k:
                continue
            ptdf_post = PTDF[m, :] + LODF[m, k] * PTDF[k, :]
            row = ptdf_post @ gen_bus_map
            const = ptdf_post @ (-load)
            extra_ub.append(row.tolist())
            extra_b.append(branch.rating_mw - const)
            extra_ub.append((-row).tolist())
            extra_b.append(branch.rating_mw + const)

    dispatch_vector, raw = _solve_dispatch_lp(
        buses, branches, gens, extra_ub=extra_ub, extra_b=extra_b
    )
    dispatch = {gen.idx: float(dispatch_vector[i]) for i, gen in enumerate(gens)}
    injections = injections_from_dispatch(buses, gens, dispatch)
    B = build_B(branches, len(buses))
    theta = solve_dc_pf(B, injections / BASE_MVA, slack_bus_1idx)
    flows = branch_flows_mw(branches, theta)
    cost = float(sum(dispatch[gen.idx] * gen.cost_usd_per_mwh for gen in gens))
    lmps = (
        _lmps_by_finite_difference(buses, branches, gens, cost, contingencies)
        if compute_lmps
        else []
    )
    binding = [
        branch.name
        for branch, flow in zip(branches, flows)
        if abs(abs(flow) - branch.rating_mw) <= 1e-5
    ]
    return DcopfResult(
        dispatch_mw=dispatch,
        injections_mw=injections.tolist(),
        angles_rad=theta.tolist(),
        line_flows_mw=flows.tolist(),
        total_cost_usd_per_h=cost,
        lmps_usd_per_mwh=lmps,
        binding_lines=binding,
        line_shadow_prices_usd_per_mwh=_line_shadow_prices(branches, raw),
        raw_success=bool(raw.success),
        raw_message=str(raw.message),
    )


def direct_outage_flows(
    branches: list[Branch], injections_mw: Iterable[float], outage_index: int
) -> list[float | None]:
    surviving = [branch for branch in branches if branch.idx != outage_index]
    B = build_B(surviving, len(default_buses()))
    theta = solve_dc_pf(B, np.asarray(list(injections_mw)) / BASE_MVA, SLACK_BUS)
    surviving_flows = branch_flows_mw(surviving, theta)
    values: list[float | None] = []
    cursor = 0
    for branch in branches:
        if branch.idx == outage_index:
            values.append(None)
        else:
            values.append(float(surviving_flows[cursor]))
            cursor += 1
    return values


def full_project_results(
    rating_overrides: dict[str, float] | None = None,
    contingencies: list[int] | None = None,
) -> dict[str, object]:
    np.random.seed(SEED)
    buses = default_buses()
    branches = apply_rating_overrides(default_branches(), rating_overrides)
    gens = default_generators()
    n_buses = len(buses)

    B = build_B(branches, n_buses)
    phase1_dispatch = {1: 110.0, 2: 40.0, 3: 0.0}
    phase1_inj = injections_from_dispatch(buses, gens, phase1_dispatch)
    phase1_theta = solve_dc_pf(B, phase1_inj / BASE_MVA, SLACK_BUS)
    phase1_flows = branch_flows_mw(branches, phase1_theta)
    PTDF = build_PTDF(branches, n_buses, SLACK_BUS)
    ptdf_flows = PTDF @ (phase1_inj / BASE_MVA) * BASE_MVA
    LODF = build_LODF(branches, n_buses, SLACK_BUS)

    dcopf = solve_dcopf(buses, branches, gens, SLACK_BUS)
    ratings = [branch.rating_mw for branch in branches]
    screening = run_n1_screening(
        branches, PTDF, LODF, np.asarray(dcopf.injections_mw) / BASE_MVA, ratings
    )
    worst = max(screening, key=lambda row: float(row["max_loading_pct"]))
    worst_index = int(worst["outage_index"])
    selected_contingencies = contingencies or [worst_index]
    scopf = solve_scopf(buses, branches, gens, SLACK_BUS, selected_contingencies)

    scopf_screen = run_n1_screening(
        branches, PTDF, LODF, np.asarray(scopf.injections_mw) / BASE_MVA, ratings
    )
    scopf_worst_row = next(
        row for row in scopf_screen if int(row["outage_index"]) == worst_index
    )
    direct_crosscheck = direct_outage_flows(branches, dcopf.injections_mw, worst_index)
    lodf_crosscheck = worst["post_flows_mw"]
    crosscheck_rows = []
    for branch, lodf_flow, direct_flow in zip(branches, lodf_crosscheck, direct_crosscheck):
        if branch.idx == worst_index:
            continue
        crosscheck_rows.append(
            {
                "line": branch.name,
                "lodf_flow_mw": lodf_flow,
                "direct_resolve_flow_mw": direct_flow,
                "abs_error_mw": abs(float(lodf_flow) - float(direct_flow)),
            }
        )

    scopf_post_loading_rows = []
    for branch, flow in zip(branches, scopf_worst_row["post_flows_mw"]):
        if branch.idx == worst_index:
            continue
        loading = abs(float(flow)) / branch.rating_mw * 100.0
        scopf_post_loading_rows.append(
            {
                "line": branch.name,
                "post_flow_mw": flow,
                "rating_mw": branch.rating_mw,
                "loading_pct": loading,
                "overloaded": loading > 100.0 + 1e-9,
            }
        )

    cost_delta = scopf.total_cost_usd_per_h - dcopf.total_cost_usd_per_h
    base_pre_loading = max(abs(f) / r * 100.0 for f, r in zip(dcopf.line_flows_mw, ratings))

    return {
        "metadata": {
            "seed": SEED,
            "base_mva": BASE_MVA,
            "slack_bus": SLACK_BUS,
            "solver": "scipy.optimize.linprog(method='highs')",
        },
        "scenario": scenario_dict(),
        "phase1": {
            "B": B.tolist(),
            "dispatch_mw": phase1_dispatch,
            "injections_mw": phase1_inj.tolist(),
            "angles_rad": phase1_theta.tolist(),
            "line_flows_mw": phase1_flows.tolist(),
            "ptdf": PTDF.tolist(),
            "ptdf_slack_column_zero": bool(np.allclose(PTDF[:, SLACK_BUS - 1], 0.0)),
            "ptdf_flow_crosscheck_mw": ptdf_flows.tolist(),
            "max_flow_crosscheck_error_mw": float(np.max(np.abs(phase1_flows - ptdf_flows))),
        },
        "phase2": {
            "base_dcopf": asdict(dcopf),
            "congested_l2_30": asdict(
                solve_dcopf(
                    buses,
                    apply_rating_overrides(default_branches(), {"L2": 30.0}),
                    gens,
                    SLACK_BUS,
                )
            ),
        },
        "phase3": {
            "lodf": LODF.tolist(),
            "lodf_l3_l1": float(LODF[2, 0]),
            "lodf_diagonal_all_one": bool(np.allclose(np.diag(LODF), 1.0)),
            "screening": screening,
            "worst_contingency": worst,
            "direct_outage_crosscheck_mw": direct_crosscheck,
            "lodf_direct_crosscheck": crosscheck_rows,
            "event_sentence": (
                "A plausible event is a relay misconfiguration or breaker operation "
                f"that trips {worst['outage']} during a coordinated cyber-physical incident."
            ),
        },
        "phase4": {
            "contingencies": selected_contingencies,
            "scopf": asdict(scopf),
            "cost_of_security_usd_per_h": cost_delta,
            "cost_of_security_pct": cost_delta / dcopf.total_cost_usd_per_h * 100.0,
            "scopf_post_contingency": scopf_worst_row,
            "scopf_post_contingency_loadings": scopf_post_loading_rows,
        },
        "phase5": {
            "operating_state_table": [
                {
                    "dispatch": "Base DCOPF",
                    "scenario": "pre-contingency",
                    "max_loading_pct": base_pre_loading,
                    "cost_usd_per_h": dcopf.total_cost_usd_per_h,
                },
                {
                    "dispatch": "Base DCOPF",
                    "scenario": f"post-contingency {worst['outage']}",
                    "max_loading_pct": worst["max_loading_pct"],
                    "cost_usd_per_h": dcopf.total_cost_usd_per_h,
                },
                {
                    "dispatch": "SCOPF",
                    "scenario": "pre-contingency",
                    "max_loading_pct": max(
                        abs(f) / r * 100.0 for f, r in zip(scopf.line_flows_mw, ratings)
                    ),
                    "cost_usd_per_h": scopf.total_cost_usd_per_h,
                },
                {
                    "dispatch": "SCOPF",
                    "scenario": f"post-contingency {worst['outage']}",
                    "max_loading_pct": scopf_worst_row["max_loading_pct"],
                    "cost_usd_per_h": scopf.total_cost_usd_per_h,
                },
            ],
            "interpretation": (
                f"The base DCOPF is economical at {dcopf.total_cost_usd_per_h:.2f} USD/h "
                f"and reaches {base_pre_loading:.2f}% maximum loading before an outage, "
                f"but under {worst['outage']} it rises to {worst['max_loading_pct']:.2f}% "
                f"and is insecure. SCOPF costs {scopf.total_cost_usd_per_h:.2f} USD/h, "
                f"so it pays Delta C = {cost_delta:.2f} USD/h "
                f"({cost_delta / dcopf.total_cost_usd_per_h * 100.0:.2f}%) every hour. "
                f"In exchange, the selected post-contingency loading is capped at "
                f"{scopf_worst_row['max_loading_pct']:.2f}% instead of exposing the system "
                "to the overload."
            ),
            "cyber_physical_reflection": (
                "The Ukraine 2015 power-grid attack is a documented example where "
                "attackers used remote access to distribution-control environments, "
                "opened breakers, disrupted operator visibility, and delayed restoration. "
                "The later Industroyer/CrashOverride incident in 2016 further showed that "
                "grid-specific malware can target substation switching operations rather "
                "than only business IT. In this setting, a line outage is not just a "
                "low-probability random fault; it can be the adversary's chosen action. "
                "That changes the dispatch decision: the operator may rationally accept "
                "the SCOPF premium when the insecure base dispatch creates an obvious "
                "post-contingency overload target."
            ),
        },
    }
