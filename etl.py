"""
Tiny ETL: generate synthetic end-of-line inspection data for a car plant,
clean it, and load it into SQLite so the dashboard reads it with SQL.

Run:  python etl.py
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DB_PATH = Path(__file__).with_name("quality.db")

LINES = ["Body-in-White", "Paint", "General Assembly", "Drive Unit"]
SHIFTS = ["Early", "Late", "Night"]
DEFECTS = {
    "Body-in-White": ["Weld spatter", "Panel gap", "Dent", "Missing rivet"],
    "Paint": ["Orange peel", "Dirt inclusion", "Run/sag", "Color mismatch"],
    "General Assembly": ["Loose connector", "Missing clip", "Scratch", "Torque NOK"],
    "Drive Unit": ["Oil leak", "Noise/vibration", "Torque NOK", "Sensor fault"],
}
BASE_RATE = {"Body-in-White": 0.020, "Paint": 0.045, "General Assembly": 0.030, "Drive Unit": 0.015}


def extract(days: int = 60, seed: int = 7) -> pd.DataFrame:
    """Simulate raw per-shift inspection records (the 'source system')."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=days, freq="D")
    rows = []
    for d in dates:
        for line in LINES:
            for shift in SHIFTS:
                inspected = int(rng.normal(420, 35))
                rate = BASE_RATE[line] * (1.25 if shift == "Night" else 1.0)
                # Inject a process issue: Paint drifts upward in the last 10 days
                if line == "Paint" and d >= dates[-10]:
                    rate *= 1.8
                n_def = rng.binomial(inspected, rate)
                weights = rng.dirichlet([6, 3, 2, 1])
                codes = rng.choice(DEFECTS[line], size=n_def, p=weights)
                for code in codes:
                    rows.append((d, line, shift, inspected, code))
                if n_def == 0:
                    rows.append((d, line, shift, inspected, None))
    return pd.DataFrame(rows, columns=["date", "line", "shift", "inspected", "defect"])


def transform(raw: pd.DataFrame):
    """Split into a production fact table and a defect fact table."""
    production = (
        raw[["date", "line", "shift", "inspected"]]
        .drop_duplicates()
        .assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d"))
    )
    defects = (
        raw.dropna(subset=["defect"])
        .groupby(["date", "line", "shift", "defect"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
        .assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d"))
    )
    return production, defects


def load(production: pd.DataFrame, defects: pd.DataFrame) -> None:
    with sqlite3.connect(DB_PATH) as con:
        production.to_sql("production", con, if_exists="replace", index=False)
        defects.to_sql("defects", con, if_exists="replace", index=False)
        con.execute("CREATE INDEX IF NOT EXISTS ix_prod ON production(date, line)")
        con.execute("CREATE INDEX IF NOT EXISTS ix_def ON defects(date, line)")


if __name__ == "__main__":
    prod, defs = transform(extract())
    load(prod, defs)
    print(f"Loaded {len(prod)} production rows and {len(defs)} defect rows into {DB_PATH.name}")
