# SmartGridSimulation

FastAPI service and reproducible project pipeline for the CPS smart-grid assignment in
`Project.pdf`.

The implementation covers:

- DC bus susceptance matrix and DC power flow
- PTDF and LODF matrices
- DCOPF with LMP estimates
- N-1 contingency screening
- single-contingency SCOPF
- operating-state comparison, report source, chart, and generated PDF report
- Docker and Docker Compose runtime

## Requirements

- Python 3.11+
- Docker Desktop, optional but recommended

The core solver is `scipy.optimize.linprog(method="highs")`. No high-level power-system
libraries are used.

## Local Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,report]"
```

Run tests:

```bash
pytest
```

Run the API:

```bash
uvicorn smart_grid.api:app --reload --host 0.0.0.0 --port 8000
```

Open Swagger UI at:

```text
http://localhost:8000/docs
```

## Docker

Start the API:

```bash
docker compose up --build api
```

Run the reproducible project script in Docker:

```bash
docker compose --profile tools run --rm project
```

## Reproduce The Project

Print all key numerical outputs:

```bash
python scripts/run_project.py
```

Generate `reports/report.md`, `reports/report.html`, `reports/operating_state_loading.png`,
and `reports/report.pdf`:

```bash
python scripts/run_project.py --write-report
```

The script prints the required banner with timestamp, Python/NumPy/SciPy versions, solver
name, and seed `31052026`.

## API Endpoints

- `GET /health`
- `GET /metadata`
- `GET /scenario/default`
- `POST /power-flow`
- `GET /ptdf`
- `GET /lodf`
- `POST /dcopf`
- `POST /n1-screening`
- `POST /scopf`
- `GET /project/run`

Example rating override:

```bash
curl -X POST http://localhost:8000/dcopf ^
  -H "Content-Type: application/json" ^
  -d "{\"rating_overrides\":{\"L2\":30}}"
```

## Repository Layout

```text
src/smart_grid/cps_grid.py  # course-required toolbox
src/smart_grid/api.py       # FastAPI application
scripts/run_project.py      # reproducible end-to-end runner
reports/report.md           # generated report source placeholder
tests/                      # unit and API tests
```
