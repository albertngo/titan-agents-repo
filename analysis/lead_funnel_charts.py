#!/usr/bin/env python3
"""Render the three lead-funnel charts from analysis/output/lead_stats.json.

Palette: RiderBlue-led categorical set, validated with the dataviz skill's
validate_palette.js (4 hues pass all six checks on light surface); "Other" is a
deliberately-recessive neutral outside the categorical set. One axis per chart,
recessive grid, thin marks, direct labels only where they earn their place.

Usage: python analysis/lead_funnel_charts.py
"""

import json
from datetime import date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

OUT = Path(__file__).resolve().parent / "output"
stats = json.loads((OUT / "lead_stats.json").read_text())

BLUE, ORANGE, TEAL, PURPLE = "#1e6fff", "#e8710a", "#00a38d", "#8c4fd6"
NEUTRAL = "#9aa1ab"          # "Other"/overflow — recessive by design
INK, MUTED, GRID = "#1f2937", "#6b7280", "#e5e7eb"
SURFACE = "#ffffff"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
    "text.color": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10, "figure.dpi": 150,
})

days = sorted(stats["by_day"])
d0, d1 = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
all_days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
labels = [d.isoformat() for d in all_days]
proj = [stats["by_day"].get(l, {}).get("project", 0) for l in labels]
store = [stats["by_day"].get(l, {}).get("store", 0) for l in labels]
total = [p + s for p, s in zip(proj, store)]


def rolling7(xs):
    out = []
    for i in range(len(xs)):
        w = xs[max(0, i - 6):i + 1]
        out.append(sum(w) / len(w))
    return out


def style_dates(ax):
    ticks = list(range(0, len(all_days), 7))
    ax.set_xticks(ticks)
    ax.set_xticklabels([all_days[i].strftime("%b %d") for i in ticks])
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_axisbelow(True)
    ax.grid(axis="x", visible=False)


# ---- 1. Trend: daily leads + 7-day average ----
fig, ax = plt.subplots(figsize=(9.5, 4.2))
x = range(len(all_days))
ax.bar(x, proj, width=0.72, color=BLUE, label="Project leads", zorder=2)
ax.bar(x, store, width=0.72, bottom=proj, color=ORANGE, label="Store leads", zorder=2)
ax.plot(x, rolling7(total), color=INK, linewidth=2, label="7-day avg (all)", zorder=3)
style_dates(ax)
ax.legend(frameon=False, loc="upper left")
ax.set_title(f"New leads per day — last {stats['window_days']} days "
             f"({stats['total_leads']} total)", loc="left", fontsize=12, color=INK)
fig.tight_layout()
fig.savefig(OUT / "chart1_lead_trend.png")

# ---- 2. Booked appointments by source ----
srcs = sorted(stats["by_source"].items(), key=lambda kv: -kv[1]["appts"])
names = [k for k, _ in srcs]
appts = [v["appts"] for _, v in srcs]
leads = [v["leads"] for _, v in srcs]
colors = [NEUTRAL if n in ("Other", "Unknown") else BLUE for n in names]

fig, ax = plt.subplots(figsize=(9.5, 4.6))
y = range(len(names))[::-1]
ax.barh(y, leads, height=0.62, color=GRID, zorder=2, label="Leads")
ax.barh(y, appts, height=0.62, color=colors, zorder=3, label="Booked appointments")
for yi, a, l in zip(y, appts, leads):
    ax.text(l + 1.5, yi, f"{a}/{l} ({a/l:.0%})" if l else "0",
            va="center", fontsize=9, color=MUTED)
ax.set_yticks(list(y))
ax.set_yticklabels(names, color=INK)
ax.xaxis.set_major_locator(MaxNLocator(integer=True))
ax.set_axisbelow(True)
ax.grid(axis="y", visible=False)
ax.legend(frameon=False, loc="lower right")
ax.set_xlim(0, max(leads) * 1.22)
ax.set_title(f"Booked appointments by lead source — last {stats['window_days']} days",
             loc="left", fontsize=12, color=INK)
fig.tight_layout()
fig.savefig(OUT / "chart2_appts_by_source.png")

# ---- 3. Daily leads by source (top 4 + Other) ----
by_ds = stats["by_day_source"]
top = [k for k, _ in sorted(stats["by_source"].items(), key=lambda kv: -kv[1]["leads"])
       if k not in ("Other", "Unknown")][:4]
series = {}
for name in top:
    series[name] = [by_ds.get(l, {}).get(name, 0) for l in labels]
series["Other"] = [sum(v for k, v in by_ds.get(l, {}).items() if k not in top)
                   for l in labels]
palette = {top[i]: c for i, c in enumerate([BLUE, ORANGE, TEAL, PURPLE][:len(top)])}
palette["Other"] = NEUTRAL

fig, ax = plt.subplots(figsize=(9.5, 4.6))
bottom = [0] * len(all_days)
for name in top + ["Other"]:
    ax.bar(x, series[name], width=0.72, bottom=bottom, color=palette[name],
           label=name, zorder=2, edgecolor=SURFACE, linewidth=0.4)
    bottom = [b + v for b, v in zip(bottom, series[name])]
style_dates(ax)
ax.legend(frameon=False, loc="upper left", ncols=len(top) + 1)
ax.set_title(f"Daily leads by source — last {stats['window_days']} days",
             loc="left", fontsize=12, color=INK)
fig.tight_layout()
fig.savefig(OUT / "chart3_daily_by_source.png")

print("wrote", *(f"chart{i}" for i in (1, 2, 3)))
