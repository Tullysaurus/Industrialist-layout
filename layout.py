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

from indlayout.flows import Analysis, analyse
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
    ap.add_argument("--no-valves", action="store_true",
                    help="do not add valve controls where even pipe splits would starve machines")
    ap.add_argument("--valve-check-time", type=float, default=None,
                    help="seconds for the quick first layout used to find splits that need valves "
                         "(default: 20%% of --time, 30-120 s)")
    ap.add_argument("--view", action="store_true", help="open the result in the desktop viewer when done")
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
        log(f"{len(inferred)} recipe(s) neither in recipes.json nor ported as special recipes, ports inferred "
            f"(see report): " + ", ".join(n.recipe_id for n in inferred))

    router_kw = {"mixed_crossing": args.allow_mixed_crossing, "jump": args.quantum_jump}
    opt_kw = dict(seed=args.seed, wire_weight=args.wire_weight, router_kw=router_kw,
                  use_modules=not args.no_modules, slack=args.slack, log=log)
    budget = args.time
    if not args.no_valves:
        # pass 1: quick layout, then replay it with even splitting to see which splits starve machines
        t1 = args.valve_check_time or min(120.0, max(30.0, 0.2 * budget))
        t1 = min(t1, 0.5 * budget)
        log(f"Pass 1 ({t1:.0f}s): quick layout to check pipe splits")
        quick, _ = optimize(problem, time_budget=t1, **opt_kw)
        check = Analysis(problem, quick).analyse()
        keys = sorted({problem.nets[ni].key for ni in check.valve_nets if problem.nets[ni].key})
        loss = [(problem.nodes[ni].name, plan, act) for ni, plan, act, _ in check.groups if act < plan * 0.995]
        if keys:
            log(f"  even splitting would starve {len(loss)} machine group(s), e.g. "
                + "; ".join(f"{n} {100 * a / p:.0f}% of plan" for n, p, a in loss[:4]))
            log(f"  -> building {len(keys)} pipe network(s) as valve manifolds: "
                + ", ".join(k.split("|")[0] for k in keys))
            cfg["valve_nets"] = keys
            problem = load_problem(args.save, args.machines, args.recipes, cfg)
        else:
            log("  every split works with even splitting - no valves needed")
        budget = max(30.0, budget - t1)
    layout, _ = optimize(problem, time_budget=budget, **opt_kw)
    analysis = analyse(problem, layout, valves=not args.no_valves)
    for ni, plan, act, act_v in analysis.groups:
        if act_v < plan * 0.995:
            log(f"WARNING: {problem.nodes[ni].name} runs at {100 * act_v / max(plan, 1e-9):.0f}% of plan "
                f"in the built layout (even-split check)")

    os.makedirs(args.out, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.save))[0]
    svg = os.path.join(args.out, base + "_layout.svg")
    js = os.path.join(args.out, base + "_layout.json")
    rep = os.path.join(args.out, base + "_report.md")
    title = f"{base} - optimized layout"
    render_svg(problem, layout, svg, title, args.allow_mixed_crossing, analysis)
    export_json(problem, layout, js, analysis, title)
    write_report(problem, layout, rep, log_lines, analysis)
    x0, y0, x1, y1 = layout.bbox
    print(f"\nFootprint {x1 - x0} x {y1 - y0} = {(x1 - x0) * (y1 - y0):,} tiles "
          f"({'fully routed' if layout.ok else 'NOT fully routed'})")
    print(f"Wrote {svg}\n      {js}\n      {rep}")
    print(f"View it with:  python viewer.py \"{js}\"")
    if args.view:
        from viewer import main as view_main
        view_main([js])
    return 0 if layout.ok else 2


if __name__ == "__main__":
    sys.exit(main())
