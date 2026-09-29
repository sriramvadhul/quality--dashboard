# Production Quality Dashboard

A small Dash app that monitors end-of-line inspection quality for a car plant: an ETL step that loads data into SQL, and a dashboard with SPC control charts, a Pareto chart and a line × shift heatmap.

## What it shows
- **KPIs:** units inspected, defects, defect rate, and the number of out-of-control days
- **p-chart (SPC):** daily defect rate with 3σ control limits. Points outside the limits are flagged in red.
- **Pareto:** the top 10 defect types by line, with a cumulative % curve
- **Heatmap:** defect rate by production line × shift
- **Filters:** production lines and date range (all aggregation is done in SQL)

The synthetic data includes a planted issue: **the Paint line drifts upward over the last 10 days**. The dashboard flags it, and the heatmap and Pareto chart trace it back to its cause.

## Run
```bash
pip install -r requirements.txt
python etl.py        # extract -> transform -> load into quality.db (SQLite)
python app.py        # http://127.0.0.1:8050
```
Deploy: `gunicorn app:server`

## Structure
```
etl.py            # extract (simulated MES data) -> transform (fact tables) -> load (SQLite)
app.py            # Dash layout + callback, SQL queries, Plotly figures
assets/style.css  # styling
```

## Next steps
- Swap SQLite for Postgres and schedule `etl.py` (cron / Airflow)
- Add Western Electric rules to the SPC chart (e.g., runs of 8 points on one side of the mean)
- Add drill-down: click a Pareto bar to filter the other charts
