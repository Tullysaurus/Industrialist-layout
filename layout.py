#!/usr/bin/env python3
"""Industrialist factory footprint optimizer.

Usage:
    python layout.py "8CPP-final_(Imported)_save.json" --time 240
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from indlayout.model import load_problem
from indlayout.optimize import optimize
from indlayout.render import export_json, render_svg, write_report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pack the machines of a planner save into the smallest area, "
                                             "with room for pipes/conveyors.")
    ap.add_argument("save", help="planner save file (.json)")
    ap.add_argument("--machines", default="machines.json")
    ap.add_argument("--recipes", default="recipes.json")
    ap.add_argument("--config", default=None,
                    help="optional JSON with overrides (port_overrides, machine_overrides, rate_overrides, "
                         "pipe_capacity, ...)")
    ap.add_argument("--time", type=float, default=300, help="time budget in seconds (default 300)")
    ap.add_argument("--slack", type=int, default=1,
                    help="extra corridor tiles around every machine group to start from (default 1); "
                         "unused space is removed again by tightening/compaction")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--wire-weight", type=float, default=1.0,
                    help="placement trade-off: area vs. estimated pipe length (default 1.0)")
    ap.add_argument("--allow-mixed-crossing", action="store_true",
                    help="let normal pipes share/cross tiles with large fluid pipes (the game has no such "
                         "intersection, so this is off by default)")
    ap.add_argument("--quantum-jump", type=int, default=3,
                    help="max tiles a pipe may hop over other pipes via quantum piping (default 3, 0 = off)")
    ap.add_argument("--mineshaft-spacing", type=float, default=None,
                    help="minimum distance between mineshaft drills in tiles (default 48)")
    ap.add_argument("--spacing-measure", choices=("edge", "center"), default=None,
                    help="edge: empty tiles between footprints along x or y (default, strictest); "
                         "center: straight-line distance between machine centres")
    ap.add_argument("--no-modules", action="store_true",
                    help="do not group connected machines into modules (one block per recipe)")
    ap.add_argument("--out", default="output", help="output directory")
    args = ap.parse_args(argv)

    cfg = {}
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)

    if args.mineshaft_spacing is not None:
        cfg.setdefault("min_spacing", {})["m_mineshaft_drill"] = args.mineshaft_spacing
    if args.spacing_measure:
        cfg["spacing_measure"] = args.spacing_measure

    log_lines = []

    def log(msg):
        log_lines.append(msg)
        print(msg, flush=True)

    problem = load_problem(args.save, args.machines, args.recipes, cfg)
    for w in problem.warnings:
        log(f"WARNING: {w}")
    inferred = [n for n in problem.nodes if not n.known]
    if inferred:
        log(f"{len(inferred)} recipe(s) not in recipes.json, ports inferred (see report): "
            + ", ".join(n.recipe_id for n in inferred))

    layout, _ = optimize(problem, time_budget=args.time, seed=args.seed, wire_weight=args.wire_weight,
                         router_kw={"mixed_crossing": args.allow_mixed_crossing, "jump": args.quantum_jump},
                         use_modules=not args.no_modules, slack=args.slack, log=log)

    os.makedirs(args.out, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.save))[0]
    svg = os.path.join(args.out, base + "_layout.svg")
    js = os.path.join(args.out, base + "_layout.json")
    rep = os.path.join(args.out, base + "_report.md")
    title = f"{base} - optimized layout"
    render_svg(problem, layout, svg, title, args.allow_mixed_crossing)
    export_json(problem, layout, js)
    write_report(problem, layout, rep, log_lines)
    x0, y0, x1, y1 = layout.bbox
    print(f"\nFootprint {x1 - x0} x {y1 - y0} = {(x1 - x0) * (y1 - y0):,} tiles "
          f"({'fully routed' if layout.ok else 'NOT fully routed'})")
    print(f"Wrote {svg}\n      {js}\n      {rep}")
    return 0 if layout.ok else 2


if __name__ == "__main__":
    sys.exit(main())
