"""
Visualization: renders exchange-rate dynamics charts from the gold
table and saves them as .jpg files under CHARTS_ROOT.

Colors are assigned per currency from a fixed, colorblind-validated
categorical order (see CURRENCY_COLORS) and never depend on filtering
or sort order, so a given currency always reads as the same color
across every chart.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Fixed categorical order (blue, orange, aqua, violet) - validated as
# colorblind-safe for all-pairs use (small multiples + overlay) via
# the dataviz skill's palette validator.
CURRENCY_COLORS = {
    "EUR": "#2a78d6",
    "USD": "#eb6834",
    "GBP": "#1baf7a",
    "JPY": "#4a3aa7",
}

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"


def _style_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRIDLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(BASELINE)
    ax.tick_params(colors=INK_MUTED, labelsize=9)
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))


def plot_dynamics_by_currency(gold: pd.DataFrame, out_path: Path) -> Path:
    """Small multiples: one line-chart subplot per currency, its own y-scale."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), facecolor=SURFACE)
    fig.suptitle("PLN exchange rate dynamics (NBP mid rate)", color=INK_PRIMARY, fontsize=14, fontweight="bold")

    for ax, currency in zip(axes.flat, config.TARGET_CURRENCIES):
        series = gold[gold["currency"] == currency].sort_values("date")
        ax.plot(series["date"], series["mid"], color=CURRENCY_COLORS[currency], linewidth=1.8)
        ax.set_title(f"PLN/{currency}", color=INK_PRIMARY, fontsize=11, loc="left")
        ax.set_ylabel("PLN", color=INK_SECONDARY, fontsize=9)
        _style_axes(ax)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, format="jpg", dpi=150)
    plt.close(fig)
    logger.info("Saved %s", out_path)
    return out_path


def plot_dynamics_indexed(gold: pd.DataFrame, out_path: Path) -> Path:
    """Overlay all four currencies on one axis, indexed to 100 at their first observation."""
    fig, ax = plt.subplots(figsize=(11, 6), facecolor=SURFACE)

    for currency in config.TARGET_CURRENCIES:
        series = gold[gold["currency"] == currency].sort_values("date")
        valid = series.dropna(subset=["mid"])
        if valid.empty:
            logger.warning("No mid-rate data for %s, skipping it in the indexed chart", currency)
            continue

        base = valid["mid"].iloc[0]
        indexed = series["mid"] / base * 100
        color = CURRENCY_COLORS[currency]
        ax.plot(series["date"], indexed, color=color, linewidth=2, label=currency)

        last_valid = valid.iloc[-1]
        ax.text(
            last_valid["date"], last_valid["mid"] / base * 100, f" {currency}",
            color=color, fontsize=9, fontweight="bold", va="center",
        )

    ax.set_title(
        "Relative dynamics vs PLN (indexed to 100 at first observation)",
        color=INK_PRIMARY, fontsize=13, loc="left",
    )
    ax.set_ylabel("Index (start = 100)", color=INK_SECONDARY)
    ax.legend(loc="upper left", frameon=False, labelcolor=INK_SECONDARY)
    _style_axes(ax)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, format="jpg", dpi=150)
    plt.close(fig)
    logger.info("Saved %s", out_path)
    return out_path


def _read_gold_table() -> pd.DataFrame:
    gold_path = config.GOLD_ROOT / "rates.parquet"
    if not gold_path.exists():
        raise FileNotFoundError(
            f"Gold table not found at {gold_path} - run ingest_gold.py "
            "(or ingest_gold.build_gold_table()) first."
        )
    return pd.read_parquet(gold_path)


def build_charts() -> List[Path]:
    gold = _read_gold_table()

    return [
        plot_dynamics_by_currency(gold, config.CHARTS_ROOT / "dynamics_by_currency.jpg"),
        plot_dynamics_indexed(gold, config.CHARTS_ROOT / "dynamics_indexed.jpg"),
    ]


def compute_insights(gold: pd.DataFrame) -> pd.DataFrame:
    """One summary row per currency: extremes of level and of daily % change.

    A currency with no mid-rate data at all is skipped (with a warning)
    rather than crashing idxmin/idxmax on an empty/all-NaN series. A
    currency with fewer than two data points has no day-over-day change
    to compare, so its fall/rise fields are left as None.
    """
    rows = []
    for currency in config.TARGET_CURRENCIES:
        series = gold[gold["currency"] == currency].sort_values("date").reset_index(drop=True)

        if series["mid"].notna().sum() == 0:
            logger.warning("No mid-rate data for %s, skipping its insights", currency)
            continue

        min_idx = series["mid"].idxmin()
        max_idx = series["mid"].idxmax()

        row = {
            "currency": currency,
            "lowest_value": series.loc[min_idx, "mid"],
            "lowest_value_date": series.loc[min_idx, "date"],
            "highest_value": series.loc[max_idx, "mid"],
            "highest_value_date": series.loc[max_idx, "date"],
        }

        if series["daily_change_pct"].notna().sum() == 0:
            logger.warning(
                "Not enough data points for %s to compute a daily change, "
                "skipping its fall/rise insights", currency,
            )
            row.update(
                biggest_one_day_fall_pct=None, biggest_one_day_fall_date=None,
                biggest_one_day_rise_pct=None, biggest_one_day_rise_date=None,
            )
        else:
            fall_idx = series["daily_change_pct"].idxmin()
            rise_idx = series["daily_change_pct"].idxmax()
            row.update(
                biggest_one_day_fall_pct=series.loc[fall_idx, "daily_change_pct"],
                biggest_one_day_fall_date=series.loc[fall_idx, "date"],
                biggest_one_day_rise_pct=series.loc[rise_idx, "daily_change_pct"],
                biggest_one_day_rise_date=series.loc[rise_idx, "date"],
            )

        rows.append(row)

    return pd.DataFrame(rows)


def print_insights(insights: pd.DataFrame) -> None:
    if insights.empty:
        print("No insights available - no data found for the target currencies.")
        return

    for _, row in insights.iterrows():
        print(f"\n{row['currency']}/PLN")
        print(f"  Highest depreciation vs PLN (lowest rate):  {row['lowest_value']:.4f} PLN on {row['lowest_value_date'].date()}")
        print(f"  Highest appreciation vs PLN (highest rate): {row['highest_value']:.4f} PLN on {row['highest_value_date'].date()}")
        if row["biggest_one_day_fall_date"] is None:
            print("  Biggest one-day fall:  not enough data")
            print("  Biggest one-day rise:  not enough data")
        else:
            print(f"  Biggest one-day fall:  {row['biggest_one_day_fall_pct']:+.2f}% on {row['biggest_one_day_fall_date'].date()}")
            print(f"  Biggest one-day rise:  {row['biggest_one_day_rise_pct']:+.2f}% on {row['biggest_one_day_rise_date'].date()}")


def run() -> None:
    gold = _read_gold_table()
    plot_dynamics_by_currency(gold, config.CHARTS_ROOT / "dynamics_by_currency.jpg")
    plot_dynamics_indexed(gold, config.CHARTS_ROOT / "dynamics_indexed.jpg")
    print_insights(compute_insights(gold))


if __name__ == "__main__":
    run()
