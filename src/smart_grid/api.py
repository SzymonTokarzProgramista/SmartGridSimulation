"""FastAPI application for the smart-grid simulation."""

from __future__ import annotations

import platform
import sys
from dataclasses import asdict
from typing import Any

import numpy as np
import scipy
from fastapi import FastAPI
from pydantic import BaseModel, Field

from smart_grid.cps_grid import (
    BASE_MVA,
    SEED,
    SLACK_BUS,
    apply_rating_overrides,
    branch_flows_mw,
    build_B,
    build_LODF,
    build_PTDF,
    default_branches,
    default_buses,
    default_generators,
    full_project_results,
    injections_from_dispatch,
    run_n1_screening,
    scenario_dict,
    solve_dc_pf,
    solve_dcopf,
    solve_scopf,
)

app = FastAPI(
    title="Smart Grid Simulation",
    version="0.1.0",
    description="DC power flow, PTDF/LODF, DCOPF, N-1 screening, and SCOPF service.",
)


class RatingOverrideRequest(BaseModel):
    rating_overrides: dict[str, float] = Field(default_factory=dict)


class PowerFlowRequest(RatingOverrideRequest):
    dispatch_mw: dict[int, float] = Field(
        default_factory=lambda: {1: 110.0, 2: 40.0, 3: 0.0}
    )


class ScopfRequest(RatingOverrideRequest):
    contingencies: list[int] | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metadata")
def metadata() -> dict[str, Any]:
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "solver": "scipy.optimize.linprog(method='highs')",
        "seed": SEED,
    }


@app.get("/scenario/default")
def scenario_default() -> dict[str, Any]:
    return scenario_dict()


@app.post("/power-flow")
def power_flow(request: PowerFlowRequest) -> dict[str, Any]:
    buses = default_buses()
    branches = apply_rating_overrides(default_branches(), request.rating_overrides)
    gens = default_generators()
    B = build_B(branches, len(buses))
    injections = injections_from_dispatch(buses, gens, request.dispatch_mw)
    theta = solve_dc_pf(B, injections / BASE_MVA, SLACK_BUS)
    return {
        "dispatch_mw": request.dispatch_mw,
        "injections_mw": injections.tolist(),
        "angles_rad": theta.tolist(),
        "line_flows_mw": branch_flows_mw(branches, theta).tolist(),
    }


@app.get("/ptdf")
def ptdf() -> dict[str, Any]:
    branches = default_branches()
    matrix = build_PTDF(branches, len(default_buses()), SLACK_BUS)
    return {"ptdf": matrix.tolist(), "slack_bus": SLACK_BUS}


@app.get("/lodf")
def lodf() -> dict[str, Any]:
    branches = default_branches()
    matrix = build_LODF(branches, len(default_buses()), SLACK_BUS)
    return {"lodf": matrix.tolist()}


@app.post("/dcopf")
def dcopf(request: RatingOverrideRequest) -> dict[str, Any]:
    buses = default_buses()
    branches = apply_rating_overrides(default_branches(), request.rating_overrides)
    gens = default_generators()
    return asdict(solve_dcopf(buses, branches, gens, SLACK_BUS))


@app.post("/n1-screening")
def n1_screening(request: RatingOverrideRequest) -> dict[str, Any]:
    buses = default_buses()
    branches = apply_rating_overrides(default_branches(), request.rating_overrides)
    gens = default_generators()
    dcopf_result = solve_dcopf(buses, branches, gens, SLACK_BUS)
    PTDF = build_PTDF(branches, len(buses), SLACK_BUS)
    LODF = build_LODF(branches, len(buses), SLACK_BUS)
    records = run_n1_screening(
        branches,
        PTDF,
        LODF,
        np.asarray(dcopf_result.injections_mw) / BASE_MVA,
        [branch.rating_mw for branch in branches],
    )
    return {"screening": records}


@app.post("/scopf")
def scopf(request: ScopfRequest) -> dict[str, Any]:
    buses = default_buses()
    branches = apply_rating_overrides(default_branches(), request.rating_overrides)
    gens = default_generators()
    contingencies = request.contingencies
    if contingencies is None:
        results = full_project_results(request.rating_overrides)
        contingencies = results["phase4"]["contingencies"]
    return asdict(solve_scopf(buses, branches, gens, SLACK_BUS, contingencies))


@app.get("/project/run")
def project_run() -> dict[str, Any]:
    return full_project_results()
