# src/summary_stats.py
import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def compute_summary_stats(trades_df, monthly_df):
    rows = []

    def add(metric, value):
        rows.append({"metric": metric, "value": value})

    closed = trades_df[trades_df["status"] == "CLOSED"]
    up = closed[closed["direction"] == "UP"]
    down = closed[closed["direction"] == "DOWN"]

    add("Total flips (closed)", len(closed))
    add("UP flips", len(up))
    add("DOWN flips", len(down))

    duration_days = closed["duration"].dt.total_seconds() / 86400
    add("Avg duration (days)", round(duration_days.mean(), 1))
    add("Median duration (days)", round(duration_days.median(), 1))
    add("Longest duration (days)", round(duration_days.max(), 1))
    add("Shortest duration (days)", round(duration_days.min(), 1))
    add("75th percentile duration (days)", round(duration_days.quantile(0.75), 1))
    add("90th percentile duration (days)", round(duration_days.quantile(0.90), 1))

    within_month = (duration_days <= 30).sum()
    beyond_month = (duration_days > 30).sum()
    add("Flips completed within ~30 days", within_month)
    add("Flips running longer than ~30 days", beyond_month)
    add("% completed within a monthly cycle", round(within_month / len(closed) * 100, 1))

    add("Avg pct_move (all)", round(closed["pct_move"].mean(), 2))
    add("Avg pct_move (UP)", round(up["pct_move"].mean(), 2))
    add("Avg pct_move (DOWN)", round(down["pct_move"].mean(), 2))
    add("Biggest single pct_move", round(closed["pct_move"].abs().max(), 2))
    add("Win rate % (pct_move > 0)", round((closed["pct_move"] > 0).mean() * 100, 1))

    add("Avg max_adverse_pct (all)", round(closed["max_adverse_pct"].mean(), 2))
    add("Median max_adverse_pct", round(closed["max_adverse_pct"].median(), 2))
    add("Worst max_adverse_pct (4yr)", round(closed["max_adverse_pct"].max(), 2))
    add("Flips with adverse move > 5%", int((closed["max_adverse_pct"] > 5).sum()))
    add("Flips with adverse move > 10%", int((closed["max_adverse_pct"] > 10).sum()))

    add("Avg max_gap_against_pct", round(closed["max_gap_against_pct"].mean(), 2))
    add("Worst single gap (4yr)", round(closed["max_gap_against_pct"].max(), 2))

    # Single-DAY move risk. The gap metrics above only see the overnight
    # jump (open vs previous close), which turns out to miss most of what a
    # bad day actually does — PIIND's 8.97% fall on 2026-08-12 was only a
    # 1.28% gap, the rest intraday, so nothing in the scoring saw it. These
    # measure the full close-to-close day. Guarded so summaries can still be
    # built from reports generated before the column existed.
    if "worst_day_against_pct" in closed.columns:
        add("Avg worst_day_against_pct", round(closed["worst_day_against_pct"].mean(), 2))
        add("Worst single-day move against (4yr)", round(closed["worst_day_against_pct"].max(), 2))
        add("Flips with a day >4% against", int((closed["worst_day_against_pct"] > 4).sum()))
    if "born_on_outlier_day" in closed.columns:
        add("Flips born on an outlier day", int(closed["born_on_outlier_day"].fillna(False).sum()))

    add("Avg monthly range_pct", round(monthly_df["range_pct"].mean(), 2))
    add("Median monthly range_pct", round(monthly_df["range_pct"].median(), 2))
    add("Smallest monthly range_pct", round(monthly_df["range_pct"].min(), 2))
    add("Largest monthly range_pct", round(monthly_df["range_pct"].max(), 2))
    add("75th percentile monthly range_pct", round(monthly_df["range_pct"].quantile(0.75), 2))
    add("90th percentile monthly range_pct", round(monthly_df["range_pct"].quantile(0.90), 2))

    add("Avg monthly up_move_pct", round(monthly_df["up_move_pct"].mean(), 2))
    add("Avg monthly down_move_pct", round(monthly_df["down_move_pct"].mean(), 2))
    add("Largest single up_move_pct", round(monthly_df["up_move_pct"].max(), 2))
    add("Largest single down_move_pct", round(monthly_df["down_move_pct"].max(), 2))
    add("75th percentile up_move_pct", round(monthly_df["up_move_pct"].quantile(0.75), 2))
    add("75th percentile down_move_pct", round(monthly_df["down_move_pct"].quantile(0.75), 2))

    return pd.DataFrame(rows)

def save_summary(summary_df, symbol):
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    path = os.path.join(EXPORTS_DIR, f"{symbol}_summary.csv")
    summary_df.to_csv(path, index=False)
    print(f"Saved summary to {path}")
    return path