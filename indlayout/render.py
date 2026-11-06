"""SVG / JSON / text output for a finished layout."""
from __future__ import annotations

import colorsys
import hashlib
import json
from collections import defaultdict
from html import escape

S = 12  # px per tile

PORT_COLORS = {("input", "Item"): "#f2b705", ("output", "Item"): "#e8590c",
               ("input", "Fluid"): "#1c7ed6", ("output", "Fluid"): "#9c36b5"}


def _hue(key: str, sat=0.65, light=0.45):
    h = int(hashlib.md5(key.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hls_to_rgb(h, light, sat)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _fill(key: str):
    return _hue(key, 0.35, 0.86)


def render_svg(problem, layout, path, title="Factory layout", mixed_crossing=False):
    x0, y0, x1, y1 = layout.bbox
    pad = 2
    vx0, vy0 = x0 - pad, y0 - pad
    W = (x1 - x0 + 2 * pad) * S
    H = (y1 - y0 + 2 * pad) * S
    header = 150
    legend_w = 420
    total_w, total_h = W + legend_w, max(H + header, 900)
    out = []
    a = out.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}" '
      f'viewBox="0 0 {total_w} {total_h}" font-family="Segoe UI, Helvetica, Arial, sans-serif">')
    a('<defs>'
      f'<pattern id="g1" width="{S}" height="{S}" patternUnits="userSpaceOnUse">'
      f'<path d="M {S} 0 L 0 0 0 {S}" fill="none" stroke="#e3e6ea" stroke-width="0.6"/></pattern>'
      f'<pattern id="g10" width="{S * 10}" height="{S * 10}" patternUnits="userSpaceOnUse">'
      f'<rect width="{S * 10}" height="{S * 10}" fill="url(#g1)"/>'
      f'<path d="M {S * 10} 0 L 0 0 0 {S * 10}" fill="none" stroke="#c5cad1" stroke-width="1"/></pattern>'
      '</defs>')
    a(f'<rect width="{total_w}" height="{total_h}" fill="#ffffff"/>')

    # ---- header
    sol = layout
    overfull = set(sol.overfull(mixed_crossing))
    all_cells = set().union(*sol.cells) if sol.cells else set()
    n_pipe_tiles = len(all_cells)
    machine_tiles = sum(sum(r.w * r.h for r in m["shape"].rects) for m in layout.machines)
    shared = sum(1 for c in all_cells if sol.occ_s.get(c, 0) + sol.occ_l.get(c, 0) >= 2)
    status = "fully routed, all pipe rules satisfied" if layout.ok else \
        f"NOT fully routed - {len(overfull)} overfull tiles (red), {len(sol.failed)} unrouted nets"
    a(f'<text x="16" y="34" font-size="24" font-weight="600" fill="#1f2328">{escape(title)}</text>')
    a(f'<text x="16" y="62" font-size="15" fill="#1f2328">Footprint {x1 - x0} x {y1 - y0} = '
      f'<tspan font-weight="600">{(x1 - x0) * (y1 - y0):,} tiles</tspan> · {len(layout.machines)} machines '
      f'({machine_tiles:,} tiles, {100 * machine_tiles / max(1, (x1 - x0) * (y1 - y0)):.1f}% of area) · '
      f'{len([n for n in problem.nets if not n.stub])} pipe networks, {n_pipe_tiles:,} pipe tiles, '
      f'{shared:,} tiles with 2 pipes</text>')
    a(f'<text x="16" y="86" font-size="15" fill="{"#2b8a3e" if layout.ok else "#c92a2a"}">Status: {status}</text>')
    a('<text x="16" y="110" font-size="13" fill="#57606a">1 grid square = 1 tile; thick lines every 10 tiles. '
      'Hover machines and pipes for details. Large fluid pipes are drawn 2 tiles wide.</text>')

    a(f'<g transform="translate(0,{header})">')
    a(f'<rect x="0" y="0" width="{W}" height="{H}" fill="url(#g10)"/>')
    a(f'<rect x="{pad * S}" y="{pad * S}" width="{(x1 - x0) * S}" height="{(y1 - y0) * S}" fill="none" '
      f'stroke="#495057" stroke-width="2" stroke-dasharray="8 4"/>')

    def X(x):
        return (x - vx0) * S

    def Y(y):
        return (y - vy0) * S

    # ---- machines
    used_ports = defaultdict(set)
    for net in problem.nets:
        for t in net.terminals:
            for p in t.ports:
                used_ports[t.inst].add(p)
    a('<g id="machines">')
    for m in layout.machines:
        node = problem.nodes[m["node"]]
        shape = m["shape"]
        fill = _fill(node.recipe_id)
        tip = (f"{node.name}\nrecipe {node.recipe_id}\nmachine {m['local'] + 1} of {node.count} "
               f"(planner count {node.machine_count:.3f})\nsize {shape.w}x{shape.h}, rotation {m['rot'] * 90}°\n"
               f"position ({m['x'] - x0}, {m['y'] - y0})")
        a(f'<g><title>{escape(tip)}</title>')
        for r in shape.rects:
            a(f'<rect x="{X(m["x"] + r.x):.1f}" y="{Y(m["y"] + r.y):.1f}" width="{r.w * S}" height="{r.h * S}" '
              f'fill="{fill}" stroke="#343a40" stroke-width="1.2" rx="2"/>')
        # labels
        if len(shape.rects) == 1:
            r = shape.rects[0]
            label = node.shape.name if not node.name.startswith(node.shape.name) else node.shape.name
            _label(a, X(m["x"] + r.x), Y(m["y"] + r.y), r.w * S, r.h * S, label, f"#{m['local'] + 1}  {node.recipe_id}")
        else:
            for r in shape.rects:
                if r.w >= 6 and r.h >= 6 and r.machine_id not in ("m_tree",):
                    _label(a, X(m["x"] + r.x), Y(m["y"] + r.y), r.w * S, r.h * S, r.label, None)
            bx, by = X(m["x"]), Y(m["y"])
            a(f'<text x="{bx + 4:.1f}" y="{by + 14:.1f}" font-size="12" font-weight="600" fill="#1f2328">'
              f'{escape(shape.name)} #{m["local"] + 1}</text>')
        # ports
        for pid, p in shape.ports.items():
            col = PORT_COLORS.get((p.direction, p.kind), "#868e96")
            used = pid in used_ports[m["inst"]]
            for (cx, cy) in p.cells:
                a(f'<rect x="{X(m["x"] + cx) + 1.5:.1f}" y="{Y(m["y"] + cy) + 1.5:.1f}" width="{S - 3}" '
                  f'height="{S - 3}" fill="{col}" fill-opacity="{1 if used else 0.3}" '
                  f'stroke="{"#000" if used else "none"}" stroke-width="0.8"><title>{escape(pid)} '
                  f'({p.direction} {p.kind}{", large" if p.width > 1 else ""}{", connected" if used else ", unused"})'
                  f'</title></rect>')
        a('</g>')
    a('</g>')

    # ---- pipes
    a('<g id="pipes" stroke-linecap="round" stroke-linejoin="round" fill="none">')
    order = sorted(range(len(problem.nets)), key=lambda i: not problem.nets[i].large)
    for ni in order:
        net = problem.nets[ni]
        col = _hue(net.product or net.label)
        tip = (f"{net.label}\n{'Large fluid pipe (2x2)' if net.large else net.kind + ' pipe'}"
               f"{' - self-feed stub' if net.stub else ''}\n"
               f"{'flow unknown' if net.flow is None else f'flow {net.flow:.2f}/s'} · capacity {net.capacity:g}/s\n"
               f"{len(net.terminals)} connections, {len(sol.cells[ni])} tiles")
        off = 1.0 if net.large else 0.5
        width = 1.7 * S if net.large else 0.42 * S
        unit = [e for e in sol.net_edges[ni] if abs(e[0][0] - e[1][0]) + abs(e[0][1] - e[1][1]) == 1]
        hops = [e for e in sol.net_edges[ni] if abs(e[0][0] - e[1][0]) + abs(e[0][1] - e[1][1]) > 1]
        segs = _merge_segments(unit)
        d = " ".join(f"M{X(ax + off):.1f} {Y(ay + off):.1f}L{X(bx + off):.1f} {Y(by + off):.1f}"
                     for (ax, ay), (bx, by) in segs)
        a(f'<g><title>{escape(tip)}</title>')
        if d:
            if net.large:
                a(f'<path d="{d}" stroke="#212529" stroke-width="{width + 2.5:.1f}"/>')
            a(f'<path d="{d}" stroke="{col}" stroke-width="{width:.1f}" stroke-opacity="0.92"/>')
        for (ax, ay), (bx, by) in hops:
            # quantum-piping hop: the two bores connect without a pipe in between
            a(f'<path d="M{X(ax + off):.1f} {Y(ay + off):.1f}L{X(bx + off):.1f} {Y(by + off):.1f}" '
              f'stroke="{col}" stroke-width="{max(2.0, width * 0.35):.1f}" stroke-dasharray="3 3">'
              f'<title>quantum-piping hop over other pipes</title></path>')
            for (qx, qy) in ((ax, ay), (bx, by)):
                a(f'<circle cx="{X(qx + off):.1f}" cy="{Y(qy + off):.1f}" r="{S * (0.5 if net.large else 0.32):.1f}" '
                  f'fill="#fff" stroke="{col}" stroke-width="2"/>')
        for (cx, cy) in sol.net_nodes[ni]:
            if net.stub or not sol.net_edges[ni]:
                sz = 2 if net.large else 1
                a(f'<rect x="{X(cx) + 2:.1f}" y="{Y(cy) + 2:.1f}" width="{sz * S - 4}" height="{sz * S - 4}" '
                  f'fill="{col}" stroke="#212529" stroke-width="1"/>')
        a('</g>')
    a('</g>')

    # ---- shared / overfull tile markers
    a('<g id="markers">')
    for c in all_cells:
        cx, cy = c
        if c in overfull:
            a(f'<rect x="{X(cx)}" y="{Y(cy)}" width="{S}" height="{S}" fill="#fa5252" fill-opacity="0.55" '
              f'stroke="#c92a2a"><title>overfull tile: {sol.occ_s.get(c, 0)} normal + {sol.occ_l.get(c, 0)} '
              f'large pipes</title></rect>')
        elif sol.occ_s.get(c, 0) + sol.occ_l.get(c, 0) >= 2:
            a(f'<rect x="{X(cx) + 2.5}" y="{Y(cy) + 2.5}" width="{S - 5}" height="{S - 5}" fill="none" '
              f'stroke="#212529" stroke-width="0.9" transform="rotate(45 {X(cx) + S / 2} {Y(cy) + S / 2})">'
              f'<title>2 pipes in this tile (intersection / dual pipe)</title></rect>')
    a('</g>')
    a('</g>')

    # ---- legend
    lx = W + 20
    ly = header
    a(f'<g transform="translate({lx},{ly})" font-size="13" fill="#1f2328">')
    a('<text y="0" font-size="16" font-weight="600">Legend</text>')
    yy = 24
    for (d, k), col in PORT_COLORS.items():
        a(f'<rect x="0" y="{yy - 10}" width="12" height="12" fill="{col}" stroke="#000" stroke-width="0.8"/>'
          f'<text x="20" y="{yy}">{k} {d} port</text>')
        yy += 20
    a(f'<rect x="0" y="{yy - 10}" width="12" height="12" fill="#adb5bd" fill-opacity="0.3"/>'
      f'<text x="20" y="{yy}">unused port (faded)</text>')
    yy += 22
    a(f'<line x1="0" y1="{yy - 4}" x2="40" y2="{yy - 4}" stroke="#495057" stroke-width="{0.42 * S}" '
      f'stroke-linecap="round"/><text x="50" y="{yy}">normal pipe / conveyor (1 tile)</text>')
    yy += 24
    a(f'<line x1="0" y1="{yy - 4}" x2="40" y2="{yy - 4}" stroke="#212529" stroke-width="{1.7 * S + 2.5}"/>'
      f'<line x1="0" y1="{yy - 4}" x2="40" y2="{yy - 4}" stroke="#868e96" stroke-width="{1.7 * S}"/>'
      f'<text x="50" y="{yy}">large fluid pipe (2x2 tiles)</text>')
    yy += 26
    a(f'<rect x="3" y="{yy - 10}" width="8" height="8" fill="none" stroke="#212529" '
      f'transform="rotate(45 7 {yy - 6})"/><text x="20" y="{yy}">tile holding 2 pipes</text>')
    yy += 20
    a(f'<rect x="0" y="{yy - 10}" width="12" height="12" fill="#fa5252" fill-opacity="0.55"/>'
      f'<text x="20" y="{yy}">overfull tile (rule broken)</text>')
    yy += 30
    a('<text font-size="15" font-weight="600" y="%d">Products</text>' % yy)
    yy += 20
    seen = {}
    for net in problem.nets:
        key = net.product or net.label
        if key in seen:
            continue
        seen[key] = 1
        name = net.label.split(" [")[0].replace(" (self-feed stub)", "")
        recips = sorted({problem.nodes[problem.instances[t.inst][0]].recipe_id for t in net.terminals})
        a(f'<rect x="0" y="{yy - 10}" width="24" height="10" fill="{_hue(key)}"/>'
          f'<text x="32" y="{yy}">{escape(name)}{" (large)" if net.large else ""}'
          f'<title>{escape(", ".join(recips))}</title></text>')
        yy += 17
    yy += 16
    a('<text font-size="15" font-weight="600" y="%d">Machines</text>' % yy)
    yy += 20
    for node in problem.nodes:
        a(f'<rect x="0" y="{yy - 10}" width="12" height="12" fill="{_fill(node.recipe_id)}" stroke="#343a40"/>'
          f'<text x="20" y="{yy}">{node.count} x {escape(node.shape.name)} '
          f'<tspan fill="#57606a">({node.recipe_id}{", inferred" if not node.known else ""})</tspan></text>')
        yy += 17
    a('</g>')
    a('</svg>')
    if yy + header + 20 > total_h:
        out[0] = out[0].replace(f'height="{total_h}"', f'height="{yy + header + 20}"').replace(
            f'viewBox="0 0 {total_w} {total_h}"', f'viewBox="0 0 {total_w} {yy + header + 20}"')
        out[2] = out[2].replace(f'height="{total_h}"', f'height="{yy + header + 20}"')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def _label(a, x, y, w, h, text, sub):
    fs = max(5.0, min(h * 0.28, w / max(4, len(text)) * 1.7, 22))
    cx, cy = x + w / 2, y + h / 2
    if sub and h > fs * 2.6:
        a(f'<text x="{cx:.1f}" y="{cy - fs * 0.15:.1f}" font-size="{fs:.1f}" text-anchor="middle" '
          f'font-weight="600" fill="#1f2328">{escape(text)}</text>')
        fs2 = max(4.0, min(fs * 0.62, w / max(4, len(sub)) * 1.7))
        a(f'<text x="{cx:.1f}" y="{cy + fs2 * 1.2:.1f}" font-size="{fs2:.1f}" text-anchor="middle" '
          f'fill="#495057">{escape(sub)}</text>')
    else:
        a(f'<text x="{cx:.1f}" y="{cy + fs * 0.35:.1f}" font-size="{fs:.1f}" text-anchor="middle" '
          f'font-weight="600" fill="#1f2328">{escape(text)}</text>')


def _merge_segments(edges):
    """Merge unit edges into straight runs to keep the SVG small."""
    adj = defaultdict(set)
    for a_, b_ in edges:
        adj[a_].add(b_)
        adj[b_].add(a_)
    done = set()
    segs = []
    for a_, b_ in edges:
        if (a_, b_) in done or (b_, a_) in done:
            continue
        dx, dy = b_[0] - a_[0], b_[1] - a_[1]
        start, end = a_, b_
        done.add((a_, b_))
        while True:  # extend forward
            n = (end[0] + dx, end[1] + dy)
            if n in adj[end] and (end, n) not in done and (n, end) not in done:
                done.add((end, n))
                end = n
            else:
                break
        while True:  # extend backward
            p = (start[0] - dx, start[1] - dy)
            if p in adj[start] and (p, start) not in done and (start, p) not in done:
                done.add((p, start))
                start = p
            else:
                break
        segs.append((start, end))
    return segs


def export_json(problem, layout, path):
    x0, y0, x1, y1 = layout.bbox
    data = {
        "footprint": {"width": x1 - x0, "height": y1 - y0, "area": (x1 - x0) * (y1 - y0)},
        "fully_routed": layout.ok,
        "machines": [],
        "pipes": [],
    }
    for m in layout.machines:
        node = problem.nodes[m["node"]]
        data["machines"].append({
            "recipe": node.recipe_id, "name": node.shape.name, "index": m["local"] + 1,
            "x": m["x"] - x0, "y": m["y"] - y0, "width": m["shape"].w, "height": m["shape"].h,
            "rotation_deg": m["rot"] * 90,
            "parts": [{"machine": r.machine_id, "x": m["x"] + r.x - x0, "y": m["y"] + r.y - y0,
                       "width": r.w, "height": r.h} for r in m["shape"].rects] if len(m["shape"].rects) > 1 else None,
        })
    for ni, net in enumerate(problem.nets):
        data["pipes"].append({
            "label": net.label, "product": net.product, "kind": net.kind, "large": net.large, "stub": net.stub,
            "flow_per_s": net.flow, "capacity_per_s": net.capacity,
            "tiles": sorted([[c[0] - x0, c[1] - y0] for c in layout.cells[ni]]),
            "segments": [[[a_[0] - x0, a_[1] - y0], [b_[0] - x0, b_[1] - y0]]
                         for a_, b_ in layout.net_edges[ni]],
            "routed": ni not in layout.failed,
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def write_report(problem, layout, path, log_lines):
    x0, y0, x1, y1 = layout.bbox
    lines = ["# Layout report", "",
             f"Footprint: {x1 - x0} x {y1 - y0} = {(x1 - x0) * (y1 - y0):,} tiles",
             f"Fully routed: {'yes' if layout.ok else 'NO'}", ""]
    lines.append("## Machines")
    for n in problem.nodes:
        lines.append(f"- {n.count} x {n.shape.name} ({n.recipe_id}, planner {n.machine_count:.4f}, "
                     f"{n.shape.w}x{n.shape.h}){'' if n.known else '  <- recipe not in recipes.json, inferred'}")
    lines += ["", "## Warnings"] + [f"- {w}" for w in problem.warnings] or ["- none"]
    lines += ["", "## Assumptions / inferred data (check these!)"] + [f"- {n}" if not n.startswith("  ") else f"    - {n.strip()}" for n in problem.notes]
    lines += ["", "## Optimizer log", "```"] + log_lines + ["```"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
