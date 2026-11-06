# Industrialist layout optimizer

Takes a save from the [Industrialist Production Calculator](https://github.com/Tullysaurus/Industrialist-Production-Calculator)
(the web app, included as a submodule) and packs its machines into the smallest footprint it can, with every
pipe and conveyor routed tile by tile. A desktop viewer shows the result with flows, connections, splits
and the same dashboard numbers as the web app.

This builds on the web app, it does not replace it: plan your factory there, export the save, lay it out here.

## Usage

```bash
pip install PySide6          # only needed for the viewer
python layout.py "8CPP-final_(Imported)_save.json" --time 300 --out output
python viewer.py "output/8CPP-final_(Imported)_save_layout.json"
```

`layout.py` writes three files to `--out`:

| file | what |
| --- | --- |
| `*_layout.json` | everything the viewer needs (machines, ports, pipes with per-segment flows, junctions, valves, stats) |
| `*_layout.svg` | static picture with flow arrows, connection markers and hover tooltips |
| `*_report.md` | stats, even-split check, valve settings, warnings and assumptions |

Useful options: `--time` (seconds, default 300), `--no-valves`, `--valve-check-time`, `--quantum-jump`,
`--mineshaft-spacing`, `--config overrides.json`, `--view` (open the viewer when done).

## Viewer

* Left: the web app's **Production Stats** (MV/HV power use and output, net pollution, profit, machine cost,
  machine space, model count), **Layout** stats, the **Even-split check**, **More Stats**
  (shortages / excesses from the planner), all machine groups and warnings. Entries are clickable.
* Hover any tile: every pipe on it with its flow and direction, splits / joins / intersections with each
  input and output value, which machine port it feeds, valve settings.
* Click a machine: its recipe card (inputs green, outputs red, rates, temperatures, ports) and its pipes
  highlighted. Click a pipe: every connection and every split / join on it.
* Toolbar: flow mode (planned, as built with valves, plain even splits), /s /min /h, toggle arrows,
  connection markers and labels, search. `F` fits, `Esc` clears the selection.

## How it works

* **Rates** come from `indlayout/planner.py`, a Python port of the web app's flow pipeline: recipe
  resolution, max-flow allocation per product, flow-weighted temperature propagation and the dashboard
  numbers. Special recipes (coal power plant, heat exchangers, modular turbine, steam condenser, mineshaft
  drill, polisher, tree farm, air separation unit, chemical plant, cooling tower) are ported in
  `indlayout/special.py`. A recipe that is neither in `recipes.json` nor ported falls back to inferred ports
  and unknown rates and is flagged in the report - port it in `special.py` when a save needs it.
* **Self-feeds** (a machine output connected to its own input) are handled inside the machine: no pipe.
* **Even splitting**: a pipe split shares its inflow evenly between the open directions, and a machine only
  runs as fast as its scarcest input. `indlayout/flows.py` replays the routed layout with those rules. If a
  split would starve machines, the affected networks are rebuilt as a **valve manifold**: 3x1 fluid/item
  valve controls (in at one end, straight out at the other, side out of the middle) whose side outlets
  each feed one consumer with its exact planned share. The layout is then optimized again with the valves
  as pieces, and the report lists each valve's percentage. Large pipes have no valves.
* **Pipe adapters**: a network joining 1-wide and 2-wide fluid ports goes through an 8x8 adapter.

## Assumptions to check

* Valve port positions (in at one end, side outlet from the middle) and adapter port positions (large port
  on one side, small port opposite) are not in the game data and were assumed.
* Pipe capacities default to 120/s (items and normal fluid pipes) and 12,000/s (large fluid pipes); change
  them with `pipe_capacity` in a `--config` file.
* The even-split check assumes outputs drain (excess backs up in the pipe but does not slow the machine)
  and that raw sources produce exactly the planned amount.
