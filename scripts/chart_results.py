#!/usr/bin/env python3
"""Generate SVG charts from mass_warlords simulation CSV output."""

import csv
import json
import sys
from pathlib import Path


def generate_survivor_chart(turns_csv: str, output_path: str) -> None:
    """Generate survivors-over-time chart as SVG."""
    turns, survivors = [], []
    with open(turns_csv) as f:
        reader = csv.DictReader(f)
        for row in reader:
            turns.append(int(row["turn"]))
            survivors.append(int(row["active_factions"]))

    # SVG dimensions
    w, h = 800, 400
    margin = {"top": 40, "right": 30, "bottom": 60, "left": 60}
    plot_w = w - margin["left"] - margin["right"]
    plot_h = h - margin["top"] - margin["bottom"]

    x_min, x_max = turns[0], turns[-1]
    y_min, y_max = 0, survivors[0]

    def x(t):
        return margin["left"] + (t - x_min) / (x_max - x_min) * plot_w

    def y(s):
        return margin["top"] + plot_h - (s - y_min) / (y_max - y_min) * plot_h

    # Build path
    path_d = f"M {x(turns[0])} {y(survivors[0])}"
    for t, s in zip(turns[1:], survivors[1:]):
        path_d += f" L {x(t)} {y(s)}"

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <style>
    text {{ font-family: 'Segoe UI', sans-serif; }}
    .title {{ font-size: 18px; font-weight: bold; fill: #e0e0e0; }}
    .label {{ font-size: 11px; fill: #999; }}
    .axis {{ stroke: #444; stroke-width: 1; }}
    .grid {{ stroke: #333; stroke-width: 0.5; stroke-dasharray: 4; }}
  </style>
  <rect width="{w}" height="{h}" fill="#1a1a2e"/>

  <!-- Title -->
  <text class="title" x="{w/2}" y="25" text-anchor="middle">Active Factions Over Time</text>

  <!-- Grid lines -->
'''
    for i in range(0, survivors[0] + 1, 5):
        yi = y(i)
        svg += f'  <line class="grid" x1="{margin["left"]}" y1="{yi}" x2="{w - margin["right"]}" y2="{yi}"/>\n'
        svg += f'  <text class="label" x="{margin["left"] - 8}" y="{yi + 4}" text-anchor="end">{i}</text>\n'

    for t in range(x_min, x_max + 1, 10):
        xi = x(t)
        svg += f'  <line class="grid" x1="{xi}" y1="{margin["top"]}" x2="{xi}" y2="{h - margin["bottom"]}"/>\n'
        svg += f'  <text class="label" x="{xi}" y="{h - margin["bottom"] + 20}" text-anchor="middle">T{t}</text>\n'

    # Data line
    svg += f'  <path d="{path_d}" fill="none" stroke="#00d4aa" stroke-width="2.5"/>\n'

    # End dots
    svg += f'  <circle cx="{x(turns[-1])}" cy="{y(survivors[-1])}" r="5" fill="#00d4aa"/>\n'
    svg += f'  <text class="label" fill="#00d4aa" x="{x(turns[-1]) + 10}" y="{y(survivors[-1]) + 5}">{survivors[-1]} factions</text>\n'

    svg += '</svg>'

    with open(output_path, "w") as f:
        f.write(svg)
    print(f"Survivor chart saved: {output_path}")


def generate_territory_chart(factions_csv: str, output_path: str) -> None:
    """Generate territory accumulation chart for top factions."""
    # Aggregate territory count per faction per turn
    from collections import defaultdict

    faction_terrs: dict[str, dict[int, int]] = defaultdict(dict)
    with open(factions_csv) as f:
        reader = csv.DictReader(f)
        for row in reader:
            turn = int(row["turn"])
            fid = row["faction_id"]
            terrs = int(row["territories"])
            faction_terrs[fid][turn] = terrs

    # Select top factions by max territories
    top = sorted(
        faction_terrs.items(),
        key=lambda x: max(x[1].values()),
        reverse=True,
    )[:8]

    w, h = 800, 420
    margin = {"top": 40, "right": 160, "bottom": 60, "left": 60}
    plot_w = w - margin["left"] - margin["right"]
    plot_h = h - margin["top"] - margin["bottom"]

    colors = ["#00d4aa", "#ff6b6b", "#ffd93d", "#6c5ce7", "#a29bfe", "#fd79a8", "#00b894", "#e17055"]

    # Gather all turns
    all_turns = sorted({t for f in faction_terrs.values() for t in f})
    x_min, x_max = min(all_turns), max(all_turns)
    y_max = max(max(f.values()) for f in faction_terrs.values())

    def x(t):
        return margin["left"] + (t - x_min) / (x_max - x_min) * plot_w

    def y(v):
        return margin["top"] + plot_h - (v / y_max * plot_h)

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <style>
    text {{ font-family: 'Segoe UI', sans-serif; }}
    .title {{ font-size: 18px; font-weight: bold; fill: #e0e0e0; }}
    .label {{ font-size: 11px; fill: #999; }}
    .axis {{ stroke: #444; stroke-width: 1; }}
    .grid {{ stroke: #333; stroke-width: 0.5; stroke-dasharray: 4; }}
    .legend {{ font-size: 12px; }}
  </style>
  <rect width="{w}" height="{h}" fill="#1a1a2e"/>

  <text class="title" x="{w/2}" y="25" text-anchor="middle">Territory Accumulation — Top Factions</text>
'''

    # Grid
    for i in range(0, int(y_max) + 1, 5):
        yi = y(i)
        svg += f'  <line class="grid" x1="{margin["left"]}" y1="{yi}" x2="{w - margin["right"]}" y2="{yi}"/>\n'
        svg += f'  <text class="label" x="{margin["left"] - 8}" y="{yi + 4}" text-anchor="end">{i}</text>\n'

    for t in range(x_min, x_max + 1, 20):
        xi = x(t)
        svg += f'  <text class="label" x="{xi}" y="{h - margin["bottom"] + 20}" text-anchor="middle">T{t}</text>\n'

    # Data lines
    for i, (fid, turns_data) in enumerate(top):
        sorted_turns = sorted(turns_data.items())
        color = colors[i % len(colors)]
        # Get faction name
        fid_name = fid  # fallback

        d = ""
        prev_t, prev_v = sorted_turns[0]
        d = f"M {x(prev_t)} {y(prev_v)}"
        for t, v in sorted_turns[1:]:
            d += f" L {x(t)} {y(v)}"
        svg += f'  <path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>\n'

        # Label
        last_t, last_v = sorted_turns[-1]
        svg += f'  <text class="legend" fill="{color}" x="{x(last_t) + 5}" y="{y(last_v) + 4}">{fid} ({last_v})</text>\n'

    svg += '</svg>'

    with open(output_path, "w") as f:
        f.write(svg)
    print(f"Territory chart saved: {output_path}")


def generate_gini_chart(turns_csv: str, output_path: str) -> None:
    """Generate Gini coefficient chart."""
    turns, ginis = [], []
    with open(turns_csv) as f:
        reader = csv.DictReader(f)
        for row in reader:
            turns.append(int(row["turn"]))
            ginis.append(float(row["gini_strength"]))

    w, h = 800, 350
    margin = {"top": 40, "right": 30, "bottom": 60, "left": 60}
    plot_w = w - margin["left"] - margin["right"]
    plot_h = h - margin["top"] - margin["bottom"]

    def x(t):
        return margin["left"] + (t - turns[0]) / (turns[-1] - turns[0]) * plot_w

    def y(g):
        return margin["top"] + plot_h - (g / 1.0 * plot_h)

    path_d = f"M {x(turns[0])} {y(ginis[0])}"
    for t, g in zip(turns[1:], ginis[1:]):
        path_d += f" L {x(t)} {y(g)}"

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <style>
    text {{ font-family: 'Segoe UI', sans-serif; }}
    .title {{ font-size: 18px; font-weight: bold; fill: #e0e0e0; }}
    .label {{ font-size: 11px; fill: #999; }}
  </style>
  <rect width="{w}" height="{h}" fill="#1a1a2e"/>
  <text class="title" x="{w/2}" y="25" text-anchor="middle">Power Concentration (Gini Coefficient)</text>
'''
    # Grid
    for gv in [0.0, 0.25, 0.5, 0.75, 1.0]:
        yi = y(gv)
        svg += f'  <line class="grid" x1="{margin["left"]}" y1="{yi}" x2="{w - margin["right"]}" y2="{yi}" stroke="#333" stroke-width="0.5" stroke-dasharray="4"/>\n'
        svg += f'  <text class="label" x="{margin["left"] - 8}" y="{yi + 4}" text-anchor="end">{gv:.2f}</text>\n'

    svg += f'  <path d="{path_d}" fill="none" stroke="#ffd93d" stroke-width="2.5"/>\n'
    svg += f'  <text class="label" fill="#ffd93d" x="{x(turns[-1]) + 10}" y="{y(ginis[-1]) + 4}">{ginis[-1]:.3f}</text>\n'
    svg += '</svg>'

    with open(output_path, "w") as f:
        f.write(svg)
    print(f"Gini chart saved: {output_path}")


def print_summary(turns_csv: str, factions_csv: str, final_json: str) -> None:
    """Print a human-readable summary."""
    with open(turns_csv) as f:
        rows = list(csv.DictReader(f))

    first, last = rows[0], rows[-1]
    print(f"\n=== SIMULATION SUMMARY ===")
    print(f"Turns: {len(rows)}")
    print(f"Survivors: {first['active_factions']} → {last['active_factions']}")
    print(f"Gini coefficient: {first['gini_strength']} → {last['gini_strength']}")

    with open(final_json) as f:
        final = json.load(f)

    # Count conquered
    active = [fid for fid, data in final.items() if data["is_active"] and data["strength"] > 0]
    eliminated = [fid for fid, data in final.items() if not data["is_active"] or data["strength"] <= 0]
    print(f"Active factions: {len(active)}")
    if eliminated:
        print(f"Eliminated: {', '.join(eliminated[:10])}{'...' if len(eliminated) > 10 else ''}")

    # Top 5
    top5 = sorted(final.items(), key=lambda x: x[1]["territories"], reverse=True)[:5]
    print("Top 5 by territories:")
    for fid, data in top5:
        print(f"  {fid:15s} {data['name']:10s} terrs={data['territories']} str={data['strength']}")


if __name__ == "__main__":
    prefix = sys.argv[1] if len(sys.argv) > 1 else "results/mass_warlords"

    print_summary(f"{prefix}_turns.csv", f"{prefix}_factions.csv", f"{prefix}_final.json")
    generate_survivor_chart(f"{prefix}_turns.csv", f"{prefix}_survivors.svg")
    generate_territory_chart(f"{prefix}_factions.csv", f"{prefix}_territories.svg")
    generate_gini_chart(f"{prefix}_turns.csv", f"{prefix}_gini.svg")
    print("\nDone!")
