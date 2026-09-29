"""
Production Quality Dashboard (Dash + Plotly + SQLite)

- KPI tiles: units inspected, defects, defect rate (DPU %), first-pass yield
- p-chart (SPC) of daily defect rate with 3-sigma control limits
- Pareto of defect types
- Defect rate heatmap by line x shift

Run:  python etl.py && python app.py   ->  http://127.0.0.1:8050
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html

DB_PATH = Path(__file__).with_name("quality.db")
if not DB_PATH.exists():
    import etl
    etl.load(*etl.transform(etl.extract()))

INK, MUTED, GRID = "#1f2937", "#6b7280", "#e5e7eb"
ACCENT, ALERT, OK = "#2563eb", "#dc2626", "#16a34a"


def query(sql: str, params=()) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query(sql, con, params=params)


LINES = query("SELECT DISTINCT line FROM production ORDER BY line")["line"].tolist()
DATES = query("SELECT MIN(date) lo, MAX(date) hi FROM production").iloc[0]


def where(lines, start, end):
    ph = ",".join("?" * len(lines))
    return f"line IN ({ph}) AND date BETWEEN ? AND ?", [*lines, start, end]


def base_layout(fig, title):
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=INK), x=0, xanchor="left"),
        margin=dict(l=50, r=20, t=50, b=40),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="Inter, Segoe UI, sans-serif", color=INK, size=12),
        hoverlabel=dict(bgcolor="white"),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def kpi(label, value, color=INK):
    return html.Div(className="kpi", children=[
        html.Div(label, className="kpi-label"),
        html.Div(value, className="kpi-value", style={"color": color}),
    ])


app = Dash(__name__, title="Quality Dashboard")
server = app.server  # for gunicorn deployment

app.layout = html.Div(className="page", children=[
    html.Div(className="header", children=[
        html.H1("Production Quality Dashboard"),
        html.P("End-of-line inspection results · synthetic demo data"),
    ]),
    html.Div(className="filters", children=[
        html.Div([html.Label("Production lines"),
                  dcc.Dropdown(LINES, LINES, id="lines", multi=True, clearable=False)],
                 style={"flex": 2}),
        html.Div([html.Label("Date range"),
                  dcc.DatePickerRange(id="dates", start_date=DATES.lo, end_date=DATES.hi,
                                      min_date_allowed=DATES.lo, max_date_allowed=DATES.hi,
                                      display_format="DD MMM YYYY")],
                 style={"flex": 1}),
    ]),
    html.Div(id="kpis", className="kpis"),
    html.Div(id="alert"),
    dcc.Graph(id="spc", config={"displayModeBar": False}),
    html.Div(className="row", children=[
        dcc.Graph(id="pareto", config={"displayModeBar": False}, style={"flex": 1}),
        dcc.Graph(id="heatmap", config={"displayModeBar": False}, style={"flex": 1}),
    ]),
])


@app.callback(
    Output("kpis", "children"), Output("alert", "children"),
    Output("spc", "figure"), Output("pareto", "figure"), Output("heatmap", "figure"),
    Input("lines", "value"), Input("dates", "start_date"), Input("dates", "end_date"),
)
def update(lines, start, end):
    lines = lines or LINES
    w, p = where(lines, start[:10], end[:10])

    # ---- daily p-chart data (SQL does the aggregation) --------------------
    daily = query(f"""
        SELECT p.date, p.inspected, COALESCE(d.defects, 0) AS defects
        FROM (SELECT date, SUM(inspected) inspected FROM production WHERE {w} GROUP BY date) p
        LEFT JOIN (SELECT date, SUM(count) defects FROM defects WHERE {w} GROUP BY date) d
        USING (date) ORDER BY p.date""", p + p)
    daily["rate"] = daily.defects / daily.inspected

    # Control limits from the first half of the window (baseline period)
    base = daily.iloc[: max(len(daily) // 2, 1)]
    pbar = base.defects.sum() / base.inspected.sum()
    sigma = np.sqrt(pbar * (1 - pbar) / daily.inspected)
    daily["ucl"] = pbar + 3 * sigma
    daily["lcl"] = (pbar - 3 * sigma).clip(lower=0)
    out = daily[daily.rate > daily.ucl]

    # ---- KPIs --------------------------------------------------------------
    total_insp, total_def = int(daily.inspected.sum()), int(daily.defects.sum())
    rate = total_def / total_insp if total_insp else 0
    kpis = [
        kpi("Units inspected", f"{total_insp:,}"),
        kpi("Defects found", f"{total_def:,}"),
        kpi("Defect rate", f"{rate:.2%}", ALERT if rate > pbar * 1.2 else INK),
        kpi("Out-of-control days", f"{len(out)}", ALERT if len(out) else OK),
    ]
    alert = (html.Div(className="alert", children=(
        f"⚠ {len(out)} day(s) above the upper control limit, latest on {out.date.iloc[-1]}. "
        "Check the Pareto and heatmap to see which line/defect drives it."))
        if len(out) else None)

    # ---- SPC chart ---------------------------------------------------------
    spc = go.Figure()
    spc.add_scatter(x=daily.date, y=daily.ucl, mode="lines", line=dict(color=MUTED, dash="dash", width=1),
                    hovertemplate="UCL %{y:.2%}<extra></extra>")
    spc.add_scatter(x=daily.date, y=daily.lcl, mode="lines", line=dict(color=MUTED, dash="dash", width=1),
                    hovertemplate="LCL %{y:.2%}<extra></extra>")
    spc.add_hline(y=pbar, line=dict(color=MUTED, width=1),
                  annotation_text=f"p̄ = {pbar:.2%}", annotation_position="top left")
    spc.add_scatter(x=daily.date, y=daily.rate, mode="lines+markers",
                    line=dict(color=ACCENT, width=2), marker=dict(size=5),
                    hovertemplate="%{x}<br>Defect rate %{y:.2%}<extra></extra>")
    spc.add_scatter(x=out.date, y=out.rate, mode="markers",
                    marker=dict(color=ALERT, size=10, line=dict(color="white", width=1.5)),
                    hovertemplate="%{x}<br>OUT OF CONTROL %{y:.2%}<extra></extra>")
    base_layout(spc, "Daily defect rate — p-chart with 3σ control limits")
    spc.update_yaxes(tickformat=".1%")
    spc.update_layout(height=340)

    # ---- Pareto ------------------------------------------------------------
    par = query(f"""SELECT line || ' · ' || defect AS defect, SUM(count) n FROM defects
                    WHERE {w} GROUP BY line, defect ORDER BY n DESC LIMIT 10""", p)
    par["cum"] = par.n.cumsum() / par.n.sum()
    pareto = go.Figure()
    pareto.add_bar(x=par.defect, y=par.n, marker_color=ACCENT,
                   hovertemplate="%{x}<br>%{y} defects<extra></extra>")
    pareto.add_scatter(x=par.defect, y=par.cum, yaxis="y2", mode="lines+markers",
                       line=dict(color=INK, width=1.5), marker=dict(size=5),
                       hovertemplate="Cumulative %{y:.0%}<extra></extra>")
    base_layout(pareto, "Top 10 defects (Pareto)")
    pareto.update_layout(height=380, yaxis2=dict(overlaying="y", side="right", range=[0, 1.05],
                                                 tickformat=".0%", dtick=0.25, showgrid=False))
    pareto.update_xaxes(tickangle=-35, tickfont=dict(size=10))

    # ---- Heatmap line x shift ---------------------------------------------
    hm = query(f"""
        SELECT p.line, p.shift, SUM(p.inspected) inspected, COALESCE(SUM(d.n), 0) defects
        FROM production p
        LEFT JOIN (SELECT date, line, shift, SUM(count) n FROM defects GROUP BY date, line, shift) d
        USING (date, line, shift)
        WHERE {w}
        GROUP BY p.line, p.shift""", p)
    hm["rate"] = hm.defects / hm.inspected
    grid = hm.pivot(index="line", columns="shift", values="rate").reindex(columns=["Early", "Late", "Night"])
    heat = go.Figure(go.Heatmap(
        z=grid.values, x=grid.columns, y=grid.index, colorscale="Blues",
        text=[[f"{v:.2%}" for v in row] for row in grid.values], texttemplate="%{text}",
        hovertemplate="%{y} · %{x} shift<br>Defect rate %{z:.2%}<extra></extra>",
        colorbar=dict(tickformat=".1%", thickness=10)))
    base_layout(heat, "Defect rate by line × shift")
    heat.update_layout(height=380)

    return kpis, alert, spc, pareto, heat


if __name__ == "__main__":
    app.run(debug=True)
