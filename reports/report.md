# CPS Smart Grid Simulation Report

Author: Surname Name  
Generated: 2026-05-30T10:03:33.209347+00:00  
Seed: `31052026`  
Solver: `scipy.optimize.linprog(method='highs')`

## Introduction

This report reproduces the course project pipeline for the custom 5-bus DC network:
DC power flow, PTDF, LODF, DCOPF, N-1 screening, single-contingency SCOPF, and the
operating-state comparison.

Use of generative AI tools is disclosed for implementation assistance. Numerical values
are produced by `scripts/run_project.py`.

## Phase 1: Ybus/DC PF/PTDF

Base dispatch for the foundation check: `{1: 110.0, 2: 40.0, 3: 0.0}` MW.

Angles in radians:

| Bus | theta |
| --- | --- |
| 1 | 0.0440 |
| 2 | -0.0288 |
| 3 | 0.0176 |
| 4 | 0.0000 |
| 5 | -0.0503 |

Line-flow cross-check:

| Line | Direct DC PF MW | PTDF MW |
| --- | --- | --- |
| L1 | 77.4161 | 77.4161 |
| L2 | 32.5839 | 32.5839 |
| L3 | -25.6049 | -25.6049 |
| L4 | 14.3951 | 14.3951 |
| L5 | 46.9790 | 46.9790 |
| L6 | 13.0210 | 13.0210 |

Maximum cross-check error: `0.00000000` MW.  
Slack column of PTDF is zero: `True`.

PTDF:

|  | Bus 1 | Bus 2 | Bus 3 | Bus 4 | Bus 5 |
| --- | --- | --- | --- | --- | --- |
| L1 | 0.3626 | -0.3850 | -0.1550 | 0.0000 | -0.1514 |
| L2 | 0.6374 | 0.3850 | 0.1550 | 0.0000 | 0.1514 |
| L3 | 0.1715 | 0.2909 | -0.2855 | 0.0000 | 0.1145 |
| L4 | 0.1715 | 0.2909 | 0.7145 | 0.0000 | 0.1145 |
| L5 | -0.1911 | -0.3241 | -0.1305 | 0.0000 | -0.7341 |
| L6 | 0.1911 | 0.3241 | 0.1305 | 0.0000 | -0.2659 |

## Phase 2: DCOPF And LMPs

Base DCOPF cost: `1860.00` USD/h.  
Base dispatch: `{1: 150.0, 2: 0.0, 3: 0.0}` MW.  
Base LMPs: `['12.40', '12.40', '12.40', '12.40', '12.40']` USD/MWh.  
Binding base lines: `[]`.

With engineered congestion `L2 = 30 MW`, cost is
`2322.63` USD/h and dispatch is
`{1: 104.64388760868304, 2: 45.35611239131693, 3: 0.0}` MW.

## Phase 3: LODF And N-1 Screening

LODF matrix:

|  | L1 | L2 | L3 | L4 | L5 | L6 |
| --- | --- | --- | --- | --- | --- | --- |
| L1 | 1.0000 | 1.0000 | -0.5429 | -0.5429 | 0.5695 | -0.5695 |
| L2 | 1.0000 | 1.0000 | 0.5429 | 0.5429 | -0.5695 | 0.5695 |
| L3 | -0.4730 | 0.4730 | 1.0000 | -1.0000 | -0.4305 | 0.4305 |
| L4 | -0.4730 | 0.4730 | -1.0000 | 1.0000 | -0.4305 | 0.4305 |
| L5 | 0.5270 | -0.5270 | -0.4571 | -0.4571 | 1.0000 | 1.0000 |
| L6 | -0.5270 | 0.5270 | 0.4571 | 0.4571 | 1.0000 | 1.0000 |

Explicit LODF value `L_L3,L1 = -0.4730`.

Contingency table:

| Outage | Max loading % | Worst line | Overloaded |
| --- | --- | --- | --- |
| L1 | 150.00 | L2 | True |
| L2 | 150.00 | L1 | True |
| L3 | 102.10 | L1 | True |
| L4 | 102.10 | L1 | True |
| L5 | 123.50 | L1 | True |
| L6 | 89.32 | L1 | False |

Worst contingency: `L2`.

Physical/adversarial event: A plausible event is a relay misconfiguration or breaker operation that trips L2 during a coordinated cyber-physical incident.

## Phase 4: SCOPF

SCOPF enforced contingencies: `[2]`.  
SCOPF cost: `2370.00` USD/h.  
SCOPF dispatch: `{1: 99.99999999999999, 2: 50.000000000000014, 3: 0.0}` MW.  
SCOPF LMPs: `['12.40', '22.60', '22.60', '22.60', '22.60']` USD/MWh.

Dispatch comparison:

| Generator | Base DCOPF MW | SCOPF MW | Move MW |
| --- | --- | --- | --- |
| G1 | 150.0000 | 100.0000 | -50.0000 |
| G2 | 0.0000 | 50.0000 | 50.0000 |
| G3 | 0.0000 | 0.0000 | 0.0000 |

Cost of security: `510.00` USD/h
(`27.42%` of base DCOPF cost).

SCOPF post-contingency max loading under the selected outage:
`100.00%`.

## Phase 5: Operating-State Analysis

| Dispatch | Scenario | Max loading % | Cost USD/h |
| --- | --- | --- | --- |
| Base DCOPF | pre-contingency | 98.12 | 1860.00 |
| Base DCOPF | post-contingency L2 | 150.00 | 1860.00 |
| SCOPF | pre-contingency | 72.24 | 2370.00 |
| SCOPF | post-contingency L2 | 100.00 | 2370.00 |

Interpretation: SCOPF pays the preventive cost of security every hour, but removes the overload exposure for the selected worst single-line outage.

Cyber-physical reflection: The Ukraine 2015 power-grid attack showed that adversaries can use cyber access to create physical switching consequences, not merely data loss. If a line trip can be intentional, the operator should treat high-impact contingencies as strategic threats and may justify SCOPF even when the random outage probability is low.

## Conclusion

The implementation provides a reproducible numerical pipeline and an API surface for
rerunning the project calculations locally or in Docker.
